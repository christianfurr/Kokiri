---
verified_at_sha: null
verified_at: 2026-11-15
---
# Kokiri

New independent repository. Source integration and product verification are in progress.

- `.cairn/features/2026-11-15-kokiri-foundation/PRD.md`: accepted project scope and verification gates.
- `.cairn/DECISIONS.md`: product/runtime boundaries and attribution decisions.
- `docs/integration-acceptance.md`: specialist boundaries, preservation, full-v28 evidence, matched gameplay gates and integration/release requirements; these are requirements, not completed acceptance.
- `.cairn/features/2026-11-15-agent-workbench/PRD.md` and `docs/development-workbench.md`: disposable agent sessions, credited transactional save editing and typed development controls; actual packaged-runtime isolation and host adoption remain acceptance gates.
- `docs/human-preview.md`: private human-owned runtime entry and clean external spawn; compiled source and real packaged isolation are separate acceptance gates. The renderer stays `Contents/MacOS/KokiriGame`.
- `LICENSE`: MIT terms preserving upstream copyright.
- `engine/`: pinned public native runtime, reviewed ownership/mesh/NS2 transfer fixes, standalone build entry. External source-built shader tools use serviced NativeAOT 10.0.14; copied-profile gameplay verification is in progress.
- `engine/docs/kokiri-startup.md`: original logo startup presentation, real phase/readiness rules and offscreen native view validation.
- `macos/`: SwiftUI Home, profile-aware Play/Settings, local preparation and public Shader Library, measured session reader and Sparkle updater. `KokiriCore/ShaderLibrary.swift` reads bound preparation receipts and full metadata lists; reference downloads remain separate from exact runtime warm-up.
- `services/catalog/`: open exact-context metadata protocol, Worker/D1 service, quarantine/signing, queue SDK and local tests.
- `assets/brand/`: original Kokiri logo and generation provenance.
- `website/`: buildless GitHub Pages site with an interactive, sample-data HUD preview; asset provenance and local preview instructions live alongside it. `.github/workflows/pages.yml` publishes only this folder.
- `release/`: signed shell archive/appcast/delta preparation; 20 checks include actual delta reconstruction and tamper rejection. Production signing/hosting remains unavailable.
- `docs/`: build, adapter, privacy and measured-performance documentation. Catalog hosting and native warm-plan adoption remain acceptance work.

The independent public repository is https://github.com/christianfurr/Kokiri. Initial source commit `bb8c3e4` is published on `feat/kokiri-foundation`; all three CI jobs passed on 2026-11-15. Game-derived code, shader binaries and user data belong outside this source repository. Root owns integration, runtime HUD and exclusive gameplay/GPU testing. Catalog runtime integration continues in a follow-up change.
