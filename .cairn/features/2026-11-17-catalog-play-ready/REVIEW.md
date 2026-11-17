# Offline catalog review

Verified 2026-11-17. Server unavailable; no deployment, ingestion activation, game/GPU run, installation or player/cache mutation.

## Implemented

- Recover exact/reference cache indexes with shared signature/context/pack verification, accepted revision floor and safe local paths. Restore before background refresh; retain a verified fallback during an outage.
- Verify signed reference or exact metadata and merge usable recipes with existing baseline dependencies into fresh local builder input. Require the current builder game version and shader chain; keep reference data outside runtime admission.
- Curate selected IDs from a hash-verified closed snapshot, preserve previously signed records and attribution, sign offline and import guarded revisions atomically. Retain quarantine rows.
- Reject unsupported raw HTTP routes before reading bodies, including encoded and dot-segment contribution aliases. Preserve default-off ingress and origin resource bounds.

## Findings resolved

Independent review confirmed and the implementation corrected:

1. Local export admitted signed metadata from another game update/chain. The exporter now reads the current builder version/header and refuses those contexts.
2. Publication import lacked SQLite page/free-space limits. It now caps pages at 1 GiB and requires 512 MiB plus twice SQL size of free space.
3. Import verification checked only referenced packs. It now validates unreferenced packs and quarantine quota accounting too.
4. Import verification could materialize an oversized existing value before rejecting it. SQL preflight checks stored types and byte lengths before fetching pack/manifest values.

SQL review found no contribution-to-code execution path. Rows stay validated data, operator SQL escapes values, import denies attachment/extensions and writes outside publication tables, and stale-envelope guards run inside one immediate transaction. Schema validity and signatures do not prove provenance, reproducibility or harmless resource use; operators still review before signing.

The deletion pass retained only the accepted offline work and reused shared signature/pack checks and the existing recipe parser. No dependencies or product flags were added. The existing LocalFile helper moved without duplication; duplicate facade reset/refresh code was removed. Final scope is 18 source/document/ledger paths, including this review.

## Verification output

Existing commands, with Node 24.22.3 from an official SHA-256-verified temporary runtime:

```text
bash macos/test.sh
Executed 62 tests, with 0 failures (0 unexpected)

bash macos/build.sh
Build complete! (17.46 sec)
Kokiri.app produced; codesign --verify --deep --strict passed

npm run typecheck
tsc --noEmit

npm run build
✓ built in 11ms
◆  Build complete

npm test
tests 10
pass 10
fail 0

npm run test:python
Ran 22 tests in 9.550s
OK
PASS native CatalogClient 32 checks; intercepted HTTPS only; no production requests

node --test --test-concurrency=1 tests/selfhost/server.test.mjs
tests 10
pass 10
fail 0

node selfhost/build.mjs /FRESH/EXTERNAL/STAGE
KOKIRI_TEST_STAGE=/FRESH/EXTERNAL/STAGE node --test --test-concurrency=1 tests/selfhost/lifecycle.test.mjs
tests 2
pass 2
fail 0

python3 -m unittest discover -s engine/tests -p test_shader_list_admission.py
Ran 3 tests in 0.014s
OK
```

No lint command is configured for this subsystem. Changed Python modules passed py_compile; Node server passed node --check; git diff --check passed. Native tests/build logs contained no compiler warnings. The first HTTP attempt refused macOS /var path aliases as designed; a canonical private temporary root passed. Initial Worker build used unsupported system Node; the supported pinned runtime passed. Neither required weakening production checks.

Disposable probes (not committed tests):

```text
PASS offline native cache: 21 checks; exact/reference restart, corruption, context, mode, traversal, rollback, symlink, queue unchanged and no network
PASS current-builder signed reference export, baseline preservation, parsed output/attribution, signed wrong-version and old-chain rejection
PASS ingress security: 5 early raw-path rejections, 3 malicious payload rejections, compressed upload rejection; quarantine unchanged
PASS: deterministic review; signed revision merge; transactional first publish; quota counters; stale rollback; retained quarantine; removal, unknown-key, malformed-row, bad-ID, bad-digest, ATTACH, extension and invalid-signature refusal
```

Native cache probe initially compared /var and /private/var spellings. Filesystem-realpath comparison confirmed identical files and both cache modes passed.

## Remaining acceptance and waivers

The preparation merge is an operator CLI feeding the existing --shader-list builder option; it is not yet automatic first-run app preparation. It requires the Python SDK's existing cryptography dependency. No full local shader compilation or measured startup/stutter improvement was attempted.

Ready-made compiled downloads still require a separately signed artifact format, exact compiler/device/options qualification and Metal/runtime adoption validation. Current public recipes remain reference-only. Do not remove runtime compatibility guards to consume them.

Homeserver activation, edge/Access route protection, public contribution ingestion, actual native uploads, backup/restore rehearsal and live catalog update verification wait for the host. Origin limits cannot guarantee internet-scale DDoS resistance. Keep contribution ingress off until those checks pass. Long-term quarantine retention/cleanup remains an operator task. Production signing keys remain offline and were not created in this run.
