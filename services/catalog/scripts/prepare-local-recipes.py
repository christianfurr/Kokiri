"""Verify a downloaded catalog and merge recipes for local game preparation.

This offline tool creates one fresh --shader-list input. It does not compile,
launch a game, download content, or modify a game/cache or the baseline list.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/catalog/sdk/python'))
sys.path.insert(0, str(ROOT / 'engine/scripts'))
import kokiri_catalog as wire
from shader_list import ShaderList


def directory(path):
    """Open each directory without following links, including ancestors."""
    absolute = os.path.abspath(path)
    parts = Path(absolute).parts[1:]
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(path, limit):
    path = Path(os.path.abspath(path))
    parent = directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        wire.require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit,
                     'input must be a bounded regular file')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    wire.require(len(data) == before.st_size <= limit and
                 (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                 (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                 'input changed during verification')
    return data


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        wire.require(key not in value, 'duplicate JSON key')
        value[key] = item
    return value


def read_json(path, limit):
    return json.loads(read_file(path, limit), object_pairs_hook=unique_object)


def verified_rows(index_path, expected, keys, minimum_revision):
    index = read_json(index_path, 1024 * 1024)
    wire.require(isinstance(index, dict) and set(index) ==
                 {'protocol', 'context_id', 'signed_manifest', 'pack_files'}, 'download index fields')
    manifest = wire.verify_manifest(index['signed_manifest'], expected, keys, for_warmup=False)
    wire.require(index['protocol'] == wire.PROTOCOL and index['context_id'] == manifest['context_id'],
                 'download index identity')
    wire.require(manifest['revision'] >= minimum_revision and manifest['record_count'] <= 100000,
                 'catalog revision or record limit')
    references = index['pack_files']
    wire.require(isinstance(references, list) and len(references) == len(manifest['packs']),
                 'download pack references')
    total_bytes = 0
    records = set()
    rows = []
    cache = Path(index_path).parent.parent / 'packs'
    for part, reference in zip(manifest['packs'], references):
        wire.require(isinstance(reference, dict) and reference ==
                     dict(part, relative_path='../packs/' + part['sha256'] + '.json'),
                     'download pack reference mismatch')
        total_bytes += part['bytes']
        wire.require(total_bytes <= 64 * 1024 * 1024, 'catalog byte limit')
        raw = read_file(cache / (part['sha256'] + '.json'), part['bytes'])
        # Reject duplicate keys before using the SDK's signed-hash/row checks.
        json.loads(raw, object_pairs_hook=unique_object)
        pack = wire.verify_pack(raw.decode('utf-8'), part, manifest['context_id'])
        for record in pack['records']:
            wire.require(record['id'] not in records, 'duplicate catalog record across packs')
            records.add(record['id'])
            rows.append(record['row'])
    wire.require(len(records) == manifest['record_count'], 'catalog record count')
    return manifest, rows


def prepare(index, context, keys, baseline, output, minimum_revision=1):
    wire.require(type(minimum_revision) is int and minimum_revision >= 1, 'minimum revision must be positive')
    expected = wire.context(read_json(context, 65536))
    wire.require(expected['game_id'] == 'oot' and expected['backend'] == 'metal',
                 'local preparation requires an Ocarina of Time Metal context')
    build_version = read_json(ROOT / 'engine/assets/expected-v131072.json', 262144)['content_version']
    header = read_file(ROOT / 'engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h', 65536).decode('ascii')
    chain = re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b', header)
    wire.require(chain is not None and expected['game_version'] == str(build_version)
                 and expected['shader_chain'] == chain[1],
                 'catalog game version or shader chain differs from this local builder')
    trusted = read_json(keys, 65536)
    wire.require(isinstance(trusted, dict) and trusted, 'supply independently trusted public keys')
    manifest, rows = verified_rows(index, expected, trusted, minimum_revision)
    original = read_file(baseline, 64 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix='kokiri-local-recipes-',
                                     dir=os.path.realpath(tempfile.gettempdir())) as folder:
        snapshot = Path(folder) / 'baseline.tsv'
        snapshot.write_bytes(original)
        merged = ShaderList.load(snapshot)
        before = len(merged.warm)
        supplemental = Path(folder) / 'catalog.tsv'
        supplemental.write_text('\n'.join(rows) + '\n', encoding='ascii')
        merged.add_rows(supplemental, 'm')
        # The normal parser can recover held rows once all binding metadata is present.
        merged.retry_refused()
        result = Path(folder) / 'merged.tsv'
        merged.save(result)
        payload = read_file(result, 128 * 1024 * 1024)
    provenance = '# Kokiri catalog: ' + wire.canonical(dict(
        context_id=manifest['context_id'], revision=manifest['revision'],
        compatibility=manifest['compatibility'])) + '\n'
    provenance += '# Catalog attribution: ' + wire.canonical(manifest['attribution']) + '\n'
    payload = provenance.encode('ascii') + payload
    destination = Path(os.path.abspath(output))
    parent = directory(destination.parent)
    staging = '.kokiri-recipes-' + str(uuid.uuid4())
    created = False
    try:
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish only the complete list; link refuses an existing destination.
        os.link(staging, destination.name, src_dir_fd=parent, dst_dir_fd=parent,
                follow_symlinks=False)
    finally:
        if created:
            os.unlink(staging, dir_fd=parent)
        os.close(parent)
    return dict(context_id=manifest['context_id'], revision=manifest['revision'],
                compatibility=manifest['compatibility'], catalog_records=len(rows),
                added_warm_rows=len(merged.warm) - before, merged_warm_rows=len(merged.warm),
                refused_bindings=merged.refused, output_sha256=wire.digest(payload.decode('utf-8')),
                prepared=False, runtime_warmup=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True, help='native reference/ or runtime-ready/ downloaded index')
    parser.add_argument('--context', required=True, help='independently selected expected catalog context JSON')
    parser.add_argument('--keys', required=True, help='independently trusted key-id to base64 public-key JSON')
    parser.add_argument('--baseline', required=True, help='existing complete shader metadata list')
    parser.add_argument('--output', required=True, help='fresh merged metadata path in an existing directory')
    parser.add_argument('--minimum-revision', type=int, default=1)
    arguments = parser.parse_args()
    print(wire.canonical(prepare(arguments.index, arguments.context, arguments.keys,
                                 arguments.baseline, arguments.output, arguments.minimum_revision)))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': 'local_recipe_preparation_failed',
                          'detail': str(error) or type(error).__name__}), file=sys.stderr)
        sys.exit(1)
