/* Internal offline verifier: an owning immutable CPU byte snapshot, validated
   against the actual host manifest before any Metal call. No GPU dependency. */
#pragma once
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static dispatch_data_t archive_library_snapshot(NSString *path, NSString *directory, NSDictionary *files,
                                               NSError **error, int *source_payload) {
    NSString *problem = nil; NSMutableString *actual = nil; void *bytes = NULL; int fd = -1;
    if (source_payload) *source_payload = 0;
    NSString *name = path.lastPathComponent;
    NSString *resolved = path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
    NSString *expected = [files isKindOfClass:NSDictionary.class] ? files[name] : nil;
    if (![directory isKindOfClass:NSString.class] || ![resolved.stringByDeletingLastPathComponent isEqualToString:directory] ||
        ![name isEqualToString:resolved.lastPathComponent] || ![name hasSuffix:@".metallib"] ||
        ![expected isKindOfClass:NSString.class] || expected.length != 64 ||
        [expected rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location != NSNotFound) {
        problem = @"Archive verification library is not listed in the actual host manifest directory"; goto fail;
    }
    fd = open(path.fileSystemRepresentation, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat before, after, named;
    if (fd < 0 || fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size <= 0 || (uint64_t)before.st_size > SIZE_MAX) {
        problem = @"Archive verification cannot open a regular prepared library"; goto fail;
    }
    size_t length = (size_t)before.st_size, at = 0;
    bytes = malloc(length);
    if (!bytes) { problem = @"Archive verification cannot allocate its temporary library snapshot"; goto fail; }
    while (at < length) {
        ssize_t n = read(fd, (uint8_t *)bytes + at, MIN(length - at, (size_t)(1 << 20)));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { problem = @"Archive verification library changed or became unreadable during its snapshot"; goto fail; }
        at += (size_t)n;
    }
    if (length < 4 || memcmp(bytes, "MTLB", 4)) {
        if (source_payload) *source_payload = 1;
        problem = @"Archive verification forbids source payloads in place of a prepared library"; goto fail;
    }
    CC_SHA256_CTX hash; CC_SHA256_Init(&hash);
    for (size_t offset = 0; offset < length;) {
        CC_LONG n = (CC_LONG)MIN(length - offset, (size_t)(1 << 20));
        CC_SHA256_Update(&hash, (uint8_t *)bytes + offset, n); offset += n;
    }
    uint8_t digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(digest, &hash);
    actual = [NSMutableString stringWithCapacity:64];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) [actual appendFormat:@"%02x", digest[i]];
    if (![actual isEqualToString:expected]) { problem = @"Archive verification library bytes differ from the actual host manifest"; goto fail; }
    if (fstat(fd, &after) || lstat(path.fileSystemRepresentation, &named) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino || before.st_size != after.st_size ||
        before.st_mode != after.st_mode || before.st_nlink != after.st_nlink ||
        before.st_mtimespec.tv_sec != after.st_mtimespec.tv_sec || before.st_mtimespec.tv_nsec != after.st_mtimespec.tv_nsec ||
        before.st_ctimespec.tv_sec != after.st_ctimespec.tv_sec || before.st_ctimespec.tv_nsec != after.st_ctimespec.tv_nsec ||
        after.st_dev != named.st_dev || after.st_ino != named.st_ino || after.st_size != named.st_size ||
        after.st_mode != named.st_mode || after.st_nlink != named.st_nlink ||
        after.st_mtimespec.tv_sec != named.st_mtimespec.tv_sec || after.st_mtimespec.tv_nsec != named.st_mtimespec.tv_nsec ||
        after.st_ctimespec.tv_sec != named.st_ctimespec.tv_sec || after.st_ctimespec.tv_nsec != named.st_ctimespec.tv_nsec) {
        problem = @"Archive verification library identity changed during its snapshot"; goto fail;
    }
    close(fd);
    return dispatch_data_create(bytes, length, NULL, DISPATCH_DATA_DESTRUCTOR_FREE);
fail:
    if (fd >= 0) close(fd);
    free(bytes);
    if (error) *error = [NSError errorWithDomain:@"KokiriArchiveVerification" code:1 userInfo:@{NSLocalizedDescriptionKey: problem}];
    return nil;
}
