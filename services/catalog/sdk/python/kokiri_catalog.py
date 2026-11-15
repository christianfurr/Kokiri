"""Reference metadata-only SDK/CLI. No default endpoint; Python3 + cryptography.
Persistent SQLite queue; safe to enqueue from multiple processes. One active
flush owner is required (the native application's actor should own it).
"""
import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

PROTOCOL = 'kokiri-catalog/1'
HASH = re.compile(r'[a-f0-9]{64}\Z')
VARIANT = re.compile(r'[a-f0-9]{64}-[a-f0-9]{12}_b\Z')
CONTEXT_KEYS = {'game_id','game_version','game_content_sha256','recipe_format','backend','shader_chain','translator_sha256','compiler_sha256','target_sha256','options_sha256'}
FINGERPRINTS = {'game_content_sha256','translator_sha256','compiler_sha256','target_sha256','options_sha256'}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def canonical(value):
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    require(all(0x20 <= ord(c) <= 0x7e for c in text), 'ASCII JSON required')
    return text

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def context(value):
    require(isinstance(value, dict) and set(value) == CONTEXT_KEYS, 'context fields')
    for k in ('game_id','game_version','shader_chain'):
        require(isinstance(value[k], str) and re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', value[k]), 'context token')
    require(value['recipe_format'] == 'mng-list-v1' and value['backend'] in ('metal','vulkan','d3d12'), 'adapter/backend')
    for k in FINGERPRINTS:
        require(value[k] is None or isinstance(value[k], str) and HASH.fullmatch(value[k]), 'context fingerprint')
    return value

def context_id(value):
    return digest(canonical(context(value)))

def pipeline(text):
    if re.fullmatch(r'[a-f0-9]{1088}', text):
        return True
    m = re.fullmatch(r'([a-f0-9_-]{0,80}):([a-f0-9_-]{0,80}):((?:[a-f0-9]{2}|z[a-f0-9]{1,3}\.)*)', text)
    if not m or not all(s in ('','-') or VARIANT.fullmatch(s) for s in m.group(1,2)):
        return False
    return 160 + sum(int(t[1:-1],16) if t.startswith('z') else 1 for t in re.findall(r'z[a-f0-9]+\.|[a-f0-9]{2}',m[3])) == 544

def row_valid(kind, row):
    require(isinstance(row,str) and len(row.encode()) <= 4096 and re.fullmatch(r'[\x20-\x7e\t]+',row), 'row bytes')
    f = row.split('\t')
    require(f[0] == kind, 'kind mismatch')
    if kind in ('V','A'):
        require(len(f)==3 and re.fullmatch(r'[a-f0-9]{64}' if kind=='V' else r'[a-f0-9]{12}',f[1]), 'binding identity')
        d=json.loads(f[2]);require(isinstance(d,dict) and set(d)<={'attr','fout','img','tex'},'binding fields')
        def typ(x): return isinstance(x,str) and re.fullmatch(r'[a-zA-Z0-9_*<>,. -]{1,64}',x)
        for group,slots in d.items():
            require(isinstance(slots,dict) and len(slots)<=64,'binding slots')
            for slot,v in slots.items():
                require(re.fullmatch(r'\d{1,3}',slot) and int(slot)<=255,'binding slot')
                require((set(v)=={'fmt','type'} and all(typ(x) for x in v.values())) if group=='img' and isinstance(v,dict) else typ(v),'binding type')
        require(canonical(d)==f[2],'canonical binding JSON');return
    flags=f.pop();require(flags in ('','m','t','mt','tm'),'flags')
    ok = kind=='S' and len(f)==3 and VARIANT.fullmatch(f[1]) and f[2] in ('0','1','5')
    ok = ok or kind=='C' and len(f)==2 and VARIANT.fullmatch(f[1])
    ok = ok or kind=='R' and len(f)==2 and pipeline(f[1])
    ok = ok or kind=='M' and len(f)==3 and (f[1]=='-' or VARIANT.fullmatch(f[1])) and pipeline(f[2])
    ok = ok or kind=='T' and len(f)==3 and pipeline(f[1]) and re.fullmatch(r'(?:\d{1,3}:[0-7];){1,8}',f[2])
    require(ok,'unsupported or malformed recipe')

def record(value):
    require(isinstance(value,dict) and set(value)=={'id','kind','row'},'record fields')
    row_valid(value['kind'],value['row'])
    require(value['id']==digest(canonical({'kind':value['kind'],'row':value['row']})),'record hash')
    return value

def envelope(value):
    require(isinstance(value,dict) and set(value)=={'protocol','context','records'} and value['protocol']==PROTOCOL,'envelope fields')
    context(value['context']);r=value['records'];require(isinstance(r,list) and 1<=len(r)<=64,'batch bounds')
    for entry in r: record(entry)
    require(len({x['id'] for x in r})==len(r) and len(canonical(value).encode())<=65536,'duplicate/body bounds')
    return value

def verify_manifest(value, expected, trusted_keys, for_warmup=True):
    """Trust store must be bundled/pinned by application, not downloaded with manifest."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    require(set(value)=={'manifest','key_id','signature'} and value['key_id'] in trusted_keys,'untrusted signing key')
    m=value['manifest']
    require(set(m)=={'protocol','context','context_id','compatibility','dataset_license','attribution','revision','packs','record_count'},'manifest fields')
    require(m['protocol']==PROTOCOL and m['dataset_license']=='MIT' and m['context_id']==context_id(m['context']),'manifest identity')
    require(canonical(context(expected))==canonical(m['context']),'incompatible context')
    exact=all(m['context'][k] is not None for k in FINGERPRINTS)
    require(m['compatibility']==('exact' if exact else 'reference-only') and (not for_warmup or exact),'reference metadata cannot warm runtime')
    require(type(m['revision']) is int and m['revision']>=1 and isinstance(m['packs'],list) and len(m['packs'])<=1024,'manifest bounds')
    require(len(canonical(value))<=262144,'manifest bytes')
    total=0;seen=set()
    for p in m['packs']:
        require(set(p)=={'sha256','bytes','record_count'} and isinstance(p['sha256'],str) and HASH.fullmatch(p['sha256']) and p['sha256'] not in seen,'pack identity')
        require(type(p['bytes']) is int and 0<p['bytes']<=262144 and type(p['record_count']) is int and 0<p['record_count']<=128,'pack bounds')
        seen.add(p['sha256']);total+=p['record_count']
    require(m['record_count']==total,'manifest count')
    require(isinstance(m['attribution'],list) and 1<=len(m['attribution'])<=8,'attribution bounds')
    for a in m['attribution']:
        require(set(a)=={'name','source_url','source_commit','license'} and a['license']=='MIT' and re.fullmatch(r'[A-Za-z0-9 ._-]{1,100}',a['name']) and re.fullmatch(r'https://[A-Za-z0-9./_-]{1,200}',a['source_url']) and re.fullmatch(r'[a-f0-9]{40}',a['source_commit']),'attribution')
    key=base64.b64decode(trusted_keys[value['key_id']],validate=True)
    signature=base64.b64decode(value['signature'],validate=True)
    Ed25519PublicKey.from_public_bytes(key).verify(signature,canonical(m).encode())
    return m

def verify_pack(text, index, cid):
    require(len(text.encode())==index['bytes']<=262144 and digest(text)==index['sha256'],'pack integrity')
    p=json.loads(text);require(set(p)=={'protocol','context_id','records'} and p['protocol']==PROTOCOL and p['context_id']==cid,'pack context')
    require(isinstance(p['records'],list) and len(p['records'])==index['record_count']<=128,'pack count')
    for r in p['records']:record(r)
    require(len({r['id'] for r in p['records']})==len(p['records']),'pack duplicates');return p

class Queue:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=5)
        self.db.executescript("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT); CREATE TABLE IF NOT EXISTS pending(cid TEXT,id TEXT,body TEXT,PRIMARY KEY(cid,id));")
        self.stopped=False
    def status(self):
        def get(k,default):
            r=self.db.execute('SELECT v FROM settings WHERE k=?',(k,)).fetchone();return r[0] if r else default
        return {'consent':get('consent','undecided'),'pending':self.db.execute('SELECT count(*) FROM pending').fetchone()[0],'failures':int(get('failures','0')),'retry_at':float(get('retry_at','0'))}
    def choose(self,choice):
        require(choice in ('undecided','enabled','disabled'),'consent choice');self.stopped=choice!='enabled'
        with self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('consent',choice))
    def enqueue(self,value):
        e=envelope(value);cid=context_id(e['context'])
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            require(self.status()['consent']=='enabled' and not self.stopped,'consent required')
            for r in e['records']:
                self.db.execute('INSERT OR IGNORE INTO pending VALUES(?,?,?)',(cid,r['id'],canonical({'context':e['context'],'record':r})))
            n,size=self.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM pending').fetchone()
            require(n<=4096 and size<=16777216,'queue bounds')
    def flush(self,send,now=None):
        now=time.time() if now is None else now;sent=0
        while not self.stopped:
            s=self.status()
            if s['consent']!='enabled' or s['retry_at']>now:break
            first=self.db.execute('SELECT cid FROM pending ORDER BY cid,id LIMIT 1').fetchone()
            if not first:break
            rows=self.db.execute('SELECT id,body FROM pending WHERE cid=? ORDER BY id LIMIT 64',first).fetchall()
            entries=[]
            for rid,body in rows:
                p=json.loads(body);trial={'protocol':PROTOCOL,'context':p['context'],'records':entries+[p['record']]}
                if len(canonical(trial).encode())>65536:break
                entries.append(p['record'])
            e=envelope({'protocol':PROTOCOL,'context':p['context'],'records':entries})
            try:
                a=send(e)
                require(isinstance(a,dict) and a.get('protocol')==PROTOCOL and a.get('context_id')==first[0] and a.get('state')=='quarantined' and isinstance(a.get('accepted_ids'),list) and sorted(a['accepted_ids'])==sorted(r['id'] for r in entries),'invalid acknowledgment')
                with self.db:
                    self.db.executemany('DELETE FROM pending WHERE cid=? AND id=?',[(first[0],r['id']) for r in entries])
                    self.db.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',[('failures','0'),('retry_at','0')])
                sent+=len(entries)
            except Exception:
                failures=min(s['failures']+1,10)
                with self.db:self.db.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',[('failures',str(failures)),('retry_at',str(now+min(3600,2**failures)))])
                break
        return {'sent':sent,**self.status()}

def https_transport(endpoint):
    u=urllib.parse.urlsplit(endpoint)
    require(u.scheme=='https' and u.hostname and not u.username and not u.password and u.path in ('','/') and not u.query and not u.fragment,'HTTPS origin required')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(NoRedirect)
    def send(e):
        req=urllib.request.Request(endpoint.rstrip('/')+'/v1/contributions',canonical(e).encode(),{'Content-Type':'application/json'},method='POST')
        with opener.open(req,timeout=15) as response:
            require(response.status==202,'not accepted');data=response.read(65537);require(len(data)<=65536,'response bounds');return json.loads(data)
    return send

def read_json(path):
    with open(path,'rb') as f:data=f.read(262145)
    require(len(data)<=262144,'input bounds');return json.loads(data)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--queue');sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status');c=sub.add_parser('consent');c.add_argument('choice',choices=['undecided','enabled','disabled'])
    for command in ('validate','enqueue'):
        c=sub.add_parser(command);c.add_argument('--envelope',required=True)
    c=sub.add_parser('flush');c.add_argument('--endpoint',required=True)
    c=sub.add_parser('verify');c.add_argument('--manifest',required=True);c.add_argument('--context',required=True);c.add_argument('--keys',required=True);c.add_argument('--reference-only',action='store_true')
    a=p.parse_args()
    if a.command=='validate':e=envelope(read_json(a.envelope));print(canonical({'valid':True,'context_id':context_id(e['context']),'records':len(e['records'])}));return
    if a.command=='verify':m=verify_manifest(read_json(a.manifest),read_json(a.context),read_json(a.keys),not a.reference_only);print(canonical({'valid':True,'context_id':m['context_id'],'records':m['record_count']}));return
    require(a.queue,'--queue required');q=Queue(a.queue)
    if a.command=='consent':q.choose(a.choice)
    elif a.command=='enqueue':q.enqueue(read_json(a.envelope))
    elif a.command=='flush':print(canonical(q.flush(https_transport(a.endpoint))));return
    print(canonical(q.status()))

if __name__=='__main__':
    try:main()
    except Exception:
        print('{"error":"catalog_operation_failed"}',file=sys.stderr);sys.exit(1)
