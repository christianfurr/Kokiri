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

    def test_parent_symlink_cannot_read_external_working_file(self):
        directory = self.root / 'public'
        directory.mkdir()
        (directory / 'source.txt').write_text('tracked source')
        self.git('add', 'public/source.txt')
        shutil.rmtree(directory)
        with tempfile.TemporaryDirectory() as external:
            (Path(external) / 'source.txt').write_text('external private bytes')
            directory.symlink_to(external, target_is_directory=True)
            result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink in file path', result.stdout)
        self.assertNotIn('external private bytes', result.stdout)

    def test_submodule_is_rejected_without_reading_commit_as_blob(self):
        self.git('update-index', '--add', '--cacheinfo',
                 '160000,1111111111111111111111111111111111111111,dependency')
        result = self.scan('--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported Git mode', result.stdout)
        self.assertNotIn('fatal:', result.stderr)

    def test_reviewed_app_image_rejects_replacement_bytes(self):
        relative = Path('assets/readme/kokiri-home.png')
        image = self.root / relative
        image.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / relative, image)
        self.git('add', str(relative))
        self.assertEqual(self.scan('--staged').returncode, 0)
        image.write_bytes(image.read_bytes() + b'private appended payload')
        self.git('add', str(relative))
        result = self.scan('--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('app image changed; review provenance', result.stdout)
        self.assertNotIn('private appended payload', result.stdout)

    def test_unused_image_name_has_no_provenance_exemption(self):
        image = self.root / 'assets/readme/kokiri-menu.png'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'\x89PNG\r\n\x1a\nprivate payload')
        self.assertNotEqual(self.scan().returncode, 0)

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
