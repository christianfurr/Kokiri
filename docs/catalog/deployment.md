# Hosting and operations

The checked-in project uses the current official `cf` CLI beta and
`cloudflare.config.ts`, plus the official Vite plugin. No Wrangler config or
dependency is used. Config shape was checked against installed `cf/config`
types and a successful local `cf build`. The global older cf0.0.6 is unsuitable;
use `services/catalog/node_modules/.bin/cf` after `npm ci`.

No authentication, remote database creation, deployment or production key
creation was performed for this implementation. Hosting is authorized within
the scoped free service; the practical prerequisite is an authenticated project
account and binding/resource setup. Paid changes require separate approval.

The operator should:

1. Use `cf cli search` with anonymous action/resource queries to find current
   account/D1/deploy commands, then inspect that discovered command's help/schema.
2. Authenticate the project account and create/link the scoped D1 binding.
   Apply `migrations/0001_catalog.sql` before serving requests. Do not expose an
   unmigrated or public test database.
3. Configure edge abuse controls before enabling anonymous POST ingress.
   `INGEST_RATE_LIMIT` is an optional native Cloudflare rate-limit binding; its
   shared per-colo bucket uses no IP/device identifier. Without that binding,
   edge WAF/rate rules must protect ingestion, or leave public POST traffic off.
   Quarantine capacities remain transactional hard limits, not a billing ceiling.
4. Review attribution/context and metadata resource costs. Generate/store the
   production Ed25519 private key in the operator's secure offline process, and
   pin the independently verified public key in the application. The Worker
   needs no signing secret. Never copy `test-only` fixtures into a trust store.
5. Prepare reviewed packs and run `scripts/prepare-publication.py` with that
   explicitly supplied key. It produces a fresh SQL file without uploading it.
   Apply immutable packs first, manifest last. A failed import can leave validated
   unreferenced packs; it cannot publish a partially indexed manifest. Replacing
   an existing manifest requires a separately reviewed revision migration.
6. Test the deployed protocol/contribution quarantine with synthetic metadata,
   verify manifests/packs using the pinned public key, then enable the configured
   native client. Inspect only aggregate service health; keep payload/IP/UA logging
   off. No private capture is needed for deployment verification.

O(1) quota counters update only on actual new context/record inserts and on
deletes in the same SQLite transaction. Duplicates remain accepted at capacity.
Promoting/removing quarantine records frees capacity through delete triggers.
Never edit usage counters by hand; migration changes need a consistency check.
The inbox has no automatic promotion path. Public GET routes cannot select it.

Replay protection is an application trust-store responsibility: native client
records the highest accepted revision per context; reference SDK users should
do the same. Key rotation needs an independently authenticated app/trust-store
update, not an untrusted `key_id` announcement.

Primary implementation references:
[Cloudflare cf repository](https://github.com/cloudflare/cf),
[Cloudflare Workers testing](https://developers.cloudflare.com/workers/testing/),
and the pinned `cf/config`/Miniflare package declarations. Some public cf docs
returned HTTP403 in this environment; no authentication bypass was attempted.
