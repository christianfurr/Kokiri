# Kokiri Development MCP

A local stdio server for inspecting Kokiri. It uses the official Python MCP SDK, locked to **2.3.0**. It opens no network listener and requires no account, hosted service or upload.

This page describes the default observation server, `server.py`. The separate, unregistered `development_server.py` adds disposable development sessions and typed editing tools. Its setup, ownership rules and pending live acceptance are documented in [Disposable agent development](../../docs/development-workbench.md).

| Tool | Result | Local writes |
| --- | --- | --- |
| `sessions_list` | Up to 128 recorded sessions and verified running identity | None |
| `session_status` | Physical footprint, RSS, recent frame times, game presents and last location | None |
| `session_logs` | Last 1–200 lines from a fixed log kind, at most 256 KiB | None |
| `session_location` | Fresh area and player coordinates, without moving the player | Diagnostic request and runtime reply |
| `session_screenshot` | One verified game window or runtime frame | Private PNG; raw frame also sends a diagnostic request |

All sessions exposed by `server.py` are observation-only. It has no launch, movement, input, close, restart, save-editing, general shell or arbitrary file-read tools. Location and screenshots have `readOnlyHint: false` because they write diagnostic files, even though they do not control the player.

`window` screenshots include the native startup screen, HUD and settings. `game_frame` captures the runtime image and can omit AppKit UI. Native capture uses one visible layer-zero window belonging to the verified process; it never falls back to a desktop screenshot. macOS may require Screen Recording permission.

## Run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from this directory:

```sh
uv sync --locked
uv run --locked python server.py
```

The server owns stdout for MCP; do not wrap it with commands that print startup text. It discovers sessions in `~/Library/Application Support/Kokiri/Sessions`. To include one other recorded-session directory, pass `--observe-root /absolute/session/directory`. This does not grant control or imply that its process is valid.

Register with Codex from this directory using its supported CLI:

```sh
codex mcp add kokiri -- uv run --locked --directory "$PWD" python "$PWD/server.py"
codex mcp get kokiri --json
```

Use `codex mcp list --json` to check configuration. A configured entry alone does not establish that this chat has loaded its tools; reload the MCP connection when needed and verify discovery plus `sessions_list` in the host. Remove only this entry with `codex mcp remove kokiri`. Preserve other MCP entries.

`plugin.json`, `mcp.json` and the bundled development skill form an optional local plugin package. `${PLUGIN_ROOT}` resolves to this directory in plugin-aware hosts. This directory is not an account plugin or a public submission.

## Boundaries and measurements

Live access requires **PID, full executable path and libproc process-start identity** to match `session.json`. If a receipt supplies a process UUID, it must also match. Older receipts without a start identity can still supply bounded recorded logs; the server never infers or adopts a live process from a PID alone. Location and raw frame requests additionally require the runtime's declared Kokiri live-status capability.

Metadata reads are capped at 64 KiB, each log tail at 256 KiB, and screenshots at 8 MiB. A session can retain at most 64 captures under `~/Library/Application Support/Kokiri/Development/Captures`. Reads reject symlinks and traversal through managed paths. Captures wait for complete PNG chunks with matching checksums before returning an image.

Frame rates describe the bounded recent presented-frame tail. Generated and duplicate timestamps are excluded; these observations do not certify a gameplay benchmark. Physical footprint is macOS process accounting, distinct from Metal allocation totals. Last-recorded location can be stale; `session_location` requests a new sample at most once per five seconds.

The existing packaged runtime enters its normal launcher even with explicit boot arguments, which writes shared log, proof and settings state despite a copied profile. New source adds a dedicated isolated entry, verified independent profile copies, pinned binary identity and per-process control leases. A fresh runtime build and live isolation acceptance are required before enabling the separate development server. Do not bypass this boundary through other tools while the user plays.

## Verification

```sh
uv run --locked python -m unittest discover -s tests -v
```

Tests use closed synthetic sessions and mocked window capture. They exercise real official SDK client/server stdio discovery, resource reads and harmless calls in both modern and legacy-handshake modes. On macOS, a small C probe verifies ctypes process-start and physical-footprint fields against the installed SDK layout using the test Python process. No game or GPU test is launched.

The 2026-11-15 continuation passed 28 tests, including FIFO rejection, cross-process pending-capture accounting, identity pinning across observations and legacy-log separation. The registered earlier snapshot loaded its five tools in Codex and `sessions_list` returned no sessions. That host check does not prove this candidate has replaced the registered source.

The disposable-workbench continuation passed **59 tests in 4.831 seconds**: 28 default observation, 18 development unit, 2 development SDK stdio and 11 transactional-save tests. Separate native CPU runs passed 19 tests, including actual typed-input/bridge negative controls and cross-process takeover guards. Actual `input.c` and `launcher.m` syntax checks passed. These checks launched no game, game window, Metal or audio. The development server remains unregistered; full runtime linking and live isolation, controller, visual and save-load acceptance remain pending. `verification.json` records the tested source identities.

Actual gameplay position responses and native game-window capture permission still need a live observation check. Native capture now reserves an empty private PNG before starting; actual `screencapture` overwrite behavior remains part of that live check. The package does not claim these were verified by fixture tests. See `../../docs/native-acceptance.md` for the product acceptance gates.

Primary references: [official Python SDK](https://github.com/modelcontextprotocol/python-sdk), [SDK stdio guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md), [MCP tool annotations](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations), and [Codex MCP configuration](https://developers.openai.com/codex/mcp/).
