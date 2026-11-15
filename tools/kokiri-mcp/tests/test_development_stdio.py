"""Real development SDK discovery and stopped synthetic-session operations."""
import hashlib
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

from mcp import Client
from mcp.client.stdio import StdioServerParameters

PACKAGE=Path(__file__).resolve().parents[1]


class DevelopmentStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_save_plan_apply_restore_preserves_fixture(self):
        from test_save_workshop import SaveWorkshopTests
        SaveWorkshopTests.setUpClass()
        fixture=SaveWorkshopTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();workspace=root/'workbench';workspace.mkdir(mode=0o700)
            app=root/'Game.app';(app/'Contents/MacOS').mkdir(parents=True)
            executable=app/'Contents/MacOS/KokiriGame';executable.write_bytes(b'synthetic-not-game')
            info=plistlib.dumps({'CFBundleIdentifier':'com.christianfurr.kokiri.runtime','CFBundleExecutable':'KokiriGame','KokiriDevelopmentVersion':1})
            (app/'Contents/Info.plist').write_bytes(info)
            (workspace/'registry.json').write_text(json.dumps({'schema':1,'runtimes':{'test':{'app':str(app),
                'info_sha256':hashlib.sha256(info).hexdigest(),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}},
                'fixtures':{'test':{'profile':str(fixture.profile)}}}))
            params=StdioServerParameters(command=sys.executable,args=[str(PACKAGE/'development_server.py'),'--workspace',str(workspace)],cwd=str(PACKAGE))
            async with Client(params,read_timeout_seconds=10) as client:
                created=await client.call_tool('development_create',{'runtime_id':'test','fixture_id':'test'})
                self.assertFalse(created.is_error);session=created.structured_content['session_id']
                snapshot=await client.call_tool('development_save_snapshot',{'session_id':session,'slot':0})
                self.assertFalse(snapshot.is_error);before=snapshot.structured_content
                planned=await client.call_tool('development_save_plan',{'session_id':session,'slot':0,'expected_snapshot':before['snapshot_id'],'changes':{'rupees':75}})
                self.assertFalse(planned.is_error);self.assertEqual(planned.structured_content['after']['rupees'],75)
                arguments={'session_id':session,'plan_id':planned.structured_content['plan_id']}
                applied=await client.call_tool('development_save_apply',arguments)
                self.assertFalse(applied.is_error);self.assertEqual(applied.structured_content['status'],'applied')
                repeated=await client.call_tool('development_save_apply',arguments)
                self.assertTrue(repeated.structured_content['already_applied'])
                restored=await client.call_tool('development_save_restore',{'session_id':session,'snapshot_id':before['snapshot_id']})
                self.assertFalse(restored.is_error)
                after=await client.call_tool('development_save_snapshot',{'session_id':session,'slot':0})
                self.assertEqual(after.structured_content['state']['rupees'],before['state']['rupees'])
            self.assertEqual(fixture.workshop.snapshot(0)['state']['rupees'],10)

    async def test_separate_server_creates_only_stopped_test_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();workspace=root/'workbench';workspace.mkdir(mode=0o700)
            profile=root/'fixture';profile.mkdir();(profile/'sample').write_bytes(b'private-synthetic')
            app=root/'Game.app';(app/'Contents/MacOS').mkdir(parents=True)
            executable=app/'Contents/MacOS/KokiriGame';executable.write_bytes(b'synthetic-not-game')
            info=plistlib.dumps({'CFBundleIdentifier':'com.christianfurr.kokiri.runtime','CFBundleExecutable':'KokiriGame','KokiriDevelopmentVersion':1})
            (app/'Contents/Info.plist').write_bytes(info)
            (workspace/'registry.json').write_text(json.dumps({'schema':1,'runtimes':{'test':{'app':str(app),
                'info_sha256':hashlib.sha256(info).hexdigest(),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}},
                'fixtures':{'test':{'profile':str(profile)}}}))
            params=StdioServerParameters(command=sys.executable,args=[str(PACKAGE/'development_server.py'),'--workspace',str(workspace)],cwd=str(PACKAGE))
            async with Client(params,read_timeout_seconds=10) as client:
                listed=await client.list_tools();names={tool.name for tool in listed.tools}
                self.assertIn('development_save_plan',names);self.assertIn('development_scenario',names)
                self.assertFalse(names&{'shell','read_file','write_file','command','memory_write','session_adopt'})
                options=await client.call_tool('development_options',{});self.assertEqual(options.structured_content['fixtures'],['test'])
                created=await client.call_tool('development_create',{'runtime_id':'test','fixture_id':'test'})
                self.assertFalse(created.is_error);session_id=created.structured_content['session_id']
                settings=await client.call_tool('development_configure',{'session_id':session_id,'settings':{'graphics-overlay.txt':2}})
                self.assertFalse(settings.is_error)
                launch=await client.call_tool('development_launch',{'session_id':session_id})
                self.assertTrue(launch.is_error)
                human=await client.call_tool('development_close',{'session_id':'human'})
                self.assertTrue(human.is_error)
                invalid=await client.call_tool('development_save_snapshot',{'session_id':session_id,'slot':9})
                self.assertTrue(invalid.is_error)
            self.assertEqual((profile/'sample').read_bytes(),b'private-synthetic')
            self.assertFalse((workspace/'sessions'/session_id/'session.json').exists())
            self.assertEqual((workspace/'sessions'/session_id/'input.txt').read_text(),'')


if __name__=='__main__':unittest.main()
