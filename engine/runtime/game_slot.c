/* Game slot: at most one game (or GPU probe) runs at a time on this Mac.
   One game takes about 6.6 GB of the 16 GB; two need about 13 GB, and exhausted memory is what made the GPU driver
   panic the kernel four times on 2026-10-12. Two games would also share one GPU, so neither one's frame times mean
   anything. Several agents (Claude, Codex) and the user's own desktop launcher start games, so the rule is enforced
   here, in every `boot` and `probe-gpu-*` run, rather than in each script.

   The holder keeps an exclusive flock(2) on <slot dir>/lock for the life of its game; the kernel drops the lock when
   the process exits or crashes, so a dead holder never blocks anyone. Waiters line up first come first served. A game
   started for the user (TOTK_SLOT_OWNER=user, the desktop launcher) goes ahead of the queue and stops an agent's game
   that holds the slot: it first records the preemption, then sends SIGTERM, so the agent's script knows to rerun that
   test once the slot is free again. A wrapper that already holds the lock (scripts/dev/game_slot.py) passes it down
   as TOTK_GAME_SLOT_FD. Files in the slot directory (shared with scripts/dev/game_slot.py; change both together):
     lock               flock(2) target
     preemption.lock    stable signal/takeover guard; a physical player retains it until exit
     holder             key=value lines about the current holder; stale once the lock is free
     queue/<ns>-<pid>   waiters (key=value: pid, start, owner, purpose, since)
     user-request       the user's game while it waits for the slot
     preempted/<token>  written just before a holder is stopped for the user
     history.log        one line per acquire / start / preempt / exit
   The slot directory is TOTK_GAME_SLOT_DIR, else ~/Library/Application Support/MacNativeGames/TOTK/game-slot, the
   folder the App's launcher passes (app/launcher.m), so a binary run directly, the scripts and the App's game share one
   slot. Until 2026-11-11 the default was analysis/game-slot next to this binary's build/ directory. */
#include <TargetConditionals.h>
#if TARGET_OS_IPHONE
#include "runtime.h"
/* One app per phone: the slot only exists to keep several games off one Mac. No agent watch either: input.c's weak
   runtime_slot_activity is used. */
void runtime_game_slot_acquire(const char *mode) { (void)mode; }
#else
#include "runtime.h"
#include "agent_slot_limit.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/proc.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static char slot_dir[PATH_MAX], lock_path[PATH_MAX], my_queue[PATH_MAX];
static char owner[33], purpose[200], token[48], mode_name[64];
static int lock_fd = -1, acquired;
static time_t acquired_at;
/* Agent shutdown and physical takeover share one linearization point. Once
   published, takeover is permanent for this process, even after lease expiry. */
static pthread_mutex_t agent_ownership_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int agent_user_takeover;
static int preemption_fd = -1, preemption_retained;

int runtime_game_slot_agent_close_begin(void) {
    pthread_mutex_lock(&agent_ownership_mutex);
    if (atomic_load_explicit(&agent_user_takeover, memory_order_acquire)) {
        pthread_mutex_unlock(&agent_ownership_mutex); return 0;
    }
    return 1;
}
void runtime_game_slot_agent_close_end(void) { pthread_mutex_unlock(&agent_ownership_mutex); }

_Noreturn static void slot_fail(const char *what, const char *path) {
    fprintf(stderr, "[game-slot] %s %s: %s\n", what, path ? path : "", strerror(errno));
    runtime_fail("game slot: see the [game-slot] line above");
}

static void path_in(char *out, const char *name) {
    if (snprintf(out, PATH_MAX, "%s/%s", slot_dir, name) >= PATH_MAX) runtime_fail("game slot path too long");
}

/* This inode is never unlinked or rotated. Open before game startup, so a
   physical takeover does not need to allocate a new descriptor or create a file. */
static int preemption_guard_open(void) {
    if(preemption_fd>=0)return 1;
    char path[PATH_MAX];path_in(path,"preemption.lock");
    int fd=open(path,O_RDWR|O_CREAT|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
    if(fd<0)return 0;
    struct stat info,path_info;
    if(fstat(fd,&info)||!S_ISREG(info.st_mode)||info.st_uid!=getuid()||info.st_nlink!=1||
       lstat(path,&path_info)||info.st_dev!=path_info.st_dev||info.st_ino!=path_info.st_ino) {
        close(fd);errno=EINVAL;return 0;
    }
    preemption_fd=fd;return 1;
}
static int preemption_guard_try(void) {
    if(preemption_retained||preemption_fd<0)return 0;
    return !flock(preemption_fd,LOCK_EX|LOCK_NB);
}

static void clean_copy(char *dst, size_t n, const char *src) {   /* one line, no control characters */
    size_t i = 0;
    for (; src && src[i] && i + 1 < n; i++) dst[i] = (unsigned char)src[i] < 0x20 ? ' ' : src[i];
    dst[i] = 0;
}

static int kv_get(const char *path, const char *key, char *out, size_t n) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[1024]; size_t kl = strlen(key); int found = 0;
    while (!found && fgets(line, sizeof line, f))
        if (!strncmp(line, key, kl) && line[kl] == '=') {
            char *v = line + kl + 1; v[strcspn(v, "\n")] = 0;
            snprintf(out, n, "%s", v); found = 1;
        }
    fclose(f);
    return found;
}

static long long kv_num(const char *path, const char *key) {
    char b[32];
    return kv_get(path, key, b, sizeof b) ? atoll(b) : 0;
}

static int try_write_atomic(const char *path, const char *text) {
    char tmp[PATH_MAX];
    if (snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, getpid()) >= (int)sizeof tmp) { errno=ENAMETOOLONG;return 0; }
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return 0;
    size_t len = strlen(text);
    ssize_t written=write(fd,text,len);int okay=written==(ssize_t)len;
    if(written>=0&&!okay)errno=EIO;
    int saved=errno;close(fd);
    if(okay) { okay=!rename(tmp,path);saved=errno; }
    if(!okay)unlink(tmp);
    errno=saved;return okay;
}
static void write_atomic(const char *path, const char *text) {
    if(!try_write_atomic(path,text))slot_fail("cannot write",path);
}

static void history(const char *event, const char *extra) {
    char p[PATH_MAX]; path_in(p, "history.log");
    int fd = open(p, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0) return;   /* the log is a convenience; the lock is what matters */
    time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
    char ts[32]; strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%S", &tm);
    char line[1024];
    int n = snprintf(line, sizeof line, "%s %s owner=%s pid=%d mode=%s purpose=%s%s%s\n", ts, event,
                     atomic_load(&agent_user_takeover)?"user":owner, getpid(),mode_name,
                     atomic_load(&agent_user_takeover)?"physical-user-takeover":purpose, extra ? " " : "", extra ? extra : "");
    if (n > 0) (void)!write(fd, line, (size_t)(n < (int)sizeof line ? n : (int)sizeof line - 1));
    close(fd);
}

/* Process start time (seconds) or 0 if the pid is gone or a zombie; with the pid it names one process exactly. */
static uint64_t pid_start(pid_t pid) {
    struct proc_bsdinfo bi;
    if (pid <= 0 || proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &bi, sizeof bi) != (int)sizeof bi || bi.pbi_status == SZOMB) return 0;
    return bi.pbi_start_tvsec;
}
static int pid_same(pid_t pid, uint64_t start) { return start && pid_start(pid) == start; }
/* Same rule as scripts/dev/game_slot.py is_game_path. */
static int slot_path_is_game(const char *path) {
    const char *b = strrchr(path, '/'); b = b ? b + 1 : path;
    if (b - path >= 16 && !strncmp(b - 16, "/Contents/MacOS/", 16) &&
        (!strcmp(b, "TOTK") || !strcmp(b, "BotW") || !strcmp(b, "Bananza") || !strcmp(b, "Pokopia") ||
         !strcmp(b, "OcarinaOfTime") || !strcmp(b, "KokiriGame"))) return 1;   /* packaged games */
    return !strncmp(b, "totk-native", 11) || !strncmp(b, "oot-native", 10);   /* also renamed copies such as totk-native.base */
}
static int pid_is_game(pid_t pid) {
    char path[PROC_PIDPATHINFO_MAXSIZE];
    if (proc_pidpath(pid, path, sizeof path) <= 0) return 0;
    return slot_path_is_game(path);
}

/* Live waiters in the queue (dead ones are removed). Returns how many; *head gets the oldest one's file name. */
static int queue_scan(char *head, size_t head_n, pid_t *pids, int max_pids) {
    char qdir[PATH_MAX]; path_in(qdir, "queue");
    DIR *d = opendir(qdir);
    if (!d) slot_fail("cannot open", qdir);
    int count = 0; if (head) head[0] = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.' || strstr(e->d_name, ".tmp")) continue;
        char p[PATH_MAX];
        if (snprintf(p, sizeof p, "%s/%s", qdir, e->d_name) >= (int)sizeof p) continue;
        pid_t pid = (pid_t)kv_num(p, "pid");
        if (!pid_same(pid, (uint64_t)kv_num(p, "start"))) { unlink(p); continue; }
        if (pids && count < max_pids) pids[count] = pid;
        count++;
        if (head && (!head[0] || strcmp(e->d_name, head) < 0)) snprintf(head, head_n, "%s", e->d_name);
    }
    closedir(d);
    return count;
}

static pid_t user_request_pid(void) {   /* a live user game waiting for the slot, or 0 */
    char p[PATH_MAX]; path_in(p, "user-request");
    pid_t pid = (pid_t)kv_num(p, "pid");
    return pid_same(pid, (uint64_t)kv_num(p, "start")) ? pid : 0;
}

/* A totk-native process that is neither queued nor this one: a game from before the slot existed (or one using another
   slot directory). Only called while holding the lock, so no game that follows the protocol can be running. */
static pid_t legacy_game(void) {
    pid_t queued[64]; int nq = queue_scan(NULL, 0, queued, 64);
    pid_t user = user_request_pid();
    int n = proc_listallpids(NULL, 0);
    if (n <= 0) return 0;
    int cap = n + 64;
    pid_t *pids = calloc((size_t)cap, sizeof *pids);
    if (!pids) runtime_fail("game slot: out of memory");
    n = proc_listallpids(pids, cap * (int)sizeof *pids);
    pid_t found = 0;
    for (int i = 0; i < n && i < cap && !found; i++) {
        pid_t p = pids[i];
        if (p <= 0 || p == getpid() || p == user || !pid_is_game(p) || !pid_start(p)) continue;
        int q = 0;
        for (int k = 0; k < nq && k < 64; k++) q |= queued[k] == p;
        if (!q) found = p;
    }
    free(pids);
    return found;
}

static void describe_holder(char *out, size_t n) {
    char p[PATH_MAX]; path_in(p, "holder");
    char who[40] = "?", what[200] = "?";
    kv_get(p, "owner", who, sizeof who); kv_get(p, "purpose", what, sizeof what);
    long long since = kv_num(p, "since"), expect = kv_num(p, "expect_s"), gp = kv_num(p, "game_pid");
    long long held = since ? (long long)time(NULL) - since : 0;
    char left[64] = "";
    if (expect > held) snprintf(left, sizeof left, "，预计还要约 %lld 分钟", (expect - held + 59) / 60);
    snprintf(out, n, "%s（%s）占用中，已 %lld 分 %lld 秒%s，游戏 pid %lld", who, what, held / 60, held % 60, left, gp);
}

typedef struct {
    char owner[33],token[48],purpose[200];
    pid_t pid;
    uint64_t start;
    struct stat generation;
} HolderSnapshot;

static int holder_decimal(const char *text,uint64_t maximum,uint64_t *value) {
    if(!*text)return 0;
    for(const char *p=text;*p;p++)if(*p<'0'||*p>'9')return 0;
    errno=0;char *end;unsigned long long parsed=strtoull(text,&end,10);
    if(errno||*end||!parsed||parsed>maximum)return 0;
    *value=(uint64_t)parsed;return 1;
}
static int holder_generation_equal(const struct stat *first,const struct stat *second) {
    return S_ISREG(second->st_mode)&&second->st_uid==getuid()&&second->st_nlink==1&&
        first->st_dev==second->st_dev&&first->st_ino==second->st_ino&&first->st_size==second->st_size&&
        first->st_mtimespec.tv_sec==second->st_mtimespec.tv_sec&&first->st_mtimespec.tv_nsec==second->st_mtimespec.tv_nsec&&
        first->st_ctimespec.tv_sec==second->st_ctimespec.tv_sec&&first->st_ctimespec.tv_nsec==second->st_ctimespec.tv_nsec;
}
static int holder_snapshot_current(const char *path,const HolderSnapshot *snapshot) {
    struct stat current;
    return !lstat(path,&current)&&holder_generation_equal(&snapshot->generation,&current);
}
static int holder_snapshot_read(const char *path,HolderSnapshot *snapshot) {
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if(fd<0)return 0;
    struct stat before,after;char buffer[4097];size_t length=0;int okay=0;
    if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_uid!=getuid()||before.st_nlink!=1||before.st_size<=0||before.st_size>4096)goto finish;
    while(length<sizeof buffer) {
        ssize_t count=read(fd,buffer+length,sizeof buffer-length);
        if(count<0&&errno==EINTR)continue;
        if(count<0)goto finish;
        if(!count)break;
        length+=(size_t)count;
    }
    if(length>4096||length!=(size_t)before.st_size||memchr(buffer,0,length)||fstat(fd,&after)||!holder_generation_equal(&before,&after))goto finish;
    buffer[length]=0;memset(snapshot,0,sizeof *snapshot);snapshot->generation=before;
    unsigned fields=0;char *context=NULL;
    for(char *line=strtok_r(buffer,"\n",&context);line;line=strtok_r(NULL,"\n",&context)) {
        char *equal=strchr(line,'=');if(!equal)continue;*equal++=0;
        unsigned bit=0;char *destination=NULL;size_t capacity=0;
        if(!strcmp(line,"owner")){bit=1;destination=snapshot->owner;capacity=sizeof snapshot->owner;}
        else if(!strcmp(line,"token")){bit=2;destination=snapshot->token;capacity=sizeof snapshot->token;}
        else if(!strcmp(line,"purpose")){bit=4;destination=snapshot->purpose;capacity=sizeof snapshot->purpose;}
        else if(!strcmp(line,"game_pid"))bit=8;
        else if(!strcmp(line,"game_start"))bit=16;
        if(!bit)continue;
        if(fields&bit)goto finish;
        fields|=bit;
        if(destination) {
            size_t size=strlen(equal);if(size>=capacity||(bit!=4&&!size))goto finish;
            if(bit!=4)for(const char *p=equal;*p;p++)if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='-'||*p=='_'))goto finish;
            memcpy(destination,equal,size+1);
        } else {
            uint64_t value;
            if(!holder_decimal(equal,bit==8?INT_MAX:UINT64_MAX,&value))goto finish;
            if(bit==8){if(value<=1)goto finish;snapshot->pid=(pid_t)value;}
            else snapshot->start=value;
        }
    }
    okay=fields==31&&holder_snapshot_current(path,snapshot);
finish:
    close(fd);return okay;
}

/* The user's game: stop an agent's game that holds the slot. The marker comes first, so the agent's script can tell a
   preemption from a crash; SIGKILL follows if the game has not gone 15 s after SIGTERM. */
static void preempt_holder(void) {
    static char done_token[48]; static time_t sent_at; static int killed;
    /* Read and signal in one cooperative transaction. Never wait for this guard
       while waiting for the game slot, and never use a previously read holder. */
    if(!preemption_guard_try())return;
    char p[PATH_MAX]; path_in(p, "holder");
    HolderSnapshot snapshot;
    if(!holder_snapshot_read(p,&snapshot)||!strcmp(snapshot.owner,"user"))goto release;
    const char *who=snapshot.owner,*tok=snapshot.token,*what=snapshot.purpose;
    pid_t gp=snapshot.pid;uint64_t start=snapshot.start;
    int live = pid_same(gp,start) && pid_is_game(gp);
    if (strcmp(done_token, tok)) {
        char m[PATH_MAX], name[80], text[200];
        snprintf(name, sizeof name, "preempted/%s", tok); path_in(m, name);
        snprintf(text, sizeof text, "by_pid=%d\nat=%lld\n", getpid(), (long long)time(NULL));
        write_atomic(m, text);
        char extra[300]; snprintf(extra, sizeof extra, "target_owner=%s target_pid=%d target_purpose=%s", who, gp, what);
        history("preempt", extra);
        if (live && holder_snapshot_current(p,&snapshot) && pid_same(gp,start) && pid_is_game(gp)) kill(gp, SIGTERM);
        fprintf(stderr, "[game-slot] 用户要玩：停止 %s 的游戏（%s，pid %d），它的测试稍后会自动重跑\n", who, what, gp);
        snprintf(done_token, sizeof done_token, "%s", tok); sent_at = time(NULL); killed = 0;
    } else if (live && !killed && time(NULL) - sent_at > 15) {
        if(holder_snapshot_current(p,&snapshot) && pid_same(gp,start) && pid_is_game(gp))kill(gp,SIGKILL);
        killed = 1;
        fprintf(stderr, "[game-slot] pid %d 15 秒内没有退出，强制结束\n", gp);
    }
release:
    flock(preemption_fd,LOCK_UN);
}

/* The folder app/launcher.m passes to its game (and scripts/dev/game_slot.py default_slot_dir); 0 without HOME. */
static int slot_default_dir(char *out, size_t n) {
    const char *home = getenv("HOME");
    if (!home || !*home) return 0;
    return snprintf(out, n, "%s/Library/Application Support/MacNativeGames/TOTK/game-slot", home) < (int)n;
}
static void mkdir_parents(const char *path) {   /* mkdir -p: MacNativeGames/TOTK may not exist yet */
    char p[PATH_MAX]; snprintf(p, sizeof p, "%s", path);
    for (char *s = p + 1; *s; s++) {
        if (*s != '/') continue;
        *s = 0;
        if (mkdir(p, 0755) && errno != EEXIST) slot_fail("cannot create", p);
        *s = '/';
    }
    if (mkdir(p, 0755) && errno != EEXIST) slot_fail("cannot create", p);
}

static void slot_dir_init(void) {
    char def[PATH_MAX] = "";
    const char *env = getenv("TOTK_GAME_SLOT_DIR");
    if ((!env || !*env) && !slot_default_dir(def, sizeof def)) def[0] = 0;
    const char *want = env && *env ? env : def;
    if (!*want) runtime_fail("game slot: no slot directory (set TOTK_GAME_SLOT_DIR)");
    mkdir_parents(want);
    if (!realpath(want, slot_dir)) slot_fail("cannot resolve", want);
    char sub[PATH_MAX];
    path_in(sub, "queue"); if (mkdir(sub, 0755) && errno != EEXIST) slot_fail("cannot create", sub);
    path_in(sub, "preempted"); if (mkdir(sub, 0755) && errno != EEXIST) slot_fail("cannot create", sub);
    path_in(lock_path, "lock");
    if(!preemption_guard_open())slot_fail("cannot open safe preemption guard",slot_dir);
}

static int test_ignores_legacy(void) {   /* tests use their own slot directory; never the shared one */
    const char *e = getenv("TOTK_GAME_SLOT_TEST_IGNORE_LEGACY"), *d = getenv("TOTK_GAME_SLOT_DIR");
    if (!e || strcmp(e, "1")) return 0;
    char shared[PATH_MAX], real[PATH_MAX];
    int is_shared = slot_default_dir(shared, sizeof shared) && !strcmp(slot_dir, realpath(shared, real) ? real : shared);
    if (!d || !*d || is_shared) runtime_fail("TOTK_GAME_SLOT_TEST_IGNORE_LEGACY needs a test TOTK_GAME_SLOT_DIR");
    return 1;
}

static void holder_write_mode(int fatal) {
    char exe[PROC_PIDPATHINFO_MAXSIZE] = "", cwd[PATH_MAX] = "", log[PATH_MAX] = "", text[4096];
    proc_pidpath(getpid(), exe, sizeof exe);
    if (!getcwd(cwd, sizeof cwd)) cwd[0] = 0;
    if (fcntl(2, F_GETPATH, log) == -1) log[0] = 0;
    const char *w = getenv("TOTK_SLOT_WRAPPER_PID"), *ex = getenv("TOTK_SLOT_EXPECT_S"), *si = getenv("TOTK_SLOT_SINCE");
    snprintf(text, sizeof text,
             "owner=%s\npurpose=%s\ntoken=%s\ngame_pid=%d\ngame_start=%llu\nwrapper_pid=%s\nsince=%lld\nexpect_s=%s\nmode=%s\nexe=%s\ncwd=%s\nlog=%s\n",
             atomic_load(&agent_user_takeover)?"user":owner,
             atomic_load(&agent_user_takeover)?"physical-user-takeover":purpose,
             token, getpid(), (unsigned long long)pid_start(getpid()), w ? w : "", si ? atoll(si) : (long long)acquired_at,
             ex ? ex : "0", mode_name, exe, cwd, log);
    char p[PATH_MAX]; path_in(p, "holder");
    if(fatal)write_atomic(p,text);
    else if(!try_write_atomic(p,text))fprintf(stderr,"[game-slot] physical takeover published in memory; holder update failed: %s\n",strerror(errno));
}
static void holder_write(void) { holder_write_mode(1); }

void runtime_game_slot_user_takeover(void) {
    pthread_mutex_lock(&agent_ownership_mutex);
    if(!atomic_load_explicit(&agent_user_takeover,memory_order_acquire)) {
        /* Updated preempters use this same inode. Retain its exclusive lock for
           the remainder of the human session, including holder-write failures.
           A preempter already inside its transaction linearizes before takeover. */
        int result=-1;
        if(preemption_fd>=0)do { result=flock(preemption_fd,LOCK_EX); } while(result<0&&errno==EINTR);
        if(!result)preemption_retained=1;
        else fprintf(stderr,"[game-slot] cannot retain physical takeover guard: %s\n",strerror(errno));
        atomic_store_explicit(&agent_user_takeover,1,memory_order_release);
        if(acquired)holder_write_mode(0);
        history("user-takeover","agent-close=disarmed");
    }
    pthread_mutex_unlock(&agent_ownership_mutex);
}

static void at_exit(void) {
    if (my_queue[0]) unlink(my_queue);
    if ((!strcmp(owner, "user") || atomic_load(&agent_user_takeover)) && user_request_pid() == getpid()) { char p[PATH_MAX]; path_in(p, "user-request"); unlink(p); }
    if (acquired) { char extra[64]; snprintf(extra, sizeof extra, "held_s=%lld", (long long)(time(NULL) - acquired_at)); history("exit", extra); }
}

static void dry_run(void) {   /* tests: hold the slot like a game would, without booting */
    const char *e = getenv("TOTK_GAME_SLOT_DRYRUN");
    if (!e) return;
    double s = atof(e);
    fprintf(stderr, "[game-slot] dry run: holding the slot %.1f s\n", s);
    for (double t = 0; t < s; t += 0.05) usleep(50000);
    exit(0);
}

/* An agent's game closes itself when nobody uses it (agent_slot_limit.h). input.c reports each input-file command and
   each real user input (runtime_slot_activity); a thread checks twice a second and asks for the close the input file's
   "close" makes (frontend.m: the window closes and waits for a save in progress). */
uint64_t dm_nvn_frame_count(void);           /* gfx/nvn/hle_nvn.c: game frames presented; nvn_mtl.m warm_start holds the
                                                first one until the warm-up before the title is done */
void runtime_front_request_agent_close(void); /* frontend.m: cancellable agent-only close */
enum { AGENT_CLOSE_STOP_S = 120 };           /* still running this long after the close request: SIGTERM, as a user's
                                                game stops an agent's game (preempt_holder) */
static _Atomic uint64_t agent_command_ns, agent_user_ns;   /* CLOCK_MONOTONIC ns of the last one; 0 none */
static uint64_t agent_clock_ns(void) { return clock_gettime_nsec_np(CLOCK_MONOTONIC); }
static double agent_clock_s(uint64_t ns) { return ns ? (double)ns / 1e9 : AGENT_NEVER; }

void runtime_slot_activity(int user) { atomic_store(user ? &agent_user_ns : &agent_command_ns, agent_clock_ns()); }

static AgentLimitConfig agent_config;
static double agent_start;

static void agent_close(AgentLimit why, double now, double shown, double last) {
    if(!runtime_game_slot_agent_close_begin())return;
    char line[200], extra[200];
    if (why == AGENT_LIMIT_IDLE) {
        long idle = (long)(now - (last > shown ? last : shown));
        snprintf(line, sizeof line, "no command or input for %ld s", idle);
        snprintf(extra, sizeof extra, "reason=idle idle_s=%ld", idle);
    } else {
        snprintf(line, sizeof line, "over its expected %ld s (+%ld s grace; running %ld s)", agent_config.expect_s,
                 agent_config.grace_s, (long)(now - agent_start));
        snprintf(extra, sizeof extra, "reason=limit expect_s=%ld running_s=%ld", agent_config.expect_s, (long)(now - agent_start));
    }
    fprintf(stderr, "[slot] agent game %s closed: %s\n", owner, line);
    history("agent-close", extra);
    runtime_front_request_agent_close();
    runtime_game_slot_agent_close_end();
}

static int agent_stop_if_owned(void) {
    if(!runtime_game_slot_agent_close_begin())return 0;
    fprintf(stderr,"[slot] agent game %s still running %d s after its close request: stopping it (SIGTERM)\n",owner,AGENT_CLOSE_STOP_S);
    history("agent-stop","reason=close-request-ignored");
    kill(getpid(),SIGTERM);
    runtime_game_slot_agent_close_end();return 1;
}

static void *agent_watch(void *arg) {
    (void)arg;
    double shown = AGENT_NEVER, closed_at = AGENT_NEVER;
    for (;;) {
        usleep(500000);
        if(atomic_load_explicit(&agent_user_takeover,memory_order_acquire))return NULL;
        double now = agent_clock_s(agent_clock_ns());
        if (closed_at >= 0) {
            if (now - closed_at < AGENT_CLOSE_STOP_S) continue;
            if(!agent_stop_if_owned())return NULL;
            closed_at = now;   /* once more after another AGENT_CLOSE_STOP_S if it is still there */
            continue;
        }
        if (shown < 0 && dm_nvn_frame_count()) shown = now;
        double cmd = agent_clock_s(atomic_load(&agent_command_ns)), user = agent_clock_s(atomic_load(&agent_user_ns));
        double last = cmd > user ? cmd : user;
        AgentLimit why = agent_limit_decide(now, agent_start, shown, last, user, (double)agent_config.idle_s, (double)agent_config.limit_s);
        if (why == AGENT_LIMIT_NONE) continue;
        agent_close(why, now, shown, last);
        closed_at = now;
    }
    return NULL;
}

/* Called once the slot is ours. The user's game (owner user, or no TOTK_SLOT_OWNER) is never watched. */
static void agent_watch_start(void) {
    if(atomic_load_explicit(&agent_user_takeover,memory_order_acquire))return;
    const char *o = getenv("TOTK_SLOT_OWNER");
    if (!agent_owner_is_agent(o)) return;
    agent_config = agent_limit_config(getenv("TOTK_AGENT_IDLE_S"), getenv("TOTK_AGENT_GRACE_S"), getenv("TOTK_AGENT_LIMIT_S"),
                                      getenv("TOTK_SLOT_EXPECT_S"));
    if (agent_config.bad)
        fprintf(stderr, "[slot] %s=%s is not whole seconds (0 to %d): its default is used\n", agent_config.bad,
                getenv(agent_config.bad), AGENT_SECONDS_MAX);
    if (!agent_config.idle_s)
        fprintf(stderr, "[slot] warning: TOTK_AGENT_IDLE_S=0: agent game %s does not close when idle; close it yourself\n", owner);
    if (!agent_config.limit_s)
        fprintf(stderr, "[slot] warning: TOTK_AGENT_LIMIT_S=0: agent game %s has no time limit; close it yourself\n", owner);
    agent_start = agent_clock_s(agent_clock_ns());
    char idle[48] = "never when idle", limit[48] = "no time limit";
    if (agent_config.idle_s) snprintf(idle, sizeof idle, "%ld s idle", agent_config.idle_s);
    if (agent_config.limit_s) snprintf(limit, sizeof limit, "%ld s", agent_config.limit_s);
    fprintf(stderr, "[slot] agent game %s: closes itself after %s or %s (TOTK_AGENT_IDLE_S, TOTK_SLOT_EXPECT_S + TOTK_AGENT_GRACE_S)\n",
            owner, idle, limit);
    if (!agent_config.idle_s && !agent_config.limit_s) return;
    pthread_t t;
    if (pthread_create(&t, NULL, agent_watch, NULL)) runtime_fail("game slot: cannot start the agent game watch");
    pthread_detach(t);
}

void runtime_game_slot_acquire(const char *mode) {
    clean_copy(mode_name, sizeof mode_name, mode);
    const char *o = getenv("TOTK_SLOT_OWNER"), *pu = getenv("TOTK_SLOT_PURPOSE");
    clean_copy(owner, sizeof owner, o && *o ? o : "unknown");
    for (const char *c = owner; *c; c++)
        if (!((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') || *c == '-' || *c == '_'))
            runtime_fail("TOTK_SLOT_OWNER: use lower-case letters, digits, - or _ (user, claude, codex ...)");
    clean_copy(purpose, sizeof purpose, pu && *pu ? pu : mode);
    slot_dir_init();
    atexit(at_exit);

    const char *fd_env = getenv("TOTK_GAME_SLOT_FD");
    if (fd_env) {   /* a wrapper took the slot for us: check that this descriptor really holds the lock */
        int fd = atoi(fd_env); struct stat a, b;
        if (fd < 3 || fstat(fd, &a) || stat(lock_path, &b) || a.st_dev != b.st_dev || a.st_ino != b.st_ino)
            runtime_fail("TOTK_GAME_SLOT_FD is not the game slot lock of this slot directory");
        if (flock(fd, LOCK_EX | LOCK_NB)) runtime_fail("TOTK_GAME_SLOT_FD does not hold the game slot (another game has it)");
        fcntl(fd, F_SETFD, FD_CLOEXEC);
        const char *t = getenv("TOTK_SLOT_TOKEN");
        if (!t || !*t) runtime_fail("TOTK_GAME_SLOT_FD without TOTK_SLOT_TOKEN");
        clean_copy(token, sizeof token, t);
        lock_fd = fd; acquired = 1; acquired_at = time(NULL);
        unsetenv("TOTK_GAME_SLOT_FD");
        holder_write();
        history("start", "slot=inherited");
        fprintf(stderr, "[game-slot] 游戏位置由启动脚本持有（%s，%s）\n", owner, purpose);
        agent_watch_start();
        dry_run();
        return;
    }

    lock_fd = open(lock_path, O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (lock_fd < 0) slot_fail("cannot open", lock_path);
    int user = !strcmp(owner, "user"), ignore_legacy = test_ignores_legacy();
    const char *mw = getenv("TOTK_GAME_SLOT_WAIT");
    double max_wait = mw ? atof(mw) : -1;
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    char name[80], text[600];
    snprintf(name, sizeof name, "queue/%019llu-%d", (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec, getpid());
    path_in(my_queue, name);
    snprintf(text, sizeof text, "pid=%d\nstart=%llu\nowner=%s\npurpose=%s\nsince=%lld\n", getpid(),
             (unsigned long long)pid_start(getpid()), owner, purpose, (long long)ts.tv_sec);
    write_atomic(my_queue, text);
    if (user) { char p[PATH_MAX]; path_in(p, "user-request"); write_atomic(p, text); }

    time_t start = time(NULL), last_log = 0;
    char reason[600] = "", key[128] = "", last_key[128] = "";   /* key: who blocks us, without the running time */
    for (;;) {
        char head[80]; queue_scan(head, sizeof head, NULL, 0);
        pid_t upid = user ? 0 : user_request_pid();
        const char *mine = strrchr(my_queue, '/') + 1;
        if (upid) { snprintf(reason, sizeof reason, "用户的游戏（pid %d）正在等，让它先", upid); snprintf(key, sizeof key, "user %d", upid); }
        else if (!user && strcmp(head, mine)) {
            snprintf(reason, sizeof reason, "排队中，前面还有别的测试（queue/%s）", head); snprintf(key, sizeof key, "queue %s", head);
        }
        else if (!flock(lock_fd, LOCK_EX | LOCK_NB)) {
            pid_t old = ignore_legacy ? 0 : legacy_game();
            if (!old) break;
            flock(lock_fd, LOCK_UN);
            snprintf(reason, sizeof reason, "pid %d 的游戏没有接入游戏锁（旧版程序？），等它退出", old);
            snprintf(key, sizeof key, "legacy %d", old);
        } else {
            if (errno != EWOULDBLOCK) slot_fail("flock", lock_path);
            describe_holder(reason, sizeof reason);
            char hp[PATH_MAX], tok[48] = ""; path_in(hp, "holder"); kv_get(hp, "token", tok, sizeof tok);
            snprintf(key, sizeof key, "holder %s", tok);
            if (user) preempt_holder();
        }
        time_t now = time(NULL);
        if (max_wait >= 0 && now - start >= max_wait) {
            fprintf(stderr, "[game-slot] 等了 %lld 秒还没轮到（%s）；TOTK_GAME_SLOT_WAIT=%s，退出 75\n", (long long)(now - start), reason, mw);
            exit(75);
        }
        if (strcmp(key, last_key) || now - last_log >= 30) {
            fprintf(stderr, "[game-slot] 等待游戏位置：%s\n", reason);
            snprintf(last_key, sizeof last_key, "%s", key); last_log = now;
        }
        usleep(user ? 200000 : 1000000);
    }
    unlink(my_queue); my_queue[0] = 0;
    if (user) { char p[PATH_MAX]; path_in(p, "user-request"); if (kv_num(p, "pid") == getpid()) unlink(p); }
    clock_gettime(CLOCK_REALTIME, &ts);
    snprintf(token, sizeof token, "%llx-%d", (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec, getpid());
    acquired = 1; acquired_at = time(NULL);
    holder_write();
    char extra[64]; snprintf(extra, sizeof extra, "waited_s=%lld", (long long)(acquired_at - start));
    history("acquire", extra);
    fprintf(stderr, "[game-slot] 取得游戏位置（%s，%s）%s\n", owner, purpose, acquired_at > start ? "，等待结束" : "");
    agent_watch_start();
    dry_run();
}
#endif   /* !TARGET_OS_IPHONE */
