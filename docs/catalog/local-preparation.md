# Prepare downloaded recipes locally

Use a verified catalog download to extend the metadata list for a new local game
build. The tool runs offline and creates a fresh list. The builder then translates
shaders from your game files and compiles libraries and pipelines on your Mac.

Keep the downloaded index in its native cache layout:

```text
Catalog/
  packs/<sha256>.json
  reference/<context_id>.json
```

An exact download uses `runtime-ready/` instead of `reference/`. The exporter
checks either kind without promoting reference data to exact runtime input.

Supply the expected catalog context and trusted public keys from your verified
application/runtime configuration. Do not take keys from downloaded metadata.
The context must match the manifest, including null fingerprints. The accepted
preparation receipt's reference context can differ from the runtime's general
context file; use the context that the app selected for this download.
The exporter also requires the builder's supported content version and the OoT
shader chain from `engine/third_party/d2r_gfx/gfx/nvn/dmsh_chain.h`. A signature
on an older catalog does not make that catalog suitable for the current builder.

Run from the source checkout with Python and `cryptography` installed:

```sh
python3 services/catalog/scripts/prepare-local-recipes.py \
  --index "$CATALOG_INDEX" \
  --context "$EXPECTED_CONTEXT_JSON" \
  --keys "$TRUSTED_KEYS_JSON" \
  --baseline engine/assets/shader_list.tsv \
  --minimum-revision 1 \
  --output "$NEW_SHADER_LIST"
```

Pass the highest accepted revision for this context as `--minimum-revision`
when your client records one. The standalone tool does not maintain revision
history. It checks the signed manifest, each content-addressed pack, record
hashes, duplicate records and bounded local paths before creating the output.
It refuses symlinks and existing output files.

The JSON result reports added warm rows and refused binding states. The tool
merges with the baseline to retain shader locators and translation dependencies;
rows with unknown binding states stay out. The normal builder still resolves
recipes against local shader data and rejects unsupported host-generated rows.
An added row is a preparation candidate, not a compiled or prepared pipeline.

Use the new list when preparing a new game app in a separate work directory:

```sh
python3 -I engine/build.py "$GAME_DUMP" \
  --shared-fonts "$VERIFIED_FONTS" \
  --work "$NEW_WORK_DIRECTORY" \
  --shader-list "$NEW_SHADER_LIST" \
  -o "$NEW_GAME_APP"
```

The exporter makes no network requests and does not alter the baseline, downloaded
packs, installed game or player cache. Keep generated lists outside the source
repository. The builder needs the usual Xcode/Metal toolchain, verified inputs,
disk space and preparation time. Server downtime does not affect an existing
download. A failed catalog export leaves the original local preparation path
available with the baseline list.

Ready-made compiled downloads and exact offline-library runtime adoption remain
separate work. This path keeps compilation local and makes no stutter or startup
time claim.
