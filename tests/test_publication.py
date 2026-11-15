"""Publication checks against real disposable Git indexes, including forced files."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'scripts').mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts/check_publication.py',
                        self.root / 'scripts/check_publication.py')
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def scan(self, *args):
        return subprocess.run([sys.executable, 'scripts/check_publication.py', *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_staged_blobs_do_not_read_later_working_bytes(self):
        file = self.root / 'source.py'
        file.write_text('print(1)\n')
        self.git('add', 'source.py')
        file.write_bytes(b'\x7fELF\0private payload')
        self.assertEqual(self.scan('--staged').returncode, 0)
        self.assertNotEqual(self.scan().returncode, 0)

    def test_force_added_ignored_game_content_is_rejected(self):
        (self.root / '.gitignore').write_text('*.bin\n')
        (self.root / 'main.patched.bin').write_bytes(b'private game content')
        self.git('add', '-f', 'main.patched.bin')
        result = self.scan('--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('main.patched.bin', result.stdout)
        self.assertNotIn('private game content', result.stdout)

    def test_credential_bytes_are_not_printed(self):
        secret = 'ghp_' + 'aB3x' * 10
        (self.root / 'config.txt').write_text(secret)
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('contents suppressed', result.stdout)
        self.assertNotIn(secret, result.stdout)

    def test_symlink_cannot_publish_an_external_file(self):
        (self.root / 'external-link').symlink_to('/etc/hosts')
        self.git('add', 'external-link')
        self.assertNotEqual(self.scan('--staged').returncode, 0)

    def test_reviewed_website_image_rejects_replacement_bytes(self):
        relative = Path('website/assets/kokiri-mark.png')
        image = self.root / relative
        image.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / relative, image)
        self.git('add', str(relative))
        self.assertEqual(self.scan('--staged').returncode, 0)
        image.write_bytes(image.read_bytes() + b'changed')
        self.git('add', str(relative))
        result = self.scan('--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('website image changed; review provenance', result.stdout)


if __name__ == '__main__':
    unittest.main()
