# Kokiri for macOS

Native SwiftUI shell; the game remains a separate native app opened with `NSWorkspace`.
Requires macOS 26, Apple silicon and Xcode. No web view, Electron or JavaScript UI.

```sh
cd macos
bash test.sh
bash build.sh
open build/Kokiri.app
```

The package pins Sparkle **2.10.0**. The preparation script fetches its official Swift Package Manager artifact and verifies the checksum from that release's upstream `Package.swift` before extraction. SwiftPM links the prepared binary target. The original framework's symlinks and helpers are preserved. Local app signing is ad hoc; this is **not** a notarized distribution release.

Setup connects a compatible game app or invokes `engine/build.py` using explicit file arguments. It never puts game output inside this repository. Import Save Profile copies the whole selected profile only when the game is closed, verifies its contents, and refuses to replace an existing Kokiri profile. Tests use temporary synthetic profiles only.

The normal game starts with Kokiri's own player profile and the shared cross-app game slot. Mods has a separate library and named loadout profiles; a compatible ordinary runtime receives a verified copy of the selected overlay for that launch. It receives no resolution, frame-rate, focus or input overrides. Folder-based save sync is disabled; Kokiri has no cloud-save product. In-game settings remain authoritative.

## Mods and Saves

Mods manages Kokiri's own local library. Import copies compatible RomFS packs or the local MacNative Mods OoT library; it does not alter that app's packs or profiles. Named mod profiles store enabled packs and load order separately from player saves. Changes apply to a later launch, never to a running game. Unsupported formats and incompatible runtimes show an error rather than claiming the profile was applied.

Applying an enabled profile requires the runtime's explicit integer `KokiriRomFSModsVersion=1` capability. New ordinary source builds advertise it only when packaging the exact runtime just produced by that build. Older/unadvertised apps and shader-only repackages stay unsupported; an empty loadout can still play without mods. The marker describes overlay support, not in-game verification of a particular pack.

The accepted private human-preview runtime explicitly disables mod overlays. Its Mods tab can manage the library and profiles, but clearly shows that this connected preview cannot apply them. Ordinary unmodded Play remains available. Supporting mods in that private runtime requires a separately tested runtime upgrade; changing launcher environment variables cannot enable it.

Saves displays the exact connected player profile, including its private playtest lineage when bound. It reads save-slot details and any embedded preview locally, with manual refresh and per-file errors. This is a read-only viewer: it does not edit, restore, delete, migrate or overwrite saves. Missing or unsupported saves stay visible as such rather than falling back to another profile.

Detailed frame recording is **off by default** for ordinary play. When enabled, Performance reads bounded timing tails (`DM_NVN_TSV_CALLS=0`) and excludes generated and duplicate presentation timestamps. Process physical footprint (using the installed SDK's libproc ABI) and read-only serialized position samples remain available without detailed recording. Rates are live observations, not certified benchmarks. A bridge connection or position does not prove unpaused gameplay. Detailed collection has overhead and its setting applies to the next session.

Open Recording accepts a dated `session.json` with actual uncompressed timing files, optional process samples and position replies. The UI prominently labels recordings and their date. A native view capture of a real recording can be produced without launching the game:

```sh
open -n build/Kokiri.app --args --recording /path/to/recorded-session
```

Capture the actual app window with macOS Screenshot after the recording loads. Protected folders can require macOS file access; the normal **Open Recording…** picker records the user's folder selection. Native control vibrancy is not faithfully represented by an offscreen view cache.

## Signed updates

With neither value set, the updater is inactive and the UI says it is unconfigured. To build a configured shell, supply **both public values**:

```sh
KOKIRI_UPDATE_FEED=https://your-domain/appcast.xml \
KOKIRI_UPDATE_PUBLIC_KEY=your-base64-32-byte-public-key bash build.sh
```

The app requires HTTPS, a 32-byte pinned Ed25519 public key, signed appcasts, verification before extraction, and no expiry of failed feed signatures. It never generates or embeds a private signing key. Sparkle owns automatic-check/download preferences. Updates target only the shell bundle; game apps, profiles, build workspaces and caches stay outside it. Production delivery still requires the signed feed, signing/notarization and real update/rejection testing.

Set `KOKIRI_VERSION` and a strictly increasing numeric `KOKIRI_BUILD_NUMBER` for each release. The builder records the actual Git commit and dirty state in the signed bundle. Automatic checks use a one-hour interval; existing user update preferences remain authoritative. See `release/README.md` at the repository root for archive/feed preparation and the official-tool tamper checks.

Live area queries require the runtime capability `KokiriLiveStatusVersion=1`. Kokiri does not send that diagnostic protocol to older public runtimes that do not advertise it. Physical process observations remain available.

Official references: [programmatic SwiftUI integration](https://sparkle-project.org/documentation/programmatic-setup/), [security settings](https://sparkle-project.org/documentation/customization/), [2.10.0 release](https://github.com/sparkle-project/Sparkle/releases/tag/2.10.0).

## Catalog boundary

The durable catalog queue is the single authority for the one-time contribution choice; the UI reads it at startup and never replays a legacy launcher preference into it. The app uses the reviewed native `CatalogClient` actor for validation, a durable bounded queue, offline retry and signature verification. A consenting session snapshots its selected runtime's bundled context and the existing profile metadata prefix before launch. After that owned process exits, only complete, prefix-verified newly appended rows are ingested; imported old rows are never relabelled with a new context. Replacement, truncation, malformed or unsupported rows are deferred or kept local with status feedback. Startup/installation selection checks for signed reference downloads when a complete prepared-game receipt supplies its compatibility context. Exact runtime downloads still require every runtime fingerprint. The UI reports verified downloads separately from bundled list counts. Runtime warm-list adoption is not yet connected. No game cache is overwritten by the client.

The default build pins the live public origin and verification key documented in [catalog integration](../docs/catalog/integration.md). Private playtests permit public reads while contributions remain disabled and shared launcher preferences remain untouched. Public build overrides use the paired `KOKIRI_CATALOG_ORIGIN` and `KOKIRI_CATALOG_KEYS_JSON` (key ID to base64 public-key map). Test fixture keys are never bundled. Wire protocol and validation are documented under `docs/catalog`; the shell does not upload raw TSV files, shader source, logs, profiles or game assets. Unknown runtime fingerprints stay reference-only and cannot be warmed.
