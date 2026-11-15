"""Compare the production storage sweep with its original every-submit scan."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r'^static [^\n]+\b' + name + r'\([^\n]*\) \{', source, re.M)
    if not match:
        raise AssertionError(f'missing production function {name}')
    end = source.index('{', match.start())
    depth = 1
    end += 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


class StorageSweep(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'requires Foundation and clang')
    def test_exact_retirement_and_scan_work(self):
        source = (ROOT / 'third_party/d2r_gfx/gfx/nvn/nvn_mtl.m').read_text()
        definitions = '\n'.join(re.search(r'^typedef struct .* } ' + name + r';[^\n]*', source, re.M)[0]
                                for name in ('stor_key', 'stor_ent'))
        names = ('stor_idle_deadline', 'stor_schedule_idle_locked', 'stor_unref_locked',
                 'stor_release_holders_locked', 'stor_drop_locked', 'stor_det_drop_locked',
                 'stor_det_sweep', 'stor_publish', 'stor_collect_drop', 'stor_sweep')
        functions = '\n\n'.join(function(source, name) for name in names)
        # Count visited slots without changing the production branch predicates.
        functions = functions.replace('i < g_by_storage.cap; i++) {',
                                      'i < g_by_storage.cap; i++) { probe_scanned++;')
        functions = functions.replace('i < g_stor_ndet; ) {',
                                      'i < g_stor_ndet; ) { probe_scanned++;')
        template = (ROOT / 'tests/storage_sweep_probe.m').read_text()
        code = template.replace('// STORAGE_TYPES', definitions).replace('// STORAGE_FUNCTIONS', functions)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            file = work / 'probe.m'
            file.write_text(code)
            outputs = {}
            for mode in ('production', 'reference'):
                binary = work / mode
                command = ['xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-fobjc-arc', '-fblocks',
                           '-fsanitize=address,undefined', '-I', str(ROOT / 'third_party/d2r_gfx/gfx/nvn'),
                           str(file), '-framework', 'Foundation', '-o', str(binary)]
                if mode == 'reference':
                    command.insert(2, '-DREFERENCE_SWEEP=1')
                compiled = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(mode, result.stdout.strip())
                outputs[mode] = dict(line.split('=', 1) for line in result.stdout.splitlines())
            for field in ('retirement_digest', 'retirement_count', 'deferred_digest', 'deferred_count'):
                self.assertEqual(outputs['production'][field], outputs['reference'][field], field)
            self.assertGreater(int(outputs['production']['retirement_count']), 2000)
            self.assertLess(int(outputs['production']['slots_scanned']),
                            int(outputs['reference']['slots_scanned']))
            print('CPU fixture scan ratio:', int(outputs['reference']['slots_scanned']) /
                  int(outputs['production']['slots_scanned']))


if __name__ == '__main__':
    unittest.main()
