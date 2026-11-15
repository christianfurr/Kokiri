# Native metadata handoff

The native render/compute adapter and renderer admission hook are implemented
and CPU tested. On 2026-11-15 the public homepage and
[protocol endpoint](https://catalog.christianfurr.dev/v1/protocol) were verified
over HTTPS, including a browser with no cookies or login. Exact manifest/pack
read paths are public; contributions remain protected and disabled. There are
no published production packs or manifests yet. **Production signing and pinned
native keys, an assembled-client download, and actual game adoption remain
unverified.** No performance improvement is claimed from downloading or
preparing metadata.

The current adapter does **not** prepare task/mesh (`M`) pipelines. The measured
multi-second cold mesh compilation hitches need a separate mesh preparation
path. A nonempty precompiled `shader-libs` directory also stays reference-only
until its offline compiler/library provenance is included in the identity.
Neither limitation changes the renderer's existing shader-selection behavior.

## Remaining acceptance

1. Prepare an operator-reviewed, signed publication for a real qualified context
   with its attribution and pack hashes. Keep its signing private key off the
   host. Pin the same production public key in the host trust store and native
   app; do not use fixture keys. `macos/build.sh` already accepts
   `KOKIRI_CATALOG_ORIGIN=https://catalog.christianfurr.dev` and
   `KOKIRI_CATALOG_KEYS_JSON`, producing `KokiriCatalogOrigin` and
   `KokiriCatalogPublicKeys`. Without both origin and keys, the facade remains
   unconfigured. Enabling community ingestion is not required to prove reads.
2. Under a separately granted CPU slot, verify the assembled Swift client with
   that origin/key pair: public download, signature/context/revision/hash checks,
   an atomic local index, bounded failures and retry, and operation without
   cookies or a shared API secret. Sharing remains a separate one-time choice;
   a disabled contribution service must preserve queued records safely.
3. Under a separately granted game/Metal slot, use an owned disposable profile
   and the exact recorded executable, translator, device/options observation and
   locally translated variants. Demonstrate an ordinary C/R recipe absent from
   the local recipe list being admitted through the actual renderer hook. Prove
   stale context, source drift and invalid metadata are deferred; preserve player
   progress, valuable caches, explicit PSO files and existing recipe lists. Play
   must not wait for the network. A JIT qualification pilot does not establish
   acceptance of a fully prebuilt v28 package or a frame-rate improvement.
4. Keep offline/mixed libraries and mesh adoption deferred until their separate
   contracts below are reviewed and exercised. The deadline does not change
   these admission boundaries.

### Offline and mesh boundaries

The preparation tooling now records a component-qualified offline compiler
context with selected driver, frontend/linker, inputs, dependencies, effective
flags/target and loader policy. That source-level qualification does not prove
which library a runtime actually loads or establish equivalence to its JIT
compiler descriptor. `kcr_observe` still rejects a populated `shader-libs`
directory. Do not remove a completed library set or relabel its receipt to make
the JIT adapter qualify. Offline/mixed admission needs a reviewed identity
contract binding the actual selected library bytes and load path to the qualified
preparation context, including any JIT fallback, followed by live verification.

Signed task/mesh (`M`) metadata remains intact but is not converted into ordinary
C/R warm rows. Mesh acceptance requires the renderer owner's task/mesh pipeline
ABI and preparation path, compatible source/reflection and compiler identities,
and a separately authorized Metal/game adoption test.

## Implemented native path

1. `CatalogFacade` activates the handoff only for a runtime declaring
   `KokiriCatalogWarmVersion=1`, with a configured endpoint and pinned keys.
   An unconfigured build supplies no catalog environment variables and performs
   no extra catalog identity observation on Play. Sharing consent is separate
   from downloading metadata.
2. During an owned session, the renderer observes its selected Metal device,
   public Metal API image UUID, OS build, actual immutable compile-options object,
   runtime executable, translator and packaged content identity. The private
   `kokiri-runtime-identity/1` receipt contains a generic device model/families,
   not a registry ID or serial number. Paths/descriptors stay local; only the
   versioned context hashes accompany contributions.
3. An owned session's appended metadata is captured before asynchronous identity
   work, so a later Play cannot add rows to the previous context. Runtime option
   changes invalidate the receipt. Startup changes are bracketed with an atomic
   generation/active-writer guard; a concurrent change prevents qualification.
   Invalid or missing observations defer sharing for that qualified session.
4. A subsequent exact-context refresh creates the native client's signed,
   content-addressed index. `CatalogWarmPlan.swift` revalidates its pinned
   signature, context, persisted revision floor, every pack hash and record ID.
   There is no network wait during Play: preparation uses already verified local
   metadata or proceeds without a catalog candidate.
5. Ordinary nonmerged/nonhost/non-specialized render (`R`) and compute (`C`)
   recipes can propose a pipeline not already in a local recipe list, provided
   every variant has local translated source and matching chain/key/stage
   reflection. The downloaded recipe never supplies shader code or a binary.
   A fresh immutable session handoff binds the rows and local byte fingerprints.
6. The renderer compares a **fresh** effective identity with the proposed context,
   checks the shell-pinned handoff SHA and local current-game scope, and verifies
   each source/reflection fingerprint. Render state is checked by the actual
   production `pso_skey_parse`/544-byte ABI; host pointers, generated host bits,
   merged/fz/layered/HDR variants and incorrect stages are rejected.
7. Accepted rows remain in memory as an immutable virtual list. The list is
   appended and classified as shipped under the existing archive/residency
   policy. Title, shared and user lists remain present. `DM_PSO_MANIFEST` is
   never set by this adapter; an explicit existing override still wins. Nothing
   is appended to `pso_user.tsv` by the adapter.

The renderer retains its existing `warm_available`, `warm_plan`, worker counts,
archive limits and low-memory shared-pipeline policy. With existing archives,
ordinary pipelines may already be prepared and yield no additional compile
gain. The general warm worker can still scan its normal translated cache;
the candidate limit bounds this adapter's additional work, not the entire
renderer or every game shader.

## Bounds and proof costs

| Boundary | Limit |
| --- | --- |
| Input catalog | 100,000 records, 1,024 packs, 64 MiB |
| One parsed pack | 256 KiB / 128 records |
| Retained handoff | 512 ordinary C/R rows, 1 MiB including proofs |
| Shell variant memo | 1,024 successful/rejected variant-stage entries |
| Local shader proof reads | 64 MiB total, source **and** reflection, independently in shell and renderer |
| One reflection | 1 MiB, parsed once per unique successful native variant |
| Identity receipt | 64 KiB in native shell |

All actual proof reads, including reads preceding a failed drift check, count
against the shell budget. Repeated invalid variants are memoized; exhausting
the budget defers new candidates. The native verifier memoizes successful
variant proofs, bounds aggregate source/reflection reads, and releases temporary
JSON objects per variant. Its executable and translator identity hashes are
separate, bounded streaming reads once at opted-in startup, outside frame replay.

Input readers walk directory components with `O_NOFOLLOW`, open regular files
with size bounds and reject changes during reading/hashing. A modified handoff
path cannot change admitted rows because workers read the retained text.

## Compiler identity meaning

The native reader explicitly accepts only the currently emitted runtime-JIT
compiler descriptor fields and scheme, including its canonical API UUID. A
different/offline scheme or extra offline evidence is rejected even when its
descriptor/context hashes agree. A preparation receipt's qualified offline
compiler context must not be relabeled as this JIT descriptor. Full offline or
mixed-path admission still needs a separate reviewed semantic contract.

`compiler_sha256` hashes a canonical descriptor declaring
`kind=metal-runtime-jit` and
`platform_compiler_identity=os-build-and-public-metal-api-image`. This is the
observed OS-provided JIT platform/API identity, **not** a claim to hash a private
compiler-service executable. An offline `xcrun metal --version` result is not
substituted for it.

`target_sha256` binds the actual selected generic device model, supported known
families, architecture, memory class and the OS/public-Metal build identity.
`options_sha256` binds the actual language/library/optimization/math/invariance
properties and supported source-generation controls, plus runtime, translator
and chain. Nondefault external mesh translation, device-library mode, unknown
macros/dynamic libraries or a populated ordinary prebuilt-library directory fail
qualification. The runtime continues using its original shader behavior.

The packaged context deliberately keeps compiler/target/options null. A real
execution observation is required to qualify it. The first adapter does not
invent values for precompiled shader libraries or attempt mesh ABI equivalence.

## Files and verification

- `macos/Sources/KokiriCore/CatalogWarmPlan.swift`: native signed-index adapter,
  private identity validator, bounded local-file readers and immutable handoff.
- `engine/third_party/d2r_gfx/gfx/nvn/kokiri_catalog_runtime.h`: Foundation-only
  identity, path, byte-budget, generation and handoff helpers.
- `kokiri_catalog_metal.inc`: actual selected-device/options observation, scoped
  local shader proof and renderer integration.
- `kokiri_catalog_pso.h`: production parser admission gate.

On 2026-11-15 the native shell suite passed **20 tests**, including eight new
warm-plan tests: a signed novel compute recipe with existing local bytes,
packed render expansion, signature/pack/revision rejection, missing/symlinked
variants, 512/513 deferral, executable replacement, a reused rejected variant
across 1,000 recipes, and an oversized sparse local source. Synthetic fixtures
contain nonshader bytes and never execute on a GPU.

Later that day the focused `CatalogWarmPlanTests` suite passed **12 tests** at
the compiler-identity guard change: the original eight plus four cases covering
unsupported/offline descriptors with consistent hashes, extra offline evidence,
canonical API UUIDs, and signed mesh deferral. That CPU-only run does not replace
the remaining assembled-client and actual renderer adoption checks above.

The actual Foundation helper and production pipeline parser passed **60 checks**
under AddressSanitizer/UndefinedBehaviorSanitizer. Checks include immutable
admission, source drift, aggregate proof limits, successful variant memoization,
generation changes, pointer/host/specialized-state rejection, symlinks in any
input/output path component, and real permission failures during invalidation.
When an invalid receipt cannot be published, the runtime removes/truncates its
owned receipt; if that also fails, it defers the option mutation instead of
leaving changed options behind an old valid context. No actual game adoption or hosting is implied.

The older Python `sdk/python/runtime_adapter.py` remains a conservative tooling
reference with an additional build-attested local-recipe intersection. Its
11-test oracle remains useful for format/ABI regression. It is not installed as
a Mac user's runtime dependency or substituted for the native adapter above.
