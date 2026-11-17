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
    BOOL human=(argc==5 || argc==7) && !strcmp(argv[4],"human");
    if(argc!=4 && !human) {
        char **boot=NULL;
        if(argc>1 && !strcmp(argv[1],"--kokiri-preview"))return kokiri_human_preview_launch(argc,argv,&boot);
        return kokiri_development_launch(argc,argv,&boot);
    }
    NSDictionary *receipt=nil;
    id capability=!strcmp(argv[3],"mods-bool") ? @YES : !strcmp(argv[3],"mods-unknown") ? @2 : @1;
    if(!(human ? kokiri_private_prepare_mods(@(argv[1]),@(argv[1]),@(argv[0]),@{@"KokiriHumanPreviewModsVersion":capability},&receipt,YES,
                                           argc==7 ? @(argv[5]) : nil,argc==7 ? @(argv[6]) : nil) :
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
    int mod=runtime_kokiri_human_mods_open("Content/file.bin");
    if(mod>=0) {
        struct stat validated;fstat(mod,&validated);
        out[@"mod_stable_before"]=@(romfs_overlay_unchanged(mod,&validated));
        if(!strcmp(argv[3],"mutate-mod-after-open")) {
            NSString *path=[@(argv[1]) stringByAppendingPathComponent:[NSString stringWithFormat:@"mods/%s/mods/Content/file.bin",argv[5]]];
            int writer=open(path.fileSystemRepresentation,O_WRONLY|O_NOFOLLOW);char changed[16];memset(changed,'x',sizeof changed);
            if(writer<0 || write(writer,changed,sizeof changed)!=sizeof changed)return 3;
            struct timespec times[2]={validated.st_atimespec,validated.st_mtimespec};
            if(futimens(writer,times))return 3;close(writer);
        }
        out[@"mod_stable_after"]=@(romfs_overlay_unchanged(mod,&validated));
        char value[128]={0};ssize_t length=read(mod,value,sizeof(value)-1);close(mod);if(length>0)out[@"mod_file"]=@(value);
    }
    out[@"mod_escape_refused"]=@(runtime_kokiri_human_mods_open("../outside")<0);
    unsigned remaining=64;int audit=open(argv[1],O_RDONLY|O_DIRECTORY);
    out[@"bounded_profile_scan"]=@(kokiri_dev_tree(audit,0,&remaining,YES));close(audit);
    remaining=64;audit=open(argv[1],O_RDONLY|O_DIRECTORY);
    out[@"bounded_full_scan"]=@(kokiri_dev_tree(audit,0,&remaining,NO));close(audit);
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

    def run_fixture(self, action="none", human=False, mods=(), **environment):
        # Poisoned optional paths are inert in this fixture (no constructors or
        # game). Production SessionManager must start with a clean allowlist.
        env = {**os.environ, "KOKIRI_DEVELOPMENT_ROOT": str(self.root),
               "KOKIRI_DEVELOPMENT_NONCE": self.nonce, **environment}
        if human:
            env["KOKIRI_HUMAN_PREVIEW_ROOT"] = str(self.root)
        return subprocess.run([str(self.binary), str(self.root), self.nonce, action, *(["human"] if human else []), *mods], env=env,
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
        self.assertEqual(env["TOTK_ROMFS_MODS"], "0")
        self.assertNotIn("KOKIRI_HUMAN_MOD_MANIFEST_SHA256", env)
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

    def prepare_mods(self):
        preview = self.prepare_human()
        self.mod_id = "d" * 32
        self.mod_folder = self.root / "mods" / self.mod_id
        self.mod_payload = self.mod_folder / "mods"
        for p in (self.root / "mods", self.mod_folder, self.mod_payload):
            p.mkdir(mode=0o700)
        (self.mod_payload / "Content").mkdir(mode=0o700)
        data = b"native-validated"
        (self.mod_payload / "Content/file.bin").write_bytes(data)
        manifest = f"Content/file.bin\t{len(data)}\t{hashlib.sha256(data).hexdigest()}\t{'b' * 64}\n"
        (self.mod_payload / "manifest.tsv").write_text(manifest)
        self.mod_record = {"schema": 1, "kind": "human-mod-overlay", "session_id": preview["session_id"],
                           "launch_id": self.mod_id, "executable_sha256": self.digest,
                           "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest()}
        self.save_mods()

    def save_mods(self):
        data = json.dumps(self.mod_record).encode()
        (self.mod_folder / "handoff.json").write_bytes(data)
        self.mod_hash = hashlib.sha256(data).hexdigest()

    def test_human_mods_keep_owner_and_use_descriptor_scoped_payload(self):
        self.prepare_mods()
        result = self.run_fixture("slot-acquired", human=True, mods=(self.mod_id, self.mod_hash),
                                  TOTK_ROMFS_MODS="/foreign/applied", KOKIRI_HUMAN_MOD_MANIFEST_SHA256="a" * 64)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["owner"], "user")
        self.assertEqual(receipt["control"], "observation-only")
        self.assertFalse(receipt["active"])
        self.assertFalse(receipt["movement_allowed"])
        self.assertFalse(receipt["close_allowed"])
        self.assertTrue(receipt["mod_escape_refused"])
        self.assertEqual(receipt["mod_file"], "native-validated")
        self.assertEqual(receipt["environment"]["TOTK_ROMFS_MODS"], str(self.mod_payload))
        self.assertEqual(receipt["environment"]["KOKIRI_HUMAN_MOD_MANIFEST_SHA256"], self.mod_record["manifest_sha256"])
        self.assertEqual(receipt["mods_handoff"]["launch_id"], self.mod_id)

    def test_human_mods_reject_capability_hash_mutation_and_stale_binding(self):
        self.prepare_mods()
        for action in ("mods-bool", "mods-unknown"):
            self.assertEqual(self.run_fixture(action, human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, "0" * 64)).returncode, 2)
        self.mod_record["session_id"] = "f" * 32
        self.save_mods()
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)

    def test_human_mods_reject_changed_payload_links_and_malformed_manifest(self):
        self.prepare_mods()
        target = self.mod_payload / "Content/file.bin"
        target.write_bytes(b"tampered")
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)
        outside = self.root.parent / "outside.bin"
        outside.write_bytes(b"native-validated")
        target.unlink()
        target.symlink_to(outside)
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)
        target.unlink()
        os.link(outside, target)
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)
        target.unlink()
        target.write_bytes(b"native-validated")
        manifest = "Content/file.bin\t16\t" + "a" * 64 + "\t-\textra\n"
        (self.mod_payload / "manifest.tsv").write_text(manifest)
        self.mod_record["manifest_sha256"] = hashlib.sha256(manifest.encode()).hexdigest()
        self.save_mods()
        self.assertEqual(self.run_fixture(human=True, mods=(self.mod_id, self.mod_hash)).returncode, 2)

    def test_private_overlay_detects_in_place_mutation_after_open_with_restored_mtime(self):
        self.prepare_mods()
        result = self.run_fixture("mutate-mod-after-open", human=True, mods=(self.mod_id, self.mod_hash))
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["mod_stable_before"])
        self.assertFalse(receipt["mod_stable_after"])

    def test_inert_snapshot_history_does_not_consume_unmodded_profile_audit(self):
        self.prepare_human()
        history = self.root / "mods/history"
        history.mkdir(mode=0o700, parents=True)
        for n in range(100):
            (history / str(n)).write_text("inert old snapshot")
        result = self.run_fixture(human=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["bounded_profile_scan"])
        self.assertFalse(receipt["bounded_full_scan"])
        self.assertEqual(receipt["environment"]["TOTK_ROMFS_MODS"], "0")

    def test_development_entry_rejects_all_preview_markers_before_writes(self):
        marker = self.root / "preview.json"
        for kind in ("regular", "directory", "dangling-symlink", "fifo"):
            with self.subTest(kind=kind):
                if kind == "regular":
                    marker.write_text('{"owner":"user"}')
                elif kind == "directory":
                    marker.mkdir()
                elif kind == "dangling-symlink":
                    marker.symlink_to(self.root / "missing-preview")
                else:
                    os.mkfifo(marker)
                before = {p.name: p.lstat() for p in self.root.iterdir()}
                result = self.run_fixture()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual({p.name for p in self.root.iterdir()}, set(before))
                for name, previous in before.items():
                    current = (self.root / name).lstat()
                    self.assertEqual((current.st_ino, current.st_size, current.st_mtime_ns),
                                     (previous.st_ino, previous.st_size, previous.st_mtime_ns))
                self.assertFalse((self.root / "profile").exists())
                marker.rmdir() if kind == "directory" else marker.unlink()


if __name__ == "__main__":
    unittest.main()
