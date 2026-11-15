/* Private, leased development entry. Included only by launcher.m, after its
   read-only game_data_in helper. This is not a normal player launch override. */
#pragma once
#include <CommonCrypto/CommonDigest.h>
#include <crt_externs.h>
#include <dirent.h>
#include <limits.h>
#include <math.h>
#include <pwd.h>
#include <stdatomic.h>
#include <sys/resource.h>

static NSString *kokiri_dev_root, *kokiri_dev_session, *kokiri_dev_nonce;
static double kokiri_dev_expires;
static dev_t kokiri_dev_device;
static ino_t kokiri_dev_inode;
static NSDictionary *kokiri_dev_receipt;
static _Atomic int kokiri_dev_slot_ready, kokiri_dev_taken_over;

static BOOL kokiri_dev_hex(id value, NSUInteger length) {
    return [value isKindOfClass:NSString.class] && [value length] == length &&
        [value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location == NSNotFound;
}
static BOOL kokiri_dev_number(id value) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID() && isfinite([value doubleValue]);
}
static BOOL kokiri_dev_schema(id value) { return kokiri_dev_number(value) && [value isEqual:@1]; }
static BOOL kokiri_dev_related(NSString *a, NSString *b) {
    return [a isEqualToString:b] || [a hasPrefix:[b stringByAppendingString:@"/"]] || [b hasPrefix:[a stringByAppendingString:@"/"]];
}
static BOOL kokiri_dev_tree(int directory, unsigned depth, unsigned *remaining) {
    if (depth > 32) return NO;
    int copy = dup(directory);
    DIR *entries = copy >= 0 ? fdopendir(copy) : NULL;
    if (!entries) { if (copy >= 0) close(copy); return NO; }
    BOOL good = YES; struct dirent *entry;
    for (;;) {
        errno=0;entry=readdir(entries);
        if(!entry) { if(errno)good=NO;break; }
        if (!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")) continue;
        if (!*remaining) { good = NO; break; } --*remaining;
        struct stat info;
        if (fstatat(directory,entry->d_name,&info,AT_SYMLINK_NOFOLLOW) || info.st_uid != getuid()) { good = NO; break; }
        if (S_ISREG(info.st_mode)) { if (info.st_nlink != 1) { good = NO; break; } }
        else if (S_ISDIR(info.st_mode)) {
            int child = openat(directory,entry->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            good = child >= 0 && kokiri_dev_tree(child,depth+1,remaining);
            if (child >= 0) close(child);
            if (!good) break;
        } else { good = NO; break; }
    }
    closedir(entries); return good;
}
static NSDictionary *kokiri_dev_json(int directory, const char *name) {
    int fd = openat(directory,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if (fd < 0) return nil;
    struct stat info; NSMutableData *data = [NSMutableData data]; BOOL good = NO;
    if (!fstat(fd,&info) && S_ISREG(info.st_mode) && info.st_uid == getuid() && info.st_nlink == 1 && info.st_size > 0 && info.st_size <= 65536) {
        unsigned char bytes[4096]; ssize_t count;
        while ((count = read(fd,bytes,sizeof bytes)) > 0) {
            [data appendBytes:bytes length:(NSUInteger)count]; if (data.length > 65536) break;
        }
        good = count == 0 && data.length <= 65536;
    }
    close(fd);
    id value = good ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    return [value isKindOfClass:NSDictionary.class] ? value : nil;
}
static BOOL kokiri_dev_lease(NSDictionary *lease, NSString *session, NSString *nonce, double maximum) {
    return kokiri_dev_schema(lease[@"schema"]) && [lease[@"session_id"] isEqual:session] && [lease[@"nonce"] isEqual:nonce] &&
        kokiri_dev_number(lease[@"expires_unix"]) && [lease[@"expires_unix"] doubleValue] > NSDate.date.timeIntervalSince1970 &&
        [lease[@"expires_unix"] doubleValue] <= maximum;
}
static int kokiri_dev_lease_valid(void) {
    @autoreleasepool {
        if (!kokiri_dev_root || NSDate.date.timeIntervalSince1970 >= kokiri_dev_expires) return 0;
        int fd = open(kokiri_dev_root.fileSystemRepresentation,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        if (fd < 0) return 0;
        struct stat info, revoked;
        BOOL same = !fstat(fd,&info) && info.st_dev == kokiri_dev_device && info.st_ino == kokiri_dev_inode &&
            info.st_uid == getuid() && (info.st_mode & 0777) == 0700;
        errno = 0;
        int absent = fstatat(fd,"revoked",&revoked,AT_SYMLINK_NOFOLLOW);
        BOOL active = same && absent < 0 && errno == ENOENT &&
            kokiri_dev_lease(kokiri_dev_json(fd,"lease.json"),kokiri_dev_session,kokiri_dev_nonce,kokiri_dev_expires);
        close(fd); return active;
    }
}
int runtime_kokiri_development_active(void) {
    return atomic_load_explicit(&kokiri_dev_slot_ready,memory_order_acquire) &&
        !atomic_load_explicit(&kokiri_dev_taken_over,memory_order_acquire) && kokiri_dev_lease_valid();
}
int runtime_kokiri_development_nonce_matches(const char *nonce) {
    if (!nonce || !runtime_kokiri_development_active() || strlen(nonce) != 64) return 0;
    const char *expected = kokiri_dev_nonce.UTF8String; unsigned difference = 0;
    for (unsigned i=0;i<64;i++) difference |= (unsigned char)nonce[i] ^ (unsigned char)expected[i];
    return difference == 0;
}
extern void runtime_game_slot_user_takeover(void) __attribute__((weak_import));
void runtime_kokiri_development_user_takeover(void) {
    /* A physical player can take over an already expired/revoked development
       session. Session validation is in-memory; do not require a live lease. */
    if (!kokiri_dev_root) return;
    atomic_store_explicit(&kokiri_dev_taken_over,1,memory_order_release);
    atomic_store_explicit(&kokiri_dev_slot_ready,0,memory_order_release);
    if(runtime_game_slot_user_takeover)runtime_game_slot_user_takeover();
    int directory=open(kokiri_dev_root.fileSystemRepresentation,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0)return;
    struct stat info;
    if(!fstat(directory,&info) && info.st_dev==kokiri_dev_device && info.st_ino==kokiri_dev_inode) {
        int fd=openat(directory,"revoked",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
        if(fd>=0) { (void)write(fd,"physical-user-takeover\n",23);close(fd); }
    }
    close(directory);
}
void runtime_kokiri_development_slot_acquired(void) {
    @autoreleasepool {
    /* Called by loader.c only after the ordinary human-priority slot succeeds.
       Do not infer ownership from an owner label or the configured receipt. */
    if(atomic_load_explicit(&kokiri_dev_taken_over,memory_order_acquire) || !kokiri_dev_lease_valid() || !kokiri_dev_receipt)return;
    int directory=open(kokiri_dev_root.fileSystemRepresentation,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0)return;
    struct stat info;struct rusage_info_v4 usage={0};
    if(fstat(directory,&info) || info.st_dev!=kokiri_dev_device || info.st_ino!=kokiri_dev_inode ||
       proc_pid_rusage(getpid(),RUSAGE_INFO_V4,(rusage_info_t *)&usage) ||
       usage.ri_proc_start_abstime!=[kokiri_dev_receipt[@"process_start"] unsignedLongLongValue]) { close(directory);return; }
    NSMutableDictionary *receipt=[kokiri_dev_receipt mutableCopy];
    receipt[@"game_slot_acquired"]=@YES;receipt[@"phase"]=@"slot-acquired";
    NSData *json=[NSJSONSerialization dataWithJSONObject:receipt options:NSJSONWritingSortedKeys error:nil];
    NSString *temporary=[@".isolation-" stringByAppendingString:NSUUID.UUID.UUIDString];
    int fd=json?openat(directory,temporary.UTF8String,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600):-1;
    if(fd>=0) {
        const unsigned char *bytes=json.bytes;NSUInteger written=0;
        while(written<json.length) { ssize_t count=write(fd,bytes+written,json.length-written);if(count<=0)break;written+=(NSUInteger)count; }
        BOOL complete=written==json.length && !fsync(fd);close(fd);
        if(complete && !renameat(directory,temporary.UTF8String,directory,"isolation.json"))
            atomic_store_explicit(&kokiri_dev_slot_ready,1,memory_order_release);
        unlinkat(directory,temporary.UTF8String,0);
    }
    close(directory);
    }
}
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static NSString *kokiri_dev_hash(NSString *path) {
    int fd = open(path.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if (fd < 0) return nil;
    struct stat info;
    if (fstat(fd,&info) || !S_ISREG(info.st_mode)) { close(fd); return nil; }
    CC_SHA256_CTX context; CC_SHA256_Init(&context);
    unsigned char bytes[65536], digest[CC_SHA256_DIGEST_LENGTH]; ssize_t count;
    while ((count = read(fd,bytes,sizeof bytes)) > 0) CC_SHA256_Update(&context,bytes,(CC_LONG)count);
    close(fd); if (count < 0) return nil;
    CC_SHA256_Final(digest,&context); NSMutableString *hex = [NSMutableString stringWithCapacity:64];
    for (unsigned i=0;i<sizeof digest;i++) [hex appendFormat:@"%02x",digest[i]];
    return hex;
}
#pragma clang diagnostic pop
static BOOL kokiri_dev_set(const char *name, NSString *value) { return value && !setenv(name,value.UTF8String,1); }
static void kokiri_dev_clean_environment(void) {
    /* The parent must also supply a clean environment at spawn: constructors run
       before this branch, notably TOTK_INPUT_SCRIPT in input.c. Keep HOME intact. */
    NSSet *keep = [NSSet setWithArray:@[@"HOME",@"USER",@"LOGNAME",@"LANG",@"LC_ALL",@"__CF_USER_TEXT_ENCODING"]];
    NSMutableArray *remove = [NSMutableArray array];
    for (char **entry=*_NSGetEnviron(); entry && *entry; entry++) {
        const char *equal = strchr(*entry,'='); if (!equal) continue;
        NSString *name = [[NSString alloc] initWithBytes:*entry length:(NSUInteger)(equal-*entry) encoding:NSUTF8StringEncoding];
        if (name && ![keep containsObject:name]) [remove addObject:name];
    }
    for (NSString *name in remove) unsetenv(name.UTF8String);
    setenv("PATH","/usr/bin:/bin:/usr/sbin:/sbin",1);
}
static BOOL kokiri_dev_prepare(NSString *root, NSString *resources, NSString *executable, NSDictionary *bundleInfo, NSDictionary **receipt) {
    if (!root.isAbsolutePath || strlen(root.fileSystemRepresentation) > 768 || [root rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) return NO;
    char canonical[PATH_MAX];
    if (!realpath(root.fileSystemRepresentation,canonical) || ![root isEqualToString:@(canonical)]) return NO;
    for (NSString *path=root; path.length>1; path=path.stringByDeletingLastPathComponent) {
        struct stat part; if (lstat(path.fileSystemRepresentation,&part) || !S_ISDIR(part.st_mode)) return NO;
    }
    struct passwd account, *found=NULL; char accountBuffer[16384];
    if (getpwuid_r(getuid(),&account,accountBuffer,sizeof accountBuffer,&found) || !found || !account.pw_dir) return NO;
    NSString *home = @(account.pw_dir);
    for (NSString *suffix in @[@"Library/Application Support/Kokiri/OcarinaOfTime/profile",@"Library/Application Support/MacNativeGames/OcarinaOfTime/profile"]) {
        NSString *player = [home stringByAppendingPathComponent:suffix];
        if (realpath(player.fileSystemRepresentation,canonical)) player = @(canonical);
        if (kokiri_dev_related(root,player)) return NO;
    }
    const char *claimedRoot=getenv("KOKIRI_DEVELOPMENT_ROOT"), *claimedNonce=getenv("KOKIRI_DEVELOPMENT_NONCE");
    if (!claimedRoot || ![root isEqualToString:@(claimedRoot)] || !claimedNonce) return NO;
    int directory = open(root.fileSystemRepresentation,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if (directory < 0) return NO;
    struct stat info; unsigned remaining=100000;
    BOOL good = !fstat(directory,&info) && info.st_uid==getuid() && (info.st_mode&0777)==0700 && kokiri_dev_tree(directory,0,&remaining);
    NSDictionary *request=good?kokiri_dev_json(directory,"request.json"):nil;
    double expiry=kokiri_dev_number(request[@"expires_unix"])?[request[@"expires_unix"] doubleValue]:0, now=NSDate.date.timeIntervalSince1970;
    good = good && kokiri_dev_schema(request[@"schema"]) && kokiri_dev_hex(request[@"session_id"],32) && kokiri_dev_hex(request[@"nonce"],64) &&
        [request[@"nonce"] isEqualToString:@(claimedNonce)] && kokiri_dev_hex(request[@"executable_sha256"],64) &&
        kokiri_dev_number(request[@"expires_unix"]) && expiry>now && expiry<=now+1800 &&
        kokiri_dev_lease(kokiri_dev_json(directory,"lease.json"),request[@"session_id"],request[@"nonce"],expiry);
    struct stat previous;
    if (!fstatat(directory,"isolation.json",&previous,AT_SYMLINK_NOFOLLOW) || !fstatat(directory,"revoked",&previous,AT_SYMLINK_NOFOLLOW)) good=NO;
    NSString *digest=good?kokiri_dev_hash(executable):nil;
    good = good && [digest isEqual:request[@"executable_sha256"]];
    for (NSString *name in @[@"profile",@"settings",@"settings/game",@"cache",@"logs",@"proof",@"contributions",@"mods",@"tmp",@"captures"]) {
        if (!good) break;
        NSString *path=[root stringByAppendingPathComponent:name];
        if (mkdir(path.fileSystemRepresentation,0700) && errno!=EEXIST) good=NO;
        struct stat child;
        if (lstat(path.fileSystemRepresentation,&child) || !S_ISDIR(child.st_mode) || child.st_uid!=getuid()) good=NO;
    }
    if (good) {
        const char *names[]={"input.txt","status.jsonl"};
        for (unsigned i=0;i<2;i++) {
            int fd=openat(directory,names[i],O_WRONLY|O_CREAT|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
            struct stat file;
            if(fd<0 || fstat(fd,&file) || !S_ISREG(file.st_mode) || file.st_uid!=getuid() || file.st_nlink!=1 || file.st_size!=0) good=NO;
            if(fd>=0)close(fd);
        }
    }
    if (!good) { close(directory); return NO; }
    NSString *profile=[root stringByAppendingPathComponent:@"profile"], *settings=[root stringByAppendingPathComponent:@"settings/game"];
    NSDictionary *paths=@{@"profile":profile,@"settings":settings,@"cache":[root stringByAppendingPathComponent:@"cache"],@"logs":[root stringByAppendingPathComponent:@"logs"],
        @"proof":[root stringByAppendingPathComponent:@"proof"],@"contributions":[root stringByAppendingPathComponent:@"contributions"],@"mods":[root stringByAppendingPathComponent:@"mods"],
        @"input":[root stringByAppendingPathComponent:@"input.txt"],@"status":[root stringByAppendingPathComponent:@"status.jsonl"],@"tmp":[root stringByAppendingPathComponent:@"tmp"]};
    kokiri_dev_clean_environment();
    NSDictionary *environment=@{@"TOTK_PROFILE_DIR":profile,@"TOTK_CONTROLS":[settings stringByAppendingPathComponent:@"controls.txt"],@"TOTK_SHADER_CACHE":paths[@"cache"],
        @"TOTK_ROMFS_PROOF_DIR":paths[@"proof"],@"TOTK_INPUT_FILE":paths[@"input"],@"OOT_EDITOR_STATUS":paths[@"status"],@"TMPDIR":[paths[@"tmp"] stringByAppendingString:@"/"],
        @"OOT_GPU_ERROR_LOG":[paths[@"logs"] stringByAppendingPathComponent:@"gpu-error.log"],@"DM_NVN_TSV":[root stringByAppendingPathComponent:@"timings.tsv"],@"DM_NVN_TSV_CALLS":@"0",
        @"DM_PSO_USER":[profile stringByAppendingPathComponent:@"pso_user.tsv"],@"TOTK_NATIVE_DIR":[resources stringByAppendingPathComponent:@"build"],
        @"TOTK_SHARED_FONTS":[resources stringByAppendingPathComponent:@"extracted/firmware/shared-fonts"],@"TOTK_SCREENSHOT_DIR":[root stringByAppendingPathComponent:@"captures"],
        @"TOTK_PICTURE_MODE":[settings stringByAppendingPathComponent:@"picture-mode.txt"],@"TOTK_VR_SETTINGS":[settings stringByAppendingPathComponent:@"vr.txt"],
        @"TOTK_CAMERA_SETTINGS":[settings stringByAppendingPathComponent:@"camera.txt"],@"TOTK_HEAD_SETTINGS":[settings stringByAppendingPathComponent:@"head.txt"],
        @"TOTK_VR_OFFSET":[settings stringByAppendingPathComponent:@"vr-offset.txt"],@"TOTK_VR_OPTIONS":[settings stringByAppendingPathComponent:@"vr-options.txt"],
        @"TOTK_CLOUD_SAVE_DIR":@"0",@"TOTK_ROMFS_MODS":@"0",@"TOTK_TEXTURE_PACK":@"0",@"MNG_UI_PACK":@"0",
        @"TOTK_FILE_HEAP":@"0",@"OOT_GUEST_FILE":@"0",@"TOTK_OPERATION_MODE":@"docked",@"TOTK_LOCALE":@"en-US",
        @"TOTK_GPU_ALLOW_SUBMIT":@"1",@"TOTK_GPU_WIDEN":@"1",@"TOTK_GPU_BLOCKRT":@"1",@"TOTK_GPU_MIDCLEAR":@"1",
        @"TOTK_SLOT_OWNER":@"kokiri-dev",@"TOTK_SLOT_PURPOSE":@"isolated-development",@"TOTK_GAME_SLOT_WAIT":@"0",
        @"TOTK_AGENT_LIMIT_S":[NSString stringWithFormat:@"%.0f",fmax(1,ceil(expiry-NSDate.date.timeIntervalSince1970))],@"TOTK_AGENT_GRACE_S":@"0",@"TOTK_AGENT_IDLE_S":@"300",
        @"TOTK_GAME_SLOT_DIR":[home stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/TOTK/game-slot"],
        @"KOKIRI_DEVELOPMENT_ROOT":root,@"KOKIRI_DEVELOPMENT_NONCE":request[@"nonce"]};
    for(NSString *key in environment) if(!kokiri_dev_set(key.UTF8String,environment[key])) { close(directory); return NO; }
    NSString *source=bundleInfo[@"KokiriSourceCommit"]; if([source isKindOfClass:NSString.class])kokiri_dev_set("TOTK_SOURCE_COMMIT",source);
    struct rusage_info_v4 usage={0};
    if(proc_pid_rusage(getpid(),RUSAGE_INFO_V4,(rusage_info_t *)&usage)) { close(directory); return NO; }
    *receipt=@{@"schema":@1,@"isolation_version":@1,@"session_id":request[@"session_id"],@"nonce":request[@"nonce"],@"pid":@(getpid()),
        @"process_start":@(usage.ri_proc_start_abstime),@"executable":executable,@"executable_sha256":digest,@"effective_paths":paths,
        @"stdout_path":[root stringByAppendingPathComponent:@"game-full.log"],@"phase":@"configured",@"game_slot_acquired":@NO,
        @"expires_unix":@(expiry),@"pipeline_archives":@"normal policy; private archive-helper lock and cleanup paths",@"os_managed_caches":@"outside application isolation boundary"};
    kokiri_dev_root=[root copy];kokiri_dev_session=[request[@"session_id"] copy];kokiri_dev_nonce=[request[@"nonce"] copy];
    kokiri_dev_expires=expiry;kokiri_dev_device=info.st_dev;kokiri_dev_inode=info.st_ino;
    kokiri_dev_receipt=[(*receipt) copy];
    close(directory); return YES;
}
static int kokiri_development_launch(int argc,char **argv,char ***boot) {
    if(argc!=3) { fprintf(stderr,"[kokiri-development] expected one private root\n"); return 1; }
    NSString *root=@(argv[2]), *resources=[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"totk"];
    char executable[PROC_PIDPATHINFO_MAXSIZE];
    if(proc_pidpath(getpid(),executable,sizeof executable)<=0) return 1;
    NSDictionary *receipt=nil;
    if(!kokiri_dev_prepare(root,resources,@(executable),NSBundle.mainBundle.infoDictionary,&receipt)) {
        fprintf(stderr,"[kokiri-development] invalid or expired isolated session request\n");return 1;
    }
    NSString *binary=[resources stringByAppendingPathComponent:@"rewritten/" TOTK_GAME_DIR "/main.patched.bin"];
    if(access(binary.fileSystemRepresentation,R_OK) || chdir(resources.fileSystemRepresentation)) return 1;
    if(access("extracted/" TOTK_GAME_DIR "/romfs/romfs.bin",R_OK)) {
        /* Only the bundle's pinned library is read. No player defaults or folder picker. */
        NSString *library=[NSBundle.mainBundle objectForInfoDictionaryKey:@"MNGGameDataFolder"];
        if(![library isKindOfClass:NSString.class] || !library.isAbsolutePath) return 1;
        NSString *pins=[NSString stringWithContentsOfFile:@"build/game-data/" TOTK_GAME_DIR "/romfs-config.txt" encoding:NSUTF8StringEncoding error:nil];
        unsigned long long size=0;NSString *sha=@"";
        for(NSString *line in [pins componentsSeparatedByString:@"\n"]) {
            NSArray *parts=[line componentsSeparatedByString:@" "];if(parts.count!=2)continue;
            if([parts[0] isEqual:@"ROMFS_IMAGE_SIZE"])size=strtoull([parts[1] UTF8String],NULL,10);
            if([parts[0] isEqual:@"ROMFS_IMAGE_SHA256"])sha=parts[1];
        }
        library=size?game_data_in(library,size,sha):nil;
        if(!library || !kokiri_dev_set("TOTK_ROMFS_DATA",library))return 1;
    }
    NSData *json=[NSJSONSerialization dataWithJSONObject:receipt options:NSJSONWritingSortedKeys error:nil];
    NSString *ack=[root stringByAppendingPathComponent:@"isolation.json"];
    if(!json || ![json writeToFile:ack options:NSDataWritingWithoutOverwriting error:nil])return 1;
    static char *arguments[4]={NULL,"rewritten/" TOTK_GAME_DIR,"boot",NULL};arguments[0]=argv[0];*boot=arguments;
    return -1;
}
