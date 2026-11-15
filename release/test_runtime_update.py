"""Small offline safety checks; fixtures are not gameplay or distribution evidence."""
import base64
import contextlib
import io
import hashlib
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SPEC = importlib.util.spec_from_file_location('runtime_update_under_test', Path(__file__).with_name('runtime_update.py'))
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.record = dict(schema='kokiri-runtime-source-v1', product=runtime.PRODUCT, version=2,
                           game_update='131072', build_api=1, source_commit='a' * 40,
                           shader_chain='oot-native-v28-test-fixture', archive_sha256='b' * 64,
                           archive_bytes=1, archive_url='https://updates.example.org/source.zip')

    def manifest(self, record=None, folder=None):
        folder = folder or self.root
        manifest, signature = folder / 'manifest.json', folder / 'manifest.sig'
        manifest.write_text(json.dumps(record or self.record, sort_keys=True))
        signature.write_bytes(base64.b64encode(self.key.sign(manifest.read_bytes())))
        return manifest, signature

    def archive(self, extra=(), omit=()):
        path = self.root / 'source.zip'
        files = {
            'engine/build.py': 'print("fixture")\n',
            'engine/scripts/preparation_receipt.py': '# fixture validator\n',
            'engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h':
                '#define DMSH_CHAIN "oot-native-v28-test-fixture" /* game: oot */\n',
            'LICENSE': 'MIT test fixture\n',
            'THIRD_PARTY_NOTICES.md': 'Fixture attribution\n',
        }
        with warnings.catch_warnings(), zipfile.ZipFile(path, 'w') as output:
            warnings.filterwarnings('ignore', message="Duplicate name: 'LICENSE'", category=UserWarning)
            for name, content in files.items():
                if name not in omit:
                    entry = zipfile.ZipInfo(name)
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | 0o644) << 16
                    output.writestr(entry, content)
            for name, mode, content in extra:
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = mode << 16
                output.writestr(entry, content)
        self.record.update(archive_sha256=runtime.sha(path), archive_bytes=path.stat().st_size)
        return path

    def compiler_observation(self):
        # Synthetic provenance; only the shared pure validator runs in these tests.
        return dict(
            observation_schema=2, qualified=True, backend='metal', version='offline compiler fixture',
            loader_environment_policy='reject-nonempty-DYLD',
            executable_sha256='8' * 64,
            effective_flags=['-mmacosx-version-min=26.0', '-fmetal-math-mode=safe',
                             '-fpreserve-invariance', '-fwrapv'],
            effective_target='air64-apple-macosx26.0.0', sdk_mode='compiler-default-resource-headers',
            resource_headers=dict(content_sha256='7' * 64),
            host_identity=dict(os_build='offline-build', machine='arm64', kernel_release='offline-kernel'),
            tool_components=[
                dict(role='driver', path='/private/fixture/metal', size=100, executable_sha256='8' * 64,
                     dependencies=[dict(loader_sha256='8' * 64, install_name='/usr/lib/libSystem.B.dylib',
                                        binding='os-build-system-component', os_build='offline-build')]),
                dict(role='frontend', path='/private/fixture/frontend', size=200, executable_sha256='6' * 64,
                     dependencies=[dict(loader_sha256='6' * 64, install_name='@rpath/libCompiler.dylib',
                                        binding='hashed-file', sha256='5' * 64,
                                        path='/private/fixture/libCompiler.dylib', size=50)]),
                dict(role='linker', path='/private/fixture/linker', size=300, executable_sha256='4' * 64,
                     dependencies=[])],
            required_files=[dict(role='selected-invocation-input', sha256='3' * 64,
                                 path='/private/fixture/libmetal_rt_osx.a', size=123)],
            effective_invocations=[
                ['/private/fixture/frontend', '-cc1', '-triple', 'air64-apple-macosx26.0.0',
                 '-o', '<intermediate.air>', '<probe-dir>/identity.metal'],
                ['/private/fixture/linker', '<intermediate.air>', '/private/fixture/libmetal_rt_osx.a',
                 '-o', '<probe-dir>/identity.partial']])

    def compiler_key(self, observation):
        spec = importlib.util.spec_from_file_location('trusted_compiler_fixture', runtime.TRUSTED_COMPILER_HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper.compiler_context_key(observation)

    def app(self, folder=None):
        app = (folder or self.root) / 'Kokiri Game.app'
        executable = app / 'Contents/MacOS/KokiriGame'
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b'#!/bin/sh\nexit 0\n')
        executable.chmod(0o700)
        resources = app / 'Contents/_CodeSignature/CodeResources'
        resources.parent.mkdir()
        resources.write_bytes(b'fixture signature resources')
        build_input_hash = hashlib.sha256(b'offline pre-seal executable fixture').hexdigest()
        receipt = dict(schema='kokiri-preparation-receipt-v1', mode='full', prepared=True, errors=[],
                       identity=dict(source_commit=self.record['source_commit'], chain=self.record['shader_chain'],
                                     runtime_sha256=build_input_hash, runtime_hash_scope=runtime.BUILD_HASH_SCOPE,
                                     translation_context_sha256='c' * 64,
                                     translator_sha256='d' * 64, gpu_architecture='apple-gpu-fixture'),
                       variants=dict(default=dict(requested=2, completed=2, failed=0),
                                     listed=dict(requested=0, completed=0, failed=0), unique_completed=2),
                       artifact_sha256=dict(runtime_sha256=build_input_hash),
                       libraries=dict(requested=2, completed=2, failed=0),
                       pipelines=dict(requested=2, completed=2, failed=0, write_failed=0, unaccounted=0))
        observation = self.compiler_observation()
        receipt.update(compiler_observation=observation, compiler_context_schema=2,
                       compiler_context_sha256=self.compiler_key(observation))
        info = dict(CFBundleIdentifier=runtime.PRODUCT, CFBundleExecutable='KokiriGame', KokiriGameUpdate='131072',
                    KokiriPrepared=True, KokiriShaders='full', KokiriSourceCommit=self.record['source_commit'],
                    KokiriBuildRuntimeSHA256=build_input_hash)
        build = app / 'Contents/Resources/totk/build'
        artifact_paths = {
            'seed_manifest_sha256': build / 'shader-seed/seed-manifest.json',
            'libraries_manifest_sha256': build / 'shader-libs/libraries-manifest.json',
            'pipeline_manifest_sha256': build / 'pipelines/compute-manifest.json',
        }
        for name, path in artifact_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = path.parent / 'fixture-payload.dat'
            payload.write_bytes(('offline fixture ' + name).encode())
            manifest = dict(files={payload.name: runtime.sha(payload)})
            if name == 'libraries_manifest_sha256':
                manifest.update(compiler_observation=deepcopy(observation), compiler_context_schema=2,
                                compiler_context_sha256=receipt['compiler_context_sha256'])
            path.write_text(json.dumps(manifest))
            receipt['artifact_sha256'][name] = runtime.sha(path)
        index = build / 'pipelines/pipelines-apple-gpu-fixture.tsv'
        index.write_text('offline fixture pipeline index\n')
        receipt['artifact_sha256']['pipeline_index_sha256'] = runtime.sha(index)
        self.write_receipt(app, receipt, info)
        return app, receipt, info

    def write_receipt(self, app, receipt, info):
        path = app / runtime.RECEIPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt))
        info['KokiriPreparationReceiptSHA256'] = runtime.sha(path)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))

    def write_library_manifest(self, app, receipt, info, manifest):
        path = app / 'Contents/Resources/totk/build/shader-libs/libraries-manifest.json'
        path.write_text(json.dumps(manifest))
        receipt['artifact_sha256']['libraries_manifest_sha256'] = runtime.sha(path)
        self.write_receipt(app, receipt, info)

    def library_manifest(self, app):
        return runtime.read_json(app / 'Contents/Resources/totk/build/shader-libs/libraries-manifest.json')

    def test_schema2_compiler_receipt_and_library_context_are_qualified(self):
        app, receipt, info = self.app()
        self.assertEqual(receipt['compiler_context_sha256'], self.compiler_key(receipt['compiler_observation']))
        with patch.object(runtime.subprocess, 'run'):
            self.assertEqual(runtime.inspect_app(app, self.record)['version'], 2)

    def test_trusted_validator_missing_linked_or_unsupported_fails_closed(self):
        missing = self.root / 'missing-trusted-helper.py'
        linked = self.root / 'linked-trusted-helper.py'
        linked.symlink_to(runtime.TRUSTED_COMPILER_HELPER)
        unsupported = self.root / 'unsupported-trusted-helper.py'
        unsupported.write_text('compiler_context_key = None\n')
        downloaded = self.root / 'version-2/source/engine/scripts/metal_toolchain.py'
        downloaded.parent.mkdir(parents=True)
        downloaded.write_text('raise AssertionError("Downloaded helper must never be imported")\n')
        for helper in (missing, linked, unsupported):
            with self.subTest(helper=helper.name):
                with patch.object(runtime, 'TRUSTED_COMPILER_HELPER', helper):
                    with self.assertRaisesRegex(ValueError, 'Trusted compiler validator'):
                        runtime.load_trusted_compiler_validator()

    def test_stage_missing_trusted_validator_refuses_before_work_or_trust_mutation(self):
        store, work, app = self.root / 'store', self.root / 'original-work', self.root / 'Original.app'
        for folder in (store, work, app):
            folder.mkdir(mode=0o700)
        manifest, signature = self.manifest()
        archive = self.root / 'unneeded-source.zip'
        archive.write_bytes(b'not an archive; trusted-helper admission must fail first')
        with patch.object(runtime, 'TRUSTED_COMPILER_HELPER', self.root / 'missing-trusted-helper.py'), \
                patch.object(runtime, 'verify_manifest', wraps=runtime.verify_manifest) as verified, \
                patch.object(runtime, 'inspect_app') as inspected, \
                patch.object(runtime, 'clone_work') as cloned, \
                patch.object(runtime, 'build_candidate') as built, \
                patch.object(runtime, 'extract_source') as extracted, \
                patch.object(runtime, 'game_closed') as observed, \
                patch.object(runtime, 'pin_key') as trusted, \
                patch.object(runtime.subprocess, 'run') as native:
            with self.assertRaisesRegex(ValueError, 'Trusted compiler validator unavailable'):
                runtime.stage(store, manifest, signature, self.public, archive, app, work,
                              self.root / 'unneeded-python')
        verified.assert_called_once_with(manifest, signature, self.public, 0)
        for action in (inspected, cloned, built, extracted, observed, trusted, native):
            action.assert_not_called()
        self.assertEqual(list(store.iterdir()), [])
        self.assertEqual(list(work.iterdir()), [])
        self.assertEqual(list(app.iterdir()), [])

    def test_candidate_rejects_old_missing_or_boolean_context_schema_despite_resealed_receipt(self):
        app, original, original_info = self.app()
        original_manifest = self.library_manifest(app)
        for location, value in (('receipt', 1), ('receipt', None), ('receipt', True),
                                ('manifest', 1), ('manifest', None), ('manifest', True)):
            with self.subTest(location=location, schema=value):
                receipt, info, manifest = deepcopy(original), deepcopy(original_info), deepcopy(original_manifest)
                target = receipt if location == 'receipt' else manifest
                if value is None:
                    target.pop('compiler_context_schema')
                else:
                    target['compiler_context_schema'] = value
                self.write_library_manifest(app, receipt, info, manifest)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def test_candidate_rejects_missing_unqualified_or_old_compiler_observations(self):
        app, original, original_info = self.app()
        original_manifest = self.library_manifest(app)
        for field, value in (('observation_schema', 1), ('observation_schema', True),
                             ('qualified', False), ('qualified', 1), ('qualified', None), ('missing', None)):
            with self.subTest(field=field, value=value):
                receipt, info, manifest = deepcopy(original), deepcopy(original_info), deepcopy(original_manifest)
                for target in (receipt, manifest):
                    if field == 'missing':
                        target.pop('compiler_observation')
                    else:
                        target['compiler_observation'][field] = value
                self.write_library_manifest(app, receipt, info, manifest)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def test_candidate_rejects_malformed_compiler_components_after_receipt_rehash(self):
        app, original, original_info = self.app()
        original_manifest = self.library_manifest(app)
        for mutation in ('relative_path', 'missing_frontend_hash', 'missing_invocation_input', 'unknown_loader'):
            with self.subTest(mutation=mutation):
                receipt, info, manifest = deepcopy(original), deepcopy(original_info), deepcopy(original_manifest)
                observation = receipt['compiler_observation']
                if mutation == 'relative_path':
                    observation['tool_components'][0]['path'] = 'relative-metal'
                elif mutation == 'missing_frontend_hash':
                    observation['tool_components'][1].pop('executable_sha256')
                elif mutation == 'missing_invocation_input':
                    observation['required_files'] = []
                else:
                    observation['tool_components'][0]['dependencies'][0]['loader_sha256'] = '0' * 64
                manifest['compiler_observation'] = deepcopy(observation)
                self.write_library_manifest(app, receipt, info, manifest)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def test_candidate_rejects_receipt_and_library_observation_mismatch(self):
        app, receipt, info = self.app()
        manifest = self.library_manifest(app)
        manifest['compiler_observation']['version'] = 'different qualified compiler fixture'
        manifest['compiler_context_sha256'] = self.compiler_key(manifest['compiler_observation'])
        self.write_library_manifest(app, receipt, info, manifest)
        with patch.object(runtime.subprocess, 'run'):
            with self.assertRaises(ValueError):
                runtime.inspect_app(app, self.record)

    def test_candidate_requires_loader_environment_admission_policy(self):
        app, original, original_info = self.app()
        original_manifest = self.library_manifest(app)
        for policy in (None, 'allow-DYLD-overrides'):
            with self.subTest(policy=policy):
                receipt, info, manifest = deepcopy(original), deepcopy(original_info), deepcopy(original_manifest)
                observation = receipt['compiler_observation']
                if policy is None:
                    observation.pop('loader_environment_policy')
                else:
                    observation['loader_environment_policy'] = policy
                manifest['compiler_observation'] = deepcopy(observation)
                self.write_library_manifest(app, receipt, info, manifest)
                # Even matching, rehashed receipt/manifest bytes must fail the
                # shared validator when loader admission was not established.
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaisesRegex(ValueError, 'loader-environment policy'):
                        runtime.inspect_app(app, self.record)

    def test_candidate_requires_current_target_and_each_correctness_flag(self):
        app, original, original_info = self.app()
        original_manifest = self.library_manifest(app)
        for missing in ('-mmacosx-version-min=26.0', '-fpreserve-invariance', '-fwrapv', 'target'):
            with self.subTest(missing=missing):
                receipt, info, manifest = deepcopy(original), deepcopy(original_info), deepcopy(original_manifest)
                observation = receipt['compiler_observation']
                if missing == 'target':
                    observation['effective_target'] = 'air64-apple-macosx27.0.0'
                    observation['effective_invocations'][0][3] = observation['effective_target']
                else:
                    observation['effective_flags'].remove(missing)
                # A self-consistent digest cannot make an unsupported target or
                # reduced correctness options eligible for a new runtime update.
                receipt['compiler_context_sha256'] = self.compiler_key(observation)
                manifest['compiler_observation'] = deepcopy(observation)
                manifest['compiler_context_sha256'] = receipt['compiler_context_sha256']
                self.write_library_manifest(app, receipt, info, manifest)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def test_candidate_rejects_forged_context_digest_with_matching_observations(self):
        app, receipt, info = self.app()
        manifest = self.library_manifest(app)
        receipt['compiler_context_sha256'] = '0' * 64
        manifest['compiler_context_sha256'] = '0' * 64
        self.write_library_manifest(app, receipt, info, manifest)
        with patch.object(runtime.subprocess, 'run'):
            with self.assertRaises(ValueError):
                runtime.inspect_app(app, self.record)

    def test_historical_schema1_rollback_baseline_remains_recoverable_when_unchanged(self):
        app, receipt, info = self.app()
        manifest = self.library_manifest(app)
        for target in (receipt, manifest):
            target['compiler_context_schema'] = 1
            target['compiler_observation']['observation_schema'] = 1
        self.write_library_manifest(app, receipt, info, manifest)
        with patch.object(runtime.subprocess, 'run'), patch.object(runtime, 'game_closed'):
            historical = runtime.inspect_app(app)
            historical.update(preparation_receipt_sha256=runtime.sha(app / runtime.RECEIPT),
                              preparation_artifact_sha256=runtime.verify_preparation_artifacts(app, receipt))
            runtime.unchanged(historical)
            store = self.root / 'historical-store'
            store.mkdir(mode=0o700)
            runtime.atomic_json(store / 'state.json',
                                dict(schema=1, highest_version=2, active=None, previous=historical))
            restored = runtime.rollback(store)
            self.assertEqual(restored['active'], historical)
            self.assertEqual(restored['highest_version'], 2)
            with self.assertRaises(ValueError):
                runtime.inspect_app(app, self.record)

    def test_manifest_verifies_exact_bytes_and_monotonic_version(self):
        manifest, signature = self.manifest()
        self.assertEqual(runtime.verify_manifest(manifest, signature, self.public, highest=1), self.record)
        with self.assertRaises(ValueError):
            runtime.verify_manifest(manifest, signature, self.public, highest=2)
        manifest.write_bytes(manifest.read_bytes() + b' ')
        with self.assertRaises(InvalidSignature):
            runtime.verify_manifest(manifest, signature, self.public)

    def test_wrong_key_and_signature_are_rejected(self):
        manifest, signature = self.manifest()
        wrong = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        with self.assertRaises(InvalidSignature):
            runtime.verify_manifest(manifest, signature, base64.b64encode(wrong).decode())
        signature.write_bytes(base64.b64encode(b'\0' * 64))
        with self.assertRaises(InvalidSignature):
            runtime.verify_manifest(manifest, signature, self.public)

    def test_manifest_rejects_invalid_identity_and_urls_even_when_signed(self):
        for field, value in [('version', True), ('source_commit', 'main'), ('archive_sha256', 'invalid'),
                             ('archive_url', 'http://updates.example.org/source.zip'),
                             ('archive_url', 'https://user:password@example.org/source.zip'),
                             ('game_update', 'wrong')]:
            with self.subTest(field=field, value=value):
                record = {**self.record, field: value}
                manifest, signature = self.manifest(record)
                with self.assertRaises(ValueError):
                    runtime.verify_manifest(manifest, signature, self.public)

    def test_duplicate_json_keys_are_rejected(self):
        manifest, signature = self.manifest()
        manifest.write_text('{"version":1,"version":2}')
        signature.write_bytes(base64.b64encode(self.key.sign(manifest.read_bytes())))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            runtime.verify_manifest(manifest, signature, self.public)

    def test_archive_requires_matching_signed_bytes_and_attribution(self):
        archive = self.archive()
        destination = self.root / 'source'
        runtime.extract_source(archive, destination, self.record)
        self.assertEqual((destination / 'LICENSE').read_text(), 'MIT test fixture\n')
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            runtime.extract_source(archive, self.root / 'changed', self.record)
        archive = self.archive(omit=('LICENSE',))
        with self.assertRaisesRegex(ValueError, 'attribution'):
            runtime.extract_source(archive, self.root / 'uncredited', self.record)
        self.assertFalse((self.root / 'uncredited').exists())

    def test_archive_rejects_traversal_links_private_data_and_unsafe_modes(self):
        entries = [('../escape.txt', stat.S_IFREG | 0o644, 'escape'),
                   ('/absolute.txt', stat.S_IFREG | 0o644, 'escape'),
                   ('nested\\escape.txt', stat.S_IFREG | 0o644, 'escape'),
                   ('link', stat.S_IFLNK | 0o777, '../escape'),
                   ('world-writable.py', stat.S_IFREG | 0o666, '# unsafe'),
                   ('user.sav', stat.S_IFREG | 0o644, 'private save'),
                   ('shader.metallib', stat.S_IFREG | 0o644, 'private shader')]
        for index, entry in enumerate(entries):
            with self.subTest(member=entry[0]):
                archive = self.archive(extra=(entry,))
                destination = self.root / ('rejected-' + str(index))
                with self.assertRaises(ValueError):
                    runtime.extract_source(archive, destination, self.record)
                self.assertFalse(destination.exists())

    def test_signed_resource_hash_allows_updated_recognized_metadata(self):
        name, content = 'engine/assets/shader_list.tsv', b'offline updated metadata fixture\n'
        archive = self.archive(extra=((name, stat.S_IFREG | 0o644, content),))
        self.record['public_resource_sha256'] = {name: hashlib.sha256(content).hexdigest()}
        manifest, signature = self.manifest()
        verified = runtime.verify_manifest(manifest, signature, self.public)
        destination = self.root / 'updated-metadata'
        runtime.extract_source(archive, destination, verified)
        self.assertEqual((destination / name).read_bytes(), content)

    def test_updated_metadata_requires_exact_signed_resource_declaration(self):
        name, content = 'engine/assets/shader_list.tsv', b'offline updated metadata fixture\n'
        archive = self.archive(extra=((name, stat.S_IFREG | 0o644, content),))
        for index, declaration in enumerate(({}, {name: '0' * 64})):
            with self.subTest(declaration=declaration):
                record = {**self.record, 'public_resource_sha256': declaration}
                manifest, signature = self.manifest(record)
                verified = runtime.verify_manifest(manifest, signature, self.public)
                destination = self.root / ('unreviewed-metadata-' + str(index))
                with self.assertRaisesRegex(ValueError, 'publication policy'):
                    runtime.extract_source(archive, destination, verified)
                self.assertFalse(destination.exists())

    def test_signed_resource_map_cannot_exempt_private_or_unknown_payloads(self):
        for index, name in enumerate(('private-game.bin', 'unreviewed-artwork.png')):
            with self.subTest(name=name):
                content = b'offline disallowed payload fixture'
                archive = self.archive(extra=((name, stat.S_IFREG | 0o644, content),))
                record = {**self.record, 'public_resource_sha256': {name: hashlib.sha256(content).hexdigest()}}
                manifest, signature = self.manifest(record)
                verified = runtime.verify_manifest(manifest, signature, self.public)
                destination = self.root / ('rejected-exemption-' + str(index))
                with self.assertRaisesRegex(ValueError, 'publication policy'):
                    runtime.extract_source(archive, destination, verified)
                self.assertFalse(destination.exists())

    def test_manifest_rejects_invalid_reviewed_resource_hash_maps(self):
        for resources in ([], {'engine/assets/shader_list.tsv': 'invalid-digest'},
                          {'engine/assets/shader_list.tsv': 'g' * 64}):
            with self.subTest(resources=resources):
                manifest, signature = self.manifest({**self.record, 'public_resource_sha256': resources})
                with self.assertRaisesRegex(ValueError, 'source-resource hashes'):
                    runtime.verify_manifest(manifest, signature, self.public)

    def test_archive_rejects_duplicate_members(self):
        archive = self.archive(extra=(('LICENSE', stat.S_IFREG | 0o644, 'duplicate'),))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            runtime.extract_source(archive, self.root / 'duplicates', self.record)

    def test_receipt_binds_executable_source_and_shader_chain(self):
        app, receipt, info = self.app()
        with patch.object(runtime.subprocess, 'run') as signed:
            result = runtime.inspect_app(app, self.record)
            signed.assert_called_once()
            self.assertEqual(result['version'], 2)
            self.assertEqual(result['build_runtime_sha256'], receipt['identity']['runtime_sha256'])
            self.assertNotEqual(result['executable_sha256'], result['build_runtime_sha256'])
            for field in ('source_commit', 'chain', 'runtime_sha256'):
                with self.subTest(identity=field):
                    altered = deepcopy(receipt)
                    altered['identity'][field] = 'different'
                    self.write_receipt(app, altered, info)
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def test_preseal_hash_scope_and_info_binding_are_required(self):
        app, receipt, info = self.app()
        for field in ('identity_hash', 'artifact_hash', 'info_hash', 'hash_scope'):
            with self.subTest(binding=field):
                altered, altered_info = deepcopy(receipt), deepcopy(info)
                if field == 'identity_hash':
                    altered['identity']['runtime_sha256'] = 'f' * 64
                elif field == 'artifact_hash':
                    altered['artifact_sha256']['runtime_sha256'] = 'f' * 64
                elif field == 'info_hash':
                    altered_info['KokiriBuildRuntimeSHA256'] = 'f' * 64
                else:
                    altered['identity']['runtime_hash_scope'] = 'ambiguous executable bytes'
                self.write_receipt(app, altered, altered_info)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaisesRegex(ValueError, 'identity differs'):
                        runtime.inspect_app(app, self.record)

    def package_output(self, candidate):
        return dict(schema='kokiri-package-output-v1', app=candidate['app'],
                    build_runtime_sha256=candidate['build_runtime_sha256'],
                    signed_runtime_sha256=candidate['executable_sha256'], info_sha256=candidate['info_sha256'],
                    code_resources_sha256=candidate['code_resources_sha256'],
                    preparation_receipt_sha256=candidate['preparation_receipt_sha256'])

    def test_external_package_output_binds_input_and_final_signed_bytes(self):
        app, receipt, info = self.app()
        with patch.object(runtime.subprocess, 'run'):
            candidate = runtime.inspect_app(app, self.record)
        work = self.root / 'work'
        output = work / 'logs/package-output.json'
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps(self.package_output(candidate)))
        self.assertEqual(runtime.verify_package_output(work, candidate), runtime.sha(output))
        self.assertNotEqual(candidate['build_runtime_sha256'], candidate['executable_sha256'])

    def test_external_package_output_rejects_changed_or_missing_identity(self):
        app, receipt, info = self.app()
        with patch.object(runtime.subprocess, 'run'):
            candidate = runtime.inspect_app(app, self.record)
        work = self.root / 'work'
        output = work / 'logs/package-output.json'
        output.parent.mkdir(parents=True)
        expected = self.package_output(candidate)
        for field in expected:
            with self.subTest(changed_field=field):
                changed = {**expected, field: 'changed fixture identity'}
                output.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'package fingerprint differs'):
                    runtime.verify_package_output(work, candidate)
        for mutation in ({key: value for key, value in expected.items() if key != 'signed_runtime_sha256'},
                         {**expected, 'unrecognized_field': 'ambiguous contract'}):
            output.write_text(json.dumps(mutation))
            with self.assertRaises(ValueError):
                runtime.verify_package_output(work, candidate)

    def test_receipt_rejects_none_partial_failed_and_unbound_preparation(self):
        app, receipt, info = self.app()
        variants = []
        for field, value in [('prepared', False), ('mode', 'none'), ('errors', ['failed'])]:
            variants.append({**receipt, field: value})
        for section, field, value in [('libraries', 'completed', 1), ('pipelines', 'failed', 1),
                                      ('pipelines', 'unaccounted', 1), ('pipelines', 'write_failed', 1)]:
            altered = deepcopy(receipt)
            altered[section][field] = value
            variants.append(altered)
        with patch.object(runtime.subprocess, 'run'):
            for index, altered in enumerate(variants):
                with self.subTest(variant=index):
                    self.write_receipt(app, altered, info)
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)
            self.write_receipt(app, receipt, info)
            path = app / runtime.RECEIPT
            path.write_text(path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'bind'):
                runtime.inspect_app(app, self.record)

    def test_prepared_payload_tampering_is_rejected_with_codesign_mocked(self):
        app, receipt, info = self.app()
        payload = app / 'Contents/Resources/totk/build/shader-libs/fixture-payload.dat'
        payload.write_bytes(b'changed shader library fixture')
        with patch.object(runtime.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'payload differs'):
                runtime.inspect_app(app, self.record)

    def test_prepared_payload_cannot_escape_the_app(self):
        app, receipt, info = self.app()
        payload = app / 'Contents/Resources/totk/build/shader-libs/fixture-payload.dat'
        external = self.root / 'outside-payload.dat'
        external.write_bytes(payload.read_bytes())
        payload.unlink()
        payload.symlink_to(external)
        with patch.object(runtime.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'payload differs'):
                runtime.inspect_app(app, self.record)

    def test_retained_prepared_identity_rehashes_shader_payloads(self):
        app, receipt, info = self.app()
        with patch.object(runtime.subprocess, 'run'):
            identity = runtime.inspect_app(app, self.record)
            runtime.unchanged(identity)
            payload = app / 'Contents/Resources/totk/build/shader-seed/fixture-payload.dat'
            payload.write_bytes(b'changed retained seed fixture')
            with self.assertRaisesRegex(ValueError, 'payload differs'):
                runtime.unchanged(identity)

    def test_invalid_gpu_archive_identity_is_rejected(self):
        app, receipt, info = self.app()
        receipt['identity']['gpu_architecture'] = '../outside'
        self.write_receipt(app, receipt, info)
        with patch.object(runtime.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'GPU archive identity'):
                runtime.inspect_app(app, self.record)

    def test_boolean_compilation_counts_are_not_integers(self):
        app, receipt, info = self.app()
        for section, field in [('libraries', 'completed'), ('libraries', 'failed'),
                               ('pipelines', 'write_failed'), ('pipelines', 'unaccounted')]:
            with self.subTest(section=section, field=field):
                altered = deepcopy(receipt)
                if field == 'completed':
                    altered[section]['requested'] = 1
                    altered[section][field] = True
                else:
                    altered[section][field] = False
                self.write_receipt(app, altered, info)
                with patch.object(runtime.subprocess, 'run'):
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

    def staged(self):
        store = self.root / 'store'
        store.mkdir(mode=0o700)
        folder = store / 'version-2'
        folder.mkdir(mode=0o700)
        self.manifest(folder=folder)
        app, _, _ = self.app(folder)
        with patch.object(runtime.subprocess, 'run'):
            candidate = runtime.inspect_app(app, self.record)
        baseline = dict(app=str(self.root / 'Baseline.app'), executable_sha256='4' * 64,
                        info_sha256='5' * 64, code_resources_sha256='7' * 64)
        runtime.atomic_json(folder / 'transaction.json', dict(phase='prepared', version=2,
                                                            candidate=candidate, baseline=baseline))
        return store, candidate, baseline

    def inspector(self, candidate, baseline):
        def inspect(path, record=None):
            actual = candidate if str(path) == candidate['app'] else baseline
            return dict(actual) if record else {key: actual[key] for key in ('app', 'executable_sha256', 'info_sha256', 'code_resources_sha256')}
        return inspect

    def test_atomic_activation_and_rollback_retain_monotonic_version(self):
        store, candidate, baseline = self.staged()
        with patch.object(runtime, 'inspect_app', side_effect=self.inspector(candidate, baseline)), \
                patch.object(runtime, 'game_closed'):
            activated = runtime.activate(store, 2, self.public)
            self.assertEqual(activated['active'], candidate)
            self.assertFalse(activated['game_launched'])
            rolled = runtime.rollback(store)
            self.assertEqual(rolled['active'], baseline)
            self.assertEqual(rolled['previous'], candidate)
            self.assertEqual(rolled['highest_version'], 2)
            self.assertEqual(runtime.state(store)['active'], baseline)
            with self.assertRaisesRegex(ValueError, 'increase'):
                runtime.activate(store, 2, self.public)
        self.assertFalse(list(store.glob('.state.json*')))

    def test_activation_refuses_mutated_candidate_or_retained_baseline(self):
        store, candidate, baseline = self.staged()
        for target in ('candidate', 'baseline'):
            with self.subTest(target=target):
                changed_candidate, changed_baseline = deepcopy(candidate), deepcopy(baseline)
                (changed_candidate if target == 'candidate' else changed_baseline)['executable_sha256'] = '0' * 64
                with patch.object(runtime, 'inspect_app', side_effect=self.inspector(changed_candidate, changed_baseline)), \
                        patch.object(runtime, 'game_closed'):
                    with self.assertRaises(ValueError):
                        runtime.activate(store, 2, self.public)
                self.assertFalse((store / 'state.json').exists())

    def test_rollback_refuses_changed_retained_signature_resources(self):
        store, candidate, baseline = self.staged()
        runtime.atomic_json(store / 'state.json', dict(schema=1, highest_version=2, active=candidate, previous=baseline))
        changed = {**baseline, 'code_resources_sha256': '0' * 64}
        with patch.object(runtime, 'inspect_app', side_effect=self.inspector(candidate, changed)), \
                patch.object(runtime, 'game_closed'):
            with self.assertRaisesRegex(ValueError, 'Retained app changed'):
                runtime.rollback(store)
        self.assertEqual(runtime.state(store)['active'], candidate)

    def test_changed_active_selection_prevents_stale_activation(self):
        store, candidate, baseline = self.staged()
        other = {**baseline, 'app': str(self.root / 'Other.app')}
        original = dict(schema=1, highest_version=1, active=other, previous=None)
        runtime.atomic_json(store / 'state.json', original)
        with patch.object(runtime, 'inspect_app', side_effect=self.inspector(candidate, baseline)), \
                patch.object(runtime, 'game_closed'):
            with self.assertRaisesRegex(ValueError, 'Active app changed'):
                runtime.activate(store, 2, self.public)
        self.assertEqual(runtime.state(store), original)

    def test_relaunch_requests_open_without_claiming_observed_gameplay(self):
        store, candidate, baseline = self.staged()
        with patch.object(runtime, 'inspect_app', side_effect=self.inspector(candidate, baseline)), \
                patch.object(runtime, 'game_closed'), patch.object(runtime.subprocess, 'run') as launched:
            result = runtime.relaunch(candidate)
        launched.assert_called_once_with(['/usr/bin/open', '-n', candidate['app']], check=True)
        self.assertEqual(result['game_launched'], 'unverified')

    def test_running_game_prevents_activation_and_relaunch(self):
        store, candidate, baseline = self.staged()
        with patch.object(runtime, 'inspect_app', side_effect=self.inspector(candidate, baseline)), \
                patch.object(runtime, 'game_closed', side_effect=ValueError('Human game is active')), \
                patch.object(runtime.subprocess, 'run') as launched:
            with self.assertRaises(ValueError):
                runtime.activate(store, 2, self.public)
            with self.assertRaises(ValueError):
                runtime.relaunch(candidate)
            launched.assert_not_called()
        self.assertFalse((store / 'state.json').exists())

    def test_interrupted_state_write_leaves_old_selection_and_no_temporary(self):
        store = self.root / 'store'
        store.mkdir()
        original = dict(schema=1, highest_version=1, active=None, previous=None)
        runtime.atomic_json(store / 'state.json', original)
        with patch.object(runtime.os, 'replace', side_effect=OSError('simulated interruption')):
            with self.assertRaises(OSError):
                runtime.atomic_json(store / 'state.json', {**original, 'highest_version': 2})
        self.assertEqual(runtime.state(store), original)
        self.assertFalse(list(store.glob('.state.json*')))

    def test_store_refuses_competing_lock_unsafe_permissions_and_symlink(self):
        store = self.root / 'store'
        with runtime.store_lock(store):
            with self.assertRaises(BlockingIOError):
                with runtime.store_lock(store):
                    self.fail('Competing store lock was accepted')
        store.chmod(0o755)
        with self.assertRaises(ValueError):
            with runtime.store_lock(store):
                self.fail('Public store directory was accepted')
        store.chmod(0o700)
        linked = self.root / 'linked'
        linked.symlink_to(store, target_is_directory=True)
        with self.assertRaises(ValueError):
            with runtime.store_lock(linked):
                self.fail('Linked store directory was accepted')

    def test_builder_group_exemption_does_not_hide_unrelated_gameplay(self):
        owned = '123 123 /private/build/oot-native\n'
        with patch.object(runtime.subprocess, 'check_output', return_value=owned):
            runtime.game_closed(owned_process_group=123)
            with self.assertRaises(ValueError):
                runtime.game_closed()
        human = '456 456 /Applications/Ocarina.app/Contents/MacOS/OcarinaOfTime\n'
        with patch.object(runtime.subprocess, 'check_output', return_value=owned + human):
            with self.assertRaisesRegex(ValueError, 'Close the game normally'):
                runtime.game_closed(owned_process_group=123)
        with patch.object(runtime.subprocess, 'check_output', return_value='789 789 /other/oot-native\n'):
            with self.assertRaises(ValueError):
                runtime.game_closed(owned_process_group=123)

    def test_unrecognized_process_snapshot_blocks_updates(self):
        with patch.object(runtime.subprocess, 'check_output', return_value='unexpected snapshot\n'):
            with self.assertRaisesRegex(ValueError, 'Unrecognized process snapshot'):
                runtime.game_closed()

    def test_store_location_refusal_makes_no_source_or_work_writes(self):
        trusted, original = self.root / 'trusted', self.root / 'original-work'
        trusted.mkdir()
        original.mkdir()
        with patch.object(runtime, 'ROOT', trusted):
            for path in (trusted, trusted / 'private-runtime-store'):
                with self.subTest(source_store=path):
                    with self.assertRaises(ValueError):
                        with runtime.store_lock(path):
                            self.fail('Source-nested store was accepted')
                    self.assertFalse((path / '.lock').exists())
            nested = original / 'private-runtime-store'
            with self.assertRaises(ValueError):
                runtime.validate_store_location(nested, original)
            self.assertFalse(nested.exists())
        self.assertEqual(list(trusted.iterdir()), [])
        self.assertEqual(list(original.iterdir()), [])

    def test_store_location_refuses_original_app_without_any_writes(self):
        app = self.root / 'Original Game.app'
        app.mkdir()
        for path in (app, app / 'private-runtime-store'):
            with self.subTest(store=path):
                with self.assertRaisesRegex(ValueError, 'outside the original app'):
                    runtime.validate_store_location(path, current_app=app)
                self.assertFalse((path / '.lock').exists())
        self.assertEqual(list(app.iterdir()), [])

    def test_cli_rejects_work_nested_store_before_lock_or_delivery(self):
        original = self.root / 'original-work'
        original.mkdir()
        nested = original / 'private-runtime-store'
        arguments = ['runtime_update.py', '--store', str(nested), 'stage',
                     '--manifest', str(self.root / 'missing-manifest'), '--public-key', self.public,
                     '--current-app', str(self.root / 'missing.app'), '--work', str(original),
                     '--python', '/unneeded/python']
        with patch.object(runtime.sys, 'argv', arguments), patch.object(runtime, 'store_lock') as locked, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.main(), 1)
        locked.assert_not_called()
        self.assertFalse(nested.exists())
        self.assertEqual(list(original.iterdir()), [])

    def test_game_process_detection_is_observation_only(self):
        with patch.object(runtime.subprocess, 'check_output', return_value='123 45 /Applications/Ocarina.app/Contents/MacOS/OcarinaOfTime\n'):
            with self.assertRaises(ValueError):
                runtime.game_closed()
        with patch.object(runtime.subprocess, 'check_output', return_value='456 78 /usr/bin/other\n'):
            runtime.game_closed()


if __name__ == '__main__':
    unittest.main()
