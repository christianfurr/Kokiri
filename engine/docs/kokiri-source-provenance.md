# Engine source provenance

Kokiri is an independent project derived from the credited MIT MacNativeGames
native OoT runtime. Original copyright and dependency notices remain in
`LICENSE.upstream`, `third_party/COPIES.md`, adjacent license files and
`third_party/UPSTREAM_NOTICES.md`.

`SOURCE_MANIFEST.json` records each imported input revision, path and digest:

| Source | Revision | Destination |
|---|---|---|
| Public OoT runtime, app, rewriter, shader tools and tests | `3edfb0b65c6398420f7cf3e8b4ede6a01ef1a904` | engine root |
| Reviewed graphics lifetimes, event projection, lazy pools and recording | `d3acf57f39c49c40de6f558de60e396f5984833a` | `third_party/d2r_gfx` |
| Reviewed NS2 regional texture-layout correction | `67baaeba3210efdf448f7b4a711b4aa41978eaa1` | `gfx/tex/nvn_deswizzle_gpu.m` |
| Disabled VR linkage and dependency bootstrap | public base above | `zeldaVR/{gfx,runtime}`, `tools/deps` |

The two external directory symlinks are materialized source copies. Reviewed
regressions receive standalone path adaptations. The manifest describes original
inputs, not byte equivalence after Kokiri's adaptations.

## Publication boundary

No game dump, extracted module, rewritten executable, generated game table,
translated shader, compiled Metal library, pipeline archive, font, save, private
diagnostic capture or prebuilt executable is imported. The official-art download
specification is omitted. Expected hashes and the RomFS inventory are verification
metadata. The pinned public shader list contains pipeline/bind metadata rather
than shader code or game assets.

The renderer's original authored shader implementations embedded in source remain
graphics code. The unused standalone `nvn_bctc.metal` file is omitted; its existing
runtime header remains. Shader tooling is rebuilt from included source and pinned
dependencies into external work output.

## Standalone adaptations

- OoT-only packaging helpers replace the multi-game root builder dependency.
- Product ID `com.christianfurr.kokiri.runtime` and version `0.1.0` are separate
  from original title identity and verified update `131072`.
- Data defaults to `~/Library/Application Support/Kokiri/OcarinaOfTime`; the
  existing cross-app game slot remains. Existing saves, contribution consent and
  cloud-sync settings are not imported automatically.
- Legacy contribution, board, nickname and screenshot endpoints are disabled;
  Kokiri's catalog adapter owns future contributions. Legacy cloud sync is off.
- Game-derived output and rebuilt tools remain external. Existing memory defaults
  remain: no automatic copy budget and 600-submission storage/arena horizons.

## Validation boundary

Public chain `oot-native-v28-mesh-primitive-blocks` differs from the earlier private
v23 measurements. Those generated caches are not interchangeable. Source builds
and CPU checks do not establish gameplay FPS, physical-memory savings, complete
game compatibility or a terrain fix. Fresh copied-profile Metal probes and
gameplay remain integration gates.
