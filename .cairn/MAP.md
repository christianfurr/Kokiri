---
verified_at_sha: null
verified_at: 2026-11-15
---
# Kokiri

New independent repository. Source integration and product verification are in progress.

- `.cairn/features/2026-11-15-kokiri-foundation/PRD.md`: accepted project scope and verification gates.
- `.cairn/DECISIONS.md`: product/runtime boundaries and attribution decisions.
- `LICENSE`: MIT terms preserving upstream copyright.
- `engine/`: pinned public native runtime, reviewed ownership/mesh/NS2 transfer fixes, standalone build entry. External source-built shader tools use serviced NativeAOT 10.0.14; copied-profile gameplay verification is in progress.
- `macos/`: SwiftUI product UI, local profile import/launch, measured session reader and Sparkle updater. Real Home/Performance captures are in `assets/readme/`; current source has passed the existing 12 core tests.
- `services/catalog/`: open exact-context metadata protocol, Worker/D1 service, quarantine/signing, queue SDK and local tests.
- `assets/brand/`: original Kokiri logo and generation provenance.
- `release/`: signed shell archive/appcast/delta preparation; 20 checks include actual delta reconstruction and tamper rejection. Production signing/hosting remains unavailable.
- `docs/`: build, adapter, privacy and measured-performance documentation. Catalog hosting and native warm-plan adoption remain acceptance work.

The public remote is https://github.com/christianfurr/Kokiri and currently empty. Game-derived code, shader binaries and user data belong outside this source repository. Root owns integration, runtime HUD and exclusive gameplay/GPU testing. Agents own engine build/provenance, native product UI and catalog implementation respectively.
