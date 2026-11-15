# Kokiri MCP handoff — 2026-11-15

## Native/MCP continuation

The original freeze record below is historical. The default `server.py` remains observation-only, with28 fixture tests observed in the continuation. The earlier registered snapshot loaded five tools in Codex and returned no sessions; candidate adoption/reload and actual game location/window capture remain pending.

The user subsequently authorized disposable agent development. Separate, unregistered `development_server.py` and the credited `save_workshop/` implement typed test-session controls, transactional save editing and repeatable scenarios. See [the workbench guide](../../docs/development-workbench.md) and its acceptance requirements. New runtime source provides the dedicated isolation entry and human-takeover gates. Actual compilation, packaged-runtime isolation and host adoption must be verified separately; do not advertise old binaries as capable by adding metadata.

The isolated worktree preserves the original shared MCP work and configuration. The historical configuration-preservation comparison remains unprovable without its lost immediate-before snapshot; no stale backup was restored. Integration owns adoption, installation and exclusive runtime test grants.

Observed continuation results: 59 MCP tests passed in 4.831 seconds; 19 native CPU tests and actual `input.c`/`launcher.m` syntax checks passed across bounded exclusive grants. The real SDK flow creates a copied fixture, snapshots/plans/applies/restores a generated save and proves the source fixture unchanged. Native fixtures include intended-failing lease, physical-input, read-only and expiry controls. All owned test groups were verified gone. These results do not establish actual game launch, physical L3+R3, startup or settled menu acceptance. Default host registration was not changed; the development server was not registered.

## Original freeze record

Engineering stopped when the parent relayed the user's request to divide remaining work into new chats. No game is assumed active; the former human PID 91969 was confirmed gone.

## Completed

- Local stdio server in `server.py` and bounded observation implementation in `kokiri.py`.
- Five tools: `sessions_list`, `session_status`, `session_logs`, `session_location`, `session_screenshot`. All sessions remain observation-only. No launch, movement, input, close, restart or save-editing tools exist.
- Exact PID, executable and process-start checks; optional receipt UUID check; libproc footprint/RSS; bounded logs/frame observations; native verified-window and separate runtime-frame capture paths; complete PNG/chunk checksum validation.
- Official `mcp==2.3.0` with `uv.lock`, portable `plugin.json`/`mcp.json`, development skill, README and fixture verification receipt.
- No engine/native UI files edited, game launched, gameplay input sent, screenshot taken, account plugin created or public service started.

## Verification

`uv run --locked python -m unittest discover -s tests -v` passed **20 tests** in **1.480 seconds** on this Mac. This includes actual official SDK client/server stdio discovery and harmless calls with negotiated protocols **2026-07-28** and **2025-11-25**, plus a C SDK versus ctypes check of the test Python process's libproc layout. `uv lock --check` and Python compilation passed.

Live gameplay location responses and native game-window screenshot acceptance remain unverified. Fixture tests do not certify gameplay performance or shader coverage. `verification.json` records the tested source hashes and limitations.

## Local configuration timing issue

Immediately before the freeze message arrived, the previously authorized supported CLI command registered an enabled stdio MCP entry named `kokiri`. `codex mcp get kokiri --json` confirmed it points to this package through `/Users/christianfurr/.local/bin/uv`. Its default discovery root is Kokiri's normal `Sessions` directory; no private observation root was registered.

The CLI operation's before/after semantic-preservation check unexpectedly returned false. Both reads used `/Users/christianfurr/.codex/config.toml`. No manual restoration or follow-up configuration edit was attempted. The comparison's before snapshot was held only in memory, so the exact additional semantic difference and preservation of preexisting settings are unverified. The only known new key is `mcp_servers.kokiri` (table), containing `command` (string) and `args` (six-element list). A read-only follow-up found no nonfinite TOML numbers that could explain dictionary inequality. Only two old local config backups were found, both dated 2026-10-17; neither establishes the immediate-before state. This chat has **not** verified that the host loaded the new tools.

Exact registration argv:

```json
["codex", "mcp", "add", "kokiri", "--", "/Users/christianfurr/.local/bin/uv", "run", "--locked", "--directory", "/Users/christianfurr/Codex-assistant/apps/Kokiri/tools/kokiri-mcp", "python", "/Users/christianfurr/Codex-assistant/apps/Kokiri/tools/kokiri-mcp/server.py"]
```

## Next chat

1. Review the `kokiri` CLI entry and configuration preservation issue. Decide whether to retain it under the user's latest instructions; do not overwrite unrelated entries.
2. When a human-owned session is actually running, use its exact recorded directory and process-start identity for observation-only SDK status and native-window screenshot acceptance. Do not send gameplay input or close/restart it.
3. Verify actual host tool discovery and `sessions_list` after connection reload; a configured entry alone is insufficient.
4. Keep test controls absent until a separately verified isolated runtime entry exists. The packaged app currently runs its normal launcher even with boot arguments, writing shared logs, RomFS proof, contribution and settings state despite a copied profile.
5. Parent owns staging/commits. Only `tools/kokiri-mcp` was edited by this agent. Six earlier scaffold files were included by the parent in commit `a9d8acd`; subsequent package changes remain for coordinated review. Unrelated `website/` and docs commit `4ce74c1` were not created by this agent.
