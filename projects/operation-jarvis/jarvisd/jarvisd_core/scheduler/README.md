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
