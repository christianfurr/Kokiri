/* CPU-only fixture: extracted production storage functions, fake texture owners,
 * and the original sweep's exact predicate. No Metal device or gameplay. */
#import <Foundation/Foundation.h>
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <time.h>
#include "nvn_hmap.h"

@protocol MTLTexture @end
@interface Texture : NSObject <MTLTexture> { @public uint64_t identity; } @end
static uint64_t created, destroyed;
@implementation Texture
- (instancetype)init {self=[super init];if(self)created++;return self;}
- (void)dealloc { destroyed++; }
@end

// STORAGE_TYPES
static pthread_mutex_t g_smu = PTHREAD_MUTEX_INITIALIZER;
static nvn_hmap g_by_storage = {.klen=sizeof(stor_key)}, g_stor_of_obj = {.klen=8}, g_by_serial = {.klen=8};
static stor_ent **g_stor_det;
static int g_stor_ndet;
static uint64_t g_fence, g_stor_swept, g_stor_entries, g_stor_sweep_next = UINT64_MAX;
static _Atomic uint64_t g_storage_revision;
static uint64_t probe_scanned, retirement_digest = 1469598103934665603ull, retirement_count;
static uint64_t deferred_digest = 1469598103934665603ull, deferred_count;
static int64_t serial_ref_balance;
static uint64_t serial_unrefs;
#define STOR_IDLE_SUBMITS 600
#define MDIE(...) abort()
#define MLOG(...) ((void)0)
#define BOTW_SERIAL_NOTE(...) ((void)0);
#define descriptor_profile_storage(...) ((void)0)
static uint64_t obj_key(id o) { return (uint64_t)(uintptr_t)(__bridge void *)o; }
static void ser_bump_locked(uint64_t serial) {(void)serial;}
static int pool_incremental(void) {return 1;}
// Count the stub boundary; this fixture does not model parent/view serial maps.
static void serial_resource_ref(id object, int delta) {
    (void)object;serial_ref_balance+=delta;assert(serial_ref_balance>=0);
    if(delta<0)serial_unrefs++;
}
static id hm_get_id(nvn_hmap *map, const uint64_t *key) {return (__bridge id)nvn_hm_get(map,key);}
static void hm_del_id(nvn_hmap *map, const uint64_t *key) {void *p=nvn_hm_del(map,key);if(p)CFRelease(p);}
static uint64_t mix(uint64_t hash,uint64_t word) {return (hash^word)*1099511628211ull;}
static NSMutableArray *pending;
static void defer_obj_release(id object) {
    @autoreleasepool {
    Texture *texture=object;
    deferred_digest=mix(mix(deferred_digest,texture->identity),g_fence+1);deferred_count++;
    [pending addObject:@[object,@(g_fence+1)]];
    }
}
static void defer_obj_unref(id object) {defer_obj_release(object);}
static void drain(uint64_t done) {
    @autoreleasepool {
    for(NSInteger i=(NSInteger)pending.count-1;i>=0;i--)
        if([pending[(NSUInteger)i][1] unsignedLongLongValue]<=done)[pending removeObjectAtIndex:(NSUInteger)i];
    }
}
typedef struct {stor_key key;} tex_t;
static int stor_on(void) {return 1;}
static int stor_key_of(const tex_t *t,stor_key *out) {*out=t->key;return 1;}
// STORAGE_FUNCTIONS

static void record_gone(void) {
    // Hash the full identity set and exact fence, independent of pointer placement.
    uint64_t set=0;
    for(NSArray *entry in pending) {
        Texture *texture=entry[0];set+=mix(texture->identity,[entry[1] unsignedLongLongValue]);
    }
    retirement_digest=mix(mix(retirement_digest,g_fence),set);
    retirement_count=g_stor_swept;
}
static stor_ent *find(uint64_t identity) {
    for(uint32_t i=0;i<g_by_storage.cap;i++) {
        stor_ent *e=g_by_storage.vals[i];if(e&&e->k.mem==identity)return e;
    }
    for(int i=0;i<g_stor_ndet;i++)if(g_stor_det[i]->k.mem==identity)return g_stor_det[i];
    return NULL;
}
static void publish(uint64_t identity) {
    if(find(identity))return;
    Texture *texture=[Texture new];texture->identity=identity;
    tex_t t={.key={.mem=identity,.size=4096,.w=8,.h=8,.d=1,.levels=1}};
    stor_publish(&t,texture);
}
static void hold(stor_ent *e) {
    if(e->nser)return;
    e->ser=realloc(e->ser,sizeof *e->ser);e->ser[0]=e->k.mem;e->nser=e->cser=1;
    id object=(__bridge id)e->tex;
    assert(!nvn_hm_put(&g_by_serial,&e->k.mem,(void *)CFBridgingRetain(object)));
    serial_resource_ref(object,1);
}
static void unhold(stor_ent *e) {
    // nser represents CPU ownership, independently from GPU deferral.
    id object=hm_get_id(&g_by_serial,&e->k.mem);
    stor_unref_locked((__bridge id)e->tex,e->k.mem);
    if(object){serial_resource_ref(object,-1);defer_obj_unref(object);hm_del_id(&g_by_serial,&e->k.mem);}
}
static void detach(stor_ent *e) {
    if(nvn_hm_get(&g_by_storage,&e->k)!=e)return;
    nvn_hm_del(&g_by_storage,&e->k);g_stor_det[g_stor_ndet++]=e;
}
static void takeback(stor_ent *e) {
    for(int i=0;i<g_stor_ndet;i++)if(g_stor_det[i]==e) {
        g_stor_det[i]=g_stor_det[--g_stor_ndet];nvn_hm_put(&g_by_storage,&e->k,e);return;
    }
}
static void drop_pool(stor_ent *e) {
    if(nvn_hm_get(&g_by_storage,&e->k)==e)stor_drop_locked(e);
    else for(int i=0;i<g_stor_ndet;i++)if(g_stor_det[i]==e) {
        g_stor_det[i]=g_stor_det[--g_stor_ndet];stor_det_drop_locked(e);break;
    }
}
static void sweep(void) {
#ifdef REFERENCE_SWEEP
    stor_collect_drop(^int(const stor_ent *e){return !e->nser&&g_fence>e->idle_fence+STOR_IDLE_SUBMITS;},&g_stor_swept);
    stor_det_sweep(^int(const stor_ent *e){return !e->nser&&g_fence>e->idle_fence+STOR_IDLE_SUBMITS;},&g_stor_swept);
#else
    stor_sweep(g_fence);
#endif
    record_gone();
}
static uint64_t random_word(uint64_t *state) {*state^=*state<<13;*state^=*state>>7;*state^=*state<<17;return *state;}
int main(void) {@autoreleasepool {@autoreleasepool {
    pending=[NSMutableArray array];g_stor_det=calloc(4096,sizeof *g_stor_det);
    uint64_t started=clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    // Exact boundary and GPU deferral before the randomized ownership route.
    publish(1);stor_ent *first=find(1);hold(first);
    // The original creation deadline must be consumed while still held.
    for(g_fence=1;g_fence<=601;g_fence++)sweep();
    assert(find(1));unhold(first);uint64_t idle=g_fence;
    for(;g_fence<=idle+600;g_fence++)sweep();assert(find(1));
    g_fence=idle+601;sweep();assert(!find(1));
    uint64_t before=destroyed;drain(g_fence);assert(destroyed==before);
    drain(g_fence+1);assert(destroyed>before); // fence+1 retirement remains necessary
    // Recreate releases holders but preserves its previous idle_fence. It can
    // therefore become eligible immediately, after an earlier bound was cleared.
    publish(1000000);stor_ent *recreated=find(1000000);hold(recreated);
    g_fence+=601;sweep();assert(find(1000000));
    g_fence++;uint64_t unrefs=serial_unrefs,defers=deferred_count;
    stor_release_holders_locked(recreated,"recreate");
    assert(serial_unrefs==unrefs+1&&deferred_count==defers+1);
    assert(!nvn_hm_get(&g_by_serial,&recreated->k.mem));sweep();
    assert(!find(1000000));
    for(uint64_t i=2;i<1026;i++){publish(i);hold(find(i));}
    uint64_t state=0x3814ad67;
    for(unsigned step=0;step<120000;step++,g_fence++) {@autoreleasepool {
        // Quiet periods let deadlines expire; bursts exercise ownership changes.
        if(step%2000<200)for(int op=0;op<6;op++) {
            uint64_t value=random_word(&state),identity=2+(value%1024);
            stor_ent *e=find(identity);
            if(!e){publish(identity);continue;}
            switch((value>>16)%7){
                case 0:hold(e);break;
                case 1:unhold(e);break;
                case 2:detach(e);break;
                case 3:takeback(e);break;
                case 4:stor_release_holders_locked(e,"recreate");break;
                case 5:drop_pool(e);break;
                default:break;
            }
        }
        sweep();drain(g_fence>2?g_fence-2:0);
    }}
    for(uint64_t i=2;i<1026;i++){stor_ent *e=find(i);if(e)unhold(e);}
    for(int i=0;i<602;i++,g_fence++)sweep();
    assert(!g_by_storage.n&&!g_stor_ndet&&!g_by_serial.n&&!serial_ref_balance);
    drain(UINT64_MAX);assert(!pending.count);
    printf("retirement_digest=%llu\nretirement_count=%llu\ndeferred_digest=%llu\ndeferred_count=%llu\nslots_scanned=%llu\nfixture_ms=%.3f\n",
        retirement_digest,retirement_count,deferred_digest,deferred_count,probe_scanned,
        (clock_gettime_nsec_np(CLOCK_UPTIME_RAW)-started)/1e6);
    free(g_by_storage.keys);free(g_by_storage.vals);free(g_stor_of_obj.keys);free(g_stor_of_obj.vals);free(g_by_serial.keys);free(g_by_serial.vals);free(g_stor_det);
}assert(created==destroyed);}return 0;}
