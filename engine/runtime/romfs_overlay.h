/* Descriptor-relative reads for private launch overlays. No symlinks or hardlinks. */
#pragma once
#include "romfs_path.h"
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static inline int romfs_overlay_unchanged(int fd, const struct stat *before) {
    struct stat after;
    return !fstat(fd,&after) && S_ISREG(after.st_mode) && after.st_uid==getuid() && after.st_nlink==1 &&
        before->st_dev==after.st_dev && before->st_ino==after.st_ino && before->st_size==after.st_size &&
        before->st_mtimespec.tv_sec==after.st_mtimespec.tv_sec && before->st_mtimespec.tv_nsec==after.st_mtimespec.tv_nsec &&
        before->st_ctimespec.tv_sec==after.st_ctimespec.tv_sec && before->st_ctimespec.tv_nsec==after.st_ctimespec.tv_nsec;
}

static inline int romfs_overlay_open(int root, const char *name) {
    if (!romfs_path_valid_relative(name) || strlen(name) >= 4000) return -1;
    for (const unsigned char *p=(const unsigned char *)name; *p; ++p)
        if (*p<32 || *p==127 || *p==':') return -1;
    char *copy=strdup(name); if (!copy) return -1;
    int directory=dup(root), result=-1;
    if (directory<0) { free(copy); return -1; }
    char *part=copy, *slash;
    while ((slash=strchr(part,'/'))) {
        *slash=0;
        int next=openat(directory,part,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        close(directory); directory=next;
        if (directory<0) break;
        struct stat st;
        if (fstat(directory,&st) || st.st_uid!=getuid()) { close(directory); directory=-1; break; }
        part=slash+1;
    }
    if (directory>=0) {
        result=openat(directory,part,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
        struct stat st;
        if (result>=0 && (fstat(result,&st) || !S_ISREG(st.st_mode) || st.st_uid!=getuid() || st.st_nlink!=1)) {
            close(result); result=-1;
        }
        close(directory);
    }
    free(copy); return result;
}
