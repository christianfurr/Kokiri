"""Tiny filesystem fixtures; no real player cache, compiler, copy tool or game."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('runtime_inputs_under_test', Path(__file__).with_name('runtime_inputs.py'))
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


class RuntimeInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.work = self.root / 'work'
        self.run = self.work / 'preparation-inputs/run-fixture'
        self.cache = self.run / 'observed-cache'
        (self.cache / 'pipelines').mkdir(parents=True)
        (self.cache / 'nested/empty').mkdir(parents=True)
        self.shader_list = self.run / 'shader-list.tsv'
        self.shader_list.write_bytes(b'# source metadata, not compiled work\n\nfirst\tvariant\nsecond\tvariant')
        (self.run / 'pso-user.tsv').write_bytes(b'# pso metadata\nC\tfirst\nM\tsecond\n')
        (self.run / 'profile-pso-user.tsv').write_bytes(b'C\tthird\nM\tfourth\nC\tfifth\n')
        (self.cache / 'pso-collected.tsv').write_bytes(b'C\tfirst\nM\tsecond\nM\tthird\nC\tfourth\n')
        (self.cache / 'nested/observed.metal').write_bytes(b'// private synthetic shader fixture\n')
        (self.cache / 'nested/reflection.json').write_text('{"unknown": [1, 2, 3]}')
        (self.cache / 'nested/unknown.data').write_bytes(b'\0complete cache fixture\xff')
        self.identity = dict(schema=6, chain=inputs.DEFAULT_CHAIN, gpu='fixture-gpu', os='fixture-os',
                             unknown_future_field={'keep': ['all', 'fields']})
        self.identity_file = self.cache / 'pipelines/identity.json'
        self.identity_file.write_text(json.dumps(self.identity))

    def capture(self):
        return inputs.capture_inputs(self.work, self.shader_list, (self.cache,))

    def clone(self, copy_function=shutil.copy2):
        clone = self.root / 'cloned-work'
        shutil.copytree(self.work, clone, copy_function=copy_function)
        return clone

    def test_entire_snapshot_includes_complete_cache_separate_psos_and_empty_directories(self):
        snapshot = self.capture()
        expected = {'.', 'shader-list.tsv', 'pso-user.tsv', 'profile-pso-user.tsv',
                    'observed-cache', 'observed-cache/pipelines', 'observed-cache/pipelines/identity.json',
                    'observed-cache/pso-collected.tsv', 'observed-cache/nested', 'observed-cache/nested/empty',
                    'observed-cache/nested/observed.metal', 'observed-cache/nested/reflection.json',
                    'observed-cache/nested/unknown.data'}
        self.assertEqual(set(snapshot['entries']), expected)
        self.assertEqual(snapshot['files'], 8)
        self.assertEqual(snapshot['bytes'], sum(path.stat().st_size for path in self.run.rglob('*') if path.is_file()))
        self.assertEqual(snapshot['metadata_rows'], {'shader-list.tsv': 2, 'pso-user.tsv': 2,
                                                   'profile-pso-user.tsv': 3, 'observed-cache/pso-collected.tsv': 4})
        self.assertIn('not compiled', snapshot['row_count_basis'])
        self.assertEqual(snapshot['learned_caches'][0]['identity'], self.identity)
        self.assertEqual(snapshot['entries']['profile-pso-user.tsv']['path'], str(self.run / 'profile-pso-user.tsv'))
        self.assertEqual(snapshot['entries']['profile-pso-user.tsv']['relative_to_work'],
                         'preparation-inputs/run-fixture/profile-pso-user.tsv')
        self.assertNotIn('translator', snapshot['learned_caches'][0]['identity'])
        self.assertNotIn('translation_context_sha256', snapshot['learned_caches'][0]['identity'])
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)

    def test_no_inputs_returns_none_without_scanning_and_caches_require_explicit_list(self):
        with patch.object(inputs.os, 'scandir', side_effect=AssertionError('Unexpected scan')):
            self.assertIsNone(inputs.capture_inputs(self.root / 'nonexistent-work'))
            with self.assertRaisesRegex(ValueError, 'explicit shader list'):
                inputs.capture_inputs(self.work, learned_caches=(self.cache,))
        self.assertEqual(inputs.remap_inputs(None, self.root / 'not-needed'), (None, ()))
        self.assertIsNone(inputs.verify_cloned_inputs(None, self.root / 'not-needed'))
        self.assertIsNone(inputs.verify_unchanged(None))

    def test_cache_only_requires_exact_chain_and_preserves_unknown_identity_fields(self):
        self.assertEqual(self.capture()['learned_caches'][0]['identity'], self.identity)
        self.identity_file.write_text(json.dumps({**self.identity, 'chain': 'oot-native-v23-old'}))
        with self.assertRaisesRegex(ValueError, 'shader chain differs'):
            self.capture()

    def test_duplicate_identity_keys_are_rejected(self):
        self.identity_file.write_text('{"chain":"old","chain":"' + inputs.DEFAULT_CHAIN + '"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate cache identity'):
            self.capture()

    def test_missing_or_oversized_selected_cache_identity_is_rejected(self):
        original = self.identity_file.read_bytes()
        self.identity_file.unlink()
        with self.assertRaisesRegex(ValueError, 'lacks pipelines/identity.json'):
            self.capture()
        self.identity_file.write_bytes(original + b' ' * (1 << 20))
        with self.assertRaisesRegex(ValueError, 'metadata bound'):
            self.capture()

    def test_only_owned_run_below_preparation_inputs_can_be_selected(self):
        outside = self.work / 'shader-list.tsv'
        outside.write_text('outside snapshot')
        with self.assertRaisesRegex(ValueError, 'owned run'):
            inputs.capture_inputs(self.work, outside)
        direct = self.work / 'preparation-inputs/shader-list.tsv'
        direct.write_text('missing explicit run directory')
        with self.assertRaisesRegex(ValueError, 'owned run'):
            inputs.capture_inputs(self.work, direct)
        with self.assertRaisesRegex(ValueError, 'inside the input run'):
            inputs.capture_inputs(self.work, self.shader_list, (self.work,))
        with self.assertRaisesRegex(ValueError, 'inside the input run'):
            inputs.capture_inputs(self.work, self.shader_list, (self.run,))

    def test_duplicate_or_nested_selected_cache_roots_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate learned cache'):
            inputs.capture_inputs(self.work, self.shader_list, (self.cache, self.cache))
        with self.assertRaisesRegex(ValueError, 'must not overlap'):
            inputs.capture_inputs(self.work, self.shader_list, (self.cache, self.cache / 'nested'))

    def test_file_and_directory_symlinks_are_rejected(self):
        for directory in (False, True):
            with self.subTest(directory=directory):
                link = self.run / 'unsafe-link'
                link.symlink_to(self.root if directory else self.shader_list, target_is_directory=directory)
                try:
                    with self.assertRaises(ValueError):
                        self.capture()
                finally:
                    link.unlink()
        selected_link = self.run / 'selected-list.tsv'
        selected_link.symlink_to(self.shader_list)
        with self.assertRaises(ValueError):
            inputs.capture_inputs(self.work, selected_link)

    def test_hardlinked_and_nonregular_files_are_rejected(self):
        alias = self.run / 'hardlinked-input'
        os.link(self.shader_list, alias)
        with self.assertRaisesRegex(ValueError, 'without hardlinks'):
            self.capture()
        alias.unlink()
        fifo = self.run / 'not-a-regular-file'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular files'):
            self.capture()

    def test_mutation_while_hashing_is_detected(self):
        original_read = os.read
        original_inode = self.shader_list.stat().st_ino
        changed = False
        def reading(descriptor, size):
            nonlocal changed
            block = original_read(descriptor, size)
            if not changed and os.fstat(descriptor).st_ino == original_inode:
                changed = True
                self.shader_list.write_bytes(b'changed while an input descriptor was open')
            return block
        with patch.object(inputs.os, 'read', side_effect=reading):
            with self.assertRaisesRegex(ValueError, 'changed while hashing'):
                self.capture()
        self.assertTrue(changed)

    def test_verification_detects_content_inventory_and_stat_only_changes(self):
        snapshot = self.capture()
        inputs.verify_unchanged(snapshot)
        before = self.shader_list.stat()
        os.utime(self.shader_list, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        changed = self.capture()
        self.assertEqual(snapshot['content_sha256'], changed['content_sha256'])
        self.assertNotEqual(snapshot['stat_sha256'], changed['stat_sha256'])
        with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
            inputs.verify_unchanged(snapshot)
        snapshot = changed
        (self.run / 'new-file').write_bytes(b'new inventory')
        with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
            inputs.verify_unchanged(snapshot)

    def test_reading_atime_does_not_invalidate_original_provenance(self):
        snapshot = self.capture()
        for path in self.run.rglob('*'):
            if path.is_file():
                path.read_bytes()
        inputs.verify_unchanged(snapshot)

    def test_changes_to_unknown_complete_cache_payload_are_detected(self):
        snapshot = self.capture()
        payload = self.cache / 'nested/unknown.data'
        payload.write_bytes(b'changed synthetic payload')
        self.assertNotEqual(self.capture()['content_sha256'], snapshot['content_sha256'])
        with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
            inputs.verify_unchanged(snapshot)

    def test_remapping_and_clone_verification_keep_all_content_but_independent_file_identities(self):
        snapshot = self.capture()
        clone = self.clone()
        shader_list, caches = inputs.remap_inputs(snapshot, clone)
        self.assertEqual(shader_list, clone / 'preparation-inputs/run-fixture/shader-list.tsv')
        self.assertEqual(caches, (clone / 'preparation-inputs/run-fixture/observed-cache',))
        copied = inputs.verify_cloned_inputs(snapshot, clone)
        self.assertEqual(copied['content_sha256'], snapshot['content_sha256'])
        self.assertNotEqual(copied['stat_sha256'], snapshot['stat_sha256'])
        self.assertEqual(copied['metadata_rows'], snapshot['metadata_rows'])
        inputs.verify_unchanged(snapshot)

    def test_clone_cannot_reuse_or_nest_inside_the_original_work(self):
        snapshot = self.capture()
        nested = self.work / 'nested-clone'
        nested.mkdir()
        for clone in (self.work, nested, self.root):
            with self.subTest(clone=clone):
                with self.assertRaisesRegex(ValueError, 'must not overlap'):
                    inputs.remap_inputs(snapshot, clone)

    def test_clone_requires_separate_pso_sibling_and_preserved_file_modes(self):
        snapshot = self.capture()
        clone = self.clone()
        pso = clone / 'preparation-inputs/run-fixture/profile-pso-user.tsv'
        original = pso.read_bytes()
        pso.unlink()
        with self.assertRaisesRegex(ValueError, 'inputs differ'):
            inputs.verify_cloned_inputs(snapshot, clone)
        pso.write_bytes(original)
        pso.chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'inputs differ'):
            inputs.verify_cloned_inputs(snapshot, clone)

    def test_clone_cannot_share_source_file_hardlinks(self):
        snapshot = self.capture()
        clone = self.clone(copy_function=os.link)
        with self.assertRaisesRegex(ValueError, 'without hardlinks'):
            inputs.verify_cloned_inputs(snapshot, clone)

    def test_clone_cannot_reuse_source_inodes_after_original_names_are_removed(self):
        snapshot = self.capture()
        clone = self.clone(copy_function=os.link)
        for path in self.run.rglob('*'):
            if path.is_file():
                path.unlink()
        # Each clone file now has one link; its captured source inode still makes
        # it ineligible as an independent copy of the owned original snapshot.
        with self.assertRaisesRegex(ValueError, 'shares original input file identities'):
            inputs.verify_cloned_inputs(snapshot, clone)


if __name__ == '__main__':
    unittest.main()
