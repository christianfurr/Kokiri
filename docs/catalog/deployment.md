# Hosting and operations

## Self-hosting assessment

The protocol does not require Cloudflare, but the current server implementation
does: `src/worker.ts` expects Workers request handling and a D1 binding. There
is no production Node/SQLite HTTP server in this repository. Installing Node or
copying the SQL migration alone does not make a self-hosted catalog available.

A 2026-11-15 SSH assessment verified the existing migration on Ubuntu 22.04's
SQLite 3.37.2, in memory only. `INSERT ... RETURNING`, duplicate handling,
capacity-trigger rejection and delete accounting passed. This establishes SQL
compatibility, not a persistent deployment, restore procedure or load capacity.

For a small home-hosted deployment, the proposed path is:

1. Reuse the existing TypeScript protocol validators and HTTP route logic behind
   a supported Node LTS HTTP adapter. Implement the D1 operations with SQLite,
   retaining whole-batch transaction rollback and logical `RETURNING` counts.
   Test concurrent duplicates, overflow rollback, invalid/oversized requests,
   immutable downloads and offline/restart behavior against real HTTP/SQLite.
2. Run one unprivileged service bound to loopback with its own private data
   directory. Use an isolated supported Node runtime if the host's system Node
   is unsuitable. Docker and a system-wide Node replacement are unnecessary.
3. Publish only that service through an authenticated named Cloudflare Tunnel
   and a deliberately selected HTTPS hostname. Tunnel is an outbound connection;
   no router port forwarding is required. Tailscale's existing private SSH path
   is administration access, not a public catalog endpoint. Keep anonymous POST
   ingress disabled until its rate limit is enforced outside and/or within the
   adapter; request-size and transactional quarantine limits remain required.
4. Back up SQLite through its online backup API (or stop the service before a
   consistent copy); copying only the main file while WAL writes are active can
   omit recent transactions. Retain dated backups off the host and restore into
   a separate directory. Validate integrity, foreign keys, aggregate quota
   counters, signed manifests and pack hashes before a restore is promoted.
5. Keep the production signing key off the public service. Publish reviewed
   immutable packs and their signed manifest using the same offline process
   below. Ship the independently verified public key and HTTPS origin with the
   app only after end-to-end acceptance.

The checked-in reference seed is **56 records / 15,346 pack bytes**, unsigned and
reference-only. Quarantine's 200,000-record global bound permits up to
819,200,000 raw row bytes before SQLite/index/context overhead. That is an upper
bound, not measured usage or a database-size ceiling: reviewed packs, backups
and logs need separate retention. Measure resident memory, request latency and
disk growth on the implemented service; no production footprint or throughput
has been measured.

Self-hosting preserves the metadata-only boundary: no game data, extracted
shaders, native libraries, caches or saves. Hosting also does not remove the
native adapter's existing gates: mesh adoption and exact compiler provenance
for populated prebuilt-library bundles remain unsupported. See
[runtime-handoff.md](runtime-handoff.md). Keep the static website and app
release distribution separate from this small catalog API.

This is an assessed deployment option. No server adapter, running service,
production signing key, DNS route or public endpoint is supplied by this
assessment. Internet upload capacity, availability and public request latency
remain unmeasured.

References: [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/),
[hostname routing](https://developers.cloudflare.com/tunnel/concepts/routing/),
[supported Node releases](https://nodejs.org/en/about/previous-releases), and
[SQLite online backup](https://www.sqlite.org/backup.html).

## Existing Cloudflare Worker deployment

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
