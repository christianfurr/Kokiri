"""Build an unsigned metadata candidate from an explicit verified SQLite snapshot.

The operator selects IDs after checking provenance and runtime reproducibility.
This command reads a closed snapshot; it does not publish or change quarantine.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('catalog', ROOT / 'sdk/python/kokiri_catalog.py')
sdk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sdk)
MAX_RECORDS = 100000
MAX_BYTES = 64 * 1024 * 1024


def snapshot_digest(path):
    info = path.lstat()
    sdk.require(stat.S_ISREG(info.st_mode) and info.st_size <= 1024 ** 3
                and info.st_uid == os.getuid() and not info.st_mode & 0o077
                and info.st_nlink == 1 and path.resolve() == path, 'private snapshot file required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    after = path.stat()
    sdk.require(all(getattr(info, key) == getattr(after, key) for key in
                    ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'snapshot changed')
    return digest.hexdigest()


def reviewed_records(db, cid, selected):
    result = []
    for rid in sorted(selected):
        row = db.execute('SELECT record_id,kind,row FROM inbox WHERE context_id=? AND record_id=? AND length(row)<=4096',
                         (cid, rid)).fetchone()
        sdk.require(row is not None, 'selected record missing or oversized')
        result.append(sdk.record(dict(zip(('id', 'kind', 'row'), row))))
    return result


def previous_catalog(db, context, trusted_keys):
    cid = sdk.context_id(context)
    row = db.execute('SELECT envelope FROM manifests WHERE context_id=? AND length(envelope)<=262144', (cid,)).fetchone()
    if row is None:
        sdk.require(db.execute('SELECT count(*) FROM manifests WHERE context_id=?', (cid,)).fetchone()[0] == 0,
                    'previous manifest oversized')
        return None, [], []
    envelope = json.loads(row[0])
    sdk.require(row[0] == sdk.canonical(envelope), 'canonical previous envelope required')
    manifest = sdk.verify_manifest(envelope, context, trusted_keys, False)
    records, packs, seen, total_bytes = [], [], set(), 0
    for part in manifest['packs']:
        found = db.execute('SELECT body FROM packs WHERE sha256=? AND length(body)<=262144', (part['sha256'],)).fetchone()
        sdk.require(found is not None, 'previous pack missing or oversized')
        total_bytes += len(found[0].encode())
        sdk.require(total_bytes <= MAX_BYTES, 'previous catalog byte bounds')
        pack = sdk.verify_pack(found[0], part, cid)
        for record in pack['records']:
            sdk.require(record['id'] not in seen and len(records) < MAX_RECORDS, 'previous duplicate/record bounds')
            seen.add(record['id'])
            records.append(record)
        packs.append((part['sha256'], found[0]))
    sdk.require(len(records) == manifest['record_count'], 'previous catalog count')
    return envelope, records, packs


def candidate_packs(records, cid):
    packs, pending, total_bytes = [], [], 0
    def flush():
        nonlocal pending, total_bytes
        if not pending:
            return
        body = sdk.canonical({'protocol': sdk.PROTOCOL, 'context_id': cid, 'records': pending})
        total_bytes += len(body.encode())
        sdk.require(total_bytes <= MAX_BYTES and len(packs) < 1024, 'candidate catalog bounds')
        packs.append(({'sha256': sdk.digest(body), 'bytes': len(body.encode()), 'record_count': len(pending)}, body))
        pending = []
    for record in sorted(records, key=lambda value: value['id']):
        trial = sdk.canonical({'protocol': sdk.PROTOCOL, 'context_id': cid, 'records': pending + [record]})
        if len(pending) == 128 or len(trial.encode()) > 262144:
            flush()
        pending.append(record)
    flush()
    return packs


def review(snapshot, expected_sha256, cid, selected_file, attribution_file, output, trusted_keys_file=None):
    snapshot = Path(os.path.abspath(snapshot))
    sdk.require(sdk.HASH.fullmatch(expected_sha256) and sdk.HASH.fullmatch(cid), 'snapshot/context hash required')
    sdk.require(not any(Path(str(snapshot) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
                'closed backup snapshot required')
    sdk.require(snapshot_digest(snapshot) == expected_sha256, 'snapshot digest mismatch')
    selected = sdk.read_json(selected_file)
    sdk.require(isinstance(selected, list) and 1 <= len(selected) <= 1024
                and all(isinstance(rid, str) and sdk.HASH.fullmatch(rid) for rid in selected)
                and len(set(selected)) == len(selected), 'selected IDs must be a unique bounded list')
    attribution = sdk.read_json(attribution_file)
    trusted_keys = sdk.read_json(trusted_keys_file) if trusted_keys_file else {}
    deadline = time.monotonic() + 15
    db = sqlite3.connect(snapshot.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        for table in ('contexts', 'inbox', 'packs', 'manifests'):
            sdk.require(db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone() == ('table',),
                        'catalog table required')
        row = db.execute('SELECT context_json FROM contexts WHERE context_id=? AND length(context_json)<=2048', (cid,)).fetchone()
        sdk.require(row is not None, 'context missing or oversized')
        context = sdk.context(json.loads(row[0]))
        sdk.require(sdk.context_id(context) == cid, 'context hash mismatch')
        previous, records, previous_packs = previous_catalog(db, context, trusted_keys)
        by_id = {record['id']: record for record in records}
        by_id.update({record['id']: record for record in reviewed_records(db, cid, selected)})
        sdk.require(len(by_id) <= MAX_RECORDS, 'candidate record bounds')
    finally:
        db.close()
    sdk.require(snapshot_digest(snapshot) == expected_sha256, 'snapshot changed during review')
    packs = candidate_packs(by_id.values(), cid)
    previous_attribution = previous['manifest']['attribution'] if previous else []
    sdk.require(isinstance(attribution, list) and 1 <= len(attribution) <= 8, 'explicit attribution list required')
    attribution = {sdk.canonical(value): value for value in previous_attribution + attribution}
    manifest = {'protocol': sdk.PROTOCOL, 'context': context, 'context_id': cid,
                'compatibility': 'exact' if all(context[k] is not None for k in sdk.FINGERPRINTS) else 'reference-only',
                'dataset_license': 'MIT', 'attribution': [attribution[key] for key in sorted(attribution)],
                'revision': previous['manifest']['revision'] + 1 if previous else 1,
                'packs': [part for part, _ in packs], 'record_count': len(by_id)}
    sdk.require(1 <= len(manifest['attribution']) <= 8, 'attribution bounds')
    for value in manifest['attribution']:
        sdk.require(isinstance(value, dict) and set(value) == {'name', 'source_url', 'source_commit', 'license'}
                    and value['license'] == 'MIT'
                    and re.fullmatch(r'[A-Za-z0-9 ._-]{1,100}', value['name'])
                    and re.fullmatch(r'https://[A-Za-z0-9./_-]{1,200}', value['source_url'])
                    and re.fullmatch(r'[a-f0-9]{40}', value['source_commit']), 'attribution fields')
    sdk.require(len(sdk.canonical(manifest).encode()) <= 262000, 'manifest byte bounds')
    receipt = {'snapshot_sha256': expected_sha256, 'context_id': cid, 'selected_ids': sorted(selected),
               'previous': previous, 'previous_envelope_sha256': sdk.digest(sdk.canonical(previous)) if previous else None,
               'published': False}
    output = Path(output)
    output.mkdir(mode=0o700)
    (output / 'packs').mkdir(mode=0o700)
    for part, body in packs:
        (output / 'packs' / (part['sha256'] + '.json')).write_text(body)
    if previous:
        (output / 'previous-packs').mkdir(mode=0o700)
        for sha, body in previous_packs:
            (output / 'previous-packs' / (sha + '.json')).write_text(body)
    (output / 'manifest.unsigned.json').write_text(sdk.canonical(manifest) + '\n')
    (output / 'review.json').write_text(sdk.canonical(receipt) + '\n')
    return {'context_id': cid, 'revision': manifest['revision'], 'records': len(by_id),
            'selected': len(selected), 'packs': len(packs), 'published': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('snapshot', 'snapshot-sha256', 'context-id', 'selected-ids', 'attribution', 'output'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--trusted-keys')
    args = parser.parse_args()
    try:
        print(sdk.canonical(review(args.snapshot, args.snapshot_sha256, args.context_id, args.selected_ids,
                                   args.attribution, args.output, args.trusted_keys)))
    except Exception as error:
        parser.exit(1, 'Contribution review failed: ' + str(error) + '\n')
