"""Apply reviewed selfhost SQL to an explicit local catalog with rollback on error.

Use a closed disposable copy first. This operator command requires pinned public
keys and the independently reviewed SQL digest. It never touches quarantine.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publication', ROOT / 'scripts/prepare-publication.py')
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)
sdk = publication.sdk


def private_file(path, limit):
    path = Path(os.path.abspath(path))
    info = path.lstat()
    sdk.require(stat.S_ISREG(info.st_mode) and info.st_size <= limit and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077 and path.resolve() == path,
                'private regular file required')
    return path


def publication_sql_only(action, first, second, database, source):
    if action == sqlite3.SQLITE_TRANSACTION:
        return sqlite3.SQLITE_OK if first in ('BEGIN', 'ROLLBACK') else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    tables = {'inbox', 'contexts', 'packs', 'manifests', 'catalog_usage', 'catalog_limits', 'context_usage'}
    if action == sqlite3.SQLITE_READ:
        allowed = (database == 'main' and first in tables) or (database == 'temp' and first in ('kokiri_publication_guard', 'sqlite_temp_master'))
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if second == 'changes' else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_CREATE_TEMP_TABLE, sqlite3.SQLITE_DROP_TEMP_TABLE):
        return sqlite3.SQLITE_OK if first == 'kokiri_publication_guard' else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
        allowed = database == 'temp' and first in ('kokiri_publication_guard', 'sqlite_temp_master')
        allowed |= database == 'main' and action == sqlite3.SQLITE_INSERT and first in ('contexts', 'packs', 'manifests')
        allowed |= database == 'main' and action == sqlite3.SQLITE_UPDATE and first == 'manifests' and second == 'envelope'
        allowed |= database == 'main' and source == 'contexts_added' and (
            (action == sqlite3.SQLITE_UPDATE and first == 'catalog_usage') or
            (action == sqlite3.SQLITE_INSERT and first == 'context_usage'))
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def verify_database(db, trusted):
    # Bound SQLite values before Python materializes a corrupt existing row.
    for table, column in (('packs', 'body'), ('manifests', 'envelope')):
        sdk.require(db.execute('SELECT 1 FROM ' + table + ' WHERE typeof(' + column +
                    ") <> 'text' OR length(CAST(" + column + ' AS BLOB)) > 262144 LIMIT 1').fetchone() is None,
                    'published input bounds')
    sdk.require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
                and not db.execute('PRAGMA foreign_key_check').fetchall(), 'catalog integrity')
    actual = db.execute('SELECT (SELECT count(*) FROM contexts), (SELECT count(*) FROM inbox)').fetchone()
    recorded = db.execute('SELECT contexts,records FROM catalog_usage WHERE singleton=1').fetchone()
    sdk.require(actual == recorded and not db.execute(
        'SELECT c.context_id FROM contexts c LEFT JOIN context_usage u USING(context_id) '
        'WHERE u.records IS NULL OR u.records<>(SELECT count(*) FROM inbox i WHERE i.context_id=c.context_id) LIMIT 1'
    ).fetchone(), 'catalog quota accounting')
    for sha, text in db.execute('SELECT sha256,body FROM packs'):
        sdk.require(len(text.encode()) <= 262144 and sdk.digest(text) == sha, 'published pack bounds/hash')
        pack = json.loads(text)
        sdk.verify_pack(text, {'sha256': sha, 'bytes': len(text.encode()),
                              'record_count': len(pack.get('records', []))}, pack.get('context_id'))
    for cid, text in db.execute('SELECT context_id,envelope FROM manifests'):
        sdk.require(len(text.encode()) <= 262144, 'published manifest bounds')
        envelope = json.loads(text)
        manifest = sdk.verify_manifest(envelope, envelope['manifest']['context'], trusted, False)
        sdk.require(manifest['context_id'] == cid, 'published context mismatch')
        ids, total = set(), 0
        for part in manifest['packs']:
            row = db.execute('SELECT body FROM packs WHERE sha256=? AND length(body)<=262144', (part['sha256'],)).fetchone()
            sdk.require(row is not None, 'published pack missing or oversized')
            total += len(row[0].encode())
            sdk.require(total <= 64 * 1024 * 1024, 'published catalog byte bounds')
            for record in sdk.verify_pack(row[0], part, cid)['records']:
                sdk.require(record['id'] not in ids and len(ids) < 100000, 'published record bounds/duplicate')
                ids.add(record['id'])
        sdk.require(len(ids) == manifest['record_count'], 'published count mismatch')


def apply(database, sql_file, expected_sha256, trusted_keys_file):
    database = private_file(database, 1024 ** 3)
    sql_file = private_file(sql_file, 160 * 1024 * 1024)
    sdk.require(isinstance(expected_sha256, str) and sdk.HASH.fullmatch(expected_sha256), 'SQL digest required')
    sql = sql_file.read_text()
    sdk.require(sdk.digest(sql) == expected_sha256 and sql.startswith('BEGIN IMMEDIATE;\n')
                and sql.endswith('COMMIT;\n'), 'reviewed transactional SQL required')
    trusted = sdk.read_json(trusted_keys_file)
    space = os.statvfs(database.parent)
    sdk.require(space.f_bavail * space.f_frsize >= 512 * 1024 * 1024 + 2 * sql_file.stat().st_size,
                'publication disk reserve required')
    db = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5)
    try:
        if hasattr(db, 'enable_load_extension'):
            db.enable_load_extension(False)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA foreign_keys=ON')
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        sdk.require(db.execute('PRAGMA page_count').fetchone()[0] * page_size <= 1024 ** 3, 'catalog size limit')
        db.execute('PRAGMA max_page_count=' + str(1024 ** 3 // page_size))
        deadline = time.monotonic() + 30
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.set_authorizer(publication_sql_only)
        db.executescript(sql[:-len('COMMIT;\n')])
        sdk.require(db.in_transaction, 'publication transaction required')
        db.set_authorizer(None)
        verify_database(db, trusted)
        db.commit()
    except Exception:
        db.set_authorizer(None)
        db.rollback()
        raise
    finally:
        db.close()
    return {'published': True, 'sql_sha256': expected_sha256, 'quarantine_removed': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('database', 'sql', 'sql-sha256', 'trusted-keys'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    try:
        print(sdk.canonical(apply(args.database, args.sql, args.sql_sha256, args.trusted_keys)))
    except Exception as error:
        parser.exit(1, 'Publication import failed: ' + str(error) + '\n')
