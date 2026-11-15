# Disposable agent development

`tools/kokiri-mcp/server.py` remains the human observation server. The separate `development_server.py` implements an explicitly configured test workbench. It is not registered in the host by this source change. Integration must accept the actual packaged runtime's isolation, expiry, revocation and human-session rejection before enabling it.

## Configure once, use identifiers

Local setup uses `development_admin.py` to register a built runtime, selected source profile and typed scenario files. The MCP accepts registry IDs; it has no arbitrary file, shell, memory-write or command-forwarding tool. Registration does not launch a game or grant the exclusive benchmark slot.

```sh
python development_admin.py runtime candidate '/private/build/Kokiri Game.app'
python development_admin.py fixture child-route /private/selected-profile
python development_admin.py scenario inventory /private/inventory-scenario.json
```

Runtime registration requires `KokiriDevelopmentVersion=1` and pins executable and Info.plist hashes. Launch additionally requires the matching Integration acceptance receipt and an Integration-issued, expiring, session-specific exclusive test permit. The local registry's `permit_file` names that private receipt. Neither can be created through MCP. Do not add a capability declaration to an older binary or treat a synthetic fixture as packaged runtime acceptance.

## Ownership contract

Creating a session makes two independent verified copies of the selected complete profile: the writable test profile and a reset baseline. Source/copy hashes must agree, including empty directories. Symlinks, hardlinks, special files and source/workspace overlap are rejected. No current-save choice or migration is inferred.

The dedicated `--kokiri-development ROOT` entry bypasses the player launcher. A clean allowlisted environment is established by the parent before runtime constructors execute. Fixed destinations cover profile, settings (including the shared-settings parent), cache, logs, control/status files, RomFS proof, contributions, mods and temporary files. Cloud/catalog/board uploads, external mods/texture/UI packs and inherited diagnostic destinations are disabled. Game assets remain read-only in the bundle or its pinned game-data library.

The Makefile links the launcher into `oot-native`. The loader selects app mode from its executable's `Contents/MacOS` location; outside a bundle the same executable remains a CLI tool. Rebuild and package the actual new source before declaring development capability. Copying or relabeling an older binary does not add this entry.

`request.json` binds schema1, session UUID, secret nonce, exact executable hash and maximum expiry (at most30minutes). `lease.json` may shorten that expiry; a revoked marker permanently denies controls for that launch. `isolation.json` binds actual PID, libproc process-start identity, executable/hash, nonce and effective paths. Its initial configured phase has `game_slot_acquired:false`; only the post-acquisition loader hook can acknowledge the shared human-priority game slot. Parent and runtime both check the lease. Existing processes are never adopted.

This is application-managed data isolation, not an operating-system sandbox. The shared cross-app game slot is intentionally global. Apple's AppKit/Metal/compiler-managed caches remain OS-managed. The archive helper override confines this project's cleanup and lock paths; it does not establish where Apple's archive builder writes. Live filesystem evidence and archive-enabled parity remain acceptance requirements.

## Workflows

Once Integration has enabled the development server, an agent can use this sequence without navigating the editor UI:

1. Call `development_options`, then `development_create` with an explicitly selected runtime and fixture ID. Retain its session ID for every subsequent call.
2. While stopped, use `development_configure` and the `development_save_snapshot` → `development_save_plan` → `development_save_apply` flow. Review the returned semantic diff before applying its plan ID. Keep the snapshot ID for restoration.
3. After the session-specific exclusive permit is issued, call `development_launch`, then poll `development_status` until `isolation_accepted` is true. A starting PID alone does not authorize controls.
4. Use `development_travel` for setup and `development_button`/`development_stick` for interaction. Resolve returned request IDs with `development_reply`; queued or warping replies are incomplete. Use `development_screenshot` to check the actual native window.
5. Run `development_scenario` or a registered `development_scenario_preset` for repeated checks. Retain its run ID and private evidence. Close with `development_close`, verify exit, then call close again to mark the profile stopped before further save edits.

- Create, configure, launch, inspect and close/restart only an exactly verified owned test session. Close acknowledgement is not exit evidence. Reset retains displaced test progress and preserves the learned private cache; it does not make a warm cache cold.
- Query position, move within the current scene, travel to the supported named destinations, save/return to local markers, and issue bounded named button/stick actions. The right stick supplies camera movement. Actions expire after at most5seconds and return to neutral. A completed input requires eligible guest-poll evidence; undelivered/refused actions stop scenarios.
- Snapshot a stopped test save, request typed changes, inspect the semantic diff, then apply the returned plan ID. Restore uses snapshot identity. The credited headless editor model preserves inventory/acquisition consistency, progress/caption pairs, stale-source rejection, backup and atomic account replacement. Direct equipped-slot replacement and live inventory writes are unsupported.
- Compose1–64typed scenario steps with a total deadline budget at most300seconds. Checkpoints collect actual presented-frame observations and physical footprint; native captures include startup/HUD/menus and carry hashes. Scene setup travel is distinct from measured walking/camera steps. Recording is evidence, not automatic performance certification.

Example scenario (requires an already playable test scene):

```json
[
  {"action":"checkpoint","label":"before movement"},
  {"action":"stick","stick":"left","x":0,"y":1,"milliseconds":1000},
  {"action":"stick","stick":"right","x":0.5,"y":0,"milliseconds":500},
  {"action":"wait","milliseconds":500},
  {"action":"capture","label":"settled scene"},
  {"action":"checkpoint","label":"after movement"}
]
```

Physical input in the test window revokes agent controls and transfers the shared slot to human ownership. Automatic agent shutdown, escalation and already-queued agent-close work must be disarmed; ordinary window/human close remains available. A subsequent developer must create a new session rather than reclaim that process.

Updated cooperating preempters hold the persistent shared `preemption.lock` across a single validated holder snapshot and signaling. Human takeover retains that lock until exit, including failure to update the holder record. Do not delete or rotate it. Older binaries and raw wrapper cleanup that ignore the guard remain outside this guarantee; an already-issued signal cannot be recalled. Merely locking a wrapper's status check does not protect a later unguarded terminate call.

## Acceptance evidence

Synthetic Python/Node and official MCP SDK tests use private generated saves, mocked processes and closed sessions. Native CPU fixtures test the actual isolation parser, typed input path and takeover gates; compiling a fixture does not verify a game launch. Required live acceptance includes effective paths and no unintended app-managed writes, acquired-slot acknowledgement, expiry/revocation, human rejection/takeover, native startup capture, settled inventory/quick-select/settings and a walking/camera scenario. Keep all game files, saves, logs and captures private.
