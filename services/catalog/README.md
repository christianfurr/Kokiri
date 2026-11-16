# Kokiri Open Shader Catalog

An open MIT metadata protocol, Cloudflare Worker/D1 implementation, and
TypeScript/Python clients. The native Foundation/CryptoKit client is
`macos/Sources/KokiriCore/CatalogClient.swift`. Protocol and trust/consent details
are in `docs/catalog/` at the repository root.

An optional guarded Node/SQLite host reuses the same HTTP handler and validators:
[selfhost/README.md](selfhost/README.md). Its private loopback staging is separate
from public hosting, production signing and native runtime acceptance.

Local setup (no authentication or remote resources required):

```sh
npm ci
npm run typecheck
npm test
npm run test:python
npm run build
```

Use a Node version supported by the pinned `cf` CLI (see `engines`). This Mac's
22.22 runtime ran the tests/build, but is below cf's declared 22.23 minimum.
`npm run build` uses `cf build` and the official Cloudflare Vite plugin with
`cloudflare.config.ts`. No Wrangler dependency/config is installed. The
Node tests use actual local workerd/D1 through Miniflare, not a SQL mock. Python
tests require `cryptography`; native client tests require macOS Swift/CryptoKit.

The public protocol endpoint responds; a published dataset and verified native
adoption remain pending. See [project status](../../STATUS.md) for current
acceptance. Do not use synthetic test keys for production. The seed is 56
attributed public metadata records, unsigned and reference-only. It does not
claim cache coverage or performance.

Storage is D1 only; immutable metadata packs are bounded small JSON documents.
R2 is unnecessary until measured pack sizes justify it. No native binary upload
or download route exists.
