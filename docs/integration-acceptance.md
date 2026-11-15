# Integration and acceptance

These gates apply to the independent, credited Kokiri project. They describe required evidence, not completed work. Integration owns candidate assembly, the exclusive heavy-work schedule, installation, rollback and release status. Specialists return scoped commits and evidence; they do not independently replace installed apps or publish releases.

## Ownership and isolation

| Track | Primary responsibility | Overlap requiring agreement |
|---|---|---|
| 01 Shaders | `engine/build.py`, shader preparation, compatibility receipts and readiness gates | Renderer compiler hooks; packaging requests from 05 |
| 02 Performance and Memory | Renderer resource lifetime, frame pacing, physical memory and performance analysis | Compiler/catalog hooks in `nvn_mtl.m`; timing hooks in `frontend.m` |
| 03 Native App and MCP | Native launch/import/session models, observation MCP, startup/HUD/input acceptance | `frontend.m`, shared Swift models, 04 catalog and 05 update UI |
| 04 Public Shader Library | Catalog service/client/protocol, compatibility and native adoption | Shared models owned by 03; renderer hooks owned by 02 |
| 05 Updates and Releases | Signed update path, packaging validation and release evidence | Build entry owned by 01; shared models owned by 03 |
| 06 Audio | Mixer/output/effects and audio acceptance | Frontend/input owned by 03; runtime scheduling owned by 02 |

Each track uses its own branch, worktree and external build output. Do not switch, reset or clean the shared checkout. Preserve uncommitted MCP work and website changes. Agree on exact functions before editing a shared file; directory ownership does not grant all sections of a shared file. Integration owns CI workflow changes and resolves overlaps before edits. Keep actual chat IDs, worktree paths, grants and transient reports in a private coordination ledger, outside the public repository.

Only one heavy build, Metal test or gameplay benchmark runs at a time on the 16 GiB Mac. Integration grants a bounded task with its command, output, resource estimate and stop condition. An idle process list is not a grant. Recheck actual processes and session identities immediately before starting. Human gameplay takes precedence; never close it to obtain a slot. When it appears, stop starting work and safely wind down owned tasks. A slot is released only after the owned process tree exits. Source review and light offline analysis can proceed separately; benchmark windows exclude competing agent work.

## Preservation before migration

1. Record the actual running executable, process-start identity and session ownership. A stale PID, lock or app title is insufficient.
2. Snapshot the complete relevant profiles, settings and compatible cache, including explicit PSO files stored outside the profile. Record source/copy SHA-256, sizes, timestamps and source stability. Preserve distinct PSO inputs even when their names are similar.
3. Compare save lineage and identify the intended current progress. Later timestamps alone do not establish the desired slot or safe merge direction. If lineage is unresolved, retain all versions and do not migrate or replace the player profile.
4. Run tests only on separately copied profiles with isolated settings, cache, logs and control paths. Hash-check player saves before and after. Test progression never becomes player progress.

Backups are private and are never committed. Game assets, generated game code, extracted shaders, saves, raw logs and credentials remain outside public source and release uploads.

## Gate A: complete v28 preparation

The earlier package used `OOT_SHADERS=none` and warmed only 1,861 shader libraries and 1,920 pipelines. It is not evidence of full v28 preparation. The 50,376-row source metadata list is not a compiled-shader count. Old v23 caches cannot be made compatible by relabeling them.

The preparation receipt must bind the following to the actual output:

- Full source commit plus any source-diff digest, executable SHA-256 and bundle identity.
- Shader-chain/backend/compiler identity, translator source and executable hashes, serviced tool version, target and effective translation/compilation options. A directory named `v28` is insufficient.
- Requested shader mode and corpus identity; requested, completed, failed and pending variants; separately identified libraries and prepared pipelines, including mesh/task and observed specialization variants.
- Complete compatible cache and explicit PSO input identities, with losses or unsupported records reported. Count actual outputs and validate receipts against them; do not infer success from source-list length or an old manifest.
- Exact commands, worker count, duration, peak preparation memory, disk use, failures and resume procedure. Quantify bounded pilot results before projecting the full run.

`none`, `title`, missing/mismatched receipts, missing outputs or outstanding required work fail the **fully prepared** gate. A gate test must demonstrate rejection of incomplete and mode-none outputs. Shader preparation alone does not establish performance, visual acceptance or whole-game coverage. Any runtime compilation observed afterward is recorded as a remaining gap, not hidden by a preparation claim.

## Gate B: matched runtime acceptance

Freeze executable and shader-pack hashes for each tested build. Match profile snapshot, route, camera, mods, resolution, scaling/interpolation, cache population, power/thermal state, focus and instrumentation. Preserve cold and warm evidence separately. A baseline and candidate that differ in preparation completeness cannot isolate a runtime optimization.

- Cold first visits, walking, camera turns and transitions; warm revisits and a subsequent launch.
- Castle Town/drawbridge in both directions, Hyrule Field, Kokiri Forest/Lost Woods, Death Mountain/Goron City, interiors, a dungeon and combat/effects where the copied progress permits. Record unavailable coverage.
- At least five matched repeated-area cycles to expose retention and a longer soak whose duration is stated. Include full-cycle transition peaks and settled memory, not just selected location windows.
- Actual presented game frames: elapsed frames/time average, median frame time, p95/p99, stated 1% low method, hitch thresholds/counts and excluded/ambiguous samples. Do not count generated frames or call reciprocal median an average.
- `phys_footprint`, full-route peak and settled values, per-cycle growth, compression/paging and CPU/GPU/blocking evidence where available. Wrapper allocation totals are not physical-memory savings. Do not reintroduce the rejected 8 GiB memory cap.
- Paired visual checks at matching positions/cameras, including Death Mountain terrain, scene-backed settings/inventory/quick-select overlays, transitions and effects. The latest v28 human playtest reported no corruption; preserve that improvement while keeping broader visual acceptance open.

Report severe drops even when no shaders compile. An improved warm route, a static hold or an attractive screenshot cannot certify cold play or game-wide performance. Independent review must examine GPU lifetime/fence safety and compare the evidence with the exact claimed behavior.

Integration records a candidate decision receipt with pass, fail or unavailable for each route's performance, memory and visual checks, tied to the tested executable and shader-pack identities. State the measured limits and reasons for unavailable coverage. Collected metrics alone do not constitute acceptance; a missing required check cannot silently pass.

## Gate C: native, library, update and audio acceptance

03 verifies non-destructive setup/import, launch ownership, actual native startup-window capture, app/game icons, HUD persistence and physical L3+R3 activation. A gameplay image named as startup proof is insufficient. MCP stays observation-only until complete test isolation is proven; host loading, live location and screenshots require their own observations. Protect unrelated host configuration with an immediate-before comparison when making an authorized configuration change.

04 verifies exact-context compatibility, offline/error handling, signatures/quarantine, bounded native warm-plan adoption and the contribution consent boundary. Local protocol tests are not a live deployed library or measured gameplay benefit. Metadata contributions exclude game-derived shader code and private player data.

05 verifies update signature rejection, tamper handling, delta reconstruction/full fallback and rollback. Source tests, staged packaging, Developer ID/notarization, production hosting, published appcast and actual installed update are separate states. Do not label a locally signed shell as a production release.

06 verifies stereo/channel mapping, game speed, movie audio, transitions, pause/resume and sustained playback on the same accepted candidate. State any output-device or physical listening checks that remain unavailable.

## Integration, installation and rollback

Accept only reviewed commits whose changed paths match their ownership. Record review findings, test commands and exit results. Assemble in the integration worktree, retaining unrelated shared work. Rerun the relevant checks on the assembled source; test success on a specialist branch does not certify integration. After any source or packaged-resource change, invalidate dependent evidence and rebuild/retest the affected gates against the new identities.

Before installation, verify all required gates, current player lineage and absence of human gameplay. Hash and back up the old bundle/resources and player data, record their exact locations, and verify the staged bundle signature and runtime resource linkage. Never overwrite a live executable. If progress cannot be preserved safely, keep the candidate staged.

Install only under integration authorization. Confirm the installed executable and shader resources match the tested hashes, perform a safe post-install check and retain a rollback receipt. Restoring the previous bundle must not overwrite newer player progress. Verify the rollback artifact before claiming rollback is available.

Release status names the observed boundary: source checks passed, staged, accepted, installed, signed/notarized, published, or update-delivery verified. Missing gates remain explicit. Do not declare the whole project complete or hand over a mode-none build as fully prepared. Preserve upstream and third-party attribution throughout.
