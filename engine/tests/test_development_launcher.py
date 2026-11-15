"""CPU-only native fixture: validates isolation setup without a game or Metal."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]


class DevelopmentLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / "fixture"
        source = Path(cls.build.name) / "fixture.m"
        source.write_text(r'''
#import <AppKit/AppKit.h>
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TOTK_GAME_DIR "oot"
static NSString *game_data_in(NSString *folder,unsigned long long size,NSString *sha) {
    (void)folder;(void)size;(void)sha;return nil;
}
#include "engine/app/kokiri_development.h"
static unsigned fixture_takeovers;
void runtime_game_slot_user_takeover(void) { fixture_takeovers++; }
int main(int argc,char **argv) { @autoreleasepool {
    BOOL human=argc==5 && !strcmp(argv[4],"human");
    if(argc!=4 && !human) {
        char **boot=NULL;
        if(argc>1 && !strcmp(argv[1],"--kokiri-preview"))return kokiri_human_preview_launch(argc,argv,&boot);
        return kokiri_development_launch(argc,argv,&boot);
    }
    NSDictionary *receipt=nil;
    if(!(human ? kokiri_private_prepare(@(argv[1]),@(argv[1]),@(argv[0]),@{},&receipt,YES) :
                 kokiri_dev_prepare(@(argv[1]),@(argv[1]),@(argv[0]),@{},&receipt)))return 2;
    if(strcmp(argv[3],"none")) {
        [[NSJSONSerialization dataWithJSONObject:receipt options:0 error:nil] writeToFile:[@(argv[1]) stringByAppendingPathComponent:@"isolation.json"] atomically:YES];
        runtime_kokiri_development_slot_acquired();
        int fd=open(argv[1],O_RDONLY|O_DIRECTORY);receipt=kokiri_dev_json(fd,"isolation.json");close(fd);
    }
    if(!strcmp(argv[3],"takeover"))runtime_kokiri_development_user_takeover();
    if(!strcmp(argv[3],"wrong-lease")) {
        int fd=open(argv[1],O_RDONLY|O_DIRECTORY);
        NSMutableDictionary *lease=[kokiri_dev_json(fd,"lease.json") mutableCopy];close(fd);
        lease[@"nonce"]=[@"" stringByPaddingToLength:64 withString:@"0" startingAtIndex:0];
        [[NSJSONSerialization dataWithJSONObject:lease options:0 error:nil] writeToFile:[@(argv[1]) stringByAppendingPathComponent:@"lease.json"] atomically:YES];
    }
    NSMutableDictionary *out=[receipt mutableCopy];
    out[@"active"]=@(runtime_kokiri_development_active());
    out[@"nonce_matches"]=@(runtime_kokiri_development_nonce_matches(argv[2]));
    out[@"slot_takeovers"]=@(fixture_takeovers);
    out[@"private_paths_ready"]=@(runtime_kokiri_private_paths_ready());
    out[@"position_allowed"]=@(runtime_kokiri_human_preview_command_allowed("oot-live mcp-0123456789abcdef0123 position\n"));
    out[@"close_allowed"]=@(runtime_kokiri_human_preview_command_allowed("close\n"));
    out[@"movement_allowed"]=@(runtime_kokiri_human_preview_command_allowed("oot-live mcp-0123456789abcdef0123 move CastleTown 1 2 3\n"));
    NSString *capture=[@(argv[1]) stringByAppendingPathComponent:@"captures/0123456789abcdef0123456789abcdef.png"];
    [NSData.data writeToFile:capture atomically:YES];
    out[@"capture_allowed"]=@(runtime_kokiri_human_preview_command_allowed([[NSString stringWithFormat:@"wshot %@\n",capture] UTF8String]));
    out[@"external_capture_allowed"]=@(runtime_kokiri_human_preview_command_allowed("wshot /tmp/0123456789abcdef0123456789abcdef.png\n"));
    NSMutableDictionary *environment=[NSMutableDictionary new];
    for(char **entry=*_NSGetEnviron();*entry;entry++) {
        NSString *row=@(*entry);NSRange equals=[row rangeOfString:@"="];
        environment[[row substringToIndex:equals.location]]=[row substringFromIndex:equals.location+1];
    }
    out[@"environment"]=environment;
    NSData *json=[NSJSONSerialization dataWithJSONObject:out options:NSJSONWritingSortedKeys error:nil];
    fwrite(json.bytes,1,json.length,stdout);return 0;
} }
''')
        compilation = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        "-I", str(REPOSITORY), str(source), "-framework", "AppKit", "-o", str(cls.binary)],
                       check=False, capture_output=True, text=True, timeout=60)
        if compilation.returncode:
            sys.stderr.write(compilation.stdout + compilation.stderr)
            compilation.check_returncode()
        cls.digest = hashlib.sha256(cls.binary.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = (Path(self.temporary.name) / "session").resolve()
        self.root.mkdir(mode=0o700)
        self.nonce = "a" * 64
        self.request = {"schema": 1, "session_id": "b" * 32, "nonce": self.nonce,
                        "expires_unix": time.time() + 600, "executable_sha256": self.digest}
        self.save_request()

    def tearDown(self):
        self.temporary.cleanup()

    def save_request(self):
        (self.root / "request.json").write_text(json.dumps(self.request))
        (self.root / "lease.json").write_text(json.dumps({key: self.request[key] for key in
            ("schema", "session_id", "nonce", "expires_unix")}))

    def run_fixture(self, action="none", human=False, **environment):
        # Poisoned optional paths are inert in this fixture (no constructors or
        # game). Production SessionManager must start with a clean allowlist.
        env = {**os.environ, "KOKIRI_DEVELOPMENT_ROOT": str(self.root),
               "KOKIRI_DEVELOPMENT_NONCE": self.nonce, **environment}
        if human:
            env["KOKIRI_HUMAN_PREVIEW_ROOT"] = str(self.root)
        return subprocess.run([str(self.binary), str(self.root), self.nonce, action, *(["human"] if human else [])], env=env,
                              capture_output=True, text=True, timeout=10)

    def test_private_paths_and_inherited_write_paths(self):
        result = self.run_fixture(TOTK_PROFILE_DIR="/forbidden/player", DM_SAVE="/forbidden/save",
                                  TOTK_SHADER_CONTRIB="/forbidden/contributions", TOTK_BOARD_DIR="/forbidden/board",
                                  KOKIRI_CATALOG_HANDOFF="/forbidden/catalog", TOTK_INPUT_SCRIPT="0:13:100")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["active"])
        self.assertFalse(receipt["nonce_matches"])
        self.assertFalse(receipt["game_slot_acquired"])
        for value in receipt["effective_paths"].values():
            self.assertTrue(Path(value).is_relative_to(self.root))
        env = receipt["environment"]
        self.assertEqual(env["TOTK_CONTROLS"], str(self.root / "settings/game/controls.txt"))
        self.assertEqual(env["TOTK_PROFILE_DIR"], str(self.root / "profile"))
        self.assertNotIn("TOTK_PIPELINE_ARCHIVE", env)
        for key in ["DM_SAVE", "TOTK_SHADER_CONTRIB", "TOTK_BOARD_DIR", "KOKIRI_CATALOG_HANDOFF", "TOTK_INPUT_SCRIPT"]:
            self.assertNotIn(key, env)

    def test_expired_and_overlong_requests_refused(self):
        for expiry in [time.time() - 1, time.time() + 1900]:
            self.request["expires_unix"] = expiry
            self.save_request()
            self.assertEqual(self.run_fixture().returncode, 2)

    def test_post_slot_hook_updates_only_acceptance_phase(self):
        result = self.run_fixture("slot-acquired")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["game_slot_acquired"])
        self.assertTrue(receipt["active"])
        self.assertTrue(receipt["nonce_matches"])
        self.assertEqual(receipt["phase"], "slot-acquired")
        self.assertEqual(receipt["executable_sha256"], self.digest)
        self.assertEqual(receipt["session_id"], self.request["session_id"])
        self.assertLessEqual(int(receipt["environment"]["TOTK_AGENT_LIMIT_S"]), 600)
        self.assertEqual(receipt["environment"]["TOTK_AGENT_GRACE_S"], "0")

    def test_wrong_digest_and_parent_nonce_refused(self):
        self.assertEqual(self.run_fixture(KOKIRI_DEVELOPMENT_NONCE="c" * 64).returncode, 2)
        self.request["executable_sha256"] = "0" * 64
        self.save_request()
        self.assertEqual(self.run_fixture().returncode, 2)

    def test_symlink_hardlink_and_special_file_refused(self):
        outside = self.root.parent / "outside"
        outside.write_text("untouched")
        target = self.root / "bad"
        target.symlink_to(outside)
        self.assertEqual(self.run_fixture().returncode, 2)
        target.unlink()
        os.link(outside, target)
        self.assertEqual(self.run_fixture().returncode, 2)
        target.unlink()
        os.mkfifo(target)
        self.assertEqual(self.run_fixture().returncode, 2)
        self.assertEqual(outside.read_text(), "untouched")

    def test_takeover_and_replaced_lease_revoke_controls(self):
        result = self.run_fixture("takeover")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["active"])
        self.assertEqual(json.loads(result.stdout)["slot_takeovers"], 1)
        self.assertTrue((self.root / "revoked").exists())
        (self.root / "revoked").unlink()
        (self.root / "isolation.json").unlink()
        result = self.run_fixture("wrong-lease")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["active"])

    def prepare_human(self):
        for name in ("request.json", "lease.json"):
            (self.root / name).unlink()
        request = {key: self.request[key] for key in ("schema", "session_id", "executable_sha256")}
        request.update(kind="human-preview", owner="user")
        (self.root / "preview.json").write_text(json.dumps(request))
        return request

    def test_human_preview_has_no_agent_lease_or_control(self):
        self.prepare_human()
        result = self.run_fixture("slot-acquired", human=True, TOTK_SLOT_OWNER="codex", TOTK_GAME_SLOT_FD="9")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["private_paths_ready"])
        self.assertFalse(receipt["active"])
        self.assertFalse(receipt["nonce_matches"])
        self.assertEqual(receipt["owner"], "user")
        self.assertEqual(receipt["control"], "observation-only")
        self.assertNotIn("expires_unix", receipt)
        self.assertNotIn("nonce", receipt)
        env = receipt["environment"]
        self.assertEqual(env["TOTK_SLOT_OWNER"], "user")
        for key in ("KOKIRI_DEVELOPMENT_ROOT", "KOKIRI_DEVELOPMENT_NONCE", "TOTK_AGENT_LIMIT_S", "TOTK_AGENT_IDLE_S", "TOTK_GAME_SLOT_FD"):
            self.assertNotIn(key, env)
        self.assertTrue(receipt["position_allowed"])
        self.assertTrue(receipt["capture_allowed"])
        self.assertFalse(receipt["close_allowed"])
        self.assertFalse(receipt["movement_allowed"])
        self.assertFalse(receipt["external_capture_allowed"])

    def test_human_preview_reopens_private_progress_without_lease(self):
        self.prepare_human()
        for _ in range(2):
            result = self.run_fixture("slot-acquired", human=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "lease.json").exists())

    def test_human_preview_not_ready_before_slot_acquisition(self):
        self.prepare_human()
        result = self.run_fixture(human=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["private_paths_ready"])
        self.assertFalse(receipt["position_allowed"])
        self.assertFalse(receipt["active"])

    def test_human_preview_rejects_agent_session_and_expiry(self):
        request = self.prepare_human()
        request["expires_unix"] = time.time() + 600
        (self.root / "preview.json").write_text(json.dumps(request))
        self.assertEqual(self.run_fixture(human=True).returncode, 2)
        del request["expires_unix"]
        (self.root / "preview.json").write_text(json.dumps(request))
        (self.root / "ownership.json").write_text("{}")
        self.assertEqual(self.run_fixture(human=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
