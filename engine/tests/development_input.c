/* CPU-only fixture: actual typed header and exact extracted input.c functions.
 * No app/game launch, framework, Metal, timing benchmark or player data. */
#include <assert.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Preserve weak-import declarations while the actual production functions and
 * typed header are parsed. Local definitions follow those uses below, matching
 * production's separately linked hooks without suppressing any warnings. */
extern int runtime_kokiri_development_active(void) __attribute__((weak_import));
extern int runtime_kokiri_development_nonce_matches(const char *) __attribute__((weak_import));
extern void runtime_kokiri_development_user_takeover(void) __attribute__((weak_import));

#define GAME_OOT 1
#define TARGET_OS_IPHONE 0
typedef struct { int64_t sampling; uint64_t buttons; int32_t lx,ly,rx,ry; uint32_t attributes,pad; } NpadState;
typedef struct { uint64_t buttons; int32_t lx,ly,rx,ry; } KeyMapOutput;
typedef KeyMapOutput RuntimeGamepadState;
static pthread_mutex_t inputLock = PTHREAD_MUTEX_INITIALIZER;
static unsigned char keys[128]; static uint64_t pending, padSeen;
static uint32_t styles = 1; static bool enabled = true, allowed = true;
static int64_t sample, kokiriDevDelivered;
static uint64_t kokiriDevButtons;
static int32_t kokiriDevAxes[4];
static _Atomic int kokiriDevInputActive;
static KeyMapOutput heldOut;
static RuntimeGamepadState physical;
static int leaseActive = 1, mode, polls, takeoverCount;
static uint64_t seenButtons;
static int32_t seenLeftX, seenRightX;
static const char *nonce = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
enum { NO_POLLS, ELIGIBLE_POLLS, INELIGIBLE_POLLS, EXPIRE_BEFORE_POLL, HUMAN_BEFORE_POLL };

static void require(int okay, const char *message) {
    if (!okay) { fprintf(stderr,"FAILED: %s\n",message); exit(2); }
}
_Noreturn static void runtime_fail(const char *message) { fprintf(stderr,"unexpected runtime failure: %s\n",message); exit(3); }
static void input_log(const char *what, uint32_t id) { (void)what; (void)id; }
static uint32_t pad_id(void) { return 0; }
static uint32_t pad_style(void) { return 1; }
static int ignore_user(void) { return 0; }
static void runtime_gamepad_read(RuntimeGamepadState *out) { *out = physical; }
static void runtime_slot_activity(int user) { (void)user; }
static void runtime_survey_cancel_user(void) {}
static void runtime_autoload_user_input(void) {}
static uint64_t runtime_now_ns(void) { return 1; }
uint64_t runtime_opening_auto_skip_buttons(void) { return 0; }
static int runtime_vr_stick_pitch_locked(void) { return 0; }
static uint64_t runtime_input_trace_next(void) { return 0; }
static void runtime_settings_page(int page) { (void)page; }
static void runtime_front_request_agent_close(void) {}
static int runtime_oot_live_command(const char *line) { (void)line; return 1; }
// ACTUAL_BUTTON_FUNCTION
// ACTUAL_USER_INPUT_FUNCTION
// ACTUAL_PAD_STATES_FUNCTION

static int fixture_sleep(useconds_t duration) {
    (void)duration;
    if (mode == NO_POLLS) return 0;
    if (mode == EXPIRE_BEFORE_POLL) leaseActive = 0;
    if (mode == HUMAN_BEFORE_POLL) { physical.buttons = 2; physical.lx = 30000; }
    uint32_t id = mode == INELIGIBLE_POLLS ? 7 : 0;
    NpadState out = {0};
    pad_states(&out,1,&id,1);
    polls++;
    seenButtons |= out.buttons;
    if (out.lx) seenLeftX = out.lx;
    if (out.rx) seenRightX = out.rx;
    return 0;
}
#define usleep fixture_sleep
#include "kokiri_development_input.h"
#undef usleep

int runtime_kokiri_development_active(void) { return leaseActive; }
int runtime_kokiri_development_nonce_matches(const char *candidate) { return leaseActive && !takeoverCount && !strcmp(candidate,nonce); }
/* Model a revocation becoming visible to the command owner before its on-disk
 * lease read catches up. The poll must cancel agent input immediately itself. */
void runtime_kokiri_development_user_takeover(void) {
    int result=pthread_mutex_trylock(&inputLock);
    require(result==0,"ownership takeover hook runs outside inputLock");
    pthread_mutex_unlock(&inputLock);
    takeoverCount++;
}

static char reply[1024];
static void reset(const char *file, int nextMode) {
    FILE *stream = fopen(file,"w"); require(stream != NULL,"create private reply"); fclose(stream);
    memset(keys,0,sizeof keys); pending=0; padSeen=0; physical=(RuntimeGamepadState){0};
    memset(kokiriDevAxes,0,sizeof kokiriDevAxes); kokiriDevButtons=0; kokiriDevDelivered=0;
    atomic_store(&kokiriDevInputActive,0); leaseActive=1; mode=nextMode; polls=takeoverCount=0;
    seenButtons=0; seenLeftX=seenRightX=0; reply[0]=0; sample=0;
}
static void command_nonce(const char *file, const char *operation, const char *token) {
    char line[256]; snprintf(line,sizeof line,"kokiri-dev %s dev-fixture %s\n",token,operation);
    require(kokiri_dev_command(line)==1,"typed header recognizes command");
    FILE *stream=fopen(file,"r");require(stream!=NULL,"read private reply");
    size_t count=fread(reply,1,sizeof reply-1,stream);reply[count]=0;fclose(stream);
}
static void command(const char *file, const char *operation) { command_nonce(file,operation,nonce); }
static void released(void) {
    require(!atomic_load(&kokiriDevInputActive) && !kokiriDevButtons,"button input released");
    require(!kokiriDevAxes[0] && !kokiriDevAxes[1] && !kokiriDevAxes[2] && !kokiriDevAxes[3],"stick input released");
    for(unsigned i=0;i<128;i++) require(!keys[i],"development input does not use synthetic keys");
    require(!pending,"development input does not latch pending buttons");
}
static NpadState later_poll(void) {
    uint32_t id=0;NpadState out={0};pad_states(&out,1,&id,1);return out;
}
int main(int argc,char **argv) {
    require(argc==2,"private reply path argument");
    const char *file=argv[1];setenv("OOT_EDITOR_STATUS",file,1);

    reset(file,NO_POLLS);command(file,"button a 100");
    require(strstr(reply,"\"status\":\"undelivered\"") && strstr(reply,"\"guest_polls\":0"),"zero-poll hold is undelivered");
    released();leaseActive=0;
    require(later_poll().buttons==0,"zero-poll command cannot appear after its lease");

    reset(file,INELIGIBLE_POLLS);command(file,"button a 100");
    require(polls>0 && sample>0 && kokiriDevDelivered==0,"ineligible guest reads do not count as delivery");
    require(strstr(reply,"\"status\":\"undelivered\"")!=NULL,"ineligible-poll hold is undelivered");released();

    reset(file,ELIGIBLE_POLLS);command(file,"button a 100");
    require(strstr(reply,"\"status\":\"completed\"") && kokiriDevDelivered>0,"eligible guest sees completed input");
    require(seenButtons==1,"actual eligible guest receives A");released();
    require(later_poll().buttons==0,"button release reaches subsequent guest poll");

    reset(file,ELIGIBLE_POLLS);command(file,"stick right 0.5 -0.25 100");
    require(strstr(reply,"\"status\":\"completed\"") && seenRightX==16383,"actual eligible guest receives camera stick");
    released();require(later_poll().rx==0,"camera stick returns to neutral");

    reset(file,EXPIRE_BEFORE_POLL);command(file,"stick left -1 0.5 100");
    require(strstr(reply,"\"status\":\"lease-refused\"")!=NULL,"expiry rejects active hold");
    require(kokiriDevDelivered==0 && seenLeftX==0,"expired input never reaches an eligible guest poll");released();

    reset(file,HUMAN_BEFORE_POLL);command(file,"stick left -1 0 100");
    require(kokiriDevDelivered==0 && seenLeftX==30000,"physical stick wins in takeover poll");
    require(takeoverCount>0 && strstr(reply,"\"status\":\"lease-refused\""),"physical input revokes active hold");
    require(seenButtons==2,"physical button survives takeover without agent buttons");released();

    reset(file,HUMAN_BEFORE_POLL);command(file,"button a 100");
    require(kokiriDevDelivered==0 && seenButtons==2,"agent button is absent from physical takeover poll");released();

    reset(file,NO_POLLS);command(file,"button a 5001");
    require(strstr(reply,"\"status\":\"invalid\"")!=NULL,"unbounded hold rejected");released();
    reset(file,ELIGIBLE_POLLS);command_nonce(file,"button a 100","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
    require(strstr(reply,"\"status\":\"lease-refused\"") && polls==0,"foreign nonce cannot start input");released();
    puts("development input: actual typed header and production guest-poll/takeover checks PASS");
    return 0;
}
