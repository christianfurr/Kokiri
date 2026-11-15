# Signed shell releases

`prepare.py` creates a signed Sparkle archive, signed appcast, optional signed
delta and public verification receipt. It never uploads files, installs an
update, creates a production signing key or changes Keychain entries.

The payload is **Kokiri.app, the native launcher shell**. The game runtime,
owned game files, saves and shader caches remain external. A shell update does
not deliver game performance or rendering fixes.

## Python environment

From the repository root, create a dedicated environment outside the checkout:

```sh
python3.14 -m venv /absolute/private/kokiri-release-venv
source /absolute/private/kokiri-release-venv/bin/activate
python -m pip install --only-binary=:all: -r release/requirements.txt
python -m pip check
python -B -m unittest discover -s release -p 'test_runtime*.py' -v
```

Use this environment for the release commands below and the
[runtime source updater](runtime-updates.md). The pinned dependency is
`cryptography==50.0.2`; wheel-only installation avoids a local Rust/C build and
fails if the selected interpreter/platform has no compatible wheel. These
packages are tooling dependencies and are not bundled with the native app.
CI can call the environment's `bin/python` directly instead of activating it.

The original 2026-11-15 native diagnostic used CPython 3.13.3 and
`cryptography==50.0.1`. That artifact evidence retains its original identities;
the new pin has separate offline-test validation. The actual engine builder
requires Python 3.14 or later.

With the new pin, `pip check` and all 47 offline runtime/ownership tests passed
in a fresh CPython 3.14.3 environment on 2026-11-15. The native diagnostic was
not rerun for this dependency-only change.

## Private verification

From the repository root on macOS:

```sh
python3 -B release/selftest.py
```

This uses the existing `macos/build/Kokiri.app` as a read-only fixture source.
It APFS-clones two temporary app bundles, generates random ephemeral test seeds,
ad-hoc signs only those copies and runs the actual upstream tools. Nothing is
installed or uploaded. The scoped workspace has a 50 MiB limit and is removed
on completion. The pinned Python environment also supplies `cryptography` for
the release key-file path, source updater and security tests.

The latest checked result is [verification.json](verification.json). Checks
include accepting genuine archive/feed/delta signatures; rejecting modified
archives, modified feeds, wrong keys, unsafe metadata and game payloads; and
reconstructing every file and symlink with `BinaryDelta apply`. This verifies
packaging and cryptographic rejection. It does **not** verify Sparkle's live
download, relaunch or unattended installation behavior.

## Production prerequisites

Production preparation refuses ad-hoc apps. Before using it, a maintainer must:

1. Build from a clean, reviewed source commit. `CFBundleShortVersionString`
   must have three numeric components; `CFBundleVersion` must be a strictly
   increasing positive decimal integer. Record the full 40-character commit in
   `KokiriSourceCommit` and set `KokiriSourceDirty` to false. The receipt and
   current clean checkout must agree with that commit.
2. Pin a production HTTPS `SUFeedURL` and 32-byte base64 `SUPublicEDKey` into
   the app. Keep `SURequireSignedFeed` and `SUVerifyUpdateBeforeExtraction`
   true, and `SUSignedFeedFailureExpirationInterval` zero. The build accepts
   public configuration through `KOKIRI_UPDATE_FEED` and
   `KOKIRI_UPDATE_PUBLIC_KEY`; it never embeds the private seed.
3. Establish an owner-controlled production Ed25519 key using
   [Sparkle's signing guidance](https://sparkle-project.org/documentation/).
   Keep the private key in the maintainer's Keychain or a regular owner-only
   seed file outside the checkout. Do not generate a production key for a
   preview, commit one or paste one into a command argument. The script accepts
   the current base64 32-byte seed format; it does not migrate legacy keys.
4. Sign all nested code and the final app with Developer ID Application and
   hardened runtime, notarize it and staple its ticket. The release script
   requires strict deep signature verification, the Developer ID authority,
   hardened runtime, successful stapler validation and Gatekeeper assessment.
   Developer ID Application credentials and a notarized Kokiri distribution
   are currently missing. This repository's ad-hoc preview is not releasable.
5. Configure the final HTTPS artifact host and feed URL, and complete a real
   update/relaunch test on disposable app copies before enabling publication.
   The tooling below prepares files locally. It contains no publishing command.

The shell build's version inputs are `KOKIRI_VERSION` and
`KOKIRI_BUILD_NUMBER`; it records source commit/dirty metadata itself. For example,
from `macos/`, set `KOKIRI_VERSION=0.1.1 KOKIRI_BUILD_NUMBER=2` alongside the
two public update variables when invoking `bash build.sh`. This still produces
an ad-hoc preview until a distribution-signing path is configured.

The official Sparkle 2.10.0 ZIP must already be available through
`macos/scripts/prepare_sparkle.py`. Its pinned SHA-256 is
`17e28312b8e18ab7cdbbe09a6fb28cc55a5479ec6c371dbc07cdecd2a14fd959`.
Before invocation, each signing/generation/delta tool is checked against that
artifact. The framework's file membership is checked against the same archive.
Only the shell executable, known Kokiri resources, signature metadata and those
framework files are permitted. These checks supplement code signing; they do
not prove the absence of copyrighted bytes hidden inside an otherwise allowed
file. Review the clean source and final bundle contents too.

## Prepare reviewable artifacts

Once the prerequisites are satisfied, use an external fresh output directory:

```sh
python3 -B release/prepare.py \
  --app /absolute/path/Kokiri.app \
  --output /absolute/path/releases/0.1.1-2 \
  --previous-build 1 \
  --download-prefix https://updates.example.org/kokiri/downloads/ \
  --keychain-account Kokiri-Release
```

`--keychain-account` looks up an **existing** account. Alternatively supply
`--key-file /absolute/private/location/seed`; no key value goes in the command.
At least 2 GiB free is required for production preparation. `--development`
exists for private test copies only and permanently marks the resulting receipt
as non-production. It does not relax HTTPS, pinned-key or signature checks.

For a later release, add `--history /absolute/path/previous-output`. The previous
receipt, archive hash, pinned public key, build number and actual signature are
checked. A development archive cannot enter a production feed. The history
build must equal `--previous-build`. One delta at most is generated with LZFSE
compression. Every generated delta is verified and recorded with its hash,
size and signature. Older clients can still use the full archive.

Review `release-receipt.json`, `appcast.xml`, the named ZIP and any named delta.
The receipt intentionally says `uploaded: false` and
`installation_tested: false`. After independently testing delivery, a maintainer
can upload the listed public artifacts through their configured host. Upload
archives and deltas first, then atomically replace the signed appcast. Never
modify the XML after signing. Keep signing seeds and private game workspaces
out of the upload tree. See
[Sparkle publishing](https://sparkle-project.org/documentation/publishing/) and
[delta updates](https://sparkle-project.org/documentation/delta-updates/).

## Update speed and runtime updates

Sparkle's supported minimum scheduled check interval is one hour; its default
is 24 hours. `SUScheduledCheckInterval=3600` is the intended shell default.
An explicit Check for Updates can discover a published update sooner. Downloads
can happen in the background when the user's settings permit it; installation
or relaunch can still wait for the app to quit or require user interaction.
These are upstream capabilities, not evidence of a tested Kokiri installation.
See [Sparkle customization](https://sparkle-project.org/documentation/customization/).

The existing source builder has a separate local runtime rebuild route:

```sh
python3 -I engine/build.py \
  --rebuild '/absolute/path/Kokiri Game.app' \
  --work /absolute/path/existing-game-workspace
```

This rebuilds from the checked-out engine source and reuses compatible local
game data, rewritten modules and shader outputs. It waits for the game to close
and refuses incompatible workspaces. A translator or shader-chain change may
require a full build, so this is not a guaranteed quick update. It was inspected
as source here, not executed by the release tests.

The separate [runtime source updater](runtime-updates.md) now implements signed
source delivery, revision and payload verification, private staged builds from
the owner's local data, preparation-receipt checks and atomic version selection
with rollback. Its native UI and production source feed remain unconfigured.
Fixture tests establish only the documented local behavior; full v28 game
update/relaunch, compatible shader preparation and production distribution
still need Integration acceptance. Never publish generated game code, binaries
or shaders through either update route.
