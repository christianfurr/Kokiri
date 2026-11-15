"""A successful exit or a filtered queue is not evidence of a complete seed."""
import json
import contextlib
import os
from pathlib import Path
import re
import sys
import tempfile
import struct
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_ns2_seed as seed


class SeedTests(unittest.TestCase):
    def corpus(self, path, count=4):
        records = []
        for number in range(count):
            control = bytes(0x60)
            code = struct.pack('<I', number)
            label = f'fixture-{number}'.encode()
            records.append(struct.pack('<IIIH', number % 6, len(control), len(code), len(label))+
                           label+control+code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(seed.CORPUS_MAGIC+struct.pack('<I', count)+b''.join(records))
        return list(seed.corpus_inventory(path))

    def completion(self, count, listed_done=0, listed_asked=0, variants=None):
        return (f'[seed] done in 1 s: {count} of {count} shaders have a translation\n'
                f"[seed] the shader list's bind states: {listed_done} of {listed_asked} translated\n"
                f'[seed] requests checked: {variants or count} variants for this runtime, 0 cached ones kept, 0 made again\n')

    def test_stream_partition_preserves_records_and_exact_binding_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root/'corpus.bin'
            keys = self.corpus(corpus)
            shader_list = root/'shader_list.tsv'
            binding = f'V\t{keys[0]}\t'+json.dumps({'tex': {'0': '2d'}}, separators=(',', ':'))
            ignored = 'V\t'+'e'*64+'\t{}'
            shader_list.write_text(binding+'\n'+ignored+'\n# no other rows enter the native chunk\n')
            chunks = seed.partition_corpus(corpus, root/'chunks', 2, shader_list)
            self.assertEqual([chunk['known_requests'] for chunk in chunks], [2, 2, 1])
            self.assertEqual([chunk['listed_requests'] for chunk in chunks], [1, 0, 0])
            self.assertTrue(all(chunk['known_requests'] <= 2 for chunk in chunks))
            raw = [row[3] for chunk in chunks for row in seed.corpus_records(Path(chunk['corpus']))]
            self.assertEqual(raw, [row[3] for row in seed.corpus_records(corpus)])
            self.assertEqual(Path(chunks[0]['list']).read_text(), binding+'\n')
            self.assertEqual(Path(chunks[-1]['list']).read_text(), '')
            self.assertEqual(set().union(*(set(chunk['keys']) for chunk in chunks)), set(keys))

    def test_single_shader_cannot_exceed_request_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root/'corpus.bin'
            key = self.corpus(corpus, 1)[0]
            listed = root/'list.tsv'
            listed.write_text(f'V\t{key}\t{{}}\n')
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                seed.partition_corpus(corpus, root/'chunks', 1, listed)

    def test_batch_failures_missing_reports_and_verified_gaps_cannot_aggregate(self):
        keys = ['a'*64, 'b'*64]
        verified = {key+'-'+'c'*12 for key in keys}
        with self.assertRaisesRegex(ValueError, 'exited'):
            seed.batch_completion(self.completion(2), keys, verified, returncode=1)
        with self.assertRaisesRegex(ValueError, 'completion reports'):
            seed.batch_completion('', keys, verified)
        with self.assertRaisesRegex(ValueError, 'listed'):
            seed.batch_completion(self.completion(2, 1, 2), keys, verified, has_list=True)
        with self.assertRaisesRegex(ValueError, 'verified set'):
            seed.batch_completion(self.completion(2), keys, {next(iter(verified))})
        first = seed.batch_completion(self.completion(1), keys[:1], {keys[0]+'-'+'c'*12})
        with self.assertRaisesRegex(ValueError, 'full corpus'):
            seed.aggregate_batches(dict.fromkeys(keys), [first], {keys[0]+'-'+'c'*12})
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            seed.aggregate_batches(dict.fromkeys(keys), [first, first], verified)
        second = seed.batch_completion(self.completion(1), keys[1:], {keys[1]+'-'+'c'*12})
        total = seed.aggregate_batches(dict.fromkeys(keys), [first, second], verified)
        self.assertEqual(total['translated_default'], 2)
        self.assertEqual(total['checked_variants'], 2)

    def test_omitted_nondefault_binding_requests_cannot_pass_zero_of_zero(self):
        key = 'a'*64
        verified = {key+'-'+'b'*12}
        with self.assertRaisesRegex(ValueError, 'source binding plan'):
            seed.batch_completion(self.completion(1), [key], verified, has_list=True,
                                  expected_listed_requests=1)
        default = seed.batch_completion(self.completion(1), [key], verified, has_list=True)
        with self.assertRaisesRegex(ValueError, 'source binding plan'):
            seed.aggregate_batches({key: {}}, [default], verified, expected_listed_requests=1)

    def test_default_equivalent_rows_are_not_counted_as_listed_requests(self):
        key = 'a'*64
        self.assertEqual(seed.listed_request_count([f'V\t{key}\t{{}}',
                                                   f'V\t{key}\t'+json.dumps({'tex': {}})]), 0)
        self.assertEqual(seed.listed_request_count([f'V\t{key}\t'+json.dumps({'tex': {'0': '*2d'}})]), 1)
        verified = {key+'-'+'b'*12}
        report = seed.batch_completion(self.completion(1), [key], verified, has_list=True,
                                       expected_listed_requests=0)
        self.assertEqual(report['listed_requests'], 0)

    def test_original_source_census_detects_binding_omitted_by_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'shader_list.tsv'
            keys = ['a'*64, 'b'*64]
            outside = 'c'*64
            binding = json.dumps({'tex': {'0': '*2d'}}, separators=(',', ':'))
            source.write_text(''.join(f'V\t{key}\t{binding}\n' for key in keys)+
                              f'V\t{outside}\t{binding}\n')
            inventory = dict.fromkeys(keys)
            expected = seed.source_listed_requests(source, inventory)
            self.assertEqual(expected, 2)  # out-of-corpus rows are not runtime requests
            first_verified = {keys[0]+'-'+'d'*12, keys[0]+'-'+'e'*12}
            first = seed.batch_completion(self.completion(1, 1, 1, 2), keys[:1], first_verified,
                                          has_list=True, expected_listed_requests=1)
            # A broken partition dropped the second V row and its own plan says zero.
            second_verified = {keys[1]+'-'+'d'*12}
            second = seed.batch_completion(self.completion(1), keys[1:], second_verified,
                                           has_list=True, expected_listed_requests=0)
            with self.assertRaisesRegex(ValueError, 'source binding plan'):
                seed.aggregate_batches(inventory, [first, second], first_verified | second_verified,
                                       expected_listed_requests=expected)

    def test_bounded_pilot_checkpoints_actual_outputs_without_publishing_full_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            corpus = root/'build/ns2-corpus/oot.bin'
            self.corpus(corpus, 2)
            romfs = root/'extracted/oot/romfs'
            romfs.mkdir(parents=True)
            (romfs/'index.json').write_text(json.dumps(dict(romfs_sha256='fixture-romfs')))
            corpus.with_suffix('.json').write_text(json.dumps(dict(
                romfs_sha256='fixture-romfs', modules={}, list=None,
                tool=seed.sha256(Path(seed.__file__).parent/'ns2_shader_corpus.py'))))
            translator = root/'translator'
            translator.write_text('fixture translator')
            binary = root/'runtime'
            binary.write_text('fixture runtime')
            test = self

            class Slot:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def popen(self, command, env, stdout, stderr):
                    keys = list(seed.corpus_inventory(Path(command[3])))
                    cache = Path(env['TOTK_SHADER_CACHE'])
                    variants = []
                    for key in keys:
                        variant = key+'-'+'c'*12
                        variants.append(variant)
                        (cache/(key+'.variants')).write_text(json.dumps([dict(variant=variant)]))
                        (cache/(variant+'_b.metal')).write_text('kernel void main0() {}')
                        (cache/(variant+'_b.json')).write_text(json.dumps(dict(
                            chain=seed.CHAIN, key=variant+'_b', entry='main0')))
                    Path(env['TOTK_SEED_VERIFIED_OUT']).write_text('\n'.join(variants)+'\n')
                    stdout.write(test.completion(len(keys)))
                    return types.SimpleNamespace(wait=lambda: 0)

            argv = ['prepare_ns2_seed.py', '--version', 'oot', '--depth-mode', 'minus-w',
                    '--binary', str(binary), '--translator', str(translator),
                    '--batch-size', '1', '--max-batches', '1', '--jobs', '1']
            with contextlib.chdir(root), mock.patch.object(sys, 'argv', argv), \
                 mock.patch.dict(sys.modules, {'game_slot': types.SimpleNamespace(GameSlot=lambda **kwargs: Slot())}), \
                 mock.patch.dict(os.environ, {'TOTK_GAME_SLOT_DIR': str(root/'slot')}):
                with self.assertRaises(SystemExit) as result:
                    seed.main()
            self.assertEqual(result.exception.code, 2)
            progress = json.loads(next((root/'logs').glob('ns2-seed-oot-batches-*/progress.json')).read_text())
            self.assertEqual(progress['status'], 'incomplete')
            self.assertEqual(len(progress['batches']), 1)
            self.assertEqual(progress['batches'][0]['translated_default'], 1)
            self.assertEqual(len(progress['batches'][0]['output_sha256']), 3)
            self.assertFalse((root/'build/shader-seed/oot').exists())

    def done(self, ok, total):
        return re.search(r'(\d+) of (\d+)', f'{ok} of {total}')

    def test_skipped_mesh_stage_is_incomplete(self):
        inventory = {'a': {'stage': 0}, 'b': {'stage': 4}}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            seed.require_complete(inventory, ['a'], self.done(1, 1))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            seed.require_complete(inventory, ['a', 'b'], self.done(1, 2))
        seed.require_complete(inventory, ['a', 'b'], self.done(2, 2))

    def test_failed_recorded_bind_state_is_incomplete(self):
        with self.assertRaisesRegex(ValueError,'listed shader variants'):
            seed.require_complete({'a':{}},['a'],self.done(1,1),self.done(2,3))

    def test_wrong_chain_cannot_enter_seed(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            key, suffix = 'a' * 64, 'b' * 12
            variant = key + '-' + suffix
            (folder / (key + '.variants')).write_text(json.dumps([{'variant': variant, 'deps': {}}]))
            (folder / (variant + '_b.metal')).write_text('kernel void main0() {}')
            reflection = folder / (variant + '_b.json')
            reflection.write_text(json.dumps(dict(chain='obsolete', entry='main0', key=variant + '_b')))
            with self.assertRaisesRegex(ValueError, 'reflection'):
                seed.seed_files(folder)
            reflection.write_text(json.dumps(dict(chain=seed.CHAIN, entry='main0', key=variant + '_b')))
            self.assertEqual(len(seed.seed_files(folder)), 3)


if __name__ == '__main__':
    unittest.main()
