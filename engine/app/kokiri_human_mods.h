/* Version 1 accepts only a pinned snapshot inside this human profile's mods/<launch-id>. */
#pragma once
#include "../runtime/romfs_overlay.h"

static BOOL kokiri_human_mod_version(id value) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value)!=CFBooleanGetTypeID() &&
        strchr("csilqCSILQ",[value objCType][0]) && [value isEqual:@1];
}
static NSData *kokiri_human_mod_read(int directory, const char *name, size_t limit) {
    int fd=romfs_overlay_open(directory,name); if(fd<0)return nil;
    struct stat before,after; NSMutableData *data=[NSMutableData data]; BOOL good=NO;
    if(!fstat(fd,&before) && before.st_size>0 && (uint64_t)before.st_size<=limit) {
        unsigned char buffer[65536]; ssize_t n;
        while((n=read(fd,buffer,sizeof buffer))>0) { [data appendBytes:buffer length:(NSUInteger)n];if(data.length>limit)break; }
        good=n==0 && data.length==(NSUInteger)before.st_size && !fstat(fd,&after) &&
            before.st_dev==after.st_dev && before.st_ino==after.st_ino && before.st_size==after.st_size &&
            before.st_mtimespec.tv_sec==after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec==after.st_mtimespec.tv_nsec &&
            before.st_ctimespec.tv_sec==after.st_ctimespec.tv_sec && before.st_ctimespec.tv_nsec==after.st_ctimespec.tv_nsec;
    }
    close(fd); return good ? data : nil;
}
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static NSString *kokiri_human_mod_digest(NSData *data) {
    if(!data)return nil;
    unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes,(CC_LONG)data.length,digest);
    NSMutableString *value=[NSMutableString stringWithCapacity:64];
    for(unsigned i=0;i<sizeof digest;i++)[value appendFormat:@"%02x",digest[i]];
    return value;
}
static NSString *kokiri_human_mod_file(int directory, const char *name, uint64_t size) {
    int fd=romfs_overlay_open(directory,name); if(fd<0)return nil;
    struct stat before,after;
    if(fstat(fd,&before) || (uint64_t)before.st_size!=size) { close(fd);return nil; }
    CC_SHA256_CTX context;CC_SHA256_Init(&context);
    unsigned char bytes[65536],digest[CC_SHA256_DIGEST_LENGTH];ssize_t count;uint64_t total=0;
    while((count=read(fd,bytes,sizeof bytes))>0) {
        total+=(uint64_t)count;if(total>size)break;CC_SHA256_Update(&context,bytes,(CC_LONG)count);
    }
    BOOL good=count==0 && total==size && !fstat(fd,&after) && before.st_dev==after.st_dev && before.st_ino==after.st_ino &&
        before.st_size==after.st_size && before.st_mtimespec.tv_sec==after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec==after.st_mtimespec.tv_nsec &&
        before.st_ctimespec.tv_sec==after.st_ctimespec.tv_sec && before.st_ctimespec.tv_nsec==after.st_ctimespec.tv_nsec;
    close(fd);if(!good)return nil;
    CC_SHA256_Final(digest,&context);NSMutableString *value=[NSMutableString stringWithCapacity:64];
    for(unsigned i=0;i<sizeof digest;i++)[value appendFormat:@"%02x",digest[i]];
    return value;
}
#pragma clang diagnostic pop
static NSDictionary *kokiri_human_mods(int directory, NSString *root, NSDictionary *preview, NSDictionary *bundle,
                                     NSString *launch, NSString *handoffHash, int *overlayDirectory) {
    if(!kokiri_human_mod_version(bundle[@"KokiriHumanPreviewModsVersion"]) ||
       !kokiri_dev_hex(launch,32) || !kokiri_dev_hex(handoffHash,64))return nil;
    int mods=openat(directory,"mods",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    int session=mods>=0 ? openat(mods,launch.UTF8String,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC) : -1;
    if(mods>=0)close(mods);
    struct stat st;
    if(session<0)return nil;
    if(fstat(session,&st) || st.st_uid!=getuid() || (st.st_mode&0777)!=0700) { close(session);return nil; }
    unsigned remaining=50000;
    if(!kokiri_dev_tree(session,0,&remaining,NO)) { close(session);return nil; }
    NSData *raw=kokiri_human_mod_read(session,"handoff.json",65536);
    NSDictionary *record=raw ? [NSJSONSerialization JSONObjectWithData:raw options:0 error:nil] : nil;
    NSSet *keys=[NSSet setWithArray:@[@"schema",@"kind",@"session_id",@"launch_id",@"executable_sha256",@"manifest_sha256"]];
    BOOL good=[record isKindOfClass:NSDictionary.class] && [[NSSet setWithArray:record.allKeys] isEqual:keys] &&
        [kokiri_human_mod_digest(raw) isEqual:handoffHash] && kokiri_human_mod_version(record[@"schema"]) &&
        [record[@"kind"] isEqual:@"human-mod-overlay"] && [record[@"session_id"] isEqual:preview[@"session_id"]] &&
        [record[@"launch_id"] isEqual:launch] && [record[@"executable_sha256"] isEqual:preview[@"executable_sha256"]] &&
        kokiri_dev_hex(record[@"manifest_sha256"],64);
    NSData *manifest=good ? kokiri_human_mod_read(session,"mods/manifest.tsv",8<<20) : nil;
    NSString *text=manifest ? [[NSString alloc] initWithData:manifest encoding:NSUTF8StringEncoding] : nil;
    good=good && text && [kokiri_human_mod_digest(manifest) isEqual:record[@"manifest_sha256"]];
    int payload=good ? openat(session,"mods",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC) : -1;
    good=good && payload>=0 && !fstat(payload,&st) && st.st_uid==getuid() && (st.st_mode&0777)==0700;
    NSMutableSet *names=[NSMutableSet set];
    for(NSString *line in [text componentsSeparatedByString:@"\n"]) {
        if(!good)break;
        if(!line.length || [line hasPrefix:@"#"])continue;
        NSArray *parts=[line componentsSeparatedByString:@"\t"];
        if(parts.count!=4) { good=NO;break; }
        NSString *name=parts[0], *size=parts[1];
        const char *path=name.UTF8String;
        good=romfs_path_valid_relative(path) && strlen(path)<4000 && !strchr(path,':') &&
            [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location==NSNotFound &&
            size.length>0 && size.length<=20 && [size rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789"] invertedSet]].location==NSNotFound &&
            kokiri_dev_hex(parts[2],64) && ([parts[3] isEqual:@"-"] || kokiri_dev_hex(parts[3],64)) && ![names containsObject:name];
        if(!good)break;
        char *end=NULL;errno=0;unsigned long long bytes=strtoull(size.UTF8String,&end,10);
        good=!errno && end && !*end && bytes<=(4ULL<<30) && [kokiri_human_mod_file(payload,path,bytes) isEqual:parts[2]];
        if(!good)break;
        [names addObject:name]; if(names.count>20000)good=NO;
    }
    good=good && names.count && [kokiri_human_mod_read(session,"mods/manifest.tsv",8<<20) isEqual:manifest];
    close(session);
    if(!good) { if(payload>=0)close(payload);return nil; }
    *overlayDirectory=payload;
    return @{@"schema":@1,@"launch_id":launch,@"handoff_sha256":handoffHash,@"manifest_sha256":record[@"manifest_sha256"],
        @"overlay":[root stringByAppendingPathComponent:[NSString stringWithFormat:@"mods/%@/mods",launch]],@"files":@(names.count)};
}
