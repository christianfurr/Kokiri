"""Pure mocked spawn checks; no executable, game, subprocess or native build runs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev/human_preview.py"
SPEC = importlib.util.spec_from_file_location("human_preview", SCRIPT)
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class HumanPreviewSpawnTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.base / "play"
        self.root.mkdir(mode=0o700)
        self.app = self.base / "Preview.app"
        (self.app / "Contents/MacOS").mkdir(parents=True)
        self.executable = self.app / "Contents/MacOS/KokiriGame"
        self.executable.write_bytes(b"mocked-preview-executable\n")
        self.executable.chmod(0o700)
        self.info = {"CFBundleIdentifier": "com.christianfurr.kokiri.runtime",
                     "CFBundleExecutable": "KokiriGame", "KokiriHumanPreviewVersion": 1}
        self.request = {"schema": 1, "kind": "human-preview", "owner": "user",
                        "session_id": "a" * 32,
                        "executable_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest()}
        self.save_metadata()
        self.account = patch.object(preview.pwd, "getpwuid",
                                   return_value=SimpleNamespace(pw_dir=str(self.home), pw_name="fixture-user"))
        self.account.start()
        self.process = Mock(pid=12345)
        self.spawn = patch.object(preview.subprocess, "Popen", return_value=self.process)
        self.popen = self.spawn.start()
        self.addCleanup(self.account.stop)
        self.addCleanup(self.spawn.stop)
        self.addCleanup(self.temporary.cleanup)

    def save_metadata(self):
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))
        (self.root / "preview.json").write_text(json.dumps(self.request))

    def refuse(self):
        with self.assertRaises((preview.PreviewError, OSError, ValueError)):
            preview.launch(self.app, self.root)
        self.popen.assert_not_called()

    def test_clean_environment_and_no_lifecycle_control(self):
        poison = {"HOME": "/wrong-home", "TOTK_SLOT_OWNER": "agent", "TOTK_GAME_SLOT_FD": "123",
                  "TOTK_INPUT_SCRIPT": "0:38:5000", "TOTK_PROFILE_DIR": "/shared-profile",
                  "DYLD_INSERT_LIBRARIES": "/bad-library", "KOKIRI_DEVELOPMENT_ROOT": "/agent",
                  "KOKIRI_DEVELOPMENT_NONCE": "b" * 64, "TOTK_AGENT_LIMIT_S": "1",
                  "TOTK_ROMFS_MODS": "/foreign/applied", "KOKIRI_HUMAN_MOD_MANIFEST_SHA256": "0" * 64}
        with patch.dict(os.environ, poison):
            self.assertEqual(preview.launch(self.app, self.root), 12345)
        arguments, options = self.popen.call_args
        self.assertEqual(arguments, ([str(self.executable), "--kokiri-preview", str(self.root)],))
        self.assertEqual(options["env"], {"HOME": str(self.home), "USER": "fixture-user", "LOGNAME": "fixture-user",
                                        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                                        "KOKIRI_HUMAN_PREVIEW_ROOT": str(self.root)})
        self.assertEqual(options["cwd"], self.app)
        self.assertEqual(options["stdin"], preview.subprocess.DEVNULL)
        self.assertIs(options["stdout"], options["stderr"])
        self.assertTrue(options["start_new_session"])
        self.assertTrue(options["close_fds"])
        self.assertEqual(self.process.mock_calls, [])

    def test_missing_or_boolean_marker_refused(self):
        for marker in (None, True, 2):
            with self.subTest(marker=marker):
                if marker is None:
                    self.info.pop("KokiriHumanPreviewVersion", None)
                else:
                    self.info["KokiriHumanPreviewVersion"] = marker
                self.save_metadata()
                self.refuse()

    def test_digest_mismatch_refused(self):
        self.request["executable_sha256"] = "0" * 64
        self.save_metadata()
        self.refuse()

    def test_agent_or_malformed_request_refused(self):
        original = dict(self.request)
        for key, value in (("owner", "agent"), ("schema", True), ("kind", "development"),
                           ("session_id", "../escape"), ("executable_sha256", "A" * 64)):
            with self.subTest(key=key):
                self.request = {**original, key: value}
                self.save_metadata()
                self.refuse()

    def test_agent_lease_keys_refused_even_when_null(self):
        original = dict(self.request)
        for key, value in (("nonce", None), ("expires_unix", None), ("nonce", "b" * 64),
                           ("expires_unix", 1)):
            with self.subTest(key=key, value=value):
                self.request = {**original, key: value}
                self.save_metadata()
                self.refuse()

    def test_mixed_development_files_and_dangling_links_refused(self):
        for name in ("request.json", "lease.json", "ownership.json", "revoked"):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(b"{}")
                self.refuse()
                path.unlink()
        dangling = self.root / "request.json"
        dangling.symlink_to(self.base / "absent-request.json")
        self.refuse()

    def test_nonprivate_or_symlink_root_refused(self):
        self.root.chmod(0o755)
        self.refuse()
        self.root.chmod(0o700)
        alias = self.base / "play-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.root = alias
        self.refuse()

    def test_root_inside_shared_support_or_logs_refused(self):
        for suffix in ("Library/Application Support/Kokiri", "Library/Application Support/MacNativeGames",
                       "Library/Logs/Kokiri", "Library/Logs/MacNativeGames"):
            with self.subTest(suffix=suffix):
                self.root = self.home / suffix / "private-looking-child"
                self.root.mkdir(mode=0o700, parents=True)
                self.save_metadata()
                self.refuse()

    def test_metadata_symlink_and_hardlink_refused(self):
        path = self.root / "preview.json"
        target = self.base / "request.json"
        path.rename(target)
        path.symlink_to(target)
        self.refuse()
        path.unlink()
        os.link(target, path)
        self.refuse()

    def test_log_symlink_and_hardlink_refused(self):
        target = self.base / "unrelated.log"
        target.write_bytes(b"preserve-me")
        path = self.root / "game-full.log"
        path.symlink_to(target)
        self.refuse()
        path.unlink()
        os.link(target, path)
        self.refuse()
        self.assertEqual(target.read_bytes(), b"preserve-me")

    def mods_fixture(self):
        self.info["KokiriHumanPreviewModsVersion"] = 1
        self.save_metadata()
        self.mod_session = "d" * 32
        self.mod_folder = self.root / "mods" / self.mod_session
        self.mod_overlay = self.mod_folder / "mods"
        for folder in (self.root / "mods", self.mod_folder, self.mod_overlay):
            folder.mkdir(mode=0o700)
        (self.mod_overlay / "Content").mkdir(mode=0o700)
        payload = b"owned-copy"
        (self.mod_overlay / "Content/file.bin").write_bytes(payload)
        manifest = f"Content/file.bin\t{len(payload)}\t{hashlib.sha256(payload).hexdigest()}\t{'b' * 64}\n"
        (self.mod_overlay / "manifest.tsv").write_text(manifest)
        self.mod_record = {"schema": 1, "kind": "human-mod-overlay", "session_id": self.request["session_id"],
                           "launch_id": self.mod_session, "executable_sha256": self.request["executable_sha256"],
                           "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest()}
        self.write_mod_record()

    def write_mod_record(self):
        data = json.dumps(self.mod_record).encode()
        (self.mod_folder / "handoff.json").write_bytes(data)
        self.mod_hash = hashlib.sha256(data).hexdigest()

    def refuse_mods(self, session=None, digest=None):
        with self.assertRaises((preview.PreviewError, OSError, ValueError)):
            preview.launch(self.app, self.root, session or self.mod_session, digest or self.mod_hash)
        self.popen.assert_not_called()
        self.assertFalse((self.root / "game-full.log").exists())

    def test_mod_snapshot_uses_typed_arguments_and_clean_environment(self):
        self.mods_fixture()
        self.assertEqual(preview.launch(self.app, self.root, self.mod_session, self.mod_hash), 12345)
        arguments, options = self.popen.call_args
        self.assertEqual(arguments[0], [str(self.executable), "--kokiri-preview", str(self.root),
                                      "--mods-session", self.mod_session, "--mods-sha256", self.mod_hash])
        self.assertNotIn("TOTK_ROMFS_MODS", options["env"])
        self.assertNotIn("KOKIRI_DEVELOPMENT_NONCE", options["env"])

    def test_mod_capability_exact_integer_required(self):
        self.mods_fixture()
        for value in (None, True, 1.0, "1", 2):
            with self.subTest(value=value):
                if value is None:
                    self.info.pop("KokiriHumanPreviewModsVersion", None)
                else:
                    self.info["KokiriHumanPreviewModsVersion"] = value
                self.save_metadata()
                self.refuse_mods()

    def test_mod_tokens_and_stale_game_or_session_refused(self):
        self.mods_fixture()
        for token, digest in (("../escape", self.mod_hash), (self.mod_session, "A" * 64), (self.mod_session, "0" * 64)):
            with self.subTest(token=token, digest=digest):
                self.refuse_mods(token, digest)
        original = dict(self.mod_record)
        for key, value in (("session_id", "f" * 32), ("executable_sha256", "e" * 64), ("schema", True)):
            self.mod_record = {**original, key: value}
            self.write_mod_record()
            self.refuse_mods()

    def test_changed_manifest_or_payload_refused(self):
        self.mods_fixture()
        file = self.mod_overlay / "Content/file.bin"
        file.write_bytes(b"changed!!!")
        self.refuse_mods()
        file.write_bytes(b"owned-copy")
        with (self.mod_overlay / "manifest.tsv").open("a") as output:
            output.write("# mutation\n")
        self.refuse_mods()

    def test_payload_symlinks_hardlinks_and_parent_escape_refused(self):
        self.mods_fixture()
        file = self.mod_overlay / "Content/file.bin"
        outside = self.base / "outside.bin"
        outside.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(outside)
        self.refuse_mods()
        file.unlink()
        os.link(outside, file)
        self.refuse_mods()
        file.unlink()
        (self.mod_overlay / "Content").rmdir()
        (self.mod_overlay / "Content").symlink_to(self.base, target_is_directory=True)
        self.refuse_mods()

    def test_malformed_manifest_cannot_be_blessed_by_new_hash(self):
        self.mods_fixture()
        for row in ("../outside\t1\t" + "a" * 64 + "\t-\n", "Content/file.bin\t9\t" + "a" * 64 + "\t-\textra\n", "# empty\n"):
            (self.mod_overlay / "manifest.tsv").write_text(row)
            self.mod_record["manifest_sha256"] = hashlib.sha256(row.encode()).hexdigest()
            self.write_mod_record()
            self.refuse_mods()


if __name__ == "__main__":
    unittest.main()
