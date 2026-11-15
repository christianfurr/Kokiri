from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parents[1]

class NativeClient(unittest.TestCase):
    def test_actual_actor(self):
        with tempfile.TemporaryDirectory() as out:
            binary=Path(out)/'catalog-client-tests'
            subprocess.run(['swiftc','-swift-version','5','-parse-as-library',
                str(PROJECT/'macos/Sources/KokiriCore/Installation.swift'),
                str(PROJECT/'macos/Sources/KokiriCore/CatalogClient.swift'),
                str(ROOT/'tests/native_actor.swift'),'-o',str(binary)],check=True,timeout=60)
            result=subprocess.run([str(binary)],cwd=ROOT,text=True,capture_output=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS native CatalogClient',result.stdout)
            print(result.stdout.strip())

if __name__=='__main__':unittest.main()
