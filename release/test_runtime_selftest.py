"""Mocked diagnostic ownership checks; never signals, launches or compiles code."""
import ctypes
import errno
import importlib.util
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location('runtime_selftest_under_test', Path(__file__).with_name('runtime_selftest.py'))
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


class DiagnosticOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(pid=1234, uid=501, started_sec=1794760000,
                             started_usec=234567, executable='/private/fixture/Kokiri Game.app/Contents/MacOS/KokiriGame')

    def test_reused_pid_and_same_path_with_different_birth_are_never_signalled(self):
        for changed in ({'started_sec': self.identity['started_sec'] + 1},
                        {'started_usec': self.identity['started_usec'] + 1}):
            with self.subTest(changed=changed), \
                    patch.object(harness, 'process_identity', return_value={**self.identity, **changed}), \
                    patch.object(harness.os, 'getuid', return_value=501), \
                    patch.object(harness.os, 'kill') as kill:
                with self.assertRaisesRegex(ValueError, 'identity changed'):
                    harness.stop_owned(self.identity)
                kill.assert_not_called()

    def test_matching_birth_signals_once_and_observes_exit(self):
        with patch.object(harness, 'process_identity', side_effect=[self.identity, None]) as observe, \
                patch.object(harness.os, 'getuid', return_value=501), \
                patch.object(harness.os, 'kill') as kill, patch.object(harness.time, 'sleep') as sleep:
            harness.stop_owned(self.identity)
        kill.assert_called_once_with(1234, signal.SIGTERM)
        self.assertEqual(observe.call_count, 2)
        sleep.assert_not_called()

    def test_signal_is_not_repeated_for_replacement_after_original_exits(self):
        replacement = {**self.identity, 'started_usec': 654321}
        with patch.object(harness, 'process_identity', side_effect=[self.identity, replacement]), \
                patch.object(harness.os, 'getuid', return_value=501), \
                patch.object(harness.os, 'kill') as kill:
            harness.stop_owned(self.identity)
        kill.assert_called_once_with(1234, signal.SIGTERM)

    def test_changed_uid_or_path_and_foreign_owner_are_never_signalled(self):
        cases = [(self.identity, {**self.identity, 'uid': 502}),
                 (self.identity, {**self.identity, 'executable': '/Applications/Human Game.app/Contents/MacOS/KokiriGame'}),
                 ({**self.identity, 'uid': 502}, {**self.identity, 'uid': 502})]
        for expected, actual in cases:
            with self.subTest(expected=expected, actual=actual), \
                    patch.object(harness, 'process_identity', return_value=actual), \
                    patch.object(harness.os, 'getuid', return_value=501), \
                    patch.object(harness.os, 'kill') as kill:
                with self.assertRaises(ValueError):
                    harness.stop_owned(expected)
                kill.assert_not_called()

    def test_unknown_snapshot_error_is_not_disappearance_and_never_signals(self):
        with patch.object(harness, 'process_identity', side_effect=ValueError('unverifiable snapshot')), \
                patch.object(harness.os, 'kill') as kill:
            with self.assertRaisesRegex(ValueError, 'unverifiable snapshot'):
                harness.stop_owned(self.identity)
            kill.assert_not_called()

    def test_already_exited_process_and_signal_race_are_benign(self):
        with patch.object(harness, 'process_identity', return_value=None), \
                patch.object(harness.os, 'kill') as kill:
            harness.stop_owned(self.identity)
            kill.assert_not_called()
        with patch.object(harness, 'process_identity', return_value=self.identity), \
                patch.object(harness.os, 'getuid', return_value=501), \
                patch.object(harness.os, 'kill', side_effect=ProcessLookupError) as kill:
            harness.stop_owned(self.identity)
            kill.assert_called_once_with(1234, signal.SIGTERM)

    def test_observe_pins_complete_kernel_birth_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'marker.txt'
            marker.write_text('updated-fixture\n1234\n' + self.identity['executable'] + '\n1794760000\n234567\n')
            owned = []
            with patch.object(harness, 'process_identity', return_value=self.identity), \
                    patch.object(harness.os, 'getuid', return_value=501):
                actual = harness.observe(marker, 'updated-fixture', Path('/private/fixture/Kokiri Game.app'), owned)
            self.assertEqual(actual, self.identity)
            self.assertEqual(owned, [self.identity])
            self.assertEqual(json.loads((marker.parent / 'observed-updated-fixture.json').read_text()), self.identity)

    def test_observe_rejects_stale_birth_owner_and_wrong_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'marker.txt'
            marker.write_text('updated-fixture\n1234\n' + self.identity['executable'] + '\n1794760000\n234567\n')
            for actual in ({**self.identity, 'started_sec': 1794760001},
                           {**self.identity, 'started_usec': 234568},
                           {**self.identity, 'uid': 502},
                           {**self.identity, 'executable': '/Applications/Human.app/Contents/MacOS/KokiriGame'}, None):
                owned = []
                with self.subTest(actual=actual), \
                        patch.object(harness, 'process_identity', return_value=actual), \
                        patch.object(harness.os, 'getuid', return_value=501):
                    with self.assertRaisesRegex(ValueError, 'process/start'):
                        harness.observe(marker, 'updated-fixture', Path('/private/fixture/Kokiri Game.app'), owned)
                self.assertEqual(owned, [])

    def library(self, snapshots=None, path_error=None, snapshot_error=None):
        """A fake libproc populates ctypes buffers without reading real processes."""
        observations = iter(snapshots or [self.identity, self.identity])
        def info(pid, flavor, argument, pointer, size):
            if snapshot_error is not None:
                code, number = snapshot_error
                ctypes.set_errno(number)
                return code
            value = next(observations)
            if value is None:
                ctypes.set_errno(errno.ESRCH)
                return 0
            record = pointer._obj
            record.pid, record.uid = value['pid'], value['uid']
            record.started_sec, record.started_usec = value['started_sec'], value['started_usec']
            return size
        def path(pid, buffer, size):
            if path_error is not None:
                ctypes.set_errno(path_error)
                return 0
            buffer.value = self.identity['executable'].encode()
            return len(buffer.value)
        return SimpleNamespace(proc_pidinfo=Mock(side_effect=info), proc_pidpath=Mock(side_effect=path))

    def test_kernel_snapshot_layout_and_consistent_birth(self):
        # Matches proc_bsdinfo in the supported macOS SDK; no libproc is loaded.
        self.assertEqual(ctypes.sizeof(harness.ProcBSDInfo), 136)
        library = self.library()
        with patch.object(harness.ctypes, 'CDLL', return_value=library):
            result = harness.process_identity(1234)
        self.assertEqual(result, self.identity)
        self.assertEqual(library.proc_pidinfo.call_count, 2)
        self.assertEqual(library.proc_pidpath.call_count, 1)

    def test_kernel_snapshot_short_unknown_and_permission_errors_fail_closed(self):
        for returned, number in [(0, errno.EPERM), (0, 0), (135, 0), (-1, errno.EIO)]:
            library = self.library(snapshot_error=(returned, number))
            with self.subTest(returned=returned, errno=number), \
                    patch.object(harness.ctypes, 'CDLL', return_value=library):
                with self.assertRaisesRegex(ValueError, 'full diagnostic process birth'):
                    harness.process_identity(1234)
            library.proc_pidpath.assert_not_called()

    def test_only_esrch_snapshot_or_path_errors_mean_disappearance(self):
        for library in (self.library(snapshot_error=(0, errno.ESRCH)),
                        self.library(path_error=errno.ESRCH), self.library(snapshots=[self.identity, None])):
            with patch.object(harness.ctypes, 'CDLL', return_value=library):
                self.assertIsNone(harness.process_identity(1234))
        with patch.object(harness.ctypes, 'CDLL', return_value=self.library(path_error=errno.EACCES)):
            with self.assertRaisesRegex(ValueError, 'executable path'):
                harness.process_identity(1234)

    def test_kernel_birth_change_between_path_snapshots_is_rejected(self):
        for changed in ({'started_usec': 234568}, {'uid': 502}, {'pid': 1235}):
            library = self.library(snapshots=[self.identity, {**self.identity, **changed}])
            with self.subTest(changed=changed), patch.object(harness.ctypes, 'CDLL', return_value=library):
                with self.assertRaisesRegex(ValueError, 'identity changed during observation'):
                    harness.process_identity(1234)


if __name__ == '__main__':
    unittest.main()
