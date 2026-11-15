# Open Shader Catalog v1

Protocol identifier: `kokiri-catalog/1`. The reference implementation is in
`services/catalog/src/protocol.ts`; Python and TypeScript clients are under
`services/catalog/sdk/`. Any recompiler may implement the protocol under MIT.
Kokiri has no exclusive adapter API. A new recipe format needs its own versioned
validator; arbitrary files or strings are never a fallback format.

V1 shares shader **identities and pipeline recipes**, not shader source, game
assets, extracted code, native libraries or executable caches. Metal, Vulkan and
D3D12 binaries are not interchangeable. Clients compile validated recipes using
their own legally obtained game data and matching local toolchain. Downloading a
recipe is not evidence that a pipeline is already compiled or hitch-free.

## Context and compatibility

Every contribution and signed manifest carries exactly these context fields:

| Field | Type / meaning |
| --- | --- |
| `game_id` | Lowercase token, e.g. `oot` |
| `game_version` | Lowercase token, e.g. `131072` |
| `game_content_sha256` | SHA-256 of the adapter's declared local game-content identity, or null |
| `recipe_format` | `mng-list-v1` |
| `backend` | `metal`, `vulkan`, or `d3d12` |
| `shader_chain` | Versioned adapter/translation chain, e.g. `mng-v28` |
| `translator_sha256` | SHA-256 of exact translator binary/build manifest, or null |
| `compiler_sha256` | SHA-256 of exact compiler identity manifest, or null |
| `target_sha256` | SHA-256 of architecture/GPU-family/OS/driver identity manifest, or null |
| `options_sha256` | SHA-256 of canonical compiler/runtime generation options, or null |

Hashes are lowercase 64-digit hex. Tokens match `[a-z0-9][a-z0-9._-]{0,63}`.
The adapter must define the local identity manifests consistently; paths and
usernames are not identity inputs. Null means **unknown**, never wildcard.
`context_id = SHA256(canonical(context))`.

Only contexts with all five non-null fingerprints are `exact`. A warm-up client
must match every field against its independently computed local context.
Unknown fingerprints produce `reference-only` metadata, which SDKs reject for
warm-up. Public v28 metadata cannot silently be used as private v23 recipes.
V1 has no native-binary download endpoint.

## Canonical encoding

Canonical bytes are compact UTF-8 JSON: object keys sorted lexicographically,
array order preserved, ASCII strings, JSON escaping, no whitespace, and safe
integer numbers only. No floats/NaN/infinities. Fixtures exercise Python/TS
agreement. Do not sign pretty-printed JSON or append a newline to pack bytes.
Duplicate JSON object keys must not be emitted; server parsers normalize the
parsed value before hashing and never use duplicate-key text as identity.

Records are `{ "id": <hash>, "kind": <one-letter kind>, "row": <full TSV row> }`.
`id = SHA256(canonical({kind,row}))`. Row spelling is significant; v1 does not
claim semantic normalization of equivalent historical pipeline states.

## API

| Method / path | Behavior |
| --- | --- |
| `GET /v1/protocol` | Version, adapter, limits, quarantine policy |
| `POST /v1/contributions` | JSON `{protocol,context,records}`; validates whole batch, inserts atomically, returns 202 |
| `GET /v1/catalogs/{context_id}/manifest` | Curated signed envelope, or 404 |
| `GET /v1/packs/{sha256}` | Curated immutable metadata JSON pack, or 404 |

202 acknowledgment:
`{protocol,context_id,state:"quarantined",accepted_ids:[...],inserted,duplicates}`.
Accepted means durably accepted into the inbox, not trusted/published.
IDs in the acknowledgment must match exactly before the client removes queued
records. Retry after network/503 failures; duplicate POSTs are idempotent.
Malformed input is 400 with a bounded error token, not a copy of submitted data.

Limits: 64 KiB request bytes, 64 distinct records/batch, 4096 bytes/row;
128 records and 256 KiB/pack; at most 1024 packs/manifest. Local durable queue:
4096 records / 16 MiB. D1 quarantine capacities: 256 contexts, 100000 records per
context and 200000 total. Capacity failure is 503, not silent loss. Deployment
must also configure edge rate limiting before exposing anonymous ingestion.

## Manifest and packs

Envelope: `{manifest,key_id,signature}`. `signature` is base64 Ed25519 over the
canonical **manifest only**. `key_id` chooses a raw32-byte public key already
pinned in the application/recompiler trust store. Never trust a key received
alongside a manifest. No production key is included in this repository.

Manifest fields are exactly:
`protocol, context, context_id, compatibility, dataset_license, attribution,
revision, packs, record_count`. License is `MIT`; attribution entries contain
`name, source_url, source_commit, license`. Revision is a positive safe integer.
Each pack index entry contains `sha256,bytes,record_count`. Pack bytes are
canonical `{protocol,context_id,records}`. Verify signature, context, exact byte
length/hash, record count, record IDs, row schema and duplicates before use.
HTTPS alone is insufficient. Preserve a locally observed highest revision to
detect rollback; v1 SDK verification validates a supplied manifest but does not
maintain this application-specific trust-store state automatically.

Historical public seed packs are unsigned reference data until trusted
promotion. Synthetic test manifests/public keys in `tests/fixtures/` are test
only and must never enter a production trust store.

## mng-list-v1 adapter

Supported rows: `V` shader binding dependencies; `A` attribute dependencies;
`S` stage variant; `C` compute pipeline; `R` render pipeline; `M` task/mesh
pipeline; `T` tile-read specialization. Full row TSV includes its kind and the
upstream `m`/`t` metadata flags. Variant names are
`<64hex>-<12hex>_b`. Render-state keys must expand to exactly 544 bytes; bounded
zero-run encoding is accepted. Dependency objects allow only the upstream
`attr,fout,img,tex` groups, bounded numeric slots and type tokens.

`L` locator rows are rejected because they can expose source paths/offsets.
Border (`B`) records are not implemented in v1; they are rejected rather than
silently treated as render recipes. Import provenance reports exclusions.
This protocol carries no arbitrary source/code field. Strict validation reduces
the accepted surface; independent semantic review is still needed before
publishing untrusted recipes.
