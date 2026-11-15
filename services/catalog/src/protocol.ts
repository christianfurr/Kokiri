/** Open metadata protocol. No shader source or native executable payloads. */
export const PROTOCOL = 'kokiri-catalog/1';
export const LIMITS = { body: 65536, batch: 64, row: 4096, pack: 262144, packRecords: 128, packs: 1024 } as const;
export type Context = {
  game_id: string; game_version: string; game_content_sha256: string | null;
  recipe_format: 'mng-list-v1'; backend: 'metal' | 'vulkan' | 'd3d12'; shader_chain: string;
  translator_sha256: string | null; compiler_sha256: string | null;
  target_sha256: string | null; options_sha256: string | null;
};
export type RecordEntry = { id: string; kind: string; row: string };
export type Contribution = { protocol: typeof PROTOCOL; context: Context; records: RecordEntry[] };
export type Pack = { protocol: typeof PROTOCOL; context_id: string; records: RecordEntry[] };
export type Manifest = {
  protocol: typeof PROTOCOL; context: Context; context_id: string;
  compatibility: 'exact' | 'reference-only'; dataset_license: 'MIT';
  attribution: { name: string; source_url: string; source_commit: string; license: 'MIT' }[];
  revision: number; packs: { sha256: string; bytes: number; record_count: number }[]; record_count: number;
};
export type SignedManifest = { manifest: Manifest; key_id: string; signature: string };
const HASH = /^[a-f0-9]{64}$/;
const VARIANT = /^[a-f0-9]{64}-[a-f0-9]{12}_b$/;
const TOKEN = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const enc = new TextEncoder();
const ascii = (value: string) => [...value].every(c => c === '\t' || c.charCodeAt(0) >= 32 && c.charCodeAt(0) <= 126);
export function check(ok: unknown, reason: string): asserts ok { if (!ok) throw new Error(reason); }
export function object(value: unknown, keys: string[]): Record<string, unknown> {
  check(value !== null && typeof value === 'object' && !Array.isArray(value), 'object required');
  const o = value as Record<string, unknown>;
  check(Object.keys(o).sort().join(',') === [...keys].sort().join(','), 'unexpected or missing fields');
  return o;
}
export function canonical(value: unknown): string {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') { check(Number.isSafeInteger(value), 'integer required'); return String(value); }
  if (typeof value === 'string') { check(ascii(value), 'ASCII required'); return JSON.stringify(value); }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  check(value !== null && typeof value === 'object', 'invalid JSON value');
  return '{' + Object.keys(value).sort().map(k => canonical(k) + ':' + canonical((value as Record<string, unknown>)[k])).join(',') + '}';
}
export async function sha256(value: string | Uint8Array): Promise<string> {
  const bytes = typeof value === 'string' ? enc.encode(value) : value;
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes as BufferSource))].map(x => x.toString(16).padStart(2, '0')).join('');
}
export function validateContext(value: unknown): Context {
  const o = object(value, ['game_id','game_version','game_content_sha256','recipe_format','backend','shader_chain','translator_sha256','compiler_sha256','target_sha256','options_sha256']);
  for (const k of ['game_id','game_version','shader_chain']) check(typeof o[k] === 'string' && ascii(o[k]) && TOKEN.test(o[k]), 'invalid context token');
  check(o.recipe_format === 'mng-list-v1' && ['metal','vulkan','d3d12'].includes(o.backend as string), 'unsupported adapter/backend');
  for (const k of ['game_content_sha256','translator_sha256','compiler_sha256','target_sha256','options_sha256']) check(o[k] === null || typeof o[k] === 'string' && o[k].length === 64 && HASH.test(o[k]), 'invalid context fingerprint');
  return o as Context;
}
export function exactContext(context: Context): boolean {
  return ['game_content_sha256','translator_sha256','compiler_sha256','target_sha256','options_sha256'].every(k => context[k as keyof Context] !== null);
}
export async function contextId(context: Context): Promise<string> { return sha256(canonical(validateContext(context))); }
function pipeline(text: string): boolean {
  if (/^[a-f0-9]{1088}$/.test(text)) return true;
  const p = /^([a-f0-9_-]{0,80}):([a-f0-9_-]{0,80}):((?:[a-f0-9]{2}|z[a-f0-9]{1,3}\.)*)$/.exec(text);
  if (!p || ![p[1],p[2]].every(x => x === '' || x === '-' || VARIANT.test(x))) return false;
  let n = 160; // two 80-byte stage names, followed by the 384-byte state
  for (const token of p[3].matchAll(/z([a-f0-9]+)\.|[a-f0-9]{2}/g)) {
    n += token[1] ? parseInt(token[1],16) : 1;
    if (n > 544) return false;
  }
  return n === 544;
}
function deps(text: string): boolean {
  try {
    const d = JSON.parse(text);
    if (!d || typeof d !== 'object' || Array.isArray(d) || Object.keys(d).some(k=>!['attr','fout','img','tex'].includes(k))) return false;
    for (const [group, slots] of Object.entries(d)) {
      if (!slots || typeof slots !== 'object' || Array.isArray(slots) || Object.keys(slots).length > 64) return false;
      for (const [slot, value] of Object.entries(slots)) {
        if (!/^\d{1,3}$/.test(slot) || Number(slot) > 255) return false;
        const type = (v: unknown) => typeof v === 'string' && /^[a-zA-Z0-9_*<>,. -]{1,64}$/.test(v);
        if (group === 'img' && value && typeof value === 'object' && !Array.isArray(value)) {
          const o = object(value, ['fmt','type']); if (!type(o.fmt) || !type(o.type)) return false;
        } else if (!type(value)) return false;
      }
    }
    return canonical(d) === text;
  } catch { return false; }
}
/** Full tab-separated metadata row; no locator/source/path row is accepted. */
export function validateRow(kind: string, row: string): void {
  check(typeof row === 'string' && row.length > 0 && enc.encode(row).length <= LIMITS.row && ascii(row), 'invalid row bytes');
  const f = row.split('\t'); check(f[0] === kind, 'kind mismatch');
  if (kind === 'V' || kind === 'A') {
    check(f.length === 3 && (kind === 'V' ? HASH : /^[a-f0-9]{12}$/).test(f[1]) && deps(f[2]), 'invalid binding recipe'); return;
  }
  const flags = f.pop(); check(typeof flags === 'string' && /^(?:m|t|mt|tm)?$/.test(flags), 'invalid flags');
  let valid = false;
  if (kind === 'S') valid = f.length === 3 && VARIANT.test(f[1]) && /^(0|1|5)$/.test(f[2]);
  if (kind === 'C') valid = f.length === 2 && VARIANT.test(f[1]);
  if (kind === 'R') valid = f.length === 2 && pipeline(f[1]);
  if (kind === 'M') valid = f.length === 3 && (f[1] === '-' || VARIANT.test(f[1])) && pipeline(f[2]);
  if (kind === 'T') valid = f.length === 3 && pipeline(f[1]) && /^(?:\d{1,3}:[0-7];){1,8}$/.test(f[2]);
  // Border recipes require a separately versioned adapter; rejecting is safer than free-form numeric strings.
  check(valid, 'unsupported or malformed recipe');
}
export async function makeRecord(kind: string, row: string): Promise<RecordEntry> {
  validateRow(kind,row); return {id: await sha256(canonical({kind,row})), kind,row};
}
export async function validateRecord(value: unknown): Promise<RecordEntry> {
  const o = object(value,['id','kind','row']);
  check(typeof o.id === 'string' && HASH.test(o.id) && typeof o.kind === 'string' && typeof o.row === 'string', 'invalid record');
  const expected = await makeRecord(o.kind,o.row); check(o.id === expected.id, 'record hash mismatch'); return expected;
}
export async function validateContribution(value: unknown): Promise<Contribution> {
  const o = object(value,['protocol','context','records']); check(o.protocol === PROTOCOL,'protocol mismatch');
  const context = validateContext(o.context); check(Array.isArray(o.records) && o.records.length > 0 && o.records.length <= LIMITS.batch,'batch bounds');
  const records = await Promise.all(o.records.map(validateRecord));
  check(new Set(records.map(r => r.id)).size === records.length,'duplicate records in batch');
  const result = {protocol: PROTOCOL,context,records} as Contribution;
  check(enc.encode(canonical(result)).length <= LIMITS.body,'body bounds'); return result;
}
export async function validateManifest(value: unknown): Promise<Manifest> {
  const o = object(value,['protocol','context','context_id','compatibility','dataset_license','attribution','revision','packs','record_count']);
  check(o.protocol === PROTOCOL && o.dataset_license === 'MIT','manifest protocol/license');
  const context = validateContext(o.context); check(o.context_id === await contextId(context),'manifest context hash');
  check(o.compatibility === (exactContext(context) ? 'exact' : 'reference-only'),'manifest compatibility');
  check(Number.isSafeInteger(o.revision) && (o.revision as number) >= 1,'manifest revision');
  check(Array.isArray(o.attribution) && o.attribution.length > 0 && o.attribution.length <= 8,'attribution bounds');
  for (const a of o.attribution) {
    const p = object(a,['name','source_url','source_commit','license']);
    check(typeof p.name === 'string' && /^[A-Za-z0-9 ._-]{1,100}$/.test(p.name) && p.license === 'MIT','attribution');
    check(typeof p.source_url === 'string' && /^https:\/\/[A-Za-z0-9./_-]{1,200}$/.test(p.source_url),'attribution URL');
    check(typeof p.source_commit === 'string' && /^[a-f0-9]{40}$/.test(p.source_commit),'attribution commit');
  }
  check(Array.isArray(o.packs) && o.packs.length <= LIMITS.packs,'pack index bounds');
  let count = 0; const seen = new Set();
  for (const item of o.packs) {
    const p = object(item,['sha256','bytes','record_count']);
    check(typeof p.sha256 === 'string' && HASH.test(p.sha256) && !seen.has(p.sha256),'pack hash'); seen.add(p.sha256);
    check(Number.isSafeInteger(p.bytes) && (p.bytes as number) > 0 && (p.bytes as number) <= LIMITS.pack,'pack bytes');
    check(Number.isSafeInteger(p.record_count) && (p.record_count as number) > 0 && (p.record_count as number) <= LIMITS.packRecords,'pack count'); count += p.record_count as number;
  }
  check(o.record_count === count,'manifest count'); return o as Manifest;
}
export function base64(bytes: Uint8Array): string { return btoa(String.fromCharCode(...bytes)); }
export function unbase64(value: string): Uint8Array { check(/^[A-Za-z0-9+/]+={0,2}$/.test(value),'base64'); return Uint8Array.from(atob(value),c=>c.charCodeAt(0)); }
/** Keys come from the application/recompiler trust store, NEVER from this envelope. */
export async function verifyManifest(value: unknown, trustedKeys: Record<string,string>, expected: Context, forWarmup = true): Promise<Manifest> {
  const o = object(value,['manifest','key_id','signature']);
  check(typeof o.key_id === 'string' && TOKEN.test(o.key_id) && typeof trustedKeys[o.key_id] === 'string','untrusted signing key');
  check(typeof o.signature === 'string' && o.signature.length === 88,'signature');
  const manifest = await validateManifest(o.manifest);
  const key = await crypto.subtle.importKey('raw',unbase64(trustedKeys[o.key_id]) as BufferSource,{name:'Ed25519'},false,['verify']);
  check(await crypto.subtle.verify('Ed25519',key,unbase64(o.signature) as BufferSource,enc.encode(canonical(manifest))),'invalid manifest signature');
  check(canonical(manifest.context) === canonical(validateContext(expected)),'incompatible context');
  check(!forWarmup || manifest.compatibility === 'exact','reference metadata cannot warm a runtime');
  return manifest;
}
export async function verifyPack(text: string, index: Manifest['packs'][number], context_id: string): Promise<Pack> {
  check(enc.encode(text).length === index.bytes && await sha256(text) === index.sha256,'pack integrity');
  const p = object(JSON.parse(text),['protocol','context_id','records']);
  check(p.protocol === PROTOCOL && p.context_id === context_id && Array.isArray(p.records) && p.records.length === index.record_count,'pack context/count');
  check(p.records.length <= LIMITS.packRecords && index.bytes <= LIMITS.pack,'pack bounds');
  const records = await Promise.all(p.records.map(validateRecord));
  check(new Set(records.map(r=>r.id)).size === records.length,'pack duplicates');
  return {protocol:PROTOCOL,context_id,records};
}
