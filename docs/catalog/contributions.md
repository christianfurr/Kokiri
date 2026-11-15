# Contributions and trusted publication

The first-run choice is `undecided`, with network contribution disabled. One
explicit `enabled` choice is remembered; the runtime can then enqueue supported
metadata automatically in bounded batches. `disabled` stops all future chunks
and retries. An already sent request may finish; toggling off cannot retract
published public metadata. A failed attempt to persist opt-out also stops new
requests for the current client session and surfaces the error.

The queue retains records offline, deduplicates context+record IDs, and retries
with bounded exponential backoff (2 seconds through 1 hour). Successful exact
acknowledgments remove records. Invalid/incomplete acknowledgments preserve them.
An application actor owns the TS queue; Python permits concurrent enqueue but
requires one active flusher. No endpoint is built in. HTTPS redirects are refused.

Only validated metadata envelopes cross the adapter boundary. No raw TSV file,
game/shader source, binaries, saves, logs, screenshots, paths, usernames, device
serials, IPs or account IDs are accepted as contribution fields. The Worker does
not log request payloads, IPs or user agents; provider network processing still
occurs when a user elects to send an HTTPS request. Request logging is disabled
in the checked-in config. No production retention policy/deployment exists yet.

Anonymous input goes to `inbox`; public GET routes cannot read it. Automatic
contribution does **not** mean automatic publication or blind trust. The operator
must check license/provenance, reproduce recipes against the claimed context,
review resource costs, and then build bounded curated packs. The offline tool
`scripts/prepare-publication.py` validates those packs and accepts an explicitly
provided Ed25519 signing key to produce a **fresh local SQL file**. It does not
create keys, deploy, upload, or execute SQL. Keys remain outside the Worker.
Only reviewed SQL is later applied by the operator. Revisions/replacements need
an explicit migration; the initial publication tool refuses replacing a manifest.

The public MacNativeGames seed retains MIT terms and attribution. No private
playtest metadata is seeded. Its unknown fingerprints make it reference-only,
not a warmed-cache compatibility promise.
