# Production catalog trust activation plan

Historical proposal dated 2026-11-15, not an activation receipt. Its key and
host baseline below describes that assessment, rather than the current service.
See [project status](../../STATUS.md) for reviewed milestones. This document
itself changes no key, publication or contribution setting. Fixture keys are
not eligible for production.

## Public security boundary

The catalog is public for readers. Authentication applies to contribution
control, while publishing remains an offline operator action.

| Surface | Intended/current boundary |
| --- | --- |
| `GET /` | Public homepage |
| `GET /v1/protocol` | Public protocol JSON, no cookies/account/shared secret |
| `GET /v1/catalogs/{context_id}/manifest` | Public exact lowercase 64-hex path; signed curated metadata or 404 |
| `GET /v1/packs/{sha256}` | Public exact lowercase 64-hex path; immutable curated metadata or 404 |
| `/v1/contributions` and descendants | Cloudflare Access restricted; service ingestion independently off |
| Publishing/admin/SQL | No public endpoint; no signing private key on the host |
| Origin | Loopback listener through outbound Cloudflare Tunnel; no router port forwarding |

Read-only checks on 2026-11-15 confirmed homepage/protocol 200 without cookies,
an absent valid manifest/pack 404 without an Access redirect, contributions 302
to Access, and `/admin` 404. Both a descriptive Kokiri verifier header and a
Safari-style header succeeded. Default `Python-urllib/3.14` instead received
Cloudflare 1010/403 on reads. This is an edge client-signature restriction, not
reader authentication. Validate the assembled client's real headers before
claiming native access. Prefer a descriptive application User-Agent; any edge
exception needs exact read-path scope and separate review, without disabling
zone-wide protections. See [Cloudflare's 1010 guidance](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/).

The same read-only SSH check found ingestion false, zero public keys and zero
contexts/manifests/packs/inbox rows. Current immutable release is
`8267ddd75c183f85f2a639e28794915a2dadf8453952646e086c83e3d2065da9`.
The empty trust-store SHA-256 is
`ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356`.
These are a dated baseline; activation must recheck them for drift.

The existing host request/body/concurrency/storage limits, OS service isolation,
verified backups and strict metadata validation remain necessary. Signature
verification protects client trust if the host changes; it does not by itself
prevent denial of service or validate that a recipe improves gameplay.

## Public-key identity and custody

Proposed initial key label: `kokiri-catalog-2026-11-15-a`. It is only a proposed
label. The actual raw public bytes, base64 value and fingerprint are **unset**
until an approved generation step produces them. Do not fill these fields with
a fixture key, placeholder bytes or an invented fingerprint.

The reviewed identity receipt must contain the key ID, Ed25519 algorithm,
base64 of the exact 32-byte raw public key, and lowercase
`SHA256(raw_32_byte_public_key)` fingerprint. This fingerprint is neither a PEM
file hash nor the hash of its base64 text. Host and native pins must match it.
The existing [Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
supports the required raw public serialization and independent verification.

Propose owner-controlled macOS Keychain custody via Security
`SecItemAdd`/`SecItemCopyMatching`, with a specifically named generic-password
item and no automatic replacement on duplicate. Use a local non-synchronizing
item and review access controls. The key is an offline signing secret; do not
claim it is a Secure Enclave key. Apple's [Keychain storage guidance](https://developer.apple.com/documentation/security/adding-a-password-to-the-keychain)
describes these APIs and generic-password items.

The current publisher accepts unencrypted Ed25519 PEM through a path and reads
it with `password=None`. A future reviewed bridge can retrieve the key in
memory and provide PEM over an inherited pipe/descriptor such as `/dev/fd/3`.
Its command line contains only that descriptor path, never key bytes. The
bridge must handle short reads, child failure, descriptor cleanup and accidental
logging before production use. No bridge is implemented by this proposal.

Never place private material on the server, in source, chat, logs, shell argv,
environment variables, temporary plaintext files or cloud-synced folders. An
owner-controlled encrypted offline backup and a successful restore/signature
check are required before relying on a single custody item. APFS file deletion
is not a secure-erasure guarantee.

## Staged activation

1. **Approve custody and key creation.** Review the precise generation/Keychain
   bridge implementation first. Then generate one production key, record only
   its public identity, verify a local sign/verify challenge and verify the
   protected backup. Do not generate or rotate keys while merely reviewing.
2. **Prepare pins.** Build a new immutable host release with the public key map;
   capture its source/release/trust hashes and previous-release identity. Build
   the native shell with `KOKIRI_CATALOG_ORIGIN=https://catalog.christianfurr.dev`
   and the same `KOKIRI_CATALOG_KEYS_JSON`. `macos/build.sh` already emits the
   required Info.plist keys. Neither environment input contains a private key.
   Verify the assembled plist and real client transport under an allocated slot.
3. **Review actual data.** Use a qualified exact runtime/compiler/device/options
   context, attribution and license provenance. Separate reference-only records
   from genuinely eligible ordinary C/R candidates. Offline/mixed and mesh
   adoption keep their own acceptance gates. No public reference fixture is
   relabeled as production proof.
4. **Sign offline.** Run the existing `prepare-publication.py` against the exact
   reviewed directory through the approved key bridge. Record context/revision,
   manifest and pack hashes, counts, key ID and public fingerprint. Its exclusive
   output creation and plain manifest INSERT intentionally refuse accidental
   replacement. It performs no upload or database mutation.
5. **Stage and verify.** Import into a private disposable copy/new restore
   directory using the actual host schema. Verify database integrity/accounting,
   `verifyPublished`, exact pack hashes, complete references and independent
   client signature/context/revision checks. Exercise corruption, wrong key,
   missing pack and lower-revision rejection before activating. The existing
   publisher may leave valid unreferenced immutable packs after a failed import;
   do not reject all such packs as a substitute for validating references.
6. **Review the concrete activation.** Present exact release/trust/database
   before/after hashes, publication IDs, tested commands and rollback inputs to
   integration. No stable-host change or publication occurs before this review.
7. **Activate the approved transaction.** Recheck the baseline, stop only the
   owned web service, take/verify a consistent snapshot, and use a bounded local
   SQLite transaction with manifest insertion last. Preserve unrelated inbox and
   context data. Restart only after the staged validation succeeds, keeping
   ingestion disabled and all public routes unchanged.
8. **Verify delivery.** Cookie-free HTTPS must return the exact signed envelope
   and immutable packs. The assembled native client must download with its real
   application headers, use pinned keys, enforce exact context/hash/revision
   checks and atomically retain its index. A separate owned Metal/game test is
   still needed for actual C/R adoption; Play must not wait on the network.

The host startup, backup and restore already verify published signatures and
packs against public pins. The client independently verifies them and persists
an accepted revision floor. None of this requires opening contributions.

## Rollback and incident boundary

Before first publication, the preceding empty trust/data state and immutable
release provide a simple rollback baseline. After publication, prefer reverting
the exact owned transaction/pointer changes; use a verified database snapshot
only after proving no intervening accepted writes would be lost. Never overwrite
a user's queue or reset a client's accepted revision floor.

If a publication must be contained, withdraw only affected manifest/pack reads
while preserving the public homepage/protocol and protected/paused contributions.
Reverting a database or server release cannot revoke data already downloaded or
erase a client's revision floor. A correction needs a higher signed revision.
The current publisher refuses replacement, so a future revision update requires
an explicit reviewed migration with a compare-and-swap precondition.

A signing-key compromise requires a reviewed pin rotation/client release and
recovery plan. Publish new pins before relying on a new key where compatibility
requires overlap; an envelope has one key ID/signature, not implicit dual
signatures. No key rotation is part of this first activation proposal.
