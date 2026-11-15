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
the [dedicated release environment](README.md#python-environment), with Python
3.14 and the pinned `release/requirements.txt` dependencies. The public key comes
from an owner configuration, never from the downloaded manifest. A store enrolls that key and
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
For a new candidate, the receipt's `seed_runtime_sha256` and the actual sealed
seed manifest's `runtime_sha256` must both match the pre-seal build runtime.
An older request proof is refused even when its translator namespace is still
compatible. Reusing cached translations requires real request revalidation by
the current runtime; changing identity labels cannot establish that evidence.

Promotion also requires `compiler_context_schema: 2` in both the receipt and
library manifest, an identical qualified `observation_schema: 2` Metal
observation, and the matching computed context digest. The verifier imports
`compiler_context_key` only from its trusted checkout's
`engine/scripts/metal_toolchain.py`. Missing trusted tooling stops staging before
building. It never imports a validator from downloaded source or queries the
host compiler to reinterpret a historical observation. The shared validator
binds the selected driver, frontend, linker, resource headers, static inputs,
declared dependencies, effective invocations and host identity. Older
launcher-only pilot observations cannot qualify a new prepared version.
Qualified observations must also attest the `reject-nonempty-DYLD` loader
environment policy; older policyless schema-2 proofs are rejected.
The supported driver policy is exactly the macOS 26.0 deployment, safe math,
preserve-invariance and wrapv options. Extra or duplicate driver flags and
recorded frontend options that disable those correctness guarantees are refused.
The qualified observation also binds the actual absolute canonical compiler
working directory; relocating the build workspace cannot silently change it.
Previously retained, unchanged snapshots can still be selected for explicit
recovery; that does not promote their old preparation evidence.

New promotion also validates the actual sealed `compute-manifest.json` through
the trusted engine's `archive_verification_errors` function. It requires fresh
read-only native verification, zero translated-library JIT attempts, zero
archive misses/writes, every requested row verified, at least one archive opened,
successful native exit and unchanged before/after archive snapshots. The native
report must identify the actual current library manifest, qualified compiler
context and raw runtime. The receipt's 14-field archive projection and five
artifact paths must match the sealed files exactly. `successful_render`,
`successful_compute` and `successful_mesh` include archive hits; they are not
counts of newly compiled pipelines. The JIT counter excludes embedded support
shaders and OS/driver code generation.

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

For a game rehearsal, use the Integration-approved isolated development launcher
for the exact selected app and retained baseline. The generic `relaunch` command
uses ordinary player-data defaults; it does not create a disposable profile,
cache or explicit PSO set. Close the rehearsal session normally under its actual
ownership rules before changing version selection.

## Explicit learned inputs

The updater accepts the producer's existing `--shader-list FILE` and repeatable
`--learned-cache DIR` inputs. A selected cache requires an explicit merged list;
the updater does not discover legacy caches or merge/rename metadata itself.
Integration must authorize creation of independent owned snapshots before
staging. Place the list, separate explicit/profile PSO files, complete cache and
any merge-recovery provenance together below `WORK/preparation-inputs/RUN`:

```text
WORK/preparation-inputs/RUN/shader-list.tsv
WORK/preparation-inputs/RUN/pso-user.tsv
WORK/preparation-inputs/RUN/profile-pso-user.tsv
WORK/preparation-inputs/RUN/observed-cache/
```

Pass the list and cache paths alongside `stage`'s other arguments. The client
inventories that entire selected run, including separate PSOs, unrecognized
cache files and empty directories, then verifies the independent work clone
has identical contents and different file identities. Only cloned input paths
reach the builder. Symbolic links, hardlinks, changed inputs and wrong shader
chains are refused. Private `input-provenance.json` records file hashes, byte
counts, source paths and metadata/stat identities; the original and cloned
inputs must remain unchanged through activation. Retain these active snapshots
until the rehearsal completes; the client never deletes them.

Metadata row totals are not compiled work or proof of semantic inclusion. The
producer must independently validate the merged normalized row set. Unsupported
raw records remain in the complete cache and separate PSOs even when they are
not prewarm requests. Cache identities without translator/compiler fields stay
intact; the updater never invents those identities. The producer validates and
imports only compatible patched MSL/metadata, rather than adopting cached base
binaries. Current-runtime request proof and qualified library/archive evidence
remain mandatory.

Staging always rebuilds a new runtime and signs a new app. With an incomplete
workspace, first establish the producer's qualified baseline through its
explicit full-build recipe; `--rebuild` keeps its compatibility refusal. The
subsequent update's own staged output is the candidate to test. Its prior
baseline supplies rollback; an earlier producer candidate's fingerprint cannot
be substituted for the new output. Freeze the final native source before request
proof, then record the separately sealed final-byte identity.

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

Run `python -B -m unittest discover -s release -p 'test_runtime*.py' -v`
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
That historical run predates the compiler-context schema-2 promotion gate.
The current diagnostic fixture supplies explicitly synthetic schema-2 data for
future transaction tests; it has not been rerun natively under the new gate and
does not establish real compiler qualification or shader preparation.
