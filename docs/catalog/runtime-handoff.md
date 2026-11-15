# Downloaded metadata → bounded local warm candidate

Status: the independent reference adapter is implemented and CPU-tested. Runtime
list insertion and native execution-receipt emission are proposed below for
review; they are **not enabled**. There is no claim that downloaded metadata has
already warmed a game session.

## Existing runtime behavior, verified from owning public source

`engine/third_party/d2r_gfx/gfx/nvn/nvn_mtl.m`:

| Function / lines at review | Relevant behavior |
| --- | --- |
| `warm_available`,10979 | Requires game shader scope plus an existing local translated source/library or prepared library; missing variants are skipped |
| `warm_plan`,11219 | Builds eligibility only after local availability checks; parses render keys with actual `pso_skey_parse` |
| `warm_worker`,11467 | Without valid archive/fill lists, also discovers late local translated shaders; changing the list alone does not bound that scan |
| `warm_light`,11582 | Compiled only on iOS; not a Mac closed-game preparation command |
| `warm_start`,11775 | `DM_PSO_MANIFEST` replaces normal title/shared/user lists; it does not append |
| `warm_start`,11826 | Shared/shipped classification determines archive-only treatment; a new override path is not automatically classified as shipped |
| `warm_shared`,7365 | OoT desktop <=16 GiB defaults to archive-only shared pipelines; explicit user override wins |
| `totk_precise_opts`,7500 | Actual runtime options preserve invariance and safe math, unless the explicit diagnostic fast-math control changes them |

`nvn_pso_skey.h` defines a544-byte recorded state and a hex-only parser. The
catalog can contain its packed representation; that representation cannot be
passed through unchanged. Recorded host pointers and host-generated pipeline
bits are invalid warm metadata. `runtime/loader.c:630` does not currently acquire
the shared game slot for `pipeline-archive`, although it does for boot and GPU
probes. That packaging command is not an automatically safe launch substitute.
No denied SDK/private archive implementation was read for this review.

Consequently, setting `DM_PSO_MANIFEST` from the launcher would both drop normal
lists and change residency classification. It is not the accepted integration.

## Implemented independent adapter

`services/catalog/sdk/python/runtime_adapter.py` exports `prepare(...)`. It:

1. Requires a fully qualified exact context and independently attested **local**
   evidence. It checks the actual runtime binary hash and descriptor hashes.
2. Revalidates the signed native index with app-pinned keys and exact context;
   verifies every referenced pack/hash/record ID, bounded to64 MiB/100000 records.
3. Intersects candidates with a build-attested local recipe allowlist and an
   attested local variant inventory; verifies selected local file bytes/stages.
   Catalog-provided hashes cannot serve as these local trust anchors.
4. Handles compute (`C`) and ordinary nonmerged, nonspecialized render (`R`)
   recipes. Packed render state becomes the actual1088-digit hex representation;
   embedded pointer fields, host-generated bits, inappropriate stages and
   specialized states are rejected. `M/T/B/S/V/A` are counted as deferred or
   unsupported for this first handoff. They are not silently warmed.
5. Writes at most512 recipes /1 MiB into a fresh immutable candidate folder with
   a deterministic receipt. It neither runs the renderer nor modifies a profile,
   runtime bundle, shader cache, user warm list or existing candidate. No eligible
   records means no warm artifact. Repeated identical preparation reuses the
   validated immutable output.

The adapter is a Python reference/tooling implementation. It is not a new
requirement for Mac users to install Python and has not been substituted for the
native client. A native adoption path must implement the same checks or expose
an equivalent verified core interface before launch integration is enabled.

The local allowlist is intentionally conservative: it must come from a reviewed,
reproduced build/recipe receipt, not merely another arbitrary TSV file. This can
prioritize already shipped safe recipes based on public observations. It cannot
adopt a novel network recipe solely because its syntax is valid or signed.

## Exact identity receipts — proposed producer contract

Hashes have distinct meanings:

| Context field | Meaning |
| --- | --- |
| `game_content_sha256` | Hash of canonical verified content-identity descriptor; not a path or raw concatenated data blob |
| `translator_sha256` | Hash of the actual rebuilt translator executable |
| `compiler_sha256` | Hash of a canonical **compiler identity descriptor**, not implicitly a compiler binary hash |
| `target_sha256` | Hash of a canonical generic device/OS/driver descriptor; never registry ID, serial number or username |
| `options_sha256` | Hash of a canonical observed compiler/source-generation options descriptor |

The private `kokiri-local-warm-evidence/1` receipt binds the exact context,
runtime binary SHA, the three identity descriptors and a local variant inventory.
Each descriptor includes its versioned schema and `observed:true`; that marker
is only a claim to be checked against the producer's independently pinned
receipt hash. It is not evidence by itself. Descriptors are never uploaded as
arbitrary user files; the public context contains only their hashes.

Before qualifying the current null values, trusted build/runtime code must
produce actual observations:

- Compiler: distinguish runtime Metal JIT from offline `metal` compilation.
  Offline identity can bind actual compiler executable/version, SDK and exact
  flags from the verified build receipt. Runtime JIT needs actual OS build and
  loaded Metal/compiler-framework build identity. Do not label an offline
  `xcrun metal --version` query as the compiler used by `newLibraryWithSource`.
- Target: record generic actual Metal device model, supported families,
  architecture and OS/driver/framework build identity. Use actual selected
  device observations. Never include `registryID` or other unique identifiers.
- Options: record effective properties from the compile-options object at use,
  plus effective source-generation controls, shader chain, translator hash and
  runtime binary identity. Include mesh packing/translation controls that change
  generated sources; an interactive change must invalidate or start a new context.
  Static source defaults are not proof of a particular process's effective values.

The current packaged compiler/target/options remain **null**. No code in this
adapter invents or auto-fills those values. A runtime execution receipt producer
and its complete field set require root review before identity qualification.

## Proposed minimal native hook, awaiting review

After a configured native client's automatic exact-context refresh, prepare a
candidate only while the owned game is closed. Preserve the existing title,
shared, manifest and user paths. Add one separately verified candidate path to
that list, classify it as shipped for existing archive-only low-memory policy,
and cap its actual adoption to the adapter's512 rows. Missing local variants
remain skipped. Do not change worker counts, cache/residency limits or warm-shared
defaults. Do not write `pso_user.tsv` or use `DM_PSO_MANIFEST` to replace defaults.

The renderer must validate the sealed candidate/context receipt before using the
path and report planned/eligible/prepared/missing counts separately. The launch
environment/hook and effective identity producer are not yet added. If a separate
preparation command is chosen, it must hold the standard shared game slot and
use the same actual runtime/compiler target; packaging mode alone does not prove
that. Native mesh (`M`) preparation needs its own bounded path/proof and is not
claimed by ordinary render/compute coverage.

## Tests

`tests/test_runtime_adapter.py`:11 CPU-only tests passed in0.46 seconds, including downloaded
compute→actual warm TSV, packed render→544-byte production representation,
reference-only rejection, local-byte drift, signed-but-unattested rejection,
missing variants,512/513 budget, host pointer/specialization rejection, tampered
packs and symbolic-link rejection. A tiny C oracle compiles the actual production
`nvn_pso_skey.h` structs/parser with real `blend_st/va_st/vs_st` definitions and
only an `NvShader` interface stub. It proves544-byte size, pointer/host-bit offsets,
and acceptance of the adapter's expanded bytes by the actual parser; the actual
host-bit negative also rejects. Synthetic local bytes are nonshader test data;
no GPU, game, native runtime build or production upload was executed.
