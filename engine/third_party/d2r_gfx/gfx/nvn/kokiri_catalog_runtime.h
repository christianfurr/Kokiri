/* Kokiri's bounded metadata handoff. No network, shader source or executable
 * download is accepted here. The native shell pins the whole handoff by SHA;
 * the renderer compares its freshly observed identity before retaining rows.
 * Foundation-only helpers are exercised without a Metal device in CPU tests. */
#pragma once
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#import <CoreFoundation/CoreFoundation.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <stdatomic.h>

#define KCR_MAX_ROWS 512u
#define KCR_MAX_BYTES (1024u * 1024u)
typedef struct { _Atomic uint64_t version; _Atomic unsigned writers; } kcr_generation;
static void kcr_change_begin(kcr_generation *state) { atomic_fetch_add(&state->writers, 1); atomic_fetch_add(&state->version, 1); }
static void kcr_change_end(kcr_generation *state) { atomic_fetch_add(&state->version, 1); atomic_fetch_sub(&state->writers, 1); }
static int kcr_snapshot(kcr_generation *state, uint64_t *version) {
    *version = atomic_load(&state->version); return atomic_load(&state->writers) == 0;
}
static int kcr_snapshot_unchanged(kcr_generation *state, uint64_t version) {
    return atomic_load(&state->writers) == 0 && atomic_load(&state->version) == version;
}

static NSString *kcr_sha(NSData *data) {
    if (!data || data.length > UINT32_MAX) return nil;
    unsigned char hash[CC_SHA256_DIGEST_LENGTH]; char text[65] = {0};
    CC_SHA256(data.bytes, (CC_LONG)data.length, hash);
    for (unsigned i = 0; i < sizeof hash; ++i) snprintf(text + i * 2, 3, "%02x", hash[i]);
    return @(text);
}
static int kcr_match(NSString *value, NSString *pattern) {
    if (![value isKindOfClass:NSString.class]) return 0;
    return [value rangeOfString:[NSString stringWithFormat:@"\\A(?:%@)\\z", pattern]
                       options:NSRegularExpressionSearch].location != NSNotFound;
}
static NSData *kcr_json(id value) {
    if (![NSJSONSerialization isValidJSONObject:value]) return nil;
    return [NSJSONSerialization dataWithJSONObject:value
        options:NSJSONWritingSortedKeys | NSJSONWritingWithoutEscapingSlashes error:nil];
}
/* Walk each directory with O_NOFOLLOW; a symlink anywhere in a downloaded
 * candidate path must not turn this into a read of another application. */
static int kcr_parent(NSString *path, NSString **name) {
    if (![path isKindOfClass:NSString.class] || !path.isAbsolutePath || path.length > 4096) return -1;
    NSArray<NSString *> *parts = path.pathComponents;
    if (parts.count < 2) return -1;
    int fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    for (NSUInteger i = 1; fd >= 0 && i + 1 < parts.count; ++i) {
        NSString *part = parts[i];
        if (!part.length || [part isEqual:@"."] || [part isEqual:@".."]) { close(fd); return -1; }
        int next = openat(fd, part.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        close(fd); fd = next;
    }
    NSString *last = parts.lastObject;
    if (!last.length || [last isEqual:@"."] || [last isEqual:@".."]) { if (fd >= 0) close(fd); return -1; }
    if (name) *name = last;
    return fd;
}
static NSData *kcr_read(NSString *path, size_t limit) {
    NSString *name = nil; int parent = kcr_parent(path, &name);
    if (parent < 0) return nil;
    int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    close(parent); if (fd < 0) return nil;
    struct stat before = {0}, after = {0};
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size < 0 || (uint64_t)before.st_size > limit) { close(fd); return nil; }
    NSMutableData *data = [NSMutableData dataWithLength:(NSUInteger)before.st_size];
    size_t at = 0;
    while (at < data.length) {
        ssize_t n = read(fd, (char *)data.mutableBytes + at, data.length - at);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { close(fd); return nil; }
        at += (size_t)n;
    }
    int ok = !fstat(fd, &after) && before.st_ino == after.st_ino && before.st_size == after.st_size &&
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec;
    close(fd); return ok ? data : nil;
}
static NSString *kcr_file_sha_count(NSString *path, uint64_t limit, uint64_t *read_bytes) {
    if (read_bytes) *read_bytes = 0;
    NSString *name = nil; int parent = kcr_parent(path, &name);
    if (parent < 0) return nil;
    int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    close(parent); if (fd < 0) return nil;
    struct stat before = {0}, after = {0};
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size < 0 || (uint64_t)before.st_size > limit) { close(fd); return nil; }
    CC_SHA256_CTX hash; CC_SHA256_Init(&hash);
    unsigned char block[65536]; ssize_t n; uint64_t count = 0;
    for (;;) {
        if (count == limit) { n = 0; break; }
        n = read(fd, block, (size_t)MIN((uint64_t)sizeof block, limit - count));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        count += (uint64_t)n;
        if (read_bytes) *read_bytes = count;
        if (count > limit) { close(fd); return nil; }
        CC_SHA256_Update(&hash, block, (CC_LONG)n);
    }
    int ok = n == 0 && count == (uint64_t)before.st_size && !fstat(fd, &after) &&
        before.st_ino == after.st_ino && before.st_size == after.st_size &&
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec;
    close(fd); if (!ok) return nil;
    unsigned char bytes[32]; char text[65] = {0}; CC_SHA256_Final(bytes, &hash);
    for (unsigned i = 0; i < sizeof bytes; ++i) snprintf(text + i * 2, 3, "%02x", bytes[i]);
    return @(text);
}
static NSString *kcr_file_sha(NSString *path, uint64_t limit) { return kcr_file_sha_count(path, limit, NULL); }
/* Caller explicitly owns/precreates the parent. Never creates a profile or
 * follows a symlink. The destination itself must be absent or a regular file. */
static int kcr_write(NSString *path, NSData *data) {
    if (!data || data.length > KCR_MAX_BYTES) return 0;
    NSString *name = nil; int parent = kcr_parent(path, &name);
    if (parent < 0) return 0;
    struct stat existing = {0};
    if (!fstatat(parent, name.fileSystemRepresentation, &existing, AT_SYMLINK_NOFOLLOW) &&
        (!S_ISREG(existing.st_mode) || existing.st_uid != getuid())) { close(parent); return 0; }
    NSString *temporary = [@".kokiri-identity-" stringByAppendingString:NSUUID.UUID.UUIDString];
    int fd = openat(parent, temporary.fileSystemRepresentation, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) { close(parent); return 0; }
    size_t at = 0;
    while (at < data.length) {
        ssize_t n = write(fd, (const char *)data.bytes + at, data.length - at);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        at += (size_t)n;
    }
    int ok = at == data.length && !fsync(fd); close(fd);
    if (ok) ok = !renameat(parent, temporary.fileSystemRepresentation, parent, name.fileSystemRepresentation);
    if (!ok) unlinkat(parent, temporary.fileSystemRepresentation, 0);
    close(parent); return ok;
}
/* A failed invalidation write must never leave an acceptable old receipt.
 * Removing the owned regular file works without allocating a replacement;
 * truncation is a fallback when the parent is not writable. */
static int kcr_revoke(NSString *path) {
    NSString *name = nil; int parent = kcr_parent(path, &name);
    if (parent < 0) return 0;
    struct stat info = {0};
    if (fstatat(parent, name.fileSystemRepresentation, &info, AT_SYMLINK_NOFOLLOW)) {
        int missing = errno == ENOENT; close(parent); return missing;
    }
    if (!S_ISREG(info.st_mode) || info.st_uid != getuid()) { close(parent); return 0; }
    if (!unlinkat(parent, name.fileSystemRepresentation, 0)) { close(parent); return 1; }
    int fd = openat(parent, name.fileSystemRepresentation, O_WRONLY | O_NOFOLLOW | O_CLOEXEC);
    close(parent); if (fd < 0) return 0;
    struct stat opened = {0};
    int ok = !fstat(fd, &opened) && S_ISREG(opened.st_mode) && opened.st_uid == getuid() &&
        opened.st_dev == info.st_dev && opened.st_ino == info.st_ino && !ftruncate(fd, 0);
    if (ok) (void)fsync(fd);
    close(fd); return ok;
}
static int kcr_invalidate_receipt(NSString *path, NSData *invalid) { return kcr_write(path, invalid) || kcr_revoke(path); }
static NSDictionary *kcr_object(NSData *data) {
    if (!data) return nil;
    id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    return [value isKindOfClass:NSDictionary.class] ? value : nil;
}
static int kcr_fields(NSDictionary *value, NSArray<NSString *> *fields) {
    return [value isKindOfClass:NSDictionary.class] && [[NSSet setWithArray:value.allKeys] isEqual:[NSSet setWithArray:fields]];
}
static int kcr_true(id value) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID() && [value boolValue];
}
static int kcr_local_shader(NSString *source, NSString *reflection, NSString *name, int stage,
                            NSString *chain, NSDictionary *proof, uint64_t *budget) {
    if (!budget || (stage != 0 && stage != 1 && stage != 5)) return 0;
    NSData *reflection_data = kcr_read(reflection, (size_t)MIN(*budget, KCR_MAX_BYTES));
    if (!reflection_data) return 0;
    *budget -= reflection_data.length;
    if (![kcr_sha(reflection_data) isEqual:proof[@"reflection_sha256"]]) return 0;
    NSDictionary *j = kcr_object(reflection_data);
    NSString *kind = stage == 0 ? @"vs" : stage == 1 ? @"ps" : @"cs";
    if (!([j[@"chain"] isEqual:chain] && [j[@"key"] isEqual:name] && [j[@"stage"] isEqual:kind] && !j[@"mesh_stage"])) return 0;
    uint64_t bytes = 0;
    NSString *hash = kcr_file_sha_count(source, *budget, &bytes);
    *budget -= MIN(*budget, bytes);
    return [hash isEqual:proof[@"source_sha256"]];
}
static NSDictionary *kcr_identity(NSDictionary *base, NSString *runtime,
                                 NSDictionary *compiler, NSDictionary *target, NSDictionary *options) {
    NSArray *fields = @[@"game_id", @"game_version", @"game_content_sha256", @"recipe_format", @"backend", @"shader_chain", @"translator_sha256", @"compiler_sha256", @"target_sha256", @"options_sha256"];
    if (!kcr_fields(base, fields) || ![base[@"backend"] isEqual:@"metal"] ||
        ![base[@"recipe_format"] isEqual:@"mng-list-v1"] || !kcr_match(runtime, @"[a-f0-9]{64}")) return nil;
    for (NSString *field in @[@"game_content_sha256", @"translator_sha256"])
        if (!kcr_match(base[field], @"[a-f0-9]{64}")) return nil;
    for (NSString *field in @[@"game_id", @"game_version", @"shader_chain"])
        if (!kcr_match(base[field], @"[a-z0-9][a-z0-9._-]{0,63}")) return nil;
    NSArray *descriptors = @[compiler ?: @{}, target ?: @{}, options ?: @{}];
    NSArray *names = @[@"compiler", @"target", @"options"];
    NSMutableDictionary *context = [base mutableCopy];
    for (NSUInteger i = 0; i < names.count; ++i) {
        NSDictionary *descriptor = descriptors[i];
        if (![descriptor[@"schema"] isEqual:[NSString stringWithFormat:@"kokiri-%@-identity/1", names[i]]] ||
            !kcr_true(descriptor[@"observed"])) return nil;
        NSString *digest = kcr_sha(kcr_json(descriptor)); if (!digest) return nil;
        context[[names[i] stringByAppendingString:@"_sha256"]] = digest;
    }
    if (![options[@"runtime_sha256"] isEqual:runtime]) return nil;
    return @{@"schema": @"kokiri-runtime-identity/1", @"valid": @YES,
        @"context": context, @"context_id": kcr_sha(kcr_json(context)), @"runtime_sha256": runtime,
        @"compiler": compiler, @"target": target, @"options": options};
}
typedef int (^kcr_variant_proof)(NSString *name, int stage, NSDictionary *proof);
/* Rows are retained in memory after validation. Never reopen the candidate
 * path later: changing/deleting a file cannot alter an admitted warm recipe. */
static NSString *kcr_handoff(NSData *data, NSString *expected_sha, NSDictionary *identity,
                             kcr_variant_proof known_variant, NSUInteger *accepted) {
    if (accepted) *accepted = 0;
    if (!known_variant || data.length > KCR_MAX_BYTES || !kcr_match(expected_sha, @"[a-f0-9]{64}") ||
        ![kcr_sha(data) isEqual:expected_sha] || !kcr_true(identity[@"valid"])) return nil;
    NSDictionary *handoff = kcr_object(data);
    if (!kcr_fields(handoff, @[@"schema", @"context", @"runtime_sha256", @"catalog_revision", @"rows", @"variants"]) ||
        ![handoff[@"schema"] isEqual:@"kokiri-catalog-handoff/1"] ||
        ![kcr_json(handoff[@"context"]) isEqual:kcr_json(identity[@"context"])] ||
        ![handoff[@"runtime_sha256"] isEqual:identity[@"runtime_sha256"]]) return nil;
    NSNumber *revision = handoff[@"catalog_revision"];
    if (![revision isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)revision) == CFBooleanGetTypeID() ||
        revision.longLongValue < 1 || revision.doubleValue != revision.longLongValue) return nil;
    NSArray *rows = handoff[@"rows"]; NSDictionary *variants = handoff[@"variants"];
    if (![rows isKindOfClass:NSArray.class] || !rows.count || rows.count > KCR_MAX_ROWS ||
        ![variants isKindOfClass:NSDictionary.class] || variants.count > KCR_MAX_ROWS * 3) return nil;
    NSMutableString *body = [NSMutableString string]; NSMutableSet *seen = [NSMutableSet set];
    NSMutableSet *used = [NSMutableSet set];
    for (id value in rows) {
        if (![value isKindOfClass:NSString.class] || [value length] > 1090 || [seen containsObject:value]) return nil;
        NSArray<NSString *> *parts = [value componentsSeparatedByString:@"\t"];
        if (parts.count != 2) return nil;
        NSArray *names; NSArray *stages;
        if ([parts[0] isEqual:@"C"] && kcr_match(parts[1], @"[a-f0-9]{64}-[a-f0-9]{12}_b")) {
            names = @[parts[1]]; stages = @[@5];
        } else if ([parts[0] isEqual:@"R"] && kcr_match(parts[1], @"[a-f0-9]{1088}")) {
            /* The owning renderer supplies actual pso_skey_parse plus its
             * nonmerged/nonhost/no-pointer gate in the proof callback. */
            NSDictionary *render = variants[parts[1]];
            if (!kcr_fields(render, @[@"vs", @"fs"]) || !kcr_match(render[@"vs"], @"[a-f0-9]{64}-[a-f0-9]{12}_b") ||
                !([render[@"fs"] isEqual:@""] || kcr_match(render[@"fs"], @"[a-f0-9]{64}-[a-f0-9]{12}_b")) ||
                !known_variant(parts[1], -1, render)) return nil;
            [used addObject:parts[1]];
            names = [render[@"fs"] length] ? @[render[@"vs"], render[@"fs"]] : @[render[@"vs"]];
            stages = names.count == 2 ? @[@0, @1] : @[@0];
        } else return nil;
        for (NSUInteger i = 0; i < names.count; ++i) {
            NSString *name = names[i]; NSDictionary *proof = variants[name];
            if (!kcr_fields(proof, @[@"stage", @"source_sha256", @"reflection_sha256"]) ||
                ![proof[@"stage"] isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)proof[@"stage"]) == CFBooleanGetTypeID() ||
                ![proof[@"stage"] isEqual:stages[i]] ||
                !kcr_match(proof[@"source_sha256"], @"[a-f0-9]{64}") ||
                !kcr_match(proof[@"reflection_sha256"], @"[a-f0-9]{64}") ||
                (![used containsObject:name] && !known_variant(name, [stages[i] intValue], proof))) return nil;
            [used addObject:name];
        }
        [seen addObject:value]; [body appendFormat:@"%@\n", value];
        if (body.length > KCR_MAX_BYTES) return nil;
    }
    if (![used isEqual:[NSSet setWithArray:variants.allKeys]]) return nil;
    if (accepted) *accepted = rows.count;
    return [body copy];
}
