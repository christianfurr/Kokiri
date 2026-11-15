import { DatabaseSync, backup } from 'node:sqlite';
import { createHash, randomUUID } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, realpathSync, renameSync, rmSync, statfsSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const MAX_DATABASE_BYTES = 1024 * 1024 * 1024;
export const DISK_FLOOR_BYTES = 512 * 1024 * 1024;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

export function hashFile(path) {
  regularPrivateFile(path);
  const fd = openSync(path, 'r');
  try {
    const before = fstatSync(fd), digest = createHash('sha256'), buffer = Buffer.alloc(65536);
    let count = 0, size;
    while ((size = readSync(fd, buffer, 0, buffer.length, null))) { digest.update(buffer.subarray(0, size)); count += size; }
    const after = fstatSync(fd);
    if (count !== before.size || before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs)
      throw new Error('file_changed');
    return digest.digest('hex');
  } finally { closeSync(fd); }
}

export function privateDirectory(path) {
  path = resolve(path);
  if (!existsSync(path)) mkdirSync(path, { mode: 0o700 });
  const st = lstatSync(path);
  if (!st.isDirectory() || st.uid !== process.getuid() || (st.mode & 0o077) || realpathSync(path) !== path)
    throw new Error('private_directory_required');
  return path;
}

export function regularPrivateFile(path) {
  const st = lstatSync(path);
  if (!st.isFile() || st.uid !== process.getuid() || st.nlink !== 1 || (st.mode & 0o077))
    throw new Error('private_file_required');
}

export function diskAvailable(directory) {
  const fs = statfsSync(directory);
  return fs.bavail * fs.bsize >= DISK_FLOOR_BYTES;
}

export function checkDatabase(db) {
  if (db.prepare('PRAGMA quick_check').all().some(row => Object.values(row)[0] !== 'ok') ||
      db.prepare('PRAGMA foreign_key_check').all().length) throw new Error('database_integrity');
  const actual = db.prepare('SELECT (SELECT count(*) FROM contexts) AS contexts, (SELECT count(*) FROM inbox) AS records').get();
  const recorded = db.prepare('SELECT contexts,records FROM catalog_usage WHERE singleton=1').get();
  if (!recorded || actual.contexts !== recorded.contexts || actual.records !== recorded.records ||
      db.prepare('SELECT c.context_id FROM contexts c LEFT JOIN context_usage u USING(context_id) WHERE u.records IS NULL OR u.records<>(SELECT count(*) FROM inbox i WHERE i.context_id=c.context_id) LIMIT 1').get())
    throw new Error('database_accounting');
}

// Only the fixed server queries use this narrow D1-shaped adapter. The HTTP
// surface cannot supply SQL. Each synchronous batch commits all records or none.
export class CatalogDatabase {
  constructor(directory, migration) {
    this.directory = privateDirectory(directory);
    if (!diskAvailable(directory)) throw new Error('disk_floor');
    this.path = join(this.directory, 'catalog.sqlite');
    let fresh = false;
    if (!existsSync(this.path)) {
      closeSync(openSync(this.path, 'wx', 0o600));
      fresh = true;
    }
    regularPrivateFile(this.path);
    for (const suffix of ['-wal', '-shm', '-journal']) {
      if (existsSync(this.path + suffix)) regularPrivateFile(this.path + suffix);
    }
    this.db = new DatabaseSync(this.path, { timeout: 1000, allowExtension: false });
    try {
      this.db.exec('PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL; PRAGMA busy_timeout=1000; PRAGMA trusted_schema=OFF;');
      const migrationHash = hash(migration);
      if (fresh) {
        this.db.exec('BEGIN IMMEDIATE');
        try {
          this.db.exec(migration);
          this.db.exec('CREATE TABLE host_schema(version INTEGER PRIMARY KEY, migration_sha256 TEXT NOT NULL)');
          this.db.prepare('INSERT INTO host_schema VALUES(1,?)').run(migrationHash);
          this.db.exec('COMMIT');
        } catch (error) { this.db.exec('ROLLBACK'); throw error; }
      }
      if (this.db.prepare('SELECT migration_sha256 FROM host_schema WHERE version=1').get()?.migration_sha256 !== migrationHash)
        throw new Error('database_schema_mismatch');
      const pageSize = this.db.prepare('PRAGMA page_size').get().page_size;
      if (this.db.prepare('PRAGMA page_count').get().page_count * pageSize > MAX_DATABASE_BYTES) throw new Error('database_size_limit');
      this.db.exec(`PRAGMA max_page_count=${Math.floor(MAX_DATABASE_BYTES / pageSize)}; PRAGMA journal_mode=WAL; PRAGMA journal_size_limit=16777216; PRAGMA wal_autocheckpoint=256;`);
      checkDatabase(this.db);
    } catch (error) { this.db.close(); throw error; }
  }
  prepare(sql) {
    const statement = this.db.prepare(sql);
    return {
      bind: (...values) => ({
        execute: () => ({ results: statement.all(...values) }),
        first: async () => statement.get(...values) ?? null,
      }),
    };
  }
  async batch(statements) {
    if (!diskAvailable(this.directory)) throw new Error('disk_floor');
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = statements.map(statement => statement.execute());
      this.db.exec('COMMIT');
      return result;
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  close() { this.db.close(); }
}

export async function verifiedBackup(source, directory) {
  directory = privateDirectory(directory);
  const space = statfsSync(directory);
  const estimated = source.prepare('PRAGMA page_count').get().page_count * source.prepare('PRAGMA page_size').get().page_size;
  if (space.bavail * space.bsize < DISK_FLOOR_BYTES + estimated) throw new Error('disk_floor');
  const partial = join(directory, `.backup-${randomUUID()}.partial`);
  const destination = join(directory, `catalog-${Date.now()}-${randomUUID()}.sqlite`);
  closeSync(openSync(partial, 'wx', 0o600));
  try {
    await backup(source, partial);
    regularPrivateFile(partial);
    const restored = new DatabaseSync(partial, { readOnly: true, allowExtension: false });
    try { checkDatabase(restored); } finally { restored.close(); }
    const digest = hashFile(partial);
    const file = openSync(partial, 'r');
    try { fsyncSync(file); } finally { closeSync(file); }
    const receipt = openSync(partial + '.sha256', 'wx', 0o600);
    try { writeFileSync(receipt, digest + '\n'); fsyncSync(receipt); } finally { closeSync(receipt); }
    renameSync(partial, destination);
    renameSync(partial + '.sha256', destination + '.sha256');
    const parent = openSync(directory, 'r');
    try { fsyncSync(parent); } finally { closeSync(parent); }
    return { path: destination, sha256: digest };
  } catch (error) {
    rmSync(destination, { force: true }); rmSync(destination + '.sha256', { force: true });
    throw error;
  } finally { rmSync(partial, { force: true }); rmSync(partial + '.sha256', { force: true }); }
}
