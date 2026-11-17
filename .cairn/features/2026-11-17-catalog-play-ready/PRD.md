# Catalog preparation and contributions

## Brief

Goal: use shared recipes to make local game preparation easier, retain verified downloads offline, and prepare a reviewed contribution publication loop while homeserver is unavailable.
Acceptance: a user can recover previously verified recipes without a network, merge a signed catalog with the existing local preparation list, and an operator can curate a snapshot into a guarded signed publication. Play remains independent of server availability.
Stack: SwiftUI/Foundation/CryptoKit launcher; Python preparation SDK; TypeScript protocol and Node/SQLite home-server service.
UI route: retain existing SwiftUI Surface, MetricCard and PageHeading components. No redesign or UI dependency.
Branch: feat/catalog-play-ready from integrated 49525d3.
Fleet: subsystem, three parallel recon/proposal agents, two safety judgments, three nonoverlapping implementations, independent review after implementation. Four concurrent slots maximum.

Assumptions: local compilation is an accepted fallback. Ready-made binary distribution requires a separate signed artifact protocol and actual compiler/device validation; the current metadata schema remains unchanged. The server is offline, so no deployment, production migration or ingress activation occurs tonight. Existing private-preview contribution isolation stays intact.

## Repo map

- macos/Sources/KokiriCore/CatalogClient.swift: signed metadata downloads, durable consent/queue, revision floors.
- macos/Sources/KokiriCore/CatalogFacade.swift: selected-runtime state, background refresh and owned-session capture.
- macos/Sources/KokiriCore/CatalogWarmPlan.swift: exact-context C/R admission with local shader witnesses.
- engine/build.py: --shader-list feeds existing local translation, library/pipeline preparation and receipts.
- engine/scripts/shader_list.py: dependency-aware recipe merge and host-row admission.
- services/catalog/src/worker.ts: bounded metadata validation, quarantine and immutable public reads.
- services/catalog/selfhost/server.mjs: loopback-only HTTP ingress, rate/time/concurrency limits.
- services/catalog/scripts/prepare-publication.py: offline signing, initial publication SQL.

## Approach

Recover signed cache indexes before network refresh and revalidate their packs. Export signed reference recipes only into local preparation, merged with the baseline; preserve exact runtime admission.
Build local snapshot curation and guarded revision publication using the existing schema. Reject direct quarantine publication and interpreting reference metadata as an exact cache. An offline-cache-only patch would leave preparation and contribution publication disconnected; a compiled-binary protocol would require a larger runtime/Metal validation project.

## Verification

Run existing native tests and release build serially after workload clearance. Run npm typecheck, service tests, Python SDK/publication tests, real loopback selfhost tests and bundled lifecycle tests. Use disposable synthetic smoke cases for new CLIs and hostile-request rejection. Run source publication scan, diff whitespace check and cairn check. No game, GPU or player-data mutation.

## Security

Contributions accept strict bounded metadata only. Reject executable/file fields, malformed hashes, unsupported rows, oversized/compressed bodies and invalid routes. Keep uploads quarantined; operators must review provenance and reproduce recipes before signing. No signing key on the service. Preserve request, connection, timeout, SQLite capacity and filesystem limits. Public edge abuse controls and Access behavior require live verification before opening ingress; origin controls cannot guarantee resistance to internet-scale DDoS.

## Out of scope and remaining gates

No ready-made binary download/install protocol, generated shaders in Git, live service updates, auth changes or gameplay/performance claims. Ready-made packs need signed artifact metadata, exact compiler/device/options identities and actual Metal adoption checks. Operator signing remains outside the server. The public recipe service remains paused for contributions until reviewed live ingress acceptance.

## Risks and rollback

Cached data may be corrupt or stale: revalidate signatures, pack hashes, counts and revision floors; retain local preparation on failure. Contribution updates may race: require an expected previous envelope and execute atomically. Local merge may lack shader bindings: retain baseline dependencies and report refused records. Revert this branch to remove new behavior; existing player caches and service data stay untouched.
