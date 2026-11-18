# Kokiri 0.1.0 Preview 4 — private-runtime mod launching

Experimental manual launcher preview for Apple silicon and macOS 26. The launcher is ad-hoc signed and **not notarized by Apple**. Production automatic updates remain unconfigured. Downloads contain the launcher and optional MCP source, never game files, private bindings, compiled shaders or saves.

## Changes

- Compatible human-preview runtimes can load the selected RomFS mod profile through a copied, hash-validated launch snapshot. The launcher, helper and native entry independently verify its identity and files.
- The new runtime advertises `KokiriHumanPreviewModsVersion=1`. An older runtime still launches an empty profile unmodded; enabled mods require a compatible runtime update. Updating the launcher alone does not update your game runtime.
- Empty profiles retain the existing unmodded launch path. MacNative Mods imports remain independent copies; foreign applied state and saves are not changed.
- Cached preparation can be verified against a newly built runtime without automatic shader translation or library compilation. Missing or incompatible inputs stop validation.

## Verified scope

Source `037e49d2445baf8529dda389d216564b72b9850d` passed 65 Swift tests, 128 focused CPU checks and independent source review. The separate local game build completed fresh cached-request validation, reused 42,466 unchanged compiled libraries, and verified all 28,786 pipeline rows including 196 mesh rows with zero JIT attempts, archive misses or writes.

Two copied-profile gameplay runs reached Death Mountain Trail and the Basic Controls screen. The unmodded run showed Nintendo prompts; the modded run showed PlayStation controller artwork and button symbols. Native logs confirmed the two hash-validated replacements. Both games exited normally and original player/library files were unchanged. This verifies that pack and the production Core/helper/runtime handoff on the development Mac. It does not certify all mods, a second Mac, or the launcher Mods-tab-to-Play flow end to end.

## Install and limits

Download the launcher ZIP, extract it and move `Kokiri.app` to Applications. Review [Apple's per-app guidance](https://support.apple.com/en-us/102445) if macOS blocks the unnotarized download. SHA256SUMS verifies archive bytes; it is not an Apple trust signature. Connect a compatible game or follow [BUILDING.md](../BUILDING.md) using your own supported dump and firmware fonts. The full Xcode/Metal toolchain and Python 3.14 remain required for source preparation.

Supported mods are folder-based RomFS replacements. Archive imports, code patches, cheats and dependency packs remain unsupported. Broader performance, memory, visual and physical-controller qualification remain open. This is an experimental preview, not a stable signed/notarized release. No production updater is enabled.
