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
toolchain=sys.modules['metal_toolchain']


class LibraryTests(unittest.TestCase):
    def qualified_observation(self):
        return dict(qualified=True, backend='metal', version='fixture',
                    observation_schema=2,
                    loader_environment_policy='reject-nonempty-DYLD',
                    executable_sha256='a'*64, effective_target='air64-apple-macosx26.0',
                    effective_flags=libraries.METAL_FLAGS, sdk_mode='compiler-default-resource-headers',
                    resource_headers=dict(content_sha256='c'*64),
                    host_identity=dict(os_build='fixture-build', machine='arm64', kernel_release='fixture-kernel'),
                    tool_components=[dict(role=role, executable_sha256=digest*64, dependencies=[],
                                          path='/private/fixture-'+role, size=100)
                                     for role, digest in [('driver', 'a'), ('frontend', 'b'), ('linker', 'c')]],
                    required_files=[dict(role='selected-invocation-input', sha256='d'*64,
                                         path='/private/libmetal_rt_osx.a', size=100)],
                    effective_invocations=[['/private/fixture-frontend', '-cc1', '-triple', 'air64-apple-macosx26.0',
                                            '-o', '<intermediate.air>', '<probe-dir>/identity.metal'],
                                           ['/private/fixture-linker', '<intermediate.air>', '/private/libmetal_rt_osx.a',
                                            '-o', '<probe-dir>/identity.partial']])

    def test_compiler_observation_hashes_selected_headers_and_actual_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            compiler = root/'metal'
            compiler.write_bytes(b'fixture compiler')
            frontend, linker, archive, dependency = (root/name for name in ('metal-frontend', 'air-lld', 'libmetal.a', 'libfixture.dylib'))
            for component in (frontend, linker, archive, dependency):
                component.write_bytes(('fixture '+component.name).encode())
            resource = root/'resource'
            headers = resource/'include/metal'
            headers.mkdir(parents=True)
            header = headers/'metal_stdlib'
            header.write_text('fixture header')
            def driver(command, **kwargs):
                if '-###' in command:
                    self.assertNotIn('-c', command)
                    plan = (f'"{frontend}" "-cc1" "-triple" "air64-apple-macosx26.0" "-resource-dir" "{resource}" '
                            f'"-o" "/tmp/identity-abcd.air" "{command[-1]}"\n'
                            f'"{linker}" "-o" "{command[command.index("-o")+1]}" "/tmp/identity-abcd.air" "{archive}"')
                    return subprocess.CompletedProcess(command, 0, '', plan)
                if command[0] == 'otool':
                    dependencies = [str(dependency)] if Path(command[-1]).resolve() == frontend.resolve() else ['/usr/lib/libSystem.B.dylib']
                    text = str(command[-1])+':\n'+''.join('\t'+name+' (compatibility version 1.0.0, current version 1.0.0)\n' for name in dependencies)
                    return subprocess.CompletedProcess(command, 0, text, '')
                return subprocess.CompletedProcess(command, 0, 'fixture-sdk', '')

            with mock.patch.object(toolchain.subprocess, 'run', side_effect=driver):
                first = toolchain.compiler_observation(str(compiler), 'same-version', {}, ['-safe'])
                header.write_text('changed header')
                second = toolchain.compiler_observation(str(compiler), 'same-version', {}, ['-safe'])
                frontend.write_bytes(b'changed frontend')
                third = toolchain.compiler_observation(str(compiler), 'same-version', {}, ['-safe'])
                linker.write_bytes(b'changed linker')
                fourth = toolchain.compiler_observation(str(compiler), 'same-version', {}, ['-safe'])
                dependency.write_bytes(b'changed dynamically loaded library')
                fifth = toolchain.compiler_observation(str(compiler), 'same-version', {}, ['-safe'])
            self.assertEqual(first['executable_sha256'], hashlib.sha256(compiler.read_bytes()).hexdigest())
            self.assertEqual(first['resource_headers']['files'], 1)
            self.assertNotEqual(libraries.compiler_context_key(first), libraries.compiler_context_key(second))
            self.assertEqual([component['role'] for component in first['tool_components']], ['driver', 'frontend', 'linker'])
            self.assertEqual(first['required_files'][0]['sha256'], libraries.digest(archive))
            self.assertNotEqual(libraries.compiler_context_key(second), libraries.compiler_context_key(third))
            self.assertNotEqual(libraries.compiler_context_key(third), libraries.compiler_context_key(fourth))
            self.assertNotEqual(libraries.compiler_context_key(fourth), libraries.compiler_context_key(fifth))
            moved = dict(first, path='/different/path', driver_plan='different diagnostics',
                         driver_plan_sha256='ignored diagnostics')
            self.assertEqual(libraries.compiler_context_key(first), libraries.compiler_context_key(moved))

    def test_same_version_changed_binary_target_or_headers_recompiles(self):
        changes = [dict(executable_sha256='b'*64), dict(effective_target='air64-apple-macosx27.0'),
                   dict(resource_headers=dict(content_sha256='d'*64))]
        for index in (1, 2):
            components = self.qualified_observation()['tool_components']
            components[index]['executable_sha256'] = 'f'*64
            changes.append(dict(tool_components=components))
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache = root/'cache'
                cache.mkdir()
                source = cache/'fixture_b.metal'
                source.write_text('kernel void main0() {}')
                out = root/'libs'
                out.mkdir()
                library = out/(libraries.digest(source)+'.metallib')
                library.write_bytes(b'old library')
                observation = self.qualified_observation()
                old_key = libraries.compiler_context_key(observation)
                old_identity = ' '.join(['fixture', *libraries.METAL_FLAGS, 'context-sha256='+old_key])
                (out/'compiler.txt').write_text(old_identity)
                (out/'libraries-manifest.json').write_text(json.dumps(dict(
                    compiler=old_identity, compiler_context_sha256=old_key,
                    compiler_observation=observation, files={library.name:libraries.digest(library)})))
                changed = dict(observation, **change)
                if 'executable_sha256' in change:
                    changed['tool_components'] = [dict(item) for item in observation['tool_components']]
                    changed['tool_components'][0]['executable_sha256'] = change['executable_sha256']
                if 'effective_target' in change:
                    changed['effective_invocations'] = [list(argv) for argv in observation['effective_invocations']]
                    changed['effective_invocations'][0][3] = change['effective_target']

                def compile_fixture(command, **kwargs):
                    Path(command[command.index('-o')+1]).write_bytes(b'new library')
                    return subprocess.CompletedProcess(command, 0, '', '')

                with mock.patch.object(sys, 'argv', ['build_shader_libs.py', '--cache', str(cache), '--out', str(out)]), \
                     mock.patch.object(libraries, 'metal_compiler', return_value=('unused', 'fixture', {})), \
                     mock.patch.object(libraries, 'compiler_observation', return_value=changed), \
                     mock.patch.object(libraries, 'GameSlot', return_value=contextlib.nullcontext()), \
                     mock.patch.object(libraries.subprocess, 'run', side_effect=compile_fixture) as compile_call:
                    with self.assertRaises(SystemExit) as result:
                        libraries.main()
                    self.assertEqual(result.exception.code, 0)
                    compile_call.assert_called_once()
                manifest = json.loads((out/'libraries-manifest.json').read_text())
                self.assertNotEqual(manifest['compiler_context_sha256'], old_key)
                self.assertEqual(library.read_bytes(), b'new library')

    def test_qualified_context_cannot_omit_frontend_linker_or_dependency_identity(self):
        for role in ('frontend', 'linker'):
            observation = self.qualified_observation()
            observation['tool_components'] = [item for item in observation['tool_components'] if item['role'] != role]
            with self.assertRaisesRegex(ValueError, 'component or host identities'):
                libraries.compiler_context_key(observation)
        observation = self.qualified_observation()
        observation['tool_components'][1]['dependencies'] = [dict(binding='hashed-file')]
        with self.assertRaisesRegex(ValueError, 'dependency lacks content identity'):
            libraries.compiler_context_key(observation)

    def test_library_driver_plan_must_include_linker(self):
        with self.assertRaisesRegex(ValueError, 'selected linker'):
            toolchain.driver_commands('"/fixture/metal" "-cc1" "-c"')

    def test_loader_overrides_are_rejected_before_driver_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            compiler = Path(folder)/'metal'
            compiler.write_bytes(b'fixture compiler')
            for variable in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'DYLD_FRAMEWORK_PATH'):
                with self.subTest(variable=variable), mock.patch.object(toolchain.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'nonempty DYLD_'):
                        toolchain.compiler_observation(str(compiler), 'fixture', {variable: '/fixture'}, ['-safe'])
                    run.assert_not_called()

    def test_qualified_loader_policy_is_required_and_bound_in_reuse_key(self):
        for policy in (None, 'unobserved'):
            observation = self.qualified_observation()
            if policy is None:
                observation.pop('loader_environment_policy')
            else:
                observation['loader_environment_policy'] = policy
            with self.assertRaisesRegex(ValueError, 'loader environment policy'):
                libraries.compiler_context_key(observation)
        with mock.patch.object(toolchain.json, 'dumps', wraps=json.dumps) as encode:
            key = libraries.compiler_context_key(self.qualified_observation())
        context = encode.call_args.args[0]
        self.assertEqual(context['loader_environment_policy'], 'reject-nonempty-DYLD')
        context_without_policy = {name: value for name, value in context.items() if name != 'loader_environment_policy'}
        previous_key = hashlib.sha256(json.dumps(context_without_policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertNotEqual(key, previous_key)

    def test_recorded_working_directory_is_conservatively_bound(self):
        first = self.qualified_observation()
        second = self.qualified_observation()
        first['effective_invocations'][0].append('-fcoverage-compilation-dir=/first/checkout')
        second['effective_invocations'][0].append('-fcoverage-compilation-dir=/relocated/checkout')
        self.assertNotEqual(libraries.compiler_context_key(first), libraries.compiler_context_key(second))

    def test_qualified_context_rejects_missing_static_input_or_invocation_inventory(self):
        for field, value in [('required_files', []), ('effective_invocations', None)]:
            observation = self.qualified_observation()
            observation[field] = value
            with self.assertRaises(ValueError):
                libraries.compiler_context_key(observation)
        observation = self.qualified_observation()
        observation['required_files'][0]['path'] = '/private/different.a'
        with self.assertRaisesRegex(ValueError, 'selected input inventory incomplete'):
            libraries.compiler_context_key(observation)

    def test_qualified_context_rejects_role_mismatch_or_unowned_dependency_loader(self):
        observation = self.qualified_observation()
        observation['effective_invocations'][0][0] = '/private/unobserved-frontend'
        with self.assertRaisesRegex(ValueError, 'executable roles'):
            libraries.compiler_context_key(observation)
        observation = self.qualified_observation()
        observation['tool_components'][0]['dependencies'] = [dict(
            loader_sha256='f'*64, install_name='/usr/lib/libSystem.B.dylib',
            binding='os-build-system-component', os_build='fixture-build')]
        with self.assertRaisesRegex(ValueError, 'loader or install name'):
            libraries.compiler_context_key(observation)

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
            observation=libraries.compiler_observation('unused','fixture',{},libraries.METAL_FLAGS)
            context=libraries.compiler_context_key(observation)
            self.assertFalse(observation['qualified'])
            identity=' '.join(['fixture',*libraries.METAL_FLAGS,'context-sha256='+context])
            (out/'compiler.txt').write_text(identity)
            expected={p.name:libraries.digest(p)for p in (base,recorded)}
            (out/'libraries-manifest.json').write_text(json.dumps(dict(
                compiler=identity,compiler_context_sha256=context,
                compiler_observation=observation,files={**expected,damaged.name:'0'*64})))
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


    def test_interrupted_compile_resumes_from_verified_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'cache';cache.mkdir();out=root/'libs'
            for n in range(260):
                (cache/f'fixture{n:04d}_b.metal').write_text(f'kernel void main{n}() {{}}')
            calls=[0]
            def compile_one(command,**kwargs):
                calls[0]+=1
                if calls[0]==251:raise RuntimeError('simulated interruption')
                partial=Path(command[command.index('-o')+1]);partial.write_bytes(Path(command[-1]).read_bytes()+b' compiled')
                return libraries.subprocess.CompletedProcess(command,0,'','')
            argv=['build_shader_libs.py','--cache',str(cache),'--out',str(out),'--jobs','1']
            with mock.patch.object(sys,'argv',argv), \
                 mock.patch.object(libraries,'metal_compiler',return_value=('unused','fixture',{})), \
                 mock.patch.object(libraries,'GameSlot',return_value=contextlib.nullcontext()), \
                 mock.patch.object(libraries.subprocess,'run',side_effect=compile_one):
                with self.assertRaisesRegex(RuntimeError,'interruption'):libraries.main()
                progress=json.loads((out/'libraries-manifest.json').read_text())
                self.assertFalse(progress['complete']);self.assertEqual(len(progress['files']),250)
                calls[0]=0
                with self.assertRaises(SystemExit) as done:libraries.main()
                self.assertEqual(done.exception.code,0)
                self.assertEqual(calls[0],10)
                final=json.loads((out/'libraries-manifest.json').read_text())
                self.assertTrue(final['complete']);self.assertEqual(len(final['files']),260)


if __name__=='__main__':
    unittest.main()
