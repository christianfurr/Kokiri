"""Small offline safety checks; fixtures are not gameplay or distribution evidence."""
import base64
import contextlib
import io
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

    def app(self, folder=None):
        app = (folder or self.root) / 'Kokiri Game.app'
        executable = app / 'Contents/MacOS/KokiriGame'
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b'#!/bin/sh\nexit 0\n')
        executable.chmod(0o700)
        resources = app / 'Contents/_CodeSignature/CodeResources'
        resources.parent.mkdir()
        resources.write_bytes(b'fixture signature resources')
        receipt = dict(schema='kokiri-preparation-receipt-v1', mode='full', prepared=True, errors=[],
                       identity=dict(source_commit=self.record['source_commit'], chain=self.record['shader_chain'],
                                     runtime_sha256=runtime.sha(executable), translation_context_sha256='c' * 64,
                                     translator_sha256='d' * 64, gpu_architecture='apple-gpu-fixture'),
                       variants=dict(default=dict(requested=2, completed=2, failed=0),
                                     listed=dict(requested=0, completed=0, failed=0), unique_completed=2),
                       artifact_sha256=dict(runtime_sha256=runtime.sha(executable)),
                       libraries=dict(requested=2, completed=2, failed=0),
                       pipelines=dict(requested=2, completed=2, failed=0, write_failed=0, unaccounted=0))
        info = dict(CFBundleIdentifier=runtime.PRODUCT, CFBundleExecutable='KokiriGame', KokiriGameUpdate='131072',
                    KokiriPrepared=True, KokiriShaders='full', KokiriSourceCommit=self.record['source_commit'])
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
            path.write_text(json.dumps(dict(files={payload.name: runtime.sha(payload)})))
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
            self.assertEqual(result['executable_sha256'], receipt['identity']['runtime_sha256'])
            for field in ('source_commit', 'chain', 'runtime_sha256'):
                with self.subTest(identity=field):
                    altered = deepcopy(receipt)
                    altered['identity'][field] = 'different'
                    self.write_receipt(app, altered, info)
                    with self.assertRaises(ValueError):
                        runtime.inspect_app(app, self.record)

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
