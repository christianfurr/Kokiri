# Mods and Saves review

## Implemented

Dedicated Mods and Saves destinations, Home/Settings save navigation, named mod loadout profiles, copied RomFS and MacNative Mods library imports, enable/load order/conflict display, and session-owned validated overlay snapshots. Mods uses the approved compact table/inspector structure informed by MacNative Mods, with search/filter controls and profile/import menus. Saves uses a slot list beside one selected preview; inventory and file details expand on demand.

The read-only native save viewer shows the exact connected profile, discovered slots, bounded embedded screenshots, vitals, era/area, inventory and milestones. A missing, invalid, changed or removed requested private binding makes the profile unavailable. Home/Settings reveal actions, HUD settings and cache paths also fail closed; the app never substitutes the ordinary profile. An invalid preview uses an inert catalog facade without a client, queue, consent lookup or network activity.

Ordinary overlays require exact integer `KokiriRomFSModsVersion=1`. The source builder advertises this only after a successful current-source native build and a matching captured, receipt-bound, copied executable hash. Generic/shader-only packaging and private-capability packages omit it. Existing preview bindings stay library-only, with normal unmodded Play preserved.

## Verification

- `KOKIRI_BUILD_JOBS=2 bash macos/test.sh`: 62 tests passed on the combined guided-setup/Mods/Saves candidate, including 6 Mods, 10 Saves, 3 private-profile resolution regressions and an invalid-preview catalog regression. The executable target compiled as part of this check.
- `/opt/homebrew/bin/python3.14 -I -m unittest discover -s engine/tests -p test_standalone_build.py`: 30 tests passed, including provenance-bound ordinary marker, stale hash refusal and private/generic omission.
- Independent source review found no remaining P1/P2 issues. Corrected findings cover NUL-inclusive runtime-index names, macOS canonical paths, inner-folder dependency bypass, selected foreign profile snapshots, bounded JPEG decoding, stale-refresh cancellation and private-profile fallback on invalid binding.
- The existing copied library and private save slots were inspected in the native app. A populated-browser sizing issue was corrected by bounding Mods to the available window size with independently scrolling panes. Final release packaging/signature and corrected-window evidence are recorded against the clean combined source commit.

## Limits and waivers

- The accepted private runtime explicitly disables mods. This change does not enable or rebuild it, mutate its binding or apply a profile to it. A future runtime change needs separate isolation/compatibility verification.
- Folder-based RomFS mods are supported. Archive import, code patches, cheats and declared dependency packs are rejected with visible messages.
- Synthetic fixtures prove decoding and overlay construction, not modded gameplay or visual compatibility of a real pack. No game launch, installation or release is part of this source verification.
- Public unbound normal launch and private-bound launch are separate checks. A successful developer-spawn private UI does not establish normal LaunchServices access to a protected private data folder; macOS access prompts remain an installation acceptance boundary.
- No save editing, restoration, migration, deletion or older-profile fallback is included. Save reads and source-library imports never write their inputs.
