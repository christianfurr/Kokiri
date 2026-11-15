"""CPU-only identity and output guards; no game, installer or Metal execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kokiri_build_under_test', ENGINE/'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class StandaloneBuildTests(unittest.TestCase):
    def test_isolated_shader_loader_and_verified_reuse(self):
        # Exercise the UI's actual -I entry, from an unrelated working folder.
        # Ready files are synthetic; source fingerprints come from real tools.
        code = r'''
import hashlib,json,pathlib,runpy,shutil,sys
from unittest.mock import patch
before=list(sys.path)
api=runpy.run_path(sys.argv[1]);g=api['ensure_shader_service'].__globals__
work=pathlib.Path(sys.argv[2]);folder=work/'shader-tools';native=folder/'native';native.mkdir(parents=True)
(native/'totk_xlate').write_bytes(b'fixture translator')
(native/'oot_write_proof.dylib').write_bytes(b'fixture proof')
record=api['shader_tools']().expected_inputs()
record.update(binary_sha256=hashlib.sha256((native/'totk_xlate').read_bytes()).hexdigest(),proof_binary_sha256=hashlib.sha256((native/'oot_write_proof.dylib').read_bytes()).hexdigest())
(folder/'build-record.json').write_text(json.dumps(record))
with patch.object(g['subprocess'],'run',side_effect=AssertionError('unexpected build/download')):
 assert api['ensure_shader_service'](work)==native.resolve()
 versioned=api['shader_service_folders'](work)[0]
 shutil.copytree(folder,versioned)
 assert api['ensure_shader_service'](work)==(versioned/'native').resolve()
 (versioned/'native/totk_xlate').write_bytes(b'unverified versioned binary')
 assert api['ensure_shader_service'](work)==native.resolve()
 (native/'totk_xlate').write_bytes(b'changed binary')
 with patch.dict(g,available_space=lambda p:0):
  try:api['ensure_shader_service'](work)
  except OSError:pass
  else:raise AssertionError('damaged ready tool was accepted')
assert sys.path==before
print('isolated ready and damaged-tool gates passed')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-c', code,
                                     str(ENGINE/'build.py'), directory],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('isolated ready and damaged-tool gates passed', result.stdout)

    def test_public_staged_rebuild_cli_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'Original.app';output=root/'Candidate.app';work=root/'owned-work'
            with patch.object(build,'update_runtime') as rebuild:
                build.main(['--rebuild',str(original),'--out',str(output),'--work',str(work),'--jobs','1'])
            rebuild.assert_called_once_with(original,work,out=output,shared=None,learned_caches=[])
            self.assertEqual(build.shader_jobs(),1)

    def test_committed_shader_callee_exposes_caller_options(self):
        result=subprocess.run([sys.executable,'-I',str(ENGINE/'scripts/prepare_ns2_seed.py'),'--help'],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for option in ('--translator','--batch-size','--max-batches','--jobs'):
            self.assertIn(option,result.stdout)

    def test_foreign_application_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)/'Foreign.app'
            info = app/'Contents/Info.plist'
            info.parent.mkdir(parents=True)
            original = plistlib.dumps({'CFBundleIdentifier': 'org.example.other'})
            info.write_bytes(original)
            with self.assertRaises(ValueError):
                build.validate_runtime_app(app)
            self.assertEqual(info.read_bytes(), original)

    def test_staged_rebuild_rejects_overlaps_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'Original.app';info=app/'Contents/Info.plist';info.parent.mkdir(parents=True)
            original=plistlib.dumps({'CFBundleIdentifier':build.RUNTIME_BUNDLE_ID,'MNGWorkFolder':str(root/'original-work'),
                                    'MNGGameDataFolder':str(root/'library')});info.write_bytes(original)
            for destination,work in [(app/'Contents/Candidate.app',root/'work'),
                                      (root/'Candidate.app',app/'Contents/work'),
                                      (root/'Candidate.app',root/'original-work/subdir'),
                                      (root/'Candidate.app',root/'Candidate.app/work'),
                                      (root/'Candidate.app',root/'Candidate.app'),
                                      (root/'library/Candidate.app',root/'work')]:
                with patch.object(build,'sync_tree',side_effect=AssertionError('must not sync')), \
                     patch.object(build,'ensure_shader_service',side_effect=AssertionError('must not build')):
                    with self.assertRaisesRegex(ValueError,'staged rebuild'):
                        build.update_runtime(app,work=work,out=destination)
                self.assertEqual(info.read_bytes(),original)

    def test_release_record_supplies_exact_source_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'outer/source';engine=root/'engine';engine.mkdir(parents=True)
            chain=engine/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h';chain.parent.mkdir(parents=True)
            chain.write_text('#define DMSH_CHAIN "oot-test" /* game: oot */\n')
            marker=root/'kokiri-source-release.json'
            record=dict(schema='kokiri-runtime-source-v1',product=build.RUNTIME_BUNDLE_ID,
                        source_commit='a'*40,game_update=131072,shader_chain='oot-test')
            marker.write_text(json.dumps(record))
            # This extracted source can sit below another repository's .git.
            (root.parent/'.git').mkdir(exist_ok=True)
            with patch.object(build,'GAME',engine),patch.object(build.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'b'*40,'')) as git:
                self.assertEqual(build.exact_source_commit(),'a'*40)
                git.assert_not_called()
                record['shader_chain']='old-chain';marker.write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError,'source-release'):
                    build.exact_source_commit()

    def test_source_checkout_cannot_be_an_output(self):
        for folder in (ENGINE.parent, ENGINE/'build'):
            with self.assertRaises(ValueError):
                build.external_workspace(folder)

    def test_actual_content_and_translator_define_reference_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, tree = root/'source', root/'work'
            (source/'assets').mkdir(parents=True)
            chain = source/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h'
            chain.parent.mkdir(parents=True)
            chain.write_text('#define DMSH_CHAIN "oot-test-v1" /* game: oot */\n')
            code = tree/'extracted/oot/exefs'
            code.mkdir(parents=True)
            (code/'main').write_bytes(b'verified original module')
            original_hash = hashlib.sha256((code/'main').read_bytes()).hexdigest()
            (source/'assets/expected-v131072.json').write_text(json.dumps({'exefs_sha256': {'main': original_hash}}))
            image = tree/'extracted/oot/romfs/romfs.bin'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'actual original game content')
            (image.parent/'index.json').write_text(json.dumps({'romfs_sha256': hashlib.sha256(image.read_bytes()).hexdigest(), 'romfs_size': image.stat().st_size}))
            (tree/'build/game-data/oot').mkdir(parents=True)
            translator = tree/'build/shader-service/totk_xlate'
            translator.parent.mkdir(parents=True)
            translator.write_bytes(b'actual rebuilt translator')
            with patch.object(build, 'GAME', source):
                context = build.catalog_context(tree)
                self.assertEqual(context['shader_chain'], 'oot-test-v1')
                self.assertEqual(context['translator_sha256'], hashlib.sha256(translator.read_bytes()).hexdigest())
                for key in ('compiler_sha256', 'target_sha256', 'options_sha256'):
                    self.assertIsNone(context[key])
                image.write_bytes(b'changed content of same size')
                with self.assertRaisesRegex(ValueError, 'differs from verified extraction'):
                    build.catalog_context(tree)
                (code/'main').write_bytes(b'damaged module')
                with self.assertRaisesRegex(ValueError, 'original module verification failed'):
                    build.catalog_context(tree)

    def test_failed_image_clone_has_no_copy_fallback(self):
        helpers = build.build_helpers()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'romfs.bin'
            source.write_bytes(b'original image')
            target = Path(directory)/'output/romfs.bin'
            with patch.object(helpers, 'clonefile', return_value=False), patch.object(helpers.shutil, 'copy2', side_effect=AssertionError('full-image copy attempted')):
                with self.assertRaises(helpers.BuildError):
                    helpers.clone(source, target)
            self.assertEqual(source.read_bytes(), b'original image')
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
