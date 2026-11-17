# Kokiri 0.1.0 Preview 3 — Mods and Saves

Experimental manual launcher preview for Apple silicon and macOS 26. It is ad-hoc signed and **not notarized by Apple**. Production automatic updates remain unconfigured. This updates the launcher only; game files, compiled shaders, private profiles and bindings are not included.

## Changes

- Dedicated Mods tab with a compact table and inspector informed by MacNative Mods: named profiles, search/filter controls, enable/order management and supported folder-based RomFS imports.
- Copy compatible Ocarina of Time packs/profiles from MacNative Mods into Kokiri's independent library. Foreign files and applied state stay unchanged. Import keeps Kokiri's active profile selected.
- Supported ordinary runtimes prepare validated session-owned overlays for the next launch. Explicit `KokiriRomFSModsVersion=1` capability is required; unsupported runtimes fail visibly. The existing private human preview supports library/profile organization only and continues to launch without mods.
- Read-only Saves tab with a compact slot list, embedded previews and decoded details. Inventory and technical file sections expand on demand. No save editing, restore, migration or deletion.
- Missing, invalid or changed private bindings show an unavailable profile. They never fall back to ordinary saves or consent/catalog state.
- Retains Preview 2's guided first-run setup, Settings game management and missing-game recovery.

## Install and limitations

Download the launcher ZIP, extract it and move `Kokiri.app` to Applications. If macOS blocks the unnotarized download, review Apple's per-app guidance: https://support.apple.com/en-us/102445. SHA256SUMS verifies archive bytes; it is not an Apple trust signature. A clean second-Mac downloaded/quarantined launch is not certified.

Connect a compatible existing game or follow [BUILDING.md](../BUILDING.md). Preparing a new game still needs the source checkout, full Xcode/Metal toolchain, Python 3.14 and your own supported game dump/firmware fonts. These inputs are not distributed.

Folder-based RomFS packs are supported; archive imports, code patches, cheats and declared dependency packs are rejected. Source/fixture tests and UI smoke do not certify modded gameplay or visual compatibility of a real pack. Existing private-bound LaunchServices startup has a separate unresolved access gate observed on this development Mac; direct developer-launch UI evidence does not prove that route works. No game runtime or player data is replaced by this release.

The MCP package retains the default observation-only server and separate gated disposable-development source. Source availability does not authorize control of human gameplay. Wider performance, memory, visuals, runtime update/relaunch/rollback and stable distribution acceptance remain open.
