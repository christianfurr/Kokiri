# Kokiri 0.4.1 — version-label hotfix

The launcher now displays **0.4.1**, build **5**, following the user's requested 0.4.x versioning. Previous Preview 4 was packaged as 0.1.0 (4). Version 0.4.0 was not separately published.

This is a version-metadata-only repackage of the verified Preview 4 launcher. Its compiled source identity stays `037e49d2445baf8529dda389d216564b72b9850d`; the verification receipt separately identifies this hotfix's packaging source. Runtime, shaders, mods, saves and settings are unchanged. Source builds now default to 0.4.1 (5).

The [Preview 4 features and verified scope](preview-0.1.0-4.md) carry forward. The manual launcher download remains experimental, ad-hoc signed and **not notarized by Apple**. Production automatic updates remain unconfigured. No game assets, compiled shaders, private bindings or saves are included.

Extract the launcher ZIP and move `Kokiri.app` to Applications. See [Apple's per-app guidance](https://support.apple.com/en-us/102445) if macOS blocks the unnotarized download. Checksums identify archive bytes, not Apple trust. The game runtime is a separate build; the version-label hotfix does not rebuild it.
