#!/usr/bin/env python3
"""Private diagnostic-app update/relaunch test. Never runs the game or uses its data."""
import argparse
import base64
import ctypes
import errno
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module('runtime_test_client', 'runtime_update.py')
packager = module('runtime_test_packager', 'prepare_runtime_source.py')
command_journal = None

C_FIXTURE = r'''
#include <mach-o/dyld.h>
#include <libproc.h>
#include <sys/proc_info.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(void) {
  char executable[4096], base[4096], path[8192], marker[4096], version[64];
  uint32_t size = sizeof(executable);
  if (_NSGetExecutablePath(executable, &size)) return 2;
  snprintf(base, sizeof(base), "%s", executable);
  char *slash = strrchr(base, '/'); if (!slash) return 3; *slash = 0;
  snprintf(path, sizeof(path), "%s/../Resources/marker-path.txt", base);
  FILE *file = fopen(path, "r"); if (!file) return 4;
  if (!fgets(marker, sizeof(marker), file)) return 5; fclose(file);
  marker[strcspn(marker, "\n")] = 0;
  snprintf(path, sizeof(path), "%s/../Resources/fixture-version.txt", base);
  file = fopen(path, "r"); if (!file) return 6;
  if (!fgets(version, sizeof(version), file)) return 7; fclose(file);
  version[strcspn(version, "\n")] = 0;
  file = fopen(marker, "w"); if (!file) return 8;
  struct proc_bsdinfo identity;
  if (proc_pidinfo(getpid(), PROC_PIDTBSDINFO, 0, &identity, sizeof(identity)) != sizeof(identity)) return 9;
  fprintf(file, "%s\n%d\n%s\n%llu\n%llu\n", version, getpid(), executable,
          identity.pbi_start_tvsec, identity.pbi_start_tvusec); fclose(file);
  sleep(30); return 0;
}
'''

# The source archive contains only this diagnostic builder, notices and a test
# chain. Its counters and data are synthetic. It cannot prepare or run the game.
BUILDER = r'''
import argparse, hashlib, json, plistlib, shutil, subprocess, sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--rebuild');p.add_argument('--out');p.add_argument('--work');p.add_argument('--jobs');a=p.parse_args()
source=Path(__file__).resolve().parents[1]
record=json.loads((source/'kokiri-source-release.json').read_text())
sys.path.insert(0,str(source/'engine/scripts'))
from metal_toolchain import compiler_context_key
observation=json.loads((source/'engine/diagnostic-compiler-observation.json').read_text())
compiler_context=compiler_context_key(observation)
app=Path(a.out);shutil.copytree(a.rebuild,app)
resources=app/'Contents/Resources';(resources/'fixture-version.txt').write_text('updated-fixture\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
build=resources/'totk/build';artifacts={}
executable=app/'Contents/MacOS/KokiriGame';artifacts['runtime_sha256']=sha(executable)
for name,folder,filename in [('seed_manifest_sha256','shader-seed','seed-manifest.json'),('libraries_manifest_sha256','shader-libs','libraries-manifest.json'),('pipeline_manifest_sha256','pipelines','compute-manifest.json')]:
 target=build/folder;target.mkdir(parents=True,exist_ok=True);payload=target/'fixture-payload.txt';payload.write_text('synthetic-data-only\n');manifest=target/filename;metadata={'files':{payload.name:sha(payload)}}
 if folder=='shader-libs':metadata.update(compiler_context_schema=2,compiler_context_sha256=compiler_context,compiler_observation=observation)
 if folder=='shader-seed':metadata['runtime_sha256']=artifacts['runtime_sha256']
 manifest.write_text(json.dumps(metadata));artifacts[name]=sha(manifest)
index=build/'pipelines/pipelines-fixture.tsv';index.write_text('synthetic-index\n');artifacts['pipeline_index_sha256']=sha(index)
counts={'requested':1,'completed':1,'failed':0}
receipt={'schema':'kokiri-preparation-receipt-v1','mode':'full','prepared':True,'errors':[],
 'identity':{'source_commit':record['source_commit'],'chain':record['shader_chain'],'runtime_sha256':sha(executable),'seed_runtime_sha256':sha(executable),'runtime_hash_scope':'pre-seal build executable; final signed bytes require an external package fingerprint','translation_context_sha256':'c'*64,'translator_sha256':'d'*64,'gpu_architecture':'fixture'},
 'variants':{'default':counts,'listed':{'requested':0,'completed':0,'failed':0},'unique_completed':1},
 'libraries':counts,'pipelines':dict(counts,write_failed=0,unaccounted=0),'artifact_sha256':artifacts,
 'compiler_context_schema':2,'compiler_context_sha256':compiler_context,'compiler_observation':observation}
path=build/'game-data/oot/preparation-receipt.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(receipt))
info_path=app/'Contents/Info.plist';info=plistlib.loads(info_path.read_bytes());info.update(KokiriPrepared=True,KokiriShaders='full',KokiriSourceCommit=record['source_commit'],KokiriPreparationReceiptSHA256=sha(path),KokiriBuildRuntimeSHA256=artifacts['runtime_sha256']);info_path.write_bytes(plistlib.dumps(info))
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True)
fingerprint={'schema':'kokiri-package-output-v1','app':str(app),'build_runtime_sha256':artifacts['runtime_sha256'],'signed_runtime_sha256':sha(executable),'info_sha256':sha(info_path),'code_resources_sha256':sha(app/'Contents/_CodeSignature/CodeResources'),'preparation_receipt_sha256':sha(path)}
logs=Path(a.work)/'logs';logs.mkdir(exist_ok=True);(logs/'package-output.json').write_text(json.dumps(fingerprint))
'''


def compiler_observation_fixture():
    """Structural test data, never evidence of observing a real compiler."""
    base = '/private/kokiri-updater-fixture'
    driver, frontend, linker = (base + '/' + role for role in ('driver', 'frontend', 'linker'))
    archive = base + '/libmetal_rt_osx.a'
    return dict(
        observation_schema=2, qualified=True, backend='metal', version='synthetic fixture',
        path=driver, executable_sha256='8' * 64,
        effective_flags=['-mmacosx-version-min=26.0', '-fmetal-math-mode=safe', '-fpreserve-invariance', '-fwrapv'],
        effective_target='air64-apple-macosx26.0.0', sdk_mode='compiler-default-resource-headers',
        loader_environment_policy='reject-nonempty-DYLD',
        resource_headers=dict(path=base + '/headers', content_sha256='7' * 64, files=1, bytes=1),
        host_identity=dict(os_build='synthetic-fixture-os', machine='arm64', kernel_release='synthetic-fixture-kernel'),
        tool_components=[
            dict(role='driver', path=driver, size=100, executable_sha256='8' * 64, dependencies=[
                dict(loader_sha256='8' * 64, install_name='/usr/lib/libSystem.B.dylib',
                     binding='os-build-system-component', os_build='synthetic-fixture-os')]),
            dict(role='frontend', path=frontend, size=200, executable_sha256='6' * 64, dependencies=[
                dict(loader_sha256='6' * 64, install_name='@rpath/libCompiler.dylib', binding='hashed-file',
                     sha256='5' * 64, path=base + '/libCompiler.dylib', size=50)]),
            dict(role='linker', path=linker, size=300, executable_sha256='4' * 64, dependencies=[])],
        required_files=[dict(role='selected-invocation-input', path=archive, size=123, sha256='3' * 64)],
        effective_invocations=[
            [frontend, '-cc1', '-triple', 'air64-apple-macosx26.0.0', '-fwrapv', '-fpreserve-invariance',
             '-o', '<intermediate.air>', '<probe-dir>/identity.metal'],
            [linker, '<intermediate.air>', archive, '-o', '<probe-dir>/identity.partial']])


def run(arguments, cwd=None):
    if command_journal is not None:
        with command_journal.open('a') as journal:
            journal.write(json.dumps(dict(command=[str(value) for value in arguments], cwd=str(cwd or Path.cwd()),
                                          started_at_utc=datetime.now(timezone.utc).isoformat())) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
    return subprocess.check_output([str(value) for value in arguments], cwd=cwd, stderr=subprocess.STDOUT, timeout=20)


class ProcBSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'pjobc', 'tdev', 'tpgid', 'nice')]
    _fields_ += [('started_sec', ctypes.c_uint64), ('started_usec', ctypes.c_uint64)]


def process_identity(pid):
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    first, second = ProcBSDInfo(), ProcBSDInfo()
    def snapshot(info):
        ctypes.set_errno(0)
        result = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if result == 0 and ctypes.get_errno() == errno.ESRCH:
            return False
        runtime.require(result == ctypes.sizeof(info), 'Cannot verify full diagnostic process birth identity')
        return True
    if not snapshot(first):
        return None
    path = ctypes.create_string_buffer(4096)
    ctypes.set_errno(0)
    if library.proc_pidpath(pid, path, len(path)) <= 0:
        if ctypes.get_errno() == errno.ESRCH:
            return None
        raise ValueError('Cannot verify diagnostic executable path')
    if not snapshot(second):
        return None
    def birth(info):
        return info.pid, info.uid, info.started_sec, info.started_usec
    runtime.require(birth(first) == birth(second) and first.pid == pid and first.started_sec > 0,
                    'Diagnostic process identity changed during observation')
    return dict(pid=pid, uid=first.uid, started_sec=first.started_sec,
                started_usec=first.started_usec, executable=os.fsdecode(path.value))


def stop_owned(identity):
    pid = identity['pid']
    actual = process_identity(pid)
    if actual is None:
        return
    runtime.require(actual == identity and actual['uid'] == os.getuid(),
                    'Diagnostic PID/start identity changed; no signal sent')
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        actual = process_identity(pid)
        if actual is None or actual != identity:
            return  # The original exited. Never signal a replacement process.
        time.sleep(0.05)
    raise ValueError('Diagnostic process did not exit within its stop bound')


def observe(marker, expected, app, owned):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.is_file():
            rows = marker.read_text().splitlines()
            if len(rows) == 5 and rows[0] == expected and all(rows[index].isdigit() for index in (1, 3, 4)):
                pid = int(rows[1])
                executable = app / 'Contents/MacOS/KokiriGame'
                identity = process_identity(pid)
                runtime.require(identity and identity['executable'] == str(executable)
                                and rows[2] == str(executable) and identity['started_sec'] == int(rows[3])
                                and identity['started_usec'] == int(rows[4]) and identity['uid'] == os.getuid(),
                                'Launch marker does not identify the selected diagnostic process/start')
                runtime.atomic_json(marker.with_name('observed-' + expected + '.json'), identity)
                owned.append(identity)
                return identity
        time.sleep(0.05)
    raise ValueError('Diagnostic app relaunch was not observed')


def selftest(output):
    global command_journal
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    output = Path(output).resolve()
    runtime.require(not output.exists() and not output.is_relative_to(runtime.ROOT), 'Use a fresh external private test folder')
    runtime.load_trusted_compiler_validator()
    runtime.game_closed()
    output.mkdir(mode=0o700)
    command_journal = output / 'commands.jsonl'
    runtime.atomic_json(output / 'invocation.json', dict(arguments=sys.argv, cwd=str(Path.cwd()),
                        python=sys.executable, harness_sha256=runtime.sha(Path(__file__)),
                        updater_sha256=runtime.sha(Path(__file__).with_name('runtime_update.py')),
                        packager_sha256=runtime.sha(Path(__file__).with_name('prepare_runtime_source.py'))))
    marker = output / 'launch-marker.txt'
    app = output / 'baseline/Kokiri Game.app'
    mac, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
    mac.mkdir(parents=True); resources.mkdir()
    source = output / 'diagnostic.c'; source.write_text(C_FIXTURE)
    run(['/usr/bin/xcrun', 'clang', '-Os', source, '-lproc', '-o', mac / 'KokiriGame'])
    (resources / 'marker-path.txt').write_text(str(marker) + '\n')
    (resources / 'fixture-version.txt').write_text('baseline-fixture\n')
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier=runtime.PRODUCT, CFBundleExecutable='KokiriGame', CFBundleName='Kokiri Update Diagnostic',
        CFBundlePackageType='APPL', CFBundleVersion='1', LSBackgroundOnly=True, KokiriGameUpdate='131072')))
    run(['/usr/bin/codesign', '--force', '--sign', '-', app])
    original = runtime.inspect_app(app)
    repository = output / 'fixture-source'; repository.mkdir()
    files = {'LICENSE':(runtime.ROOT/'LICENSE').read_text(),
             'THIRD_PARTY_NOTICES.md':(runtime.ROOT/'THIRD_PARTY_NOTICES.md').read_text(),
             'engine/build.py':BUILDER, 'engine/scripts/preparation_receipt.py':'# synthetic receipt fixture; no game preparation\n',
             'engine/scripts/metal_toolchain.py':runtime.TRUSTED_COMPILER_HELPER.read_text(),
             'engine/diagnostic-compiler-observation.json':json.dumps(compiler_observation_fixture()),
             'engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h':'#define DMSH_CHAIN "oot-native-v28-updater-fixture" /* game: oot */\n'}
    for name, content in files.items():
        path = repository / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
    run(['/usr/bin/git','init','-q',repository]);run(['/usr/bin/git','-C',repository,'add','.'])
    run(['/usr/bin/git','-C',repository,'-c','user.name=Kokiri Diagnostic','-c','user.email=diagnostic@invalid','commit','-qm','Diagnostic source fixture'])
    key = output / 'ephemeral-seed'
    key.write_bytes(base64.b64encode(Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())))
    key.chmod(0o600)
    owned = []
    try:
        delivery = output / 'delivery'
        record = packager.prepare(repository, delivery, 1, 'https://updates.invalid/fixture.zip', key)
        manifest, signature, archive = delivery / 'manifest.json', delivery / 'manifest.json.sig', delivery / 'runtime-source.zip'
        public = record['public_key']
        work = output / 'original-work';work.mkdir();(work/'preserved-cache.txt').write_text('preserved-fixture\n')
        with runtime.store_lock(output/'versions') as store:
            staged = runtime.stage(store,manifest,signature,public,archive,app,work,sys.executable)
            runtime.require(staged['candidate']['executable_sha256'] != staged['candidate']['build_runtime_sha256'],
                            'Fixture did not demonstrate distinct pre-seal and final signed byte hashes')
            runtime.require(runtime.state(store)['active'] is None, 'Stage selected an app prematurely')
            activated = runtime.activate(store,1,public)
            selected = Path(activated['active']['app'])
            runtime.relaunch(activated['active']);identity = observe(marker,'updated-fixture',selected,owned)
            stop_owned(identity);owned.remove(identity);marker.unlink()
            rolled = runtime.rollback(store)
            runtime.relaunch(rolled['active']);identity=observe(marker,'baseline-fixture',app,owned)
            stop_owned(identity);owned.remove(identity)
            runtime.require(runtime.inspect_app(app)==original, 'Original diagnostic app changed')
            runtime.require((work/'preserved-cache.txt').read_text()=='preserved-fixture\n','Original workspace changed')
            runtime.require(runtime.state(store)['highest_version']==1,'Rollback lowered replay protection')
        result = dict(schema=1, tested_at_utc=datetime.now(timezone.utc).isoformat(),
                      fixture_only=True, synthetic_compiler_observation=True,
                      game_assets_used=False, game_launched=False, production_ready=False,
                      source_manifest_sha256=runtime.sha(manifest), source_archive_sha256=runtime.sha(archive),
                      baseline=original, candidate=staged['candidate'],
                      checks=['real signed source package','real strict code-signature verification','distinct pre-seal versus final signed byte hashes',
                              'private staged local build','atomic activation','selected diagnostic app relaunch observed',
                              'rollback diagnostic app relaunch observed','original app/workspace preserved','replay watermark retained'])
        runtime.atomic_json(output/'verification.json',result)
        return result
    finally:
        key.unlink(missing_ok=True)
        for identity in owned:
            stop_owned(identity)
        # Unobserved or restarted instances are never signalled. A failed
        # observation may require waiting for the fixture's 30-second self-exit
        # and verifying that exit before releasing the exclusive test slot.


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    def deadline(_signal, _frame):
        raise TimeoutError('Diagnostic test exceeded its 60-second overall bound')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(60)
    try:
        print(json.dumps(selftest(args.output),sort_keys=True))
    except Exception as error:
        parser.exit(1,'Diagnostic update test failed: '+str(error)+'\n')
    finally:
        signal.alarm(0)
