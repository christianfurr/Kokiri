# Contributing to Kokiri

Kokiri keeps its source, tests and catalog protocol open. Small, reproducible changes are easiest to review.

## Bugs and performance reports

Include your Kokiri build, macOS version, Apple chip, RAM, internal/output resolution and pacing settings. Describe the area and the movement or camera sequence that triggers the problem. Compare a first visit with a repeat visit when possible. A screenshot of Kokiri's session page can help; remove personal paths before sharing.

Keep game dumps, firmware, keys, saves, extracted shader code, generated game binaries and private diagnostic logs out of the repository and public issue attachments. Synthetic fixtures and small sanitized numerical results are welcome.

## Code

- Read `.cairn/MAP.md` and the nearest dependency notice before changing imported code.
- Preserve provenance and copyright notices. Keep game-derived build output in an external workspace.
- Describe the concrete behavior change and the evidence that checks it. A source build does not prove improved gameplay.
- Use the native app checks in `macos/README.md` and the catalog's local tests for those components. Run the relevant engine probes for graphics changes; include a failing baseline or negative control when it establishes the fix.
- Do not change retention, memory or frame-pacing defaults without measured correctness and gameplay evidence.

## Catalog adapters

Read `docs/catalog/protocol.md` and `docs/catalog/integration.md`. An adapter must define its metadata grammar and compatibility fingerprints, reject arbitrary code/paths and provide malformed-input fixtures. Native cache binaries are not portable catalog entries. Automatic contribution needs a visible one-time choice, an off switch and offline retry.

## Releases

Development builds are not a notarized release. A release needs the publication scan, local checks, copied-profile gameplay, distribution signing and a verified update feed. Publish the tested commit and matching measurements; do not reuse an older shader-chain result as a new build's benchmark.
