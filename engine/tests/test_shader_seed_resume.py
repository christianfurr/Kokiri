"""Synthetic ledger reconciliation; never execute a game, translator or Metal tool."""
import contextlib
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_ns2_seed as seed
import resume_shader_seed as resume


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class ResumeFixture:
    def __init__(self, root, *, historical=True):
        self.root = root
        self.corpus = root/'build/ns2-corpus/oot.bin'
        records = []
        for number in range(2):
            control, code, label = bytes(0x60), struct.pack('<I', number), f'fixture-{number}'.encode()
            records.append(struct.pack('<IIIH', number, len(control), len(code), len(label))+label+control+code)
        self.corpus.parent.mkdir(parents=True)
        self.corpus.write_bytes(seed.CORPUS_MAGIC+struct.pack('<I', 2)+b''.join(records))
        self.inventory = seed.corpus_inventory(self.corpus)
        self.keys = list(self.inventory)
        self.shared = root/'shader_list.tsv'
        self.shared.write_text(f'V\t{self.keys[0]}\t'+json.dumps({'tex': {'0': '*2d'}}, separators=(',', ':'))+'\n')
        self.runtime, self.translator = root/'runtime', root/'translator'
        self.runtime.write_bytes(b'synthetic runtime'); self.translator.write_bytes(b'synthetic translator')
        context = seed.translation_context(self.translator, 'minus-w')
        self.cache = root/'build/ns2-seed-cache/oot'/context
        self.cache.mkdir(parents=True)
        self.service = self.cache/'tool/build/shader-service/totk_xlate'
        self.service.parent.mkdir(parents=True); self.service.write_bytes(self.translator.read_bytes())
        self.identity = dict(chain=seed.CHAIN, version='oot', source_romfs_sha256='1'*64,
                             corpus_sha256=seed.sha256(self.corpus), shader_list_sha256=seed.sha256(self.shared),
                             runtime_sha256=seed.sha256(self.runtime), translator_sha256=seed.sha256(self.translator),
                             translation_context_sha256=context, nvn_depth_mode='minus-w')
        self.chunks = seed.partition_corpus(self.corpus, root/'partitions', 2, self.shared)
        self.producer = root/'producer.json'
        write(self.producer, dict(schema=1, planned_batches=len(self.chunks), **{key:self.identity[key] for key in
              ('corpus_sha256', 'runtime_sha256', 'translator_sha256', 'translation_context_sha256')}))
        self.plan_path = root/'resume.json'
        self.plan = dict(schema=resume.SCHEMA, identity=self.identity, partitions=[], windows=[])
        self.window_values = []
        self.child_values = []
        self.proof_values = []
        for number, chunk in enumerate(self.chunks):
            descriptor = dict(number=number, corpus=chunk['corpus'], list=chunk['list'],
                              corpus_sha256=chunk['corpus_sha256'], list_sha256=chunk['list_sha256'])
            self.plan['partitions'].append(descriptor)
            window_dir = root/'windows'/str(number)
            window_dir.mkdir(parents=True)
            proof_path, receipt_path = window_dir/'proof.json', window_dir/'receipt.json'
            grant = dict(owner_thread_id='01a1e00c-e2ee-7dd3-bdcf-31eef3625144', state='granted',
                         grant_id=f'fixture-{number}', lease_content_sha256='a'*64)
            proof = dict(schema='kokiri-finite-source-proof-v1', grant_id=grant['grant_id'], lease_content_sha256='a'*64,
                         selected_batches=[number], source_corpus=dict(sha256=self.identity['corpus_sha256']),
                         producer_progress_path=str(self.producer), producer_progress_sha256=seed.sha256(self.producer),
                         inputs={str(path.resolve()):dict(sha256=seed.sha256(path)) for path in
                                 (self.shared, self.runtime, self.service)},
                         batch_plans=[dict(batch_number=number, batch_path=chunk['corpus'], list_path=chunk['list'],
                            batch_sha256=chunk['corpus_sha256'], list_sha256=chunk['list_sha256'], keys=sorted(chunk['keys']),
                            defaults_requested=len(chunk['keys']), binding_requests=chunk['listed_requests'],
                            conservative_known_requests=chunk['known_requests'],
                            source_record_offset=12+sum(len(raw) for raw in records[:number]))])
            write(proof_path, proof)
            self.proof_values.append((proof_path, proof))
            attempt = window_dir/'batch'; attempt.mkdir()
            names = set()
            for key in chunk['keys']:
                variants = [key+'-'+'b'*12]+([key+'-'+'c'*12] if number == 0 else [])
                names.update(variants)
                retained = variants+([key+'-'+'d'*12] if number == 0 else [])
                write(self.cache/(key+'.variants'), [dict(variant=name, deps={}, request='f'*64) for name in retained])
                for name in retained:
                    (self.cache/(name+'_b.metal')).write_text('kernel void main0() {} // '+name)
                    write(self.cache/(name+'_b.json'), dict(chain=seed.CHAIN, key=name+'_b', entry='main0'))
            listed = chunk['listed_requests']
            log = (f'[seed] done in 1 s: {len(chunk["keys"])} of {len(chunk["keys"])} shaders have a translation\n'
                   f"[seed] the shader list's bind states: {listed} of {listed} translated\n"
                   f'[seed] requests checked: {len(names)} variants for this runtime, {len(names)} cached ones kept, 0 made again\n')
            log_path, verified_path = attempt/'native.log', attempt/'verified.txt'
            log_path.write_text(log); verified_path.write_text('\n'.join(sorted(names))+'\n')
            completion = seed.batch_completion(log, chunk['keys'], names, True, expected_listed_requests=listed)
            outputs, _ = seed.verified_batch_outputs(self.cache, names, chunk['keys'], 1)
            completion['output_sha256'] = seed.parallel_sha256(list(outputs.values()), 1)
            child_path = attempt/'receipt.json'
            child = dict(schema='kokiri-bounded-shader-batch-v2', status='batch-complete-only', returncode=0,
                         remaining_native_group=[], batch_number=number, source_proof_path=str(proof_path),
                         source_proof_sha256=seed.sha256(proof_path), batch_sha256=chunk['corpus_sha256'],
                         list_sha256=chunk['list_sha256'], completion=completion,
                         command=[str(self.runtime), 'synthetic-rewritten', 'seed-shaders', chunk['corpus'], chunk['list']],
                         effective_env=dict(TOTK_SHADER_CACHE=str(self.cache.resolve()), TOTK_NATIVE_DIR=str(self.service.parent.parent),
                            TOTK_SEED_DEPTH_MODE='minus-w', TOTK_SHADER_SEED='off', TOTK_RT_BG_WORKERS='1',
                            TOTK_SHADER_SERVICE='native', TOTK_XLATE_SPIRV_CROSS='inproc', TOTK_SEED_VERIFY='1'))
            if historical:
                completion.update(log=str(log_path), log_sha256=seed.sha256(log_path),
                                  verified_path=str(verified_path), verified_sha256=seed.sha256(verified_path))
            write(child_path, child)
            self.child_values.append((child_path, child))
            entry = dict(batch=number, receipt=str(child_path), receipt_sha256=seed.sha256(child_path), result='batch-complete-only')
            window = dict(schema='kokiri-finite-shader-window-v2', status='finite-window-complete-only', remaining_supervisor_group=[],
                          jobs=1, maximum_known_requests=4000, maximum_seconds=300, full_seed_published=False, prepared=False,
                          grant=grant, selected_batches=[number], completed=[entry], source_proof_path=str(proof_path),
                          source_proof_sha256=seed.sha256(proof_path))
            self.window_values.append((receipt_path, window))
            self.plan['windows'].append(dict(receipt=str(receipt_path), receipt_sha256='', ledger_sha256=''))
        self.refresh()

    def refresh(self):
        for index, ((proof_path, proof), (child_path, child), (window_path, window)) in enumerate(
                zip(self.proof_values, self.child_values, self.window_values)):
            write(proof_path, proof)
            child['source_proof_sha256'] = seed.sha256(proof_path)
            write(child_path, child)
            window['source_proof_sha256'] = seed.sha256(proof_path)
            window['completed'][0]['receipt_sha256'] = seed.sha256(child_path)
            ledger = window_path.parent/'ledger.jsonl'
            ledger.write_text(''.join(json.dumps(entry)+'\n' for entry in window['completed']))
            write(window_path, window)
            self.plan['windows'][index].update(receipt_sha256=seed.sha256(window_path), ledger_sha256=seed.sha256(ledger))
        write(self.plan_path, self.plan)

    def reconcile(self, **kwargs):
        return resume.reconcile_plan(self.plan_path, expected_identity=kwargs.get('identity', self.identity),
                                     corpus=self.corpus, shader_list=self.shared, cache=self.cache, jobs=1)


class ResumeTests(unittest.TestCase):
    def test_complete_multiwindow_evidence_reconciles_without_native_or_partition_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = ResumeFixture(Path(folder))
            before = {Path(chunk['corpus']):Path(chunk['corpus']).read_bytes() for chunk in fixture.chunks}
            with mock.patch.object(seed.subprocess, 'run') as run, mock.patch.object(seed, 'partition_corpus') as partition:
                result = fixture.reconcile()
                run.assert_not_called(); partition.assert_not_called()
            self.assertEqual(set(result['inventory']), set(fixture.keys))
            self.assertEqual(result['totals']['translated_default'], 2)
            self.assertEqual(result['totals']['listed_asked'], 1)
            self.assertEqual(len(result['verified']), 3)
            self.assertTrue(all(row['corroboration'] == 'historical-hashes' for row in result['progress']['batches']))
            for path, raw in before.items(): self.assertEqual(path.read_bytes(), raw)

    def test_legacy_log_corroboration_requires_explicit_admission_and_is_labelled(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = ResumeFixture(Path(folder), historical=False)
            with self.assertRaisesRegex(ValueError, 'explicit import-time'):
                fixture.reconcile()
            for window in fixture.plan['windows']: window['allow_import_time_corroboration'] = True
            write(fixture.plan_path, fixture.plan)
            result = fixture.reconcile()
            self.assertTrue(all(row['corroboration'] == 'import-time-only' for row in result['progress']['batches']))
            self.assertTrue(all('imported_log_sha256' in row for row in result['progress']['batches']))

    def test_missing_duplicate_failed_unknown_and_unledgered_evidence_are_rejected(self):
        for failure in ('missing', 'duplicate', 'failed-child', 'unknown-child', 'failed-window', 'missing-ledger'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                fixture = ResumeFixture(Path(folder))
                if failure == 'missing': fixture.plan['windows'].pop()
                elif failure == 'duplicate': fixture.plan['windows'].append(copy.deepcopy(fixture.plan['windows'][0]))
                elif failure == 'failed-child': fixture.child_values[0][1]['status'] = 'failed'
                elif failure == 'unknown-child': fixture.child_values[0][1]['schema'] = 'old-direct-probe'
                elif failure == 'failed-window': fixture.window_values[0][1]['status'] = 'failed'
                if failure in ('failed-child', 'unknown-child', 'failed-window'): fixture.refresh()
                else: write(fixture.plan_path, fixture.plan)
                if failure == 'missing-ledger': (fixture.window_values[0][0].parent/'ledger.jsonl').unlink()
                with self.assertRaises((ValueError, OSError)):
                    fixture.reconcile()

    def test_partition_gaps_and_resealed_omitted_source_binding_are_rejected(self):
        for failure in ('missing-partition', 'duplicate-number', 'omitted-binding'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                fixture = ResumeFixture(Path(folder))
                if failure == 'missing-partition': fixture.plan['partitions'].pop()
                elif failure == 'duplicate-number': fixture.plan['partitions'][1]['number'] = 0
                else:
                    listed = Path(fixture.chunks[0]['list']); listed.write_text('')
                    fixture.plan['partitions'][0]['list_sha256'] = seed.sha256(listed)
                write(fixture.plan_path, fixture.plan)
                with self.assertRaisesRegex(ValueError, 'incomplete|ordered|binding membership'):
                    fixture.reconcile()

    def test_changed_historical_proof_or_null_hash_is_not_relabelled_as_corroboration(self):
        for failure in ('null-hash', 'old-log', 'missing-proof'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                fixture = ResumeFixture(Path(folder))
                if failure == 'null-hash':
                    fixture.child_values[0][1]['completion']['log_sha256'] = None; fixture.refresh()
                elif failure == 'old-log':
                    (fixture.child_values[0][0].parent/'native.log').write_text('different historical log')
                else:
                    fixture.proof_values[0][1]['batch_plans'] = []; fixture.refresh()
                with self.assertRaisesRegex(ValueError, 'pinned hash|hash differs|immutable partition plan'):
                    fixture.reconcile()

    def test_historical_completion_hashes_cannot_be_ignored_by_legacy_optin(self):
        for failure in ('corrupt-log-hash', 'corrupt-verified-hash', 'only-one-hash'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                fixture = ResumeFixture(Path(folder))
                for window in fixture.plan['windows']: window['allow_import_time_corroboration'] = True
                completion = fixture.child_values[0][1]['completion']
                if failure == 'corrupt-log-hash': completion['log_sha256'] = '0'*64
                elif failure == 'corrupt-verified-hash': completion['verified_sha256'] = '0'*64
                else: completion.pop('verified_sha256')
                fixture.refresh()
                with self.assertRaisesRegex(ValueError, 'hash differs|incomplete historical'):
                    fixture.reconcile()

    def test_stale_runtime_context_index_output_binding_and_log_are_rejected(self):
        for failure in ('runtime', 'translator', 'chain', 'depth', 'index', 'msl', 'binding', 'log', 'request', 'descendants'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                fixture = ResumeFixture(Path(folder))
                if failure in ('runtime', 'translator', 'chain', 'depth'):
                    field = {'runtime':'runtime_sha256', 'translator':'translator_sha256', 'chain':'chain', 'depth':'nvn_depth_mode'}[failure]
                    identity = dict(fixture.identity, **{field:'changed'})
                    fixture.plan['identity'] = identity; write(fixture.plan_path, fixture.plan)
                    with self.assertRaisesRegex(ValueError, 'context|revalidation'):
                        fixture.reconcile(identity=identity)
                    continue
                if failure == 'index':
                    (fixture.cache/(fixture.keys[0]+'.variants')).write_text('[]')
                elif failure == 'msl':
                    (fixture.cache/(fixture.keys[0]+'-'+'b'*12+'_b.metal')).write_text('changed')
                elif failure == 'binding':
                    Path(fixture.chunks[0]['list']).write_text('')
                elif failure == 'log':
                    (fixture.child_values[0][0].parent/'native.log').write_text('not completed')
                elif failure == 'request':
                    path = fixture.cache/(fixture.keys[0]+'.variants')
                    entries = json.loads(path.read_text()); entries[0].pop('request'); write(path, entries)
                    fixture.child_values[0][1]['completion']['output_sha256'][path.name] = seed.sha256(path)
                    fixture.refresh()
                elif failure == 'descendants':
                    fixture.child_values[0][1]['remaining_native_group'] = [{'pid':123}]; fixture.refresh()
                with self.assertRaises((ValueError, OSError)):
                    fixture.reconcile()

    def test_cli_publish_only_requires_both_flags(self):
        for flags in (['--resume-plan', 'fixture.json'], ['--publish-verified-only']):
            with mock.patch.object(sys, 'argv', ['prepare_ns2_seed.py', '--version', 'oot', '--depth-mode', 'minus-w',
                                   '--binary', 'unused', *flags]):
                with self.assertRaises(SystemExit) as result: seed.main()
                self.assertEqual(result.exception.code, 2)

    def test_publish_only_cli_preserves_partitions_and_full_cache_without_native_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = ResumeFixture(root)
            romfs = root/'extracted/oot/romfs'
            write(romfs/'index.json', dict(romfs_sha256='1'*64))
            write(fixture.corpus.with_suffix('.json'), dict(romfs_sha256='1'*64, modules={},
                tool=seed.sha256(Path(seed.__file__).parent/'ns2_shader_corpus.py'), list=seed.sha256(fixture.shared)))
            protected = {path:path.read_bytes() for path in fixture.cache.glob('*') if path.is_file()}
            partitions = {Path(chunk['corpus']):Path(chunk['corpus']).read_bytes() for chunk in fixture.chunks}
            output = root/'published'
            args = ['prepare_ns2_seed.py', '--version', 'oot', '--depth-mode', 'minus-w',
                    '--binary', str(fixture.runtime), '--translator', str(fixture.translator), '--list', str(fixture.shared),
                    '--resume-plan', str(fixture.plan_path), '--publish-verified-only', '--output', str(output), '--jobs', '1']
            with contextlib.chdir(root), mock.patch.object(sys, 'argv', args), \
                 mock.patch.object(seed, 'run') as extraction, mock.patch.object(seed, 'partition_corpus') as partition, \
                 mock.patch.object(seed.subprocess, 'run') as native, mock.patch.object(seed.subprocess, 'Popen') as popen:
                seed.main()
                extraction.assert_not_called(); partition.assert_not_called(); native.assert_not_called(); popen.assert_not_called()
            metadata = json.loads((output/'seed-manifest.json').read_text())
            self.assertEqual(metadata['translated_default'], 2)
            self.assertEqual(metadata['shaders'], 3)
            self.assertEqual(metadata['runtime_sha256'], fixture.identity['runtime_sha256'])
            for path, contents in {**protected, **partitions}.items(): self.assertEqual(path.read_bytes(), contents)
            extra = fixture.keys[0]+'-'+'d'*12+'_b.metal'
            self.assertTrue((fixture.cache/extra).exists())
            self.assertFalse((output/extra).exists())

    def test_changed_output_after_reconciliation_cannot_replace_prior_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = ResumeFixture(root)
            result = fixture.reconcile()
            out = root/'published'; out.mkdir(); (out/'prior').write_bytes(b'prior seed')
            filename = fixture.keys[0]+'-'+'b'*12+'_b.metal'
            (fixture.cache/filename).write_text('changed after reconciliation')
            inputs = {key:value for key, value in fixture.identity.items() if key != 'runtime_sha256'}
            metadata = dict(fixture.identity, schema=1, game='oot', inputs=inputs, files={}, all_default=True,
                            corpus_shaders=2, translated_default=2, listed_variants=1, listed_asked=1)
            with self.assertRaisesRegex(ValueError, 'changed after reconciliation'):
                seed.publish_seed(out, fixture.cache, result['verified'], result['inventory'], metadata,
                                  started_at=0, jobs=1, protected_paths=result['protected_paths'],
                                  expected_output_sha256=result['output_sha256'])
            self.assertEqual((out/'prior').read_bytes(), b'prior seed')

    def test_publish_only_cannot_regenerate_an_unverified_corpus(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); fixture = ResumeFixture(root)
            write(root/'extracted/oot/romfs/index.json', dict(romfs_sha256='1'*64))
            write(fixture.corpus.with_suffix('.json'), {'stale': True})
            args = ['prepare_ns2_seed.py', '--version', 'oot', '--depth-mode', 'minus-w',
                    '--binary', str(fixture.runtime), '--translator', str(fixture.translator), '--list', str(fixture.shared),
                    '--resume-plan', str(fixture.plan_path), '--publish-verified-only']
            with contextlib.chdir(root), mock.patch.object(sys, 'argv', args), mock.patch.object(seed, 'run') as extraction:
                with self.assertRaisesRegex(ValueError, 'regeneration is disabled'):
                    seed.main()
                extraction.assert_not_called()


if __name__ == '__main__':
    unittest.main()
