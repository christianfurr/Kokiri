# Native Mac and observation acceptance

Run `KOKIRI_BUILD_JOBS=1 bash macos/test.sh` for native core and profile-import regressions. Run the locked MCP suite from `tools/kokiri-mcp` using `uv run --locked python -m unittest discover -s tests -v`. These checks do not launch the game or establish performance, visual correctness or applied runtime isolation.

On 2026-11-15 the native suite passed 22 tests; the MCP suite passed 26. Native tests ran with one worker against the pinned Sparkle 2.10.0 artifact. The full command, source hashes, executable identity and test logs are retained in private integration evidence, separate from player data.

Profile import copies the complete folder, checks source/copy fingerprints, rejects symbolic-link entries and canonical source/destination nesting, and refuses existing destinations. Test fixtures prove these paths; migration of real player progress still requires integration's explicit save-lineage choice. A later modification time alone does not identify the intended current save.

Launch/import/build operations reject conflicting native operations. Launch also checks for another game after asynchronous catalog preparation. The remaining check-to-open race and NSWorkspace reuse mean a launch receipt is observation identity evidence, not proof of the effective profile, settings, cache and log destinations. Keep MCP observation-only until all isolation surfaces are acknowledged and tested by the actual runtime.

## Live checks

Integration owns the game slot and installed/released artifacts. Record exact source, executable and shader-pack identities, effective paths, cache condition, settings and session receipt before testing. Verify PID, executable and process start for every observed game. Never adopt a legacy process using only its PID or interrupt human gameplay.

| Surface | Required observation | Current limit |
| --- | --- | --- |
| Host MCP | Discover five tools and call `sessions_list` | Earlier registered snapshot loaded; candidate source requires integration adoption/reload |
| Location | Correlated fresh position reply from verified capable game | No live reply accepted in this pass |
| Native capture | Capture exactly the verified game window, including AppKit UI | Screen Recording permission and reserved-output overwrite unverified |
| Startup | Capture leaf-K loading phase in the real native window, then observe dismissal into the original opening/game | Offscreen fixture and gameplay images do not prove actual startup |
| Setup/import | Complete verified copy from selected current progress; source hashes unchanged | Real save-lineage selection remains integration-owned |
| Icons | Inspect product and private game app icons at native sizes | Resource/source presence alone is insufficient |
| Settings/HUD | Change detail, corner and scale; restart and verify persistence | Source and file round-trip tests are insufficient for live layout |
| Input | Activate settings with physical L3+R3; verify held/released behavior | Synthetic input does not prove physical activation |
| Scene menus | Check settled inventory and quick-select over representative scenes | Capture after settling; preserve the reported v28 corruption improvement |

`actual-startup-with-logo.png` from earlier evidence is gameplay. Do not use it as startup proof. Retain screenshots/logs/profile data privately. Keep game assets and extracted shaders outside this source repository.

The original MCP registration's configuration-preservation comparison remains unproven because no immediate-before snapshot survived. Read-only inspection verified the documented entry, without changing configuration or restoring older backups. Current valid TOML and successful host loading cannot reconstruct the lost comparison.
