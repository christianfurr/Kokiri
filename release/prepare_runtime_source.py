#!/usr/bin/env python3
"""Package a clean, reviewed source commit; sign no generated game artifacts."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('runtime_update', Path(__file__).with_name('runtime_update.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def prepare(repository, output, version, url, key_file):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    repository, output = Path(repository).resolve(strict=True), Path(output).resolve()
    runtime.require(not output.exists() and not output.is_relative_to(repository), 'Use a fresh external output folder')
    runtime.require(type(version) is int and 0 < version <= 10**12, 'Release version must be a positive sequence number')
    runtime.https(url)
    def git(*arguments):
        return subprocess.check_output(['/usr/bin/git', '-C', str(repository), *arguments])
    runtime.require(not git('status', '--porcelain', '--untracked-files=normal').strip(), 'Source checkout must be clean')
    commit = git('rev-parse', 'HEAD').decode().strip()
    runtime.require(runtime.COMMIT.fullmatch(commit), 'Source commit must have an exact identity')
    key_file = Path(key_file).absolute()
    metadata = key_file.lstat()
    runtime.require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                    and not metadata.st_mode & 0o077 and metadata.st_size <= 256,
                    'Signing seed must be a regular owner-only external file')
    runtime.require(not key_file.resolve().is_relative_to(repository), 'Signing material must stay outside source')
    seed = base64.b64decode(key_file.read_bytes().strip(), validate=True)
    runtime.require(len(seed) == 32, 'Expected a 32-byte Ed25519 signing seed')
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    guard = runtime.publication_guard()
    entries = []
    total = 0
    for row in git('ls-tree', '-r', '-z', commit).split(b'\0'):
        if not row:
            continue
        meta, raw_name = row.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        name = raw_name.decode()
        runtime.require(kind == 'blob' and mode in {'100644', '100755'}, 'Source contains a link or submodule')
        size = int(git('cat-file', '-s', blob))
        runtime.require(size <= 32 << 20, 'Source member exceeds size bound')
        total += size
        runtime.require(total <= runtime.MAX_EXPANDED, 'Source exceeds the release size bound')
        data = git('cat-file', 'blob', blob)
        runtime.require(guard.issue(name, data, mode) is None, 'Publication rejected source member: ' + name)
        entries.append((name, mode, data))
    contents = {name: data for name, _, data in entries}
    runtime.require('engine/scripts/preparation_receipt.py' in contents,
                    'This source commit lacks preparation receipts; integrate the staged builder first')
    builder = contents['engine/build.py'].decode()
    runtime.require('--jobs' in builder and 'source-release' in builder,
                    'This source commit lacks the staged source-release builder API')
    chain = re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot',
                      contents['engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h'].decode())
    runtime.require(chain, 'Source shader chain is missing')
    output.mkdir(mode=0o700)
    archive = output / 'runtime-source.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, mode, data in sorted(entries):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | int(mode, 8) & 0o777) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(entry, data)
    runtime.require(archive.stat().st_size <= runtime.MAX_ARCHIVE, 'Compressed source exceeds release bound')
    record = dict(schema='kokiri-runtime-source-v1', product=runtime.PRODUCT, version=version,
                  source_commit=commit, game_update='131072', build_api=1, shader_chain=chain[1],
                  archive_url=url, archive_sha256=runtime.sha(archive), archive_bytes=archive.stat().st_size)
    reviewed = set(guard.PINNED_METADATA) | set(guard.REVIEWED_WEBSITE_IMAGES) | set(guard.REVIEWED_APP_IMAGES)
    record['public_resource_sha256'] = {name: hashlib.sha256(data).hexdigest()
                                      for name, _, data in entries if name in reviewed}
    manifest = output / 'manifest.json'
    runtime.atomic_json(manifest, record)
    (output / 'manifest.json.sig').write_bytes(base64.b64encode(private_key.sign(manifest.read_bytes())) + b'\n')
    public = base64.b64encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    runtime.verify_manifest(manifest, output / 'manifest.json.sig', public)
    return dict(**record, public_key=public, uploaded=False, runtime_built=False, production_distribution_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=runtime.ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', type=int, required=True)
    parser.add_argument('--archive-url', required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.repository, args.output, args.version, args.archive_url, args.key_file)
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        parser.exit(1, 'Source release refused: ' + type(error).__name__ + '\n')


if __name__ == '__main__':
    main()
