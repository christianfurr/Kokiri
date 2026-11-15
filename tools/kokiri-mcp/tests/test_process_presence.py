"""Read failures and failed game probes never authorize mutation. No OS signals."""
import errno
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kokiri import KokiriError, ProcessReader


class ProcessPresenceTests(unittest.TestCase):
    def setUp(self):
        self.reader=object.__new__(ProcessReader)

    def test_rusage_and_path_failures_do_not_prove_exit(self):
        for rusage,path in ((1,1),(0,0),(0,-1)):
            self.reader.library=SimpleNamespace(proc_pid_rusage=Mock(return_value=rusage),
                                                proc_pidpath=Mock(return_value=path))
            with self.subTest(rusage=rusage,path=path),patch('kokiri.os.kill') as probe:
                self.assertIsNone(self.reader.sample(991))
                self.assertEqual(self.reader.presence(991),'present')
                probe.assert_called_once_with(991,0)

    def test_only_esrch_proves_absence(self):
        for error,expected in ((ProcessLookupError(errno.ESRCH,'gone'),'gone'),
                               (PermissionError(errno.EPERM,'denied'),'unknown'),
                               (OSError(errno.EIO,'unavailable'),'unknown')):
            with self.subTest(error=error),patch('kokiri.os.kill',side_effect=error):
                self.assertEqual(self.reader.presence(991),expected)

    def test_invalid_pids_are_unknown_without_os_probe(self):
        with patch('kokiri.os.kill') as probe:
            for pid in (None,True,False,0,1,-1,'991'):
                self.assertEqual(self.reader.presence(pid),'unknown')
            probe.assert_not_called()

    def test_game_probe_distinguishes_found_absent_and_errors(self):
        for code in (0,1,2,3,-9):
            with self.subTest(code=code),patch('kokiri.sys.platform','darwin'), \
                    patch('kokiri.subprocess.run',return_value=SimpleNamespace(returncode=code)):
                if code in (0,1):self.assertEqual(self.reader.game_running(),code==0)
                else:
                    with self.assertRaises(KokiriError):self.reader.game_running()

    def test_game_probe_errors_fail_closed(self):
        for error in (OSError(errno.EIO,'probe failed'),subprocess.TimeoutExpired('pgrep',3)):
            with self.subTest(error=error),patch('kokiri.sys.platform','darwin'), \
                    patch('kokiri.subprocess.run',side_effect=error):
                with self.assertRaises(KokiriError):self.reader.game_running()


if __name__=='__main__':unittest.main()
