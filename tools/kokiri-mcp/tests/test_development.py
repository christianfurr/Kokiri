"""No game launched: independently copied fixtures and mocked process/launch boundary."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import tempfile
import time
import struct
import unittest
from unittest.mock import patch
import zlib
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from development import Development, PATHS, COORDINATOR, profile_manifest, digest
from commands import action, scenario
from kokiri import KokiriError, ProcessReader, atomic_json


class Process:
    value=None
    human=False
    def sample(self,pid): return dict(self.value) if self.value and pid==self.value['pid'] else None
    def game_running(self): return self.human


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name).resolve()
        self.workspace=self.root/'workbench';self.workspace.mkdir(mode=0o700)
        self.fixture=self.root/'fixture';self.fixture.mkdir();(self.fixture/'save').mkdir()
        (self.fixture/'save/test.bin').write_bytes(b'original-test-save')
        app=self.root/'Game.app';(app/'Contents/MacOS').mkdir(parents=True)
        self.exe=app/'Contents/MacOS/KokiriGame';self.exe.write_bytes(b'synthetic-no-executable')
        info=plistlib.dumps({'CFBundleIdentifier':'com.christianfurr.kokiri.runtime','CFBundleExecutable':'KokiriGame','KokiriDevelopmentVersion':1})
        (app/'Contents/Info.plist').write_bytes(info)
        self.runtime={'app':str(app),'executable_sha256':digest(self.exe),'info_sha256':hashlib.sha256(info).hexdigest(),
                      'isolation_acceptance':{'passed':True,'executable_sha256':digest(self.exe)}}
        self.registry={'schema':1,'runtimes':{'test':self.runtime},'fixtures':{'test':{'profile':str(self.fixture)}},'permit_file':str(self.root/'permit.json')}
        atomic_json(self.workspace/'registry.json',self.registry)
        self.process=Process();self.manager=Development(self.workspace,self.process)
        self.created=self.manager.create('test','test');self.id=self.created['session_id'];self.session=self.workspace/'sessions'/self.id

    def tearDown(self):self.temporary.cleanup()

    def live(self,slot=True):
        self.process.value={'pid':991,'executable':str(self.exe),'process_start':123,'process_uuid':'ab'*16,'physical_footprint_bytes':2048,'resident_bytes':1024}
        atomic_json(self.session/'session.json',self.process.value)
        request={'schema':1,'session_id':self.id,'nonce':'ab'*32,'expires_unix':time.time()+600,'executable_sha256':digest(self.exe)}
        atomic_json(self.session/'request.json',request);atomic_json(self.session/'lease.json',request)
        atomic_json(self.session/'isolation.json',dict(self.process.value,schema=1,isolation_version=1,session_id=self.id,nonce=request['nonce'],
            executable_sha256=digest(self.exe),game_slot_acquired=slot,effective_paths={k:str(self.session/v) for k,v in PATHS.items()}))
        self.grant()

    def grant(self):
        atomic_json(self.root/'permit.json',{'schema':1,'issuer':COORDINATOR,'state':'granted','session_id':self.id,
            'executable_sha256':digest(self.exe),'expires_unix':time.time()+700})

    def test_profile_copy_is_independent_and_source_unchanged(self):
        copied=self.session/'profile/save/test.bin';source=self.fixture/'save/test.bin'
        self.assertEqual(copied.read_bytes(),source.read_bytes());self.assertNotEqual(copied.stat().st_ino,source.stat().st_ino)
        copied.write_bytes(b'test-only-edit');self.assertEqual(source.read_bytes(),b'original-test-save')

    def test_human_id_and_path_traversal_never_adopted(self):
        for identifier in ['../fixture','human','ab'*10]:
            with self.assertRaises(KokiriError):self.manager.close(identifier)
        self.assertFalse((self.fixture/'revoked').exists())

    def test_fixture_links_and_workspace_nesting_rejected(self):
        (self.fixture/'link').symlink_to(self.exe)
        with self.assertRaises(KokiriError):self.manager.create('test','test')
        (self.fixture/'link').unlink()
        os.link(self.exe,self.fixture/'hardlink')
        with self.assertRaises(KokiriError):self.manager.create('test','test')
        (self.fixture/'hardlink').unlink()
        self.registry['fixtures']['test']['profile']=str(self.workspace)
        atomic_json(self.workspace/'registry.json',self.registry)
        with self.assertRaises(KokiriError):self.manager.create('test','test')

    def test_configured_ack_cannot_authorize_control_before_slot(self):
        self.live(slot=False)
        with self.assertRaises(KokiriError):self.manager.action(self.id,{'action':'button','button':'a','milliseconds':100})
        self.assertEqual((self.session/'input.txt').read_text(),'')

    def test_exact_identity_lease_revocation_and_expiry_fail_closed(self):
        self.live();request=json.loads((self.session/'request.json').read_text())
        self.assertEqual(self.manager.action(self.id,{'action':'button','button':'a','milliseconds':100})['status'],'queued')
        wire=(self.session/'input.txt').read_text();self.assertIn('button a100'.replace('a100','a 100'),wire)
        self.assertIn(request['nonce'],wire)
        (self.session/'revoked').touch()
        with self.assertRaises(KokiriError):self.manager.action(self.id,{'action':'position'})
        (self.session/'revoked').unlink();lease=dict(request,expires_unix=time.time()-1);atomic_json(self.session/'lease.json',lease)
        with self.assertRaises(KokiriError):self.manager.action(self.id,{'action':'position'})
        atomic_json(self.session/'lease.json',request);self.process.value['process_start']+=1
        with self.assertRaises(KokiriError):self.manager.close(self.id)
        self.assertEqual((self.session/'input.txt').read_text(),wire)

    def test_launch_requires_grant_and_human_exclusion_before_popen(self):
        with patch('development.subprocess.Popen') as spawn:
            with self.assertRaises((KokiriError,FileNotFoundError)):self.manager.launch(self.id)
            self.grant();self.process.human=True
            with self.assertRaises(KokiriError):self.manager.launch(self.id)
        spawn.assert_not_called()

    def test_known_shared_slot_games_are_detected_without_adoption(self):
        reader=ProcessReader()
        for target in ('Bananza','Pokopia'):
            with self.subTest(target=target),patch('kokiri.sys.platform','darwin'),patch('kokiri.subprocess.run') as probe:
                probe.side_effect=lambda command,**kw: type('Result',(),{'returncode':0 if command[-1]==target else 1})()
                self.assertTrue(reader.game_running())

    def test_stopped_settings_are_allowlisted_and_atomic_validation(self):
        with self.assertRaises(KokiriError):self.manager.configure(self.id,{'graphics-overlay.txt':2,'unknown':'/outside'})
        self.assertEqual(list((self.session/'settings/game').iterdir()),[])
        self.manager.configure(self.id,{'graphics-overlay.txt':2})
        self.assertEqual((self.session/'settings/game/graphics-overlay.txt').read_text(),'2\n')
        self.live()
        with self.assertRaises(KokiriError):self.manager.configure(self.id,{'graphics-overlay.txt':1})

    def test_entire_scenario_validated_before_effect(self):
        self.live()
        with self.assertRaises(KokiriError):self.manager.run(self.id,[{'action':'button','button':'a','milliseconds':100},{'action':'shell','command':'anything'}])
        self.assertEqual((self.session/'input.txt').read_text(),'')

    def test_shortened_lease_rejected_before_scenario_first_action(self):
        self.live()
        lease=json.loads((self.session/'lease.json').read_text())
        lease['expires_unix']=time.time()+.1
        atomic_json(self.session/'lease.json',lease)
        with self.assertRaises(KokiriError):
            self.manager.run(self.id,[{'action':'button','button':'a','milliseconds':100}])
        self.assertEqual((self.session/'input.txt').read_text(),'')

    def test_scenario_does_not_echo_private_acceptance_proof(self):
        self.live()
        path=self.session/'ownership.json';owned=json.loads(path.read_text())
        owned['runtime']['isolation_acceptance']['nonce']='PRIVATE-ATTESTATION-NONCE'
        atomic_json(path,owned)
        report=self.manager.run(self.id,[{'action':'checkpoint','label':'test boundary'}])
        self.assertEqual(report['status'],'completed')
        self.assertNotIn('PRIVATE-ATTESTATION-NONCE',json.dumps(report))
        self.assertNotIn('isolation_acceptance',report['runtime'])

    def test_unverified_spawn_cannot_be_closed_into_editable_state(self):
        self.grant()
        with patch('development.subprocess.run'),patch('development.subprocess.Popen') as spawn:
            spawn.return_value.pid=991;spawn.return_value.poll.return_value=0
            with self.assertRaises(KokiriError):self.manager.launch(self.id,10)
        self.assertEqual(json.loads((self.session/'ownership.json').read_text())['state'],'unverified')
        with self.assertRaises(KokiriError):self.manager.close(self.id)
        with self.assertRaises(KokiriError):self.manager.reset(self.id)
        with self.assertRaises(KokiriError):self.manager.configure(self.id,{'graphics-overlay.txt':2})

    def test_action_bounds_and_unknown_fields(self):
        invalid=[{'action':'stick','stick':'left','x':float('nan'),'y':0,'milliseconds':10},
                 {'action':'button','button':'a','milliseconds':5001},{'action':'move','map':'Forest\nclose','x':0,'y':0,'z':0},
                 {'action':'settings','page':True},{'action':'position','command':'close'}]
        for step in invalid:
            with self.assertRaises(KokiriError):action(step)
        with self.assertRaises(KokiriError):scenario([{'action':'warp','destination':'field'}]*2)

    def test_settings_parent_symlink_cannot_redirect_writes(self):
        outside=self.root/'outside-settings';outside.mkdir()
        private=self.session/'settings/game';private.rmdir();private.symlink_to(outside,target_is_directory=True)
        with self.assertRaises((KokiriError,OSError)):
            self.manager.configure(self.id,{'graphics-overlay.txt':2})
        self.assertEqual(list(outside.iterdir()),[])

    def test_log_links_are_rejected_before_spawn_or_external_write(self):
        self.grant()
        outside=self.root/'outside.log';outside.write_bytes(b'unchanged private fixture')
        target=self.session/'game-full.log'
        for kind in ('symlink','hardlink'):
            with self.subTest(kind=kind):
                if kind=='symlink':target.symlink_to(outside)
                else:os.link(outside,target)
                try:
                    with patch('development.subprocess.run'),patch('development.subprocess.Popen') as spawn:
                        with self.assertRaises((KokiriError,OSError)):
                            self.manager.launch(self.id)
                        spawn.assert_not_called()
                    self.assertEqual(outside.read_bytes(),b'unchanged private fixture')
                finally:target.unlink()

    def test_launch_spawns_with_clean_environment_and_reports_starting_only(self):
        self.grant()
        self.process.value={'pid':991,'executable':str(self.exe),'process_start':123,'process_uuid':'ab'*16,
                            'physical_footprint_bytes':2048,'resident_bytes':1024}
        contaminated={'TOTK_PROFILE_DIR':'/synthetic-human-profile','TOTK_INPUT_SCRIPT':'unsafe-inherited-input',
                      'DYLD_INSERT_LIBRARIES':'/synthetic-injection.dylib','DM_NVN_TSV':'/synthetic-external.log'}
        with patch.dict(os.environ,contaminated),patch('development.subprocess.run') as signature,patch('development.subprocess.Popen') as spawn:
            spawn.return_value.pid=991;spawn.return_value.poll.return_value=None
            result=self.manager.launch(self.id,seconds=10)
            self.assertEqual(result['status'],'starting')
            self.assertFalse(result['isolation_accepted'])
            owned=json.loads((self.session/'ownership.json').read_text())
            self.assertEqual(owned['cache_condition'],'private cache; current cold/warm state unverified')
            configuration=spawn.call_args.kwargs
            environment=configuration['env']
            self.assertTrue(set(contaminated).isdisjoint(environment))
            self.assertEqual(set(environment),{'PATH','HOME','TMPDIR','LANG','KOKIRI_DEVELOPMENT_ROOT','KOKIRI_DEVELOPMENT_NONCE'})
            self.assertEqual(environment['KOKIRI_DEVELOPMENT_ROOT'],str(self.session))
            self.assertEqual(environment['TMPDIR'],str(self.session/'tmp'))
            self.assertTrue(configuration['start_new_session'])
            self.assertEqual(spawn.call_args.args[0],[str(self.exe),'--kokiri-development',str(self.session)])
            signature.assert_called_once()
            self.assertEqual(signature.call_args.args[0][:4],['/usr/bin/codesign','--verify','--deep','--strict'])

    def test_frame_settings_use_runtime_lock_grammar(self):
        for wrong in ('30','60'):
            with self.assertRaises(KokiriError):self.manager.configure(self.id,{'graphics-frame.txt':wrong})
        self.manager.configure(self.id,{'graphics-frame.txt':'lock-60'})
        self.assertEqual((self.session/'settings/game/graphics-frame.txt').read_text(),'lock-60\n')

    @staticmethod
    def png():
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x00\x00\x00\x00'))+chunk(b'IEND',b'')

    def test_native_capture_rechecks_identity_and_rejects_incomplete_png(self):
        self.live()
        folder=self.session/'capture-fixture';folder.mkdir()
        path=folder/'window.png';path.write_bytes(self.png())
        with patch('development.SessionStore.capture_request',return_value=path):
            result=self.manager.capture(self.id)
            self.assertEqual(result['surface'],'window');self.assertEqual(result['png'],self.png())
            path.write_bytes(self.png()[:-1])
            with self.assertRaises(KokiriError):self.manager.capture(self.id)
        path.write_bytes(self.png())
        def change_identity(*args,**kwargs):
            self.process.value['process_start']+=1
            return path
        with patch('development.SessionStore.capture_request',side_effect=change_identity):
            with self.assertRaises(KokiriError):self.manager.capture(self.id)


if __name__=='__main__':unittest.main()
