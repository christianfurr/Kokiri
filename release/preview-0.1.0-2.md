# Kokiri 0.1.0 Preview 2

Experimental launcher preview for Apple silicon and macOS 26. The downloadable launcher is ad-hoc signed and **not notarized by Apple**. It is a manual-install preview; production automatic updates remain unconfigured.

## Install

Download `Kokiri-0.1.0-preview.2-macOS-arm64.zip`, extract it and move `Kokiri.app` to Applications. This installs the launcher only. An existing compatible native game app can be connected immediately. Preparing a new game still requires the Kokiri source checkout, full Xcode with its Metal toolchain, Python 3.14, your supported game dump and extracted firmware fonts. Bundled preparation tools are not included.

macOS may block the first launch because the developer cannot be verified. If you choose to trust this download, Apple documents the per-app **System Settings > Privacy & Security > Open Anyway** flow: https://support.apple.com/en-us/102445. This preview has no Apple notarization ticket. A clean second-Mac downloaded/quarantined launch has not been verified. SHA256SUMS identifies the published archive; it is not an Apple trust signature.

## Changes

- First-run setup guides game selection, extracted firmware fonts and preparation in a compact window without the main sidebar.
- Configured users go directly to Home. Game management is in Settings; the permanent Setup tab is removed.
- Home emphasizes Play, recent session information and saves.
- Setup choices persist locally and are revalidated on reopen. Preparation uses observed stages and optional logs.
- Missing games keep their saved connection and offer Locate Game/Try Again recovery.
- Replacement connections require inspection and successful preference persistence. Existing output apps and overlapping source/input/preparation/output locations are rejected.

## Verification and limits

42 native tests passed, along with a release build, strict deep signature verification, publication scans and independent review. Native returning-user navigation, management entry, welcome/game selection and cancellation were inspected. Full clean-Mac import, complete gameplay coverage and production update/relaunch remain unverified.

No game files, firmware fonts, compiled game shaders, saves or private bindings are included. Game preparation uses your own inputs and still runs locally. This release changes the launcher; it does not replace an existing private game app or its caches.
