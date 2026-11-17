# Credits and third-party notices

Kokiri derives its initial native runtime, static ARM64 rewriting and Metal graphics from [MacNativeGames](https://github.com/ly05010419/MacNativeGames) contributors under MIT. The root [LICENSE](LICENSE) preserves that copyright. [SOURCE_MANIFEST.json](engine/SOURCE_MANIFEST.json) records imported revisions and source hashes; [LICENSE.upstream](engine/LICENSE.upstream) preserves the original license text.

Engine dependency licenses remain beside the source. Consult [COPIES.md](engine/third_party/COPIES.md) for adaptation provenance and [UPSTREAM_NOTICES.md](engine/third_party/UPSTREAM_NOTICES.md) for the inherited dependency inventory. The latter retains original monorepo path names; imported copies live beneath `engine/`.

The native Mac product uses [Sparkle 2.10.0](https://github.com/sparkle-project/Sparkle/releases/tag/2.10.0) under MIT. Its preparation script downloads the official artifact, verifies its pinned checksum and copies Sparkle's license into the built app. The repository does not contain that prebuilt framework.

The development save workshop uses pure save-model functions and inventory metadata from [Traiver/OOT-SW2SE](https://github.com/Traiver/OOT-SW2SE), with Christian Furr's macOS adaptations. Its [provenance](tools/kokiri-mcp/save_workshop/PROVENANCE.md) records the imported revision and scope; the adjacent [MIT license](tools/kokiri-mcp/save_workshop/LICENSE) preserves the original notice. Game/save bytes and upstream artwork are not included.

The catalog protocol, service and client code use the root MIT license. The reference pipeline dataset preserves the MacNativeGames MIT notice in [services/catalog/seed/LICENSE](services/catalog/seed/LICENSE) and its exact source revision/hash in the seed provenance. No game or shader-source license is granted by this metadata dataset.

Build tools fetched into an external cache retain their own licenses. The optional external ZBIC decoder is a GPLv2 build utility; Kokiri does not copy its code into this repository or ship it in the Mac app. Game files, firmware fonts and generated game content are supplied locally by the user and are excluded from public source and releases.
