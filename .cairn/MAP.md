---
verified_at_sha: 5bb5ccc
verified_at: 2026-11-17
---
# Kokiri

Independent Mac project. [STATUS.md](../STATUS.md) is the dated public acceptance summary; [BUILDING.md](../BUILDING.md) covers current build/import entry points. The map's documentation and publication routes were checked against the source revision above; acceptance requirements are not completion claims.

- `.cairn/features/2026-11-15-kokiri-foundation/PRD.md`: accepted project scope and verification gates.
- `.cairn/DECISIONS.md`: product/runtime boundaries and attribution decisions.
- `docs/integration-acceptance.md`: specialist boundaries, preservation, full-v28 evidence, matched gameplay gates and integration/release requirements; these are requirements, not completed acceptance.
- `.cairn/features/2026-11-15-agent-workbench/PRD.md` and `docs/development-workbench.md`: disposable agent sessions, credited transactional save editing and typed development controls; actual packaged-runtime isolation and host adoption remain acceptance gates.
- `.cairn/features/2026-11-16-mods-saves/`: dedicated Mods profiles/imports and read-only Saves viewer; ordinary overlay launch requires an explicit compatible runtime. Existing private preview remains library-only for mods.
- `docs/human-preview.md`: private human-owned runtime entry and clean external spawn; compiled source and real packaged isolation are separate acceptance gates. The renderer stays `Contents/MacOS/KokiriGame`.
- `LICENSE`: MIT terms preserving upstream copyright.
- `engine/`: pinned public native runtime, reviewed ownership/mesh/NS2 transfer fixes, standalone build entry. External source-built shader tools use serviced NativeAOT 10.0.14; copied-profile gameplay verification is in progress.
- `engine/docs/kokiri-startup.md`: original logo startup presentation, real phase/readiness rules and offscreen native view validation.
- `.cairn/features/2026-11-16-guided-setup/FLOW.md` and `REVIEW.md`: first-run setup, Settings game management, persisted drafts and unavailable-game recovery; native checks and remaining clean-Mac import boundary.
- `macos/`: SwiftUI Home, Mods loadouts, read-only Saves, profile-aware Play/Settings, preparation counts, public Shader Library and measured session reader with Sparkle updater. `macos/README.md` documents capabilities and configuration. Dated Home/Performance captures and provenance are in `assets/readme/`.
- `services/catalog/`: exact-context metadata protocol, Worker/D1 and selfhost service, bounded quarantine, offline snapshot review and guarded signed revision publication. `docs/catalog/contributions.md` gives operator commands; public ingress remains disabled until live acceptance.
- `assets/brand/`: original Kokiri logo and generation provenance.
- `website/`: buildless GitHub Pages site with an interactive, sample-data HUD preview; asset provenance and local preview instructions live alongside it. `.github/workflows/pages.yml` publishes only this folder.
- `release/`: signed shell archive/appcast/delta preparation and a separate signed runtime-source updater. Local fixture/diagnostic tests do not establish actual game update/relaunch/rollback or production delivery; each route documents its remaining gates.
- `docs/README.md`: build and release navigation. `docs/catalog/local-preparation.md` covers offline signed recipe export into existing local `--shader-list` preparation. Native downloads recover verified cache indexes during outages; exact runtime compatibility and gameplay adoption remain separate gates.
- `scripts/check_publication.py` and `tests/test_publication.py`: prospective/staged source boundary and exact reviewed image/metadata pins. Source-only publication excludes generated game payloads and private player data.

The independent public repository is https://github.com/christianfurr/Kokiri. Game-derived code, shader binaries and user data belong outside this source repository. Integration owns accepted source integration, installation/releases and exclusive gameplay/GPU scheduling. Use separate worktrees and owned output paths; preserve shared uncommitted MCP and website work.

Catalog offline work: `.cairn/features/2026-11-17-catalog-play-ready/` records scope, verification and the unavailable-host gates.
