"""Offline stage/activation wiring with owned toy inputs and a fake builder."""
import contextlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_runtime_update as fixtures

_SELECTED = object()


class RuntimeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.RuntimeUpdateTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.runtime = fixtures.runtime
        self.root = self.base.root
        self.store, self.work = self.root / 'store', self.root / 'original-work'
        self.store.mkdir(mode=0o700)
        self.run = self.work / 'preparation-inputs/run-fixture'
        self.run.mkdir(parents=True)
        self.shader_list = self.run / 'shader-list.tsv'
        self.shader_list.write_text('# metadata fixture\nfirst\tvariant\nsecond\tvariant\n')
        (self.run / 'pso-user.tsv').write_text('C\tfirst\nM\tsecond\n')
        (self.run / 'profile-pso-user.tsv').write_text('M\tfirst\nC\tsecond\nC\tthird\n')
        self.caches = tuple(self.run / name for name in ('observed-cache', 'extra-cache'))
        for cache in self.caches:
            (cache / 'pipelines').mkdir(parents=True)
            (cache / 'pipelines/identity.json').write_text(json.dumps(dict(
                schema=6, chain=self.base.record['shader_chain'], gpu='fixture-gpu', os='fixture-os',
                unknown_identity_field=['preserve', 'verbatim'])))
            (cache / 'pso-collected.tsv').write_text('C\tobserved\nM\tobserved\n')
            (cache / 'observed.metal').write_text('// synthetic private cache fixture\n')
            (cache / 'reflection.json').write_text('{"synthetic": true}')
        self.current_app, _, _ = self.base.app()
        self.archive = self.base.archive()
        self.manifest, self.signature = self.base.manifest()
        self.version = self.store / 'version-2'
        self.build_arguments = None

    def native_stub(self, arguments, **kwargs):
        self.assertEqual(arguments[0], '/usr/bin/codesign', 'Unexpected native command in offline test')
        return SimpleNamespace(returncode=0)

    def stage(self, *, shader_list=_SELECTED, learned_caches=_SELECTED, mutate_build=None, mutate_clone=None):
        shader_list = self.shader_list if shader_list is _SELECTED else shader_list
        learned_caches = self.caches if learned_caches is _SELECTED else learned_caches

        def clone(source, destination):
            shutil.copytree(source, destination)
            if mutate_clone:
                mutate_clone(Path(destination))

        def build(arguments, log, environment):
            self.build_arguments = [str(value) for value in arguments]
            self.assertEqual(environment['OOT_SHADERS'], 'full')
            app = Path(arguments[arguments.index('--out') + 1])
            work = Path(arguments[arguments.index('--work') + 1])
            created, _, _ = self.base.app(app.parent)
            self.assertEqual(created, app)
            candidate = self.runtime.inspect_app(app, self.base.record)
            output = work / 'logs/package-output.json'
            output.parent.mkdir(parents=True)
            output.write_text(json.dumps(self.base.package_output(candidate)))
            if mutate_build:
                mutate_build(work)

        with patch.object(self.runtime, 'game_closed'), \
                patch.object(self.runtime.subprocess, 'run', side_effect=self.native_stub) as native, \
                patch.object(self.runtime.shutil, 'disk_usage', return_value=SimpleNamespace(free=10 << 30)), \
                patch.object(self.runtime, 'clone_work', side_effect=clone) as cloned, \
                patch.object(self.runtime, 'build_candidate', side_effect=build) as built:
            self.effects = dict(native=native, cloned=cloned, built=built)
            return self.runtime.stage(self.store, self.manifest, self.signature, self.base.public,
                                      self.archive, self.current_app, self.work, self.root / 'fake-python',
                                      shader_list=shader_list, learned_caches=learned_caches)

    def test_stage_forwards_only_remapped_inputs_and_retains_separate_psos(self):
        result = self.stage()
        self.assertEqual(result['status'], 'staged')
        self.assertFalse(result['activated'])
        self.assertFalse(result['game_launched'])
        cloned_run = self.version / 'work/preparation-inputs/run-fixture'
        arguments = self.build_arguments
        self.assertEqual(arguments[arguments.index('--rebuild') + 1], str(self.current_app))
        self.effects['built'].assert_called_once()
        self.assertEqual(arguments.count('--shader-list'), 1)
        self.assertEqual(arguments[arguments.index('--shader-list') + 1], str(cloned_run / 'shader-list.tsv'))
        forwarded = [arguments[index + 1] for index, value in enumerate(arguments) if value == '--learned-cache']
        self.assertEqual(forwarded, [str(cloned_run / cache.name) for cache in self.caches])
        for original in (self.shader_list, *self.caches):
            self.assertNotIn(str(original), arguments)
        for sibling in ('pso-user.tsv', 'profile-pso-user.tsv'):
            self.assertEqual((cloned_run / sibling).read_bytes(), (self.run / sibling).read_bytes())
        provenance_path = self.version / 'input-provenance.json'
        provenance = self.runtime.read_json(provenance_path)
        self.assertEqual(provenance['schema'], 'kokiri-runtime-input-provenance-v1')
        self.assertEqual(provenance['original']['content_sha256'], provenance['staged']['content_sha256'])
        self.assertEqual(provenance['staged']['metadata_rows']['pso-user.tsv'], 2)
        self.assertEqual(provenance['staged']['metadata_rows']['profile-pso-user.tsv'], 3)
        transaction = self.runtime.read_json(self.version / 'transaction.json')
        self.assertEqual(transaction['phase'], 'prepared')
        self.assertEqual(transaction['input_provenance_sha256'], self.runtime.sha(provenance_path))
        with patch.object(self.runtime, 'game_closed'), \
                patch.object(self.runtime.subprocess, 'run', side_effect=self.native_stub):
            activated = self.runtime.activate(self.store, 2, self.base.public)
        self.assertEqual(activated['status'], 'activated')
        self.assertEqual(self.runtime.state(self.store)['active']['app'], str(self.version / 'Kokiri Game.app'))

    def test_no_selected_inputs_preserves_rebuild_without_forwarded_or_scanned_inputs(self):
        self.stage(shader_list=None, learned_caches=())
        self.assertNotIn('--shader-list', self.build_arguments)
        self.assertNotIn('--learned-cache', self.build_arguments)
        self.assertEqual(self.build_arguments[self.build_arguments.index('--rebuild') + 1], str(self.current_app))
        self.effects['built'].assert_called_once()
        provenance = self.runtime.read_json(self.version / 'input-provenance.json')
        self.assertIsNone(provenance['original'])
        self.assertIsNone(provenance['staged'])

    def assert_not_prepared(self):
        transaction = self.runtime.read_json(self.version / 'transaction.json')
        self.assertNotEqual(transaction['phase'], 'prepared')
        self.assertFalse((self.store / 'state.json').exists())

    def test_changed_clone_is_refused_before_builder_runs(self):
        def mutate(work):
            (work / 'preparation-inputs/run-fixture/profile-pso-user.tsv').unlink()
        with self.assertRaisesRegex(ValueError, 'Cloned preparation inputs differ'):
            self.stage(mutate_clone=mutate)
        self.effects['built'].assert_not_called()
        self.assert_not_prepared()

    def test_original_mutated_by_fake_builder_cannot_be_marked_prepared(self):
        def mutate(work):
            self.shader_list.write_text('changed original metadata\n')
        with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
            self.stage(mutate_build=mutate)
        self.assert_not_prepared()

    def test_staged_cache_mutated_by_fake_builder_cannot_be_marked_prepared(self):
        def mutate(work):
            payload = work / 'preparation-inputs/run-fixture/observed-cache/reflection.json'
            payload.write_text('{"changed": true}')
        with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
            self.stage(mutate_build=mutate)
        self.assert_not_prepared()

    def test_outside_work_inputs_are_refused_before_key_enrollment_or_clone(self):
        outside = self.root / 'outside/shader-list.tsv'
        outside.parent.mkdir()
        outside.write_text('outside selected work\n')
        with self.assertRaisesRegex(ValueError, 'owned run'):
            self.stage(shader_list=outside)
        for effect in self.effects.values():
            effect.assert_not_called()
        self.assertFalse((self.store / 'trust.json').exists())
        self.assertFalse(self.version.exists())

    def test_caches_without_list_are_refused_before_key_enrollment_or_clone(self):
        with self.assertRaisesRegex(ValueError, 'explicit shader list'):
            self.stage(shader_list=None)
        for effect in self.effects.values():
            effect.assert_not_called()
        self.assertFalse((self.store / 'trust.json').exists())
        self.assertFalse(self.version.exists())

    def test_activation_refuses_missing_changed_or_retyped_provenance(self):
        self.stage()
        path, transaction_path = self.version / 'input-provenance.json', self.version / 'transaction.json'
        original, original_transaction = path.read_bytes(), transaction_path.read_bytes()
        for mutation in ('missing', 'changed', 'schema'):
            with self.subTest(provenance=mutation):
                path.write_bytes(original)
                transaction_path.write_bytes(original_transaction)
                if mutation == 'missing':
                    path.unlink()
                elif mutation == 'changed':
                    path.write_bytes(original + b' ')
                else:
                    record = json.loads(original)
                    record['schema'] = 'unsupported-provenance'
                    self.runtime.atomic_json(path, record)
                    transaction = json.loads(original_transaction)
                    transaction['input_provenance_sha256'] = self.runtime.sha(path)
                    self.runtime.atomic_json(transaction_path, transaction)
                with patch.object(self.runtime, 'inspect_app') as inspected:
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        self.runtime.activate(self.store, 2, self.base.public)
                inspected.assert_not_called()
                self.assertFalse((self.store / 'state.json').exists())

    def assert_activation_refuses_changed_input(self, origin):
        self.stage()
        provenance = self.runtime.read_json(self.version / 'input-provenance.json')
        root = Path(provenance[origin]['root'])
        (root / 'profile-pso-user.tsv').write_text('changed explicit PSO sibling\n')
        with patch.object(self.runtime, 'inspect_app') as inspected:
            with self.assertRaisesRegex(ValueError, 'Original preparation inputs changed'):
                self.runtime.activate(self.store, 2, self.base.public)
        inspected.assert_not_called()
        self.assertFalse((self.store / 'state.json').exists())

    def test_activation_rechecks_original_inputs_before_promoting(self):
        self.assert_activation_refuses_changed_input('original')

    def test_activation_rechecks_staged_inputs_before_promoting(self):
        self.assert_activation_refuses_changed_input('staged')

    def test_cli_preserves_shader_list_and_repeatable_cache_arguments(self):
        arguments = ['runtime_update.py', '--store', str(self.store), 'stage',
                     '--manifest', str(self.manifest), '--signature', str(self.signature),
                     '--archive', str(self.archive), '--public-key', self.base.public,
                     '--current-app', str(self.current_app), '--work', str(self.work),
                     '--python', str(self.root / 'fake-python'), '--shader-list', str(self.shader_list)]
        for cache in self.caches:
            arguments += ['--learned-cache', str(cache)]
        with patch.object(self.runtime.sys, 'argv', arguments), \
                patch.object(self.runtime, 'stage', return_value=dict(status='synthetic-stage')) as staged, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.runtime.main(), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'synthetic-stage')
        self.assertEqual(staged.call_args.kwargs, dict(shader_list=self.shader_list, learned_caches=list(self.caches)))
        self.assertEqual(staged.call_args.args[6], self.work)


if __name__ == '__main__':
    unittest.main()
