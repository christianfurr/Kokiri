# Live area telemetry

The optional desktop bridge in `runtime/oot_live.h` is authored code from this
project's earlier OoT Editor integration. The prior implementation credited
Kabosune/oot-remake-modding's address-map and sloperina layout notes. Kokiri keeps
that attribution and the existing update-131072 instruction fingerprints. Only
small compatibility constants and authored host code are present; no extracted
module, generated game code, shader or player data is copied here.

`OOT_EDITOR_STATUS` names an existing owned regular file opened without following
its final symlink. `TOTK_INPUT_FILE` carries serialized `oot-live` requests. The
input reader queues a request; the game's full-key or handheld controller poll
consumes it after releasing the host input mutex. Both plural and SDK single-state
APIs use that path. No renderer frame hook or external process-memory API is used.
The module and output descriptor publish atomically under the queue mutex. A
request arriving before module initialization gets a terminal `not-ready` reply,
so the app's single-request monitor can try again after startup.

The `session/ready` reply means the bridge passed its compatibility checks. It
does not mean the world has loaded. A valid position requires a live player actor;
callers still need to distinguish paused menus and scene transitions.

Normal Kokiri sessions expose read-only position and area observations. Move and
warp requests require a non-user `TOTK_SLOT_OWNER` and an existing owned profile
whose canonical path lies outside both Kokiri and legacy real-profile trees.
Ownership is checked when queuing and again before mutation. Test harnesses must
use a copied profile and declare their agent owner explicitly. Queued requests
expire before looking up or moving an actor; a timed-out mutation must not be
retried unless the bridge explicitly reports that it expired without execution.

Movement retains the existing in-game physics-controller calls and bounded
distance, map, pause and save-write checks. Warp uses only the previously verified
fixed destinations and game event constructors. The bridge does not edit saves,
restore progress or accept arbitrary memory addresses.

CPU verification uses a synthetic sparse module and actual parser/queue code:

```sh
python3 -m unittest discover -s engine/tests -p test_oot_live_bridge.py -v
```

The positive fixture checks file and fingerprint rejection, normal-session
read-only behavior, serialized requests, concurrent initialization and expiry.
It passes 42 checks; the same fixture also passed ThreadSanitizer with no race
report during the 2026-11-15 integration. Two isolated negative controls
remove only the read-only gate or expiry condition and must fail their respective
assertions. CPU checks do not prove the game's actor layout or traversal works;
copied-profile gameplay remains a separate integration gate.
