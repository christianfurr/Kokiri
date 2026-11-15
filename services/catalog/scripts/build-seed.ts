/** Imports ONLY an explicitly supplied public MIT metadata list. Never discovers
 * a user's shader/cache directories. Emits unsigned reference data, not binaries. */
import {readFile,mkdir,writeFile,lstat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {PROTOCOL,canonical,contextId,makeRecord,sha256,LIMITS,type Context,type RecordEntry} from '../src/protocol.ts';
const args=process.argv.slice(2);
function arg(name:string){const i=args.indexOf(name);return i<0?undefined:args[i+1];}
const output=arg('--output');if(!output)throw Error('--output required (fresh directory)');
const limit=Number(arg('--per-kind')??100000);if(!Number.isSafeInteger(limit)||limit<1||limit>100000)throw Error('limit');
let source:string;
if(args.includes('--stdin')){
  const chunks:Buffer[]=[];let n=0;for await(const b of process.stdin){n+=b.length;if(n>67108864)throw Error('source bounds');chunks.push(b);}source=Buffer.concat(chunks).toString('utf8');
}else{const input=arg('--input');if(!input)throw Error('--input or --stdin required');const st=await lstat(input);if(!st.isFile()||st.isSymbolicLink()||st.size>67108864)throw Error('input file');source=await readFile(input,'utf8');}
const context:Context={game_id:'oot',game_version:'131072',game_content_sha256:null,recipe_format:'mng-list-v1',backend:'metal',shader_chain:'mng-v28',translator_sha256:null,compiler_sha256:null,target_sha256:null,options_sha256:null};
const cid=await contextId(context);const records:RecordEntry[]=[];const counts:Record<string,number>={};const excluded:Record<string,number>={};const seen=new Set();
for(const row of source.split(/\r?\n/)){
  if(!row||row.startsWith('#'))continue;const kind=row.split('\t',1)[0];
  if(!['V','A','S','C','R','M','T'].includes(kind)){excluded[kind]=(excluded[kind]??0)+1;continue;}
  const record=await makeRecord(kind,row); // Validate even rows omitted by the explicit sample limit.
  if((counts[kind]??0)>=limit||seen.has(record.id))continue;seen.add(record.id);counts[kind]=(counts[kind]??0)+1;records.push(record);
}
const packs:{sha256:string;bytes:number;record_count:number;body:string}[]=[];let pending:RecordEntry[]=[];
async function flush(){if(!pending.length)return;const body=canonical({protocol:PROTOCOL,context_id:cid,records:pending});packs.push({sha256:await sha256(body),bytes:Buffer.byteLength(body),record_count:pending.length,body});pending=[];}
for(const r of records){const trial=canonical({protocol:PROTOCOL,context_id:cid,records:[...pending,r]});if(pending.length>=LIMITS.packRecords||Buffer.byteLength(trial)>LIMITS.pack)await flush();pending.push(r);}await flush();
const manifest={protocol:PROTOCOL,context,context_id:cid,compatibility:'reference-only',dataset_license:'MIT',attribution:[{name:'MacNativeGames contributors',source_url:'https://github.com/ly05010419/MacNativeGames',source_commit:'597e9bca63e34560a9dc20a75168abae258e8bdb',license:'MIT'}],revision:1,packs:packs.map(({body,...index})=>index),record_count:records.length};
// All input validation completes before creating any output. mkdir is exclusive.
await mkdir(resolve(output));await mkdir(resolve(output,'packs'));
for(const p of packs)await writeFile(resolve(output,'packs',p.sha256+'.json'),p.body,{flag:'wx'});
await writeFile(resolve(output,'manifest.unsigned.json'),canonical(manifest)+'\n',{flag:'wx'});
await writeFile(resolve(output,'provenance.json'),canonical({source:'games/oot/assets/shader_list.tsv',source_sha256:await sha256(source),source_commit:manifest.attribution[0].source_commit,counts,excluded,per_kind_limit:limit,reference_only:true})+'\n',{flag:'wx'});
console.log(canonical({records:records.length,packs:packs.length,context_id:cid,reference_only:true}));
