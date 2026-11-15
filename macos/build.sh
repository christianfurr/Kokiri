#!/bin/bash
set -euo pipefail
KOKIRI_MACOS="$(cd "$(dirname "$0")" && pwd)"
cd "$KOKIRI_MACOS"
KOKIRI_FINAL_APP="$KOKIRI_MACOS/build/Kokiri.app"
python3 -I - "$KOKIRI_FINAL_APP/Contents/MacOS/Kokiri" <<'PY'
import subprocess,sys
names=subprocess.check_output(['/bin/ps','-axo','comm='],text=True).splitlines()
if sys.argv[1] in (line.strip() for line in names):raise SystemExit('Quit the Kokiri preview before replacing its app bundle')
PY
python3 -I scripts/prepare_sparkle.py
swift build -c release --jobs "${KOKIRI_BUILD_JOBS:-2}"
KOKIRI_BIN="$(swift build -c release --show-bin-path)"
mkdir -p "$KOKIRI_MACOS/build"
KOKIRI_STAGING="$(mktemp -d "$KOKIRI_MACOS/build/.kokiri-app.XXXXXX")"
KOKIRI_APP="$KOKIRI_STAGING/Kokiri.app"
trap 'if [[ -d "$KOKIRI_STAGING/Previous.app" && ! -e "$KOKIRI_FINAL_APP" ]]; then mv "$KOKIRI_STAGING/Previous.app" "$KOKIRI_FINAL_APP"; fi; rm -rf "$KOKIRI_STAGING"' EXIT
mkdir -p "$KOKIRI_APP/Contents/MacOS" "$KOKIRI_APP/Contents/Frameworks" "$KOKIRI_APP/Contents/Resources"
cp "$KOKIRI_BIN/Kokiri" "$KOKIRI_APP/Contents/MacOS/Kokiri"
KOKIRI_SPARKLE="$(python3 -I - <<'PY'
from pathlib import Path
matches=list(Path('.build/vendor/Sparkle.xcframework').glob('macos-*/Sparkle.framework'))
if len(matches)!=1:raise SystemExit('Expected exactly one pinned macOS Sparkle framework')
print(matches[0].resolve())
PY
)"
ditto "$KOKIRI_SPARKLE" "$KOKIRI_APP/Contents/Frameworks/Sparkle.framework"
cp ../LICENSE "$KOKIRI_APP/Contents/Resources/LICENSE"
if [[ -f ../THIRD_PARTY_NOTICES.md ]]; then cp ../THIRD_PARTY_NOTICES.md "$KOKIRI_APP/Contents/Resources/THIRD_PARTY_NOTICES.md"; fi
cp .build/vendor/LICENSE "$KOKIRI_APP/Contents/Resources/Sparkle-LICENSE"
cp ../assets/brand/kokiri-mark.png "$KOKIRI_APP/Contents/Resources/KokiriMark.png"
bash scripts/create_icon.sh ../assets/brand/kokiri-mark.png "$KOKIRI_APP/Contents/Resources/Kokiri.icns"
python3 -I - "$KOKIRI_APP" <<'PY'
import base64, json, os, plistlib, re, subprocess, sys
from pathlib import Path
from urllib.parse import urlsplit
app=Path(sys.argv[1]);feed=os.environ.get('KOKIRI_UPDATE_FEED');key=os.environ.get('KOKIRI_UPDATE_PUBLIC_KEY')
version=os.environ.get('KOKIRI_VERSION','0.1.0');build=os.environ.get('KOKIRI_BUILD_NUMBER','1')
if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[a-zA-Z0-9.-]+)?',version):
    raise SystemExit('KOKIRI_VERSION must be a semantic version')
if not re.fullmatch(r'[1-9][0-9]{0,11}',build):raise SystemExit('KOKIRI_BUILD_NUMBER must be a positive numeric build number')
repo=Path.cwd().parent
commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
dirty=bool(subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True))
if bool(feed)!=bool(key):raise SystemExit('Supply both KOKIRI_UPDATE_FEED and KOKIRI_UPDATE_PUBLIC_KEY, or neither')
info={'CFBundleIdentifier':'com.christianfurr.kokiri','CFBundleName':'Kokiri','CFBundleDisplayName':'KOKIRI',
      'CFBundleExecutable':'Kokiri','CFBundlePackageType':'APPL','CFBundleShortVersionString':version,
      'CFBundleVersion':build,'KokiriSourceCommit':commit,'KokiriSourceDirty':dirty,
      'CFBundleIconFile':'Kokiri.icns','LSMinimumSystemVersion':'26.0','NSHighResolutionCapable':True,
      'NSPrincipalClass':'NSApplication','SUVerifyUpdateBeforeExtraction':True,'SURequireSignedFeed':True,
      'SUSignedFeedFailureExpirationInterval':0,'SUShowReleaseNotes':False,'SUEnableSystemProfiling':False,
      'SUEnableAutomaticChecks':True,'SUAutomaticallyUpdate':True,'SUScheduledCheckInterval':3600}
if feed:
    parsed=urlsplit(feed)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise SystemExit('The signed update feed must be an HTTPS URL without credentials or fragment')
    if len(base64.b64decode(key,validate=True))!=32:raise SystemExit('Expected a 32-byte Ed25519 public key')
    info.update(SUFeedURL=feed,SUPublicEDKey=key)
origin=os.environ.get('KOKIRI_CATALOG_ORIGIN');encoded=os.environ.get('KOKIRI_CATALOG_KEYS_JSON')
if bool(origin)!=bool(encoded):raise SystemExit('Supply both catalog origin and public keys, or neither')
if origin:
    parsed=urlsplit(origin);keys=json.loads(encoded)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise SystemExit('Catalog origin must be an HTTPS origin')
    if not isinstance(keys,dict) or not keys or any(not isinstance(v,str) or len(base64.b64decode(v,validate=True))!=32 for v in keys.values()):
        raise SystemExit('Catalog public keys must be a nonempty key-id map of 32-byte base64 keys')
    info.update(KokiriCatalogOrigin=origin,KokiriCatalogPublicKeys=keys)
with (app/'Contents/Info.plist').open('wb') as stream:plistlib.dump(info,stream)
PY
install_name_tool -add_rpath @executable_path/../Frameworks "$KOKIRI_APP/Contents/MacOS/Kokiri" 2>/dev/null || true
codesign --force --sign - --timestamp=none "$KOKIRI_APP"
codesign --verify --deep --strict "$KOKIRI_APP"
python3 -I - "$KOKIRI_APP" "$KOKIRI_FINAL_APP" <<'PY'
from pathlib import Path
import sys
staged,final=map(Path,sys.argv[1:]);previous=staged.parent/'Previous.app'
if final.exists():final.rename(previous)
try:staged.rename(final)
except BaseException:
    if previous.exists():previous.rename(final)
    raise
PY
printf '%s\n' "$KOKIRI_FINAL_APP"
