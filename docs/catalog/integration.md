# Recompiler integration

1. Compute context locally from reproducible adapter/toolchain manifests; never
   label an unknown compiler/target fingerprint exact.
2. Parse runtime records through the strict adapter, then form record IDs and
   validated envelopes. Never point the client at a raw cache directory.
3. Ask once for public metadata contribution. Remember enabled/disabled, show
   pending count, and expose off at any time. Keep the game independent of network.
4. A single background owner flushes bounded batches. Retry offline; recheck
   consent between requests. Do not compile the entire corpus in RAM.
5. Ship the operator's independently verified production public key with the app.
   Fetch the exact context manifest, verify its signature and every pack, then
   pass supported recipes to the runtime's existing bounded preparation path.
   The service does not implement that runtime handoff for other recompilers.

TypeScript API: `src/protocol.ts` exports validators/hash/verification;
`sdk/typescript/client.ts` exports `CatalogQueue`, `QueueStore`, and an explicit
HTTPS transport. Queue storage must be atomic and owned by one application actor.

Python reference CLI (`cryptography` is required for Ed25519 verification):

```sh
python3 sdk/python/kokiri_catalog.py validate --envelope envelope.json
python3 sdk/python/kokiri_catalog.py --queue queue.sqlite status
python3 sdk/python/kokiri_catalog.py --queue queue.sqlite consent enabled
python3 sdk/python/kokiri_catalog.py --queue queue.sqlite enqueue --envelope envelope.json
python3 sdk/python/kokiri_catalog.py --queue queue.sqlite flush --endpoint https://YOUR-APPROVED-ORIGIN
python3 sdk/python/kokiri_catalog.py --queue queue.sqlite consent disabled
python3 sdk/python/kokiri_catalog.py verify --manifest manifest.json --context context.json --keys pinned-keys.json
```

Commands emit bounded JSON status and generic error tokens. Validate/verify do
not create a queue or send requests. `--reference-only` permits signature checking
of reference metadata for inspection; it must never be used for runtime warm-up.
The CLI is a reference integration tool, not a requirement that a Mac user install
Python. Native clients can use URLSession/CryptoKit with the same schema/fixtures.

`tests/fixtures/` contains synthetic contribution/context/pack/signed-manifest
examples. Test keys are regenerated locally by the runtime tests and are not
production credentials. `seed/reference/` is separate, attributed public metadata.

Native implementation: `CatalogClient` is a Foundation/CryptoKit actor with
durable bounded queue, signature/context/pack verification, and a metadata-only
`runtime-ready/<context_id>.json` index outside the bundle. It never replaces
the game's shader cache. The client verifies one <=256 KiB pack at a time and
stores immutable `packs/<sha256>.json` files in its own 0700 cache. It supports
up to 100000 records, 1024 packs and 64 MiB total download-cache disk usage,
including prior packs, published indexes and staged bytes (contribution queue
has its separate16 MiB bound). It retains bounded identity/index bookkeeping, not aggregate
pack objects. A new index is published atomically only after all referenced packs
verify. Failed downloads/publications remove their own staging/new unreferenced
packs; existing verified files and prior indexes remain. Under the explicit
single-directory-owner contract, a refresh also removes only its UUID-named
interrupted staging directories before reserving new space. It remembers highest
accepted revisions before publication, so a disk failure cannot lower that floor.

`ingestRuntimeMetadata(from:context:)` handles an explicitly supplied owned
session delta, not an arbitrary cache scan. It checks consent before opening the
file, accepts at most 16 MiB/100000 lines, validates supported records, normalizes
the runtime's omitted optional provenance flag to an empty column, and reports
unsupported/malformed/deferred counts. A bounded acknowledgment ledger avoids
requeuing accepted IDs. The app must snapshot/verify the prelaunch file prefix
and bundled context before attributing appended rows to a session. Importing a
whole legacy profile must not relabel old v23 recipes as new v28 output.

Current boundary: service/reference/native clients are locally implemented.
A production trust key, public hosting and verified runtime adoption of the
downloaded metadata artifact remain separate integration gates. No live catalog
availability or performance gain is claimed.
