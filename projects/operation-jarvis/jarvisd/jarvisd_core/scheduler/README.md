# Private scheduler backend

Operation JARVIS owns scheduling, execution, SQLite history, APNs registration/
delivery, and Pi-session completion receipts. Pi extensions only translate tool
calls or lifecycle events into fixed backend CLI invocations. The HTTP daemon
continues exposing sanitized read-only job/result projections; no new remote job
administration capability is introduced.

## Layout

- `runner.py`: existing scheduling engine and CLI, retained intact for relocation.
- `apns_provider.py`, `apns_registration.py`, `session_completion.py`: notification
  implementation, moved with its existing safety gates and no-replay behavior.
- `migrate_storage.py`: explicit offline SQLite backup/relocation with integrity
  and complete logical-content verification; never executes jobs or deletes source.
- `../../tests/scheduler/`: offline regression tests, included by `../../verify.sh`.
- `../../../data/scheduler/scheduler.sqlite`: jobs, history, registry, outbox.
- `../../../data/session-notifications/`: enable gate, private receipts, event locks.

Paths above are relative to this directory. From the repository root:

```sh
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json status
.venv/bin/python -m unittest discover -s projects/operation-jarvis/jarvisd/tests/scheduler -v
node --test .pi/tests/cron.test.mjs
```

Runtime directories are mode 0700, databases and sidecars 0600, and all data is
gitignored. The backend enforces these permissions without requiring Pi startup.
`JARVIS_SCHEDULER_DIR`, `JARVIS_SCHEDULER_DB_PATH`, and
`JARVIS_SESSION_NOTIFICATIONS_DIR` may explicitly override storage locations.
Pi settings remain in `.pi`: reading model configuration does not make Pi the
owner of execution or persistence.

## Job categories

Each job has an optional `category` text column, added automatically and
idempotently to existing databases. Missing, blank, or `Uncategorized` values use
NULL storage and display as **Uncategorized**. New labels are whitespace-normalized,
title-cased, limited to 64 characters, and reject control characters/recognized
credentials or private paths. There is no separate registry or category hierarchy.

From the repository root:

```sh
RUNNER=projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py
.venv/bin/python "$RUNNER" list --category Shopping
.venv/bin/python "$RUNNER" set-category gear-hunter --category Shopping
.venv/bin/python "$RUNNER" set-category "Keyboard lights" --category "Home Automation"
# Explicitly clear an assignment:
.venv/bin/python "$RUNNER" set-category gear-hunter --category ""
```

`add` also accepts `--category`. `set-category` updates only category/updated-at;
it does not enable, run, reschedule, recreate, or delete a job or touch its history.
Mutation requires owner intent. Human-readable `list` groups alphabetically,
Uncategorized last, preserving existing schedule ordering within each group.
Filtering is case/whitespace-insensitive; `list --category Uncategorized` finds
unassigned jobs. Disabled jobs remain in CLI inventory.

`list-public` includes a sanitized `category` label without changing its existing
job ordering or summary. Older clients ignore the extra field; newer clients
accept missing/null categories. The iPhone and Watch use shared category grouping
for enabled jobs only, preserving thread IDs, read state, and notification routes.
The HTTP daemon also explicitly projects/validates `category`; deploying only the
runner will not update an already-running/frozen daemon's field allowlist. Native
rollout requires the updated daemon plus rebuilt iPhone/Watch apps. Deploy/restart
the daemon and install signed apps only through the owner-approved release flow;
changing category assignments does not itself restart services. No remote
category-write API or notification payload change is introduced.

Before applying assignments, create a private SQLite online backup (including WAL
contents) and verify its integrity. Keep job-specific assignments out of schema
migrations. Roll back code without restoring an old database over newer executions;
the additive column is safe for old code to ignore.

## Worker and consumers

The one-minute launchd worker remains independent of the HTTP process. Its label
stays `com.jarvis.pi-scheduler` to preserve service-health and operational identity;
its executable points directly here. No job IDs, schedules, models, enabled states,
next-run times, retained sequences, dispatch flags, or device registrations change.

There are no compatibility scripts or runtime symlinks in `.pi`. The Pi tool and
lifecycle extensions invoke this backend directly; notification enable gates and
receipts are backend-owned. Native source uses the backend registration command.
The installed frozen HTTP daemon selects this runner through the explicit
`JARVISD_SCHEDULER_RUNNER` launchd environment setting; new daemon source also
uses this path by default.

Pi sessions opened before relocation must `/reload` before using scheduler tools
or completion notifications. Older native binaries must be rebuilt/reinstalled
to use the new fixed SSH registration command. Existing registered-device state
is preserved; do not unregister/re-register devices just to test relocation.

## Cutover / rollback

1. Wait for every scheduler/manual-job/notification child to finish; never kill a
   running job for relocation. Unload only the periodic scheduler while idle.
2. Temporarily close the completion enable gate, retain its exact contents, and
   preserve old code, worker plist, SQLite backup, and notification state in an
   owner-only migration directory under `projects/operation-jarvis/data/`.
3. Copy the SQLite store with `migrate_storage.py`; verify integrity and all tables
   (including sequences, registry/outbox, receipts, and flags), not just jobs.
4. Point consumers directly at the backend and remove retired `.pi` locations.
   Move completion state and restore its unchanged enable gate. Reload old Pi
   sessions and rebuild native clients as needed.
5. Point the worker plist at this backend and bootstrap it. Its existing
   `RunAtLoad` may run normally due jobs; do not invoke manual test runs or drain
   notifications. Verify CLI status, launchd exit status, and read-only app API.

On rollback, stop the worker and quiesce writers again. Preserve post-cutover
state first. Restore the old code/plist but copy the **current** database and
receipts back to their old paths with SQLite-safe copying. Do not blindly restore
an old database snapshot after jobs or deliveries have run: that can replay work.
The initial snapshot is for verification/disaster recovery, not automatic replay.

This relocation intentionally avoids a simultaneous engine rewrite. A subsequent
refactor can separate scheduling/storage/executors and move shared notifications
into a sibling package without changing these adapter contracts.
