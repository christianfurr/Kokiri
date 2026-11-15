# Home-server catalog

This Node/SQLite host reuses `src/worker.ts` and its protocol validators. It
implements the server's narrow D1 operations with one atomic SQLite transaction
per batch. There is no web SQL/admin/publication endpoint and no signing key.
The service shares metadata only; no game files, shaders, caches or saves.

The root GET route serves a static catalog homepage with the current public
preview status and a link to `/v1/protocol`. It uses a stylesheet-hash CSP and
loads no scripts, fonts, trackers, or remote assets. The homepage's paused
contribution status matches the installed default-off ingestion configuration;
review its copy before opening community ingestion.

Public reads do not require an account. The reviewed tunnel should allow only
the root homepage, `/v1/protocol`, exact lowercase 64-hex context manifest paths,
and exact lowercase 64-hex pack paths. The first rule must protect
`^/v1/contributions(/.*)?$` with the contribution-control Access application's
exact audience. Ingestion remains disabled in the service independently of that
Access policy. Unmatched paths return 404. Enable URL normalization and verify
encoded/normalized write-path variants before activating changes. The Node
listener remains local; no router port forwarding is required.

Public access does not publish inbox records. The offline publication process
prepares curated packs and signed manifests; startup and restore validate the
published data against pinned public keys, and clients independently verify the
manifest signature and referenced pack hashes. No signing private key or web
publication endpoint is installed on this host. Production signing, trust-key
configuration, and admission of the first real catalog remain separate gates.

## Protections

| Boundary | Enforced value |
| --- | --- |
| Listen address | `127.0.0.1` only |
| Anonymous ingestion | Off unless explicitly configured |
| HTTP requests / POSTs | 300 / 60 per minute, global buckets |
| Concurrent requests / connections | 8 / 32 |
| Header / request-body bytes | 8 KiB / 64 KiB |
| Body receive / HTTP receive and socket-idle budgets | 5 / 10 seconds |
| Main SQLite database | 1 GiB maximum pages |
| Free filesystem reserve | 512 MiB; backup also reserves snapshot space |
| Database acknowledgments | Only after transactional commit; duplicates idempotent |
| Incoming records | Strict existing metadata schema; quarantine only |
| GET routes | Static homepage, protocol, curated immutable packs and signed manifests |
| Backup retention | Seven verified snapshots plus SHA-256 sidecars |
| Unit limits | 256 MiB memory, no swap, one logical CPU, 32 tasks, 128 FDs |

Both units run as the existing unprivileged user, with no new privileges or
capabilities. User/mount namespaces hide the rest of the home directory; only
the catalog root is visible read-only, and the service's data directory (or
backup unit's snapshot directory) is writable. User/system D-Bus runtime paths
are inaccessible; the HTTP/SQLite host does not need these session sockets.
Private temporary/device views
and the web service's Node filesystem permissions add separate boundaries. The
backup process uses the OS filesystem sandbox without Node's permission mode:
that mode disables `fsync`, which backups deliberately require for durability.
The backup's only writable bind remains its own snapshot directory. No request bodies,
client addresses, user agents, headers or raw parser errors are logged. Health
logs contain aggregate counters; unit log rate limits bound their frequency.

These controls do not make the shared home server a dedicated security boundary:
the administrator, root and unrelated processes with the same user identity can
change its files. Node's permission model is defense in depth, not an OS sandbox
replacement. The host still needs supported OS/runtime maintenance. Resource
caps intentionally prefer a rejected/retried contribution over disk or memory
exhaustion; a global bucket can be exhausted by one caller. Public ingress needs
edge abuse controls in addition to these origin limits.

The ten-second HTTP receive/socket-idle settings are not an absolute deadline
for the entire response handler. Body reception has its own five-second timer;
bounded SQLite work has a one-second busy timeout. Process CPU/memory limits
remain the outer boundary if a synchronous operation stalls.

Both units pin their threads to logical CPU 0. Check that this CPU is available
on the target host before installation. They also request CPU quotas of 20% of
one CPU (backup 10%) where the controller is delegated. On the assessed host,
only memory and PID controllers are delegated to user services: `cpu.max` is
absent, so those quota settings are **not enforced**. The independently checked
CPU affinity is the active CPU boundary there, alongside request-rate limits;
it does not imply a 20% time quota.

## Build and tests

Use a supported Node LTS release (the deployment test used verified Node
24.22.3). `npm ci` is for build dependencies only; deployed bundles have no npm
runtime dependencies. Run from `services/catalog`:

```sh
node --test --test-concurrency=1 tests/selfhost/server.test.mjs
node selfhost/build.mjs /YOUR/EXTERNAL/STAGE
```

The fixture tests use temporary SQLite files and real loopback HTTP, including
valid concurrent submissions, bounds/time/rate/concurrency rejection, whole-batch
quota rollback, default-off ingestion, private path checks, signature/hash
verification, and restored committed data. They do not use game content.

## Private installation

Review the exact bundles, hashes and units before activation. Keep the machine's
system Node and existing services unchanged. Under a newly owned private root
`~/.local/share/kokiri-catalog` create `runtime`, `releases`, `data` and `backups`.
The root and writable directories must have mode 0700, owned by the service user;
SQLite/snapshot files must be regular, non-hardlinked, owner-private files.
Precreate writable directories before applying the Node filesystem restrictions.

Place an official checksum-verified supported Node runtime under `runtime`.
Put the bundle, migration, licenses and a public-only `trusted-keys.json` into a
versioned release directory, then set `current` to that release. For an empty
private stage, the trust file is `{}`; this deliberately cannot validate a
published manifest. Never put synthetic fixture keys into that trust file.
Private signing keys remain off the public service.

The checked-in user units point at these exact paths and localhost port 8787.
Copy reviewed units into `~/.config/systemd/user`, verify them, reload the user
manager, then enable/start the catalog and backup timer. They require working
unprivileged user/mount namespaces and persistent user services. Test actual
file hiding/write denial and cgroup limits; do not silently remove protections
when the host rejects them.

On 2026-11-15 an isolated host probe verified home-file hiding, a read-only
code bind and a writable own-data bind. A bundled CLI probe returned protocol
HTTP 200, rejected disabled ingestion with 503, exited cleanly on SIGTERM,
created a verified online backup and restored it into a fresh directory.
Outside-file reads were denied under Node filesystem permissions. Initial
empty-service resident memory was approximately 64 MiB; this is a startup
snapshot, not a loaded-service peak or throughput benchmark. Final persistent
unit activation and public reachability are separate deployment receipts.

## Backups, restore and rollback

`backup.mjs` uses SQLite's online backup API. It verifies SQL integrity and quota
accounting plus curated signatures/pack hashes using pinned public keys. It
hashes and syncs a fresh snapshot and sidecar, then publishes them and prunes
only its own verified old snapshots. It never copies a live main database file
without its WAL context. Failures preserve existing snapshots and emit a generic
failure event. Monitor the backup unit/timer; the process does not invent a
successful backup when checks fail.

The backup unit requires the catalog already active, and does not start a
manually stopped service. Its read-only WAL access was verified while the
catalog was running. Closed WAL databases can require writable sidecars, so
offline recovery uses the separate restore tool rather than relaxing the
backup's data mount. Stale owner-private backup staging files older than a day
are removed on a later run; a killed unit never promotes its partial snapshot.

Copy snapshots and their hashes off the server, validate hashes on receipt,
restrict permissions, and retain an independently verified copy. A same-disk
backup is not protection against losing the host/disk. The daily timer schedules
local snapshots; an off-host copy schedule is a distinct operations task.

Rehearse a restore with the bundled tool and a hash recorded outside the source
database directory:

```sh
KOKIRI_CATALOG_RESTORE_ROOT=/NEW/OWNED/RESTORE/DIRECTORY \
KOKIRI_CATALOG_TRUSTED_KEYS=/READONLY/PUBLIC-KEYS.json \
node /STAGE/restore.mjs /SNAPSHOT/catalog.sqlite EXPECTED_SHA256
```

The restore destination must not exist. The tool checks the digest, migration,
integrity, quota accounting and public content, and reports `promoted:false`.
It never stops a service or overwrites/promotes live data. Preserve failed
restore directories for diagnosis; do not point the service at one.

For code rollback, stop this catalog unit, preserve a verified snapshot and the
current release identity, switch only `current` to the prior reviewed compatible
release, then start and verify the protocol plus default-off ingress. For data
recovery, keep the service stopped, retain the failed data directory, and promote
only a separately restored/verified directory after review. Never overwrite a
running executable or an open SQLite file. Other host services are out of scope.

## Public rollout gate

Private loopback staging does not make a public library. A reviewed HTTPS
hostname/tunnel and edge abuse rules, real offline signing/publication, an
independently pinned app public key/origin and end-to-end native verification
are still required. No catalog availability or FPS claim follows from these
HTTP tests. Native offline/mixed-library provenance and mesh admission retain
their existing refusal gates. Keep POST disabled until the complete ingress
path is reviewed; no router port forwarding or broad host access is needed.
