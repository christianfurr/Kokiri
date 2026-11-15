# Native startup screen

`runtime/kokiri_startup.h` draws Kokiri's original leaf-K mark and a static forest background inside the native game window. The standalone builder copies the repository's original `assets/brand/kokiri-mark.png` into `Contents/Resources/KokiriMark.png` before signing the game app. No game artwork is used by this screen.

The existing runtime callbacks supply verification bytes, imported item counts, shader/pipeline warm-up counts and phase descriptions. Work without a known total uses an indeterminate indicator. A percentage describes the current counted phase, not an estimated overall loading duration. No timer advances progress.

The screen dismisses after a real frame has been presented and either warm-up has finished or the renderer has explicitly released the title. This preserves the game's original opening and allows title-visible background warm-up. It requires no editor bridge or launcher environment variable. The artwork does not capture mouse or keyboard input; ordinary window/menu close and settings controls remain available. macOS may verify an app before its process starts; this in-process screen cannot cover that system check.

Validation uses `python3 -I -m unittest discover -s engine/tests -p test_startup_view.py -v`. The offscreen AppKit fixture loads the real original mark, checks the readiness cases and responsive layout at six viewport cases, and renders the actual view. Its phase text is explicitly labeled synthetic. A fresh game build must separately verify the logo resource and actual startup/dismissal before being described as gameplay validated.
