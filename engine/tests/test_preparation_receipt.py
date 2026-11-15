"""Synthetic coverage failures that must stop a full-preparation claim."""
import copy
import importlib.util
from pathlib import Path
import unittest
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/preparation_receipt.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('preparation_receipt', SCRIPT)
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


class PreparationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(chain='oot-native-v28-mesh-primitive-blocks', source_romfs_sha256='a' * 64,
                             translator_sha256='b' * 64, nvn_depth_mode='minus-w')
        self.seed = dict(self.identity, version='oot', all_default=True, only=None,
                         translation_context_sha256='c' * 64, runtime_sha256='f' * 64,
                         corpus_shaders=2, translated_default=2, listed_asked=1, listed_variants=1,
                         shaders=3, files={'first_b.metal': '1' * 64,
                                           'second_b.metal': '2' * 64, 'binding_b.metal': '3' * 64})
        self.libraries = dict(complete=True, subset=False,
                              compiler='Metal fixture -fpreserve-invariance -fwrapv',
                              sources=copy.deepcopy(self.seed['files']),
                              files={str(n) * 64 + '.metallib': 'e' * 64 for n in range(1, 4)})
        observation = dict(qualified=True, backend='metal', path='/private/compiler', version='fixture',
                           executable_sha256='8' * 64,
                           effective_flags=['-mmacosx-version-min=26.0', '-fmetal-math-mode=safe',
                                            '-fpreserve-invariance', '-fwrapv'],
                           effective_target='air64-apple-macosx26.0.0', driver_plan='raw driver trace',
                           driver_plan_sha256='9' * 64, sdk_mode='compiler-default-resource-headers',
                           resource_headers={'content_sha256': '7' * 64},
                           available_macos_sdk={'path': '/private/sdk', 'version': '26.0'})
        observation.update(
            observation_schema=2,
            loader_environment_policy='reject-nonempty-DYLD',
            host_identity=dict(os_build='fixture-build', machine='arm64', kernel_release='fixture-kernel'),
            tool_components=[
                dict(role='driver', path='/private/compiler', size=100, executable_sha256='8' * 64, dependencies=[
                    dict(loader_sha256='8' * 64, install_name='/usr/lib/libSystem.B.dylib',
                         binding='os-build-system-component', os_build='fixture-build')]),
                dict(role='frontend', path='/private/frontend', size=200, executable_sha256='6' * 64, dependencies=[
                    dict(loader_sha256='6' * 64, install_name='@rpath/libCompiler.dylib',
                         binding='hashed-file', sha256='5' * 64, path='/private/libCompiler.dylib', size=50)]),
                dict(role='linker', path='/private/linker', size=300, executable_sha256='4' * 64, dependencies=[])],
            required_files=[dict(role='selected-invocation-input', sha256='3' * 64,
                                 path='/private/libmetal_rt_osx.a', size=123)],
            effective_invocations=[['/private/frontend', '-cc1', '-triple', 'air64-apple-macosx26.0.0',
                                    '-fwrapv', '-fpreserve-invariance',
                                    '-o', '<intermediate.air>', '<probe-dir>/identity.metal'],
                                   ['/private/linker', '<intermediate.air>', '/private/libmetal_rt_osx.a',
                                    '-o', '<probe-dir>/identity.partial']])
        self.libraries['compiler_observation'] = observation
        self.libraries['compiler_context_schema'] = 2
        self.libraries['compiler_context_sha256'] = receipt.compiler_context_key(observation)
        self.pipelines = dict(chain=self.identity['chain'], runtime_sha256='f' * 64,
                              render=2, compute=1, mesh=1, kept=2, failed=0, write_failed=0,
                              arch='fixture_gpu', listed_mesh=1, mesh_indexed=1)
        self.artifacts = {field: 'f' * 64 for field in receipt.ARTIFACT_FIELDS}

    def make(self, mode='full', **kwargs):
        return receipt.preparation_receipt(mode, self.seed, self.libraries, self.pipelines,
                                           expected_identity=self.identity, artifact_sha256=self.artifacts,
                                           pipeline_requested=6, source_commit='0' * 40, **kwargs)

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

    def test_changed_runtime_without_request_revalidation_is_not_prepared(self):
        self.artifacts['runtime_sha256'] = '0' * 64
        self.pipelines['runtime_sha256'] = '0' * 64
        result = self.reject('seed requests were not verified by the packaged runtime')
        self.assertEqual(result['identity']['seed_runtime_sha256'], 'f' * 64)
        self.assertEqual(result['identity']['runtime_sha256'], '0' * 64)

    def test_manifest_with_current_runtime_request_proof_can_be_prepared(self):
        self.artifacts['runtime_sha256'] = '0' * 64
        self.pipelines['runtime_sha256'] = '0' * 64
        self.seed['runtime_sha256'] = '0' * 64
        result = receipt.require_prepared(self.make())
        self.assertEqual(result['identity']['seed_runtime_sha256'], result['identity']['runtime_sha256'])
        self.assertEqual(result['identity']['translation_context_sha256'], 'c' * 64)
        self.assertEqual(result['identity']['chain'], self.identity['chain'])

    def test_missing_seed_runtime_request_proof_is_not_prepared(self):
        self.seed.pop('runtime_sha256')
        self.reject('seed request proof lacks a valid runtime SHA-256')

    def test_invalid_seed_runtime_request_proof_is_not_prepared(self):
        for invalid in (None, 123, 'invalid', 'f' * 63, 'f' * 65):
            with self.subTest(invalid=invalid):
                self.seed['runtime_sha256'] = invalid
                self.reject('seed request proof lacks a valid runtime SHA-256')

    def test_shared_msl_hash_counts_source_coverage_and_unique_files_separately(self):
        self.seed.update(shaders=2, listed_asked=0, listed_variants=0,
                         files={'first_b.metal': '1' * 64, 'second_b.metal': '1' * 64})
        self.libraries['sources'] = copy.deepcopy(self.seed['files'])
        self.libraries['files'] = {'1' * 64 + '.metallib': 'e' * 64}
        counts = receipt.require_prepared(self.make())['libraries']
        self.assertEqual((counts['requested'], counts['completed']), (2, 2))
        self.assertEqual((counts['unique_requested_files'], counts['unique_prepared_files']), (1, 1))
        self.assertEqual(counts['retained_library_files'], 1)
        self.assertEqual(counts['count_basis'], 'seed variant source coverage; not unique library files')

    def test_retained_library_files_do_not_inflate_requested_or_prepared_files(self):
        self.libraries['files']['9' * 64 + '.metallib'] = 'd' * 64
        counts = receipt.require_prepared(self.make())['libraries']
        self.assertEqual((counts['unique_requested_files'], counts['unique_prepared_files']), (3, 3))
        self.assertEqual(counts['retained_library_files'], 4)
        self.assertEqual(counts['files'], 4)

    def test_unique_library_counts_include_observed_sources(self):
        self.add_observed_cache()
        counts = receipt.require_prepared(self.make())['libraries']
        self.assertEqual((counts['unique_requested_files'], counts['unique_prepared_files']), (4, 4))
        self.assertEqual(counts['requested'], 3)

    def test_missing_unique_library_file_blocks_preparation(self):
        self.libraries['files'].pop('3' * 64 + '.metallib')
        result = self.reject('do not cover every unique requested source hash')
        self.assertEqual(result['libraries']['unique_requested_files'], 3)
        self.assertEqual(result['libraries']['unique_prepared_files'], 2)

    def add_observed_cache(self):
        digest = '4' * 64
        name = digest + '.metal'
        self.libraries['variant_caches'] = [dict(identity={'chain': self.identity['chain']},
                                               sources={name: digest})]
        self.libraries['sources'][name] = digest
        self.libraries['files'][digest + '.metallib'] = 'e' * 64
        return name, digest

    def test_compiler_observation_is_preserved_without_inferred_jit_equivalence(self):
        observation = self.libraries['compiler_observation']
        expected_flags = list(observation['effective_flags'])
        result = receipt.require_prepared(self.make())
        self.assertEqual(result['compiler_observation'], observation)
        observation['effective_flags'].append('changed after receipt')
        self.assertEqual(result['compiler_observation']['effective_flags'], expected_flags)

    def test_trailing_driver_overrides_return_structured_error(self):
        observation = self.libraries['compiler_observation']
        flags = list(observation['effective_flags'])
        for override in ('-fmetal-math-mode=fast', '-fno-wrapv', '-fno-preserve-invariance', '-ffast-math'):
            with self.subTest(override=override):
                observation['effective_flags'] = flags + [override]
                self.reject('compiler observation identity is invalid')

    def test_frontend_only_conflicts_return_structured_error(self):
        observation = self.libraries['compiler_observation']
        frontend = list(observation['effective_invocations'][0])
        for override in ('-fno-wrapv', '-fno-preserve-invariance', '-fstrict-overflow'):
            with self.subTest(override=override):
                observation['effective_invocations'][0] = frontend + [override]
                self.reject('compiler observation identity is invalid')

    def test_safe_frontend_defaults_remain_qualified(self):
        observation = self.libraries['compiler_observation']
        observation['effective_invocations'][0].extend(
            ['-fmetal-math-fp32-functions=fast', '-fno-rounding-math', '-ffp-contract=on'])
        self.libraries['compiler_context_sha256'] = receipt.compiler_context_key(observation)
        receipt.require_prepared(self.make())

    def test_missing_compiler_observation_cannot_be_prepared(self):
        self.libraries.pop('compiler_observation')
        self.reject('requires a qualified compiler observation')

    def test_unqualified_compiler_observation_cannot_be_prepared(self):
        self.libraries['compiler_observation']['qualified'] = False
        self.reject('requires a qualified compiler observation')

    def test_wrong_compiler_backend_cannot_be_prepared(self):
        self.libraries['compiler_observation']['backend'] = 'other'
        self.reject('compiler observation backend is not Metal')

    def test_missing_compiler_executable_digest_cannot_be_prepared(self):
        self.libraries['compiler_observation'].pop('executable_sha256')
        self.reject('lacks executable SHA-256')

    def test_missing_resource_header_digest_cannot_be_prepared(self):
        self.libraries['compiler_observation'].pop('resource_headers')
        self.reject('lacks resource header SHA-256')

    def test_wrong_target_cannot_be_prepared(self):
        self.libraries['compiler_observation']['effective_target'] = 'air64-apple-macosx28.0.0'
        self.reject('target is not macOS 26.0.0')

    def test_missing_deployment_flag_cannot_be_prepared(self):
        self.libraries['compiler_observation']['effective_flags'] = ['-fwrapv']
        self.reject('lacks the macOS 26.0 deployment flag')

    def test_missing_library_context_cannot_be_prepared(self):
        self.libraries.pop('compiler_context_sha256')
        self.reject('missing library compiler context SHA-256')

    def test_changed_compiler_observation_invalidates_context(self):
        self.libraries['compiler_observation']['version'] = 'different compiler'
        self.reject('library compiler context differs from its observation')

    def test_schema_one_compiler_context_cannot_be_prepared(self):
        self.libraries['compiler_context_schema'] = 1
        self.reject('requires compiler observation and context schema 2')

    def test_missing_loader_environment_policy_returns_structured_error(self):
        self.libraries['compiler_observation'].pop('loader_environment_policy')
        self.reject('compiler observation identity is invalid')

    def test_wrong_loader_environment_policy_returns_structured_error(self):
        self.libraries['compiler_observation']['loader_environment_policy'] = 'unqualified'
        self.reject('compiler observation identity is invalid')

    def test_schema_one_observation_cannot_be_prepared(self):
        self.libraries['compiler_observation']['observation_schema'] = 1
        self.reject('requires compiler observation and context schema 2')

    def test_legacy_launcher_only_identity_returns_structured_error(self):
        observation = self.libraries['compiler_observation']
        for field in ('tool_components', 'required_files', 'host_identity', 'effective_invocations', 'observation_schema'):
            observation.pop(field)
        self.libraries.pop('compiler_context_schema')
        result = self.reject('compiler observation identity is invalid')
        self.assertTrue(any('component or host identities' in error for error in result['errors']))

    def test_missing_frontend_identity_returns_structured_error(self):
        observation = self.libraries['compiler_observation']
        observation['tool_components'] = [item for item in observation['tool_components'] if item['role'] != 'frontend']
        self.reject('compiler observation identity is invalid')

    def test_missing_linker_identity_returns_structured_error(self):
        observation = self.libraries['compiler_observation']
        observation['tool_components'] = [item for item in observation['tool_components'] if item['role'] != 'linker']
        self.reject('compiler observation identity is invalid')

    def test_missing_local_dependency_hash_returns_structured_error(self):
        self.libraries['compiler_observation']['tool_components'][1]['dependencies'][0].pop('sha256')
        self.reject('compiler dependency lacks content identity')

    def test_missing_dependency_audit_returns_structured_error(self):
        self.libraries['compiler_observation']['tool_components'][0].pop('dependencies')
        self.reject('lacks dependency audit')

    def test_missing_static_library_hash_returns_structured_error(self):
        self.libraries['compiler_observation']['required_files'][0].pop('sha256')
        self.reject('compiler invocation input lacks content identity')

    def test_missing_required_file_inventory_returns_structured_error(self):
        self.libraries['compiler_observation'].pop('required_files')
        self.reject('compiler observation identity is invalid')

    def test_missing_system_host_binding_returns_structured_error(self):
        self.libraries['compiler_observation']['host_identity'].pop('os_build')
        self.reject('compiler observation identity is invalid')

    def test_mismatched_system_host_binding_returns_structured_error(self):
        self.libraries['compiler_observation']['tool_components'][0]['dependencies'][0]['os_build'] = 'other-build'
        self.reject('compiler dependency lacks system identity')

    def test_malformed_component_returns_structured_error(self):
        self.libraries['compiler_observation']['tool_components'] = [None]
        self.reject('compiler observation identity is invalid')

    def test_observed_specializations_are_counted_separately(self):
        self.add_observed_cache()
        result = receipt.require_prepared(self.make())
        self.assertEqual(result['observed_specializations'], dict(requested=1, completed=1, failed=0))
        self.assertEqual(result['libraries']['requested'], 3)

    def test_observed_specializations_deduplicate_repeated_caches(self):
        self.add_observed_cache()
        self.libraries['variant_caches'].append(copy.deepcopy(self.libraries['variant_caches'][0]))
        result = receipt.require_prepared(self.make())
        self.assertEqual(result['observed_specializations']['requested'], 1)

    def test_missing_observed_source_is_fatal(self):
        name, _ = self.add_observed_cache()
        self.libraries['sources'].pop(name)
        result = self.reject('do not cover every observed specialization')
        self.assertEqual(result['observed_specializations']['failed'], 1)

    def test_changed_observed_source_is_fatal(self):
        name, _ = self.add_observed_cache()
        self.libraries['sources'][name] = '5' * 64
        self.reject('do not cover every observed specialization')

    def test_missing_observed_library_is_fatal(self):
        _, digest = self.add_observed_cache()
        self.libraries['files'].pop(digest + '.metallib')
        self.reject('do not cover every observed specialization')

    def test_observed_specializations_from_v23_are_fatal(self):
        self.add_observed_cache()
        self.libraries['variant_caches'][0]['identity']['chain'] = 'oot-native-v23-txd-derivative-order'
        self.reject('observed specialization cache belongs to another shader chain')

    def test_invalid_observed_hash_filename_is_fatal(self):
        name, digest = self.add_observed_cache()
        self.libraries['variant_caches'][0]['sources'] = {'wrong.metal': digest}
        self.libraries['sources']['wrong.metal'] = digest
        self.reject('invalid observed specialization source identity')

    def test_conflicting_observed_source_is_fatal(self):
        name, _ = self.add_observed_cache()
        self.libraries['variant_caches'].append(dict(identity={'chain': self.identity['chain']},
                                                   sources={name: '5' * 64}))
        self.reject('conflicting observed specialization source')

    def test_unresolved_required_inputs_block_preparation(self):
        result = self.make(unresolved_inputs=['unresolved binding metadata'])
        self.assertEqual(result['unresolved_inputs'], ['unresolved binding metadata'])
        with self.assertRaisesRegex(ValueError, 'required preparation inputs remain unresolved'):
            receipt.require_prepared(result)

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
