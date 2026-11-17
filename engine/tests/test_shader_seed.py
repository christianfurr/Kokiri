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
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_ns2_seed as seed


class SeedTests(unittest.TestCase):
    def publication_fixture(self, root):
        cache = root/'cache'
        cache.mkdir()
        key = 'a'*64
        verified, extra = key+'-'+'b'*12, key+'-'+'c'*12
        entries = [dict(variant=name, deps={}, request='f'*64) for name in (verified, extra)]
        (cache/(key+'.variants')).write_text(json.dumps(entries))
        for name in (verified, extra):
            (cache/(name+'_b.metal')).write_text('kernel void main0() {} // '+name)
            (cache/(name+'_b.json')).write_text(json.dumps(dict(chain=seed.CHAIN, key=name+'_b', entry='main0')))
        inputs = dict(chain=seed.CHAIN, version='oot', source_romfs_sha256='1'*64,
                      translation_context_sha256='2'*64, nvn_depth_mode='minus-w', translator_sha256='3'*64,
                      shader_list_sha256=None, corpus_sha256='4'*64, scripts_sha256={}, only_sha256=None)
        metadata = dict(inputs, schema=1, game='oot', runtime_sha256='5'*64, corpus_inputs={},
                        all_default=True, only=None, stages={'4': 1}, preparation_sha256='6'*64,
                        corpus_shaders=1, translated_default=1, listed_variants=0, listed_asked=0,
                        batch_receipts={'status': 'complete'}, inputs=inputs, files={})
        return cache, key, verified, extra, metadata

    def test_seed_publisher_filters_verified_variants_and_preserves_complete_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache, key, verified, extra, metadata = self.publication_fixture(root)
            before = (cache/(key+'.variants')).read_bytes()
            out = root/'published'
            report = seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                       started_at=time.time(), jobs=1)
            self.assertEqual(json.loads((out/(key+'.variants')).read_text()),
                             [json.loads(before)[0]])
            self.assertFalse((out/(extra+'_b.metal')).exists())
            self.assertTrue((cache/(extra+'_b.metal')).exists())
            self.assertEqual((cache/(key+'.variants')).read_bytes(), before)
            self.assertEqual((out/(verified+'_b.metal')).stat().st_ino,
                             (cache/(verified+'_b.metal')).stat().st_ino)
            self.assertEqual(json.loads((out/'shader-keys.json').read_text())['keys'], [key])
            self.assertEqual(report['shaders'], 1)
            self.assertEqual(report['inputs'], metadata['inputs'])
            self.assertEqual(report['batch_receipts'], metadata['batch_receipts'])
            self.assertEqual(json.loads((out/'seed-manifest.json').read_text()), report)
            self.assertTrue(out.with_name('published.verified.json').is_file())
            for name, digest in report['files'].items():
                self.assertEqual(seed.sha256(out/name), digest)

    def test_missing_verified_output_cannot_replace_existing_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache, key, verified, extra, metadata = self.publication_fixture(root)
            out = root/'published'
            out.mkdir()
            (out/'prior-seed').write_bytes(b'preserve prior published bytes')
            (cache/(extra+'_b.metal')).unlink()
            metadata.update(listed_variants=1, listed_asked=1)
            with self.assertRaisesRegex(ValueError, 'missing cached outputs'):
                seed.publish_seed(out, cache, {verified, extra}, {key: {'stage': 4}}, metadata,
                                  started_at=time.time(), jobs=1)
            self.assertEqual((out/'prior-seed').read_bytes(), b'preserve prior published bytes')
            self.assertFalse(out.with_name('published.partial').exists())

    def test_publication_context_or_reflection_mismatch_preserves_prior_seed(self):
        for mismatch in ('context', 'reflection'):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, _, metadata = self.publication_fixture(root)
                out = root/'published'
                out.mkdir()
                (out/'prior-seed').write_bytes(b'prior')
                if mismatch == 'context':
                    metadata['translator_sha256'] = 'e'*64
                else:
                    (cache/(verified+'_b.json')).write_text(json.dumps(dict(chain='old-chain', key=verified+'_b', entry='main0')))
                with self.assertRaisesRegex(ValueError, 'context|reflection'):
                    seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                      started_at=time.time(), jobs=1)
                self.assertEqual((out/'prior-seed').read_bytes(), b'prior')

    def test_publication_rename_failure_restores_prior_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache, key, verified, _, metadata = self.publication_fixture(root)
            out = root/'published'
            out.mkdir()
            (out/'prior-seed').write_bytes(b'prior')
            rename = Path.rename

            def fail_staging(path, target):
                if path == out.with_name('published.partial'):
                    raise OSError('synthetic publication failure')
                return rename(path, target)

            with mock.patch.object(Path, 'rename', fail_staging):
                with self.assertRaisesRegex(OSError, 'synthetic publication failure'):
                    seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                      started_at=time.time(), jobs=1)
            self.assertEqual((out/'prior-seed').read_bytes(), b'prior')

    def test_publication_rejects_cache_output_and_generated_path_overlaps_before_mutation(self):
        for overlap in ('equal', 'ancestor', 'descendant', 'parent-symlink', 'stage-symlink', 'old-symlink'):
            with self.subTest(overlap=overlap), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, extra, metadata = self.publication_fixture(root)
                prior = root/'published'
                prior.mkdir()
                (prior/'prior-seed').write_bytes(b'prior')
                out = prior
                if overlap == 'equal': out = cache
                elif overlap == 'ancestor': out = root
                elif overlap == 'descendant': out = cache/'new-seed'
                elif overlap == 'parent-symlink':
                    alias = root/'alias'; alias.symlink_to(cache, target_is_directory=True); out = alias/'new-seed'
                elif overlap == 'stage-symlink':
                    prior.with_name('published.partial').symlink_to(cache, target_is_directory=True)
                else:
                    (root/f'.published.old-{os.getpid()}-123').symlink_to(cache, target_is_directory=True)
                before = {path.name:path.read_bytes() for path in cache.iterdir() if path.is_file()}
                with mock.patch.object(seed.time, 'time_ns', return_value=123), \
                     mock.patch.object(seed.shutil, 'rmtree') as remove, \
                     mock.patch.object(Path, 'rename') as rename, \
                     mock.patch.object(Path, 'mkdir') as mkdir:
                    with self.assertRaisesRegex(ValueError, 'protected'):
                        seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                          started_at=time.time(), jobs=1)
                    remove.assert_not_called(); rename.assert_not_called(); mkdir.assert_not_called()
                self.assertEqual({path.name:path.read_bytes() for path in cache.iterdir() if path.is_file()}, before)
                self.assertTrue((cache/(extra+'_b.metal')).exists())
                self.assertEqual((prior/'prior-seed').read_bytes(), b'prior')

    def test_publication_protects_selected_input_and_evidence_sentinels(self):
        for protected_kind in ('output-child', 'stage', 'backup-record', 'symlink-parent'):
            with self.subTest(protected_kind=protected_kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, _, metadata = self.publication_fixture(root)
                out = root/'published'
                out.mkdir()
                (out/'prior-seed').write_bytes(b'prior')
                if protected_kind == 'output-child':
                    proof = out/'ledger.jsonl'
                elif protected_kind == 'stage':
                    stage = root/'published.partial'; stage.mkdir(); proof = stage/'corpus.bin'
                elif protected_kind == 'backup-record':
                    proof = root/f'.published.old-{os.getpid()}-123.verified.json'
                else:
                    evidence = root/'evidence'; evidence.mkdir(); proof = evidence/'proof.json'
                    alias = root/'alias'; alias.symlink_to(evidence, target_is_directory=True)
                    out = alias/'not-created-yet'
                proof.write_bytes(b'protected source/evidence bytes')
                with mock.patch.object(seed.time, 'time_ns', return_value=123), \
                     mock.patch.object(seed.shutil, 'rmtree') as remove, \
                     mock.patch.object(Path, 'rename') as rename, \
                     mock.patch.object(Path, 'mkdir') as mkdir:
                    protected = proof.parent if protected_kind == 'symlink-parent' else proof
                    with self.assertRaisesRegex(ValueError, 'protected'):
                        seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                          started_at=time.time(), protected_paths=(protected,), jobs=1)
                    remove.assert_not_called(); rename.assert_not_called(); mkdir.assert_not_called()
                self.assertEqual(proof.read_bytes(), b'protected source/evidence bytes')
                self.assertEqual((root/'published/prior-seed').read_bytes(), b'prior')

    def test_case_alias_of_existing_cache_ancestor_is_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache, _, _, _, _ = self.publication_fixture(root)
            alias = root/'CACHE'
            if not alias.exists() or not os.path.samefile(alias, cache):
                self.skipTest('filesystem is case sensitive')
            with self.assertRaisesRegex(ValueError, 'protected'):
                seed.guard_publication_paths(alias/'new-seed', cache, root/'safe-stage', root/'safe-old')

    def test_known_logs_are_protected_without_extra_caller_paths(self):
        for overlap in ('equal', 'ancestor'):
            with self.subTest(overlap=overlap), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, extra, metadata = self.publication_fixture(root)
                out = root/'published'; out.mkdir(); (out/'prior-seed').write_bytes(b'prior')
                logs = out if overlap == 'equal' else out/'logs'
                logs.mkdir(exist_ok=True)
                (logs/'selected.log').write_bytes(b'preserve selected evidence')
                with mock.patch.object(seed.shutil, 'rmtree') as remove, mock.patch.object(Path, 'rename') as rename:
                    with self.assertRaisesRegex(ValueError, 'protected'):
                        seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                          started_at=time.time(), logs=logs, jobs=1)
                    remove.assert_not_called(); rename.assert_not_called()
                self.assertEqual((logs/'selected.log').read_bytes(), b'preserve selected evidence')
                self.assertEqual((out/'prior-seed').read_bytes(), b'prior')
                self.assertTrue((cache/(extra+'_b.metal')).exists())

    def test_verification_record_failure_preserves_prior_seed_and_record(self):
        for failure in ('write', 'rename'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, extra, metadata = self.publication_fixture(root)
                out = root/'published'; out.mkdir(); (out/'prior-seed').write_bytes(b'prior')
                prior_record = root/'published.verified.json'; prior_record.write_bytes(b'prior verification record')
                rename = Path.rename
                def fail_record(path, target):
                    if path == root/'published.partial.verified.json':
                        raise OSError('synthetic record install failure')
                    return rename(path, target)
                patch = (mock.patch.object(seed, 'record_verified', side_effect=OSError('synthetic record write failure'))
                         if failure == 'write' else mock.patch.object(Path, 'rename', fail_record))
                with patch, mock.patch.object(seed.subprocess, 'Popen') as cleanup:
                    with self.assertRaisesRegex(OSError, 'synthetic record'):
                        seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                          started_at=time.time(), jobs=1)
                    cleanup.assert_not_called()
                self.assertEqual((out/'prior-seed').read_bytes(), b'prior')
                self.assertEqual(prior_record.read_bytes(), b'prior verification record')
                self.assertTrue((cache/(extra+'_b.metal')).exists())

    def test_cached_publication_updates_runtime_proof_without_retranslating_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache, key, verified, _, metadata = self.publication_fixture(root)
            entries = json.loads((cache/(key+'.variants')).read_text())
            (cache/(key+'.variants')).write_text(json.dumps(entries[:1]))
            out = root/'published'
            first = seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                      started_at=time.time(), jobs=1)
            inode = (cache/(verified+'_b.metal')).stat().st_ino
            self.assertIsNone(seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                               started_at=time.time(), jobs=1))
            changed = dict(metadata, runtime_sha256='9'*64)
            with mock.patch.object(seed.subprocess, 'Popen'):
                updated = seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, changed,
                                            started_at=time.time(), jobs=1)
            self.assertEqual(updated['runtime_sha256'], '9'*64)
            self.assertEqual(updated['inputs'], first['inputs'])
            self.assertEqual((out/(verified+'_b.metal')).stat().st_ino, inode)
            self.assertEqual(json.loads((out/'seed-manifest.json').read_text())['runtime_sha256'], '9'*64)

    def test_unchanged_publication_rechecks_expected_cache_hashes_before_return(self):
        for changed in ('metal', 'index'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache, key, verified, _, metadata = self.publication_fixture(root)
                entries = json.loads((cache/(key+'.variants')).read_text())
                (cache/(key+'.variants')).write_text(json.dumps(entries[:1]))
                outputs, _ = seed.verified_batch_outputs(cache, {verified}, {key}, 1)
                expected = seed.parallel_sha256(list(outputs.values()), 1)
                out = root/'published'
                seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                  started_at=time.time(), jobs=1, expected_output_sha256=expected)
                (out/'prior-seed-sentinel').write_bytes(b'preserve prior seed')
                if changed == 'metal':
                    (cache/(verified+'_b.metal')).write_text('in-place change after reconciliation')
                else:
                    entries[0]['request'] = '0'*64
                    (cache/(key+'.variants')).write_text(json.dumps(entries[:1]))
                before = {path:path.read_bytes() for path in cache.iterdir() if path.is_file()}
                with mock.patch.object(seed.shutil, 'rmtree') as remove, mock.patch.object(Path, 'rename') as rename:
                    with self.assertRaisesRegex(ValueError, 'changed after reconciliation'):
                        seed.publish_seed(out, cache, {verified}, {key: {'stage': 4}}, metadata,
                                          started_at=time.time(), jobs=1, expected_output_sha256=expected)
                    remove.assert_not_called(); rename.assert_not_called()
                self.assertEqual((out/'prior-seed-sentinel').read_bytes(), b'preserve prior seed')
                for path, contents in before.items(): self.assertEqual(path.read_bytes(), contents)

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

    def test_cached_only_batches_require_every_native_request_to_be_kept(self):
        key = 'a' * 64
        verified = {key + '-' + 'c' * 12}
        text = self.completion(1).replace('0 cached ones kept', '1 cached ones kept')
        report = seed.batch_completion(text, [key], verified, require_cached=True)
        self.assertEqual(report['made_again'], 0)
        text = text.replace('1 cached ones kept, 0 made again', '0 cached ones kept, 1 made again')
        with self.assertRaisesRegex(ValueError, 'cached-only'):
            seed.batch_completion(text, [key], verified, require_cached=True)
        with self.assertRaisesRegex(ValueError, 'verified set'):
            seed.batch_completion(self.completion(1), [key], set(), require_cached=True)

    def test_cached_only_requires_complete_prior_inventory_and_exact_context(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);translator=out/'translator';translator.write_bytes(b'pinned translator')
            record=dict(chain=seed.CHAIN,translation_context_sha256='a'*64,translator_sha256=seed.sha256(translator),
                        all_default=True,only=None,corpus_shaders=1,translated_default=1,listed_asked=0,listed_variants=0,
                        files={'a_b.metal':'b'*64,**{name:'c'*64 for name in seed.GENERATED}})
            manifest=out/'seed-manifest.json';manifest.write_text(json.dumps(record))
            self.assertEqual(seed.cached_seed_outputs(out,'a'*64,translator),{'a_b.metal':'b'*64})
            for changed in (dict(files={}),dict(files={'../escape':'b'*64}),dict(all_default=False),
                            dict(translated_default=0),dict(translation_context_sha256='c'*64)):
                manifest.write_text(json.dumps({**record,**changed}))
                with self.assertRaisesRegex(ValueError,'complete compatible'):
                    seed.cached_seed_outputs(out,'a'*64,translator)

    def test_cached_only_rejects_old_evidence_resume_before_reading_inputs(self):
        with mock.patch.object(sys,'argv',['prepare_ns2_seed.py','--version','oot','--depth-mode','minus-w',
                                           '--binary','/missing-runtime','--require-cached','--resume-plan','/old-plan',
                                           '--publish-verified-only']):
            with self.assertRaises(SystemExit) as done:
                seed.main()
            self.assertEqual(done.exception.code,2)

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
