# Headless save workshop

Internal API for an already isolated, **stopped agent-owned test profile**. The session manager supplies fixed paths and holds its session lease throughout calls:

```python
workshop = Workshop(profile, existing_private_state_dir, stopped_check)
snapshot = workshop.snapshot(slot=0)
plan = workshop.plan(0, {"rupees": 100, "hearts": 3}, snapshot["snapshot_id"])
receipt = workshop.apply(plan["plan_id"])
workshop.restore(snapshot["snapshot_id"])
```

`WorkshopError` rejects unsupported or stale operations. Paths are constructor-only inputs; never expose them as MCP tool parameters. `stopped_check` must verify the owned process and lease rather than accepting an agent assertion. The service also serializes calls with a nonblocking file lock. It does not establish launcher isolation or authorize an ordinary player-profile write.

Snapshots copy and hash the complete account, including unknown files and empty directories. Symlinks, hardlinks, special files, cross-user entries, oversized files/accounts and ambiguous accounts are rejected. Maximums: six numbered slots, 2 MiB per file, 8 MiB / 256 entries per account. State must reside outside the profile; snapshot/plan metadata contains private save hashes and semantic state.

Plans accept only typed fields:

- `rupees`, `wallet` (the three known actor names), `hearts`, `max_hearts`, `magic`, `max_magic`.
- `ammo` with existing quantity identifiers; `capacity` with seeds/nuts/sticks/bombs/arrows tiers.
- `bottles` count and `bottle_fill` from the existing supported refill names.
- `inventory` or `equipment`: `add`, `remove`, `clear_acquisitions` lists of known actor names. Equipment means ownership; arbitrary equipped-slot assignment is unsupported. Existing equipped-item and acquisition-consistency rules apply.
- `progression`: known named Boolean fields present in the save; no numeric hashes or offsets.
- `destination`: `hyrule`, `kokiri`, `kakariko` for the next-load checkpoint; `learn_songs`: `epona`, `sun`, `warps` groups using the existing editor rules.

The result contains a semantic before/after diff, including automatic capacity/acquisition changes. Source save files are untouched until apply. Apply checks the expected full-account snapshot again immediately before an atomic account-directory swap; it retains the original copied snapshot as a backup. Completed plan retries return their original receipt without applying twice, and report whether the current account still matches that receipt. Restore backs up the current account before swapping in a verified snapshot; the original account directory must still exist.

A synced journal precedes the swap. A failure writing the completion receipt rolls back the directory swap; an interrupted rollback retains the original staged account and journal. Retrying the plan recovers a matching completed swap without repeating it. The tests simulate these failures; actual machine-power-loss durability has not been certified. Per-profile leases protect cooperating tools; this is not an operating-system sandbox against arbitrary same-user processes.

The fixed local Node executable receives bounded JSON stdin and returns JSON stdout. `cli.cjs` exposes only inspect/plan and never receives file paths. It starts no DOM or WebView and permits no arbitrary script evaluation. See PROVENANCE.md and LICENSE for the reused MIT save rules. The existing OoT Editor checkout remains untouched.

Synthetic verification:

```sh
python3 -m unittest discover -s tests -p test_save_workshop.py -v
```

No live memory editing, human save application, game launch or current-v28 runtime acceptance is established by these fixtures.
