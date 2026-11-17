# Connected app acceptance — 2026-11-16

- Launcher implementation: `e5805182fbf503632941d553bdd937d095520e13`; 35 native tests passed, release build and strict deep code-signature verification passed. All three GitHub CI jobs passed for that commit.
- Independent read-only review cleared that exact commit after fixing duplicate library controls, tile-read naming, retained mesh coverage and private-session reconnection.
- Actual installed app opened and verified the public catalog: 29,796 records in 233 signed packs. Separate reference cache; no game-cache adoption or contribution upload.
- Home shows 42,466 prepared libraries and 28,786 pipelines, including 196 mesh requests, from the output-bound full receipt. Recipe totals are labeled separately.
- Public service publication passed actual isolated Node startup verification, all-pack HTTP checks, signed backup/restore rehearsal and independent anonymous HTTPS signature/pack verification. A verified signed database snapshot is retained off-host.
- Private binding/helper and existing player profile remain connected. App navigation and recent-session display were checked without launching or controlling gameplay.

Limits: reconnect admission is covered by identity checks, tests and review, but a fresh reopen during human gameplay was not performed in this batch. Catalog data is reference metadata, not compiled binaries. Wider gameplay/performance/memory acceptance remains deferred; notarized distribution and production automatic updates remain open.
