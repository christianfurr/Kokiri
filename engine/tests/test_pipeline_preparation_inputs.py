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
                      TOTK_PAR_RECHECK='0',UNRELATED_FIXTURE='retained')
        with patch.dict(os.environ,original,clear=True),patch.object(build,'shader_jobs',return_value=1):
            env=build.pipeline_archive_environment(self.tree,self.root/'cache',self.root/'seed')
            self.assertEqual(dict(os.environ),original)
        for name in ('TOTK_FAST_MATH','TOTK_SHADER_DEVICE_LIBS','OOT_UMUL_INLINE'):
            self.assertEqual(env[name],'0')
        self.assertEqual(env['TOTK_PAR_RECHECK'],'1')
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

    def run_archive(self,mode,change=None):
        libraries,path=self.manifest(mode)
        native=self.work/'build/oot-native';native.parent.mkdir(parents=True,exist_ok=True)
        native.write_bytes(b'CPU fixture only')
        lists=[self.root/'pso_title.tsv',self.root/'pso_manifest.tsv']
        for listed in lists:listed.write_text('# no render or mesh rows\n')
        row='C\tfixture_compute_b';key='c'+hashlib.sha256(row[2:].encode()).hexdigest()[:40]
        def fake_native(*args,**kwargs):
            if change is not None:change(path)
            kwargs['stdout'].write(json.dumps(dict(render=0,compute=1,mesh=0,kept=0,
                                                  failed=0,seconds=0,write_failed=0,arch='fixture_arch'))+'\n')
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
            if change is not None:
                with self.assertRaisesRegex(ValueError,'changed during archive preparation'):
                    build.compute_pipeline_archive(self.work,self.tree,lists,mode)
                copied.assert_not_called()
                return
            target=build.compute_pipeline_archive(self.work,self.tree,lists,mode)
        run.assert_called_once();copied.assert_called_once()
        report=json.loads((target/'compute-manifest.json').read_text())
        self.assertEqual(report['libraries_manifest_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['compiler_context_sha256'],'a'*64)
        self.assertEqual(report['compiler_context_schema'],2)
        self.assertIn('intended manifest snapshot',report['library_input_binding'])
        self.assertIn('including archive hits',report['counter_basis'])

    def test_unchanged_full_inputs_are_accepted_and_recorded(self):
        self.run_archive('full')

    def test_unchanged_title_inputs_are_accepted_and_recorded(self):
        self.run_archive('title')

    def test_changed_manifest_rejects_before_archive_copy(self):
        self.run_archive('full',lambda path:path.write_bytes(path.read_bytes()+b'\n'))

    def test_changed_title_context_rejects_before_archive_copy(self):
        self.run_archive('title',lambda path:path.write_text(json.dumps(dict(self.metadata,compiler_context_sha256='b'*64))))


if __name__=='__main__':
    unittest.main()
