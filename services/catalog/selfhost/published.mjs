import { readFileSync, lstatSync } from 'node:fs';
import { sha256, verifyManifest, verifyPack } from '../src/protocol.ts';

export function readTrustedKeys(path) {
  if (!path) return {};
  const st = lstatSync(path);
  if (!st.isFile() || st.size > 16384) throw new Error('invalid_public_trust_store');
  const keys = JSON.parse(readFileSync(path, 'utf8'));
  if (!keys || Array.isArray(keys) || typeof keys !== 'object' || Object.keys(keys).length > 32 ||
      Object.entries(keys).some(([k, v]) => !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(k) || typeof v !== 'string' || !/^[A-Za-z0-9+/]{43}=$/.test(v)))
    throw new Error('invalid_public_trust_store');
  return keys;
}

// Publication is offline. Neither server nor backup has a signing private key.
// A restored DB with a bad/untrusted manifest cannot silently become public.
export async function verifyPublished(db, trustedKeys) {
  for (const row of db.prepare('SELECT sha256,body FROM packs').iterate()) {
    if (await sha256(row.body) !== row.sha256) throw new Error('published_pack_hash');
    const pack = JSON.parse(row.body);
    await verifyPack(row.body, { sha256: row.sha256, bytes: Buffer.byteLength(row.body), record_count: pack.records?.length }, pack.context_id);
  }
  for (const row of db.prepare('SELECT context_id,envelope FROM manifests').iterate()) {
    const envelope = JSON.parse(row.envelope);
    const manifest = await verifyManifest(envelope, trustedKeys, envelope.manifest?.context, false);
    if (row.context_id !== manifest.context_id) throw new Error('published_context');
    const records = new Set();
    for (const part of manifest.packs) {
      const pack = db.prepare('SELECT body FROM packs WHERE sha256=?').get(part.sha256);
      if (!pack) throw new Error('published_pack_missing');
      const verified = await verifyPack(pack.body, part, manifest.context_id);
      for (const r of verified.records) {
        if (records.has(r.id)) throw new Error('published_duplicate');
        records.add(r.id);
      }
    }
    if (records.size !== manifest.record_count) throw new Error('published_record_count');
  }
}
