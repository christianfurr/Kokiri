# Private human preview

The preview uses the same bare `Contents/MacOS/KokiriGame` renderer as the normal app. Its compiled `--kokiri-preview <private-root>` entry starts with human ownership and private application data. It has no agent lease, idle timeout, shutdown timer, movement, save editor or automatic close. The separate development MCP remains unregistered until real isolation acceptance.

Integration owns packaging, preparation, installation and the exclusive launch grant. Source fixtures do not establish packaged runtime isolation, startup appearance, controller behavior or rendering acceptance.

## Preparation contract

Integrate all native changes before the final raw build. Record the exact pre-sign renderer hash in preparation evidence, then record the final signed main hash separately. The preview does not introduce another embedded renderer or wrapper executable. Do not add a capability marker to an older binary.

The private app keeps bundle ID `com.christianfurr.kokiri.runtime`, `CFBundleExecutable=KokiriGame`, and integer `KokiriHumanPreviewVersion=1`. A marked app refuses the ordinary shared-player launch path. `--check` remains a read-only package check. The normal Kokiri installation is unchanged.

Provision an existing canonical, same-user directory with mode 0700 outside the app and the shared Kokiri/MacNativeGames support and log trees. Integration must capture a fresh, fully stopped source profile and preserve its source hashes and lineage before making an independent private copy. Preserve the complete compatible cache and explicit PSO file; do not substitute source-row counts, old v23 caches or partial preparation for v28 readiness.

Place this bounded metadata in `preview.json` inside the private directory:

```json
{
  "schema": 1,
  "kind": "human-preview",
  "owner": "user",
  "session_id": "<32 lowercase hex characters>",
  "executable_sha256": "<64 lowercase hex characters of the final signed main>"
}
```

No nonce, expiry, agent request, lease, ownership or revocation file is accepted. The private directory holds `profile/`, `cache/`, `settings/game/`, `proof/`, `logs/`, `contributions/`, `captures/`, `tmp/`, and observation metadata. The explicit user PSO is `profile/pso_user.tsv`. Existing private progress survives a later human relaunch. One process holds a directory lock until exit, preventing two preview launches from sharing it.

## Launch contract

After Integration grants the actual launch, invoke the source helper with `--app <private-app>` and `--private-root <private-directory>` using `engine/scripts/dev/human_preview.py`. The helper verifies the marker, request, final executable hash and private log. It creates a new process session with a clean environment before native constructors can consume inherited diagnostic input. It returns the starting PID without waiting, controlling, adopting or closing the game. Direct execution from an arbitrary inherited shell environment is outside this supported boundary.

The native entry validates paths again, configures private settings/cache/log/proof/PSO destinations and sets `TOTK_SLOT_OWNER=user` before acquiring the shared game slot. The shared slot remains the sole intentional shared coordination state. Leaderboard, contribution upload, cloud save, inherited mods, autoload and diagnostic workers stay disabled. Apple's OS-managed caches remain outside this application-managed isolation boundary.

A newly built runtime may advertise exact integer `KokiriHumanPreviewModsVersion=1`, separately from ordinary RomFS mod support. The launcher copies a nonempty profile to `mods/<launch-id>/mods` and pins `handoff.json` to the human session, signed executable and manifest. The helper accepts only `--mods-session <32-lowercase-hex>` plus `--mods-sha256 <64-lowercase-hex>`; it never accepts an arbitrary overlay directory or inherited mod environment. The native entry independently checks those bytes, preserves a no-follow directory descriptor and rechecks private file identity across reads. Missing, linked, mutated, stale or incompatible snapshots fail visibly. Original game-file hashes remain checked by the normal RomFS loader. Empty profiles pass neither option and keep mods explicitly disabled, including on older runtimes. This source capability requires a separately validated candidate; it does not upgrade an existing installed game.

`session.json` binds the PID, process start, actual executable hash and effective paths. `isolation.json` starts at `configured` and changes to `slot-acquired` only after the game slot succeeds. Preview authorization for agent controls remains false permanently. Position observations and UUID-named captures are the only accepted input-file requests. Captures and logs stay under the private directory; the screenshot-folder chooser cannot redirect them. Ordinary human window close continues to work; agent-close calls are refused even before physical input.

## Live acceptance still required

- Inspect the real packaged acknowledgements and process identity, then compare shared settings/profile/cache/log/proof/contribution state against an immediate-before snapshot. Exercise private settings and save persistence, native window captures and live position replies.
- Capture actual branded startup from the verified native window. Gameplay is not startup evidence. Check settled inventory and quick-select overlays, scene-backed custom settings, HUD persistence and physical L3+R3.
- Keep human ownership across updater candidate and rollback launches using this clean entry. Bind both actual main identities separately, preserve progress lineages, and never use a plain updater relaunch that falls back to shared defaults.
- Schedule representative walking/camera and repeated-transition performance checks separately. Source/SDK checks cannot certify frame pacing, physical-memory savings, visual correctness or full shader preparation.
