import { build } from 'esbuild';
import { copyFile, mkdir } from 'node:fs/promises';
const outdir = process.argv[2];
if (!outdir) throw new Error('provide_external_output_directory');
await mkdir(outdir, { recursive: true });
await build({ entryPoints: { server: 'selfhost/server.mjs', backup: 'selfhost/backup.mjs', restore: 'selfhost/restore.mjs' }, outdir,
  bundle: true, platform: 'node', target: 'node24', format: 'esm', outExtension: { '.js': '.mjs' }, legalComments: 'inline' });
await copyFile('migrations/0001_catalog.sql', outdir + '/0001_catalog.sql');
await copyFile('../../LICENSE', outdir + '/LICENSE');
await copyFile('../../THIRD_PARTY_NOTICES.md', outdir + '/THIRD_PARTY_NOTICES.md');
