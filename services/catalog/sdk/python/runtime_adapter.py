"""Closed-game reference adapter. Produces a bounded warm-list candidate only.

No process execution, GPU access, cache/profile modification or automatic runtime
adoption. Trust anchors and local evidence hashes come from an independently
verified runtime/build receipt, never the downloaded catalog itself.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile

import kokiri_catalog as wire

MAX_RECIPES = 512
MAX_WARM_BYTES = 1024 * 1024

def bounded_file(path, limit):
    path = Path(path)
    wire.require(path.is_file() and not path.is_symlink(), 'regular nonsymlink input required')
    wire.require(path.stat().st_size <= limit, 'file bounds')
    with path.open('rb') as f:
        data = f.read(limit + 1)
    wire.require(len(data) <= limit, 'file bounds')
    return data

def file_sha256(path):
    path = Path(path)
    wire.require(path.is_file() and not path.is_symlink(), 'regular nonsymlink variant required')
    wire.require(path.stat().st_size <= 1024 * 1024 * 1024, 'variant bounds')
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    wire.require((before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns), 'variant changed during verification')
    return digest.hexdigest()

def unpack_state(text):
    """Actual mng pso_skey ABI: two80-byte names,384 state bytes; no pointers."""
    wire.require(wire.pipeline(text), 'pipeline syntax')
    if re.fullmatch(r'[a-f0-9]{1088}', text):
        data = bytes.fromhex(text)
    else:
        vs, fs, rest = text.split(':')
        tail = bytearray()
        for token in re.findall(r'z[a-f0-9]+\.|[a-f0-9]{2}', rest):
            tail.extend(bytes(int(token[1:-1],16)) if token.startswith('z') else bytes.fromhex(token))
        data = vs.encode().ljust(80,b'\0') + fs.encode().ljust(80,b'\0') + bytes(tail)
    wire.require(len(data)==544 and data[200:216]==bytes(16) and data[536:544]==bytes(8), 'recorded pipeline contains host pointers')
    wire.require(struct.unpack_from('<I',data,268)[0] & 0xc0 == 0, 'host-generated pipeline cannot be warmed from metadata')
    def name(offset):
        raw=data[offset:offset+80];text=raw.rstrip(b'\0')
        wire.require(raw==text.ljust(80,b'\0'),'noncanonical stage name')
        result=text.decode('ascii');wire.require(not result or wire.VARIANT.fullmatch(result),'variant identity');return result
    vs,fs=name(0),name(80)
    # Initial adoption handles ordinary render/compute only. Native mesh,
    # fragment specialization and merged/tile paths need separate semantics gates.
    wire.require(vs and data[160]==0 and (not fs or data[161]==1) and data[162]==0 and data[163]==0, 'specialized pipeline requires separate adoption gate')
    return data.hex(), [(vs,0)] + ([(fs,1)] if fs else [])

def runtime_recipe(row):
    """Canonical candidate or None for a deliberately unsupported recipe kind."""
    fields=row.split('\t');kind=fields[0]
    if kind not in ('C','R'):
        return None
    # Local production recorder omits the optional metadata provenance column.
    if len(fields)==2:
        row += '\t'
        fields=row.split('\t')
    wire.row_valid(kind,row)
    if kind=='C':
        return 'C\t'+fields[1],[(fields[1],5)]
    key,variants=unpack_state(fields[1])
    return 'R\t'+key,variants

def qualify(context, evidence, expected_evidence_sha256):
    """Checks evidence binding; does NOT manufacture missing observable facts."""
    wire.context(context)
    wire.require(all(context[k] is not None for k in wire.FINGERPRINTS),'reference-only context cannot be adopted')
    wire.require(wire.digest(wire.canonical(evidence))==expected_evidence_sha256,'local evidence not independently attested')
    wire.require(set(evidence)=={'schema','context','runtime_sha256','compiler','target','options','variants'},'evidence fields')
    wire.require(evidence['schema']=='kokiri-local-warm-evidence/1' and wire.canonical(evidence['context'])==wire.canonical(context),'evidence context')
    wire.require(isinstance(evidence['runtime_sha256'],str) and wire.HASH.fullmatch(evidence['runtime_sha256']),'runtime identity')
    for name in ('compiler','target','options'):
        descriptor=evidence[name]
        wire.require(isinstance(descriptor,dict) and descriptor.get('schema')=='kokiri-'+name+'-identity/1','identity descriptor schema')
        wire.require(descriptor.get('observed') is True,'unobserved identity descriptor')
        wire.require(wire.digest(wire.canonical(descriptor))==context[name+'_sha256'],'identity descriptor hash')
    wire.require(evidence['options'].get('runtime_sha256')==evidence['runtime_sha256'],'options/runtime binding')
    wire.require(isinstance(evidence['variants'],list) and len(evidence['variants'])<=100000,'variant inventory bounds')
    inventory={}
    for v in evidence['variants']:
        wire.require(isinstance(v,dict) and set(v)=={'name','stage','sha256','file'},'variant evidence fields')
        wire.require(isinstance(v['name'],str) and wire.VARIANT.fullmatch(v['name']) and type(v['stage']) is int and v['stage'] in (0,1,3,4,5),'variant evidence identity')
        wire.require(isinstance(v['sha256'],str) and wire.HASH.fullmatch(v['sha256']),'variant evidence hash')
        wire.require(v['file'] in (v['name']+'.metal',v['name']+'.metallib'),'variant filename must be flat/exact')
        key=(v['name'],v['stage']);wire.require(key not in inventory,'duplicate variant evidence');inventory[key]=v
    return inventory

def prepare(index_path, expected_context, trusted_keys, evidence, evidence_sha256,
            runtime_executable, variant_folder, allowlist_data, allowlist_sha256, output_root):
    """Every source is read-only. Only a fresh own output folder is published.

    `allowlist_sha256` and `evidence_sha256` must be pinned by the trusted build /
    own runtime observation receipt. Supplying hashes from the server would
    defeat this boundary. No broad metadata-to-GPU fallback exists.
    """
    inventory=qualify(expected_context,evidence,evidence_sha256)
    wire.require(file_sha256(runtime_executable)==evidence['runtime_sha256'],'runtime binary changed')
    wire.require(isinstance(allowlist_data,bytes) and len(allowlist_data)<=16*1024*1024 and hashlib.sha256(allowlist_data).hexdigest()==allowlist_sha256,'local recipe allowlist not attested')
    local_recipes=set()
    for row in allowlist_data.decode('ascii').splitlines():
        if not row or row.startswith('#'):continue
        try:
            recipe=runtime_recipe(row)
        except (ValueError,UnicodeError):
            continue
        if recipe:local_recipes.add(recipe[0])
    index_path=Path(index_path)
    index=json.loads(bounded_file(index_path,1024*1024))
    wire.require(set(index)=={'protocol','context_id','signed_manifest','pack_files'} and index['protocol']==wire.PROTOCOL,'runtime index fields')
    manifest=wire.verify_manifest(index['signed_manifest'],expected_context,trusted_keys)
    wire.require(index['context_id']==manifest['context_id'],'runtime index context')
    refs=index['pack_files'];wire.require(isinstance(refs,list) and len(refs)==len(manifest['packs']),'pack index count')
    folder=index_path.parent.parent/'packs'
    wire.require(folder.is_dir() and not folder.is_symlink(),'pack root')
    selected=[];seen=set();record_ids=[];verified_variants={};counts={'unsupported':0,'not_local_recipe':0,'missing_variant':0,'deferred':0}
    total_bytes=0;all_record_ids=set();total_records=0
    for ref,part in zip(refs,manifest['packs']):
        wire.require(isinstance(ref,dict) and set(ref)=={'sha256','bytes','record_count','relative_path'},'pack reference fields')
        wire.require(all(ref[k]==part[k] for k in part) and ref['relative_path']=='../packs/'+part['sha256']+'.json','pack reference mismatch')
        total_bytes+=part['bytes'];total_records+=part['record_count']
        wire.require(total_bytes<=64*1024*1024 and total_records<=100000,'catalog bounds')
        text=bounded_file(folder/(part['sha256']+'.json'),262144).decode('ascii')
        pack=wire.verify_pack(text,part,manifest['context_id'])
        for record in pack['records']:
            wire.require(record['id'] not in all_record_ids,'duplicate catalog identity');all_record_ids.add(record['id'])
            try:recipe=runtime_recipe(record['row'])
            except ValueError:recipe=None
            if recipe is None:counts['unsupported']+=1;continue
            row,variants=recipe
            if row not in local_recipes:counts['not_local_recipe']+=1;continue
            if row in seen:continue
            if any(v not in inventory for v in variants):counts['missing_variant']+=1;continue
            if len(selected)>=MAX_RECIPES or sum(len(r)+1 for r in selected)+len(row)+1>MAX_WARM_BYTES:
                counts['deferred']+=1;continue
            for name,stage in variants:
                v=inventory[(name,stage)]
                if name not in verified_variants:
                    wire.require(file_sha256(Path(variant_folder)/v['file'])==v['sha256'],'local variant bytes changed')
                    verified_variants[name]=v['sha256']
            seen.add(row);selected.append(row);record_ids.append(record['id'])
    wire.require(total_records==manifest['record_count'],'catalog total')
    receipt={'schema':'kokiri-warm-candidate/1','context_id':manifest['context_id'],'catalog_revision':manifest['revision'],
             'evidence_sha256':evidence_sha256,'allowlist_sha256':allowlist_sha256,'runtime_sha256':evidence['runtime_sha256'],
             'selected_record_ids':record_ids,'selected':len(selected),'skipped':counts,'variant_sha256':verified_variants,
             'automatic_adoption':False,'kinds':['C','R'],'limit':MAX_RECIPES}
    if not selected:
        return {'artifact':None,'receipt':receipt}
    body=('\n'.join(selected)+'\n').encode('ascii');receipt['warm_list_sha256']=hashlib.sha256(body).hexdigest()
    plan_id=wire.digest(wire.canonical(receipt));output_root=Path(output_root)
    wire.require(not output_root.is_symlink(),'output root must not be a symlink')
    output_root.mkdir(parents=True,exist_ok=True)
    destination=output_root/plan_id
    wire.require(not destination.is_symlink(),'candidate directory must not be a symlink')
    encoded=wire.canonical(receipt).encode()+b'\n'
    if destination.exists():
        wire.require(bounded_file(destination/'pso_catalog.tsv',MAX_WARM_BYTES)==body and bounded_file(destination/'receipt.json',1024*1024)==encoded,'existing candidate changed')
        return {'artifact':str(destination/'pso_catalog.tsv'),'receipt':receipt}
    staging=Path(tempfile.mkdtemp(prefix='.warm-',dir=output_root))
    try:
        os.chmod(staging,0o700)
        for name,data in (('pso_catalog.tsv',body),('receipt.json',encoded)):
            with (staging/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.rename(staging,destination)
    finally:
        if staging.exists():shutil.rmtree(staging)
    return {'artifact':str(destination/'pso_catalog.tsv'),'receipt':receipt}
