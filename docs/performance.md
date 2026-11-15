# Performance evidence

## Current boundary

The latest v28 user playtest reported no rendering corruption. Preserve that improvement while completing broader visual checks. Severe FPS drops, compilation hitches and high memory use remain unresolved; no whole-game performance acceptance follows from that visual report.

Full v28 preparation has never completed. The earlier build labeled ready used `OOT_SHADERS=none` and warmed only 1,861 shader libraries and 1,920 pipelines. The source list's 50,376 metadata rows are not a compiled-shader count. Shader libraries, prepared pipelines and source metadata are separate measurements. Old v23 caches cannot be relabeled as compatible v28 caches.

The figures below describe an earlier private v23 runtime experiment on an Apple M4 with 16 GiB unified memory, AC power, a 1280×720 internal picture and 1920×1080 output. They do not measure the current Kokiri v28 build, compare Kokiri against a competitor or prove a new performance improvement.

## Five-cycle diagnostic baseline, 2026-11-15

The same copied profile revisited two reported Death Mountain positions and Goron City. Each location window included walking and left/right camera turns. The run lasted 789.842 seconds. The real player's 20 profile files remained unchanged. The experiment enabled the existing 768 MiB CPU texture-copy budget; this setting creates substantial eviction/reupload traffic and is not a Kokiri default.

| Cycle | Trail position 1, FPS | Trail position 2, FPS | Goron City, FPS | Full-cycle peak, MiB | Settled exit, MiB |
|---|---:|---:|---:|---:|---:|
| 1 | 61.29 | 52.72 | 69.41 | 10,338.54 | 10,241.67 |
| 2 | 59.98 | 56.40 | 61.02 | 10,525.84 | 10,427.85 |
| 3 | 65.43 | 55.74 | 70.52 | 10,648.12 | 10,503.51 |
| 4 | 63.04 | 56.39 | 70.55 | 10,791.29 | 10,432.92 |
| 5 | 64.52 | 57.02 | 70.30 | 10,824.50 | 10,429.70 |

The presentation analyzer accepted all 15 windows after matching actual presentation times and frame identity, excluding generated frames. The first six windows contained five gaps above 100 ms; the final nine contained none. Full-cycle peaks include transitions and settling, which the location windows omit. The peak grew 485.95 MiB from cycle 1 to 5 even though late settled exits stayed near the same value. Memory growth is still open.

This is one repeated warm route, without a matched default-budget control soak. Fresh areas can compile new pipelines and hitch for seconds. The route does not establish a whole-game 60 FPS result. Death Mountain's rectangular corruption remained visible in later v23 controlled tests, including a broad occlusion-result override. This historical observation does not contradict the later v28 user's no-corruption report.

## Method for new results

See [runtime validation](runtime-validation.md) for the strict actual-presentation
analyzer, timing-counter alignment and matched walking/transition acceptance.

1. Record source, executable and shader-chain fingerprints, hardware and power state.
2. Use a disposable copy of the latest profile, a fixed route and the same warm population. Preserve the real profile before and after.
3. Include walking, camera turns, transitions and repeated revisits. Separate static allocation holds from FPS measurements.
4. Derive game rates from real presentation callbacks. Reject ambiguous duplicate timestamps in certified comparisons. Report long gaps and frame-time distributions alongside averages.
5. Sample `phys_footprint` and report full-route peaks. Renderer allocation totals overlap; do not add them or label a wrapper-allocation reduction as physical-memory savings.
6. Compare equivalent builds and disclose recording overhead, cache state and unavailable coverage. Keep image-quality and interpolation settings explicit.

Kokiri's live UI shows observations. It does not certify a benchmark because a file contains FPS samples.
