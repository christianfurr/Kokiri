/* Foundation-only control of the production byte-snapshot validator. Synthetic
   MTLB-prefixed bytes are never passed to Metal or claimed to be a library. */
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <CommonCrypto/CommonDigest.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

static int inject_drift;
static ssize_t fixture_read(int fd, void *bytes, size_t length) {
    ssize_t got = read(fd, bytes, length);
    if (got > 0 && inject_drift) {
        inject_drift = 0;
        struct stat st;
        if (fstat(fd, &st)) abort();
        struct timeval times[2] = {{st.st_atimespec.tv_sec, 0}, {st.st_mtimespec.tv_sec + 1, 0}};
        if (futimes(fd, times)) abort();
    }
    return got;
}
/* Substitute only the I/O primitive to deterministically change this fixture's
   mtime after a real read. The validator below is the exact production header. */
#define read fixture_read
#include "../third_party/d2r_gfx/gfx/nvn/nvn_archive_library_snapshot.h"
#undef read
#include "../third_party/d2r_gfx/gfx/nvn/totk_shader_seed.h"
#include "../third_party/d2r_gfx/gfx/nvn/nvn_shader_device_libs.h"

static void require(BOOL ok, NSString *message) {
    if (!ok) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
static NSString *digest(NSData *data) {
    uint8_t hash[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes, (CC_LONG)data.length, hash);
    NSMutableString *hex = [NSMutableString stringWithCapacity:64];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) [hex appendFormat:@"%02x", hash[i]];
    return hex;
}
static void rejects(NSString *path, NSString *directory, NSDictionary *files, BOOL source) {
    NSError *error = nil; int payload = 0;
    dispatch_data_t snapshot = archive_library_snapshot(path, directory, files, &error, &payload);
    require(!snapshot && error && payload == source, @"negative snapshot case was accepted or misclassified");
}
int main(int argc, const char **argv) {
    @autoreleasepool {
        require(argc == 2, @"usage: archive-library-snapshot <new-owned-fixture-directory>");
        require(unsetenv("TOTK_SHADER_DEVICE_LIBS") == 0 && !nvn_shader_device_libs_enabled(getenv("TOTK_SHADER_DEVICE_LIBS")), @"unset device-library mode must be disabled");
        const char *values[] = {"", "0", "1", "01", "true"};
        const int enabled[] = {0, 0, 1, 0, 0};
        for (size_t i = 0; i < sizeof values / sizeof values[0]; i++) {
            require(setenv("TOTK_SHADER_DEVICE_LIBS", values[i], 1) == 0 &&
                    nvn_shader_device_libs_enabled(getenv("TOTK_SHADER_DEVICE_LIBS")) == enabled[i], @"device-library enabled-value semantics changed");
        }
        NSString *root = @(argv[1]); NSFileManager *fm = NSFileManager.defaultManager;
        require(root.isAbsolutePath && ![fm fileExistsAtPath:root], @"fixture root must be new and absolute");
        NSString *directory = [root stringByAppendingPathComponent:@"actual"];
        NSString *other = [root stringByAppendingPathComponent:@"other"];
        require([fm createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil] &&
                [fm createDirectoryAtPath:other withIntermediateDirectories:YES attributes:nil error:nil], @"fixture directory creation failed");
        directory = directory.stringByResolvingSymlinksInPath;
        NSString *name = [[@"" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0] stringByAppendingPathExtension:@"metallib"];
        NSString *path = [directory stringByAppendingPathComponent:name];
        const uint8_t fixture[] = {'M','T','L','B',1,2,3,4};
        NSData *good = [NSData dataWithBytes:fixture length:sizeof fixture];
        require([good writeToFile:path atomically:NO], @"fixture library creation failed");
        NSDictionary *files = @{name:digest(good)}; NSError *error = nil; int payload = 0;
        dispatch_data_t snapshot = archive_library_snapshot(path, directory, files, &error, &payload);
        require(snapshot && !error && !payload, @"valid production snapshot was refused");
        NSData *changed = [@"MTLBdifferent bytes" dataUsingEncoding:NSUTF8StringEncoding];
        require([changed writeToFile:path atomically:NO], @"fixture mutation failed");
        const void *bytes = NULL; size_t length = 0;
        dispatch_data_t mapped = dispatch_data_create_map(snapshot, &bytes, &length);
        require(mapped && length == good.length && !memcmp(bytes, good.bytes, length), @"snapshot changed with its backing file");
        rejects(path, directory, files, NO);                     // changed bytes, same filename
        require([good writeToFile:path atomically:NO], @"fixture restore failed");
        rejects(path, directory, @{}, NO);                       // unlisted filename
        rejects(path, directory, @{name:@"not-a-content-hash"}, NO);
        NSString *outside = [other stringByAppendingPathComponent:name];
        require([good writeToFile:outside atomically:NO], @"outside fixture creation failed");
        rejects(outside, directory, files, NO);                  // correct bytes, wrong directory
        require([fm removeItemAtPath:outside error:nil] && [fm createSymbolicLinkAtPath:outside withDestinationPath:path error:nil], @"symlink fixture failed");
        rejects(outside, directory, files, NO);                  // resolved name matches; O_NOFOLLOW still refuses
        require([fm removeItemAtPath:outside error:nil] && link(path.fileSystemRepresentation, outside.fileSystemRepresentation) == 0, @"hardlink fixture failed");
        error = nil; snapshot = archive_library_snapshot(path, directory, files, &error, &payload);
        require(snapshot && !error, @"stable existing source hardlinks must remain admissible");
        inject_drift = 1;
        rejects(path, directory, files, NO);                     // actual read, matching digest, changed identity
        NSData *source = [@"kernel void synthetic_source() {}" dataUsingEncoding:NSUTF8StringEncoding];
        require([source writeToFile:path atomically:NO], @"source-payload fixture failed");
        rejects(path, directory, @{name:digest(source)}, YES);    // matching SHA cannot admit a source payload
        require([fm removeItemAtPath:path error:nil], @"missing-file fixture failed");
        rejects(path, directory, files, NO);
        require([fm createDirectoryAtPath:path withIntermediateDirectories:NO attributes:nil error:nil], @"directory-file fixture failed");
        rejects(path, directory, files, NO);
        /* Exercise the production read-only seed branch too. Every input is
           synthetic and every mutation below stays in this new fixture root. */
        NSString *seed = [root stringByAppendingPathComponent:@"seed"], *cache = [root stringByAppendingPathComponent:@"cache"];
        require([fm createDirectoryAtPath:seed withIntermediateDirectories:NO attributes:nil error:nil] &&
                [fm createDirectoryAtPath:cache withIntermediateDirectories:NO attributes:nil error:nil], @"seed fixture directory creation failed");
        NSString *sentinel = [cache stringByAppendingPathComponent:@"preserve-complete-cache-extra"];
        require([good writeToFile:sentinel atomically:NO], @"seed fixture sentinel creation failed");
        NSDictionary *before = [fm attributesOfItemAtPath:cache error:nil];
        NSString *entry = [[@"" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0] stringByAppendingPathExtension:@"variants"];
        NSString *manifest = [seed stringByAppendingPathComponent:@"seed-manifest.json"];
        NSDictionary *metadata = @{@"schema":@1, @"chain":@DMSH_CHAIN, @"shaders":@1, @"files":@{entry:digest(good)}};
        require([[NSJSONSerialization dataWithJSONObject:metadata options:0 error:nil] writeToFile:manifest atomically:NO] &&
                [good writeToFile:[seed stringByAppendingPathComponent:entry] atomically:NO], @"seed manifest creation failed");
        error = nil;
        require([totk_seed_import_readonly(seed, cache, &error)[@"available"] boolValue] && !error, @"valid read-only seed was refused");
        NSString *missing = [root stringByAppendingPathComponent:@"must-not-be-created"];
        error = nil;
        require(!totk_seed_import_readonly(seed, missing, &error) && error && ![fm fileExistsAtPath:missing], @"read-only seed created a missing cache");
        error = nil;
        require(!totk_seed_import_readonly(seed, sentinel, &error) && error && [[NSData dataWithContentsOfFile:sentinel] isEqual:good], @"read-only seed admitted or changed a file as its cache");
        NSMutableDictionary *bad = [metadata mutableCopy]; bad[@"chain"] = @"wrong-chain";
        require([[NSJSONSerialization dataWithJSONObject:bad options:0 error:nil] writeToFile:manifest atomically:NO], @"wrong-chain fixture failed");
        error = nil;
        require(!totk_seed_import_readonly(seed, cache, &error) && error, @"read-only seed admitted another chain");
        bad = [metadata mutableCopy]; bad[@"files"] = @{@"../must-not-escape":digest(good)};
        require([[NSJSONSerialization dataWithJSONObject:bad options:0 error:nil] writeToFile:manifest atomically:NO], @"unsafe-entry fixture failed");
        error = nil;
        require(!totk_seed_import_readonly(seed, cache, &error) && error, @"read-only seed admitted an unsafe overlay");
        NSDictionary *after = [fm attributesOfItemAtPath:cache error:nil];
        require([[fm contentsOfDirectoryAtPath:cache error:nil] isEqual:@[@"preserve-complete-cache-extra"]] &&
                [[NSData dataWithContentsOfFile:sentinel] isEqual:good] &&
                [before[NSFileModificationDate] isEqual:after[NSFileModificationDate]] &&
                ![fm fileExistsAtPath:[root stringByAppendingPathComponent:@"must-not-escape"]], @"read-only seed changed cache/evidence");
        printf("{\"validator\":\"production archive_library_snapshot, totk_seed_import_readonly and nvn_shader_device_libs_enabled\",\"positive_cases\":3,\"negative_cases\":13,\"device_library_cases\":6,\"owning_snapshot_unchanged\":true,\"seed_cache_unchanged\":true,\"metal_calls\":0}\n");
    }
    return 0;
}
