import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {PROTOCOL, canonical, contextId, makeRecord, validateContribution, verifyManifest, verifyPack, base64, sha256, validateRow, type Context, type Manifest} from '../src/protocol.ts';
import {CatalogQueue,type QueueState} from '../sdk/typescript/client.ts';
import worker from '../src/worker.ts';
const context:Context={game_id:'oot',game_version:'131072',game_content_sha256:'1'.repeat(64),recipe_format:'mng-list-v1',backend:'metal',shader_chain:'mng-v28',translator_sha256:'2'.repeat(64),compiler_sha256:'3'.repeat(64),target_sha256:'4'.repeat(64),options_sha256:'5'.repeat(64)};
const variant='a'.repeat(64)+'-'+'b'.repeat(12)+'_b';
const record=await makeRecord('S',`S\t${variant}\t0\tm`);
const contribution={protocol:PROTOCOL,context,records:[record]};
let mf:Miniflare;let manifest:Manifest;let signed:unknown;let keys:Record<string,string>;let pack:string;
before(async()=>{
  const bundled=await build({entryPoints:['src/worker.ts'],bundle:true,format:'esm',platform:'browser',write:false});
  mf=new Miniflare({...convertV4MiniflareOptions({modules:true,script:bundled.outputFiles[0].text,compatibilityDate:'2026-11-15',d1Databases:{DB:'catalog-test'}}),telemetry:{enabled:false},enableDevRegistry:false,logRequests:false});
  const db=await mf.getD1Database('DB');const sql=await readFile('migrations/0001_catalog.sql','utf8');
  // exec accepts one SQL statement per line, including the single-line triggers.
  await db.exec(sql.split('\n').filter(x=>x.trim()&&!x.startsWith('--')).join('\n'));
  const cid=await contextId(context);pack=canonical({protocol:PROTOCOL,context_id:cid,records:[record]});
  manifest={protocol:PROTOCOL,context,context_id:cid,compatibility:'exact',dataset_license:'MIT',attribution:[{name:'Synthetic test metadata',source_url:'https://example.invalid/test',source_commit:'a'.repeat(40),license:'MIT'}],revision:1,packs:[{sha256:await sha256(pack),bytes:Buffer.byteLength(pack),record_count:1}],record_count:1};
  signed=JSON.parse(await readFile('tests/fixtures/manifest.json','utf8'));
  keys=JSON.parse(await readFile('tests/fixtures/trusted-keys.json','utf8'));
  assert.deepEqual((signed as any).manifest,manifest);
  await db.prepare('INSERT INTO contexts VALUES(?,?)').bind(cid,canonical(context)).run();
  await db.prepare('INSERT INTO packs VALUES(?,?)').bind(manifest.packs[0].sha256,pack).run();
  await db.prepare('INSERT INTO manifests VALUES(?,?)').bind(cid,canonical(signed)).run();
  // Synthetic checked-in fixture only; tests never write source or production keys.
});
after(async()=>{await mf?.dispose();});
const post=(value:unknown)=>mf.dispatchFetch('https://catalog.invalid/v1/contributions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
test('actual Worker/D1 concurrent duplicate submissions quarantine exactly once',async()=>{
  const responses=await Promise.all(Array.from({length:8},()=>post(contribution)));
  const rows=await Promise.all(responses.map(async r=>{assert.equal(r.status,202);return r.json() as Promise<any>;}));
  assert.equal(rows.reduce((n,r)=>n+r.inserted,0),1);
  const db=await mf.getD1Database('DB');assert.equal((await db.prepare('SELECT count(*) AS n FROM inbox').first<any>()).n,1);
  assert(rows.every(r=>r.state==='quarantined'&&r.accepted_ids[0]===record.id));
});
test('malformed/unbounded/private payloads rejected without insert',async()=>{
  for(const bad of [ {...contribution,source:'shader code'}, {...contribution,records:[]}, {...contribution,records:Array(65).fill(record)}, {...contribution,records:[record,record]}, {...contribution,records:[{...record,id:'0'.repeat(64)}]}, {...contribution,context:{...context,username:'person'}}, {...contribution,records:[{...record,kind:'L',row:'L\tprivate/path'}]} ])assert.equal((await post(bad)).status,400);
  assert.equal((await mf.dispatchFetch('https://catalog.invalid/v1/contributions',{method:'POST',headers:{'Content-Type':'application/json'},body:' '.repeat(65537)})).status,400);
  assert.equal((await mf.dispatchFetch('https://catalog.invalid/v1/contributions',{method:'POST',body:'{}'})).status,400);
});
test('curated download verifies pinned key, exact context and pack hash',async()=>{
  const response=await mf.dispatchFetch(`https://catalog.invalid/v1/catalogs/${manifest.context_id}/manifest`);assert.equal(response.status,200);
  const m=await verifyManifest(await response.json(),keys,context);
  const p=await mf.dispatchFetch(`https://catalog.invalid/v1/packs/${m.packs[0].sha256}`);assert.equal(p.status,200);
  assert.equal((await verifyPack(await p.text(),m.packs[0],m.context_id)).records[0].id,record.id);
  assert.equal((await mf.dispatchFetch(`https://catalog.invalid/v1/packs/${record.id}`)).status,404);
});
test('tampered manifest/untrusted signer/incompatible backend or chain never warm',async()=>{
  await assert.rejects(()=>verifyManifest({...signed as any,manifest:{...manifest,revision:2}},keys,context),/signature/);
  await assert.rejects(()=>verifyManifest(signed,{},context),/untrusted/);
  for(const expected of [{...context,backend:'vulkan'},{...context,shader_chain:'mng-v23'},{...context,compiler_sha256:'8'.repeat(64)}])await assert.rejects(()=>verifyManifest(signed,keys,expected as Context),/incompatible/);
  await assert.rejects(()=>verifyPack(pack+' ',manifest.packs[0],manifest.context_id),/integrity/);
  await assert.rejects(()=>verifyPack(pack,manifest.packs[0],'0'.repeat(64)),/context/);
});
test('packed state zero runs are bounded and paths/source syntax cannot enter recipes',()=>{
  validateRow('R',`R\t${variant}:${variant}:z180.\tm`);
  for(const row of [`R\t${variant}:${variant}:zfff.\tm`,`R\t${variant}:${variant}:z100000000.\tm`,record.row+'\n','L\tmodule:private\tfoo','S\t../../path\t0\tm','V\t'+'a'.repeat(64)+'\t{"attr":{},"fout":{},"img":{},"tex":{"0":"#include <private>"}}'])assert.throws(()=>validateRow(row[0],row));
});
test('optional rate-limit denial avoids body parsing and database access',async()=>{
  let key='';
  const response=await worker.fetch(new Request('https://catalog.invalid/v1/contributions',{method:'POST',body:'not json'}),{
    DB:null as any,INGEST_RATE_LIMIT:{limit:async(value:{key:string})=>{key=value.key;return {success:false};}} as any
  });
  assert.equal(response.status,429);assert.equal(key,'metadata-ingress-v1');
});
test('offline queue preserves records, deduplicates, honors disabled default and backoff',async()=>{
  let state:QueueState={consent:'undecided',pending:[],failures:0,retry_at:0};let calls=0;
  const store={load:async()=>structuredClone(state),save:async(s:QueueState)=>{state=structuredClone(s);}};
  const q=new CatalogQueue(store,async()=>{calls++;throw Error('offline');});
  await assert.rejects(()=>q.enqueue(contribution),/consent/);assert.equal((await q.flush(100)).sent,0);assert.equal(calls,0);
  await q.consent('enabled');await q.enqueue(contribution);await q.enqueue(contribution);assert.equal(state.pending.length,1);
  await q.flush(100);assert.equal(calls,1);assert.equal(state.pending.length,1);await q.flush(101);assert.equal(calls,1);
  await q.consent('disabled');await q.flush(1000);assert.equal(calls,1);
});
test('switching consent off during first request prevents second chunk',async()=>{
  let state:QueueState={consent:'enabled',pending:[contribution,{...contribution,records:[await makeRecord('S',`S\t${'c'.repeat(64)}-${'b'.repeat(12)}_b\t0\tm`)]}],failures:0,retry_at:0};let calls=0;let off:Promise<void>;
  const store={load:async()=>structuredClone(state),save:async(s:QueueState)=>{state=structuredClone(s);}};
  const q=new CatalogQueue(store,async e=>{calls++;off=q.consent('disabled');return {protocol:PROTOCOL,context_id:await contextId(e.context),state:'quarantined',accepted_ids:e.records.map(r=>r.id)};});
  await q.flush(100);await off!;assert.equal(calls,1);assert.equal(state.pending.length,1);assert.equal(state.consent,'disabled');
});
test('failed opt-out persistence still blocks future requests this session',async()=>{
  const state:QueueState={consent:'enabled',pending:[contribution],failures:0,retry_at:0};let calls=0;
  const q=new CatalogQueue({load:async()=>structuredClone(state),save:async()=>{throw Error('disk full');}},async()=>{calls++;});
  await assert.rejects(()=>q.consent('disabled'),/disk full/);await q.flush(100);assert.equal(calls,0);
});
test('small-cap counters are atomic under overflow, concurrent new keys and duplicate-at-capacity',async()=>{
  const db=await mf.getD1Database('DB');
  await db.prepare('UPDATE catalog_limits SET contexts=2,records=2,per_context=2').run();
  const r1=await makeRecord('S',`S\t${'d'.repeat(64)}-${'b'.repeat(12)}_b\t0\tm`);
  const r2=await makeRecord('S',`S\t${'e'.repeat(64)}-${'b'.repeat(12)}_b\t0\tm`);
  assert.equal((await post({...contribution,records:[r1,r2]})).status,503);
  assert.deepEqual(await db.prepare('SELECT contexts,records FROM catalog_usage').first(),{contexts:1,records:1});
  assert.equal((await db.prepare('SELECT records FROM context_usage').first<any>()).records,1);
  const concurrent=await Promise.all([post({...contribution,records:[r1]}),post({...contribution,records:[r2]})]);
  assert.deepEqual(concurrent.map(r=>r.status).sort(),[202,503]);
  assert.equal((await db.prepare('SELECT records FROM catalog_usage').first<any>()).records,2);
  const duplicate=await post(contribution);assert.equal(duplicate.status,202);assert.equal((await duplicate.json() as any).inserted,0);
  assert.equal((await db.prepare('SELECT records FROM catalog_usage').first<any>()).records,2);
  // Promotion/review removes quarantine rows explicitly; delete accounting
  // releases capacity without scanning/recomputing the whole inbox.
  await db.prepare('DELETE FROM inbox WHERE record_id<>?').bind(record.id).run();
  assert.equal((await db.prepare('SELECT records FROM catalog_usage').first<any>()).records,1);
  assert.equal((await post({...contribution,records:[r1]})).status,202);
  // A failed multi-statement batch also rolls back a newly created context.
  assert.equal((await post({...contribution,context:{...context,game_version:'other'}})).status,503);
  assert.equal((await db.prepare('SELECT contexts FROM catalog_usage').first<any>()).contexts,1);
  await db.prepare('DELETE FROM inbox').run();
  await db.prepare('DELETE FROM contexts WHERE context_id NOT IN (SELECT context_id FROM manifests)').run();
  assert.equal((await db.prepare('SELECT records FROM catalog_usage').first<any>()).records,0);
});
