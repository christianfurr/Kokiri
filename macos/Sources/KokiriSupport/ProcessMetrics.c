#include "KokiriSupport.h"
#include <libproc.h>
#include <sys/resource.h>

int kokiri_process_sample(int pid, KokiriProcessSample *sample) {
    struct rusage_info_v4 info = {0};
    if (pid <= 1 || !sample || proc_pid_rusage(pid, RUSAGE_INFO_V4, (rusage_info_t *)&info)) return 0;
    *sample = (KokiriProcessSample){info.ri_phys_footprint, info.ri_resident_size,
                                  info.ri_proc_start_abstime, info.ri_user_time + info.ri_system_time};
    return 1;
}
int kokiri_process_path(int pid, char *path, unsigned capacity) {
    return pid > 1 && path && capacity ? proc_pidpath(pid, path, capacity) : 0;
}
