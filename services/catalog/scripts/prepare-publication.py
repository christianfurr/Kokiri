"""Sign reviewed metadata into a fresh SQL file without uploading or changing data.

Default output preserves the first-publication D1 workflow. --selfhost-sql adds
an atomic SQLite transaction guarded by the reviewed previous signed envelope.
"""
import argparse
import base64
import importlib.util
import re
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('catalog', ROOT / 'sdk/python/kokiri_catalog.py')
sdk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sdk)


def read_packs(directory, manifest):
    bodies, record_ids, total = [], set(), 0
    for index in manifest['packs']:
        path = directory / (index['sha256'] + '.json')
        sdk.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 262144, 'pack file bounds')
        text = path.read_text()
        total += len(text.encode())
        sdk.require(total <= 64 * 1024 * 1024, 'catalog byte bounds')
        pack = sdk.verify_pack(text, index, manifest['context_id'])
        for record in pack['records']:
            sdk.require(record['id'] not in record_ids and len(record_ids) < 100000,
                        'duplicate record across packs or catalog record bounds')
            record_ids.add(record['id'])
        bodies.append((index['sha256'], text))
    sdk.require(len(record_ids) == manifest['record_count'], 'catalog count')
    return bodies, record_ids


def reviewed_previous(directory, manifest, record_ids, trusted_keys):
    receipt = sdk.read_json(directory / 'review.json')
    sdk.require(isinstance(receipt, dict) and set(receipt) == {'snapshot_sha256', 'context_id', 'selected_ids',
                'previous', 'previous_envelope_sha256', 'published'}, 'review receipt fields')
    sdk.require(receipt['context_id'] == manifest['context_id'] and receipt['published'] is False
                and isinstance(receipt['snapshot_sha256'], str) and sdk.HASH.fullmatch(receipt['snapshot_sha256']),
                'review receipt identity')
    selected = receipt['selected_ids']
    sdk.require(isinstance(selected, list) and 1 <= len(selected) <= 1024
                and all(isinstance(rid, str) and sdk.HASH.fullmatch(rid) for rid in selected)
                and len(set(selected)) == len(selected) and set(selected) <= record_ids, 'review selected IDs')
    previous = receipt['previous']
    if previous is None:
        sdk.require(receipt['previous_envelope_sha256'] is None and manifest['revision'] == 1, 'first revision required')
        return None
    sdk.require(receipt['previous_envelope_sha256'] == sdk.digest(sdk.canonical(previous)), 'previous envelope digest')
    old = sdk.verify_manifest(previous, manifest['context'], trusted_keys, False)
    sdk.require(manifest['revision'] == old['revision'] + 1, 'next revision required')
    _, previous_ids = read_packs(directory / 'previous-packs', old)
    sdk.require(previous_ids <= record_ids, 'new revision must retain published records')
    sdk.require({sdk.canonical(value) for value in old['attribution']} <=
                {sdk.canonical(value) for value in manifest['attribution']}, 'retain published attribution')
    return previous


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def selfhost_sql(manifest, envelope, bodies, previous):
    cid = quote(manifest['context_id'])
    context = quote(sdk.canonical(manifest['context']))
    sql = ['BEGIN IMMEDIATE;', 'CREATE TEMP TABLE kokiri_publication_guard(ok INTEGER CHECK(ok=1));']
    def guard(condition):
        sql.append('INSERT OR ROLLBACK INTO kokiri_publication_guard VALUES(CASE WHEN ' + condition + ' THEN 1 ELSE 0 END);')
    if previous is None:
        guard(f'NOT EXISTS(SELECT 1 FROM manifests WHERE context_id={cid})')
    else:
        old = quote(sdk.canonical(previous))
        guard(f'EXISTS(SELECT 1 FROM manifests WHERE context_id={cid} AND envelope={old})')
    sql.append(f'INSERT OR IGNORE INTO contexts VALUES({cid},{context});')
    guard(f'EXISTS(SELECT 1 FROM contexts WHERE context_id={cid} AND context_json={context})')
    for sha, body in bodies:
        sha, body = quote(sha), quote(body)
        guard(f'NOT EXISTS(SELECT 1 FROM packs WHERE sha256={sha} AND body<>{body})')
        sql.append(f'INSERT OR IGNORE INTO packs VALUES({sha},{body});')
    if previous is None:
        sql.append(f'INSERT OR ROLLBACK INTO manifests VALUES({cid},{quote(sdk.canonical(envelope))});')
    else:
        sql.append(f'UPDATE OR ROLLBACK manifests SET envelope={quote(sdk.canonical(envelope))} WHERE context_id={cid};')
        guard('changes()=1')
    sql.extend(['DROP TABLE kokiri_publication_guard;', 'COMMIT;'])
    return sql


def prepare(directory, key_path, key_id, output, selfhost=False, trusted_keys_file=None):
    sdk.require(re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', key_id), 'key id')
    directory = Path(directory)
    manifest = sdk.read_json(directory / 'manifest.unsigned.json')
    key = load_pem_private_key(Path(key_path).read_bytes(), password=None)
    sdk.require(isinstance(key, Ed25519PrivateKey), 'Ed25519 required')
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    envelope = {'manifest': manifest, 'key_id': key_id,
                'signature': base64.b64encode(key.sign(sdk.canonical(manifest).encode())).decode()}
    sdk.verify_manifest(envelope, manifest['context'], {key_id: public}, for_warmup=False)
    bodies, record_ids = read_packs(directory / 'packs', manifest)
    if selfhost:
        trusted = sdk.read_json(trusted_keys_file) if trusted_keys_file else {}
        previous = reviewed_previous(directory, manifest, record_ids, trusted)
        sql = selfhost_sql(manifest, envelope, bodies, previous)
    else:
        # Immutable packs precede first publication for D1's non-transactional SQL import.
        # A plain manifest INSERT refuses replacement of any existing revision.
        sql = [f"INSERT OR IGNORE INTO contexts VALUES({quote(manifest['context_id'])},{quote(sdk.canonical(manifest['context']))});"]
        sql.extend(f'INSERT OR IGNORE INTO packs VALUES({quote(sha)},{quote(body)});' for sha, body in bodies)
        sql.append(f"INSERT INTO manifests VALUES({quote(manifest['context_id'])},{quote(sdk.canonical(envelope))});")
    text = '\n'.join(sql) + '\n'
    with open(output, 'x', opener=lambda path, flags: __import__('os').open(path, flags, 0o600)) as stream:
        stream.write(text)
    return {'context_id': manifest['context_id'], 'records': manifest['record_count'], 'packs': len(bodies),
            'revision': manifest['revision'], 'key_id': key_id, 'public_key': public, 'uploaded': False,
            'transactional': selfhost, 'sql_sha256': sdk.digest(text)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('reviewed-dir', 'signing-key', 'key-id', 'output-sql'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--selfhost-sql', action='store_true')
    parser.add_argument('--trusted-keys')
    args = parser.parse_args()
    try:
        print(sdk.canonical(prepare(args.reviewed_dir, args.signing_key, args.key_id, args.output_sql,
                                   args.selfhost_sql, args.trusted_keys)))
    except Exception as error:
        parser.exit(1, 'Publication preparation failed: ' + str(error) + '\n')
