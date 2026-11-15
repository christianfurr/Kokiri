import { PROTOCOL, LIMITS, canonical, contextId, validateContribution } from './protocol.ts';
export interface Env { DB: D1Database; INGEST_RATE_LIMIT?: RateLimit }
const json = (body: unknown, status = 200, cache = 'no-store') => new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json','Cache-Control':cache,'X-Content-Type-Options':'nosniff'}});
async function readBody(request: Request): Promise<unknown> {
  if (request.headers.get('Content-Type')?.split(';')[0] !== 'application/json') throw new Error('JSON required');
  if (Number(request.headers.get('Content-Length')) > LIMITS.body) throw new Error('body bounds');
  const reader = request.body?.getReader(); if (!reader) throw new Error('body required');
  const chunks: Uint8Array[] = []; let n=0;
  try { for (;;) { const r=await reader.read(); if(r.done) break; n+=r.value.length; if(n>LIMITS.body) throw new Error('body bounds'); chunks.push(r.value); } }
  finally { await reader.cancel(); }
  const all=new Uint8Array(n); let at=0; for(const c of chunks){all.set(c,at);at+=c.length;}
  return JSON.parse(new TextDecoder('utf-8',{fatal:true,ignoreBOM:false}).decode(all));
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const path = new URL(request.url).pathname;
    if(request.method==='GET' && path==='/v1/protocol') return json({protocol:PROTOCOL,adapter:'mng-list-v1',limits:LIMITS,contributions:'quarantined',native_binaries:false});
    if(request.method==='POST' && path==='/v1/contributions') {
      // Optional edge binding uses one shared bucket per colo, not client IPs
      // or persistent visitor identifiers. D1 capacities remain authoritative.
      if(env.INGEST_RATE_LIMIT && !(await env.INGEST_RATE_LIMIT.limit({key:'metadata-ingress-v1'})).success)
        return json({error:'rate_limited'},429);
      let c;
      try { c=await validateContribution(await readBody(request)); } catch { return json({error:'invalid_contribution'},400); }
      const id=await contextId(c.context);
      try {
        // D1 batch is transactional. Unique keys deduplicate concurrent requests.
        const results=await env.DB.batch([
          env.DB.prepare('INSERT OR IGNORE INTO contexts(context_id,context_json) VALUES(?,?)').bind(id,canonical(c.context)),
          ...c.records.map(r=>env.DB.prepare('INSERT OR IGNORE INTO inbox(context_id,record_id,kind,row) VALUES(?,?,?,?) RETURNING record_id').bind(id,r.id,r.kind,r.row))
        ]);
        // meta.changes includes accounting-trigger updates; RETURNING counts
        // only new logical records, not their O(1) quota bookkeeping.
        const inserted=results.slice(1).reduce((n,r)=>n+r.results.length,0);
        return json({protocol:PROTOCOL,context_id:id,state:'quarantined',accepted_ids:c.records.map(r=>r.id),inserted,duplicates:c.records.length-inserted},202);
      } catch { return json({error:'inbox_unavailable'},503); }
    }
    let m;
    if(request.method==='GET' && (m=/^\/v1\/catalogs\/([a-f0-9]{64})\/manifest$/.exec(path))) {
      const row=await env.DB.prepare('SELECT envelope FROM manifests WHERE context_id=?').bind(m[1]).first<{envelope:string}>();
      return row ? new Response(row.envelope,{headers:{'Content-Type':'application/json','Cache-Control':'public,max-age=300','X-Content-Type-Options':'nosniff'}}) : json({error:'not_found'},404);
    }
    if(request.method==='GET' && (m=/^\/v1\/packs\/([a-f0-9]{64})$/.exec(path))) {
      // Unreviewed inbox records are never reachable here.
      const row=await env.DB.prepare('SELECT body FROM packs WHERE sha256=?').bind(m[1]).first<{body:string}>();
      return row ? new Response(row.body,{headers:{'Content-Type':'application/json','Cache-Control':'public,max-age=31536000,immutable','X-Content-Type-Options':'nosniff'}}) : json({error:'not_found'},404);
    }
    return json({error:'not_found'},404);
  }
};
