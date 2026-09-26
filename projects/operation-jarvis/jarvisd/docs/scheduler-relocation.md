# Scheduler backend relocation — 2026-09-25 EDT

The scheduler and notification implementation moved from `.pi/scheduler/` into
`jarvisd/jarvisd_core/scheduler/`. Tests moved into `jarvisd/tests/scheduler/` and
are now discovered by backend verification. No engine rewrite, new API write
surface, changes to job definitions, or automatic notification activation.

## Initial installed cutover

Record: `projects/operation-jarvis/data/scheduler-migrations/20260926T013221Z/cutover.json`.
The entire migration directory is owner-only, ignored runtime data.

- Waited for the observed manual job to finish before stopping the periodic worker.
- Preserved original code, worker plist, database, completion receipts, and gate.
- SQLite backup + integrity check + logical-content comparison verified every
  table: 7 jobs, 500 results, 4 config rows, 2 registered devices, 209 outbox rows,
  418 delivery rows, sequence state, and no active scheduler locks at cutover.
- Moved the completion receipts and event locks into `data/session-notifications/`;
  verified receipt contents exactly and restored the original enabled gate.
- Switched `com.jarvis.pi-scheduler` directly to the backend runner. Its first
  normal launchd invocation exited 0. No manual job run or notification drain
  was used for verification.
- New and compatibility CLI status paths succeeded. The installed daemon returned
  HTTP 200 / `ok: true` for `/health`, `/api/v1/scheduled-jobs`, and a bounded
  `/api/v1/scheduled-job-results?limit=1` read.
- The initial cutover did not restart the HTTP daemon, native apps, terminal, or
  audio services; temporary exec-only adapters served their old command paths.

## Final cutover: no compatibility layer

At the owner's request, removed `.pi/scheduler/` entirely and removed
`.pi/runtime/session-notifications/`, including its enable-marker symlink.
There are no legacy entry scripts or runtime aliases. All scheduler and
completion state remains under Operation JARVIS data.

The installed frozen HTTP daemon now receives an explicit
`JARVISD_SCHEDULER_RUNNER` pointing directly to the backend. Its original plist
and pre-restart service PIDs were backed up under the migration record's
`remove-compatibility/` directory. The watchdog was paused, the daemon was
restarted after waiting for a quiet child-process interval, and the watchdog
was restored. No scheduler worker, terminal, audio, or device service was
restarted for this final cutover. Health, jobs, and bounded results API reads
all succeeded after the old paths were deleted.

Existing Pi sessions must `/reload` to replace their in-memory adapters. Native
source already uses the new fixed SSH registration command; older installed
binaries require rebuild/reinstallation for future registration changes. They
were not rebuilt or installed during this backend migration. Existing APNs
registrations and notification state were not modified.

See the [backend README](../jarvisd_core/scheduler/README.md) for current consumer
paths and rollback that preserves post-cutover state rather than replaying it.

The existing backup project's required paths and synthetic restore fixtures were
updated narrowly so backups target the relocated backend/database. Other existing
work in that project and `.gitignore` was preserved.

## Verification

- 741 backend tests passed, including 50 scheduler/storage/layout tests and
  explicit assertions that retired `.pi` locations do not exist.
- 5 Pi-adapter/client-path tests passed: root/nested working directory resolution,
  backend ownership, and the native registration command.
- Existing backup project's 10 offline/local-repository tests.
- Shell syntax checks and `git diff --check`.
- Native registration command source/assertions updated; no new native build was
  installed, and no actual push or registration was triggered as a test.

## Remaining `.pi` ownership audit (not migrated in this change)

The scheduler is now backend-owned; this is not a claim that all other `.pi`
components are already thin adapters. Next candidates are:

1. `.pi/memory/memory.py` and its SQLite store: application memory service behind
   a Pi adapter, with a separate storage migration.
2. `.pi/extensions/50-browser/chrome-bridge-daemon.mjs` and browser provisioning
   helpers: separate transport/service lifecycle from the Pi tool definitions.
3. Session-status persistence/pruning inside `46-local-pi-session-status.ts`:
   retain Pi event observation in the extension; consider moving durable
   housekeeping behind a backend interface without adding a process per heartbeat.

Pi settings, tool schemas/rendering, lifecycle hooks, and harness-specific test or
patch scripts can remain in `.pi`; unrelated service relocations need their own
compatibility and live-cutover review.
