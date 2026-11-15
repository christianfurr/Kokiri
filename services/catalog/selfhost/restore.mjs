import { constants, copyFileSync, chmodSync, mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { CatalogDatabase, hashFile, privateDirectory } from './database.mjs';
import { readTrustedKeys, verifyPublished } from './published.mjs';

// Only restore to a fresh directory. Never stop a service, replace live data,
// change symlinks, or promote the result from this tool.
process.umask(0o077);
try {
  const [source, expected] = process.argv.slice(2);
  const output = process.env.KOKIRI_CATALOG_RESTORE_ROOT;
  if (!source || !/^[a-f0-9]{64}$/.test(expected) || !output || hashFile(source) !== expected)
    throw new Error('restore_input');
  mkdirSync(resolve(output), { mode: 0o700 }); // deliberately not recursive
  const directory = privateDirectory(output);
  copyFileSync(source, join(directory, 'catalog.sqlite'), constants.COPYFILE_EXCL);
  chmodSync(join(directory, 'catalog.sqlite'), 0o600);
  if (hashFile(join(directory, 'catalog.sqlite')) !== expected) throw new Error('restore_changed');
  const db = new CatalogDatabase(directory, readFileSync(new URL('./0001_catalog.sql', import.meta.url), 'utf8'));
  try { await verifyPublished(db.db, readTrustedKeys(process.env.KOKIRI_CATALOG_TRUSTED_KEYS)); } finally { db.close(); }
  console.log(JSON.stringify({ event: 'restore_verified', promoted: false }));
} catch { console.error(JSON.stringify({ event: 'restore_failed', promoted: false })); process.exitCode = 1; }
