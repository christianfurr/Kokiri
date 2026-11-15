"""Build and run the actual bounded renderer helper without creating a GPU."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'Foundation CPU oracle runs on macOS')
class CatalogRuntimeTests(unittest.TestCase):
    def test_actual_foundation_handoff_and_path_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            program = root / 'catalog-runtime'
            result = subprocess.run(['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-function', '-Wno-deprecated-declarations', '-fobjc-arc', '-fblocks',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I' + str(ENGINE / 'third_party/d2r_gfx/gfx/nvn/include'),
                str(ENGINE / 'tests/catalog_runtime.m'), '-framework', 'Foundation', '-o', str(program)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(program), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('CPU catalog runtime checks passed', result.stdout)
            print(result.stdout.strip())

if __name__ == '__main__':
    unittest.main()
