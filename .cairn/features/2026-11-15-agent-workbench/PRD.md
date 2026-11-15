# Agent development workbench

The user authorized the reviewed OoT Editor-to-MCP development workflow on 2026-11-15: isolated disposable sessions, typed travel/input controls, transactional test-save editing and repeatable scenarios. Preserve ordinary human-session observation and all existing player data.

## Acceptance

- A configured private runtime/fixture registry supplies pinned builds and source profiles; MCP tools accept identifiers, not arbitrary paths or commands.
- Creating a session verifies and copies a complete profile without hardlinks, records source/copy hashes, and creates private settings/cache/log/control/proof/contribution destinations.
- A dedicated runtime entry acknowledges effective isolation, process identity and a revocable expiring lease. Normal launcher defaults and legacy reconnect never authorize mutations.
- Launch/control/close require the exclusive scheduled game slot and exact owned process identity. Human gameplay takes precedence. No existing process is adopted or signaled.
- Typed movement, named travel, bounded controller actions and settings return correlated completion evidence. Setup teleport is separate from measured walking/camera routes.
- Save read/plan/apply/restore operate only on a stopped owned test profile. Reuse credited editor semantics, preserve before/after diffs, source conflict checks, backups and atomic replacement. Retries are idempotent.
- Bounded scenarios compose typed actions and observation checkpoints; reports include actual presented frames, process footprint and exact build/cache/settings identities, without inventing benchmark certification.
- Keep saves, extracted game metadata/assets, binaries, logs and captures private. Preserve upstream/editor attribution. Integration alone adopts host tools or authorizes game launches/installations.

## Verification boundaries

Synthetic unit/SDK tests cover validation, identity/lease rejection, isolation paths, concurrent access, save transactions and scenario bounds. CPU native fixtures verify the dedicated launch path. Actual packaged runtime acknowledgement, travel/input, settled menus and repeated-route observation need a separate exclusive game-slot test. No mutation capability is production accepted until that live isolation test passes.

Observed on 2026-11-15 UTC: 59 MCP tests passed in 4.831 seconds, 19 native CPU tests passed, and actual input/launcher syntax checks passed. The separate development server remains unregistered. These source checks do not close the live acceptance requirements above.
