#!/usr/bin/env python3
"""Prepare signed Kokiri shell updates. Never uploads or installs an update."""
import argparse
import base64
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPARKLE_SHA256 = '17e28312b8e18ab7cdbbe09a6fb28cc55a5479ec6c371dbc07cdecd2a14fd959'
SPARKLE_NS = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'
RESOURCES = {'LICENSE', 'THIRD_PARTY_NOTICES.md', 'Sparkle-LICENSE', 'KokiriMark.png', 'Kokiri.icns'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def command(arguments, *, secret_input=None, environment=None):
    result = subprocess.run([str(x) for x in arguments], input=secret_input,
                            capture_output=True, timeout=180, env=environment)
    # Tool diagnostics can contain signing-file contents. Do not echo them.
    if result.returncode:
        raise ValueError(f'{Path(str(arguments[0])).name} failed (exit {result.returncode}); no signing material printed')
    return result.stdout.decode('utf-8')


def https(value, *, prefix=False):
    require(isinstance(value, str), 'HTTPS URL must be a string')
    u = urllib.parse.urlsplit(value)
    require(u.scheme == 'https' and u.hostname and not u.username and not u.password
            and not u.query and not u.fragment, 'Expected HTTPS URL without credentials, query or fragment')
    require(not prefix or value.endswith('/'), 'Download prefix must end with /')
    return value


def allowed_bundle_path(path):
    p = PurePosixPath(path)
    require(not p.is_absolute() and '..' not in p.parts, 'Archive path escapes its bundle')
    return (str(p) in {'Contents/Info.plist', 'Contents/PkgInfo', 'Contents/MacOS/Kokiri'}
            or str(p) == 'Contents/_CodeSignature/CodeResources'
            or str(p) in sparkle_framework_paths()
            or str(p) in {'Contents/Resources/' + name for name in RESOURCES})


@lru_cache(maxsize=1)
def sparkle_framework_paths():
    archive = ROOT / 'macos/.build/vendor/Sparkle-2.10.0.zip'
    require(archive.is_file() and sha(archive) == SPARKLE_SHA256, 'Prepare the checksum-pinned official Sparkle artifact first')
    prefix = 'Sparkle.xcframework/macos-arm64_x86_64/'
    with zipfile.ZipFile(archive) as source:
        return {('Contents/Frameworks/' + item.filename.removeprefix(prefix)).rstrip('/')
                for item in source.infolist() if item.filename.startswith(prefix)}


def validate_info(info, development):
    require(isinstance(info, dict), 'Bundle metadata must be a property-list dictionary')
    require(info.get('CFBundleIdentifier') == 'com.christianfurr.kokiri'
            and info.get('CFBundleExecutable') == 'Kokiri', 'Only the Kokiri shell can be released here')
    version, build = info.get('CFBundleShortVersionString'), info.get('CFBundleVersion')
    require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version), 'Product version must have three numeric components')
    require(isinstance(build, str) and re.fullmatch(r'[1-9][0-9]{0,11}', build), 'Build number must be a positive decimal integer of at most 12 digits')
    require(info.get('SURequireSignedFeed') is True and info.get('SUVerifyUpdateBeforeExtraction') is True
            and info.get('SUSignedFeedFailureExpirationInterval') == 0, 'Required Sparkle signature settings are missing')
    https(info.get('SUFeedURL', ''))
    key = base64.b64decode(info.get('SUPublicEDKey', ''), validate=True)
    require(len(key) == 32, 'The app must pin its real Ed25519 public key')
    if not development:
        require(re.fullmatch(r'[a-f0-9]{40}', info.get('KokiriSourceCommit', '')) is not None
                and info.get('KokiriSourceDirty') is False, 'Production releases require clean source-commit metadata')
    return version, int(build), key


def validate_app(app, *, development=False):
    app = Path(app).resolve(strict=True)
    require(app.name == 'Kokiri.app' and app.is_dir(), 'Bundle must be named Kokiri.app')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    validate_info(info, development)
    for path in app.rglob('*'):
        if path.is_symlink():
            require(path.resolve().is_relative_to(app), 'Bundle symlink escapes the shell')
        elif path.is_dir():
            continue
        require(allowed_bundle_path(path.relative_to(app).as_posix()), 'Unexpected shell payload: ' + path.relative_to(app).as_posix())
    require((app / 'Contents/MacOS/Kokiri').is_file(), 'Shell executable is missing')
    command(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    if not development:
        require(command(['/usr/bin/git', '-C', ROOT, 'rev-parse', 'HEAD']).strip() == info['KokiriSourceCommit']
                and not command(['/usr/bin/git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=normal']).strip(),
                'Production release must match this clean source checkout')
        details = subprocess.run(['/usr/bin/codesign', '-d', '--verbose=4', str(app)], capture_output=True, text=True, check=True).stderr
        require('Authority=Developer ID Application:' in details and 'runtime' in details, 'Production shell needs Developer ID and hardened runtime')
        command(['/usr/bin/xcrun', 'stapler', 'validate', app])
        command(['/usr/sbin/spctl', '--assess', '--type', 'execute', app])
    return info


def validate_archive(path):
    with zipfile.ZipFile(path) as archive:
        total = 0
        names = set()
        for entry in archive.infolist():
            normalized = PurePosixPath(entry.filename).as_posix()
            require(normalized not in names, 'Archive contains duplicate members')
            names.add(normalized)
            total += entry.file_size
            require(total <= 256 << 20, 'Shell archive exceeds 256 MiB expanded')
            p = PurePosixPath(entry.filename)
            require(not p.is_absolute() and '..' not in p.parts, 'Archive path escapes its root')
            if entry.is_dir():
                continue
            # ditto may include AppleDouble resource metadata for permitted files.
            parts = list(p.parts)
            if parts and parts[0] == '__MACOSX':
                parts = parts[1:]
                require(parts and parts[-1].startswith('._'), 'Unexpected archive metadata')
                parts[-1] = parts[-1][2:]
                original = '/'.join(parts)
                require(original in archive.namelist() or original + '/' in archive.namelist(), 'Orphaned archive metadata')
                if original + '/' in archive.namelist():
                    continue
            require(parts and parts[0] == 'Kokiri.app', 'Archive contains another product')
            require(allowed_bundle_path(PurePosixPath(*parts[1:]).as_posix()), 'Archive contains game or unexpected payload')
            if stat.S_ISLNK(entry.external_attr >> 16):
                target = archive.read(entry).decode('utf-8')
                require(not PurePosixPath(target).is_absolute(), 'Archive contains absolute symlink')
                combined = list(PurePosixPath(*parts[:-1]).parts)
                for part in PurePosixPath(target).parts:
                    if part == '..':
                        require(len(combined) > 1, 'Archive symlink escapes its bundle')
                        combined.pop()
                    elif part != '.':
                        combined.append(part)
        return plistlib.loads(archive.read('Kokiri.app/Contents/Info.plist'))


def sparkle_tools():
    vendor = ROOT / 'macos/.build/vendor'
    archive = vendor / 'Sparkle-2.10.0.zip'
    require(archive.is_file() and sha(archive) == SPARKLE_SHA256, 'Prepare the checksum-pinned official Sparkle artifact first')
    with zipfile.ZipFile(archive) as source:
        for name in ('sign_update', 'generate_appcast', 'generate_keys', 'BinaryDelta'):
            path = vendor / 'bin' / name
            require(path.is_file() and hashlib.sha256(source.read('bin/' + name)).hexdigest() == sha(path), 'Sparkle tool differs from its pinned artifact')
    return vendor / 'bin'


class Signer:
    def __init__(self, tools, key_file=None, account=None):
        self.tools = tools
        if key_file:
            self.key_file = Path(key_file).resolve(strict=True)
            require(not Path(key_file).is_symlink() and self.key_file.is_file()
                    and self.key_file.stat().st_uid == os.getuid()
                    and self.key_file.stat().st_mode & 0o077 == 0, 'Private key file must be a regular owner-only file')
            require(self.key_file.stat().st_size <= 256, 'Private key file exceeds the expected seed format')
            seed = base64.b64decode(self.key_file.read_bytes().strip(), validate=True)
            require(len(seed) == 32, 'Use the current 32-byte Sparkle private-seed format')
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
                from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            except ImportError as error:
                raise ValueError('Private-seed files require the release-only Python cryptography package') from error
            self.public_key = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            self.arguments = ['--ed-key-file', self.key_file]
        else:
            require(account, 'Select an explicit signing key file or existing Keychain account')
            value = command([tools / 'generate_keys', '--account', account, '-p']).strip()
            self.public_key = base64.b64decode(value, validate=True)
            require(len(self.public_key) == 32, 'Existing Keychain public key is unavailable')
            self.arguments = ['--account', account]

    def verify(self, path, signature=None):
        return command([self.tools / 'sign_update', '--verify', *self.arguments, path, *([signature] if signature else [])])


def prepare(args):
    app, output = args.app.resolve(strict=True), args.output.resolve()
    require(not output.exists() and not output.is_relative_to(ROOT), 'Choose a fresh external output directory')
    require(output.parent.is_dir(), 'Create the external output parent directory first')
    require(args.previous_build >= 0, 'Previous build must be zero or positive')
    https(args.download_prefix, prefix=True)
    info = validate_app(app, development=args.development)
    version, build, public_key = validate_info(info, args.development)
    require(build > args.previous_build, 'Build number must increase')
    tools = sparkle_tools()
    signer = Signer(tools, args.key_file, args.keychain_account)
    require(signer.public_key == public_key, 'Signing key does not match the app-pinned public key')
    require(shutil.disk_usage(output.parent).free >= ((64 << 20) if args.development else (2 << 30)), 'Insufficient release workspace headroom')
    output.mkdir(mode=0o700)
    name = f'Kokiri-{version}-{build}.zip'
    archive, feed = output / name, output / 'appcast.xml'
    command(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive])
    validate_archive(archive)
    if args.history:
        history = args.history.resolve(strict=True)
        receipt = json.loads((history / 'release-receipt.json').read_text())
        require(not receipt['development'] or args.development, 'Development history cannot enter a production feed')
        previous = history / receipt['archive']
        require(previous.parent == history and previous.is_file() and sha(previous) == receipt['archive_sha256'], 'Previous archive integrity failed')
        previous_info = validate_archive(previous)
        validate_info(previous_info, args.development)
        require(int(previous_info['CFBundleVersion']) == args.previous_build, 'History must match the declared previous build')
        signer.verify(previous, receipt['archive_signature'])
        shutil.copyfile(previous, output / previous.name)
    # Foundation respects CFFIXED_USER_HOME. Keep the generator's extracted-app
    # cache in this invocation's private workspace, then remove only that cache.
    with tempfile.TemporaryDirectory(prefix='.sparkle-work-', dir=output) as cache_home:
        environment = {**os.environ, 'CFFIXED_USER_HOME': cache_home}
        command([tools / 'generate_appcast', *signer.arguments,
                 '--download-url-prefix', args.download_prefix, '--maximum-deltas', '1',
                 '--delta-compression', 'lzfse', '-o', feed, output], environment=environment)
    signer.verify(feed)
    xml = ET.parse(feed)
    items = [item for item in xml.findall('./channel/item') if item.findtext(SPARKLE_NS + 'version') == str(build)]
    require(len(items) == 1, 'Generated feed does not identify the new build once')
    enclosure = items[0].find('enclosure')
    require(enclosure is not None and enclosure.get('url') == args.download_prefix + urllib.parse.quote(name)
            and enclosure.get('length') == str(archive.stat().st_size), 'Generated enclosure does not match its archive')
    signature = enclosure.get(SPARKLE_NS + 'edSignature')
    require(signature and len(base64.b64decode(signature, validate=True)) == 64, 'Generated archive signature is missing')
    signer.verify(archive, signature)
    deltas = []
    for enclosure in items[0].findall(SPARKLE_NS + 'deltas/enclosure'):
        delta_name = urllib.parse.unquote(PurePosixPath(urllib.parse.urlsplit(enclosure.get('url', '')).path).name)
        delta = output / delta_name
        require(delta.parent == output and delta.is_file()
                and enclosure.get('url') == args.download_prefix + urllib.parse.quote(delta_name)
                and enclosure.get('length') == str(delta.stat().st_size), 'Generated delta does not match its enclosure')
        delta_signature = enclosure.get(SPARKLE_NS + 'edSignature')
        require(delta_signature, 'Delta signature is missing')
        signer.verify(delta, delta_signature)
        deltas.append(dict(file=delta_name, sha256=sha(delta), bytes=delta.stat().st_size,
                           signature=delta_signature, from_build=enclosure.get(SPARKLE_NS + 'deltaFrom')))
    receipt = dict(format=1, product='com.christianfurr.kokiri', product_version=version,
                   build_number=build, development=args.development,
                   source_commit=info.get('KokiriSourceCommit'), archive=name,
                   archive_sha256=sha(archive), archive_bytes=archive.stat().st_size,
                   archive_signature=signature, feed='appcast.xml', feed_sha256=sha(feed),
                   feed_url=info['SUFeedURL'], sparkle_version='2.10.0',
                   sparkle_artifact_sha256=SPARKLE_SHA256,
                   public_key=base64.b64encode(public_key).decode(),
                   deltas=deltas,
                   installation_tested=False, uploaded=False)
    (output / 'release-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--download-prefix', required=True)
    parser.add_argument('--previous-build', required=True, type=int)
    parser.add_argument('--history', type=Path)
    key = parser.add_mutually_exclusive_group(required=True)
    key.add_argument('--key-file', type=Path)
    key.add_argument('--keychain-account')
    parser.add_argument('--development', action='store_true', help='Private ad-hoc verification only; marks artifacts non-production')
    args = parser.parse_args()
    try:
        prepare(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Release preparation refused: {error}\n')


if __name__ == '__main__':
    main()
