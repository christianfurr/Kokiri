import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:net';
import { hashFile } from '../../selfhost/database.mjs';

const stage = process.env.KOKIRI_TEST_STAGE && resolve(process.env.KOKIRI_TEST_STAGE);
const run = (args, env) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, args, { env }); let out = '', error = '';
  child.stdout.on('data', b => { out += b; }); child.stderr.on('data', b => { error += b; });
  child.once('error', reject); child.once('close', code => resolve({ code, out, error }));
});
function fixtureRoot(t) {
  const root = mkdtempSync(join(tmpdir(), 'kokiri-lifecycle-'));
  for (const part of ['data', 'backups']) mkdirSync(join(root, part), { mode: 0o700 });
  writeFileSync(join(root, 'keys.json'), '{}\n', { mode: 0o600 });
  writeFileSync(join(root, 'outside-canary'), 'synthetic non-secret canary', { mode: 0o600 });
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return { root, env: { ...process.env, KOKIRI_CATALOG_DATA: join(root, 'data'), KOKIRI_CATALOG_BACKUPS: join(root, 'backups'), KOKIRI_CATALOG_TRUSTED_KEYS: join(root, 'keys.json'), KOKIRI_CATALOG_INGEST: '0' } };
}

test('bundled CLI starts under file permissions, closes gracefully, snapshots and restores without overwrite', { skip: !stage }, async t => {
  const { root, env } = fixtureRoot(t);
  const socket = createServer(); await new Promise(r => socket.listen(0, '127.0.0.1', r));
  const port = socket.address().port; await new Promise(r => socket.close(r));
  const child = spawn(process.execPath, ['--permission', '--allow-fs-read=' + stage, '--allow-fs-read=' + root, '--allow-fs-write=' + join(root, 'data'), join(stage, 'server.mjs')], { env: { ...env, KOKIRI_CATALOG_PORT: String(port) } });
  let stdout = '', stderr = '';
  child.stdout.on('data', b => { stdout += b; }); child.stderr.on('data', b => { stderr += b; });
  const done = new Promise(r => child.once('close', code => r(code)));
  t.after(async () => { if (child.exitCode === null) child.kill('SIGTERM'); await done; });
  let ready = false;
  for (let n = 0; n < 50; n++) {
    if (child.exitCode !== null) assert.fail('CLI startup failed: ' + stderr);
    try {
      const r = await fetch(`http://127.0.0.1:${port}/v1/protocol`);
      assert.equal(r.status, 200); ready = true; break;
    } catch { await new Promise(r => setTimeout(r, 20)); }
  }
  assert(ready);
  const off = await fetch(`http://127.0.0.1:${port}/v1/contributions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(off.status, 503);
  child.kill('SIGTERM'); assert.equal(await done, 0);
  assert(stdout.includes('catalog_started')); assert(!stdout.includes('synthetic non-secret'));
  for (let i = 0; i < 8; i++) {
    const b = await run([join(stage, 'backup.mjs')], env);
    assert.equal(b.code, 0, b.error + b.out);
  }
  const snapshots = readdirSync(join(root, 'backups')).filter(n => n.endsWith('.sqlite'));
  assert.equal(snapshots.length, 7);
  for (const name of snapshots) {
    const file = join(root, 'backups', name);
    assert.equal(hashFile(file), readFileSync(file + '.sha256', 'utf8').trim());
  }
  const backup = join(root, 'backups', snapshots[0]); const digest = hashFile(backup);
  const restoreEnv = { ...env, KOKIRI_CATALOG_RESTORE_ROOT: join(root, 'restored') };
  const restored = await run([join(stage, 'restore.mjs'), backup, digest], restoreEnv);
  assert.equal(restored.code, 0, restored.error + restored.out); assert(restored.out.includes('"promoted":false'));
  assert.equal((await run([join(stage, 'restore.mjs'), backup, digest], restoreEnv)).code, 1);
  assert.equal((await run([join(stage, 'restore.mjs'), backup, '0'.repeat(64)], { ...env, KOKIRI_CATALOG_RESTORE_ROOT: join(root, 'bad-restore') })).code, 1);
});

test('runtime permission layer denies outside files and child execution', { skip: !stage }, async t => {
  const { root } = fixtureRoot(t);
  const read = await run(['--permission', '--allow-fs-read=' + stage, '-e', `try { require('node:fs').readFileSync(process.argv[1]); process.exit(1); } catch (e) { process.exit(e.code==='ERR_ACCESS_DENIED'?0:2); }`, join(root, 'outside-canary')], process.env);
  assert.equal(read.code, 0);
  const exec = await run(['--permission', '-e', `try { require('node:child_process').spawnSync('/bin/true'); process.exit(1); } catch (e) { process.exit(e.code==='ERR_ACCESS_DENIED'?0:2); }`], process.env);
  assert.equal(exec.code, 0);
});
