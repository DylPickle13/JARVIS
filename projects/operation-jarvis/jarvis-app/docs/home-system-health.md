# Compact iPhone Home: oMLX and system health

The iPhone Home card below oMLX is a read-only disclosure. It projects the
existing `/api/v1/state` response; it does not call `/api/v1/services`, monitoring
URLs, diagnostics, recovery, or device APIs. Expansion adds no network work.
Watch layout and polling are unchanged.

## oMLX

Only fresh loading, queued, prefill, processing, or generating hosts get a row
on iPhone. Loaded-but-idle models do not. The heading remains when both rows are
hidden, with Idle only when both hosts are known fresh and ready. Missing,
checking, stale, and unknown peers remain visible in the heading, even while
another host is busy. The full observation set still drives the update dot and
existing animation gates. Metric headings disappear when there are no rows.
The shared view defaults to showing all rows, preserving Watch behavior.

## Backend compatibility review (2026-09-22)

Reviewed the current working-tree backend and `docs/efficiency-audit.md`, not just
an older committed API:

- Services are `subsystems.services.services[name]`, alongside collector metadata.
  The previous app decoder ignored that nested map. It now decodes it additively;
  an older/missing map is Unknown, not Healthy.
- Health uses `subsystemsMeta`: `ok`, `stale`, `refreshing`, `error`, `ageSeconds`.
  Top-level `ok` only confirms a response; it does not imply all services work.
- Freshness ceilings match `StateCoordinator.DEFAULT_STALE_AFTER`: plugs 30s,
  purifier 90s, Pi 180s, services 660s, Codex 900s, network 1260s. Explicit backend
  stale/errors always win. The app adds elapsed time since the state request began,
  so old-host healthy flags and frozen snapshots cannot remain healthy forever.
  These ceilings must be reviewed if backend freshness policy changes.
- Service importance and execution mode are separate: `critical: true` means
  required, not always running. Backend metadata declares `executionMode` as
  `continuous` or `periodic`; the jobs scheduler is periodic. Cached observations
  include `loaded`, `running`, `lastExitCode`, and `lastExitSignal`. A required
  continuous service must be running. A loaded periodic service with a successful
  last exit and no current process is healthy: “Scheduled · idle between checks.”
  An unloaded required scheduler, missing configuration, nonzero exit, or signal
  remains an issue. A failed last check stays visible even while the next check
  runs; a later successful completion clears it. Missing completion/registration
  data is Unknown when idle. Older hosts missing execution mode cannot establish
  whether a stopped required service should be running, so display Unknown.
  Optional stopped services remain informational. No scheduler name is hardcoded
  in the UI, and no restart/control permissions are granted by these fields.
- Plug batching can return partial failures despite an aggregate successful read.
  Per-plug and per-purifier stale/error outcomes prevent a false Healthy summary.
- Idle/new/quit Pi slots are not daemon failures. The card checks Pi collector
  freshness rather than requiring every interactive session to be running.
- Passive-tab cache mode and existing Home collection policy remain unchanged.
  No app-triggered diagnostic polling, lease extensions beyond existing Home
  reads, hardware read fan-out, or automatic recovery was introduced.

Expanded rows describe cached software/read health, not physical security or a
live connectivity guarantee. Unknown entries keep the aggregate from saying
Healthy. A stale service collection does not claim an individual service is
currently stopped. Observation age refers to the last good read, not a failed
attempt. oMLX retains its own independent, stricter activity-freshness display.

Source review alone does not establish which backend revision is running. The
periodic-service fix needs the updated backend collector **and** service
configuration deployed, then the app updated. The app does not activate backend changes itself. Until the
backend supports execution-mode/completion metadata, stopped required services
remain Unknown instead of being incorrectly classified as failures. Periodic
runner health is not proof that every scheduled job succeeded; job results stay
in the Jobs tab. No restart of the scheduler or replay of a job is needed.

## Deployment checkpoint (2026-09-22, 12:30 EDT)

Backend `20260922T162806Z-periodic-service-health` is active and preserves the
previously deployed efficiency release. All 980 frozen Python tests passed.
Live cached services returned fresh `executionMode: periodic`, `loaded: true`,
`running: false`, `lastExitCode: 0`, and no terminating signal for the scheduler.
The scheduler, Pi sessions, and audio services were not restarted. Notifications
remain off. Only jarvisd and its unchanged watchdog were cycled after worker and
readback checks; the old backend/plist is retained for rollback.

Signed and audited iPhone build 211 is ready, **not yet installed**. Its native
macOS package suite executed 205 tests with 3 expected live-test skips and no
failures. Build 210 remains the last installed app; it still needs the app update
to interpret the new service metadata. No simulator validation was performed.

## Health summary clock correction

The five-second TimelineView is a redraw scheduler, not the freshness clock.
Its previous tick can precede a newly fetched snapshot's request timestamp.
Using that old tick produced negative elapsed time, temporarily made every
collector Unknown, and hid a real service issue until the next tick. The card
now evaluates with the actual render-time Date instead. Regression tests
reproduce this exact Issue → Unknown oscillation and verify that actual expiry,
missing data, future-clock rejection, and recovery still work. No debouncing,
issue masking, or extra polling was added.

## Checks

Package tests cover cached-service decoding/round trips, required vs optional
services, missing/legacy metadata, freshness ceilings and elapsed time, partial
device observations, active oMLX phases, independent rows, and peer warnings.
The signed device archive checks compilation of AppState and the new view.
The simulator test build was stopped at the owner's request; no simulator test
pass is claimed for this change. Physical layout/interaction acceptance remains
separate from compilation, native macOS package tests, and successful installation.
