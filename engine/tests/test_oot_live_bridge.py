"""Actual local bridge parser/queue fixture and two isolated negative controls."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'uses macOS self-memory and file APIs; no GPU')
class LiveBridgeTests(unittest.TestCase):
    def test_actual_bridge_and_rejected_mutation_controls(self):
        source = (ENGINE / 'runtime/oot_live.h').read_text()
        controls = [('positive', source, None)]
        user_gate = 'if (kind != 1 && !oot_live_mutations_allowed())'
        tick_gate = 'if ((kind == 2 || kind == 3) && !oot_live_mutations_allowed())'
        self.assertEqual(source.count(user_gate), 1)
        self.assertEqual(source.count(tick_gate), 1)
        controls.append(('no-read-only-gate', source.replace(user_gate, 'if (0 && kind != 1 && !oot_live_mutations_allowed())')
                         .replace(tick_gate, 'if (0 && (kind == 2 || kind == 3) && !oot_live_mutations_allowed())'), 'normal move rejected'))
        expiry = 'if (kind <= 3 && runtime_now_ns() > oot_live_queue_deadline)'
        self.assertEqual(source.count(expiry), 1)
        controls.append(('no-expiry', source.replace(expiry, 'if (0 && kind <= 3 && runtime_now_ns() > oot_live_queue_deadline)'),
                         'expiry occurs before actor lookup or mutation'))
        with tempfile.TemporaryDirectory(prefix='kokiri-live-bridge-') as directory:
            work = Path(directory)
            for name, header, expected_failure in controls:
                fixture = work / name; fixture.mkdir()
                (fixture / 'oot_live.h').write_text(header)
                # The fixture includes the supplied actual/one-change header first.
                executable = fixture / 'bridge'
                subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                                '-I', str(fixture), '-I', str(ENGINE / 'runtime'),
                                '-I', str(ENGINE / 'third_party/d2r_gfx/gfx/nvn/include'),
                                str(ENGINE / 'tests/oot_live_bridge.c'), '-o', str(executable)], check=True)
                result = subprocess.run([str(executable), str(fixture)], capture_output=True, text=True, timeout=15)
                if expected_failure is None:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('checks PASS', result.stdout)
                    print(result.stdout.strip())
                else:
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('FAILED: ' + expected_failure, result.stderr)
                    print(name + ': intended negative assertion failed')


if __name__ == '__main__':
    unittest.main()
