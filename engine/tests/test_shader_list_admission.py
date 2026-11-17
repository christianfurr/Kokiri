"""Historical host-only rows remain in source data but cannot become archive requests."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import shader_list as sl

VS = 'a' * 64 + '-' + sl.DEFAULT_SUFFIX + '_b'
FS = 'b' * 64 + '-' + sl.DEFAULT_SUFFIX + '_b'
TASK = 'c' * 64 + '-' + sl.DEFAULT_SUFFIX + '_b'


def pipeline(flags=0, sequence=0, mesh=False):
    key = bytearray(544)
    key[:80] = VS.encode().ljust(80, b'\0')
    key[80:160] = FS.encode().ljust(80, b'\0')
    key[160], key[161] = (4 if mesh else 0), 1
    struct.pack_into('<I', key, 248, sequence)
    struct.pack_into('<I', key, 268, flags)
    return key.hex()


class PipelineAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / 'seed'
        self.seed.mkdir()
        (self.seed / 'shader-keys.json').write_text(json.dumps({'keys': [name[:64] for name in (VS, FS, TASK)]}))
        for name in (VS, FS, TASK):
            (self.seed / (name[:64] + '.variants')).write_text(json.dumps([{'variant': name[:-2]}]))

    def test_native_host_bits_rejected_for_each_pipeline_kind_without_rewriting(self):
        for flags in (0x40, 0x80, 0xc0):
            for row in (('R', pipeline(flags)), ('B', pipeline(flags), '-', '0:1:0x0p+0,0x0p+0,0x0p+0,0x0p+0;'),
                        ('T', pipeline(flags), '1:0;'), ('M', TASK, pipeline(flags, mesh=True))):
                with self.subTest(flags=flags, kind=row[0]):
                    parsed = sl.warm_row(list(row))
                    self.assertIsNotNone(parsed)
                    lst = sl.ShaderList()
                    lst.add_warm(parsed, 'm')
                    rows, counts = lst.resolve(self.seed, 'm')
                    self.assertEqual(rows, [])
                    self.assertEqual(counts['missing'], 0)
                    self.assertEqual(counts['rejected_host_rows'], [dict(reason='PSO_HOST_BITS', kind=row[0],
                        host_bits=flags, input_canonical_row_sha256=hashlib.sha256('\t'.join(parsed).encode()).hexdigest())])
                    self.assertEqual(list(lst.warm), [parsed])

    def test_supported_render_tile_compute_and_task_mesh_rows_survive(self):
        rows = [('R', pipeline(0x3f)), ('T', pipeline(), '1:0;'), ('C', VS),
                ('M', TASK, pipeline(mesh=True))]
        lst = sl.ShaderList()
        for row in rows:
            lst.add_warm(row, 'm')
        resolved, counts = lst.resolve(self.seed, 'm')
        self.assertEqual(resolved, rows)
        self.assertEqual(counts['rejected_host_rows'], [])

    def test_resolve_cli_excludes_69_legacy_rows_and_binds_provenance_without_editing_source(self):
        lst = sl.ShaderList()
        valid = ('R', pipeline())
        lst.add_warm(valid, 't')
        for sequence in range(1, 70):
            lst.add_warm(('R', pipeline(0x40, sequence)), 'm')
        mesh = ('M', TASK, pipeline(mesh=True))
        lst.add_warm(mesh, 'm')
        source, title, manifest = (self.root / name for name in ('source.tsv', 'title.tsv', 'manifest.tsv'))
        lst.save(source)
        before = source.read_bytes()
        self.assertIn(':', before.decode())   # Real source encoding packs the pipeline keys.
        with redirect_stdout(io.StringIO()) as output:
            sl.main(['resolve', str(self.seed), str(source), str(manifest), str(title)])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(sl.ShaderList.load(source).warm), 71)
        admitted = [line for path in (title, manifest) for line in path.read_text().splitlines()
                    if line and not line.startswith('#')]
        self.assertEqual(admitted, ['\t'.join(valid), '\t'.join(mesh)])
        metadata = json.loads(next(line[len(sl.ADMISSION_PREFIX):] for line in manifest.read_text().splitlines()
                                   if line.startswith(sl.ADMISSION_PREFIX)))
        self.assertEqual(metadata['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(len(metadata['rejected_host_rows']), 69)
        self.assertEqual(len({row['input_canonical_row_sha256'] for row in metadata['rejected_host_rows']}), 69)
        self.assertIn('69 unsupported PSO_HOST_BITS rows rejected with provenance', output.getvalue())


if __name__ == '__main__':
    unittest.main()
