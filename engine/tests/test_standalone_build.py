"""CPU-only identity and output guards; no game, installer or Metal execution."""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
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


class PrivateRuntimeMetadataTests(unittest.TestCase):
    """Tiny synthetic packages; every external process is forbidden or mocked."""

    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.capabilities={key:1 for key in build.PRIVATE_RUNTIME_CAPABILITIES}
        for name in ('Popen','run','check_output'):
            forbidden=patch.object(build.subprocess,name,side_effect=AssertionError('unexpected external process'))
            forbidden.start();self.addCleanup(forbidden.stop)

    def app(self,name,metadata):
        app=self.root/name;info=app/'Contents/Info.plist';info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps(metadata))
        return app

    def metadata(self,capabilities=None):
        return dict(CFBundleIdentifier=build.RUNTIME_BUNDLE_ID,CFBundleExecutable=build.RUNTIME_EXECUTABLE,
                    UnrelatedOldKey='must not carry',**(capabilities or {}))

    def test_owned_metadata_is_allowlisted(self):
        app=self.app('Private.app',self.metadata(self.capabilities))
        self.assertEqual(build.validate_runtime_app(app),self.capabilities)
        self.assertEqual(build.validate_runtime_app(self.app('Ordinary.app',self.metadata())),{})
        self.assertEqual(build.validate_runtime_app(self.root/'Absent.app'),{})

    def test_each_present_marker_requires_exact_integer_one(self):
        app=self.app('Invalid.app',self.metadata())
        for key in self.capabilities:
            for value in (True,False,0,2,'1',1.0,[],{}):
                with self.subTest(key=key,value=value):
                    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(self.metadata({key:value})))
                    with self.assertRaisesRegex(ValueError,'private runtime capability'):
                        build.package_app(self.root/'work',self.root/'tree',app)

    def test_non_dictionary_plist_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'not owned by Kokiri'):
            build.validate_runtime_app(self.app('Invalid.app',['not','a','dictionary']))

    def test_metadata_aliases_are_rejected(self):
        target=self.app('Target.app',self.metadata(self.capabilities))
        alias=self.root/'Alias.app';alias.symlink_to(target,target_is_directory=True)
        contents=self.root/'ContentsAlias.app';contents.mkdir()
        (contents/'Contents').symlink_to(target/'Contents',target_is_directory=True)
        info_alias=self.root/'InfoAlias.app';(info_alias/'Contents').mkdir(parents=True)
        (info_alias/'Contents/Info.plist').symlink_to(target/'Contents/Info.plist')
        for app in (alias,contents,info_alias):
            with self.subTest(app=app),self.assertRaisesRegex(ValueError,'symbolic links'):
                build.validate_runtime_app(app)
        args=SimpleNamespace(platform='macos',update=None,dlc=None,mod=None,out=alias)
        with self.assertRaisesRegex(ValueError,'symbolic links'):
            build.build(args,self.root/'input')
        with self.assertRaisesRegex(ValueError,'symbolic links'):
            build.update_runtime(alias,work=self.root/'work',out=self.root/'Candidate.app')
        with self.assertRaisesRegex(ValueError,'symbolic links'):
            build.update_runtime(target,work=self.root/'work',out=alias)

    def test_update_rejects_conflicting_output_before_work(self):
        for index,(source_caps,destination_caps) in enumerate(((self.capabilities,{'KokiriHumanPreviewVersion':1}),
                                                              ({},self.capabilities),(self.capabilities,{}))):
            source=self.app(f'Source{index}.app',self.metadata(source_caps))
            destination=self.app(f'Output{index}.app',self.metadata(destination_caps))
            before=(source/'Contents/Info.plist').read_bytes(),(destination/'Contents/Info.plist').read_bytes()
            with patch.object(build,'ensure_shader_service',side_effect=AssertionError('unexpected heavy work')):
                with self.assertRaisesRegex(ValueError,'differ from the existing output'):
                    build.update_runtime(source,work=self.root/f'work{index}',out=destination)
            self.assertEqual(((source/'Contents/Info.plist').read_bytes(),(destination/'Contents/Info.plist').read_bytes()),before)

    def test_internal_metadata_cannot_add_keys_or_downgrade_private_output(self):
        app=self.app('Private.app',self.metadata(self.capabilities))
        for metadata in ({'ArbitraryKey':1},{'KokiriDevelopmentVersion':True},{}):
            with self.subTest(metadata=metadata),self.assertRaises(ValueError):
                build.package_app(self.root/'work',self.root/'tree',app,private_capabilities=metadata)

    def test_internal_private_metadata_cannot_mark_existing_ordinary_output(self):
        app=self.app('Ordinary.app',self.metadata())
        with self.assertRaisesRegex(ValueError,'differ from the existing output'):
            build.package_app(self.root/'work',self.root/'tree',app,private_capabilities=self.capabilities)

    def package(self,capabilities,*,update=False):
        """Exercise real packaging order with tiny resources and mocked proof/tools."""
        root=self.root;work=root/'work';tree=work/'oot';(work/'logs').mkdir(parents=True)
        runtime=work/'build/oot-native';runtime.parent.mkdir();runtime.write_bytes(b'new compiled runtime fixture')
        native=root/'native';native.mkdir();(native/'totk_xlate').write_bytes(b'translator fixture')
        translator=tree/'build/shader-service/totk_xlate';translator.parent.mkdir(parents=True)
        translator.write_bytes((native/'totk_xlate').read_bytes())
        output=root/'Candidate.app';source=None;source_bytes=None
        if update:
            source_metadata=self.metadata(capabilities);source_metadata['MNGGameDataFolder']=str(root/'original-game-data')
            source=self.app('Source.app',source_metadata)
            source_bytes=(source/'Contents/Info.plist').read_bytes()
        else:
            self.app(output.name,self.metadata(capabilities))   # no old executable is needed
        receipt=dict(prepared=False,artifact_sha256={'runtime_sha256':build.sha(runtime)})
        receipt_path=tree/'build/game-data/oot/preparation-receipt.json'
        def write_receipt(*args):
            receipt_path.parent.mkdir(parents=True,exist_ok=True)
            receipt_path.write_text(json.dumps(receipt));return receipt
        def clone(source,destination):
            source,destination=Path(source),Path(destination)
            self.assertIn(root,source.parents)
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(source.read_bytes() if source.is_file() else b'synthetic resource')
        def copy_tree(source,destination,**kwargs):
            source,destination=Path(source),Path(destination)
            self.assertIn(root,source.parents);destination.mkdir(parents=True,exist_ok=True)
            if (source/'preparation-receipt.json').is_file():clone(source/'preparation-receipt.json',destination/'preparation-receipt.json')
        seals=[]
        def command(argv,**kwargs):
            if argv[0]=='codesign':
                app=Path(argv[-1]);seals.append(plistlib.loads((app/'Contents/Info.plist').read_bytes()))
                if '--sign' in argv:
                    seal=app/'Contents/_CodeSignature/CodeResources';seal.parent.mkdir();seal.write_bytes(b'synthetic seal')
            elif argv[0] not in ('make','bash') and not str(argv[1]).endswith('make_opening_overlay.py'):
                raise AssertionError('unexpected tool invocation: '+str(argv))
            return subprocess.CompletedProcess(argv,0)
        def install(temporary,out):
            self.assertEqual(len(seals),2)
            if out.exists():out.rename(root/'replaced-placeholder')
            temporary.rename(out)
        helpers=SimpleNamespace(record_update_source=lambda *args:None,place_library_image=lambda *args,**kwargs:None,
                                install_app=install)
        values=dict(GAME=root/'source/engine',ensure_disk_space=lambda *args:None,catalog_context=lambda *args:{},
                    verify_shader_resources=lambda *args:None,shader_dirs=lambda *args:(root/'seed',root/'libraries',''),
                    resolve_lists=lambda *args:(root/'title.tsv',root/'manifest.tsv'),write_preparation_receipt=write_receipt,
                    clone_file=clone,build_helpers=lambda:helpers,imported_romfs=lambda *args:{},
                    exact_source_commit=lambda:'a'*40,contrib_folder=lambda:root/'contributions',
                    verify_staged_preparation_inputs=lambda *args:None,app_running=lambda *args:False,
                    ensure_shader_service=lambda *args:None,update_blocker=lambda *args:'',
                    ready_shader_service=lambda *args:native,sync_tree=lambda *args:None,shader_steps=lambda *args,**kwargs:None,
                    shader_mode=lambda *args:'full')
        with ExitStack() as stack:
            for key,value in values.items():stack.enter_context(patch.object(build,key,value))
            stack.enter_context(patch.object(build.shutil,'copytree',side_effect=copy_tree))
            stack.enter_context(patch.object(build.subprocess,'run',side_effect=command))
            if update:build.update_runtime(source,work=work,out=output)
            else:build.package_app(work,tree,output,'library',root/'game-data',mode='full')
        info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
        fingerprint=json.loads((work/'logs/package-output.json').read_text())
        self.assertEqual(fingerprint['info_sha256'],build.sha(output/'Contents/Info.plist'))
        self.assertEqual(seals,[info,info])
        self.assertNotIn('UnrelatedOldKey',info)
        self.assertEqual(info['CFBundleIdentifier'],build.RUNTIME_BUNDLE_ID)
        self.assertEqual(info['CFBundleExecutable'],build.RUNTIME_EXECUTABLE)
        self.assertFalse(info['KokiriPrepared'])   # synthetic resources prove metadata ordering only
        if update:self.assertEqual((source/'Contents/Info.plist').read_bytes(),source_bytes)
        self.assertLess(sum(path.stat().st_size for path in root.rglob('*') if path.is_file()),1<<20)
        return info

    def test_full_private_package_marks_before_signing_and_fingerprinting(self):
        info=self.package(self.capabilities)
        self.assertEqual({key:info[key] for key in self.capabilities},self.capabilities)

    def test_staged_private_update_preserves_both_markers_before_sealing(self):
        info=self.package(self.capabilities,update=True)
        self.assertEqual({key:info[key] for key in self.capabilities},self.capabilities)

    def test_ordinary_full_package_stays_unmarked(self):
        info=self.package({})
        for key in self.capabilities:self.assertNotIn(key,info)

    def test_ordinary_staged_update_stays_unmarked(self):
        info=self.package({},update=True)
        for key in self.capabilities:self.assertNotIn(key,info)


if __name__ == '__main__':
    unittest.main()
