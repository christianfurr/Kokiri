# Reference metadata seed

`reference/` contains a deliberately small public MIT sample: the first eight
distinct records of each supported kind from MacNativeGames commit
`597e9bca63e34560a9dc20a75168abae258e8bdb`,
`games/oot/assets/shader_list.tsv`. It contains identifiers and descriptors,
not shader code. The upstream list describes OoT Switch 2 version 131072.

The original attribution and MIT terms apply; see `LICENSE` in this directory.
This is not a CC0 relicense. Kokiri is an independent project.

All compiler, translator, content, target and option fingerprints are unknown in
this historical list. The context is therefore **reference-only**. It cannot
warm either the public v28 or private v23 runtime without separate, proven
context qualification. It contains no executable libraries or native binaries.

`manifest.unsigned.json` is intentionally unsigned and is not served by the
Worker. An operator must review provenance, qualify context if applicable,
and supply an offline signing key before publication. No key or deployment
has been created for this seed.

Reproduce from the pinned public list using `scripts/build-seed.ts --stdin
--output <fresh-directory> --per-kind 8`. Omitting `--per-kind` imports the
supported records of the whole explicitly supplied list. The importer validates
all supported rows before writing. Locator rows and unimplemented border recipe
rows are excluded and counted. It never searches local caches or game data.
