# Kokiri foundation

## Brief

Build an independent, polished Mac application for Ocarina of Time from the credited native runtime foundation. The user selected Kokiri and requested a standalone repository, a distinctive native experience, README screenshots and measured statistics, fast automatic updates, and an open shared shader library with automatic contributions.

Acceptance: a user can build from their own game files, open Kokiri, preserve/import their save, play through a branded native workflow, inspect honest session statistics, receive verified updates, and participate in a documented catalog protocol other recompilers can implement. Performance remediation continues through actual movement/camera runs, physical-memory observation and Death Mountain visual checks.

Fleet: project; root owns architecture, integration and the exclusive GPU slot, with three reusable implementation/review agents. Work proceeds in parallel where file ownership does not overlap.

## Source boundary

Import pinned public OoT source and reviewed fixes, with source-only copies of required graphics and linkage dependencies. Preserve MIT and adjacent dependency notices. Replace monorepo build assumptions. Rebuild shader tooling from pinned source into external build output. The public v28 shader chain differs from the private measured v23 build and requires fresh native gameplay validation.

## Work items

1. Establish source provenance, standalone build, publication guard and own product identity while retaining game identity.
2. Build the native Mac home/setup/session experience and low-overhead measured statistics.
3. Implement signed app update plumbing and reproducible release validation.
4. Build an open catalog protocol, compatible native client, automatic contribution queue and independently deployable service.
5. Complete rendering/performance investigation and move verified fixes into the new runtime.
6. Produce real screenshots, benchmark artifacts, README, credits, contribution guide and public repository metadata.
7. Review, run source/native/service checks, test copied-profile gameplay, publish the independent source repository and a reviewable branch. Do not merge existing upstream PRs.
8. Add the original Kokiri identity, custom in-game menu, and HUD position/scale/detail controls with real persisted runtime support.
9. Open the game settings/HUD controls with L3 + R3, preserving the existing keyboard shortcut. Verify the chord and HUD during actual gameplay.
10. Show an original Kokiri logo startup screen with real phase/progress updates, responsive layout and actual first-frame/warm-up dismissal. Preserve the game's opening and ordinary window controls.
10. Add a branded startup loading screen using the original Kokiri logo, with honest phase/status reporting and reliable dismissal into the game.

## Latest steering

2026-11-16 update: full v28 preparation completed for the accepted private playtest, the user reports good gameplay, and the public signed reference catalog is live. See the connected-app PRD/review for the current app batch. Earlier status statements below describe their original snapshot.

The user requested closure of our MacNativeGames PRs. All three open PRs (#2180, #2181, #2206) were closed on 2026-11-15; further development belongs in Kokiri. Initial standalone source commit `bb8c3e4` is public and all three CI jobs passed. Cloudflare CLI authentication is currently absent, so a deployed public catalog is not yet available.

## Verification

Exact commands will be added with each implemented target. Required gates include standalone source build, native UI compilation/render checks, catalog validation/signature/compatibility/offline behavior, signed-update rejection tests, asset publication scan, existing runtime/source regressions, Metal native probes and fresh copied-profile gameplay.

## Current limits

The existing installed app remains unchanged. No 60 FPS, memory-ceiling or terrain-fix claim is accepted without matching evidence. Automatic app releases need a distribution-signing/notarization route; the currently visible keychain has Apple Development identities, not Developer ID Application. Implement and test the update path before reporting production readiness.

## Boundaries

No game data, generated game binaries/shaders, saves, private diagnostic dumps, unrelated application changes, paid services, unsolicited messages or invented benchmarks. No new account/cloud-save product. Preserve real player progress and the existing cross-app game slot. Any hosted resource must be new and scoped to Kokiri.
