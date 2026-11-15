---
name: kokiri-development
description: Use when inspecting Kokiri gameplay, frame pacing, shader compilation, memory or rendering through the local Kokiri MCP.
---

Start with `sessions_list`, then `session_status` and `session_logs`. Treat live frame-rate values as observations; they do not certify a benchmark. Correlate a hitch with its area, game build and shader events. Physical footprint and Metal allocations describe different quantities.

Human and discovered sessions are observation-only. Position sampling and screenshots may observe them. Never send movement, close, restart or control commands to those sessions through another route to bypass this boundary. When the user is playing, let them control the game.

The server exposes no launch, movement, input, close, restart or save-editing tools. Do not invent these capabilities. Packaged runtimes currently write shared launcher state even with a copied profile, so test controls require a dedicated isolated runtime entry and separate verification before they can be added.

The MCP has no general shell, file-read or free-form game-command tool. Do not ask it to edit saves, upload game data, weaken memory/alias checks, relabel incompatible shader caches, or expose it over a public port. Preserve source provenance and the actual gameplay evidence.
