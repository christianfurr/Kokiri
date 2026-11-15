# Decisions

- 2026-11-15: The user chose Kokiri and authorized a standalone repository, not a GitHub fork. Preserve MacNativeGames and third-party notices and credit the source lineage.
- 2026-11-15: Keep native ARM64 execution and Metal as the initial foundation. Preserve game identity separately from product branding; do not rebuild the CPU frontend without evidence.
- 2026-11-15: Keep game dumps, generated code, shaders, caches, fonts and saves outside the public source repository.
- 2026-11-15: App updates use signed releases; the shared shader catalog has an open, versioned protocol and separate backend/compiler compatibility namespaces.
- 2026-11-15: The user requested automatic contributions. New public users make a one-time choice; contributions contain pipeline metadata, not saves, logs or extracted shader code.
- 2026-11-15: README statistics and screenshots must come from the implemented app and documented measurements. Existing severe FPS drops, cold hitches, memory peaks and terrain corruption remain acceptance work.
- 2026-11-15: The user added an original logo, a custom game menu and configurable HUD position, size and detail. The runtime and product app share HUD preference version 1; legacy bundles do not advertise this capability.
- 2026-11-15: Created the independent public repository at https://github.com/christianfurr/Kokiri without a fork relationship. Source publication waits for the asset/provenance scan.
- 2026-11-15: At the user's request, closed all three then-open MacNativeGames PRs authored by christianfurr: #2180, #2181 and #2206. Continue development in Kokiri; do not reopen or create upstream PRs without a new request. Closed PR history and existing licensed public code remain available.
- 2026-11-15: L3 + R3 and key 1 open the custom in-game settings. HUD preferences cover detail, corner and scale; the full runtime HUD samples actual process physical footprint. Gameplay and controller-chord validation remain required.
- 2026-11-15: Runtime live status is capability version 1. The ordinary product observes position only; movement/travel commands require an agent-owned, separately copied profile. Cache the verified capability for the active session rather than trusting an earlier app selection after a bundle replacement.
- 2026-11-15: NativeAOT 10.0.12 is not release eligible after the servicing advisory. Both shader tools now build from source with runtime 10.0.14, with official package hashes and actual output checks; do not suppress the advisory or reuse the older binaries.
- 2026-11-15: The first public-v28 cold run ended after a malformed diagnostic command from the harness. It supplied no world-ready, performance or terrain acceptance evidence. Preserve that failed run and use only valid input grammar in subsequent tests.
- 2026-11-15: Local catalog protocol/client/signature tests do not establish a live public library or performance benefit. Exact compiler, target and effective-option identities and bounded native warm-plan adoption must be verified separately; no incompatible cache relabeling.
