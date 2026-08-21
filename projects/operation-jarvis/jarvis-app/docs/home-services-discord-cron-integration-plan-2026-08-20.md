# Home Services integration plan — Discord bot and scheduled jobs

**Prepared:** 2026-08-20
**Baseline:** JARVIS `0.2.0 (9)`
**Target candidate:** JARVIS `0.2.0 (10)`
**Implementation status:** read-only phase complete and physically deployed on iPhone and Watch; optional bot, scheduler, and job mutations remain disabled.
**Scope:** expand the Home Services section without changing Watch, widget, plug, purifier, or room-audio behavior.

## 1. Goal

Make Home accurately represent the operational JARVIS runtimes on `mac-mini-64`:

1. JARVIS Discord Bot (`com.operation-jarvis.discord-bot`)
2. Room Audio Server (`com.operation-jarvis.room-audio-server`)
3. Discord Cron Scheduler (`com.jarvis.pi-discord-cron`)
4. The scheduler's individual Discord/Pi jobs
5. `jarvisd`, retained as a protected, read-only daemon card

The Discord bot and scheduler are LaunchAgents. Individual scheduled jobs are records managed by `.pi/discord-cron/runner.py`; they are not LaunchAgents and must not be added to `services.json` as fake services.

## 2. Current baseline

- `jarvisd/services.json` registers only `room-audio-server`.
- `GET /api/v1/services` returns LaunchAgent state for registered services.
- `POST /api/v1/services/{name}` supports `start`, `stop`, and `restart` through a fixed `launchctl` adapter and emits audit events.
- `jarvisd` and its resurrector are protected from service actions.
- Home polls services and daemon health every 15 seconds.
- The cron runner is authoritative for job definitions and exposes machine-readable `--json list` and `--json status` commands.
- The current five jobs are enabled, but their membership is dynamic and must never be hard-coded into Swift.

## 3. Product boundary

### Include

- Live loaded/running/PID status for the Discord bot, room-audio server, and cron scheduler.
- Stable display names, descriptions, ordering, criticality, and server-declared allowed actions.
- Sanitized scheduled-job telemetry: name, ID, schedule kind/expression, enabled state, next run, last run, last status, run count, and optional description.
- Independent loading/error states so a cron-list failure does not hide LaunchAgent status.
- Local-time display on iPhone; backend timestamps remain ISO-8601 UTC.
- Existing event audit for service actions.

### Exclude from the first release

- Job creation, deletion, prompt editing, model selection, or Discord channel setup.
- Job prompts, model names, Discord channel/thread IDs, database paths, local command lines, environment values, or run output.
- Canceling an already-running scheduled job. Stopping the scheduler only prevents future due-job launches; it does not promise to kill an existing child process.
- Watch and widget service controls.
- Control of `jarvisd` or `jarvisd-resurrector`.

## 4. Backend contract

### 4.1 Register the two missing LaunchAgents

Extend `jarvisd/services.json` with:

- `discord-bot`
  - label `com.operation-jarvis.discord-bot`
  - plist `~/Library/LaunchAgents/com.operation-jarvis.discord-bot.plist`
  - display name `JARVIS Discord Bot`
- `discord-cron-scheduler`
  - label `com.jarvis.pi-discord-cron`
  - plist `~/Library/LaunchAgents/com.jarvis.pi-discord-cron.plist`
  - display name `Scheduled Jobs Runner`

Add metadata understood by `jarvisd`, not trusted from the client:

```json
{
  "displayName": "JARVIS Discord Bot",
  "sortOrder": 10,
  "critical": true,
  "allowedActions": ["start", "stop", "restart"]
}
```

Room audio receives equivalent metadata with a later sort order. The API must report `configured`/plist availability separately from `loaded` and `running`. `jarvisd` must enforce each service's `allowedActions`; hiding a button in Swift is not authorization.

Before exposing Start for the Discord bot, add or document a canonical, path-safe installer for its LaunchAgent. The current user plist exists but is not represented by a tracked installer in the repository. The cron runner already owns generation of its scheduler plist.

### 4.2 Add a dedicated scheduled-jobs read endpoint

Add:

```text
GET /api/v1/scheduled-jobs
```

Suggested response:

```json
{
  "ok": true,
  "generatedAt": "2026-08-21T00:00:00Z",
  "summary": {
    "total": 5,
    "enabled": 5,
    "running": 0,
    "errors": 0
  },
  "jobs": [
    {
      "id": "job_…",
      "name": "daily-job-search",
      "kind": "cron",
      "schedule": "0 9 * * *",
      "enabled": true,
      "nextRunAt": "2026-08-21T09:00:00Z",
      "lastRunAt": "2026-08-20T09:00:00Z",
      "lastStatus": "success",
      "runCount": 79,
      "description": null
    }
  ]
}
```

Implementation rules:

- Invoke the canonical runner with fixed argv and no shell, using a short bounded timeout.
- Prefer adding a runner `list-public`/`--public` mode that emits only the approved fields; sanitize again at the `jarvisd` boundary.
- Never read or mutate the SQLite database directly from Swift or `jarvisd`.
- Cap job count and every string field; reject malformed/non-object runner output.
- Return a truthful unavailable response on runner timeout/nonzero exit without leaking stderr, paths, prompts, or configuration.
- Apply existing native API authentication and request logging.
- Do not put jobs into `/api/v1/state`; keep the independent 15-second Home service poll.

### 4.3 Optional second-stage job actions

Only after read-only telemetry passes should the app add:

```text
POST /api/v1/scheduled-jobs/{id}
{"action":"enable" | "disable" | "run"}
```

The backend must allow only those three fixed actions and fixed validated IDs. `enable`/`disable` require confirmation and an audit event. `run` must be detached, return an accepted/request ID response promptly, and explain that output is posted to Discord. Do not expose add/remove/edit/setup through the native API.

## 5. JARVISKit and AppState

Add typed models rather than using `[String: JSONValue]`:

- `ServiceStatus` and `ServicesListResponse`
  - retain current status fields
  - add `displayName`, `sortOrder`, `critical`, `configured`, and `allowedActions`
- `ScheduledJob`
- `ScheduledJobsSummary`
- `ScheduledJobsResponse`

Extend `JarvisAPI`/`JarvisClient` with `scheduledJobs(_:)` and, only in the second stage, `scheduledJobAction(_:)`.

Add independent AppState properties:

- `lastScheduledJobs`
- `scheduledJobsLoaded`
- `scheduledJobsLoading`
- `scheduledJobsErrorMessage`

`pollHomeServices()` should fetch services, scheduled jobs, and health concurrently every 15 seconds. A failure in one request must preserve the last successful value from the others. `clearConnection()` must reset the new state.

## 6. Home UI

Keep Services at the bottom of Home and render this order:

1. **Runtime services**
   - JARVIS Discord Bot
   - Room Audio Server
   - Scheduled Jobs Runner
2. **Scheduled jobs**
   - summary such as `5 of 5 enabled`
   - one compact row/card per job
3. **jarvisd**
   - protected version/uptime card

Runtime cards should use server-provided display names and allowed actions. Critical service actions require impact-specific confirmation:

- Discord bot Stop/Restart: text and voice responses will be interrupted.
- Scheduler Stop/Restart: future due-job dispatch pauses; already-running work may continue.
- Room audio Stop/Restart: room voice becomes temporarily unavailable.

Scheduled-job rows should show:

- enabled/disabled indicator
- human-readable schedule plus the original expression
- next run in the iPhone's local time zone
- last result and relative last-run time
- run count

Use a disclosure group or navigation detail if five or more rows make Home too long. Preserve Dynamic Type, VoiceOver labels, high contrast, stale/error captions, and minimum tap targets. Never infer a service or job action from stale/unknown status.

## 7. Safety and control policy

- Read-only polling ships first and cannot execute LaunchAgent or job actions.
- Service controls remain explicit button actions with a busy lock and confirmation for Stop/Restart.
- Add per-service server-side action allowlists.
- Preserve `jarvisd`/resurrector protection.
- Do not test Discord Bot Stop/Restart while the controlling conversation depends on that bot.
- Do not test scheduler Stop across a due boundary unless the affected job behavior is understood.
- Use the existing disposable LaunchAgent lifecycle fixture for automated and physical UI write validation first.
- Any real Discord bot, scheduler, or scheduled-job mutation requires a separate warning and explicit user authorization.

## 8. Test plan

### Backend

- Parse metadata and enforce per-service allowed actions.
- Report configured, loaded, running, and PID states independently.
- Protect `jarvisd` and resurrector even if misconfigured in `services.json`.
- Scheduled-job adapter: success, empty list, timeout, nonzero exit, malformed JSON, oversized output, unknown fields, and sanitization.
- Prove prompt/model/thread/channel/path fields never reach the native response.
- Auth tests for both scheduled-job GET and optional POST.
- Exactly one bounded audit event per accepted/rejected mutation.

### JARVISKit/AppState

- Decode all optional status/job fields and unknown future fields.
- Verify URL encoding for job IDs.
- Verify independent error retention and concurrent 15-second polling.
- Verify duplicate taps cannot issue duplicate service/job actions.
- Verify refresh fetches state, services, scheduled jobs, and health.

### UI

- Deterministic runtime ordering from `sortOrder`.
- Running/stopped/unloaded/unconfigured/unknown states.
- Five jobs, no jobs, mixed enabled states, running/error status, stale data, and long names.
- Maximum Dynamic Type, VoiceOver, dark mode, increased contrast, and Reduce Motion.
- Write-blocking mock must prove launch and scrolling issue GETs only.

### Regression

- `jarvisd` tests and live sanitized contract check.
- JARVISKit and AppState tests.
- iOS/watchOS simulator builds and signed generic-device build.
- Full `JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh`.
- Repository smoke suite, secret audit, identity audit, and `git diff --check`.

## 9. Delivery sequence

1. **Contract and safety tests** — add failing backend/Swift tests first.
2. **Runtime inventory** — register Discord bot and scheduler with metadata; add the canonical Discord bot LaunchAgent installer/documentation.
3. **Read-only job adapter** — add sanitized runner output and `GET /api/v1/scheduled-jobs`.
4. **Native models/polling** — typed JARVISKit API and independent AppState state.
5. **Home UI** — runtime group, scheduled-job list, critical confirmations, and accessibility.
6. **Mock validation** — simulator against a write-blocking backend; prove zero POSTs.
7. **Live read validation** — restart only `jarvisd`, verify the three runtimes and dynamic job list without changing their states.
8. **Build/deploy** — archive/export and install the same `0.2.0 (10)` product on the allowlisted iPhone and Watch.
9. **Physical read-only acceptance** — verify layout, local dates, error handling, and no service/job writes.
10. **Optional control phase** — only with separate approval, validate the disposable service first, then selectively authorize real service/job actions.

## 10. Physical build-10 checkpoint

- The exact signed archive was installed on the allowlisted iPhone and Watch;
  both inventories report `0.2.0 (10)`.
- The physical iPhone repeatedly received HTTP 200 from `/api/v1/services` and
  `/api/v1/scheduled-jobs` over LAN, while the Watch companion launched and
  retained `companionAppInstalled=true`.
- The native response lists all three runtimes and all five current jobs.
- The Discord bot and scheduler advertise no allowed actions; room-audio keeps
  its pre-existing lifecycle controls.
- No service, job, plug, purifier, or command POST occurred during deployment or
  physical validation. Discord bot, scheduler, and room-audio PIDs were
  unchanged across the daemon-only deployment restart.

## 11. Acceptance criteria

The integration is complete when:

- Home shows all three runtime services with truthful live status.
- Home dynamically shows every canonical scheduled job and correct enabled/next/last state.
- No job names are hard-coded in Swift.
- No prompt, secret, Discord identifier, path, command, environment value, or raw runner output reaches the app.
- Failure of the scheduler/job adapter does not hide room audio, Discord bot, or `jarvisd` status.
- Polling and physical read-only validation cause no POST requests or process changes.
- Critical actions are server-allowlisted, UI-confirmed, audited, and duplicate-suppressed.
- `jarvisd` remains impossible to stop or restart through its own native API.
- The full verification matrix passes before physical deployment.
