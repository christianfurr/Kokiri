"""Offline trusted-promotion step: reviewed metadata + supplied Ed25519 PEM key
to a fresh SQL file. Does not upload, deploy, create keys or mutate a database.
"""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key,Encoding,PublicFormat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('catalog',root/'sdk/python/kokiri_catalog.py')
sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)

def prepare(directory,key_path,key_id,output):
    sdk.require(__import__('re').fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}',key_id),'key id')
    directory=Path(directory);manifest=sdk.read_json(directory/'manifest.unsigned.json')
    key=load_pem_private_key(Path(key_path).read_bytes(),password=None);sdk.require(isinstance(key,Ed25519PrivateKey),'Ed25519 required')
    public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    envelope={'manifest':manifest,'key_id':key_id,'signature':base64.b64encode(key.sign(sdk.canonical(manifest).encode())).decode()}
    sdk.verify_manifest(envelope,manifest['context'],{key_id:public},for_warmup=False)
    bodies=[];record_ids=set()
    for index in manifest['packs']:
        path=directory/'packs'/(index['sha256']+'.json');sdk.require(path.is_file() and not path.is_symlink(),'pack file')
        text=path.read_text();pack=sdk.verify_pack(text,index,manifest['context_id'])
        for record in pack['records']:
            sdk.require(record['id'] not in record_ids,'duplicate record across packs');record_ids.add(record['id'])
        bodies.append((index['sha256'],text))
    def quote(value):return "'"+value.replace("'","''")+"'"
    # Plain INSERT deliberately refuses replacing an existing publication. A new
    # revision/pointer update needs an explicit operator-reviewed migration.
    # D1 does not expose SQL BEGIN/COMMIT through its API. Packs are immutable;
    # write the manifest last as the publication point. A failed import can
    # leave validated, unreferenced packs, never a partially indexed manifest.
    sql=[f"INSERT OR IGNORE INTO contexts VALUES({quote(manifest['context_id'])},{quote(sdk.canonical(manifest['context']))});"]
    for sha,body in bodies:sql.append(f'INSERT OR IGNORE INTO packs VALUES({quote(sha)},{quote(body)});')
    sql.append(f"INSERT INTO manifests VALUES({quote(manifest['context_id'])},{quote(sdk.canonical(envelope))});")
    with open(output,'x') as f:f.write('\n'.join(sql)+'\n')
    return {'context_id':manifest['context_id'],'records':manifest['record_count'],'packs':len(bodies),'key_id':key_id,'public_key':public,'uploaded':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reviewed-dir',required=True);p.add_argument('--signing-key',required=True);p.add_argument('--key-id',required=True);p.add_argument('--output-sql',required=True);a=p.parse_args()
    print(sdk.canonical(prepare(a.reviewed_dir,a.signing_key,a.key_id,a.output_sql)))
