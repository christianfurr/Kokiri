import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, chmodSync, mkdirSync, symlinkSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { connect } from 'node:net';
import { DatabaseSync } from 'node:sqlite';
import { CatalogDatabase, checkDatabase, hashFile, verifiedBackup } from '../../selfhost/database.mjs';
import { createCatalogServer, HOST_LIMITS } from '../../selfhost/server.mjs';
import { verifyPublished } from '../../selfhost/published.mjs';
import { makeRecord } from '../../src/protocol.ts';

const migration = readFileSync(new URL('../../migrations/0001_catalog.sql', import.meta.url), 'utf8');
const fixture = name => JSON.parse(readFileSync(new URL('../fixtures/' + name, import.meta.url), 'utf8'));
const contribution = fixture('contribution.json');
async function setup(t, options = {}) {
  const root = mkdtempSync(join(tmpdir(), 'kokiri-host-test-'));
  const data = join(root, 'data');
  const database = new CatalogDatabase(data, migration);
  const service = createCatalogServer({ database, ingest: true, ...options });
  const address = await service.listen(0);
  const origin = `http://127.0.0.1:${address.port}`;
  t.after(async () => {
    await new Promise(resolve => { service.server.close(resolve); service.server.closeAllConnections(); });
    database.close(); rmSync(root, { recursive: true, force: true });
  });
  const post = (body, headers = {}) => fetch(origin + '/v1/contributions', { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body) });
  return { root, data, database, service, address, origin, post };
}
function raw(port, payload) {
  return new Promise((resolve, reject) => {
    const socket = connect(port, '127.0.0.1', () => socket.write(payload));
    let body = '';
    socket.setTimeout(2000, () => socket.destroy(new Error('test_socket_timeout')));
    socket.on('data', bytes => { body += bytes; });
    socket.on('error', reject); socket.on('end', () => resolve(body));
  });
}

test('loopback service validates and durably deduplicates concurrent metadata', async t => {
  const s = await setup(t);
  assert.equal(s.address.address, '127.0.0.1');
  const results = await Promise.all(Array.from({ length: 6 }, async () => {
    const r = await s.post(contribution); assert.equal(r.status, 202); return r.json();
  }));
  assert.equal(results.reduce((n, r) => n + r.inserted, 0), 1);
  checkDatabase(s.database.db);
  assert.equal((await fetch(s.origin + '/v1/protocol')).status, 200);
  assert.equal((await fetch(s.origin + '/v1/packs/' + contribution.records[0].id)).status, 404);
  assert.equal((await fetch(s.origin + '/catalog.sqlite')).status, 404);
  const second = new CatalogDatabase(s.data, migration);
  try { assert.equal(second.db.prepare('SELECT records FROM catalog_usage').get().records, 1); } finally { second.close(); }
});

test('invalid/private payloads and excessive bodies leave no inbox records', async t => {
  const s = await setup(t);
  for (const value of [{ ...contribution, source: 'private shader source' }, { ...contribution, records: [] }, '{broken']) {
    assert.equal((await s.post(value)).status, 400);
  }
  assert.equal((await s.post(contribution, { 'Content-Type': 'text/plain' })).status, 400);
  assert.equal((await s.post(' '.repeat(65537))).status, 413);
  assert.equal((await s.post(contribution, { 'Content-Encoding': 'gzip' })).status, 413);
  const chunked = await raw(s.address.port, 'POST /v1/contributions HTTP/1.1\r\nHost: local\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n10001\r\n' + 'x'.repeat(65537) + '\r\n0\r\n\r\n');
  assert.match(chunked, /^HTTP\/1.1 413/);
  assert.equal(s.database.db.prepare('SELECT records FROM catalog_usage').get().records, 0);
});

test('whole-batch capacity rollback and duplicate-at-capacity are preserved', async t => {
  const s = await setup(t);
  s.database.db.exec('UPDATE catalog_limits SET contexts=1,records=1,per_context=1');
  const extra = await makeRecord('S', 'S\t' + 'd'.repeat(64) + '-' + 'b'.repeat(12) + '_b\t0\tm');
  assert.equal((await s.post({ ...contribution, records: [contribution.records[0], extra] })).status, 503);
  assert.equal(s.database.db.prepare('SELECT contexts FROM catalog_usage').get().contexts, 0);
  assert.equal((await s.post(contribution)).status, 202);
  const duplicate = await s.post(contribution); assert.equal(duplicate.status, 202); assert.equal((await duplicate.json()).inserted, 0);
  assert.equal((await s.post({ ...contribution, context: { ...contribution.context, game_version: 'other' } })).status, 503);
  checkDatabase(s.database.db);
});

test('ingress is off by default and rate limits ignore spoofed IP headers', async t => {
  const off = await setup(t, { ingest: false });
  assert.equal((await off.post(contribution)).status, 503);
  const s = await setup(t, { limits: { ...HOST_LIMITS, postsPerMinute: 1 } });
  assert.equal((await s.post(contribution)).status, 202);
  const response = await s.post(contribution, { 'CF-Connecting-IP': '192.0.2.5', 'X-Forwarded-For': '192.0.2.6' });
  assert.equal(response.status, 429); assert.equal(response.headers.get('retry-after'), '60');
  checkDatabase(s.database.db);
});

test('slow request bodies time out; malformed parser inputs do not echo raw bytes', async t => {
  const s = await setup(t, { limits: { ...HOST_LIMITS, bodyTimeoutMs: 80 } });
  const slow = await raw(s.address.port, 'POST /v1/contributions HTTP/1.1\r\nHost: local\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{');
  assert.match(slow, /^HTTP\/1.1 408/);
  const malformed = await raw(s.address.port, 'PRIVATE-PAYLOAD\r\n\r\n');
  assert.match(malformed, /^HTTP\/1.1 400/); assert(!malformed.includes('PRIVATE-PAYLOAD'));
});

test('global request and inflight budgets protect GET as well as POST', async t => {
  const rate = await setup(t, { limits: { ...HOST_LIMITS, requestsPerMinute: 1 } });
  assert.equal((await fetch(rate.origin + '/v1/protocol')).status, 200);
  assert.equal((await fetch(rate.origin + '/v1/protocol')).status, 429);
  const busy = await setup(t, { limits: { ...HOST_LIMITS, inflight: 1, bodyTimeoutMs: 150 } });
  const stalled = connect(busy.address.port, '127.0.0.1');
  stalled.on('error', () => {}); t.after(() => stalled.destroy());
  await new Promise(resolve => stalled.once('connect', resolve));
  stalled.write('POST /v1/contributions HTTP/1.1\r\nHost: local\r\nContent-Length: 20\r\n\r\n{');
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal((await fetch(busy.origin + '/v1/protocol')).status, 503);
});

test('private storage rejects symlinks, permissive directories and changed migration', t => {
  const root = mkdtempSync(join(tmpdir(), 'kokiri-path-test-')); t.after(() => rmSync(root, { recursive: true, force: true }));
  const publicDir = join(root, 'public'); mkdirSync(publicDir); chmodSync(publicDir, 0o755);
  assert.throws(() => new CatalogDatabase(publicDir, migration), /private_directory/);
  const target = join(root, 'target'); mkdirSync(target, { mode: 0o700 });
  const link = join(root, 'link'); symlinkSync(target, link);
  assert.throws(() => new CatalogDatabase(link, migration), /private_directory/);
  const db = new CatalogDatabase(target, migration); db.close();
  assert.throws(() => new CatalogDatabase(target, migration + '\n-- changed'), /schema_mismatch/);
});

test('online backup restores committed inbox and rejects accounting or published-content corruption', async t => {
  const s = await setup(t); await s.post(contribution);
  const snapshot = await verifiedBackup(s.database.db, join(s.root, 'backups'));
  assert.equal(hashFile(snapshot.path), snapshot.sha256);
  const restoreDir = join(s.root, 'restored'); mkdirSync(restoreDir, { mode: 0o700 });
  copyFileSync(snapshot.path, join(restoreDir, 'catalog.sqlite')); chmodSync(join(restoreDir, 'catalog.sqlite'), 0o600);
  const restored = new CatalogDatabase(restoreDir, migration);
  try { checkDatabase(restored.db); assert.equal(restored.db.prepare('SELECT records FROM catalog_usage').get().records, 1); }
  finally { restored.close(); }
  s.database.db.exec('UPDATE catalog_usage SET records=0');
  await assert.rejects(() => verifiedBackup(s.database.db, join(s.root, 'badbackups')), /accounting/);
  s.database.db.exec('UPDATE catalog_usage SET records=1');
  s.database.db.prepare('INSERT INTO packs VALUES(?,?)').run('0'.repeat(64), '{}');
  await assert.rejects(() => verifyPublished(s.database.db, {}), /published_pack_hash/);
});

test('curated signed HTTP downloads keep signature and hash validation after SQLite restore', async t => {
  const s = await setup(t); await s.post(contribution);
  const envelope = fixture('manifest.json'), pack = JSON.stringify(fixture('pack.json'));
  // Pack signature/hash uses canonical JSON, independently checked by verifier.
  const { canonical } = await import('../../src/protocol.ts');
  s.database.db.prepare('INSERT INTO packs VALUES(?,?)').run(envelope.manifest.packs[0].sha256, canonical(JSON.parse(pack)));
  s.database.db.prepare('INSERT INTO manifests VALUES(?,?)').run(envelope.manifest.context_id, canonical(envelope));
  await verifyPublished(s.database.db, fixture('trusted-keys.json'));
  const response = await fetch(s.origin + '/v1/catalogs/' + envelope.manifest.context_id + '/manifest');
  assert.equal(response.status, 200);
  assert.equal((await response.json()).signature, envelope.signature);
  await assert.rejects(() => verifyPublished(s.database.db, {}), /untrusted/);
  s.database.db.prepare('UPDATE manifests SET envelope=?').run(canonical({ ...envelope, manifest: { ...envelope.manifest, revision: 2 } }));
  await assert.rejects(() => verifyPublished(s.database.db, fixture('trusted-keys.json')), /signature/);
});
