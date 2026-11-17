# Project status

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
