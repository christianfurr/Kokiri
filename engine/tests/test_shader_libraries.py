"""A default-only rebuild must preserve verified libraries of recorded bindings."""
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest import mock

GAME=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('oot_libraries',GAME/'scripts/build_shader_libs.py')
libraries=importlib.util.module_from_spec(spec);spec.loader.exec_module(libraries)


class LibraryTests(unittest.TestCase):
    def runtime_cache(self, root, name='runtime', chain=None):
        cache = root/name
        (cache/'pipelines').mkdir(parents=True)
        (cache/'pipelines/identity.json').write_text(json.dumps(dict(
            chain=chain or libraries.CHAIN, schema=6, gpu='fixture', os='fixture')))
        return cache

    def variant(self, cache, content='kernel void patched() {}'):
        folder = cache/'variants'
        folder.mkdir(exist_ok=True)
        source = folder/(hashlib.sha256(content.encode()).hexdigest()+'.metal')
        source.write_text(content)
        return source

    def test_patched_variants_are_compiled_and_recorded_without_importing_base_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed = root/'seed'
            seed.mkdir()
            base = seed/('a'*64+'-'+'b'*12+'_b.metal')
            base.write_text('kernel void base() {}')
            runtime = self.runtime_cache(root)
            patched = self.variant(runtime)
            # Base runtime translations are not trusted without seed request verification.
            (runtime/'unverified_b.metal').write_text('kernel void unverified() {}')
            (runtime/'unverified_b.json').write_text(json.dumps(dict(chain=libraries.CHAIN)))
            out = root/'libs'
            compiled = []

            def compile_fixture(command, **kwargs):
                source = Path(command[-1])
                compiled.append(source)
                Path(command[command.index('-o')+1]).write_bytes(b'MTLB'+source.read_bytes())
                return subprocess.CompletedProcess(command, 0, '', '')

            with mock.patch.object(sys, 'argv', ['build_shader_libs.py', '--cache', str(seed),
                                   '--variant-cache', str(runtime), '--out', str(out)]), \
                 mock.patch.object(libraries, 'metal_compiler', return_value=('fixture-metal', 'fixture', {})), \
                 mock.patch.object(libraries, 'GameSlot', return_value=contextlib.nullcontext()), \
                 mock.patch.object(libraries.subprocess, 'run', side_effect=compile_fixture):
                with self.assertRaises(SystemExit) as result:
                    libraries.main()
                self.assertEqual(result.exception.code, 0)
            self.assertCountEqual(compiled, [base, patched])
            manifest = json.loads((out/'libraries-manifest.json').read_text())
            self.assertTrue(manifest['complete'])
            self.assertEqual(manifest['sources'][patched.name], patched.stem)
            self.assertIn(patched.stem+'.metallib', manifest['files'])
            provenance = manifest['variant_caches'][0]
            self.assertEqual(provenance['identity']['chain'], libraries.CHAIN)
            self.assertEqual(provenance['identity_sha256'], libraries.digest(runtime/'pipelines/identity.json'))
            self.assertEqual(provenance['sources'], {patched.name: patched.stem})

    def test_old_chain_is_rejected_even_with_valid_source_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = self.runtime_cache(Path(folder), chain='oot-native-v23-txd-derivative-order')
            self.variant(runtime)
            with self.assertRaisesRegex(ValueError, 'incompatible patched-variant cache'):
                libraries.recorded_variants([runtime])

    def test_reflection_disagreement_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = self.runtime_cache(Path(folder))
            self.variant(runtime)
            (runtime/'fixture_b.json').write_text(json.dumps(dict(chain='old-chain')))
            with self.assertRaisesRegex(ValueError, 'incompatible cached reflection'):
                libraries.recorded_variants([runtime])

    def test_tampered_source_or_non_hash_name_is_rejected(self):
        for tamper in (True, False):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as folder:
                runtime = self.runtime_cache(Path(folder))
                patched = self.variant(runtime)
                if tamper:
                    patched.write_text('kernel void changed() {}')
                else:
                    patched.rename(patched.with_name('unverified.metal'))
                with self.assertRaisesRegex(ValueError, 'filename does not match source hash'):
                    libraries.recorded_variants([runtime])

    def test_repeated_caches_deduplicate_and_empty_cache_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.runtime_cache(root, 'first')
            second = self.runtime_cache(root, 'second')
            empty = self.runtime_cache(root, 'empty')
            source = self.variant(first)
            self.variant(second)
            sources, provenance = libraries.recorded_variants([first, second, empty])
            self.assertEqual(set(sources), {source.name})
            self.assertEqual(len(provenance), 3)
            self.assertEqual(provenance[-1]['sources'], {})

    def test_same_filename_different_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.runtime_cache(root, 'first')
            second = self.runtime_cache(root, 'second')
            source = self.variant(first)
            folder = second/'variants'
            folder.mkdir()
            (folder/source.name).write_text('kernel void different() {}')
            with self.assertRaisesRegex(ValueError, 'filename does not match source hash'):
                libraries.recorded_variants([first, second])

    def test_default_only_rebuild_keeps_verified_recorded_library(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'cache';cache.mkdir();out=root/'libs';out.mkdir()
            source=cache/'fixture_b.metal';source.write_text('kernel void main0() {}')
            base=out/(libraries.digest(source)+'.metallib');base.write_bytes(b'default fixture')
            recorded=out/('a'*64+'.metallib');recorded.write_bytes(b'recorded binding fixture')
            damaged=out/('b'*64+'.metallib');damaged.write_bytes(b'changed after verification')
            identity=' '.join(['fixture',*libraries.METAL_FLAGS])
            (out/'compiler.txt').write_text(identity)
            expected={p.name:libraries.digest(p)for p in (base,recorded)}
            (out/'libraries-manifest.json').write_text(json.dumps(dict(
                compiler=identity,files={**expected,damaged.name:'0'*64})))
            with mock.patch.object(sys,'argv',['build_shader_libs.py','--cache',str(cache),'--out',str(out)]), \
                 mock.patch.object(libraries,'metal_compiler',return_value=('unused','fixture',{})), \
                 mock.patch.object(libraries,'GameSlot',return_value=contextlib.nullcontext()), \
                 mock.patch.object(libraries.subprocess,'run') as compile_call:
                with self.assertRaises(SystemExit) as result:
                    libraries.main()
                self.assertEqual(result.exception.code,0)
                compile_call.assert_not_called()
            manifest=json.loads((out/'libraries-manifest.json').read_text())
            self.assertTrue(manifest['complete'])
            self.assertEqual(manifest['files'],expected)


if __name__=='__main__':
    unittest.main()
