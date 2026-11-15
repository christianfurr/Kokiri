"""Synthetic coverage failures that must stop a full-preparation claim."""
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/preparation_receipt.py'
spec = importlib.util.spec_from_file_location('preparation_receipt', SCRIPT)
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


class PreparationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(chain='oot-native-v28-mesh-primitive-blocks', source_romfs_sha256='a' * 64,
                             translator_sha256='b' * 64, nvn_depth_mode='minus-w')
        self.seed = dict(self.identity, version='oot', all_default=True, only=None,
                         translation_context_sha256='c' * 64, runtime_sha256='d' * 64,
                         corpus_shaders=2, translated_default=2, listed_asked=1, listed_variants=1,
                         shaders=3, files={'first_b.metal': '1' * 64,
                                           'second_b.metal': '2' * 64, 'binding_b.metal': '3' * 64})
        self.libraries = dict(complete=True, subset=False,
                              compiler='Metal fixture -fpreserve-invariance -fwrapv',
                              sources=copy.deepcopy(self.seed['files']),
                              files={str(n) * 64 + '.metallib': 'e' * 64 for n in range(1, 4)})
        self.pipelines = dict(chain=self.identity['chain'], runtime_sha256='f' * 64,
                              render=2, compute=1, mesh=1, kept=2, failed=0, write_failed=0,
                              arch='fixture_gpu', listed_mesh=1, mesh_indexed=1)
        self.artifacts = {field: 'f' * 64 for field in receipt.ARTIFACT_FIELDS}

    def make(self, mode='full'):
        return receipt.preparation_receipt(mode, self.seed, self.libraries, self.pipelines,
                                           expected_identity=self.identity, artifact_sha256=self.artifacts,
                                           pipeline_requested=6, source_commit='0' * 40)

    def reject(self, message):
        result = self.make()
        self.assertFalse(result['prepared'])
        with self.assertRaisesRegex(ValueError, message):
            receipt.require_prepared(result)
        return result

    def test_exact_full_request_accounting_is_prepared(self):
        result = receipt.require_prepared(self.make())
        self.assertEqual(result['variants']['unique_completed'], 3)
        self.assertEqual(result['libraries']['completed'], 3)
        self.assertEqual(result['pipelines']['completed'], 6)
        self.assertEqual(result['identity']['chain'], self.identity['chain'])
        self.assertEqual(result['artifact_sha256'], self.artifacts)
        self.assertIn('unobserved', result['limitation'])

    def test_none_and_title_cannot_claim_prepared(self):
        for mode in ('none', 'title'):
            result = self.make(mode)
            self.assertFalse(result['prepared'])
            with self.assertRaisesRegex(ValueError, 'only full shader mode'):
                receipt.require_prepared(result)

    def test_missing_seed_cannot_claim_prepared(self):
        self.seed = None
        self.reject('default shader requests are incomplete')

    def test_default_shader_omission_cannot_hide_behind_all_default(self):
        self.seed['translated_default'] = 1
        result = self.reject('default shader requests are incomplete')
        self.assertEqual(result['variants']['default']['failed'], 1)

    def test_manifest_cannot_attest_more_defaults_than_variants(self):
        self.seed['corpus_shaders'] = 4
        self.seed['translated_default'] = 4
        self.reject('seed has fewer variants than default shader requests')

    def test_listed_binding_failure_is_fatal(self):
        self.seed['listed_variants'] = 0
        result = self.reject('listed shader requests are incomplete')
        self.assertEqual(result['variants']['listed']['failed'], 1)

    def test_subset_seed_is_not_full(self):
        self.seed['only'] = 2
        self.reject('seed was restricted')

    def test_subset_libraries_are_not_full(self):
        self.libraries['subset'] = True
        self.reject('Metal libraries were restricted')

    def test_binding_library_omission_is_fatal(self):
        self.libraries['files'].pop('3' * 64 + '.metallib')
        result = self.reject('Metal libraries do not cover')
        self.assertEqual(result['libraries']['failed'], 1)

    def test_incomplete_library_manifest_is_fatal(self):
        self.libraries['complete'] = False
        self.reject('Metal library compilation is incomplete')

    def test_failed_render_or_mesh_is_not_prepared(self):
        self.pipelines['failed'] = 1
        self.reject('pipeline preparation or archive writes failed')

    def test_silently_skipped_pipeline_is_not_prepared(self):
        self.pipelines['render'] = 1
        result = self.reject('pipeline completion does not cover')
        self.assertEqual(result['pipelines']['unaccounted'], 1)

    def test_extra_completed_rows_do_not_establish_matching_coverage(self):
        self.pipelines['kept'] = 3
        self.reject('pipeline completion does not cover')

    def test_archive_write_failure_is_fatal_even_with_all_built(self):
        self.pipelines['write_failed'] = 1
        self.reject('pipeline preparation or archive writes failed')

    def test_missing_mesh_archive_records_are_fatal(self):
        self.pipelines['mesh_indexed'] = 0
        self.reject('does not cover the declared mesh requests')

    def test_v23_seed_cannot_be_relabelled_as_v28(self):
        self.seed['chain'] = 'oot-native-v23-txd-derivative-order'
        self.reject('seed identity differs: chain')

    def test_different_translator_is_fatal(self):
        self.seed['translator_sha256'] = 'e' * 64
        self.reject('seed identity differs: translator_sha256')

    def test_different_pipeline_runtime_is_fatal(self):
        self.pipelines['runtime_sha256'] = 'a' * 64
        self.reject('pipeline archive belongs to another runtime')

    def test_missing_artifact_identity_is_fatal(self):
        self.artifacts.pop('pipeline_index_sha256')
        self.reject('missing artifact SHA-256: pipeline_index_sha256')

    def test_missing_counter_is_unknown_not_zero(self):
        self.pipelines.pop('failed')
        result = self.reject('missing or invalid count: failed')
        self.assertIsNone(result['pipelines']['failed'])


if __name__ == '__main__':
    unittest.main()
