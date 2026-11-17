<p align="center">
  <img src="assets/brand/kokiri-mark.png" width="150" alt="Kokiri leaf K logo">
</p>
<h1 align="center">Kokiri</h1>
<p align="center">Ocarina of Time for Apple silicon Macs.</p>
<p align="center">Apple silicon · macOS 26 · native ARM64 · Metal</p>

[![Source and native app checks](https://github.com/christianfurr/Kokiri/actions/workflows/checks.yml/badge.svg)](https://github.com/christianfurr/Kokiri/actions/workflows/checks.yml)

Kokiri brings the **Nintendo Switch 2 edition of Ocarina of Time** to Apple silicon Macs, with a native launcher, custom in-game settings and a configurable performance HUD. It builds on the credited [MacNativeGames](https://github.com/ly05010419/MacNativeGames) native ARM64 and Metal runtime. You build the game locally from your own files.

**Development preview.** There is no stable release yet. Full v28 preparation completed for the current private playtest: 42,466 compiled Metal libraries and 28,786 pipelines, including 196 mesh pipelines. The user reports smooth gameplay with occasional new pipeline compilation; broader performance, memory and visual acceptance remain open. The [public metadata catalog](https://catalog.christianfurr.dev) now serves 29,796 signed reference recipes.

[Website & HUD preview](https://christianfurr.github.io/Kokiri/) · [Status](STATUS.md) · [Install guide](#install-guide) · [Build guide](BUILDING.md) · [Documentation](docs/README.md) · [Report a problem](https://github.com/christianfurr/Kokiri/issues) · [Contribute](CONTRIBUTING.md)

![Kokiri native Home window](assets/readme/kokiri-home.png)

Actual native app window, captured 2026-11-15 with an existing compatible game build.

## What Kokiri adds

- **A native Mac launcher.** Connect a compatible built game, import a copy of your complete save profile, and launch from SwiftUI. Your original profile stays in its original location.
- **A Kokiri welcome.** The original leaf-K appears in the Mac app icons and native startup screen, alongside observed loading phases and progress.
- **Custom in-game settings.** Open Kokiri's menu with **L3 + R3** or **key 1** on matching runtimes. The controller shortcut still needs physical-controller verification.
- **A configurable performance HUD.** Choose four corners, four sizes and three detail modes. Position, size and detail have been checked in gameplay and persist between launches.
- **Local session statistics.** Inspect physical memory use, sampled area and optional frame timing. Recordings show their date and build, and observed game rates exclude generated frames.

Kokiri also develops an **open shader and pipeline catalog** that compatible projects can integrate. The public service serves 29,796 signed reference recipes, and the native app verifies downloads into its separate metadata cache. Exact runtime warm-up adoption remains a separate acceptance gate. The launcher's signed-update plumbing uses Sparkle, alongside a separate runtime-source update path that rebuilds from your own assets. Production feeds, distribution signing and actual game update/relaunch/rollback acceptance remain pending.

<a id="try-kokiri"></a>

## Install guide

Kokiri currently requires a source build. There is no stable signed/notarized installer. The launcher and your private game app are separate builds; if you already have a compatible native game app, skip step 3.

| Requirement | Current support |
| --- | --- |
| Mac | Apple silicon |
| Operating system | macOS 26 |
| Build tools | Full Xcode with Metal toolchain; Python 3.14 or later for the game builder |
| Game input | Your own Nintendo Switch 2 dump, title `0400486024DEC000`, update `131072` |
| Other inputs | Your own six required shared firmware fonts and manifest; see the [build guide](BUILDING.md) |
| Distribution | Source preview; no stable, notarized download yet |

**This build does not accept an N64 or Nintendo 3DS ROM.** Game files, firmware fonts and generated game apps are not distributed in this repository.

### 1. Get the source

Install full Xcode with its Metal toolchain and Python 3.14 or later, then clone the repository in Terminal:

```sh
git clone https://github.com/christianfurr/Kokiri.git
cd Kokiri
```

The first build needs internet access to fetch pinned public dependencies. For a fresh game import, the external work location needs at least **40 GiB free** to pass the initial check; full preparation may need more. See [supported dump layouts and font requirements](BUILDING.md#requirements) before building.

### 2. Build and open the launcher

Run from the repository root:

```sh
bash macos/test.sh
bash macos/build.sh
open macos/build/Kokiri.app
```

The launcher is built at `macos/build/Kokiri.app` and locally signed ad hoc. Keep this checkout if you plan to rebuild it. Quit the launcher before replacing its bundle with a later build.

### 3. Build your private game app

You can prepare the game in the launcher: on first launch, choose **Add Game**, select your game files and firmware fonts, then choose **Prepare Game**. Select this Kokiri source folder when prompted. Once a game is connected, preparation is available under **Settings → Manage Game… → Prepare from Game Files…**. The preview still needs the build tools listed above. Default work and game locations stay outside the repository; you can change them there.

Alternatively, use Terminal:

Replace the example paths below with absolute paths to your own files and fresh work/output locations **outside the repository**. Quit gameplay first and run only one heavy build at a time.

```sh
OOT_SHADERS=full OOT_SHADER_SUBSET=all OOT_BUNDLE_SHADERS=1 \
python3.14 -I engine/build.py "/absolute/path/to/owned-dump" \
  --shared-fonts "/absolute/path/to/owned-shared-fonts" \
  --work "/absolute/path/outside-checkout/Kokiri-work" \
  --out "/absolute/path/outside-checkout/Kokiri Game.app" \
  --jobs 2
```

These settings request full shader preparation. Wait for successful completion before connecting the game; building the launcher alone does not prepare it. Keep the work directory for compatible reuse. If the build fails, review its error and work-folder logs before retrying the same paths. The [complete build guide](BUILDING.md) covers input validation, preparation receipts and troubleshooting.

### 4. Connect and play

1. On first launch, choose **Connect Existing App…** (or **Settings → Manage Game… → Connect Another Game…** afterward) and select your built `Kokiri Game.app` or a compatible native MacNativeGames app.
2. To continue an existing save, close the game and use **Import Profile…** to select the complete profile folder. Kokiri copies it and refuses to replace an existing Kokiri profile; your original stays in place.
3. Choose **Play Game** from Home. On matching Kokiri runtimes, **key 1** opens the in-game settings and HUD controls. The **L3 + R3** controller shortcut still needs physical-controller verification.

Kokiri-specific features depend on the connected runtime. The public Shader Library provides signed reference metadata, not game files or compiled shader packs. See [current status](STATUS.md) for gameplay and update limitations.

## Help test and follow development

We need reproducible gameplay reports, especially from **Castle Town, Death Mountain and repeated area transitions**. Include your build, Mac chip, RAM, macOS version, internal/output resolution, frame-generation settings and the route that triggers the issue. Note whether it happens on a first visit or a repeat visit.

[Open an issue](https://github.com/christianfurr/Kokiri/issues) or read the [contribution guide](CONTRIBUTING.md). Keep dumps, keys, saves, translated shaders and private logs out of public attachments. Use GitHub's **Watch** menu to follow repository activity, or **Star** the project to bookmark it.

## A library other recompilers can use

The [open catalog protocol](docs/catalog/protocol.md) shares shader identities and pipeline recipes. Each compatible runtime builds its own native cache. Game, translation chain and compiler fingerprints keep incompatible records apart.

After a one-time choice, clients can queue contributions, deduplicate them and retry offline. The service quarantines new records before trusted publication. Downloads use a pinned signing key and content hashes. Contributions contain validated metadata; game files, shader source and player data stay local.

The first adapter supports the credited runtime's metadata format. Other projects can implement that format or contribute a versioned adapter. [Integration guide](docs/catalog/integration.md) · [Contribution flow](docs/catalog/contributions.md)

Native warm-plan adoption remains unaccepted. Records with unknown compiler target or effective options stay reference-only. Mesh pipelines and precompiled shader-library installs also remain reference-only; the catalog has no measured stutter-reduction result. See the [integration boundaries](docs/catalog/integration.md).

## Build from source

The [install guide](#install-guide) above covers first-time setup. Use the [complete build guide](BUILDING.md) for owned inputs, full-preparation settings, storage and concurrency limits. Run these launcher commands from the repository root:

Build the native product app:

```sh
bash macos/test.sh
bash macos/build.sh
open macos/build/Kokiri.app
```

The private game app is a separate build through `engine/build.py`. It validates your supported local input and rebuilds shader tooling from pinned source. Keep its work folder and generated app outside this checkout. The launcher build does not complete runtime preparation.

## Gameplay status and performance

| Area | Current status |
| --- | --- |
| Native launcher | Compiles; Home and Performance screenshots show the implemented app |
| Custom menu and HUD | Checked in a copied-profile gameplay session; physical L3 + R3 verification remains open |
| Whole-game performance | Unverified; severe FPS drops, compilation stalls and memory growth remain open |
| v28 visual correctness | No corruption reported in the latest user playtest; broader area and visual checks remain open |
| v28 shader preparation | Complete for the current private build; preparation does not guarantee every gameplay specialization is covered |
| Public metadata catalog | Live signed reference dataset; native downloads remain separate from game caches |
| Automatic updates | Plumbing tested; production signing and distribution remain pending |

New results need a matching build, hardware, resolution, tested route and cache state. We report actual game presentation rates separately from frame generation. We do not claim whole-game 60 FPS or a performance advantage over another project.

The [performance evidence and testing method](docs/performance.md) include an older v23 runtime diagnostic baseline. Those figures do not measure the current Kokiri build.

![Kokiri showing a dated performance recording](assets/readme/kokiri-performance.png)

Actual session viewer displaying an earlier v23 recording. The displayed figures are historical observations, not current Kokiri benchmarks.

## Credits and license

MacNativeGames contributors built the native execution, service and graphics foundation. Kokiri retains their MIT copyright and the adjacent dependency notices. Sparkle provides the native updater. The save workshop derives from Traiver's OOT-SW2SE with Christian Furr's macOS adaptations. The catalog's initial reference dataset preserves its upstream attribution and MIT terms.

[MIT license](LICENSE) · [Credits & third-party notices](THIRD_PARTY_NOTICES.md) · [Engine dependency notices](engine/third_party/COPIES.md) · [Source revisions](engine/docs/kokiri-source-provenance.md)

Kokiri is an independent community project and is not affiliated with Nintendo. Game names identify the supported user-supplied software.
