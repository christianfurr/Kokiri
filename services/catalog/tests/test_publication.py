import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publication',ROOT/'scripts/prepare-publication.py')
publication=importlib.util.module_from_spec(spec);spec.loader.exec_module(publication)

class Publication(unittest.TestCase):
    def test_reviewed_seed_signature_sql_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=Path(tmp)/'test-only.pem'
            key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
            sql=Path(tmp)/'publication.sql'
            result=publication.prepare(ROOT/'seed/reference',key,'test-only',sql)
            self.assertFalse(result['uploaded']);self.assertEqual(result['records'],56)
            db=sqlite3.connect(':memory:');db.executescript((ROOT/'migrations/0001_catalog.sql').read_text());db.executescript(sql.read_text())
            envelope=json.loads(db.execute('SELECT envelope FROM manifests').fetchone()[0])
            verified=publication.sdk.verify_manifest(envelope,envelope['manifest']['context'],{'test-only':result['public_key']},False)
            self.assertEqual(verified['compatibility'],'reference-only')
            with self.assertRaises(ValueError):publication.sdk.verify_manifest(envelope,verified['context'],{'test-only':result['public_key']},True)
            with self.assertRaises(FileExistsError):publication.prepare(ROOT/'seed/reference',key,'test-only',sql)
            with self.assertRaises(sqlite3.IntegrityError):db.executescript(sql.read_text())
            db.close()
    def test_tampered_pack_refuses_output(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            seed=Path(tmp)/'seed';shutil.copytree(ROOT/'seed/reference',seed)
            pack=next((seed/'packs').glob('*.json'));pack.write_text(pack.read_text()+' ')
            key=Path(tmp)/'test-only.pem';key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
            output=Path(tmp)/'must-not-exist.sql'
            with self.assertRaises(ValueError):publication.prepare(seed,key,'test-only',output)
            self.assertFalse(output.exists())

if __name__=='__main__':unittest.main()
