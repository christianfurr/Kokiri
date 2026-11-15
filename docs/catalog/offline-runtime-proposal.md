# Offline and mixed catalog admission proposal

Status: proposed for integration review; no renderer implementation is allocated
by this document. Public reads remain available independently of runtime
qualification. This proposal does not publish metadata or change the host.

## Evidence and prerequisites

The existing `kcr_observe` rejects a populated `shader-libs` directory and emits
only the known runtime-JIT compiler descriptor. `CatalogRuntimeIdentity.load`
strictly accepts that descriptor; the facade requires
`KokiriCatalogWarmVersion == 1`. A hash that is internally consistent does not
make an unknown compiler scheme supported.

01 owns compiler observation, library production and actual native load/archive
verification. Its `build_shader_libs.py` binds reuse and retained files to both
the compiler identity and `compiler_context_sha256`. Its manifest contains
`sources[source_name] = source_sha256`, `files[source_sha256.metallib] =
binary_sha256`, the schema-2 compiler observation/context, and variant-cache
provenance. A retained file can have valid compiler provenance without a current
`sources` alias; admission must still prove its local source, reflection and
entry, rather than infer an alias from the filename.

Read-only inspection of 01 source `ed5041c` found the internal
`archive_library_snapshot` validator and a verify-only `lib_from_file` branch.
It hashes an owned CPU snapshot, checks the listed binary and file drift, and
passes that snapshot to `newLibraryWithData`. Its scope is the offline verifier;
ordinary gameplay still uses the existing loader. This source is not evidence
of a built executable, successful current library loads, or catalog adoption.

01 reported zero qualified schema-2 libraries actually compiled and loaded as
of this review. The historical 100-file pilots have no schema-2 observation;
their nonempty-function checks do not prove every selected entry or pipeline.
The next dependency is 01's accepted, exercised actual-byte/entry/archive proof
against the final frozen executable and manifest.

## Proposed private identity and capability

Keep `kokiri-catalog/1`, its exact context fields, and public C/R records intact.
The context's existing `compiler_sha256` can bind a newly versioned local
descriptor. This is a new admission scheme, not an assertion that offline and
JIT libraries are equivalent.

Propose capability 2 and private receipt/handoff version 2. Version-1 readers
must continue rejecting version 2; new readers explicitly enumerate supported
versions instead of accepting an arbitrary version greater than one. The final
field names/API remain a review decision before implementation.

The proposed compiler descriptor has a fixed field set binding:

| Input | Binding |
| --- | --- |
| Scheme | New schema/kind with explicit offline or mixed semantics |
| Offline compiler | 01's recomputed strict schema-2 compiler-context hash |
| Selected inventory | SHA-256 of the actual raw `libraries-manifest.json` used by the loader |
| JIT route | Existing fully observed JIT descriptor, for the mixed policy only |
| Selection policy | A versioned, enumerated policy described below |

Hash the descriptor using the existing catalog canonical encoding. Preserve
the existing actual-runtime, translator/content, target/device, OS and effective
options bindings. Local paths remain receipt references, not new public context
fields. Do not include the full inventory in the 64-KiB identity receipt.

The two proposed policies govern catalog qualification, without changing normal
renderer choices:

1. `exact-prebuilt-only/1`: every translated candidate stage must have a listed,
   qualified binary that the actual loader successfully consumes. Any fallback
   defers catalog qualification. Use this policy first for full-prebuilt v28.
2. `exact-prebuilt-otherwise-jit/1`: source-hash membership in the sealed file map
   determines the expected route. A listed binary must load as that binary; a
   source absent from the map may use the separately observed precise JIT route.
   A listed binary failing to load and falling back to JIT is unexpected and
   invalidates the catalog session, rather than silently changing its identity.

An unlisted offline binary, source-as-library payload, device-library route,
seed-image fallback without equivalent actual-byte proof, unknown compile mode,
or identity drift defers catalog use. The normal game may retain its existing
fallback behavior. Catalog observations from an invalidated epoch are not shared.

## Actual-load witness and bounded handoff

Reuse 01's load-validation seam instead of adding a second file-open/hash path
in the catalog adapter. For each admitted ordinary C/R stage, a private witness
must bind the current source/reflection hashes, source-hash lookup, expected
route, actual consumed binary hash plus compiler context (or explicit JIT
identity), requested entry name and actual function type. An existence check,
`functionNames.count > 0`, or hashing a file then reopening it is insufficient.

Candidate admission must observe the same immutable bytes passed to Metal. Any
path that can substitute bytes or retrigger translation must either supply this
witness or fail catalog qualification. 01 owns the loader and patched-variant
coverage audit, including entry selection and source fallback. No extra retained
Metal library/pipeline population is proposed.

Keep the existing 512 C/R candidate, 1-MiB handoff, 64-MiB source/reflection proof
budget, 1-MiB per-reflection and 64-KiB identity limits. All failed proof reads
still consume their applicable budget. Keep one bounded success/failure memo per
candidate stage. Do not embed all library bytes or the full manifest in each row.

The complete schema-2 inventory has not yet been measured. The two historical
pilot manifests are 31,515 and 37,484 bytes for 101 source aliases/100 files;
these are not full-set memory estimates. Before implementation approval, 01 and
04 must agree explicit manifest bytes/entry limits, per-library snapshot limits,
and a total proof/read-memory budget using the actual full inventory. A missing
bound or exhausted budget defers catalog admission. The new path must not
inherit an effectively unbounded allocation merely because it is local input.

Extend the current generation/active-writer guard to cover manifest selection,
actual load route and proof changes. An option or library mismatch invalidates
the whole qualified session for the first implementation. Finer attribution is
deferred; it is not needed to qualify a bounded first release.

## Ownership and required allocation

| Owner | Existing seam | Proposed work, only after allocation |
| --- | --- | --- |
| 01 | `metal_toolchain.py::compiler_context_key`, `build_shader_libs.py`, `preparation_receipt.py` | Authoritative manifest/context producer and exercised full-preparation receipt |
| 01 | `nvn_mtl.m::lib_from_file`, `shader_lib_prebuilt`, `shader_load_mode`, patched-variant routes; RT cache hooks | Actual bytes/entry/route witness; share an internal CPU proof seam without duplicating loader behavior |
| 04 | `kokiri_catalog_metal.inc::kcr_observe`, `kokiri_catalog_runtime.h` | Proposed descriptor/epoch/handoff admission, after shared-renderer scope is assigned |
| 03/04 | `CatalogFacade.swift`, `CatalogWarmPlan.swift`, runtime bundle capability | Explicit version-2 support and bounded local witness verification; agree file ownership first |
| 02 | Existing warm worker/archive/residency policies | Review resource impact and unchanged worker/lifetime policy; no ownership change proposed |
| 00 | Integration and exclusive native/game slots | Approve contract, assign overlaps and sequence actual acceptance |

No `nvn_mtl.m`, RT, facade, warm-worker or version edit is authorized by this
proposal. 01's verify-only instrumentation is not a license to enable new
production behavior in its normal loader branch.

## Acceptance sequence

1. Review the identity/policy, source ownership and measured parser/proof bounds.
2. Exercise 01's full-preparation proof with the final runtime, raw manifest,
   schema-2 context and actual selected entries; fresh archive reopen must show
   zero translated-library JIT attempts, misses and writes with unchanged
   archives. This excludes embedded host/support shaders and OS/driver codegen.
3. Under an allocated CPU slot, exercise the actual private validators: unknown
   schema, retained-file alias ambiguity, missing/unlisted library, byte/entry
   drift, source payload, unexpected JIT, policy mismatch, epoch race and bounds.
4. Under a separate Metal/game slot, admit a real ordinary C/R catalog recipe
   absent from the local list using the declared offline policy, then prove
   negative cases defer it and preserve normal saves/caches/archives.
5. Only then consider the explicitly mixed policy and its separately measured
   absent-from-manifest JIT route.

Full known-set preparation and a novel catalog recipe are separate claims. An
additional recipe can require a new PSO; that does not retroactively establish
or invalidate the baseline full-preparation receipt. Task/mesh (`M`) adoption
remains a separate ABI/preparation path, without conversion into C/R rows.
