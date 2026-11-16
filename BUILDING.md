# Build Kokiri

Run the commands below from the repository root. Check [current status](STATUS.md) first: full v28 preparation remains incomplete, and contributors do not yet have an accepted playable package from that build. Build duration, peak memory and whole-game performance remain unverified.

Kokiri has two app bundles:

| App | Contents | Build |
| --- | --- | --- |
| `Kokiri.app` | Native SwiftUI launcher, setup and session viewer | `macos/build.sh` |
| `Kokiri Game.app` | Native runtime and your locally owned game content | `engine/build.py` in an external workspace |

Building the launcher does not build or update the game runtime. Local builds use ad-hoc signing; they are not notarized distribution packages.

## Requirements

- Apple silicon Mac with macOS 26 and full Xcode, including its Metal toolchain.
- Python 3.14 or later for the game builder.
- Your own Nintendo Switch 2 edition of Ocarina of Time, title `0400486024DEC000`, update `131072`.
- The six required `.bfttf` shared firmware fonts and their existing `manifest.json`, obtained from your own files. Arbitrary TTF files do not satisfy this input.
- An external work/output location. A fresh import requires at least **40 GiB free** to pass its initial space check; this is not a measured total storage requirement for full preparation.

The builder accepts a complete `.nup` application package, or a dump root containing `updates/131072/romfs/` and `updates/131072/exefs/`. It can fall back to `base/exefs/` for code. The update RomFS must already contain the complete patched tree; a delta-only directory is insufficient. The builder validates the supported version and content. It does not decrypt NSP/XCI inputs or accept separate update, DLC or mod arguments. N64 and Nintendo 3DS ROMs are unsupported.

The first build needs network access for pinned public dependencies. The launcher fetches checksum-pinned Sparkle. The runtime builder prepares its Python environment, codecs and source-built shader tools outside the checkout. Game data and firmware fonts come from your local inputs.

## Native launcher

```sh
bash macos/test.sh
bash macos/build.sh
open macos/build/Kokiri.app
```

See the [native app guide](macos/README.md) for capabilities, recordings and public updater configuration. Setup can connect an existing compatible game app. Import Save Profile copies the selected complete profile while the game is closed and refuses to replace an existing Kokiri profile.

## Private game runtime

Choose fresh output and work paths outside this checkout. Quit gameplay before starting a heavy build, and run only one build or Metal benchmark at a time on the same Mac. Keep human play sessions and their original profiles intact.

```sh
OOT_SHADERS=full OOT_SHADER_SUBSET=all OOT_BUNDLE_SHADERS=1 \
python3.14 -I engine/build.py "/absolute/path/to/owned-dump" \
  --shared-fonts "/absolute/path/to/owned-shared-fonts" \
  --work "/absolute/path/outside-checkout/Kokiri-work" \
  --out "/absolute/path/outside-checkout/Kokiri Game.app" \
  --jobs 2
```

These shader settings request full preparation and avoid inherited `none` or `listed` settings from a test environment. The bounded worker budget defaults to two; `--jobs 1` reduces concurrency. These settings do not establish a memory ceiling or guarantee completion.

Keep the work directory for compatible reuse. After an interruption, inspect the reported failure and preserve completed outputs before retrying the same command. Do not delete caches or staging directories just to bypass a validation error. A successful build must carry matching preparation receipts; game launch and visual/performance acceptance are separate checks.

Advanced local inputs are explicit: `--shader-list /absolute/path/list.tsv` supplies metadata, and repeatable `--learned-cache /absolute/path/cache` supplies compatible runtime cache input. Preserve complete compatible caches, including mesh records, and the associated explicit pipeline metadata file. Do not mix or relabel older shader chains. Source-list row totals do not count compiled shaders or pipelines.

## Updates and troubleshooting

The game builder supports `--rebuild` for an existing private runtime, but compatibility changes can require full preparation. Use a separate candidate/workspace and review the [runtime update design](release/runtime-updates.md) before staging updates. Sparkle updates the launcher bundle; a runtime update must rebuild from the owner's local assets and verify compatible preparation. Actual game update/relaunch and rollback remain pending acceptance.

Read the reported error and relevant work-folder log before changing inputs. A missing Metal compiler requires the full Xcode Metal toolchain. A font error requires the six supported files and manifest. A version, integrity or preparation mismatch requires correcting that input or build, rather than weakening the checks.

For a public [bug report](https://github.com/christianfurr/Kokiri/issues), include the source commit, Mac chip/RAM, macOS version, relevant settings and a sanitized error description. Keep game files, fonts, generated apps, caches, saves and private logs out of attachments. See [contributing](CONTRIBUTING.md) and [source provenance](engine/docs/kokiri-source-provenance.md).
