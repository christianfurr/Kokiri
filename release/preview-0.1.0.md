# Kokiri 0.1.0 Preview 1

Source and MCP development preview for Apple silicon Macs. This is not a stable release or a signed/notarized application download. Build the launcher and game separately using BUILDING.md and your own supported game files. No game content, compiled shader binaries, player profiles or private bindings are distributed.

## Included

- Connected native Home/Play, profile-aware Settings, recent-session Performance and a public Shader Library.
- Signed public metadata catalog: 29,796 reference recipes in 233 packs. These stay separate from native game caches and do not qualify as exact runtime warm-up input. Contributions remain disabled.
- A portable Kokiri MCP source package with five observation tools: sessions, status, bounded logs, location and verified game-window capture. Install uv, extract the archive and follow tools/kokiri-mcp/README.md. The default MCP entry exposes observation only.
- Separate disposable development-workbench source with registry-based setup, isolation/ownership checks and typed test tools. It stays unregistered and requires Integration acceptance and an exclusive test permit. These controls are not accepted for human gameplay.
- Development workspace defaults are separated from player data. The native process test now checks its executable against an independent C SDK probe, including uv-managed Python installations.

## Validation and limits

84 MCP tests passed on macOS using the locked SDK, including actual stdio discovery, closed test-profile/save transactions and the C process probe. Launcher implementation previously passed 35 native tests, a release build, strict signature verification and independent review. Broader matched performance/memory/visual acceptance, live disposable-runtime control acceptance and production automatic updates remain open. The user reports good gameplay from the separately prepared private v28 package; that private package is not included here.

Existing human saves, caches and uncommitted work remain preserved. Do not relabel v23 caches as v28, overwrite newer progress with an older profile, or infer that source metadata totals count compiled shaders.

The MCP archive includes a dependency lockfile and license/attribution files. uv downloads the locked SDK dependencies during setup. SHA256SUMS records the exact downloadable archive identity. GitHub also provides the complete tagged source archives. Credentials, logs and game assets belong outside public reports.
