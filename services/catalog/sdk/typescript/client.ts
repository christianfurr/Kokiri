export * from '../../src/protocol.ts';
import { check, canonical, contextId, LIMITS, PROTOCOL, validateContribution, type Contribution } from '../../src/protocol.ts';
/** Single-owner queue adapter. Implement save atomically in your application's
 * local store; serialize multiple processes through that store. Never upload TSV files. */
export interface QueueState { consent:'undecided'|'enabled'|'disabled'; pending:Contribution[]; failures:number; retry_at:number }
export interface QueueStore { load():Promise<QueueState>; save(state:QueueState):Promise<void> }
export type Transport = (envelope:Contribution)=>Promise<unknown>;
export class CatalogQueue {
  private tail:Promise<unknown> = Promise.resolve();
  private stopped = false;
  private store:QueueStore;
  private transport:Transport;
  constructor(store:QueueStore, transport:Transport) {this.store=store;this.transport=transport;}
  private serial<T>(fn:()=>Promise<T>):Promise<T> { const p=this.tail.then(fn);this.tail=p.catch(()=>{});return p; }
  /** Immediately cancels future chunks, even while an in-flight request finishes. */
  consent(choice:QueueState['consent']):Promise<void> {
    this.stopped=choice!=='enabled';
    return this.serial(async()=>{const s=await this.store.load();s.consent=choice;await this.store.save(s);});
  }
  enqueue(value:unknown):Promise<void> { return this.serial(async()=>{
    const e=await validateContribution(value);const s=await this.store.load();
    check(s.consent==='enabled'&&!this.stopped,'consent required');
    const cid=await contextId(e.context);
    const ids=new Set<string>(); for(const p of s.pending)if(await contextId(p.context)===cid)for(const r of p.records)ids.add(r.id);
    const records=e.records.filter(r=>!ids.has(r.id));if(records.length)s.pending.push({...e,records});
    check(s.pending.reduce((n,p)=>n+p.records.length,0)<=4096 && canonical(s).length<=16777216,'queue bounds');
    await this.store.save(s);
  }); }
  flush(now=Date.now()/1000):Promise<{sent:number;pending:number}> { return this.serial(async()=>{
    let s=await this.store.load();let sent=0;
    while(!this.stopped && s.consent==='enabled' && s.pending.length && s.retry_at<=now){
      const envelope=await validateContribution(s.pending[0]);
      try {
        const raw=await this.transport(envelope);
        check(raw!==null&&typeof raw==='object','invalid acknowledgment');const a=raw as Record<string,unknown>;
        check(a.protocol===PROTOCOL&&a.context_id===await contextId(envelope.context)&&a.state==='quarantined','invalid acknowledgment');
        check(Array.isArray(a.accepted_ids)&&canonical([...a.accepted_ids].sort())===canonical(envelope.records.map(r=>r.id).sort()),'incomplete acknowledgment');
        // Reload consent after every request; disabled while request1 never sends request2.
        s=await this.store.load();s.pending.shift();s.failures=0;s.retry_at=0;sent+=envelope.records.length;await this.store.save(s);
      } catch {s=await this.store.load();s.failures=Math.min(s.failures+1,10);s.retry_at=now+Math.min(3600,2**s.failures);await this.store.save(s);break;}
    }
    return {sent,pending:s.pending.reduce((n,p)=>n+p.records.length,0)};
  }); }
}
/** Supply an explicitly configured HTTPS origin. No default production endpoint. */
export function httpsTransport(endpoint:string):Transport {
  const u=new URL(endpoint);check(u.protocol==='https:'&&!u.username&&!u.password&&u.pathname==='/'&&!u.search&&!u.hash,'HTTPS origin required');
  return async envelope=>{
    const r=await fetch(new URL('/v1/contributions',u),{method:'POST',redirect:'error',headers:{'Content-Type':'application/json'},body:canonical(envelope),signal:AbortSignal.timeout(15000)});
    check(r.status===202,'contribution not accepted');
    const reader=r.body?.getReader();check(reader,'response required');let n=0;let body='';const decoder=new TextDecoder();
    try{for(;;){const b=await reader.read();if(b.done)break;n+=b.value.length;check(n<=LIMITS.body,'response bounds');body+=decoder.decode(b.value,{stream:true});}body+=decoder.decode();}finally{await reader.cancel();}
    return JSON.parse(body);
  };
}
