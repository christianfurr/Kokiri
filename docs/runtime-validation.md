# Runtime performance validation

Shader preparation, frame production, actual presentation and physical memory
are separate measurements. A complete v28 preparation receipt is a prerequisite
for a prepared-build comparison; a source metadata row count is not that receipt.

## Analyze actual game presentations

`engine/scripts/analyze_presented.py` reads the version 1 immutable presentation
sidecar emitted by `DM_NVN_TSV`. It starts no game and does not modify its inputs.
Keep captures and reports outside the source checkout.

```sh
python3 engine/scripts/analyze_presented.py "$RUN/timings.tsv.presented.tsv" \
  --segments "$RUN/segments.jsonl" --output "$RUN/presented-analysis.json"
python3 -m unittest discover -s engine/tests -p 'test_analyze_presented.py' -v
```

Segment markers use the same macOS monotonic clock as actual presentation:

```json
{"scene":"drawbridge-walk","suite":"warm-1","phase":"start","monotonic":1000.0}
{"scene":"drawbridge-walk","suite":"warm-1","phase":"end","monotonic":1060.0}
```

Use real `time.monotonic()` readings at the boundaries. These example values
are illustrative. Complete markers select the half-open interval `[start,end)`.
Record after the end marker until every earlier queued game ticket has a terminal
event; a fixed number of extra frames cannot guarantee callback completion.

The analyzer resolves queue/terminal identity by ticket, frame and texture serial.
It sorts actual display timestamps rather than callback publication order. Explicit
drops remain distinct from missing callbacks. Generated frames are reported
separately and cannot establish game FPS. Version 1 lacks expected generated-frame
enqueues, so generated/total physical-update completeness is never certified.

For complete game coverage, average FPS is the number of distinct actual game
presentation timestamps inside the segment divided by its full wall duration.
Interval p95/p99 use nearest rank. The 1% low is 1000 divided by the mean of the
slowest `ceil(0.01 * interval_count)` intervals in milliseconds. Hitches count gaps
strictly greater than 33.3, 50 and 100 ms. No interval outside the segment is clipped
or invented at its edges.

Missing/malformed events, contradictory identities, pending outcomes and multiple
game tickets at one timestamp suppress certified results. Observed gap statistics
remain available for investigation, with the blockers listed. `complete_coverage`
certifies only the event accounting; it does not certify the route, scene,
equivalent builds, instrumentation overhead or visual quality.

## Attribute blocking carefully

In `hle_nvn.c`, `@frame_ms` is spacing between present-call entry timestamps.
Compiler/resource counters are sampled after the current present operation.
Consequently a compiler stall can appear in one row's creation counters and the
next row's entry interval. Inspect adjacent rows and their `@call_ms` timestamps
before calling a long entry interval a non-compilation hitch. GPU durations
arrive later but already carry their original frame identity; do not shift those
row identities again.

`@sub_wall_ms` versus `@sub_cpu_ms` helps locate blocking, but neither proves its
cause. Uploads, CPU waits, shader compilation and GPU spans can overlap. Do not
sum their medians or subtract distributions to invent an exclusive CPU budget.
Use a separately recorded CPU/system trace to distinguish dependencies, resource
preparation, compression and paging. System-wide paging is not per-game attribution.
Never join concatenated logs on frame number alone.

## Matched route and memory acceptance

Before each authorized launch, recheck human ownership and the exclusive heavy-work
lease. Use a disposable profile and independently copied compatible v28 cache,
including the explicit user PSO file and mesh records. Hash source, executable,
translator, seed, prepared archive and initial cache inventory. Restart each side
from equivalent cache copies; do not let the baseline donate extra learned entries
to the candidate. Keep saves and cache originals intact.

Match internal/output resolution, quality/upscaler, generated-frame mode, mods,
window focus, power and thermal/background conditions. Run cold first visits and
warm revisits separately. Include walking and left/right camera movement in:

- Castle Town and an ordinary drawbridge crossing in both directions.
- Death Mountain Trail and Goron City, including scene-backed settings/menu checks.
- At least five repeated transitions through the same route, with start/end marks
  for movement, loading and settled holds. Preserve full-cycle memory peaks.

Sample process `phys_footprint` with PID/start identity; report per-cycle peak,
settled exit and final plateau or continuing growth. RSS, Metal allocated bytes,
wrapper sizes and residency totals overlap and must not be added. Reduced wrapper
counts or sweep work do not establish physical-memory savings. A lower final
sample does not establish a plateau. Preserve the reported v28 corruption
improvement; inspect matched gameplay/menu captures before accepting a candidate.

The storage-sweep candidate preserves the existing 600-submission idle rule and
deferred GPU retirement. It skips table scans before the earliest possible idle
deadline. Its CPU fixture checks exact retirement identities/fences; it does not
measure game FPS, GPU lifetime on hardware or physical footprint. Matched gameplay
and rendering acceptance remain required before integrating a performance claim.
