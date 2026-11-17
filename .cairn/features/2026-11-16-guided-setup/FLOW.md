# Proposed first-run and game-management flow

Status: user approved and implemented in source, 2026-11-16. See REVIEW.md for verification boundaries. Supersedes the permanent Setup sidebar direction.

## Entry and navigation

Resolve the configured installation before choosing the initial screen. A valid connected installation opens Home. No configured installation opens a separate compact welcome/setup window, without the main sidebar or Play toolbar. A missing or invalid previously connected installation opens Home with recovery actions; preserve the binding, profile and caches, and do not silently start a fresh setup.

Remove Setup from the sidebar entirely. Returning users get Home, Performance, Shader Library and Settings. Settings > Game contains the connected app, Show in Finder, Connect Another Game and Prepare from Game Files. Existing-game connection and replacement remain unavailable while a game or preparation runs. Cancelling management preserves the working connection.

## First run

1. Welcome: Kokiri mark, concise title and one primary Add Game action. Secondary Connect Existing App action skips preparation after inspection.
2. Game files: one file/folder selection target, supported-format help on demand and inline actionable errors. Preserve inputs when going back. Recognize supported existing apps and route to connection rather than rebuilding.
3. Firmware fonts: one folder selection target, explain the required extracted font files and manifest. Raw firmware archive import is not implemented and must not be advertised. Structural checks do not claim full integrity verification.
4. Prepare: summarize chosen files and storage, check available tools/storage before starting, and show observed preparation stages with optional logs. Provide progress without an invented percentage. Storage overrides belong behind Change Location; developer source controls remain preview-only prerequisites and must not be presented as a finished consumer install experience.
5. Ready: verified installed game, optional import of an existing save while closed, then Open Kokiri. Play is available on Home. Preparation completion does not claim whole-game visual/performance acceptance.

Closing an unfinished wizard must offer a clear exit while preserving resumable completed build work. Do not imply an installer keeps working after the app exits unless lifecycle handling is implemented. Persist draft selections only as needed for resumability and revalidate permissions and paths on return.

## Failure and recovery

Invalid input stays on its step with a concise reason and replacement picker. Interrupted preparation preserves paths/completed work and offers retry. A disconnected drive or moved app offers Locate Game and Try Again on Home; it does not discard saves or ask for firmware again. A candidate replacement becomes the configured installation only after inspection succeeds.

## Visual direction

Use a compact centered native window, one heading, one selection region and one primary action. Keep the established Kokiri mark and forest accent; use system typography, restrained spacing and plain labels. Remove stacked rounded containers, repeated subtitles, uppercase eyebrows and always-visible format paragraphs. Put lengthy supported-format details behind Help. Keep Back and Continue in consistent footer positions and errors adjacent to the relevant selection. Reserve enough room for readable errors at supported accessibility sizes.

Home prioritizes the game and Play, with a small last-session summary and save access. Detailed shader counts and preparation status belong in Shader Library; settings and replacement actions belong in Settings.

## Verification before delivery

Check clean first run, valid existing installation, missing external drive, invalid input, back navigation, cancel/reopen, preparation interruption/retry, connection failure and existing-save preservation. Verify keyboard focus, window sizing, inline errors and preparation state while navigating. A clean-Mac packaged import remains a separate delivery gate from source-build UI tests.
