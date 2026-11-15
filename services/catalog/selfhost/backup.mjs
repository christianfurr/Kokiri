import { DatabaseSync } from 'node:sqlite';
import { lstatSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { checkDatabase, hashFile, privateDirectory, regularPrivateFile, verifiedBackup } from './database.mjs';
import { readTrustedKeys, verifyPublished } from './published.mjs';

process.umask(0o077);
try {
  const data = privateDirectory(process.env.KOKIRI_CATALOG_DATA);
  const directory = privateDirectory(process.env.KOKIRI_CATALOG_BACKUPS);
  const path = join(data, 'catalog.sqlite');
  regularPrivateFile(path);
  const db = new DatabaseSync(path, { readOnly: true, timeout: 1000, allowExtension: false });
  let result;
  const keys = readTrustedKeys(process.env.KOKIRI_CATALOG_TRUSTED_KEYS);
  try { checkDatabase(db); await verifyPublished(db, keys); result = await verifiedBackup(db, directory); } finally { db.close(); }
  const restored = new DatabaseSync(result.path, { readOnly: true, allowExtension: false });
  try { await verifyPublished(restored, keys); } finally { restored.close(); }
  // Only our named, owner-private regular snapshots are eligible for retention.
  const files = readdirSync(directory).filter(n => /^catalog-\d+-[a-f0-9-]{36}\.sqlite$/.test(n)).sort((a, b) => lstatSync(join(directory, b)).mtimeMs - lstatSync(join(directory, a)).mtimeMs);
  for (const name of files.slice(7)) {
    const old = join(directory, name); regularPrivateFile(old); regularPrivateFile(old + '.sha256');
    const expected = readFileSync(old + '.sha256', 'utf8').trim();
    if (hashFile(old) !== expected) throw new Error('backup_changed');
    rmSync(old); rmSync(old + '.sha256');
  }
  console.log(JSON.stringify({ event: 'backup_verified', filename: result.path.split('/').pop(), sha256: result.sha256 }));
} catch { console.error(JSON.stringify({ event: 'backup_failed' })); process.exitCode = 1; }
