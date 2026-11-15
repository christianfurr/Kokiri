"""CPU fixture using the actual slot code and queued frontend close functions.

No game, window, signal, GPU or shared slot is used. A fake window counts closes;
kill is intercepted inside the fixture. Native compilation requires the CPU slot.
"""
import json
import os
import select
from pathlib import Path
import subprocess
import sys
import sys
import tempfile
import time
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]


def function(source, name):
    start = source.index("void " + name + "(")
    cursor = source.index("{", start)
    depth = 1
    end = cursor + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class GameSlotTakeoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / "fixture"
        source = Path(cls.build.name) / "fixture.m"
        frontend = (REPOSITORY / "engine/runtime/frontend.m").read_text()
        closes = "\n".join(function(frontend, name) for name in
                           ("runtime_front_request_close", "runtime_front_request_agent_close"))
        source.write_text(r'''
#import <AppKit/AppKit.h>
#include <stdatomic.h>
#include <libproc.h>
#include <time.h>
#include <unistd.h>
static int fixture_signals, fixture_signals_after_takeover, fixture_closes;
static int fixture_replace_holder,fixture_replaced_holder;
static char fixture_holder_path[4096];
static time_t fixture_offset;
static time_t fixture_time(time_t *out);
static int fixture_proc_pidpath(int pid,void *buffer,uint32_t size);
static ssize_t fixture_read(int fd,void *buffer,size_t size);
int fixture_kill(pid_t pid,int signal);
#define kill fixture_kill
#define time fixture_time
#define proc_pidpath fixture_proc_pidpath
#define read fixture_read
#include "engine/runtime/game_slot.c"
#undef kill
#undef time
#undef proc_pidpath
#undef read
static time_t fixture_time(time_t *out) { time_t value=time(NULL)+fixture_offset;if(out)*out=value;return value; }
static int fixture_proc_pidpath(int pid,void *buffer,uint32_t size) {
    (void)pid;return snprintf(buffer,size,"/private/fixture/Game.app/Contents/MacOS/KokiriGame");
}
static void fixture_publish_human(void) {
    char text[256];snprintf(text,sizeof text,"owner=user\ntoken=new-human\npurpose=fixture\ngame_pid=%d\ngame_start=%llu\n",getpid(),(unsigned long long)pid_start(getpid()));
    write_atomic(fixture_holder_path,text);fixture_replaced_holder=1;
}
static ssize_t fixture_read(int fd,void *buffer,size_t size) {
    ssize_t count=read(fd,buffer,size);char path[4096];
    if(count>0&&fixture_replace_holder&&fcntl(fd,F_GETPATH,path)>=0&&!strcmp(path,fixture_holder_path)) {
        fixture_replace_holder=0;fixture_publish_human();
    }
    return count;
}
int fixture_kill(pid_t pid,int signal) {
    (void)pid;(void)signal;fixture_signals++;
    if(atomic_load(&agent_user_takeover))fixture_signals_after_takeover++;
    return 0;
}
_Noreturn void runtime_fail(const char *message) { fprintf(stderr,"%s\n",message);exit(97); }
uint64_t dm_nvn_frame_count(void) { return 1; }
@interface FixtureWindow:NSObject
-(void)performClose:(id)sender;
@end
@implementation FixtureWindow
-(void)performClose:(id)sender { (void)sender;fixture_closes++; }
@end
static FixtureWindow *window;
''' + closes + r'''
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=3)return 2;
    snprintf(slot_dir,sizeof slot_dir,"%s",argv[1]);
    if(!preemption_guard_open())return 98;
    if(!strcmp(argv[2],"atomic-publication")||!strcmp(argv[2],"mixed-generation-negative")) {
        path_in(fixture_holder_path,"holder");char folder[PATH_MAX];path_in(folder,"preempted");mkdir(folder,0700);
        write_atomic(fixture_holder_path,"owner=codex\ntoken=old-agent\npurpose=fixture\ngame_pid=2147483647\ngame_start=1\n");
        if(!strcmp(argv[2],"atomic-publication")) { fixture_replace_holder=1;preempt_holder(); }
        else {
            /* Historical negative control: separate opens pair the old owner
               with the new human's PID after an atomic publisher replacement. */
            char who[40];kv_get(fixture_holder_path,"owner",who,sizeof who);fixture_publish_human();
            pid_t target=(pid_t)kv_num(fixture_holder_path,"game_pid");
            if(strcmp(who,"user")&&pid_same(target,(uint64_t)kv_num(fixture_holder_path,"game_start")))fixture_kill(target,SIGTERM);
        }
        printf("{\"signals\":%d,\"replaced\":%d}\n",fixture_signals,fixture_replaced_holder);return 0;
    }
    if(!strcmp(argv[2],"preempt")||!strcmp(argv[2],"preempt-wait")) {
        preempt_holder();printf("{\"signals\":%d}\n",fixture_signals);fflush(stdout);
        if(!strcmp(argv[2],"preempt-wait")) {
            (void)getchar();fixture_offset=20;preempt_holder();
            printf("{\"signals\":%d}\n",fixture_signals);fflush(stdout);
        }
        return 0;
    }
    if(!strcmp(argv[2],"human-before-slot")) {
        setenv("TOTK_SLOT_OWNER","user",1);
        int allowed=runtime_game_slot_agent_close_begin();if(allowed)runtime_game_slot_agent_close_end();
        printf("{\"allowed\":%d}\n",allowed);return 0;
    }
    snprintf(owner,sizeof owner,"%s",!strcmp(argv[2],"human-owned") ? "user" : "codex");snprintf(purpose,sizeof purpose,"fixture");
    snprintf(mode_name,sizeof mode_name,"boot");snprintf(token,sizeof token,"fixture");
    acquired=1;acquired_at=time(NULL);holder_write();window=[FixtureWindow new];
    if(!strcmp(argv[2],"protect")||!strcmp(argv[2],"protect-io-failure")) {
        if(!strcmp(argv[2],"protect-io-failure")) {
            char fail[PATH_MAX];snprintf(fail,sizeof fail,"%s/holder.%d.tmp",slot_dir,getpid());mkdir(fail,0700);
        }
        runtime_game_slot_user_takeover();
        printf("{\"protected\":%d}\n",preemption_retained);fflush(stdout);
        (void)getchar();return 0;
    }
    if(!strcmp(argv[2],"term-then-takeover")) {
        char folder[PATH_MAX];path_in(folder,"preempted");mkdir(folder,0700);
        preempt_holder();runtime_game_slot_user_takeover();fixture_offset=20;preempt_holder();
        printf("{\"signals\":%d,\"protected\":%d}\n",fixture_signals,preemption_retained);return 0;
    }
    if(!strcmp(argv[2],"ordinary"))runtime_front_request_close();
    else agent_close(AGENT_LIMIT_OVER,100,0,0);
    if(strcmp(argv[2],"agent-owned") && strcmp(argv[2],"human-owned")) {
        runtime_game_slot_user_takeover();
        for(unsigned i=0;i<10;i++)agent_stop_if_owned();
    }
    dispatch_async(dispatch_get_main_queue(),^{
        char path[PATH_MAX],published[40]="";path_in(path,"holder");
        kv_get(path,"owner",published,sizeof published);
        printf("{\"closes\":%d,\"signals\":%d,\"signals_after_takeover\":%d,\"owner\":\"%s\",\"taken_over\":%d}\n",
            fixture_closes,fixture_signals,fixture_signals_after_takeover,published,atomic_load(&agent_user_takeover));
        fflush(stdout);exit(0);
    });
    dispatch_main();
} }
''')
        # The extracted frontend sees strong fixture gate definitions in this TU;
        # production uses weak imports. Suppress only that address-folding warning.
        compilation = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        "-Wno-pointer-bool-conversion", "-I", str(REPOSITORY), str(source),
                        "-framework", "AppKit", "-o", str(cls.binary)],
                       capture_output=True, text=True, check=False, timeout=60)
        if compilation.returncode:
            sys.stderr.write(compilation.stdout + compilation.stderr)
            compilation.check_returncode()

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def run_fixture(self, mode):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([str(self.binary), str(Path(temporary).resolve()), mode], capture_output=True,
                                    text=True, check=True, timeout=5)
            return json.loads(result.stdout)

    def test_queued_agent_close_canceled_by_takeover(self):
        result = self.run_fixture("takeover")
        self.assertEqual(result["closes"], 0)
        self.assertEqual(result["owner"], "user")
        self.assertEqual(result["taken_over"], 1)

    def test_human_owner_refuses_agent_close_without_physical_takeover(self):
        result = self.run_fixture("human-owned")
        self.assertEqual(result["closes"], 0)
        self.assertEqual(result["taken_over"], 0)
        self.assertEqual(result["owner"], "user")

    def test_human_owner_refuses_agent_close_before_slot_acquisition(self):
        self.assertEqual(self.run_fixture("human-before-slot")["allowed"], 0)

    def test_agent_escalation_stays_disarmed_after_takeover(self):
        result = self.run_fixture("takeover")
        self.assertEqual(result["signals"], 0)
        self.assertEqual(result["signals_after_takeover"], 0)

    def test_normal_close_remains_effective_after_takeover(self):
        result = self.run_fixture("ordinary")
        self.assertEqual(result["closes"], 1)
        self.assertEqual(result["owner"], "user")

    def test_agent_close_still_runs_without_takeover(self):
        result = self.run_fixture("agent-owned")
        self.assertEqual(result["closes"], 1)
        self.assertEqual(result["owner"], "codex")
        self.assertEqual(result["taken_over"], 0)

    @staticmethod
    def python_guard(directory):
        # Import the actual script helper, not a reimplementation of flock.
        sys.path.insert(0, str(REPOSITORY / "engine/scripts/dev"))
        import game_slot
        return game_slot.preemption_guard(directory)

    def packet(self, process):
        wire=b"";deadline=time.monotonic()+5
        while b"\n" not in wire:
            ready,_,_=select.select([process.stdout],[],[],max(0,deadline-time.monotonic()))
            self.assertTrue(ready,"Timed out waiting for the bounded native fixture reply")
            chunk=os.read(process.stdout.fileno(),1024)
            self.assertTrue(chunk,"Native fixture exited before its reply")
            wire+=chunk
            self.assertLess(len(wire),4096)
        return json.loads(wire)

    def test_native_takeover_blocks_independent_c_and_python_preempters(self):
        for mode in ("protect", "protect-io-failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                process=subprocess.Popen([str(self.binary),temporary,mode],stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    self.assertEqual(self.packet(process)["protected"],1)
                    with self.assertRaises(BlockingIOError):
                        with self.python_guard(temporary):
                            self.fail("A retained native guard must block the Python body")
                    result=subprocess.run([str(self.binary),temporary,"preempt"],capture_output=True,text=True,check=True,timeout=5)
                    self.assertEqual(json.loads(result.stdout)["signals"],0)
                finally:
                    process.communicate("\n",timeout=5)
                # Exit releases the kernel lock; the persistent inode remains.
                with self.python_guard(temporary):
                    self.assertTrue((Path(temporary)/"preemption.lock").is_file())

    def test_python_guard_blocks_native_preemption(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.seed_agent_holder(temporary)
            with self.python_guard(temporary):
                result=subprocess.run([str(self.binary),temporary,"preempt"],capture_output=True,text=True,check=True,timeout=5)
                self.assertEqual(json.loads(result.stdout)["signals"],0)
            # Negative control: the same fresh target is eligible once unlocked.
            result=subprocess.run([str(self.binary),temporary,"preempt"],capture_output=True,text=True,check=True,timeout=5)
            self.assertEqual(json.loads(result.stdout)["signals"],1)

    @staticmethod
    def seed_agent_holder(directory):
        sys.path.insert(0,str(REPOSITORY/"engine/scripts/dev"))
        import game_slot
        folder=Path(directory);(folder/"preempted").mkdir(exist_ok=True)
        game_slot.kv_write(folder/"holder",{"owner":"codex","token":"synthetic","purpose":"fixture",
            "game_pid":os.getpid(),"game_start":game_slot.pid_start(os.getpid())})

    def test_interprocess_guard_blocks_previously_scheduled_kill_escalation(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.seed_agent_holder(temporary)
            process=subprocess.Popen([str(self.binary),temporary,"preempt-wait"],stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(self.packet(process)["signals"],1)
                with self.python_guard(temporary):
                    process.stdin.write("\n");process.stdin.flush()
                    self.assertEqual(self.packet(process)["signals"],1)
                    process.wait(timeout=5)
            finally:
                if process.poll() is None:process.kill()
                process.communicate(timeout=5)

    def test_term_then_takeover_prevents_late_escalation(self):
        result=self.run_fixture("term-then-takeover")
        self.assertEqual(result["signals"],1)
        self.assertEqual(result["protected"],1)

    def test_guard_symlink_hardlink_and_fifo_fail_closed(self):
        for kind in ("symlink","hardlink","fifo"):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary);outside=folder/"original";outside.write_text("preserved")
                guard=folder/"preemption.lock"
                if kind=="symlink":guard.symlink_to(outside)
                elif kind=="hardlink":os.link(outside,guard)
                else:os.mkfifo(guard)
                result=subprocess.run([str(self.binary),temporary,"preempt"],capture_output=True,timeout=5)
                self.assertEqual(result.returncode,98)
                with self.assertRaises(OSError):
                    with self.python_guard(folder):self.fail("Malformed guard body must not run")
                self.assertEqual(outside.read_text(),"preserved")

    def test_atomic_holder_publication_cannot_mix_old_owner_and_new_pid(self):
        result=self.run_fixture("atomic-publication")
        self.assertEqual(result,{"signals":0,"replaced":1})
        negative=self.run_fixture("mixed-generation-negative")
        self.assertEqual(negative,{"signals":1,"replaced":1})

    def test_malformed_holder_records_cannot_signal_or_escape_marker_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.seed_agent_holder(temporary)
            folder=Path(temporary);valid=(folder/"holder").read_text()
            records=[valid+"owner=user\n",valid.replace("game_start=","unused="),
                     valid.replace("token=synthetic","token=../escaped"),
                     valid.replace("game_start=","game_start=-"),valid+"unknown="+"x"*4096]
            for record in records:
                with self.subTest(record=record[:80]):
                    (folder/"holder").write_text(record)
                    result=subprocess.run([str(self.binary),temporary,"preempt"],capture_output=True,text=True,check=True,timeout=5)
                    self.assertEqual(json.loads(result.stdout)["signals"],0)
                    self.assertFalse((folder/"escaped").exists())


if __name__ == "__main__":
    unittest.main()
