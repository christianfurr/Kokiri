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
                  "KOKIRI_DEVELOPMENT_NONCE": "b" * 64, "TOTK_AGENT_LIMIT_S": "1"}
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


if __name__ == "__main__":
    unittest.main()
