import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdk/python'))
import kokiri_catalog as wire
import runtime_adapter as adapter

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.variants=self.root/'variants';self.variants.mkdir()
        self.binary=self.root/'runtime';self.binary.write_bytes(b'synthetic nonexecutable runtime fixture')
        self.context=json.loads((ROOT/'tests/fixtures/context.json').read_text())
        runtime=hashlib.sha256(self.binary.read_bytes()).hexdigest()
        descriptors={k:{'schema':'kokiri-'+k+'-identity/1','observed':True,'test_fixture':True} for k in ('compiler','target','options')}
        descriptors['options']['runtime_sha256']=runtime
        for k,d in descriptors.items():self.context[k+'_sha256']=wire.digest(wire.canonical(d))
        self.evidence={'schema':'kokiri-local-warm-evidence/1','context':self.context,'runtime_sha256':runtime,**descriptors,'variants':[]}
        self.key=Ed25519PrivateKey.generate();self.keys={'test-only':base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}
        self.allow=[];self.records=[]
    def tearDown(self):self.tmp.cleanup()
    def add_variant(self,n,stage):
        name=format(n,'064x')+'-'+'b'*12+'_b';filename=name+'.metal';data=('synthetic fixture '+str(n)).encode()
        (self.variants/filename).write_bytes(data)
        self.evidence['variants'].append({'name':name,'stage':stage,'file':filename,'sha256':hashlib.sha256(data).hexdigest()})
        return name
    def add_row(self,row,allow=True):
        kind=row[0];wire.row_valid(kind,row)
        self.records.append({'kind':kind,'row':row,'id':wire.digest(wire.canonical({'kind':kind,'row':row}))})
        if allow:self.allow.append(row)
    def index(self):
        cid=wire.context_id(self.context);packdir=self.root/'packs';packdir.mkdir(exist_ok=True)
        parts=[]
        for at in range(0,len(self.records),128):
            body=wire.canonical({'protocol':wire.PROTOCOL,'context_id':cid,'records':self.records[at:at+128]})
            sha=wire.digest(body);(packdir/(sha+'.json')).write_text(body)
            parts.append({'sha256':sha,'bytes':len(body),'record_count':len(self.records[at:at+128])})
        manifest={'protocol':wire.PROTOCOL,'context':self.context,'context_id':cid,'compatibility':'exact','dataset_license':'MIT','attribution':[{'name':'Synthetic fixture','source_url':'https://example.invalid/test','source_commit':'a'*40,'license':'MIT'}],'revision':1,'packs':parts,'record_count':len(self.records)}
        signed={'manifest':manifest,'key_id':'test-only','signature':base64.b64encode(self.key.sign(wire.canonical(manifest).encode())).decode()}
        ready=self.root/'runtime-ready';ready.mkdir(exist_ok=True);index=ready/(cid+'.json')
        index.write_text(wire.canonical({'protocol':wire.PROTOCOL,'context_id':cid,'signed_manifest':signed,'pack_files':[{**p,'relative_path':'../packs/'+p['sha256']+'.json'} for p in parts]}))
        return index
    def prepare(self,index=None):
        allow=('\n'.join(self.allow)+'\n').encode()
        return adapter.prepare(index or self.index(),self.context,self.keys,self.evidence,wire.digest(wire.canonical(self.evidence)),self.binary,self.variants,allow,hashlib.sha256(allow).hexdigest(),self.root/'warm-candidates')
    def test_downloaded_compute_becomes_bounded_runtime_recipe_without_profile_write(self):
        name=self.add_variant(1,5);self.add_row('C\t'+name+'\tm')
        result=self.prepare();self.assertEqual(Path(result['artifact']).read_text(),'C\t'+name+'\n')
        self.assertFalse(result['receipt']['automatic_adoption']);self.assertEqual(result['receipt']['selected'],1)
        self.assertFalse((self.root/'profile').exists())
        self.assertEqual(self.prepare()['artifact'],result['artifact'])
    def test_packed_render_expands_actual544byte_layout(self):
        vs=self.add_variant(1,0);fs=self.add_variant(2,1)
        tail=bytearray(384);tail[1]=1
        packed=vs+':'+fs+':'+tail.hex()
        self.add_row('R\t'+packed+'\tm')
        result=self.prepare();row=Path(result['artifact']).read_text().rstrip().split('\t')
        self.assertEqual(len(row[1]),1088);self.assertEqual(bytes.fromhex(row[1])[:80],vs.encode().ljust(80,b'\0'))
    def test_null_context_never_qualifies(self):
        self.context['compiler_sha256']=None
        with self.assertRaisesRegex(ValueError,'reference-only'):self.prepare()
        self.assertFalse((self.root/'warm-candidates').exists())
    def test_wrong_evidence_anchor_rejects(self):
        name=self.add_variant(1,5);self.add_row('C\t'+name+'\tm')
        with self.assertRaisesRegex(ValueError,'independently attested'):
            adapter.qualify(self.context,self.evidence,'0'*64)
    def test_unattested_evidence_and_changed_local_bytes_reject(self):
        name=self.add_variant(1,5);self.add_row('C\t'+name+'\tm');index=self.index()
        (self.variants/(name+'.metal')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'):self.prepare(index)
        self.assertFalse((self.root/'warm-candidates').exists())
    def test_signed_but_not_locally_attested_recipe_is_not_adopted(self):
        name=self.add_variant(1,5);self.add_row('C\t'+name+'\tm',allow=False)
        result=self.prepare();self.assertIsNone(result['artifact']);self.assertEqual(result['receipt']['skipped']['not_local_recipe'],1)
    def test_missing_variant_and_specialized_metadata_remain_deferred(self):
        name='c'*64+'-'+'b'*12+'_b';self.add_row('C\t'+name+'\tm')
        self.add_row('S\t'+name+'\t0\tm')
        result=self.prepare();self.assertIsNone(result['artifact']);self.assertEqual(result['receipt']['skipped']['missing_variant'],1);self.assertEqual(result['receipt']['skipped']['unsupported'],1)
    def test_cap512_does_not_materialize_full_catalog(self):
        for n in range(513):self.add_row('C\t'+self.add_variant(n,5)+'\tm')
        result=self.prepare();self.assertEqual(result['receipt']['selected'],512);self.assertEqual(result['receipt']['skipped']['deferred'],1)
        self.assertEqual(len(Path(result['artifact']).read_text().splitlines()),512)
    def test_pointer_host_specialization_guards(self):
        vs=self.add_variant(1,0);data=bytearray(544);data[:80]=vs.encode().ljust(80,b'\0')
        for offset,value in ((200,1),(536,1),(268,64),(162,1),(163,1)):
            bad=bytearray(data);bad[offset]=value
            with self.assertRaises(ValueError):adapter.runtime_recipe('R\t'+bad.hex()+'\tm')
    def test_tampered_index_pack_and_symlink_do_not_publish(self):
        name=self.add_variant(1,5);self.add_row('C\t'+name+'\tm');index=self.index()
        pack=next((self.root/'packs').iterdir());original=pack.read_bytes();pack.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.prepare(index)
        pack.write_bytes(original);variant=self.variants/(name+'.metal');saved=self.root/'saved';variant.rename(saved);variant.symlink_to(saved)
        with self.assertRaises(ValueError):self.prepare(index)
        self.assertFalse((self.root/'warm-candidates').exists())
    def test_actual_production_state_header_accepts_expanded_adapter_bytes(self):
        """Use real pso_skey structs/parser; stub only NvShader's interface."""
        import re
        source=ROOT.parents[1]/'engine/third_party/d2r_gfx/gfx/nvn'
        obj=(source/'nvn_obj.h').read_text()
        definitions=[]
        for name in ('blend_st','va_st','vs_st'):
            definitions.append(re.search(r'typedef struct \{[^\n]+\} '+name+r';',obj)[0])
        definitions.append('typedef struct { char key[80]; int stage; } NvShader;')
        header=(source/'nvn_pso_skey.h').read_text().replace('#include "nvn_obj.h"','\n'.join(definitions))
        (self.root/'production.h').write_text(header)
        program='''#include <stdio.h>
#include <stddef.h>
#include "production.h"
_Static_assert(sizeof(pso_skey)==544,"actual recorded ABI changed");
_Static_assert(offsetof(pso_skey,k.vs)==200,"pointer offset");
_Static_assert(offsetof(pso_skey,k.fs)==208,"pointer offset");
_Static_assert(offsetof(pso_skey,k.a2c)==268,"host bits offset");
_Static_assert(offsetof(pso_skey,k.fsfn)==536,"function pointer offset");
int main(int argc,char **argv){pso_skey state;if(argc!=2||pso_skey_parse(argv[1],&state))return 2;
char text[2*sizeof(state)+1];pso_skey_hex(&state,text);puts(text);return 0;}
'''
        code=self.root/'oracle.c';code.write_text(program);binary=self.root/'oracle'
        subprocess.run(['clang','-std=gnu11',str(code),'-o',str(binary)],check=True,capture_output=True,timeout=10)
        vs=self.add_variant(1,0);fs=self.add_variant(2,1)
        tail=bytearray(384);tail[1]=1
        expanded,variants=adapter.unpack_state(vs+':'+fs+':'+tail.hex())
        result=subprocess.run([str(binary),expanded],text=True,capture_output=True,check=True,timeout=3)
        self.assertEqual(result.stdout.strip(),expanded)
        self.assertEqual(variants,[(vs,0),(fs,1)])
        host=bytearray.fromhex(expanded);host[268]=64
        self.assertEqual(subprocess.run([str(binary),host.hex()],capture_output=True,timeout=3).returncode,2)

if __name__=='__main__':unittest.main()
