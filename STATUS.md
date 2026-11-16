# Project status

Updated **2026-11-16**. Source reviewed at [`4b25230`](https://github.com/christianfurr/Kokiri/commit/4b25230a95097a44ad509f96e75c467e6b534de8). This page records reviewed milestones; a passing source check does not establish gameplay or distribution acceptance.

**Kokiri is a development preview. Full v28 preparation remains incomplete, and there is no accepted playable package from the current full-v28 build.** Severe FPS drops, compilation hitches and high memory use remain unresolved. The latest v28 user playtest reported no rendering corruption; broader visual checks remain open.

| Area | Implemented or observed | Remaining acceptance |
| --- | --- | --- |
| Native Mac app | SwiftUI launcher, copied-profile import, settings and session viewer; dated [actual app captures](assets/readme/PROVENANCE.md) | Current packaged flow and physical-controller shortcut checks |
| v28 preparation | 107 translation batches completed; 42,848 default translation requests and 8,553 listed requests; 41,407 initial Metal libraries compiled with 0 failures in that stage | Final pipeline archives, complete output-bound preparation proof and a packaged runtime |
| Gameplay | Latest v28 human playtest reported no corruption; human accepted the audio change | Matched first/repeat routes, area transitions, broader visual correctness, FPS/hitch and physical-memory measurements |
| Shared catalog | Public protocol endpoint responds; metadata validation, signing and local client tests exist | Published dataset, exact target/options compatibility and verified native warm-up adoption; no measured stutter reduction |
| Automatic updates | Sparkle shell packaging and a separate signed runtime-source update path have local tests, including rejection and diagnostic rollback | Actual full-v28 game update/relaunch/rollback, production feeds, Developer ID signing and notarization |
| Public distribution | Reviewed source, documentation and static website | Stable signed/notarized app release |

## Reading preparation counts

Translation requests, compiled Metal libraries, pipeline records and successful archive creation are different measurements. The stage counts above do not add up to a build percentage or certify the final package. The **50,376-row source metadata list is not a compiled-shader count**.

The earlier v28 package used `OOT_SHADERS=none` and warmed only 1,861 libraries and 1,920 pipelines. It did not complete full preparation. Old v23 caches cannot become compatible v28 caches through renaming; retain their original compatibility identities.

## Evidence and next gates

- [Build guide](BUILDING.md): current entry points, owned inputs and explicit full-preparation settings.
- [Performance method](docs/performance.md): matching source, hardware, settings, route and cache state; older v23 measurements keep their historical labels.
- [Catalog integration](docs/catalog/integration.md): compatibility and native adoption boundaries. A responding protocol endpoint does not establish a populated library.
- [Shell release tooling](release/README.md) and [runtime source updates](release/runtime-updates.md): local checks and production prerequisites.
- [Integration acceptance](docs/integration-acceptance.md): requirements for accepting a candidate.

Maintainers update this page after reviewed milestones. Screenshots retain their capture dates, and the website HUD uses illustrative values. Keep game assets, extracted shaders, saves, private logs and credentials out of public reports.
