#!/usr/bin/env python3
"""Verified source updates and recoverable, private local runtime versions.

This trusted client is kept outside downloaded source. No game assets are served.
Activation selects a version in a private store; it never replaces an installed app.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import runtime_inputs

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_COMPILER_HELPER = ROOT / 'engine/scripts/metal_toolchain.py'
TRUSTED_PREPARATION_HELPER = ROOT / 'engine/scripts/preparation_receipt.py'
MAX_ARCHIVE = 128 << 20
MAX_EXPANDED = 256 << 20
RECEIPT = 'Contents/Resources/totk/build/game-data/oot/preparation-receipt.json'
PRODUCT = 'com.christianfurr.kokiri.runtime'
BUILD_HASH_SCOPE = 'pre-seal build executable; final signed bytes require an external package fingerprint'
SUPPORTED_COMPILER_FLAGS = {'-mmacosx-version-min=26.0', '-fmetal-math-mode=safe', '-fpreserve-invariance', '-fwrapv'}
ARCHIVE_VERIFICATION_FIELDS = (
    'verify_only', 'verification_process_fresh', 'verification_runtime_sha256', 'native_exit_code',
    'library_jit_attempts', 'archive_misses', 'archive_writes', 'verified_rows', 'archive_files_opened',
    'libraries_manifest_sha256', 'compiler_context_sha256', 'compiler_context_schema',
    'archive_snapshot_before_sha256', 'archive_snapshot_after_sha256')
DIGEST = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def read_json(path, limit=1 << 20):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            'Missing, linked or oversized JSON record')
    return parse_json(path.read_bytes())


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def https(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment,
            'Updates require HTTPS without credentials, query or fragment')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Update redirects require a reviewed feed change')


def download(url, destination, limit):
    https(url)
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'Kokiri-Source-Updater/1'})
    with opener.open(request, timeout=30) as response, Path(destination).open('xb') as output:
        count = 0
        while block := response.read(min(1 << 20, limit + 1 - count)):
            count += len(block)
            require(count <= limit, 'Update response exceeds its size limit')
            output.write(block)


def verify_manifest(manifest, signature, public_key, highest=0):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    manifest, signature = Path(manifest), Path(signature)
    require(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size <= 1 << 20,
            'Missing or oversized manifest')
    raw = manifest.read_bytes()
    require(signature.is_file() and not signature.is_symlink() and signature.stat().st_size <= 256,
            'Missing or oversized manifest signature')
    key = base64.b64decode(public_key, validate=True)
    signed = base64.b64decode(signature.read_bytes().strip(), validate=True)
    require(len(key) == 32 and len(signed) == 64, 'Invalid update key or signature size')
    # Verify exact bytes, before trusting URLs, version numbers or extracting code.
    Ed25519PublicKey.from_public_bytes(key).verify(signed, raw)
    record = parse_json(raw)
    require(isinstance(record, dict), 'Manifest must be a JSON object')
    require(record.get('schema') == 'kokiri-runtime-source-v1' and record.get('product') == PRODUCT,
            'Unrecognized runtime source manifest')
    require(type(record.get('version')) is int and 0 < record['version'] <= 10**12
            and record['version'] > highest, 'Runtime source version must increase')
    require(record.get('game_update') == '131072' and record.get('build_api') == 1,
            'Unsupported game update or builder API')
    require(COMMIT.fullmatch(str(record.get('source_commit', ''))), 'Exact source commit required')
    require(DIGEST.fullmatch(str(record.get('archive_sha256', ''))), 'Invalid archive identity')
    require(type(record.get('archive_bytes')) is int and 0 < record['archive_bytes'] <= MAX_ARCHIVE,
            'Invalid source archive size')
    require(isinstance(record.get('shader_chain'), str) and record['shader_chain'].startswith('oot-native-'),
            'Exact shader chain required')
    resources = record.get('public_resource_sha256', {})
    require(isinstance(resources, dict) and all(isinstance(name, str) and DIGEST.fullmatch(str(digest))
                                               for name, digest in resources.items()),
            'Invalid reviewed source-resource hashes')
    https(record.get('archive_url', ''))
    return record


def publication_guard():
    spec = importlib.util.spec_from_file_location('kokiri_publication', ROOT / 'scripts/check_publication.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_source(archive, destination, record):
    archive, destination = Path(archive), Path(destination)
    require(archive.stat().st_size == record['archive_bytes'] and sha(archive) == record['archive_sha256'],
            'Source archive size or SHA-256 differs from the signed manifest')
    require(not destination.exists(), 'Source destination must be fresh')
    guard = publication_guard()
    reviewed_names = set(guard.PINNED_METADATA) | set(guard.REVIEWED_WEBSITE_IMAGES) | set(guard.REVIEWED_APP_IMAGES)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        require(len(entries) <= 20000 and sum(e.file_size for e in entries) <= MAX_EXPANDED,
                'Source archive exceeds extraction bounds')
        seen = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            require(not entry.is_dir() and name.as_posix() == entry.filename
                    and not name.is_absolute() and '..' not in name.parts and '\\' not in entry.filename
                    and entry.filename.casefold() not in seen and '.git' not in {part.casefold() for part in name.parts},
                    'Invalid or duplicate source member')
            seen.add(entry.filename.casefold())
            mode = entry.external_attr >> 16
            require(stat.S_ISREG(mode) and not mode & 0o7022, 'Source member has unsafe file type or mode')
            require(entry.file_size <= 32 << 20, 'Source member exceeds size bound')
            data = source.read(entry)
            reason = guard.issue(entry.filename, data)
            # The maintainer's current publication guard reviews changed metadata
            # and artwork before signing. The old trusted client accepts their
            # newly signed exact bytes only at already recognized source paths.
            reviewed_change = (entry.filename in reviewed_names and reason in {
                'public metadata pin changed; review provenance', 'website image changed; review provenance',
                'app image changed; review provenance'} and
                record.get('public_resource_sha256', {}).get(entry.filename) == hashlib.sha256(data).hexdigest())
            require(reason is None or reviewed_change,
                    'Source member failed publication policy: ' + entry.filename)
        needed = {'engine/build.py', 'engine/scripts/preparation_receipt.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md'}
        require({name.casefold() for name in needed} <= seen,
                'Source release lacks the staged builder, receipt validator or attribution')
        destination.mkdir(mode=0o700)
        for entry in entries:
            target = destination / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(source.read(entry))
            target.chmod((entry.external_attr >> 16) & 0o755)
    chain_file = destination / 'engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h'
    chain = re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot', chain_file.read_text())
    require(chain and chain[1] == record['shader_chain'], 'Signed source and shader chain differ')


def game_closed(owned_process_group=None):
    # Never send input or terminate any process. Unknown process-list failure blocks work.
    rows = subprocess.check_output(['/bin/ps', '-axo', 'pid=,pgid=,comm='], text=True).splitlines()
    for row in rows:
        fields = row.strip().split(maxsplit=2)
        require(len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit(), 'Unrecognized process snapshot')
        if Path(fields[2]).name not in {'KokiriGame', 'OcarinaOfTime', 'oot-native'}:
            continue
        # The staged builder legitimately launches oot-native for shader requests
        # and archive preparation. Only its new process group is ours to exempt.
        if owned_process_group is not None and int(fields[1]) == owned_process_group:
            continue
        raise ValueError('Close the game normally before updating; no session was interrupted')


def inspect_app(app, record=None):
    app = Path(app).resolve(strict=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    require(info.get('CFBundleIdentifier') == PRODUCT and info.get('CFBundleExecutable') == 'KokiriGame',
            'Managed updates require a Kokiri runtime app')
    require(info.get('KokiriGameUpdate') == '131072', 'Runtime game update differs')
    executable = app / 'Contents/MacOS/KokiriGame'
    require(executable.is_file() and os.access(executable, os.X_OK), 'Runtime executable is missing')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = dict(app=str(app), executable_sha256=sha(executable), info_sha256=sha(app / 'Contents/Info.plist'),
                  code_resources_sha256=sha(app / 'Contents/_CodeSignature/CodeResources'))
    if info.get('MNGGameDataFolder'):
        data = Path(info['MNGGameDataFolder']).resolve(strict=True) / 'oot/romfs.bin'
        require(data.is_file() and not data.is_symlink(), 'External game-data image is missing or linked')
        result['external_game_data'] = dict(path=str(data), sha256=sha(data), bytes=data.stat().st_size)
    if record is None:
        return result
    receipt = read_json(app / RECEIPT)
    require(receipt.get('schema') == 'kokiri-preparation-receipt-v1' and receipt.get('mode') == 'full'
            and receipt.get('prepared') is True and receipt.get('errors') == [], 'Runtime shader preparation is incomplete')
    identity = receipt.get('identity', {})
    require(info.get('KokiriPrepared') is True and info.get('KokiriShaders') == 'full'
            and info.get('KokiriPreparationReceiptSHA256') == sha(app / RECEIPT),
            'Runtime metadata does not bind a full preparation receipt')
    build_hash = receipt.get('artifact_sha256', {}).get('runtime_sha256')
    require(identity.get('source_commit') == record['source_commit'] == info.get('KokiriSourceCommit')
            and identity.get('chain') == record['shader_chain']
            and identity.get('runtime_hash_scope') == BUILD_HASH_SCOPE
            and DIGEST.fullmatch(str(build_hash)) and identity.get('runtime_sha256') == build_hash
            and info.get('KokiriBuildRuntimeSHA256') == build_hash,
            'Prepared runtime/source/shader identity differs from the signed release')
    require(DIGEST.fullmatch(str(identity.get('seed_runtime_sha256', '')))
            and identity['seed_runtime_sha256'] == build_hash,
            'Seed requests were not verified by the current build runtime')
    require(DIGEST.fullmatch(str(identity.get('translation_context_sha256', '')))
            and DIGEST.fullmatch(str(identity.get('translator_sha256', ''))),
            'Prepared translation context and translator identity required')
    if 'external_game_data' in result:
        require(identity.get('source_romfs_sha256') == result['external_game_data']['sha256'],
                'External game-data image differs from the preparation source')
    sections = [('default variants', receipt.get('variants', {}).get('default', {}), True),
                ('listed variants', receipt.get('variants', {}).get('listed', {}), False),
                ('libraries', receipt.get('libraries', {}), True),
                ('pipelines', receipt.get('pipelines', {}), True)]
    for section, counts, nonempty in sections:
        require(type(counts.get('requested')) is int and counts['requested'] > 0
                or not nonempty and type(counts.get('requested')) is int and counts['requested'] == 0,
                'Invalid requested work count: ' + section)
        require(type(counts.get('completed')) is int and type(counts.get('failed')) is int
                and counts['completed'] == counts['requested'] and counts['failed'] == 0,
                'Incomplete prepared work: ' + section)
    require(type(receipt['pipelines'].get('write_failed')) is int and receipt['pipelines']['write_failed'] == 0
            and type(receipt['pipelines'].get('unaccounted')) is int and receipt['pipelines']['unaccounted'] == 0,
            'Pipeline archive is incomplete')
    require(type(receipt['variants'].get('unique_completed')) is int
            and receipt['variants']['unique_completed'] == receipt['libraries']['requested'],
            'Compiled library coverage differs from unique shader variants')
    result['preparation_artifact_sha256'] = verify_preparation_artifacts(app, receipt, qualify_compiler=True)
    result.update(version=record['version'], source_commit=record['source_commit'],
                  preparation_receipt_sha256=sha(app / RECEIPT), shader_chain=record['shader_chain'],
                  build_runtime_sha256=build_hash)
    return result


def load_trusted_compiler_validator():
    helper = TRUSTED_COMPILER_HELPER
    require(helper.is_file() and not helper.is_symlink(),
            'Trusted compiler validator unavailable; integrate the schema-2 engine tooling')
    spec = importlib.util.spec_from_file_location('kokiri_trusted_compiler_validator', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = getattr(module, 'compiler_context_key', None)
    require(callable(validator), 'Trusted compiler validator lacks context support')
    return validator


def verify_compiler_context(receipt, libraries):
    require(type(receipt.get('compiler_context_schema')) is int and receipt['compiler_context_schema'] == 2
            and type(libraries.get('compiler_context_schema')) is int and libraries['compiler_context_schema'] == 2,
            'Full preparation requires compiler context schema 2')
    observation = receipt.get('compiler_observation')
    require(isinstance(observation, dict) and observation.get('qualified') is True
            and type(observation.get('observation_schema')) is int and observation['observation_schema'] == 2
            and observation.get('backend') == 'metal', 'Qualified Metal compiler observation schema 2 required')
    require(observation.get('loader_environment_policy') == 'reject-nonempty-DYLD',
            'Compiler observation lacks the required loader-environment policy')
    flags = observation.get('effective_flags')
    require(isinstance(flags, list) and all(isinstance(flag, str) for flag in flags)
            and len(flags) == len(SUPPORTED_COMPILER_FLAGS) and set(flags) == SUPPORTED_COMPILER_FLAGS
            and isinstance(observation.get('effective_target'), str)
            and re.search(r'-apple-macosx26\.0\.0(?:$|-)', observation['effective_target']),
            'Compiler observation lacks required macOS target or correctness flags')
    invocations = observation.get('effective_invocations')
    require(isinstance(invocations, list)
            and all(isinstance(argv, list) and all(isinstance(arg, str) for arg in argv) for argv in invocations),
            'Compiler observation lacks effective invocations')
    for argv in invocations:
        require(not any(arg in {'-fno-wrapv', '-fno-preserve-invariance', '-fstrict-overflow', '-ffast-math', '-funsafe-math-optimizations'}
                        or arg.startswith('-fmetal-math-mode=') and arg != '-fmetal-math-mode=safe' for arg in argv),
                'Compiler invocation overrides the required correctness policy')
    require(observation == libraries.get('compiler_observation'), 'Compiler observation differs from library manifest')
    context = receipt.get('compiler_context_sha256')
    require(DIGEST.fullmatch(str(context)) and context == libraries.get('compiler_context_sha256'),
            'Compiler context differs from library manifest')
    validator = load_trusted_compiler_validator()
    try:
        expected = validator(observation)
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        raise ValueError('Invalid qualified compiler observation') from error
    require(context == expected, 'Compiler context digest does not match the recorded toolchain')
    return context


def load_trusted_preparation_validator():
    helper = TRUSTED_PREPARATION_HELPER
    require(helper.is_file() and not helper.is_symlink(),
            'Trusted final archive validator unavailable; integrate the final preparation tooling')
    spec = importlib.util.spec_from_file_location('kokiri_trusted_preparation_validator', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = getattr(module, 'archive_verification_errors', None)
    require(callable(validator), 'Trusted preparation validator lacks final archive support')
    return validator


def verify_archive_verification(receipt, report):
    require(isinstance(report, dict), 'Final archive report must be a JSON object')
    counts, identity, artifacts = receipt['pipelines'], receipt['identity'], receipt['artifact_sha256']
    require(type(report.get('requested')) is int and report['requested'] == counts['requested']
            and type(report.get('completed')) is int and report['completed'] == counts['completed']
            and report.get('chain') == identity['chain'] and report.get('arch') == identity['gpu_architecture']
            and report.get('runtime_sha256') == artifacts['runtime_sha256'],
            'Final archive report differs from the prepared runtime or requested pipeline set')
    validator = load_trusted_preparation_validator()
    try:
        errors = validator(report, requested=counts['requested'],
                           libraries_manifest_sha256=artifacts['libraries_manifest_sha256'],
                           compiler_context_sha256=receipt['compiler_context_sha256'],
                           runtime_sha256=artifacts['runtime_sha256'])
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        raise ValueError('Invalid final archive verification evidence') from error
    require(isinstance(errors, list) and not errors, 'Final archive verification did not establish read-only preparation')
    expected = {field: report.get(field) for field in ARCHIVE_VERIFICATION_FIELDS}
    require(receipt.get('archive_verification') == expected, 'Receipt archive proof differs from the sealed pipeline report')
    return expected


def verify_preparation_artifacts(app, receipt, *, qualify_compiler=False):
    arch = receipt['identity'].get('gpu_architecture')
    require(isinstance(arch, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', arch), 'Invalid GPU archive identity')
    build = app / 'Contents/Resources/totk/build'
    paths = dict(seed_manifest_sha256=build / 'shader-seed/seed-manifest.json',
                 libraries_manifest_sha256=build / 'shader-libs/libraries-manifest.json',
                 pipeline_manifest_sha256=build / 'pipelines/compute-manifest.json',
                 pipeline_index_sha256=build / 'pipelines' / ('pipelines-' + arch + '.tsv'))
    expected = receipt['artifact_sha256']
    if qualify_compiler:
        artifact_paths = {name: path.relative_to(app).as_posix() for name, path in paths.items()}
        artifact_paths['runtime_sha256'] = 'Contents/MacOS/KokiriGame'
        require(receipt.get('artifact_paths') == artifact_paths, 'Preparation artifact paths differ from the actual bundle')
    for name, path in paths.items():
        require(path.resolve(strict=True).is_relative_to(app)
                and DIGEST.fullmatch(str(expected.get(name, ''))) and sha(path) == expected[name],
                'Preparation artifact differs: ' + name)
        if name == 'pipeline_index_sha256':
            continue
        manifest = read_json(path, limit=32 << 20)
        if name == 'seed_manifest_sha256' and qualify_compiler:
            require(manifest.get('runtime_sha256') == receipt['identity']['seed_runtime_sha256']
                    == receipt['artifact_sha256']['runtime_sha256'],
                    'Seed manifest requests belong to another build runtime')
        if name == 'libraries_manifest_sha256' and qualify_compiler:
            verify_compiler_context(receipt, manifest)
        if name == 'pipeline_manifest_sha256' and qualify_compiler:
            verify_archive_verification(receipt, manifest)
        files = manifest.get('files')
        require(isinstance(files, dict) and files, 'Preparation artifact lacks payload hashes')
        for relative, digest in files.items():
            member = PurePosixPath(relative)
            require(not member.is_absolute() and '..' not in member.parts and '\\' not in relative
                    and DIGEST.fullmatch(str(digest)), 'Invalid preparation payload path or hash')
            payload = path.parent / relative
            require(payload.resolve(strict=True).is_relative_to(app) and sha(payload) == digest,
                    'Prepared shader/archive payload differs')
    return {name: expected[name] for name in paths}


def validate_store_location(root, work=None, current_app=None):
    root = Path(root).expanduser().absolute()
    require(root != ROOT and not root.is_relative_to(ROOT), 'Private runtime store must stay outside trusted source')
    require(not any((parent / '.git').exists() for parent in (root, *root.parents)),
            'Private runtime store must stay outside Git checkouts')
    if work is not None:
        original = Path(work).expanduser().resolve(strict=True)
        require(root != original and not root.is_relative_to(original),
                'Runtime store must stay outside the original build workspace')
    if current_app is not None:
        original_app = Path(current_app).expanduser().resolve(strict=True)
        require(root != original_app and not root.is_relative_to(original_app),
                'Runtime store must stay outside the original app')


@contextmanager
def store_lock(root):
    root = Path(root).expanduser().absolute()
    validate_store_location(root)
    require(not root.is_symlink() and root.resolve() == root, 'Store path must not contain symlinks')
    if not root.exists():
        root.mkdir(mode=0o700, parents=True)
    require(root.is_dir() and root.stat().st_uid == os.getuid() and not root.stat().st_mode & 0o077,
            'Runtime store must be an owner-only directory')
    lock = os.open(root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    finally:
        os.close(lock)


def state(root):
    path = root / 'state.json'
    value = read_json(path) if path.exists() else dict(schema=1, highest_version=0, active=None, previous=None)
    require(value.get('schema') == 1 and type(value.get('highest_version')) is int
            and value['highest_version'] >= 0, 'Invalid runtime store state; inspect retained versions')
    return value


def clone_work(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    require(not destination.is_relative_to(source) and not source.is_relative_to(destination),
            'Build workspaces must not overlap')
    # Copies are mutable build data: reject links that could make the builder write
    # into the original workspace. Venv executable links alone may target the host.
    for directory, folders, files in os.walk(source):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink():
                relative = path.relative_to(source).as_posix()
                require(relative in {'venv/bin/python', 'venv/bin/python3', 'venv/bin/python3.14'}
                        and path.resolve().is_file(), 'Workspace link requires a fresh isolated build: ' + relative)
    require(not destination.exists(), 'Build workspace destination exists')
    # APFS clones avoid copying locally owned game assets; fail instead of falling
    # back to a large copy on another filesystem.
    subprocess.run(['/bin/cp', '-cR', str(source), str(destination)], check=True)


def build_candidate(arguments, log, environment):
    game_closed()
    process = subprocess.Popen([str(value) for value in arguments], stdout=log, stderr=subprocess.STDOUT,
                               env=environment, start_new_session=True)
    try:
        while process.poll() is None:
            time.sleep(1)
            game_closed(owned_process_group=process.pid)
        require(process.returncode == 0, 'Local runtime build failed; see the retained private build.log')
    finally:
        if process.poll() is None:
            # Stop only our owned build group when human gameplay appears.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def pin_key(root, public_key):
    key = base64.b64decode(public_key, validate=True)
    require(len(key) == 32, 'Invalid public update key')
    trust = root / 'trust.json'
    if trust.exists():
        require(read_json(trust) == dict(schema=1, public_key=public_key), 'Public update key differs from the enrolled key')
    else:
        atomic_json(trust, dict(schema=1, public_key=public_key))


def verify_package_output(work, candidate):
    path = Path(work) / 'logs/package-output.json'
    output = read_json(path)
    expected = dict(schema='kokiri-package-output-v1', app=candidate['app'],
                    build_runtime_sha256=candidate['build_runtime_sha256'],
                    signed_runtime_sha256=candidate['executable_sha256'],
                    info_sha256=candidate['info_sha256'], code_resources_sha256=candidate['code_resources_sha256'],
                    preparation_receipt_sha256=candidate['preparation_receipt_sha256'])
    require(output == expected, 'Final signed package fingerprint differs from the staged build output')
    return sha(path)


def stage(root, manifest, signature, public_key, archive, current_app, work, python,
          *, shader_list=None, learned_caches=()):
    validate_store_location(root, work, current_app)
    current = state(root)
    record = verify_manifest(manifest, signature, public_key, current['highest_version'])
    load_trusted_compiler_validator()
    load_trusted_preparation_validator()
    original_inputs = runtime_inputs.capture_inputs(work, shader_list, learned_caches, record['shader_chain'])
    pin_key(root, public_key)
    game_closed()
    baseline = inspect_app(current_app)
    if current['active']:
        require(current['active']['app'] == baseline['app'], 'Selected app differs from the managed active version')
        unchanged(current['active'])
        baseline = current['active']
    require(shutil.disk_usage(root).free >= 6 << 30, 'Runtime update needs at least 6 GiB free plus build headroom')
    version = root / ('version-' + str(record['version']))
    require(not version.exists(), 'Version already staged; inspect its retained diagnostics')
    version.mkdir(mode=0o700)
    atomic_json(version / 'transaction.json', dict(phase='verifying-source', version=record['version'], baseline=baseline))
    source = version / 'source'
    extract_source(archive, source, record)
    shutil.copyfile(manifest, version / 'manifest.json')
    shutil.copyfile(signature, version / 'manifest.sig')
    # Source identity is the signed manifest, not a fabricated local git commit.
    atomic_json(source / 'kokiri-source-release.json', record)
    clone_work(work, version / 'work')
    staged_inputs = runtime_inputs.verify_cloned_inputs(original_inputs, version / 'work')
    runtime_inputs.verify_unchanged(original_inputs)
    input_provenance = dict(schema='kokiri-runtime-input-provenance-v1', original=original_inputs, staged=staged_inputs)
    atomic_json(version / 'input-provenance.json', input_provenance)
    selected_list, selected_caches = runtime_inputs.remap_inputs(original_inputs, version / 'work')
    atomic_json(version / 'transaction.json', dict(phase='building', version=record['version'], baseline=baseline))
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('OOT_', 'TOTK_', 'DYLD_', 'PYTHON', 'DM_'))}
    environment.update(OOT_SHADERS='full', KOKIRI_BUILD_JOBS='2')
    app = version / 'Kokiri Game.app'
    build_arguments = [python, '-I', source / 'engine/build.py', '--rebuild', Path(current_app).resolve(),
                       '--out', app, '--work', version / 'work', '--jobs', '2']
    if selected_list is not None:
        build_arguments += ['--shader-list', selected_list]
    for cache in selected_caches:
        build_arguments += ['--learned-cache', cache]
    with (version / 'build.log').open('xb') as log:
        build_candidate(build_arguments, log, environment)
    runtime_inputs.verify_unchanged(original_inputs)
    runtime_inputs.verify_unchanged(staged_inputs)
    require(not app.is_symlink() and app.resolve(strict=True) == app.absolute(),
            'Candidate app must be owned by its version directory')
    candidate = inspect_app(app, record)
    package_output_sha256 = verify_package_output(version / 'work', candidate)
    candidate_info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if candidate_info.get('MNGGameDataFolder'):
        require(Path(candidate_info['MNGGameDataFolder']).resolve().is_relative_to(version / 'work'),
                'Candidate game-data library escapes its versioned workspace')
    atomic_json(version / 'transaction.json', dict(phase='prepared', version=record['version'],
                                                 candidate=candidate, baseline=baseline,
                                                 package_output_sha256=package_output_sha256,
                                                 input_provenance_sha256=sha(version / 'input-provenance.json')))
    return dict(status='staged', candidate=candidate, activated=False, game_launched=False)


def unchanged(identity):
    actual = inspect_app(identity['app'])
    require(all(actual.get(key) == identity.get(key) for key in actual), 'Retained app changed; activation refused')
    if identity.get('preparation_receipt_sha256'):
        app = Path(identity['app'])
        require(sha(app / RECEIPT) == identity['preparation_receipt_sha256'], 'Retained preparation receipt changed')
        require(verify_preparation_artifacts(app, read_json(app / RECEIPT)) == identity['preparation_artifact_sha256'],
                'Retained shader preparation changed')


def activate(root, version, public_key):
    current = state(root)
    folder = root / ('version-' + str(version))
    transaction = read_json(folder / 'transaction.json')
    require(transaction.get('phase') == 'prepared', 'Candidate has not completed preparation')
    record = verify_manifest(folder / 'manifest.json', folder / 'manifest.sig', public_key, current['highest_version'])
    pin_key(root, public_key)
    require(record['version'] == version, 'Candidate version mismatch')
    provenance_path = folder / 'input-provenance.json'
    require(DIGEST.fullmatch(str(transaction.get('input_provenance_sha256', '')))
            and sha(provenance_path) == transaction['input_provenance_sha256'], 'Preparation input provenance changed')
    provenance = read_json(provenance_path, limit=32 << 20)
    require(provenance.get('schema') == 'kokiri-runtime-input-provenance-v1', 'Invalid preparation input provenance')
    runtime_inputs.verify_unchanged(provenance['original'])
    runtime_inputs.verify_unchanged(provenance['staged'])
    app = folder / 'Kokiri Game.app'
    require(not app.is_symlink() and app.resolve() == app.absolute(),
            'Candidate app must stay inside its version directory')
    candidate = inspect_app(app, record)
    require(candidate == transaction['candidate'], 'Candidate changed after staging')
    baseline = transaction['baseline']
    require(not current['active'] or current['active'] == baseline, 'Active app changed after staging')
    unchanged(baseline)
    game_closed()
    atomic_json(root / 'state.json', dict(schema=1, highest_version=version, active=candidate, previous=baseline))
    return dict(status='activated', active=candidate, previous=baseline, game_launched=False)


def rollback(root):
    current = state(root)
    require(current['previous'], 'No retained rollback version')
    unchanged(current['previous'])
    game_closed()
    # Never lower the accepted release sequence, even after explicit rollback.
    restored = {**current, 'active': current['previous'], 'previous': current['active']}
    atomic_json(root / 'state.json', restored)
    return dict(status='rolled_back', **restored, game_launched=False)


def relaunch(identity):
    unchanged(identity)
    game_closed()
    subprocess.run(['/usr/bin/open', '-n', identity['app']], check=True)
    return dict(status='launch_requested', active=identity, game_launched='unverified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True, type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    stage_parser = sub.add_parser('stage')
    delivery = stage_parser.add_mutually_exclusive_group(required=True)
    delivery.add_argument('--feed')
    delivery.add_argument('--manifest', type=Path)
    stage_parser.add_argument('--signature', type=Path)
    stage_parser.add_argument('--archive', type=Path)
    stage_parser.add_argument('--public-key', required=True)
    stage_parser.add_argument('--current-app', required=True, type=Path)
    stage_parser.add_argument('--work', required=True, type=Path)
    stage_parser.add_argument('--python', required=True, type=Path)
    stage_parser.add_argument('--shader-list', type=Path, help='explicit merged metadata in WORK/preparation-inputs/RUN')
    stage_parser.add_argument('--learned-cache', type=Path, action='append', default=[],
                              help='complete same-chain cache within the selected owned input run (repeatable)')
    activation = sub.add_parser('activate')
    activation.add_argument('--version', required=True, type=int)
    activation.add_argument('--public-key', required=True)
    sub.add_parser('rollback')
    sub.add_parser('relaunch')
    args = parser.parse_args()
    try:
        validate_store_location(args.store, args.work if args.action == 'stage' else None,
                                args.current_app if args.action == 'stage' else None)
        with store_lock(args.store) as root:
            if args.action == 'stage':
                with tempfile.TemporaryDirectory(prefix='.delivery-', dir=root) as temporary:
                    delivery = Path(temporary)
                    manifest, signature, archive = args.manifest, args.signature, args.archive
                    if args.feed:
                        manifest, signature, archive = delivery / 'manifest.json', delivery / 'manifest.sig', delivery / 'source.zip'
                        download(args.feed, manifest, 1 << 20)
                        download(args.feed + '.sig', signature, 256)
                        record = verify_manifest(manifest, signature, args.public_key, state(root)['highest_version'])
                        download(record['archive_url'], archive, record['archive_bytes'])
                    require(manifest and signature and archive, 'Local delivery requires manifest, signature and archive')
                    result = stage(root, manifest, signature, args.public_key, archive, args.current_app, args.work, args.python,
                                   shader_list=args.shader_list, learned_caches=args.learned_cache)
            elif args.action == 'activate':
                result = activate(root, args.version, args.public_key)
            elif args.action == 'rollback':
                result = rollback(root)
            elif args.action == 'relaunch':
                active = state(root)['active']
                require(active, 'No active managed runtime')
                result = relaunch(active)
            else:
                result = dict(status='observed', **state(root))
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        # Build/signing diagnostics remain in private files. Do not emit their
        # contents or downloaded source exceptions into an app's public UI.
        print(json.dumps(dict(status='refused', error=type(error).__name__,
                              detail=str(error) if isinstance(error, ValueError) else 'See private update diagnostics.')))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
