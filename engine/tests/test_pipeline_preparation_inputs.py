"""CPU-only archive input/environment guards; no native, SDK, signing or Metal calls."""
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ENGINE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pipeline_build_under_test',ENGINE/'build.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class PipelinePreparationInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tree=self.root/'tree';self.work=self.root/'work'
        self.metadata=dict(complete=True,compiler_context_schema=2,compiler_context_sha256='a'*64)

    def manifest(self,mode='full'):
        seed,libraries,_=build.shader_dirs(self.tree,mode)
        seed.mkdir(parents=True,exist_ok=True);libraries.mkdir(parents=True,exist_ok=True)
        (seed/'seed-manifest.json').write_text(json.dumps(dict(chain='fixture-v28')))
        path=libraries/'libraries-manifest.json';path.write_text(json.dumps(self.metadata))
        return libraries,path

    def test_host_environment_overrides_diagnostics_without_mutation(self):
        original=dict(TOTK_FAST_MATH='1',TOTK_SHADER_DEVICE_LIBS='1',OOT_UMUL_INLINE='9',
                      TOTK_PAR_RECHECK='0',KOKIRI_ARCHIVE_VERIFY_ONLY='1',UNRELATED_FIXTURE='retained')
        with patch.dict(os.environ,original,clear=True),patch.object(build,'shader_jobs',return_value=1):
            env=build.pipeline_archive_environment(self.tree,self.root/'cache',self.root/'seed')
            self.assertEqual(dict(os.environ),original)
        for name in ('TOTK_FAST_MATH','TOTK_SHADER_DEVICE_LIBS','OOT_UMUL_INLINE'):
            self.assertEqual(env[name],'0')
        self.assertEqual(env['TOTK_PAR_RECHECK'],'1')
        self.assertEqual(env['KOKIRI_ARCHIVE_VERIFY_ONLY'],'0')
        self.assertEqual(env['TOTK_PIPELINE_ARCHIVE_HOST'],'1')
        self.assertEqual(env['TOTK_NATIVE_DIR'],str(self.tree/'build'))
        self.assertEqual(env['TOTK_WARM_THREADS'],'1')
        self.assertEqual(env['UNRELATED_FIXTURE'],'retained')

    def test_snapshot_hash_and_context_use_the_same_single_read(self):
        libraries,path=self.manifest()
        raw=path.read_bytes()
        with patch.object(Path,'read_bytes',return_value=raw) as read:
            result=build.pipeline_library_inputs(libraries)
        read.assert_called_once_with()
        self.assertEqual(result,dict(libraries_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                                     compiler_context_sha256='a'*64,compiler_context_schema=2))

    def test_missing_or_invalid_manifest_is_rejected(self):
        libraries,path=self.manifest()
        path.unlink()
        with self.assertRaisesRegex(ValueError,'pipeline library manifest'):
            build.pipeline_library_inputs(libraries)
        path.write_bytes(b'not JSON')
        with self.assertRaisesRegex(ValueError,'pipeline library manifest'):
            build.pipeline_library_inputs(libraries)

    def test_missing_or_invalid_context_is_rejected(self):
        libraries,path=self.manifest()
        for changes in ({'compiler_context_schema':None},{'compiler_context_schema':1},
                        {'compiler_context_schema':2.0},{'compiler_context_sha256':None},
                        {'compiler_context_sha256':'a'*63},{'compiler_context_sha256':'A'*64},
                        {'compiler_context_sha256':'a'*64+'\n'}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps(dict(self.metadata,**changes)))
                with self.assertRaisesRegex(ValueError,'schema 2 compiler context'):
                    build.pipeline_library_inputs(libraries)

    def run_archive(self,mode,change=None,*,verify_only=False,overrides=None,archive_change=False,
                    runtime_change=False,request_change=False,expected_error=None):
        libraries,path=self.manifest(mode)
        native=self.work/'build/oot-native';native.parent.mkdir(parents=True,exist_ok=True)
        native.write_bytes(b'CPU fixture only')
        lists=[self.root/'pso_title.tsv',self.root/'pso_manifest.tsv']
        for listed in lists:listed.write_text('# no render or mesh rows\n')
        row='C\tfixture_compute_b';key='c'+hashlib.sha256(row[2:].encode()).hexdigest()[:40]
        cache=self.tree/'build/compute-pipelines/fixture-v28'
        archive=cache/'pipelines/fixture.metalarchive'
        if verify_only:
            archive.parent.mkdir(parents=True);archive.write_bytes(b'CPU fixture, never loaded')
        def fake_native(*args,**kwargs):
            self.assertEqual(kwargs['env']['KOKIRI_ARCHIVE_VERIFY_ONLY'],'1' if verify_only else '0')
            self.assertEqual(kwargs['env']['TOTK_PAR_RECHECK'],'1')
            report=dict(render=0,compute=1,mesh=0,kept=0,failed=0,seconds=0,write_failed=0,arch='fixture_arch')
            if verify_only:
                report.update(verify_only=True,library_jit_attempts=0,archive_misses=0,archive_writes=0,
                              verified_rows=1,archive_files_opened=1,**build.pipeline_library_inputs(libraries))
            for name,value in (overrides or {}).items():
                if value is None:report.pop(name,None)
                else:report[name]=value
            if archive_change:archive.write_bytes(b'changed during allegedly read-only verify')
            if runtime_change:native.write_bytes(b'replaced runtime')
            if request_change:lists[0].write_text('# changed request snapshot\n')
            if change is not None:change(path)
            kwargs['stdout'].write(json.dumps(report)+'\n')
            return subprocess.CompletedProcess(args[0],0)
        def fake_copy(made,target,arch,chain):
            target.mkdir(parents=True)
            (target/f'pipelines-{arch}.tsv').write_text(key+'\tfixture\n')
            return 1
        copied=Mock(side_effect=fake_copy)
        modules={'prepare_compute_pipelines':SimpleNamespace(compute_rows=lambda seed:[row]),
                 'dev.game_slot':SimpleNamespace(GameSlot=lambda **kwargs:nullcontext())}
        with patch.dict(sys.modules,modules),patch.object(sys,'path',list(sys.path)), \
             patch.object(build,'shader_jobs',return_value=1), \
             patch.object(build.subprocess,'run',side_effect=fake_native) as run, \
             patch.object(build,'build_helpers',return_value=SimpleNamespace(mac_pipeline_files=copied)):
            if change is not None or expected_error:
                with self.assertRaisesRegex(ValueError,expected_error or 'changed during archive preparation'):
                    build.compute_pipeline_archive(self.work,self.tree,lists,mode,verify_only=verify_only)
                copied.assert_not_called()
                return
            target=build.compute_pipeline_archive(self.work,self.tree,lists,mode,verify_only=verify_only)
        run.assert_called_once();copied.assert_called_once()
        report=json.loads((target/'compute-manifest.json').read_text())
        self.assertEqual(report['libraries_manifest_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['compiler_context_sha256'],'a'*64)
        self.assertEqual(report['compiler_context_schema'],2)
        self.assertIn('native-read final manifest' if verify_only else 'intended manifest snapshot',report['library_input_binding'])
        self.assertIn('including archive hits',report['counter_basis'])
        if verify_only:
            self.assertTrue(report['verification_process_fresh'])
            self.assertEqual(report['archive_snapshot_before_sha256'],report['archive_snapshot_after_sha256'])
            self.assertEqual(report['verification_runtime_sha256'],build.sha(native))

    def test_unchanged_full_inputs_are_accepted_and_recorded(self):
        self.run_archive('full')

    def test_unchanged_title_inputs_are_accepted_and_recorded(self):
        self.run_archive('title')

    def test_changed_manifest_rejects_before_archive_copy(self):
        self.run_archive('full',lambda path:path.write_bytes(path.read_bytes()+b'\n'))

    def test_changed_title_context_rejects_before_archive_copy(self):
        self.run_archive('title',lambda path:path.write_text(json.dumps(dict(self.metadata,compiler_context_sha256='b'*64))))

    def test_strict_fresh_read_only_pass_binds_actual_final_inputs(self):
        self.run_archive('full',verify_only=True)

    def test_old_runtime_success_report_without_verify_capability_fails(self):
        self.run_archive('full',verify_only=True,overrides={'verify_only':None},expected_error='fresh read-only')

    def test_fake_success_with_jit_or_miss_or_archive_write_is_rejected(self):
        for field in ('library_jit_attempts','archive_misses','archive_writes'):
            with self.subTest(field=field):
                # Give each native report an independent tiny fixture tree.
                self.tree=self.root/field;self.work=self.root/(field+'-work')
                self.run_archive('full',verify_only=True,overrides={field:1},expected_error='requires zero '+field)

    def test_verified_row_gap_is_rejected(self):
        self.run_archive('full',verify_only=True,overrides={'verified_rows':0},expected_error='every requested row')

    def test_native_failure_counter_cannot_hide_behind_successful_counts(self):
        self.run_archive('full',verify_only=True,overrides={'failed':1},expected_error='incomplete pipeline archive')

    def test_no_actual_archive_reopened_is_rejected(self):
        self.run_archive('full',verify_only=True,overrides={'archive_files_opened':0},expected_error='reopen evidence')

    def test_native_used_another_library_manifest(self):
        self.run_archive('full',verify_only=True,overrides={'libraries_manifest_sha256':'b'*64},expected_error='final libraries_manifest')

    def test_archive_wrote_bytes_despite_claiming_zero_writes(self):
        self.run_archive('full',verify_only=True,archive_change=True,expected_error='archive changed')

    def test_changed_raw_runtime_is_rejected(self):
        self.run_archive('full',verify_only=True,runtime_change=True,expected_error='runtime changed')

    def test_changed_final_libraries_are_rejected(self):
        self.run_archive('full',lambda path:path.write_bytes(path.read_bytes()+b'\n'),verify_only=True)

    def test_changed_request_snapshot_is_rejected(self):
        self.run_archive('full',verify_only=True,request_change=True,expected_error='request lists changed')

    def test_directory_only_archive_drift_changes_snapshot(self):
        folder=self.root/'archive';folder.mkdir();(folder/'existing').write_bytes(b'x')
        before=build.pipeline_archive_snapshot(folder)
        (folder/'empty-new-directory').mkdir()
        self.assertNotEqual(before['sha256'],build.pipeline_archive_snapshot(folder)['sha256'])

    def test_full_package_runs_final_read_only_pass_after_collection_and_recheck(self):
        class StopBeforePackaging(Exception):pass
        for mode,expected in [('full',[False,'compile',False,'coverage',True]),
                              ('title',[False,'compile',False,'coverage']),('none',[])]:
            with self.subTest(mode=mode):
                events=[]
                def archive(*args,**kwargs):
                    events.append(kwargs.get('verify_only',False));return self.root/'prepared'
                with patch.object(build,'validate_runtime_app'),patch.object(build,'ensure_disk_space'), \
                     patch.object(build,'catalog_context',return_value={}), \
                     patch.object(build,'verify_shader_resources',return_value={'chain':'fixture-v28'}), \
                     patch.object(build,'resolve_lists',return_value=()), \
                     patch.object(build,'compute_pipeline_archive',side_effect=archive), \
                     patch.object(build,'compile_shader_libraries',side_effect=lambda *a,**k:events.append('compile')), \
                     patch.object(build,'verify_recorded_variant_coverage',side_effect=lambda *a:events.append('coverage')), \
                     patch.object(build,'write_preparation_receipt',side_effect=StopBeforePackaging), \
                     patch.object(build.subprocess,'run') as no_process:
                    with self.assertRaises(StopBeforePackaging):
                        build.package_app(self.work,self.tree,self.root/'fixture.app',mode=mode)
                    no_process.assert_not_called()
                self.assertEqual(events,expected)

    def test_copied_pre_sign_inputs_must_match_verified_receipt(self):
        paths=build._script('preparation_receipt').preparation_artifact_paths('fixture_arch')
        app=self.root/'fixture.app';hashes={}
        for key,relative in paths.items():
            path=app/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(('synthetic '+key).encode());hashes[key]=build.sha(path)
        receipt=dict(prepared=True,identity={'gpu_architecture':'fixture_arch'},artifact_sha256=hashes)
        build.verify_staged_preparation_inputs(app,receipt)
        for key,relative in paths.items():
            with self.subTest(key=key):
                path=app/relative;original=path.read_bytes();path.write_bytes(b'replaced after verification')
                with self.assertRaisesRegex(ValueError,'staged preparation input differs'):
                    build.verify_staged_preparation_inputs(app,receipt)
                path.write_bytes(original)

    def test_unprepared_package_keeps_existing_no_proof_behavior(self):
        build.verify_staged_preparation_inputs(self.root/'absent.app',{'prepared':False})


if __name__=='__main__':
    unittest.main()
