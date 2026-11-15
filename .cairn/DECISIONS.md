# Decisions

- 2026-11-15: The user chose Kokiri and authorized a standalone repository, not a GitHub fork. Preserve MacNativeGames and third-party notices and credit the source lineage.
- 2026-11-15: Keep native ARM64 execution and Metal as the initial foundation. Preserve game identity separately from product branding; do not rebuild the CPU frontend without evidence.
- 2026-11-15: Keep game dumps, generated code, shaders, caches, fonts and saves outside the public source repository.
- 2026-11-15: App updates use signed releases; the shared shader catalog has an open, versioned protocol and separate backend/compiler compatibility namespaces.
- 2026-11-15: The user requested automatic contributions. New public users make a one-time choice; contributions contain pipeline metadata, not saves, logs or extracted shader code.
- 2026-11-15: README statistics and screenshots must come from the implemented app and documented measurements. Existing severe FPS drops, cold hitches, memory peaks and terrain corruption remain acceptance work.
