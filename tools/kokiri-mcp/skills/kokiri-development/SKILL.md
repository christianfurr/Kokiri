---
name: kokiri-development
description: Use when inspecting Kokiri gameplay, frame pacing, shader compilation, memory or rendering, or running copied-profile development tests through the local Kokiri MCP.
---

Start with `sessions_list`, then `session_status` and `session_logs`. Treat live frame-rate values as observations; they do not certify a benchmark. Correlate a hitch with its area, game build and shader events. Physical footprint and Metal allocations describe different quantities.

Human and discovered sessions are observation-only. Position sampling and screenshots may observe them. Never send movement, close, restart or control commands to those sessions through another route to bypass this boundary. When the user is playing, let them control the game.

For automation, register a built Kokiri Game app, then use `test_launch` to create a fresh, verified copy of a closed source profile. Keep its returned lease. Only this server instance's owned test session and lease permit `test_input` or `test_close`. Use short timed inputs; the server supplies releases. A missing or stale lease is not permission to adopt another process.

The MCP has no general shell, file-read or free-form game-command tool. Do not ask it to edit saves, upload game data, weaken memory/alias checks, relabel incompatible shader caches, or expose it over a public port. Preserve source provenance and the actual gameplay evidence.
