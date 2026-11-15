# Local verification — 2026-11-15

No deployment, remote resource creation, production signing key, real metadata
upload or GPU/game execution was performed by the catalog implementation.

| Check | Actual result |
| --- | --- |
| Official `cf build` → Vite/Workers output | PASS; ~9.5 KiB Worker bundle |
| TypeScript strict typecheck | PASS |
| Node test suite | 10/10 PASS; actual workerd/D1 plus client checks |
| Python discovery | 11/11 PASS, including compiled native actor fixture |
| Native Foundation/CryptoKit actor fixture | 32 checks PASS, including full50376-record streaming corpus gate; all HTTPS intercepted locally |
| Public MIT sample import | 56 records / one unsigned reference pack; all 50376 supported source rows validated before output |
| Wrangler dependency | Absent (`npm ls wrangler` empty) |

Worker/D1 checks cover concurrent duplicate requests, quarantine isolation,
malformed/private/bounded inputs, curated signature/context/pack verification,
and transactionally maintained small-cap quota counters. Concurrent overflow
accepts one new key and rejects the other; duplicate-at-capacity succeeds without
counter changes; failed batches roll back records and newly created contexts;
deletes release capacity. The optional rate-limit denial path bypasses body/DB
work without a per-person identifier.

Reference clients test offline persistence/backoff, concurrent SQLite enqueue,
exact acknowledgments, opt-out between chunks, and persistence failure. Native
tests additionally cover user-recorder ingestion with omitted flags, unsupported
locator/border rows, acknowledged-record deduplication, reference-only warm-up
rejection, real Ed25519 checks, and a signed older revision rejected after an
artifact publication failure/restart. The full-corpus gate uses 50376 unique
synthetic records across394 bounded packs; the actor publishes a small index,
keeps pack files under64 MiB, and reuses verified immutable files on refresh.
Failed publication must leave neither staging nor newly promoted orphan packs.
Actual corpus result:9216894 pack bytes,126893-byte index,394pack GETs on first
refresh and zero additional pack GETs on the second. UUID-named interrupted
staging is cleaned on refresh under the explicit single-directory-owner contract.
The64 MiB bound includes existing packs, published indexes, staged bytes and a
1 MiB atomic-index reserve. Files live only in disposable test folders.

Offline publication tests use temporary synthetic signing keys, validate the
public reference seed, refuse overwrite/republication, and reject tampered packs
before creating output. Synthetic cross-language fixture keys are test-only;
their private keys are not stored. Tests do not rewrite checked-in fixtures.

Commands run from `services/catalog`:

```sh
node_modules/.bin/tsc --noEmit
/opt/homebrew/opt/node@22/bin/node --experimental-strip-types --test --test-concurrency=1 tests/catalog.test.ts
python3 -m unittest discover -s tests -p 'test_*.py'
PATH=/opt/homebrew/opt/node@22/bin:$PATH node_modules/.bin/cf build
```

This host has Node22.22, below cf's declared22.23 minimum. Local build/tests
passed, but supported Node versions in `package.json` remain the requirement for
reproducible deployment. No unsupported global tooling was upgraded.

Remaining gates: authenticated Cloudflare account/bindings, edge abuse controls,
production key pinning, deployed synthetic end-to-end verification, and explicit
runtime adoption of downloaded metadata. Initial packaged context has unknown
compiler/target/options and therefore cannot warm from public reference data.
There is no measured FPS/startup/hitch improvement attributed to this service.
