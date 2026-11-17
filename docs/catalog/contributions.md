# Contributions and trusted publication

Users choose whether to share pipeline metadata. The initial choice is
`undecided`, with contribution requests disabled. An explicit `enabled` choice
allows bounded background batches; `disabled` stops future chunks and retries.
An in-flight request may finish. Opting out cannot retract published metadata.
If persistence of opt-out fails, the client still stops new requests for its
current session and reports the error.

The durable queue deduplicates context and record IDs and retains records while
offline. Retries use exponential backoff from 2 seconds to 1 hour. Only a valid
acknowledgment of the exact submitted IDs removes pending records. One actor
owns flushing. HTTPS redirects are refused.

Contributions contain validated recipe fields. The schema rejects raw files,
shader source, binaries, saves, logs, screenshots, personal paths and additional
fields. Request logging stays off. Network providers still process the HTTPS
connection. The deployed ingestion route remains paused until host and edge
verification; the local tools below do not enable it.

## Review and publish offline

Anonymous submissions enter quarantine. Public GET routes cannot read `inbox`.
The operator must review ownership, MIT attribution and runtime reproducibility
before selecting IDs for publication. Passing schema validation does not prove
that a recipe is useful, safe to compile, or licensed for redistribution.

Use a closed SQLite backup produced by the online backup tool. Record its hash
outside the snapshot directory, verify it after transfer, and keep its mode
0600. The review command refuses WAL/SHM/journal sidecars, symlinks, hardlinks,
other-owner files, files readable by other users, or a mismatched digest. It
opens the snapshot read-only with SQLite's immutable mode and query-only policy.
Its queries have a 15-second budget.

The selected-ID file is a JSON array of 1 to 1,024 unique lowercase SHA-256 IDs.
Each ID must exist in the selected context. The attribution file is an explicit
JSON array using the protocol's `name`, `source_url`, `source_commit` and `license`
fields. Select records only after reviewing their source and reproducing them
under their claimed context.

```sh
python3 services/catalog/scripts/review-contributions.py \
  --snapshot /PRIVATE/CLOSED/catalog.sqlite \
  --snapshot-sha256 BACKUP_RECEIPT_SHA256 \
  --context-id CONTEXT_SHA256 \
  --selected-ids reviewed-ids.json \
  --attribution reviewed-attribution.json \
  --trusted-keys pinned-public-keys.json \
  --output /PRIVATE/NEW/candidate
```

The command validates context and row hashes, merges the selected records with
all records from the existing signed catalog, and retains existing attribution.
Existing manifests and packs must verify against the independently pinned public
keys. It sorts records by ID and emits deterministic bounded packs, an unsigned
manifest, and `review.json`. It retains previous signed pack evidence for the
signing step. The candidate has at most 100,000 records, 1,024 packs and 64 MiB of
pack data. Each pack has at most 128 records and 256 KiB. The snapshot stays
unchanged; no record enters the public service.

After reviewing the candidate, use an existing offline Ed25519 signing key:

```sh
python3 services/catalog/scripts/prepare-publication.py \
  --reviewed-dir /PRIVATE/NEW/candidate \
  --signing-key /OFFLINE/catalog-signing.pem \
  --key-id YOUR_PINNED_KEY_ID \
  --selfhost-sql \
  --trusted-keys pinned-public-keys.json \
  --output-sql /PRIVATE/NEW/publication.sql
```

The signing step verifies previous signed evidence again and refuses a revision
that drops published records or attribution. It requires the next revision for
that exact context. The fresh SQL output includes its SHA-256 in the result and
guards replacement against the exact previous signed envelope. Signing creates
no key and makes no network request. Keep the private key off the public host.

Rehearse importing into a closed disposable catalog copy first. Review the SQL
and its digest before an authorized live import:

```sh
python3 services/catalog/scripts/import-publication.py \
  --database /PRIVATE/DISPOSABLE/catalog.sqlite \
  --sql /PRIVATE/NEW/publication.sql \
  --sql-sha256 REVIEWED_SQL_SHA256 \
  --trusted-keys pinned-public-keys.json
```

Use this importer for selfhost SQL. It stops at the first SQL error, denies
attachment/extension/file-access SQL and changes outside publication tables,
verifies published signatures and pack integrity before commit, and rolls back
on failure. It caps SQLite pages at 1 GiB, reserves 512 MiB plus twice the SQL
size for write/journal work, checks quarantine quota accounting, and validates
unreferenced packs as well as active manifests. Its query budget is 30 seconds.
An outdated previous revision fails without replacing a newer one.
Do not paste this SQL into a client configured to continue after errors.
The importer retains quarantine rows; a separate reviewed retention procedure
must handle those rows before opening long-term public ingestion.

Without `--selfhost-sql`, the signing command retains its original first-publish
D1 output and refuses replacement of an existing manifest. It does not consume
the review receipt or permit update publication through that older path.

## Host activation gate

When the host returns, rehearse backup, review, signing and import using
synthetic metadata through the deployed HTTP service. Check anonymous reads,
protected write-path variants, disabled-ingestion behavior, rate limits and
restart/restore behavior before opening contributions. Keep signing keys and
publication commands outside the request-serving process.

Strict metadata validation prevents arbitrary executable uploads; it does not
establish that valid-looking recipes are harmless or make a service immune to
DoS. Keep bounded origin requests and database quotas, edge abuse controls and
runtime resource limits. Publish only reviewed compatible recipes, and have
clients verify the signed manifest and pack hashes before use. Compiled shader
binaries require a separately qualified distribution format and remain outside
this metadata protocol.

The public MacNativeGames seed retains MIT terms and attribution. Unknown
fingerprints keep it reference-only; neither this review workflow nor a signature
turns it into an exact runtime warm-up promise.
