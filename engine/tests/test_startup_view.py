"""Offscreen native startup view and actual readiness predicate; no game or Metal."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires AppKit; no GPU')
class StartupViewTests(unittest.TestCase):
    def test_native_layout_logo_and_readiness(self):
        with tempfile.TemporaryDirectory(prefix='kokiri-startup-view-') as directory:
            work = Path(directory)
            executable = work/'startup-view'
            image = Path(os.environ.get('KOKIRI_STARTUP_FIXTURE_IMAGE', work/'startup-fixture.png'))
            subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-deprecated-declarations', '-fobjc-arc',
                            '-I', str(ENGINE/'runtime'), str(ENGINE/'tests/startup_view.m'),
                            '-framework', 'Cocoa', '-o', str(executable)], check=True)
            result = subprocess.run([str(executable), str(ENGINE.parent/'assets/brand/kokiri-mark.png'), str(image)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('checks PASS', result.stdout)
            self.assertTrue(image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
