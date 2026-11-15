"""Fetch the official Sparkle 2.10.0 SPM artifact, pinned to its upstream checksum."""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / '.build/vendor'
SHA256 = '17e28312b8e18ab7cdbbe09a6fb28cc55a5479ec6c371dbc07cdecd2a14fd959'
URL = 'https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-for-Swift-Package-Manager.zip'


def main():
    VENDOR.mkdir(parents=True, exist_ok=True)
    archive = VENDOR / 'Sparkle-2.10.0.zip'
    if not archive.exists():
        temporary = archive.with_suffix('.download')
        try:
            subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                            '--max-time', '120', URL, '-o', str(temporary)], check=True)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
                raise SystemExit('Sparkle artifact checksum mismatch; nothing extracted')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Sparkle artifact checksum mismatch; nothing extracted')
    if not (VENDOR / 'Sparkle.xcframework/Info.plist').is_file():
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(VENDOR)], check=True)
    print('Sparkle 2.10.0: upstream artifact checksum verified')


if __name__ == '__main__':
    main()
