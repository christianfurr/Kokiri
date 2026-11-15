#!/usr/bin/env python3
"""Exercise official Sparkle signing using temporary, non-production fixtures."""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('kokiri_release', Path(__file__).with_name('prepare.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=release.ROOT / 'macos/build/Kokiri.app')
    args = parser.parse_args()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    checks = []
    peak = 0
    with tempfile.TemporaryDirectory(prefix='kokiri-sparkle-test-') as temporary:
        workspace = Path(temporary)
        os.chmod(workspace, 0o700)

        def size():
            total = 0
            for path in workspace.rglob('*'):
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue  # The generator atomically renames its cache trees.
                if not stat.S_ISDIR(metadata.st_mode):
                    total += metadata.st_size
            return total

        def run(arguments, succeeds=True):
            nonlocal peak
            process = subprocess.Popen([str(x) for x in arguments], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            deadline = time.monotonic() + 180
            try:
                while process.poll() is None:
                    peak = max(peak, size())
                    if peak > 50 << 20 or time.monotonic() > deadline:
                        raise ValueError('Test workspace bound or command deadline exceeded')
                    time.sleep(0.05)
                stdout, _ = process.communicate()
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
            peak = max(peak, size())
            release.require(peak <= 50 << 20, 'Test workspace exceeded 50 MiB')
            release.require((process.returncode == 0) == succeeds, 'Unexpected result from ' + Path(str(arguments[0])).name)
            return stdout.decode('utf-8')

        def rejects(label, action):
            try:
                action()
            except (ValueError, OSError, KeyError):
                checks.append(label)
                return
            raise ValueError('Expected rejection: ' + label)

        seed = os.urandom(32)
        key = workspace / 'ephemeral-test-seed'
        key.write_bytes(base64.b64encode(seed))
        os.chmod(key, 0o600)
        public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        tools = release.sparkle_tools()
        signer = release.Signer(tools, key_file=key)
        checks.append('official Sparkle 2.10.0 artifact and signing-tool hashes')

        def fixture(name, version, build):
            parent = workspace / name
            parent.mkdir()
            app = parent / 'Kokiri.app'
            run(['/bin/cp', '-cR', args.app.resolve(strict=True), app])
            info_path = app / 'Contents/Info.plist'
            info = plistlib.loads(info_path.read_bytes())
            info.update(CFBundleShortVersionString=version, CFBundleVersion=str(build),
                        SUFeedURL='https://updates.invalid/appcast.xml',
                        SUPublicEDKey=base64.b64encode(public).decode(),
                        SURequireSignedFeed=True, SUVerifyUpdateBeforeExtraction=True,
                        SUSignedFeedFailureExpirationInterval=0)
            info_path.write_bytes(plistlib.dumps(info))
            run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', app])
            return app

        old = fixture('old', '0.1.0', 1)
        new = fixture('new', '0.1.1', 2)
        old_output, new_output = workspace / 'old-output', workspace / 'new-output'

        def prepare(app, output, previous, history=None):
            arguments = [sys.executable, Path(__file__).with_name('prepare.py'), '--app', app,
                         '--output', output, '--download-prefix', 'https://updates.invalid/downloads/',
                         '--previous-build', str(previous), '--key-file', key, '--development']
            if history:
                arguments += ['--history', history]
            return json.loads(run(arguments))

        first = prepare(old, old_output, 0)
        second = prepare(new, new_output, 1, old_output)
        archive = new_output / second['archive']
        feed = new_output / second['feed']
        signer.verify(archive, second['archive_signature'])
        checks.append('actual sign_update accepts valid full-archive signature')
        signer.verify(feed)
        checks.append('actual sign_update accepts valid embedded feed signature')

        tampered = workspace / 'tampered.zip'
        tampered.write_bytes(archive.read_bytes() + b'tampered')
        rejects('actual sign_update rejects modified archive', lambda: signer.verify(tampered, second['archive_signature']))
        tampered.unlink()
        tampered_feed = workspace / 'tampered.xml'
        original_feed = feed.read_bytes()
        release.require(b'0.1.1' in original_feed, 'Expected display version is absent')
        tampered_feed.write_bytes(original_feed.replace(b'0.1.1', b'0.1.9', 1))
        rejects('actual sign_update rejects modified signed feed', lambda: signer.verify(tampered_feed))

        wrong_key = workspace / 'wrong-test-seed'
        wrong_key.write_bytes(base64.b64encode(os.urandom(32)))
        os.chmod(wrong_key, 0o600)
        other = release.Signer(tools, key_file=wrong_key)
        rejects('actual sign_update rejects a different signing key', lambda: other.verify(archive, second['archive_signature']))

        rejects('production rejects an unqualified development bundle', lambda: release.validate_app(new))
        info = release.validate_app(new, development=True)
        unsafe = {**info, 'SUFeedURL': 'http://updates.invalid/appcast.xml'}
        rejects('metadata rejects an HTTP feed', lambda: release.validate_info(unsafe, True))
        unsafe = {**info, 'CFBundleIdentifier': 'com.example.game'}
        rejects('metadata rejects a non-shell product', lambda: release.validate_info(unsafe, True))
        unsafe = {**info, 'SURequireSignedFeed': False}
        rejects('metadata rejects an unsigned-feed policy', lambda: release.validate_info(unsafe, True))
        unsafe = {**info, 'SUPublicEDKey': base64.b64encode(b'short').decode()}
        rejects('metadata rejects an invalid public key', lambda: release.validate_info(unsafe, True))
        payload = new / 'Contents/Resources/game.nsp'
        payload.write_bytes(b'private-fixture-only')
        rejects('bundle boundary rejects game data before packaging', lambda: release.validate_app(new, development=True))
        payload.unlink()
        payload = new / 'Contents/Frameworks/Sparkle.framework/Versions/B/game.nsp'
        payload.write_bytes(b'private-fixture-only')
        rejects('framework boundary rejects files absent from official Sparkle', lambda: release.validate_app(new, development=True))
        payload.unlink()
        unsafe_archive = workspace / 'unexpected.zip'
        with zipfile.ZipFile(unsafe_archive, 'w') as fixture_zip:
            fixture_zip.writestr('Kokiri.app/Contents/Resources/game.nsp', b'private-fixture-only')
        rejects('archive boundary rejects game data', lambda: release.validate_archive(unsafe_archive))
        unsafe_archive.unlink()
        run([sys.executable, Path(__file__).with_name('prepare.py'), '--app', new,
             '--output', workspace / 'wrong-key-output', '--download-prefix', 'https://updates.invalid/',
             '--previous-build', '1', '--key-file', wrong_key, '--development'], succeeds=False)
        release.require(not (workspace / 'wrong-key-output').exists(), 'Mismatched signing key created output')
        checks.append('app-pinned key mismatch refuses packaging')
        os.chmod(wrong_key, 0o644)
        rejects('key material must have owner-only permissions', lambda: release.Signer(tools, key_file=wrong_key))
        os.chmod(wrong_key, 0o600)
        with zipfile.ZipFile(unsafe_archive, 'w') as fixture_zip:
            fixture_zip.writestr('../escaped', b'private-fixture-only')
        rejects('archive boundary rejects path traversal', lambda: release.validate_archive(unsafe_archive))
        unsafe_archive.unlink()
        # Build-number rejection happens before output creation or signing.
        run([sys.executable, Path(__file__).with_name('prepare.py'), '--app', new,
             '--output', workspace / 'rejected-output', '--download-prefix', 'https://updates.invalid/',
             '--previous-build', '2', '--key-file', key, '--development'], succeeds=False)
        release.require(not (workspace / 'rejected-output').exists(), 'Rejected release created output')
        checks.append('unchanged build number refuses packaging')

        xml = ET.parse(feed)
        deltas = xml.findall('.//' + release.SPARKLE_NS + 'deltas/enclosure')
        delta_checked = False
        if deltas:
            release.require(len(deltas) == 1, 'Expected one bounded delta')
            enclosure = deltas[0]
            from urllib.parse import urlsplit, unquote
            delta = new_output / unquote(Path(urlsplit(enclosure.get('url')).path).name)
            release.require(delta.parent == new_output and delta.is_file(), 'Delta was not generated locally')
            signer.verify(delta, enclosure.get(release.SPARKLE_NS + 'edSignature'))
            checks.append('actual sign_update accepts generated delta signature')
            patched = workspace / 'patched.app'
            run([tools / 'BinaryDelta', 'apply', old, patched, delta])
            expected = {p.relative_to(new).as_posix(): (os.readlink(p) if p.is_symlink() else release.sha(p))
                        for p in new.rglob('*') if p.is_symlink() or p.is_file()}
            actual = {p.relative_to(patched).as_posix(): (os.readlink(p) if p.is_symlink() else release.sha(p))
                      for p in patched.rglob('*') if p.is_symlink() or p.is_file()}
            release.require(expected == actual, 'Patched fixture differs from the new shell')
            checks.append('actual BinaryDelta reconstructs every new file and symlink')
            delta_checked = True

        report = dict(tested_at_utc=datetime.now(timezone.utc).isoformat(),
                      sparkle_version='2.10.0', sparkle_artifact_sha256=release.SPARKLE_SHA256,
                      prepare_source_sha256=release.sha(Path(__file__).with_name('prepare.py')),
                      selftest_source_sha256=release.sha(__file__),
                      checks_passed=len(checks), checks=checks, fixture_versions=['0.1.0 (1)', '0.1.1 (2)'],
                      peak_workspace_bytes=peak, workspace_limit_bytes=50 << 20,
                      delta_signature_verified=delta_checked,
                      production_key_created=False, keychain_modified=False,
                      uploaded=False, installation_tested=False, runtime_update_tested=False)
    report['temporary_workspace_removed'] = not workspace.exists()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        raise SystemExit('Sparkle self-test failed: ' + str(error))
