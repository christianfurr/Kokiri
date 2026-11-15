#ifndef KOKIRI_SUPPORT_H
#define KOKIRI_SUPPORT_H
#include <stdint.h>
typedef struct {
    uint64_t footprint;
    uint64_t resident;
    uint64_t start;
    uint64_t cpu_nanoseconds;
} KokiriProcessSample;
int kokiri_process_sample(int pid, KokiriProcessSample *sample);
int kokiri_process_path(int pid, char *path, unsigned capacity);
#endif
