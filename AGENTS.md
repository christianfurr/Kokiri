# Kokiri agent guide

## Start here

Kokiri is an independent, credited Apple silicon/macOS project built on MacNativeGames. Preserve MIT attribution and third-party notices. Development belongs in this repository, not new upstream PRs unless the user requests them.

Read `.cairn/MAP.md`, `.cairn/DECISIONS.md`, the foundation PRD under `.cairn/features/2026-11-15-kokiri-foundation/`, and `STATUS.md` before substantive work. Read the relevant feature PRD/review too. Verify documentation against current source, installed artifacts and processes.

**Shared-checkout warning:** the main local checkout can be older than integrated `master` and contain valuable uncommitted MCP work. Missing `STATUS.md` does not mean the recent work never happened. Inspect Git refs/worktrees; consult the Integration worktree without resetting or switching the shared checkout.

## Current handoff — 2026-11-16

- A full-v28 private game package is accepted: **42,466 compiled Metal libraries, 28,786 completed pipeline requests, including 196 mesh**. Newly encountered specializations can still compile during play.
- The user reports good gameplay and accepted audio. Wider performance, memory and visual acceptance remain open. The broader performance campaign is deferred; do not restart it without current authorization.
- Connected launcher implementation: `e5805182fbf503632941d553bdd937d095520e13`. Home/Play, current profile, Settings, recent Performance and the public Shader Library were checked in the installed app. Thirty-five native tests and independent review passed.
- Integrated source: `2798f7e6b4088b7045e740fae90fb2ac44f40928` (PR #3); all three CI jobs passed. These are historical identities: verify the current HEAD and installed bundle before relying on them.
- https://catalog.christianfurr.dev serves **29,796 signed reference recipes in 233 packs**. Anonymous HTTPS and actual native downloads were verified. Contributions remain disabled. This is metadata, not downloadable compiled shader binaries or an exact runtime warm-up cache.
- The app cleanup's **6/6 completed items describe that batch only**, not project/release completion.
- There is no stable signed/notarized public release. Production feeds/signing, actual runtime update/relaunch/rollback, physical-controller checks and wider gameplay acceptance remain separate gates. Reconnecting observation to an already-open private game was reviewed/tested at the admission layer, but not exercised during human gameplay in that batch.

## Preserve the working environment

- Use your own branch/worktree and build outputs. Never reset, clean, stash away, switch, or overwrite another chat's shared checkout. Preserve dirty `tools/kokiri-mcp/` implementation and recent website work.
- Only Integration integrates changes or authorizes installation/releases. Coordinate through **Kokiri — 00 Integration**; discover actual chat IDs rather than guessing. Other specialist chats were stopped. Do not wake or resume them just because a historical task exists.
- Specialist lanes: 01 Shaders; 02 Performance and Memory; 03 Native App and MCP; 04 Public Shader Library; 05 Updates and Releases; 06 Audio. Resolve ownership before overlapping edits to `nvn_mtl.m`, `engine/build.py`, `frontend.m`, shared Swift models or CI workflows.
- Only **one heavy build, Metal test or gameplay benchmark** may run at once on the 16GB development Mac. A quiet process list alone is not a workload grant. Check live ownership and Integration's current schedule first. Human gameplay takes precedence.
- Never terminate, relaunch, send game input to, or replace a human-owned game. Human observation is distinct from disposable development control. Preserve the cross-app game slot and ownership checks.
- The latest live private playtest profile is the player's current lineage. The user originally selected the latest legacy Ocarina progress; that was copied and subsequently played. **Do not overwrite newer private-playtest progress with the older legacy source.** Establish lineage and verify complete backups before any migration.
- Preserve complete compatible caches, mesh records and explicit user PSO files. Do not trim or rebuild them merely to simplify a task. Never delete the only working build or rollback copy during cleanup.
- Local paths, bindings, save lineage, rollback artifacts and exact private evidence belong in the local Integration ledger, not public docs. On the current Mac, consult `~/Downloads/kokiri-integration-20261115/status.md`, `progress.json` and the connected-shell acceptance receipt; recheck freshness. Do not commit that private ledger.

## Source map and verification

- `macos/`: SwiftUI launcher; `KokiriCore` contains preparation, profile, session and catalog checks. The launcher and game are separate artifacts; updating one does not update the other.
- `engine/`: native runtime, renderer and private game builder. Keep game inputs and generated outputs outside source.
- `services/catalog/`: metadata protocol, verification, signing/publication tooling and self-hosted service. Private signing keys stay off the public service. Reference downloads stay separate from exact runtime input and game caches.
- `tools/kokiri-mcp/`: observation/development tools; preserve uncommitted work and enforce human/development boundaries.
- `website/`: existing static GitHub Pages design. Preserve approved visuals; use direct copy and label illustrative/historical captures.
- `release/`: launcher and runtime-source update tooling. Tested plumbing does not prove production distribution.

For launcher changes, run `bash macos/test.sh` and `bash macos/build.sh` only after workload clearance. For publication, stage only owned files and run `python3 -I scripts/check_publication.py --staged`; check the staged diff. Run relevant targeted tests for other changes. A documentation-only edit does not require rebuilding the game or shaders.

Keep game assets, extracted shaders, compiled caches, saves, logs, credentials and private bindings out of Git, CI artifacts and public reports. Do not bypass publication or compatibility checks.

Never describe an `OOT_SHADERS=none` package as fully prepared. The earlier incomplete package warmed only 1,861 libraries/1,920 pipelines. The 50,376 source rows are not compiled-shader counts; v23 caches cannot be relabeled as v28. Report exact executable, receipt and shader-pack identities, route/cache conditions and remaining limitations before any readiness claim. Full release acceptance needs matched cold/warm walking, camera and transition routes, repeated-area soaks and visual checks.

Write durable decisions and acceptance evidence to the appropriate Cairn files. Give concise progress updates with a real scoped task count; distinguish source checks, installed behavior, user reports and public release readiness. If the user says stop everything/all chats, stop immediately and preserve state until directly resumed.
