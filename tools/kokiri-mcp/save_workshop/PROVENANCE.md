# Save domain provenance

`domain.cjs` contains the pure constants and save-model functions from `Vendor/OOT-SW2SE/editor.html` in the existing OoT Editor checkout. Its upstream base is Traiver/OOT-SW2SE commit `de26f03d0a299e39e5536bf68eeef9b251fadba1`; Christian Furr's macOS adaptation adds supported inventory removal, vitals, travel and song rules. MIT notice is preserved in LICENSE. `catalog.json` contains that source's inventory/registration metadata and only its named Boolean edit allowlist. No game/save bytes, artwork or generated executable code are included.

Local extraction source SHA-256: `d178fc14718e3bd6b26f6a1276759facf1604b336809ed2b5938e7483c027e08`.

The source checkout was read-only. UI, dialogs, DOM initialization, web bridges and arbitrary field editing were not imported. The JSON CLI wraps this domain with typed changes; no raw field hashes/offsets are accepted. Equipment ownership uses supported inventory rules; arbitrary equipped-slot replacement and live memory edits are unsupported.
