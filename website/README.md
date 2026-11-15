# Kokiri website

Static HTML, CSS and JavaScript. No package install, analytics, external font service or build step. The interactive HUD uses sample values and earlier runtime captures; it does not run the game or measure browser performance.

Preview from the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory website
```

Open http://127.0.0.1:4173. Check the four HUD corners, four sizes (75–150%), three detail modes, both scenes and Reset. Inputs use native keyboard navigation. The site supports reduced motion and remains readable without JavaScript.

The Pages workflow uploads only this folder. Assets use relative paths so the site works at `/Kokiri/`. Source/build guides link to the repository's default `HEAD`, not a fixed release. Before changing release claims, verify the matching app/runtime and update the root README too.

See [asset provenance](assets/PROVENANCE.md). Keep local QA screenshots and game/build output out of this folder.
