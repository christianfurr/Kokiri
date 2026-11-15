#!/usr/bin/env python3
"""Private diagnostic-app update/relaunch test. Never runs the game or uses its data."""
import argparse
import base64
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

C_FIXTURE = r'''
#include <mach-o/dyld.h>
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
  fprintf(file, "%s\n%d\n%s\n", version, getpid(), executable); fclose(file);
  sleep(30); return 0;
}
'''

# The source archive contains only this diagnostic builder, notices and a test
# chain. Its counters and data are synthetic. It cannot prepare or run the game.
BUILDER = r'''
import argparse, hashlib, json, plistlib, shutil, subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--rebuild');p.add_argument('--out');p.add_argument('--work');p.add_argument('--jobs');a=p.parse_args()
source=Path(__file__).resolve().parents[1]
record=json.loads((source/'kokiri-source-release.json').read_text())
app=Path(a.out);shutil.copytree(a.rebuild,app)
resources=app/'Contents/Resources';(resources/'fixture-version.txt').write_text('updated-fixture\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
build=resources/'totk/build';artifacts={}
for name,folder,filename in [('seed_manifest_sha256','shader-seed','seed-manifest.json'),('libraries_manifest_sha256','shader-libs','libraries-manifest.json'),('pipeline_manifest_sha256','pipelines','compute-manifest.json')]:
 target=build/folder;target.mkdir(parents=True,exist_ok=True);payload=target/'fixture-payload.txt';payload.write_text('synthetic-data-only\n');manifest=target/filename;manifest.write_text(json.dumps({'files':{payload.name:sha(payload)}}));artifacts[name]=sha(manifest)
index=build/'pipelines/pipelines-fixture.tsv';index.write_text('synthetic-index\n');artifacts['pipeline_index_sha256']=sha(index)
executable=app/'Contents/MacOS/KokiriGame';artifacts['runtime_sha256']=sha(executable)
counts={'requested':1,'completed':1,'failed':0}
receipt={'schema':'kokiri-preparation-receipt-v1','mode':'full','prepared':True,'errors':[],
 'identity':{'source_commit':record['source_commit'],'chain':record['shader_chain'],'runtime_sha256':sha(executable),'runtime_hash_scope':'pre-seal build executable; final signed bytes require an external package fingerprint','translation_context_sha256':'c'*64,'translator_sha256':'d'*64,'gpu_architecture':'fixture'},
 'variants':{'default':counts,'listed':{'requested':0,'completed':0,'failed':0},'unique_completed':1},
 'libraries':counts,'pipelines':dict(counts,write_failed=0,unaccounted=0),'artifact_sha256':artifacts}
path=build/'game-data/oot/preparation-receipt.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(receipt))
info_path=app/'Contents/Info.plist';info=plistlib.loads(info_path.read_bytes());info.update(KokiriPrepared=True,KokiriShaders='full',KokiriSourceCommit=record['source_commit'],KokiriPreparationReceiptSHA256=sha(path),KokiriBuildRuntimeSHA256=artifacts['runtime_sha256']);info_path.write_bytes(plistlib.dumps(info))
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True)
fingerprint={'schema':'kokiri-package-output-v1','app':str(app),'build_runtime_sha256':artifacts['runtime_sha256'],'signed_runtime_sha256':sha(executable),'info_sha256':sha(info_path),'code_resources_sha256':sha(app/'Contents/_CodeSignature/CodeResources'),'preparation_receipt_sha256':sha(path)}
logs=Path(a.work)/'logs';logs.mkdir(exist_ok=True);(logs/'package-output.json').write_text(json.dumps(fingerprint))
'''


def run(arguments, cwd=None):
    return subprocess.check_output([str(value) for value in arguments], cwd=cwd, stderr=subprocess.STDOUT, timeout=20)


def stop_owned(pid, executable):
    actual = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'comm='], capture_output=True, text=True)
    if actual.returncode == 0:
        runtime.require(actual.stdout.strip() == str(executable), 'Diagnostic PID ownership changed; no signal sent')
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if subprocess.run(['/bin/ps', '-p', str(pid)], stdout=subprocess.DEVNULL).returncode != 0:
                return
            time.sleep(0.05)
        raise ValueError('Diagnostic process did not exit within its stop bound')


def observe(marker, expected, app):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.is_file():
            rows = marker.read_text().splitlines()
            if len(rows) == 3 and rows[0] == expected and rows[1].isdigit():
                pid = int(rows[1])
                executable = app / 'Contents/MacOS/KokiriGame'
                actual = run(['/bin/ps', '-p', pid, '-o', 'comm=']).decode().strip()
                runtime.require(actual == str(executable), 'Launch marker does not identify the selected app')
                return pid, executable
        time.sleep(0.05)
    raise ValueError('Diagnostic app relaunch was not observed')


def selftest(output):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    output = Path(output).resolve()
    runtime.require(not output.exists() and not output.is_relative_to(runtime.ROOT), 'Use a fresh external private test folder')
    runtime.game_closed()
    output.mkdir(mode=0o700)
    marker = output / 'launch-marker.txt'
    app = output / 'baseline/Kokiri Game.app'
    mac, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
    mac.mkdir(parents=True); resources.mkdir()
    source = output / 'diagnostic.c'; source.write_text(C_FIXTURE)
    run(['/usr/bin/xcrun', 'clang', '-Os', source, '-o', mac / 'KokiriGame'])
    (resources / 'marker-path.txt').write_text(str(marker) + '\n')
    (resources / 'fixture-version.txt').write_text('baseline-fixture\n')
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier=runtime.PRODUCT, CFBundleExecutable='KokiriGame', CFBundleName='Kokiri Update Diagnostic',
        CFBundlePackageType='APPL', CFBundleVersion='1', LSBackgroundOnly=True, KokiriGameUpdate='131072')))
    run(['/usr/bin/codesign', '--force', '--sign', '-', app])
    original = runtime.inspect_app(app)
    repository = output / 'fixture-source'; repository.mkdir()
    files = {'LICENSE':'MIT diagnostic fixture only\n', 'THIRD_PARTY_NOTICES.md':'No game data. Diagnostic update/relaunch fixture.\n',
             'engine/build.py':BUILDER, 'engine/scripts/preparation_receipt.py':'# synthetic receipt fixture; no game preparation\n',
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
            runtime.relaunch(activated['active']);pid,exe = observe(marker,'updated-fixture',selected);owned.append((pid,exe))
            stop_owned(pid,exe);owned.remove((pid,exe));marker.unlink()
            rolled = runtime.rollback(store)
            runtime.relaunch(rolled['active']);pid,exe=observe(marker,'baseline-fixture',app);owned.append((pid,exe))
            stop_owned(pid,exe);owned.remove((pid,exe))
            runtime.require(runtime.inspect_app(app)==original, 'Original diagnostic app changed')
            runtime.require((work/'preserved-cache.txt').read_text()=='preserved-fixture\n','Original workspace changed')
            runtime.require(runtime.state(store)['highest_version']==1,'Rollback lowered replay protection')
        result = dict(schema=1, tested_at_utc=datetime.now(timezone.utc).isoformat(),
                      fixture_only=True, game_assets_used=False, game_launched=False, production_ready=False,
                      source_manifest_sha256=runtime.sha(manifest), source_archive_sha256=runtime.sha(archive),
                      baseline=original, candidate=staged['candidate'],
                      checks=['real signed source package','real strict code-signature verification','distinct pre-seal versus final signed byte hashes',
                              'private staged local build','atomic activation','selected diagnostic app relaunch observed',
                              'rollback diagnostic app relaunch observed','original app/workspace preserved','replay watermark retained'])
        runtime.atomic_json(output/'verification.json',result)
        return result
    finally:
        key.unlink(missing_ok=True)
        for pid,exe in owned:
            stop_owned(pid,exe)
        # Observation may fail after LaunchServices started the fixture. Clean
        # only our exact private diagnostic paths, even without a parsed marker.
        expected = {str(app / 'Contents/MacOS/KokiriGame'),
                    str(output / 'versions/version-1/Kokiri Game.app/Contents/MacOS/KokiriGame')}
        rows = run(['/bin/ps', '-axo', 'pid=,comm=']).decode().splitlines()
        for row in rows:
            fields = row.strip().split(maxsplit=1)
            if len(fields) == 2 and fields[0].isdigit() and fields[1] in expected:
                stop_owned(int(fields[0]), Path(fields[1]))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        print(json.dumps(selftest(args.output),sort_keys=True))
    except Exception as error:
        parser.exit(1,'Diagnostic update test failed: '+str(error)+'\n')
