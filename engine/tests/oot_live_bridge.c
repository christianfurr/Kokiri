/* CPU fixture: actual bridge parser, queue and compatibility/file gates. No game
 * code, external process access, GPU or save writes. Module memory is synthetic. */
#include <assert.h>
#include <sys/mman.h>
#include <sys/types.h>
#include "runtime.h"
static uint64_t fixture_now = 1000000000ULL;
uint64_t runtime_now_ns(void) { return fixture_now; }
int runtime_fs_save_busy(void) { return 0; }
#include "oot_live.h"

static unsigned checked;
#define CHECK(x, label) do { if (!(x)) { fprintf(stderr, "FAILED: %s\n", label); return 2; } checked++; } while (0)

static void bridge_reset(void) {
    if (oot_live_fd >= 0) close(oot_live_fd);
    oot_live_fd = -1; oot_live_main = 0;
    atomic_store(&oot_live_unavailable, 0);
    memset(&oot_live_request, 0, sizeof oot_live_request);
    atomic_store(&oot_live_pending, 0);
}
static int last_status(const char *path, const char *want) {
    FILE *f = fopen(path, "r"); if (!f) return 0;
    char line[512], last[512] = {0};
    while (fgets(line, sizeof line, f)) memcpy(last, line, strlen(line) + 1);
    fclose(f);
    char match[128]; snprintf(match, sizeof match, "\"status\":\"%s\"", want);
    return strstr(last, match) != NULL;
}
static void *publish_bridge(void *module) { runtime_oot_live_init(module); return NULL; }
static void *query_during_publication(void *ignored) {
    (void)ignored;
    for (unsigned i = 0; i < 32; i++) runtime_oot_live_command("oot-live concurrent position\n");
    return NULL;
}
int main(int argc, char **argv) {
    CHECK(argc == 2, "private temporary root supplied");
    char status[PATH_MAX], alias[PATH_MAX], fifo[PATH_MAX], profile[PATH_MAX];
    CHECK(snprintf(status, sizeof status, "%s/status.jsonl", argv[1]) < (int)sizeof status, "status path bound");
    CHECK(snprintf(alias, sizeof alias, "%s/status-link", argv[1]) < (int)sizeof alias, "alias path bound");
    CHECK(snprintf(fifo, sizeof fifo, "%s/status-fifo", argv[1]) < (int)sizeof fifo, "fifo path bound");
    CHECK(snprintf(profile, sizeof profile, "%s/profile-copy", argv[1]) < (int)sizeof profile, "profile path bound");
    CHECK(mkdir(profile, 0700) == 0, "synthetic disposable profile created");
    int fd = open(status, O_WRONLY | O_CREAT | O_TRUNC, 0600); CHECK(fd >= 0, "owned status file created"); close(fd);
    setenv("TOTK_INPUT_FILE", "/unused-synthetic-input", 1);
    setenv("TOTK_SLOT_OWNER", "user", 1); setenv("TOTK_PROFILE_DIR", profile, 1);
    unsetenv("TOTK_EXPORT_IOS"); unsetenv("OOT_EDITOR_STATUS");
    const size_t size = OOT_LIVE_ACTORS + 0x100000;
    unsigned char *bytes = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    CHECK(bytes != MAP_FAILED, "sparse synthetic module reserved");
    Module module = {.name = "main", .base = bytes, .size = size};
    runtime_oot_live_init(&module); CHECK(oot_live_fd < 0, "feature off without explicit status path");
    setenv("OOT_EDITOR_STATUS", status, 1);
    CHECK(runtime_oot_live_command("oot-live early position\n") == 1 && !atomic_load(&oot_live_pending) && last_status(status, "not-ready"), "pre-init query has terminal not-ready reply");
    runtime_oot_live_init(&module); CHECK(oot_live_fd < 0, "wrong module fingerprints fail closed");
    CHECK(runtime_oot_live_command("oot-live incompatible position\n") == 1 && last_status(status, "unsupported"), "failed compatibility announced without world access");
    const struct { size_t off; uint32_t word; } words[] = {
        {0x6b254c, 0xf9401000}, {0x6b25b8, 0xf9412908}, {0xd7a820, 0xb940b808}, {0x32db244, 0xf9404908},
        {0x4b6db4, 0xd10083ff}, {0xd79f14, 0xa9bd7bfd}, {0x20b6f4, 0xa9bc7bfd}, {0x12dbe4, 0xfc1c0fe8}
    };
    for (unsigned i = 0; i < sizeof words / sizeof *words; i++) memcpy(bytes + words[i].off, &words[i].word, 4);
    CHECK(symlink(status, alias) == 0, "synthetic symlink created");
    setenv("OOT_EDITOR_STATUS", alias, 1); runtime_oot_live_init(&module);
    CHECK(oot_live_fd < 0, "symlink status rejected");
    CHECK(mkfifo(fifo, 0600) == 0, "synthetic FIFO created");
    setenv("OOT_EDITOR_STATUS", fifo, 1); runtime_oot_live_init(&module);
    CHECK(oot_live_fd < 0, "FIFO rejected without waiting for a reader");
    setenv("OOT_EDITOR_STATUS", status, 1); runtime_oot_live_init(&module);
    CHECK(oot_live_fd >= 0 && last_status(status, "ready"), "compatible bridge announces protocol ready only");
    int held_fd = oot_live_fd; runtime_oot_live_init(&module); CHECK(oot_live_fd == held_fd, "repeat initialization does not replace/leak descriptor");
    CHECK(runtime_oot_live_command("key 38 100\n") == 0, "unrelated input preserved");
    CHECK(runtime_oot_live_command("oot-live sample position\n") == 1 && atomic_load(&oot_live_pending), "normal player can queue position");
    CHECK(runtime_oot_live_command("oot-live second position\n") == 1 && last_status(status, "busy"), "single outstanding request enforced");
    CHECK(!strcmp(oot_live_request.id, "sample"), "busy request cannot replace owner");
    runtime_oot_live_tick(); CHECK(!atomic_load(&oot_live_pending) && last_status(status, "not-ready"), "protocol ready is not a playable world");
    CHECK(runtime_oot_live_command("oot-live move-normal move MountainTrail_Child 1 2 3\n") == 1 && !atomic_load(&oot_live_pending) && last_status(status, "read-only"), "normal move rejected");
    CHECK(runtime_oot_live_command("oot-live warp-normal warp field\n") == 1 && !atomic_load(&oot_live_pending) && last_status(status, "read-only"), "normal warp rejected");
    CHECK(runtime_oot_live_command("oot-live bad-token! position\n") == 1 && !atomic_load(&oot_live_pending), "invalid id never queued");
    CHECK(runtime_oot_live_command("oot-live bad-number move MountainTrail_Child nan 2 3\n") == 1 && last_status(status, "invalid"), "nonfinite move never queued");
    CHECK(runtime_oot_live_command("oot-live extra position unexpected\n") == 1 && last_status(status, "invalid"), "extra command bytes rejected");
    setenv("TOTK_SLOT_OWNER", "kokiri-verification", 1);
    CHECK(oot_live_mutations_allowed(), "owned disposable profile enables test mutation");
    CHECK(runtime_oot_live_command("oot-live expires move MountainTrail_Child 1 2 3\n") == 1 && atomic_load(&oot_live_pending), "owned test mutation queued");
    fixture_now += 6000000000ULL; runtime_oot_live_tick();
    CHECK(!atomic_load(&oot_live_pending) && last_status(status, "expired"), "expiry occurs before actor lookup or mutation");
    CHECK(runtime_oot_live_command("oot-live revoke warp field\n") == 1 && atomic_load(&oot_live_pending), "owned warp queued");
    setenv("TOTK_SLOT_OWNER", "user", 1); runtime_oot_live_tick();
    CHECK(!atomic_load(&oot_live_pending) && last_status(status, "read-only"), "ownership revoked before mutation");
    setenv("TOTK_SLOT_OWNER", "kokiri-verification", 1);
    struct passwd *pw = getpwuid(getuid()); CHECK(pw && pw->pw_dir, "actual account home available");
    setenv("TOTK_PROFILE_DIR", pw->pw_dir, 1);
    CHECK(!oot_live_mutations_allowed(), "ancestor of real profile trees rejected");
    CHECK(oot_live_related_path("/", "/somewhere") && oot_live_related_path("/a/profile", "/a/profile/save") && !oot_live_related_path("/a/profile-copy", "/a/profile"), "canonical path component boundaries");
    bridge_reset();
    pthread_t publishers[2], observer;
    CHECK(pthread_create(&observer, NULL, query_during_publication, NULL) == 0, "startup observer created");
    CHECK(pthread_create(&publishers[0], NULL, publish_bridge, &module) == 0, "first publisher created");
    CHECK(pthread_create(&publishers[1], NULL, publish_bridge, &module) == 0, "second publisher created");
    CHECK(pthread_join(observer, NULL) == 0 && pthread_join(publishers[0], NULL) == 0 && pthread_join(publishers[1], NULL) == 0, "startup participants joined");
    CHECK(oot_live_fd >= 0 && atomic_load(&oot_live_main) == (uintptr_t)bytes, "parallel publication leaves complete valid bridge");
    if (atomic_load(&oot_live_pending)) runtime_oot_live_tick();
    CHECK(!atomic_load(&oot_live_pending), "startup request reaches a terminal state");
    bridge_reset(); munmap(bytes, size);
    printf("oot live bridge: %u checks PASS\n", checked); return 0;
}
