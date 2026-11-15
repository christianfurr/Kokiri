# Credits and third-party notices

Kokiri derives its initial native runtime, static ARM64 rewriting and Metal graphics from MacNativeGames contributors under MIT. The root `LICENSE` preserves that copyright. `engine/SOURCE_MANIFEST.json` records imported revisions and source hashes; `engine/LICENSE.upstream` preserves the original license text.

Engine dependency licenses remain beside the source. Consult `engine/third_party/COPIES.md` for adaptation provenance and `engine/third_party/UPSTREAM_NOTICES.md` for the inherited dependency inventory. The latter retains original monorepo path names; imported copies live beneath `engine/`.

The native Mac product uses Sparkle 2.10.0 under MIT. Its preparation script downloads the official artifact, verifies its pinned checksum and copies Sparkle's license into the built app. The repository does not contain that prebuilt framework.

The catalog protocol, service and client code use the root MIT license. The reference pipeline dataset preserves the MacNativeGames MIT notice in `services/catalog/seed/LICENSE` and its exact source revision/hash in the seed provenance. No game or shader-source license is granted by this metadata dataset.

Build tools fetched into an external cache retain their own licenses. The optional external ZBIC decoder is a GPLv2 build utility; Kokiri does not copy its code into this repository or ship it in the Mac app. Game files, firmware fonts and generated game content are supplied locally by the user and are excluded from public source and releases.
