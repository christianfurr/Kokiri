import ctypes
import fcntl
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kokiri import SessionStore, ProcessReader, KokiriError, atomic_json, bounded_bytes, checked_directory, tail, complete_png
from server import require_identity
from mcp.server.mcpserver.exceptions import ToolError


class FakeProcess:
    def __init__(self): self.value = None
    def sample(self, pid): return dict(self.value) if self.value and self.value['pid'] == pid else None
    def game_running(self): return self.value is not None
    def windows(self, pid): return [321] if self.sample(pid) else []


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.process = FakeProcess()
        self.store = SessionStore(self.root/'Kokiri', process_reader=self.process)
        self.folder = self.store.managed_directory(self.store.sessions_root/'human')
        self.exe = self.root/'Game.app/Contents/MacOS/KokiriGame'
        self.exe.parent.mkdir(parents=True); self.exe.write_bytes(b'\xcf\xfa\xed\xfeunit-test-placeholder')
        (self.exe.parent.parent/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.christianfurr.kokiri.runtime', 'KokiriLiveStatusVersion':1}))
        self.metadata = dict(pid=991, executable=str(self.exe), process_start=123, process_uuid='abc', started=100)
        self.process.value = {**self.metadata, 'physical_footprint_bytes':2048, 'resident_bytes':1024}
        atomic_json(self.folder/'session.json', self.metadata)
        (self.folder/'input.txt').write_text(''); (self.folder/'status.jsonl').write_text('')
        self.identifier = self.store.session_id(self.folder)

    def tearDown(self): self.temporary.cleanup()

    def test_only_observation_commands_can_reach_human_channel(self):
        for line in ['close', 'key 13 200', 'down 13', 'oot-live mcp-123 move Kakariko 1 2 3']:
            with self.assertRaises(KokiriError): self.store.send_observation(self.identifier,line)
        self.assertEqual((self.folder/'input.txt').read_text(),'')

    def test_pid_reuse_fails_closed(self):
        self.process.value['process_start'] += 1
        self.assertFalse(self.store.status(self.identifier)['running_verified'])
        with self.assertRaises(KokiriError): self.store.location_request(self.identifier)
        self.assertEqual((self.folder/'input.txt').read_text(),'')

    def test_replaced_receipt_cannot_rebind_pending_observation(self):
        identity = require_identity(self.store, self.identifier)
        self.metadata['process_start'] += 1
        self.process.value['process_start'] += 1
        atomic_json(self.folder/'session.json', self.metadata)
        self.assertTrue(self.store.status(self.identifier)['running_verified'])
        with self.assertRaises(ToolError):
            require_identity(self.store, self.identifier, identity)

    def test_legacy_session_does_not_fall_back_to_kokiri_global_log(self):
        self.metadata['executable'] = str(self.exe.with_name('OcarinaOfTime'))
        self.process.value['executable'] = self.metadata['executable']
        atomic_json(self.folder/'session.json', self.metadata)
        with patch('kokiri.tail', return_value=[]) as read:
            self.assertEqual(self.store.logs(self.identifier, 'game', 1)['lines'], [])
        read.assert_called_once_with(self.folder, 'game-full.log', 1)

    def test_invalid_executable_metadata_keeps_recorded_log_readable(self):
        for executable in [None, 123]:
            self.metadata['executable'] = executable
            atomic_json(self.folder/'session.json', self.metadata)
            self.assertEqual(self.store.logs(self.identifier, 'game', 1)['lines'], [])

    def test_wrong_executable_fails_closed(self):
        self.process.value['executable'] = '/somewhere/OtherApp'
        self.assertFalse(self.store.list_sessions()['sessions'][0]['running_verified'])

    def test_missing_start_is_not_inferred_from_pid(self):
        del self.metadata['process_start']; atomic_json(self.folder/'session.json',self.metadata)
        self.assertFalse(self.store.status(self.identifier)['running_verified'])

    def test_location_is_the_only_observation_wire(self):
        token = self.store.location_request(self.identifier)
        self.assertEqual((self.folder/'input.txt').read_text(),f'oot-live {token} position\n')
        with self.assertRaises(KokiriError): self.store.location_request(self.identifier)
        self.assertNotIn('move',(self.folder/'input.txt').read_text())

    def test_capability_missing_does_not_send_unknown_command(self):
        (self.exe.parent.parent/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.christianfurr.kokiri.runtime'}))
        with self.assertRaises(KokiriError): self.store.location_request(self.identifier)
        self.assertEqual((self.folder/'input.txt').read_text(),'')

    def test_observed_external_root_never_grants_control(self):
        self.store.observe_roots.append(self.folder)
        self.metadata['role']='kokiri-mcp';atomic_json(self.folder/'session.json',self.metadata)
        self.assertEqual(self.store.list_sessions()['sessions'][0]['control'],'observation-only')

    def test_contained_file_reader_rejects_symlink_and_traversal(self):
        (self.root/'private.txt').write_text('not-to-be-read')
        (self.folder/'linked').symlink_to(self.root/'private.txt')
        for name in ['linked','../private.txt',str(self.root/'private.txt')]:
            with self.assertRaises((OSError,KokiriError)): bounded_bytes(self.folder,name,100)

    def test_fifo_rejected_without_waiting_for_peer(self):
        fifo = self.folder/'fifo'
        os.mkfifo(fifo)
        script = ('import os,sys; from pathlib import Path; from kokiri import open_relative,KokiriError; '
                  'open_relative(Path(sys.argv[1]), "fifo", int(sys.argv[2]))')
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        for flags in [os.O_RDONLY, os.O_WRONLY | os.O_APPEND]:
            result = subprocess.run([sys.executable, '-c', script, str(self.folder), str(flags)],
                                    capture_output=True, timeout=3, env=environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(b'KokiriError' in result.stderr or b'OSError' in result.stderr)

    def test_oversized_json_and_bounded_tail(self):
        (self.folder/'large.json').write_bytes(b'a'*1025)
        with self.assertRaises(KokiriError): bounded_bytes(self.folder,'large.json',1024)
        (self.folder/'events.jsonl').write_text('secret-prefix\n'+'x'*300000+'\nlast\n')
        self.assertEqual(tail(self.folder,'events.jsonl',1),['last'])
        with self.assertRaises(KokiriError): tail(self.folder,'events.jsonl',201)

    def test_symlink_root_and_creation_chain_rejected(self):
        outside=self.root/'outside';outside.mkdir()
        link=self.root/'link';link.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(KokiriError): checked_directory(link)
        with self.assertRaises(OSError): self.store.managed_directory(link/'must-not-create')
        self.assertFalse((outside/'must-not-create').exists())

    def test_capture_identifier_traversal_rejected_before_directory_write(self):
        with self.assertRaises(KokiriError): self.store.capture_request('../../outside')
        self.assertFalse(self.store.development.exists())

    def test_frame_stats_exclude_generated_duplicates_and_negative(self):
        rows=[]
        for i,stamp in enumerate([10.,10.01,10.02,10.02]):
            rows.append(f'presented\t{i}\tx\tx\t0\t{stamp}\tx\tx')
        rows.extend(['presented\t5\tx\tx\t1\t11\tx\tx','presented\t6\tx\tx\t0\t-1\tx\tx'])
        (self.folder/'timings.tsv.presented.tsv').write_text('\n'.join(rows)+'\n')
        (self.folder/'timings.tsv').write_text('1\t@frame_ms\t12\n2\t@frame_ms\t250\n3\t@frame_ms\tnan\n')
        result=self.store.status(self.identifier)
        self.assertAlmostEqual(result['observed_game_presents_per_second'],100)
        self.assertEqual(result['max_frame_ms'],250)
        self.assertFalse(result['certified_benchmark'])

    def test_native_window_capture_uses_only_verified_window_id(self):
        with patch('kokiri.subprocess.run') as run:
            path=self.store.capture_request(self.identifier,'window')
        self.assertEqual(run.call_args.args[0],['/usr/sbin/screencapture','-x','-l','321',str(path)])
        self.assertTrue(path.is_relative_to(self.store.development/'Captures'))

    def test_native_capture_pid_changed_never_calls_screencapture(self):
        self.process.value['process_start']+=1
        with patch('kokiri.subprocess.run') as run:
            with self.assertRaises(KokiriError):self.store.capture_request(self.identifier,'window')
        run.assert_not_called()

    def test_capture_file_count_is_bounded(self):
        folder=self.store.managed_directory(self.store.development/'Captures'/self.identifier)
        for index in range(64): (folder/str(index)).touch()
        with patch('kokiri.subprocess.run') as run:
            with self.assertRaisesRegex(KokiriError, '64-capture'):
                self.store.capture_request(self.identifier,'window')
        run.assert_not_called()

    def test_pending_concurrent_captures_reserve_last_slot(self):
        folder=self.store.managed_directory(self.store.development/'Captures'/self.identifier)
        for index in range(63): (folder/str(index)).touch()
        def request():
            try:
                return self.store.capture_request(self.identifier, 'game_frame')
            except KokiriError:
                return None
        with ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(lambda _: request(), range(4)))
        self.assertEqual(sum(path is not None for path in results), 1)
        self.assertEqual(len(list(folder.iterdir())), 64)
        self.assertEqual((self.folder/'input.txt').read_text().count('wshot '), 1)

    def capture_workers(self, count):
        script = '''
import json,sys
from pathlib import Path
from kokiri import SessionStore,KokiriError
root=Path(sys.argv[1])
metadata=json.loads((root/'Sessions/human/session.json').read_text())
class Process:
 def sample(self,pid):
  return dict(metadata,physical_footprint_bytes=2048,resident_bytes=1024) if pid==metadata['pid'] else None
store=SessionStore(root,process_reader=Process())
try:
 store.capture_request(sys.argv[2],'game_frame')
 print('reserved')
except KokiriError:
 print('refused')
'''
        workers = [subprocess.Popen([sys.executable, '-c', script, str(self.store.support), self.identifier],
                    cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True) for _ in range(count)]
        try:
            results = []
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=10)
                self.assertEqual(worker.returncode, 0, stderr)
                results.append(stdout.strip())
            return results
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                worker.wait()

    def test_capture_reservation_respects_other_process_directory_lock(self):
        folder = self.store.managed_directory(self.store.development/'Captures'/self.identifier)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.capture_workers(2), ['refused', 'refused'])
            self.assertEqual(list(folder.iterdir()), [])
            self.assertEqual((self.folder/'input.txt').read_text(), '')
        finally:
            os.close(directory)

    def test_independent_processes_cannot_exceed_last_capture_slot(self):
        folder = self.store.managed_directory(self.store.development/'Captures'/self.identifier)
        for index in range(63):
            (folder/str(index)).touch()
        results = self.capture_workers(4)
        self.assertEqual(results.count('reserved'), 1)
        self.assertEqual(results.count('refused'), 3)
        self.assertEqual(len(list(folder.iterdir())), 64)
        self.assertEqual((self.folder/'input.txt').read_text().count('wshot '), 1)

    def test_failed_capture_releases_reservation(self):
        folder=self.store.managed_directory(self.store.development/'Captures'/self.identifier)
        with patch('kokiri.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'screencapture')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.store.capture_request(self.identifier, 'window')
        self.assertEqual(list(folder.iterdir()), [])

    def test_invalid_location_identifier_does_not_grow_rate_map(self):
        for identifier in ['../../outside', 'a'*20]:
            with self.assertRaises(KokiriError): self.store.location_request(identifier)
        self.assertEqual(self.store.commands,{})

    def test_partial_png_waits_and_complete_png_checks_chunks(self):
        def chunk(kind, payload):
            return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))
        data = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',1,1,8,6,0,0,0))
        data += chunk(b'IDAT', zlib.compress(b'\0\0\0\0\0'))+chunk(b'IEND', b'')
        for end in range(len(data)):
            self.assertFalse(complete_png(data[:end]))
        self.assertTrue(complete_png(data))
        corrupt = bytearray(data); corrupt[28] ^= 1
        with self.assertRaises(KokiriError): complete_png(bytes(corrupt))


@unittest.skipUnless(sys.platform=='darwin','macOS native process API')
class NativeProcessTests(unittest.TestCase):
    def test_actual_libproc_matches_sdk_c_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'probe.c';binary=root/'probe'
            source.write_text('#include <libproc.h>\n#include <sys/resource.h>\n#include <stdlib.h>\n#include <stdio.h>\nint main(int argc,char **argv){if(argc!=2)return 2;struct rusage_info_v4 r={0};if(proc_pid_rusage(atoi(argv[1]),RUSAGE_INFO_V4,(rusage_info_t *)&r))return 3;printf("%llu %llu\\n",(unsigned long long)r.ri_proc_start_abstime,(unsigned long long)r.ri_phys_footprint);return 0;}\n')
            subprocess.run(['xcrun','clang','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True,capture_output=True)
            start,footprint=map(int,subprocess.check_output([str(binary),str(os.getpid())],text=True).split())
            sample=ProcessReader().sample(os.getpid())
            self.assertEqual(start,sample['process_start'])
            self.assertGreater(sample['physical_footprint_bytes'],0)
            self.assertLess(abs(footprint-sample['physical_footprint_bytes']),16<<20)
            self.assertIn('Python',sample['executable'])


if __name__=='__main__':unittest.main()
