import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('catalog',ROOT/'sdk/python/kokiri_catalog.py')
sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)
def fixture(name):return json.loads((ROOT/'tests/fixtures'/name).read_text())
def ack(e):return {'protocol':sdk.PROTOCOL,'context_id':sdk.context_id(e['context']),'state':'quarantined','accepted_ids':[r['id'] for r in e['records']]}

class ProtocolTests(unittest.TestCase):
    def test_cross_language_signed_fixtures(self):
        e=fixture('contribution.json');sdk.envelope(e)
        m=sdk.verify_manifest(fixture('manifest.json'),e['context'],fixture('trusted-keys.json'))
        text=sdk.canonical(fixture('pack.json'))
        self.assertEqual(sdk.verify_pack(text,m['packs'][0],m['context_id'])['records'],e['records'])
    def test_tamper_context_and_pinned_key(self):
        e=fixture('contribution.json');m=fixture('manifest.json');keys=fixture('trusted-keys.json')
        wrong=copy.deepcopy(e['context']);wrong['shader_chain']='mng-v23'
        for value,context,trust in ((m,wrong,keys),(m,e['context'],{})):
            with self.assertRaises(Exception):sdk.verify_manifest(value,context,trust)
        m['manifest']['revision']+=1
        with self.assertRaises(Exception):sdk.verify_manifest(m,e['context'],keys)
    def test_bounds_and_private_fields(self):
        e=fixture('contribution.json')
        for value in ({**e,'source':'code'}, {**e,'records':e['records']*65}, {**e,'records':e['records']*2}):
            with self.assertRaises(ValueError):sdk.envelope(value)
        for row in ('L\tprivate/path','R\t-:-:zfff.\tm',e['records'][0]['row']+'\n','V\t'+'a'*64+'\t{"attr":{},"fout":{},"img":{},"tex":{"0":"#include <private>"}}'):
            with self.assertRaises(ValueError):sdk.row_valid(row[0],row)

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'queue.sqlite');self.q=sdk.Queue(self.path);self.e=fixture('contribution.json')
    def tearDown(self):self.q.db.close();self.tmp.cleanup()
    def test_default_no_network_and_remembered_consent(self):
        calls=[]
        self.q.flush(lambda e:calls.append(e));self.assertFalse(calls)
        with self.assertRaises(ValueError):self.q.enqueue(self.e)
        self.q.choose('enabled');self.q.enqueue(self.e)
        other=sdk.Queue(self.path);self.assertEqual(other.status()['consent'],'enabled');other.db.close()
    def test_concurrent_dedup(self):
        self.q.choose('enabled')
        def enqueue(_):
            q=sdk.Queue(self.path);q.enqueue(self.e);q.db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(enqueue,range(16)))
        self.assertEqual(self.q.status()['pending'],1)
    def test_offline_retry_and_incomplete_ack_keep_data(self):
        self.q.choose('enabled');self.q.enqueue(self.e);calls=[]
        def offline(e):calls.append(e);raise OSError('offline')
        self.q.flush(offline,100);self.q.flush(offline,101);self.assertEqual(len(calls),1);self.assertEqual(self.q.status()['pending'],1)
        self.q.flush(lambda e:{},104);self.assertEqual(self.q.status()['pending'],1)
        result=self.q.flush(ack,110);self.assertEqual(result['sent'],1);self.assertEqual(result['pending'],0)
    def test_disable_between_chunks(self):
        self.q.choose('enabled');records=[]
        for n in range(65):
            row='S\t'+format(n,'064x')+'-'+'b'*12+'_b\t0\tm'
            records.append({'kind':'S','row':row,'id':sdk.digest(sdk.canonical({'kind':'S','row':row}))})
        self.q.enqueue({**self.e,'records':records[:64]});self.q.enqueue({**self.e,'records':records[64:]})
        calls=[]
        def send(e):calls.append(e);other=sdk.Queue(self.path);other.choose('disabled');other.db.close();return ack(e)
        result=self.q.flush(send,100);self.assertEqual(len(calls),1);self.assertEqual(result['pending'],1);self.assertEqual(result['consent'],'disabled')
    def test_off_persistence_failure_fails_closed(self):
        self.q.choose('enabled');self.q.enqueue(self.e);self.q.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(Exception):self.q.choose('disabled')
        calls=[];self.q.flush(lambda e:calls.append(e),100);self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
