/* CPU-only. Never constructs a Metal device or runs downloaded shader code. */
#import <Foundation/Foundation.h>
#include <assert.h>
#include "../third_party/d2r_gfx/gfx/nvn/kokiri_catalog_runtime.h"
@interface NvShader : NSObject { @public char key[80]; int stage; } @end
#include "../third_party/d2r_gfx/gfx/nvn/nvn_pso_skey.h"
#include "../third_party/d2r_gfx/gfx/nvn/kokiri_catalog_pso.h"
_Static_assert(sizeof(pso_skey) == 544, "recorded pipeline ABI changed");

static unsigned checks;
#define CHECK(...) do { ++checks; if (!(__VA_ARGS__)) { fprintf(stderr, "check %u failed: %s:%d %s\n", checks, __FILE__, __LINE__, #__VA_ARGS__); return 1; } } while (0)
int main(int argc, char **argv) {
    @autoreleasepool {
        CHECK(argc == 2);
        NSString *root = @(argv[1]);
        NSString *hash = [@"a" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0];
        NSString *key = [hash stringByAppendingString:@"-bbbbbbbbbbbb_b"];
        NSDictionary *base = @{@"game_id":@"oot", @"game_version":@"131072", @"game_content_sha256":hash,
            @"recipe_format":@"mng-list-v1", @"backend":@"metal", @"shader_chain":@"oot-test-v1", @"translator_sha256":hash,
            @"compiler_sha256":NSNull.null, @"target_sha256":NSNull.null, @"options_sha256":NSNull.null};
        NSDictionary *compiler = @{@"schema":@"kokiri-compiler-identity/1", @"observed":@YES, @"test_fixture":@YES};
        NSDictionary *target = @{@"schema":@"kokiri-target-identity/1", @"observed":@YES, @"test_fixture":@YES};
        NSDictionary *options = @{@"schema":@"kokiri-options-identity/1", @"observed":@YES, @"runtime_sha256":hash};
        NSDictionary *identity = kcr_identity(base, hash, compiler, target, options);
        CHECK(identity && kcr_true(identity[@"valid"]));
        CHECK([identity[@"context_id"] isEqual:kcr_sha(kcr_json(identity[@"context"]))]);
        CHECK(!kcr_identity(base, @"bad", compiler, target, options));
        NSMutableDictionary *bad = [options mutableCopy]; bad[@"runtime_sha256"] = @"bad";
        CHECK(!kcr_identity(base, hash, compiler, target, bad));
        bad = [compiler mutableCopy]; bad[@"observed"] = @1;
        CHECK(!kcr_identity(base, hash, bad, target, options));
        bad = [base mutableCopy]; bad[@"game_content_sha256"] = NSNull.null;
        CHECK(!kcr_identity(bad, hash, compiler, target, options));
        kcr_generation generation = {0}; uint64_t snapshot = 99;
        CHECK(kcr_snapshot(&generation, &snapshot) && snapshot == 0);
        kcr_change_begin(&generation);
        CHECK(!kcr_snapshot_unchanged(&generation, snapshot));
        CHECK(!kcr_snapshot(&generation, &snapshot));
        kcr_change_end(&generation);
        CHECK(kcr_snapshot(&generation, &snapshot) && kcr_snapshot_unchanged(&generation, snapshot));
        kcr_change_begin(&generation); kcr_change_end(&generation);
        CHECK(!kcr_snapshot_unchanged(&generation, snapshot));
        NSDictionary *proof = @{@"stage":@5, @"source_sha256":hash, @"reflection_sha256":hash};
        NSDictionary *handoff = @{@"schema":@"kokiri-catalog-handoff/1", @"context":identity[@"context"],
            @"runtime_sha256":hash, @"catalog_revision":@1, @"rows":@[[@"C\t" stringByAppendingString:key]], @"variants":@{key:proof}};
        /* The callback models independently checked local shader bytes. */
        __block unsigned visits = 0;
        kcr_variant_proof known = ^int(NSString *name, int stage, NSDictionary *p) {
            ++visits; return [name isEqual:key] && stage == 5 && [p isEqual:proof];
        };
        NSData *encoded = kcr_json(handoff); NSUInteger admitted = 0;
        NSString *rows = kcr_handoff(encoded, kcr_sha(encoded), identity, known, &admitted);
        CHECK(admitted == 1 && visits == 1 && [rows isEqual:[NSString stringWithFormat:@"C\t%@\n", key]]);
        CHECK(!kcr_handoff(encoded, hash, identity, known, &admitted) && admitted == 0);
        bad = [identity mutableCopy]; bad[@"valid"] = @NO;
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), bad, known, NULL));
        bad = [identity mutableCopy]; bad[@"runtime_sha256"] = @"different";
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), bad, known, NULL));
        bad = [handoff mutableCopy]; bad[@"catalog_revision"] = @YES; encoded = kcr_json(bad);
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), identity, known, NULL));
        bad = [handoff mutableCopy]; bad[@"rows"] = @[[@"C\t" stringByAppendingString:key], [@"C\t" stringByAppendingString:key]]; encoded = kcr_json(bad);
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), identity, known, NULL));
        bad = [handoff mutableCopy]; bad[@"rows"] = @[@"S\tunsafe\t0"]; encoded = kcr_json(bad);
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), identity, known, NULL));
        encoded = kcr_json(handoff);
        CHECK(!kcr_handoff(encoded, kcr_sha(encoded), identity, ^int(NSString *n, int s, NSDictionary *p) { (void)n;(void)s;(void)p;return 0; }, NULL));
        pso_skey state = {0}; strlcpy(state.vs, key.UTF8String, sizeof state.vs);
        char state_hex[sizeof state * 2 + 1]; pso_skey_hex(&state, state_hex);
        NSDictionary *render_proof = @{@"vs":key, @"fs":@""};
        CHECK(kcr_render_proof(@(state_hex), render_proof));
        state.k.vs = (const void *)1; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        NSString *local_source = [root stringByAppendingPathComponent:@"local.metal"];
        NSString *local_reflection = [root stringByAppendingPathComponent:@"local.json"];
        NSData *local_bytes = [@"synthetic nonshader bytes" dataUsingEncoding:NSUTF8StringEncoding];
        NSData *local_meta = kcr_json(@{@"key":key, @"chain":@"oot-test-v1", @"stage":@"cs"});
        CHECK(kcr_write(local_source, local_bytes) && kcr_write(local_reflection, local_meta));
        NSDictionary *local_proof = @{@"stage":@5, @"source_sha256":kcr_sha(local_bytes), @"reflection_sha256":kcr_sha(local_meta)};
        uint64_t budget = local_bytes.length + local_meta.length;
        CHECK(kcr_local_shader(local_source, local_reflection, key, 5, @"oot-test-v1", local_proof, &budget) && budget == 0);
        CHECK(!kcr_local_shader(local_source, local_reflection, key, 5, @"oot-test-v1", local_proof, &budget) && budget == 0);
        budget = local_meta.length + local_bytes.length - 1;
        CHECK(!kcr_local_shader(local_source, local_reflection, key, 5, @"oot-test-v1", local_proof, &budget));
        CHECK(budget == local_bytes.length - 1);
        CHECK(kcr_write(local_source, [@"changed" dataUsingEncoding:NSUTF8StringEncoding]));
        budget = 1024;
        CHECK(!kcr_local_shader(local_source, local_reflection, key, 5, @"oot-test-v1", local_proof, &budget));
        CHECK(budget == 1024 - local_meta.length - 7);
        /* Two distinct render states reuse one vertex shader. The actual parser
         * runs for each state; the local shader proof runs exactly once. */
        memset(&state, 0, sizeof state); strlcpy(state.vs, key.UTF8String, sizeof state.vs);
        state.k.cfmt[0] = 1; pso_skey_hex(&state, state_hex); NSString *first = @(state_hex);
        state.k.cfmt[0] = 2; pso_skey_hex(&state, state_hex); NSString *second = @(state_hex);
        NSDictionary *vertex_proof = @{@"stage":@0, @"source_sha256":hash, @"reflection_sha256":hash};
        bad = [handoff mutableCopy];
        bad[@"rows"] = @[[ @"R\t" stringByAppendingString:first], [@"R\t" stringByAppendingString:second]];
        bad[@"variants"] = @{first:render_proof, second:render_proof, key:vertex_proof};
        encoded = kcr_json(bad); __block unsigned local_checks = 0;
        CHECK(kcr_handoff(encoded, kcr_sha(encoded), identity, ^int(NSString *name, int stage, NSDictionary *p) {
            if (stage == -1) return kcr_render_proof(name, p);
            ++local_checks; return stage == 0 && [name isEqual:key] && [p isEqual:vertex_proof];
        }, &admitted) && admitted == 2 && local_checks == 1);
        state.k.vs = NULL; state.k.fsfn = (const void *)1; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        state.k.fsfn = NULL; state.k.a2c = PSO_HOST_RECT; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        state.k.a2c = 0; state.merged = 1; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        state.merged = 0; state.fz = 1; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        state.fz = 0; state.vs_stage = 4; pso_skey_hex(&state, state_hex);
        CHECK(!kcr_render_proof(@(state_hex), render_proof));
        NSString *file = [root stringByAppendingPathComponent:@"identity.json"];
        CHECK(kcr_write(file, kcr_json(identity)));
        CHECK([kcr_read(file, KCR_MAX_BYTES) isEqual:kcr_json(identity)]);
        NSString *blocked = [root stringByAppendingPathComponent:@"blocked"];
        CHECK(!mkdir(blocked.fileSystemRepresentation, 0700));
        NSString *receipt = [blocked stringByAppendingPathComponent:@"receipt.json"];
        CHECK(kcr_write(receipt, kcr_json(identity)));
        CHECK(!chmod(blocked.fileSystemRepresentation, 0500));
        CHECK(!kcr_write(receipt, encoded));
        CHECK(kcr_invalidate_receipt(receipt, encoded));
        CHECK(kcr_read(receipt, KCR_MAX_BYTES).length == 0);
        CHECK(!chmod(blocked.fileSystemRepresentation, 0700));
        CHECK(kcr_write(receipt, kcr_json(identity)));
        CHECK(!chmod(receipt.fileSystemRepresentation, 0400) && !chmod(blocked.fileSystemRepresentation, 0500));
        int mutation = 0;
        if (kcr_invalidate_receipt(receipt, encoded)) mutation = 1;
        CHECK(mutation == 0);
        CHECK([kcr_read(receipt, KCR_MAX_BYTES) isEqual:kcr_json(identity)]);
        CHECK(!chmod(blocked.fileSystemRepresentation, 0700) && !chmod(receipt.fileSystemRepresentation, 0600));
        CHECK([kcr_file_sha(file, KCR_MAX_BYTES) isEqual:kcr_sha(kcr_json(identity))]);
        CHECK(!kcr_read(file, 1));
        CHECK(!kcr_file_sha(file, 1));
        NSString *link = [root stringByAppendingPathComponent:@"link.json"];
        CHECK(!symlink(file.fileSystemRepresentation, link.fileSystemRepresentation));
        CHECK(!kcr_read(link, KCR_MAX_BYTES) && !kcr_file_sha(link, KCR_MAX_BYTES));
        CHECK(!kcr_write(link, encoded));
        NSString *dirlink = [root stringByAppendingPathComponent:@"linked-directory"];
        CHECK(!symlink(root.fileSystemRepresentation, dirlink.fileSystemRepresentation));
        CHECK(!kcr_read([dirlink stringByAppendingPathComponent:@"identity.json"], KCR_MAX_BYTES));
        CHECK(!kcr_write([dirlink stringByAppendingPathComponent:@"new.json"], encoded));
        CHECK([kcr_read(file, KCR_MAX_BYTES) isEqual:kcr_json(identity)]);
        printf("%u CPU catalog runtime checks passed\n", checks);
    }
    return 0;
}
