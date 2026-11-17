# Mods and Saves

Add dedicated native Mods and Saves destinations to Kokiri. Mods owns an independent library with named loadout profiles and compatible local MacNative Mods imports. Saves shows the actual connected profile and its readable save slots.

Approved interface direction: Compact split. Mods takes its compact table, filters/search and selected-pack inspector from MacNative Mods, retaining Kokiri's forest/cream identity. Saves uses a compact slot list beside one selected preview; inventory and technical file details are collapsed. Keep secondary actions in menus and remove repeated cards, descriptions and headings.

Acceptance:
- Mods supports importing compatible RomFS packs, copying the local MacNative Mods OoT library, selecting and managing named profiles, enabling packs and changing load order.
- Imports copy into Kokiri's separate store. Foreign libraries and their selected/applied state stay untouched. Unsupported packs and unsafe paths produce visible errors.
- Ordinary compatible game launches prepare a validated, session-specific overlay. Profile changes apply to the next launch; a running game's profile is never changed in place.
- The existing private preview disables mod overrides in its native entry. Show this limitation explicitly while retaining library/profile management and ordinary unmodded Play. Do not claim that it applied a profile.
- Saves reads the same connected profile used for Play, including a private binding when present. Display real decoded slot details, embedded previews when available, refresh state and bounded malformed/unsupported-file errors.
- Saves remains read-only. No migration, editing, deletion, restoration or silent fallback to an older profile.
- A missing, invalid or subsequently changed private binding makes the player profile unavailable. Saves and Home/Settings reveal actions never fall back to the ordinary profile in a requested private preview.
- Meaningful temporary-fixture tests cover profile persistence, compatible manifests, unsafe input rejection, real save-layout decoding and malformed data. Build the native app under the exclusive CPU reservation and obtain independent review.

No engine rebuild, native preview capability change, gameplay launch, installation or public release is included. A future private runtime upgrade needs its own isolation/compatibility tests and Integration scheduling. Keep game assets, saves, imported packs and local evidence outside source.
