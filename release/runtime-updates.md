# Private runtime updates from signed source

The game runtime is separate from the Kokiri launcher. Sparkle updates the
launcher bundle. `runtime_update.py` stages a new game runtime from a signed
source release and the owner's existing local game workspace. No game dump,
rewritten module, compiled shader, cache, font, save or log is published.

This is a maintainer CLI, not an enabled automatic-update UI. The native app
still reports runtime updates as unconfigured. There is no production source
feed, enrolled production signing key, Developer ID distribution or notarization
acceptance. Local fixture tests do not establish actual game update/relaunch.
Full v28 preparation and integration acceptance remain prerequisites.

## Trust and build contract

Keep this client in a trusted checkout, outside the downloaded source. Use
Python 3.14 with `cryptography` installed. The public key comes from an owner
configuration, never from the downloaded manifest. A store enrolls that key and
rejects a different key; key rotation requires a separately reviewed migration.
The exact manifest bytes have a detached base64 Ed25519 signature. Required
fields are:

| Field | Meaning |
| --- | --- |
| `schema` | `kokiri-runtime-source-v1` |
| `product` | `com.christianfurr.kokiri.runtime` |
| `version` | Increasing positive integer release sequence |
| `source_commit` | Exact 40-character source commit |
| `game_update` | `131072` |
| `build_api` | `1`: staged rebuild interface |
| `shader_chain` | Exact source translation chain |
| `archive_url` | HTTPS source ZIP, no credentials/query/fragment |
| `archive_sha256`, `archive_bytes` | Exact source archive identity and bound |
| `public_resource_sha256` | Exact reviewed metadata/artwork bytes at recognized source paths |

Signature verification precedes use of URLs or source extraction. HTTPS delivery
rejects redirects and bounds each response. Archive inspection rejects links,
submodules, duplicate/case-colliding paths, traversal, `.git`, oversized members
and files forbidden by the trusted publication policy. The signed archive is
source only, not a remotely supplied build command or binary payload.
Changed metadata and artwork must first pass the maintainer's current source
publication pins. Their new hashes are signed in the source manifest, allowing
an older client to accept reviewed changes at already recognized paths (such as
an expanded shader metadata list). A signature cannot introduce a new arbitrary
binary path or bypass the private-file boundary.

The trusted client writes `kokiri-source-release.json` in extracted source so
the builder can record the authenticated source commit without a fabricated Git
HEAD. The staged builder API is owned by the shader-build specialist:

```text
python3.14 -I SOURCE/engine/build.py --rebuild ORIGINAL.app \
  --out VERSION/Kokiri\ Game.app --work VERSION/work --jobs 2
```

Each version gets an APFS clone of the local build workspace. Non-venv links
are rejected so build writes cannot follow them into the original workspace.
The app, workspace and private build log stay in that version's directory.
Existing compatible cache/PSO files remain in the original workspace; nothing
is relabeled between translation chains. The builder validates compatibility.
A changed chain or translator can require a fresh full build; staged rebuilds
refuse an incompatible workspace. Compatible rebuilds still prepare their
requested variants and archives. A candidate's external game-data
library, if any, must resolve inside its own versioned workspace.

The builder must provide
`Contents/Resources/totk/build/game-data/oot/preparation-receipt.json`, schema
`kokiri-preparation-receipt-v1`, plus `KokiriPrepared` and
`KokiriPreparationReceiptSHA256` bundle metadata. Activation requires strict
deep code-signature verification, exact runtime/source/chain/context/translator
identities, full mode and complete requested default/listed variants, compiled
libraries and pipelines with no failures. The source list's 50,376 metadata
rows are never interpreted as compiled shader totals. A complete receipt covers
its requested corpus, not every possible future gameplay variant.

`receipt.identity.runtime_sha256` and `artifact_sha256.runtime_sha256` identify
the pre-seal build executable used for pipeline preparation, as explicitly
stated by `runtime_hash_scope`. `KokiriBuildRuntimeSHA256` must match that input.
Signing changes executable bytes; the raw final signed executable hash cannot
be embedded inside its own signed resource receipt without a circular hash.
The trusted signed-source builder verifies the copied input before signing and
writes `work/logs/package-output.json` afterward. The updater independently
matches its actual final executable, plist, signed resources and receipt hashes
to that output, then freezes those final hashes in the private transaction.
Activation and rollback recompute the final byte hashes. This trust model relies
on the reviewed source builder and local compiler/signing tools; it does not
independently reproduce the compiler output from a remote prebuilt binary.

## Prepare source delivery

Only Integration authorizes a release. After its review, a maintainer can create
local artifacts from a clean integrated commit that implements the staged
builder contract:

```sh
python3 -B release/prepare_runtime_source.py \
  --repository /absolute/clean/Kokiri \
  --version 1 \
  --archive-url https://OWNER-HOST/kokiri/runtime-source-1.zip \
  --key-file /absolute/private/owner-only-seed \
  --output /absolute/private/source-release-1
```

The seed is the base64 32-byte Ed25519 format in a regular owner-only file
outside source. Never pass a private seed value on a command line. The packager
scans actual committed blobs, preserves licenses/notices, creates a deterministic
source ZIP and detached manifest signature, and verifies that signature locally.
It uploads nothing. After separate publication authorization, host the source
ZIP at the exact signed URL, then the manifest and `.sig`. This is distinct from
Sparkle's signed appcast format; do not edit signed bytes after signing.

## Stage, select and recover

The owner-only store must be external to the source and original build
workspace, on APFS with at least 6 GiB free plus build-specific headroom. Heavy
work requires the Integration slot during development. The client refuses to
start while a game runs and stops its own build group if gameplay appears; it
never terminates gameplay or sends game input. There remains a brief process
start race, so native launch and updater scheduling also need a shared-slot
integration before automatic use.

```sh
python3 -B release/runtime_update.py --store /absolute/private/RuntimeVersions \
  stage --feed https://OWNER-HOST/kokiri/manifest.json \
  --public-key BASE64_PUBLIC_KEY \
  --current-app '/absolute/current/Kokiri Game.app' \
  --work /absolute/current/Kokiri-work \
  --python /absolute/path/to/python3.14
```

Offline delivery uses `--manifest FILE --signature FILE --archive FILE` instead
of `--feed`; it applies identical signature/content checks. The store's prepared
candidate is selected only by the separate command:

```sh
python3 -B release/runtime_update.py --store /absolute/private/RuntimeVersions \
  activate --version 1 --public-key BASE64_PUBLIC_KEY
python3 -B release/runtime_update.py --store /absolute/private/RuntimeVersions status
python3 -B release/runtime_update.py --store /absolute/private/RuntimeVersions relaunch
python3 -B release/runtime_update.py --store /absolute/private/RuntimeVersions rollback
```

All commands return one JSON object. Failure exits nonzero with
`status: refused`; private compiler logs stay in the version folder. A staged
result has `status: staged`, `candidate`, `activated: false` and
`game_launched: false`. Selection has `status: activated`, `active` and
`previous`. `status` exposes the selection and highest accepted release number.
The native app must launch `active.app` after verifying it, not a remembered
installation path. `relaunch` reports only `launch_requested` and explicitly
leaves successful launch unverified until an observer confirms the process.

Activation revalidates the candidate and retained baseline before atomically
replacing `state.json` (temporary file, fsync, rename, directory fsync). A crash
before selection leaves the previous selection; a crash afterward leaves the
new one. A failed/interrupted build remains in its version folder for inspection
and cannot activate. No installed app is replaced. `rollback` atomically selects
the retained prior app after verifying its executable, plist and signed resource
envelope. The highest accepted sequence stays unchanged, preventing a signed
old manifest replay after rollback. Rollback does not copy or restore profiles,
saves or learned caches. Those remain separate and must never be overwritten
as part of runtime recovery.

Prepared versions and original workspaces are deliberately retained. Inspect
failed staging directories before manually archiving them; the client has no
automatic deletion or cache-pruning operation.

## Evidence limits

Run `python3 -B -m unittest discover -s release -p 'test_runtime_update.py' -v`
for source/signature/path/transaction fixtures. A mocked code-signature check is
not signing acceptance. The release fixture harness, when separately granted,
uses synthetic counters and a tiny diagnostic executable; it cannot establish
full v28 game preparation, visual correctness, game relaunch or production
Sparkle installation. Keep those acceptance results and exact candidate hashes
in Integration's private evidence, separate from local source tests.

On 2026-11-15 the serialized diagnostic run passed: signed source packaging,
strict code-signature validation, staging, actual diagnostic relaunch, rollback
and baseline relaunch, with original app/workspace preservation. Both observed
processes exited after PID/UID/path/kernel-birth verification. The real retained
manifest rejected changed bytes and a wrong signing key; the retained source ZIP
rejected modification before extraction. Signing produced distinct pre-seal and
final executable hashes, as required by the builder contract. The sanitized
[verification record](runtime-verification.json) pins those artifact identities.
Its preparation counters are synthetic; it proves the update transaction and
diagnostic launches, not actual game or production distribution acceptance.
