# Connected Kokiri app

Make the existing Home, Play, Shader Library, Performance and Settings flows coherent. Preserve the forest identity and all player progress. The user reported a good full-v28 playtest and requested app work rather than further game tuning.

Acceptance:
- Home shows the selected game, real preparation counts, correct player profile and a clear Play/Return action.
- Shader Library reads the full bundled metadata (including files above16MiB), distinguishes compiled libraries from recipes, and can verify/download the public signed reference catalog without adopting it as exact runtime input.
- The private playtest can read the public library while contributions remain disabled and shared preferences remain unchanged.
- Settings reveals the actual active profile/settings and explains controls/HUD clearly; Performance retains actual observations and useful empty/recent-session states.
- A normal reopening of the installed Kokiri app retains its existing signed private binding. No game renderer, save migration, engine rebuild or automatic game launch.
- Appropriate Swift/client tests, signed-catalog integration, source publication checks and actual app launch pass. Human gameplay preempts heavy work.

Public metadata remains recipe/reference data, not downloadable Metal binaries or a whole-game performance guarantee. Production distribution credentials remain outside this batch.
