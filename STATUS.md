# Project status

## Preview 4 acceptance — 2026-11-18

The mod-capable private runtime and launcher build 4 were built from clean source `037e49d2445baf8529dda389d216564b72b9850d`. 65 Swift tests, 128 focused CPU checks and independent source review passed. Fresh preparation reused 42,466 compiled libraries and verified 28,786 pipeline rows, including 196 mesh, with zero JIT attempts, misses or archive writes. A genuine receipt binds preparation to the new executable.

Actual unmodded and PlayStation-prompts-mod runs reached Death Mountain Trail and Basic Controls on copied profiles. Visual differences and native replacement validation were observed; both normal exits and original-file preservation passed. This establishes the tested pack's production Core/helper/runtime path, not all mod compatibility or the Mods-tab-to-Play flow end to end. See [Preview 4 scope and limitations](release/preview-0.1.0-4.md). Distribution remains an experimental ad-hoc-signed, unnotarized manual launcher download; game data and shaders stay private. The dated sections below retain their original identities and scope.

Updated **2026-11-16**. Launcher implementation reviewed at [`e580518`](https://github.com/christianfurr/Kokiri/commit/e5805182fbf503632941d553bdd937d095520e13). This page records reviewed milestones; source checks, private playability and public distribution are separate acceptance stages.

**Kokiri is a playable private development preview.** Full v28 preparation completed for the accepted private package. The user reports good gameplay with occasional new pipeline compilation and accepted the audio change. Broader performance, memory and visual verification remain open; there is no stable signed/notarized public release.

| Area | Implemented or observed | Remaining acceptance |
| --- | --- | --- |
| Native Mac app | Installed Home, Play/profile connection, Settings, recent-session Performance and signed public Shader Library; 35 native tests, release build, strict deep signature verification and independent review passed | Reopen during active human gameplay and physical-controller shortcut checks |
| v28 preparation | 42,466 unique compiled Metal libraries; 28,786 completed pipeline requests including 196 mesh; output-bound full receipt and final signed package accepted | Newly encountered specializations can still compile during play; other machines/builds require their own compatible preparation |
| Gameplay | User reports good current-v28 gameplay and no corruption; audio accepted | Matched cold/warm walking, camera and transition routes, repeated-area soaks, wider visuals and physical-memory measurements; the broader performance campaign is deferred |
| Shared catalog | Live public signed reference dataset: 29,796 records in 233 packs; anonymous HTTPS and actual native app verification; signed backup/restore and off-host snapshot verified | Exact target/options compatibility and native warm-up adoption; no measured stutter reduction; contribution ingestion remains disabled |
| Automatic updates | Sparkle shell packaging and a separate signed runtime-source update path have local tests, including rejection and diagnostic rollback | Actual full-v28 game update/relaunch/rollback, production feeds, Developer ID signing and notarization |
| Public distribution | Reviewed source, documentation, static website and source-only launcher CI artifacts | Stable signed/notarized app release; game content and compiled shader packs are private |

## Guided setup preview

The launcher now opens a compact first-run setup flow for new users, opens Home directly for configured games, and places game management in Settings. Missing games retain their connection for recovery. Draft selections persist locally; replacement connections are verified and saved before activation. Home prioritizes Play, session information and saves.

The setup batch passed 42 native tests, a release build, strict signature verification and review. Returning-user navigation, the management sheet and cancellation were inspected in the native app. Clean-Mac full game import and bundled preparation tools remain pending; this source preview still requires Xcode and Python 3.14. See the [setup review](.cairn/features/2026-11-16-guided-setup/REVIEW.md).

## Preparation identity and counts

The private game uses renderer source `4b25230a95097a44ad509f96e75c467e6b534de8` and packaging/accounting source `d8db59078a42e03c3f48a6b907895d601714936f`. Its final signed executable SHA-256 is `62924a157332b6ef554bbbba29b7a7be73ee005178f364c1185a72a9fbea0e5c`; full preparation receipt SHA-256 is `62bf2df573af4055c4c56f61f049ce421db20abdfa37b6b9f871e50152f75f85`. The launcher is a separate artifact.

Translation requests, compiled libraries, recipe rows and completed pipeline preparation are different measurements. The **50,376-row source metadata list is not a compiled-shader count**. The earlier mode-none v28 package warmed only 1,861 libraries and 1,920 pipelines; it is not the accepted full-preparation package. Old v23 caches retain their original compatibility identity.

## Public metadata library

[Open the catalog](https://catalog.christianfurr.dev) · [Protocol endpoint](https://catalog.christianfurr.dev/v1/protocol) · [Integration and pinned public key](docs/catalog/integration.md)

The published v28 dataset contains 24,361 render, 4,512 shader-variant, 623 compute, 104 tile-read and 196 mesh records. It is signed reference metadata: compiler identity is qualified, target/options remain unqualified. The app keeps downloads separate from native game caches and does not use this dataset as an exact warm-up list. Compiled shaders, game assets, player saves and private logs are not hosted.

## Evidence and next gates

- [Connected app review](.cairn/features/2026-11-16-connected-app/REVIEW.md): exact source and tested app/service boundaries.
- [Build guide](BUILDING.md): owned inputs and explicit full-preparation settings.
- [Performance method](docs/performance.md): matching hardware, settings, routes and cache state; older v23 measurements remain historical.
- [Shell releases](release/README.md), [runtime source updates](release/runtime-updates.md) and [integration acceptance](docs/integration-acceptance.md): remaining delivery and gameplay gates.

Existing screenshots retain their original capture dates. The website HUD uses illustrative values. Keep game assets, extracted shaders, saves, private logs and credentials out of public reports.

## MCP preview packaging

The source/MCP preview includes the default observation server and a separate, unregistered disposable-development workbench. 84 locked MCP tests passed on macOS, including native process verification. Default development workspaces use a separate KokiriDevelopment root. Actual live development-runtime isolation/control acceptance remains gated; source availability does not authorize player control. See [preview notes](release/preview-0.1.0.md).

## Mods and Saves preview

The next experimental launcher preview adds compact Mods profiles/imports and read-only Saves while retaining Guided Setup. Ordinary mod launch requires explicit capability; existing private human previews remain library-only. Invalid private bindings fail closed for saves, reveals and catalog state. Runtime/gameplay compatibility and normal private-bound launch are separate acceptance gates. See [Preview 3 notes](release/preview-0.1.0-3.md).
