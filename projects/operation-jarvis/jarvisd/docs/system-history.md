# System health chart history — backend

**Initial recording:** `20260930T010227Z-system-history` on 2026-09-29 EDT.
**Sensor-health extension deployed:** `20260930T153603Z-sensor-health` on 2026-09-30.
Native app installation/UI changes are separate; this extension is backend-only.

This adds bounded chart history to the existing in-process monitoring cycle.
It does not add device polling, start collectors, renew foreground leases,
request purifier recovery, run diagnostics, issue commands, restart services,
or change incident thresholds/notifications. No new Python dependency is used.
Existing fields and `/api/v1/monitor/*` contracts remain unchanged. State and
`/api/v1/health` now add a sanitized `health` summary; HTTP 200/top-level `ok`
mean the query succeeded, not that all components are healthy.

## Explicit activation

During a separately approved backend deployment, preserve current monitoring
configuration and set (the installed release below explicitly enables this):

```text
JARVISD_SYSTEM_HISTORY_ENABLED=true
```

Default is `false`. Only exact `true`/`false` are accepted. Enabling history
requires `JARVISD_MONITORING_ENABLED=true` and its existing API-token requirement.
Validation happens before collector/thread/storage startup. Imports do not open
history storage or start workers. This flag does not enable alerts or expand the
security/device monitor list. No launchd plist or live configuration is changed
by the implementation.

One optional callback on the existing 60-second monitor cycle reads:

```python
STATE_COORDINATOR.snapshot(client_active=False, start_collectors=False)
```

The chart callback is independent of incident-store success/failure. Chart
storage failure does not mark incident storage failed or stop existing monitoring.
No catch-up loop or backlog replay occurs. Storage writes and cache evaluations
happen on the background monitor thread, never on a history HTTP request.

## Meaning and scope

A sample evaluates **cached status health**, not independent device connectivity,
continuous process uptime or physical radio health. A network collector verifies
availability of its existing network data, not a new Internet reachability test.
Pi means the existing Pi/session-data collector, not an extra remote host probe.
An off plug/purifier is not an unhealthy device. Purifier is still on-demand:
without existing fresh reads its history becomes unverified; recording must not
silently turn it into a background cloud poller.

Recorded components:

- `services`, `pi`, `network`, `plugs`, `purifier`, `codexQuota`;
- `security`: aggregate availability of all configured sensor status reads;
- `devices`: worst status of plugs, purifier and configured sensor-read health;
- `overall`: worst status of the six collectors and configured sensor-read health;
- up to 23 registered `service:<key>` components when security is included (32 total).

Sensor health consumes the existing serial poller's cached read outcomes only.
A failed read is unavailable immediately; missing/expired evidence is unknown,
never healthy. Disabled/unconfigured sensor monitoring is inactive. The existing
sensor observation TTL (at least 120 seconds) is preserved. No sensor contact or
motion values, aliases, raw errors, or radio-freshness claims enter this summary
or chart storage. Presence and oMLX's different freshness policies remain separate.

Security chart coverage starts with the new deployment; prior samples are not
backfilled or reclassified. Older overall/device samples retain their original
six-collector scope. `/health` remains daemon liveness, so a sensor failure cannot
cause the watchdog to restart the backend. Native clients must consume the new
summary for current-health badges; no native app is rebuilt by this extension.

Required continuous services must run. Loaded periodic services idle after a
successful check are healthy. Failed/signal-terminated scheduled completions
remain degraded even while a subsequent check is running. Optional stopped
services are inactive, not overall failures. Missing registrations/completion
information cannot become healthy. A failed or expired service collector cannot
establish the status of its retained cached service inventory.

| State | Meaning |
| --- | --- |
| `healthy` | Required observations verified and current at evaluation |
| `inactive` | Optional service intentionally not running/loaded |
| `degraded` | Verified scheduled check failed |
| `unavailable` | Collector/device observation failed, or required service missing/stopped |
| `unknown` | Missing, expired, invalid, incomplete or pending evidence |

Unavailable collector/device observations **do not prove a physical outage**.
Chart expiry is explicitly unknown even though the existing app summarizes stale
data as an issue. No timestamp, old receipt, cached process entry or raw error is
used to infer a fresh healthy state. Overflow/invalid service keys make the
aggregate unknown rather than silently reporting only the healthy subset.

## Coverage, clocks and aggregation

Both snapshot generation time and collector source time are checked. The effective
age is the greater of source age and reported age plus snapshot elapsed time.
Missing, future, naive or invalid timestamps fail closed. Existing collector
freshness limits are preserved (services 660s, Pi 180s, plugs 30s, purifier 90s,
network 1260s, Codex 900s).

A stepwise sampled interval ends at the next evaluation, its remaining freshness
(for healthy/inactive evidence), or a 90-second recording coverage lease, whichever
is earliest. This is an approximation of sampled evidence, **not an exact outage
start/end**. In particular a 60-second sampler cannot guarantee continuous coverage
for a collector with a 30-second freshness limit: those uncovered seconds remain
explicit gaps even if later observations are healthy. Do not turn such gaps into
physical outages or invent continuous green coverage.

The last sample of a different process run is conservatively not extended beyond
its check time. Restart, dropped/failed records, worker stalls, and clock jumps
cannot bridge an unobserved period. Wall/monotonic divergence over five seconds
starts a new recording run. Backward wall time cannot overwrite or reorder stored
samples; writes fail closed until wall time advances past the last stored sample.

Server-chosen windows and resolution bound response size:

| Window | Resolution | Buckets per series |
| --- | --- | --- |
| `1h` | 60 seconds | 60 |
| `24h` (default) | 300 seconds | 288 |
| `7d` | 1,800 seconds | 336 |

Aggregation preserves the worst observed state. Missing coverage is also
explicit; a partially healthy bucket cannot become a solid green bucket.
`mixed`, `stateSeconds`, `coverageSeconds`, `missingSeconds` and reason codes
support honest rendering and drill-down. `stateSeconds` describes inferred
covered portions only; missing seconds are not counted as observed unknown data.
A red/degraded mixed bucket does not mean the entire bucket was down. Brief
failures observed by this sampler survive aggregation, but failures entirely
between evaluations may be missed. No arbitrary health percentage is calculated.

## Private persistence and resource limits

New, separate database (existing incident history is neither migrated nor changed):

`~/Library/Application Support/JARVIS/system-history/history.sqlite3`

- Explicit runtime initialization, schema version 1; future schemas rejected.
- Directory 0700, DB 0600; symlink paths and hard-linked DBs rejected.
- Only safe component keys, UTC evaluation/source times, allowlisted states/reason
  codes and freshness bounds are persisted. No device IDs/names, sensor state,
  tokens, paths, raw errors, PID values or control payloads.
- Up to seven days / 10,081 samples, pruned on successful append. Capacity may
  shorten retained history; `earliestSampleAt` discloses available history.
- At most 32 components/sample and 16 KiB/sample including accounting overhead.
- 24 MiB logical payload budget; 8,192 × 4 KiB SQLite pages (32 MiB DB cap).
  DELETE rollback journal, no accumulating WAL. Journal can temporarily add up
  to approximately another DB-sized allocation; these bounds are not a total
  32 MiB disk-footprint claim. Freed pages are reused, not vacuumed per tick.
- DB contention is bounded (50ms in-process lock acquisition, 250ms SQLite busy
  timeout). At most two history builds concurrently. Decode one stored row at a
  time; no seven-day expanded Python-object copy. Default response is five
  series; drill-down is a single component.

Cold storage-open failure leaves the backend running and history unavailable;
fix storage and use an approved restart to reopen. Transient append failure
returns sanitized unavailability until a subsequent normal recording cycle
succeeds; no old failure or notification is replayed. Existing controls/state
remain available. HTTP reads never prune, sample, refresh or mutate state.

## HTTP contract

`GET /api/v1/system/history?window=24h`

Uses the same API authorization policy as cached dashboard state. In
`trusted-network` mode, a permitted source address can read history without an
API token; outside those configured networks access is denied, even with a token.
In `token` mode, the existing API token is still required. Duplicate token headers
and unapproved origins are rejected before any database read. Responses use
existing `Cache-Control: no-store`. This owner-approved policy correction replaces
the original history-only token requirement; no CIDRs or global auth mode change.
Only `window` and optional `component` selectors are accepted. Duplicate/empty/
unknown selectors, arbitrary ranges/resolutions, refresh flags, more than two
fields, malformed query strings and queries over 256 characters return 400.

Default series: `services`, `pi`, `network`, `devices`, `overall`. For one collector
or registered service use, for example:

```text
/api/v1/system/history?window=1h&component=purifier
/api/v1/system/history?window=24h&component=service:room-audio-server
```

Service selectors must refer to actual recorded registry keys; an otherwise
valid service key not found in the requested window returns 404. Fixed component
keys return empty/unknown buckets when no history exists. No old incident records
are backfilled into chart coverage.

Response fields:

```json
{
  "ok": true,
  "schemaVersion": 1,
  "scope": "cached_status_health",
  "window": "24h",
  "from": "<UTC>",
  "to": "<UTC>",
  "sampleIntervalSeconds": 60,
  "resolutionSeconds": 300,
  "coverageLeaseSeconds": 90,
  "retentionSeconds": 604800,
  "earliestSampleAt": "<UTC or null>",
  "latestSampleAt": "<UTC or null>",
  "series": [{
    "id": "network",
    "buckets": [{
      "from": "<UTC>",
      "to": "<UTC>",
      "state": "unavailable",
      "reasonCodes": ["collector_failed", "current"],
      "coverageSeconds": 270,
      "stateSeconds": {"healthy": 210, "unavailable": 60},
      "missingSeconds": 30,
      "mixed": true,
      "sourceObservedAt": "<UTC or null>"
    }]
  }]
}
```

Dates are UTC; clients may display EDT/local time. A 200 means the query succeeded,
not that components are healthy. No history yet means zero coverage and unknown
buckets. Disabled recording returns 503 `system_history_disabled`; storage failure,
contention or excess concurrent builds returns 503 `system_history_unavailable`.
No raw filesystem/SQLite/collector errors are exposed. Other methods cannot start
recording or issue commands through this route.

## Validation and rollout gate

Offline tests use synthetic snapshots, fake clocks, temporary private DBs and
loopback fixture HTTP servers. Cover classification, expiry, delayed/future dates,
periodic-service semantics, partial buckets, worst-state aggregation, clock jumps,
restart holes, capacity/time retention, permissions/schema/link safety, contention,
write failure/recovery, disabled startup, optional storage failure, API auth/query
validation and absence of collector/refresh work on HTTP reads.

Candidate validation: `verify.sh` passed all **789 backend tests**, plus Python
syntax, shell syntax and LaunchAgent plist checks. The **42 history-specific tests**
passed three repeated runs. A synthetic full-retention/capacity exercise used
10,081 samples with 10 components and 6,919 samples with 32 components; both
respected the logical/page budgets and returned five × 336 bounded buckets.
Largest exercised DB: 28,442,624 bytes; peak traced read allocations approximately
28.4 MB; largest exercised response 455,805 bytes. These are offline fixture
measurements, not live production latency or capture evidence. The existing
`control_runtime.py` finally-return syntax warning remains unrelated.

## Deployed checkpoint — 2026-09-29 EDT

Owner-approved backend-only release: **`20260930T010227Z-system-history`**.
Private artifact root:

`~/Library/Application Support/JARVIS/jarvisd/deployments/20260930T010227Z-system-history`

Recording began at **2026-09-29 21:08:02 EDT / 2026-09-30T01:08:02.360Z**.
Only four executable backend inputs differ from the installed baseline:
`jarvisd.py`, `monitor_worker.py`, `system_health.py`, `system_history.py`.
A focused test and this design document were also included. Other working-tree
changes, including the scheduler's source-default relocation, were excluded;
the existing explicit scheduler runtime configuration was preserved.
The frozen installed candidate passed **732 backend tests**, Python/shell syntax
and LaunchAgent plist checks using the installed Python interpreter. This count
is distinct from the broader working-tree 789-test suite above.

Only `com.operation-jarvis.jarvisd` was restarted, in **0.426 seconds**. The
watchdog stayed running. Before/after identities matched for **13 protected
services, 10 tmux panes and 10 Pi processes**; scheduler registration/plist was
preserved. Configuration/token, CLI/vendor-wrapper and scheduler-runner hashes
were unchanged. No native app build/install, device write, forced refresh,
cloud recovery, speed test, notification enablement, other service restart or
Pi session restart occurred.

Live GET-only verification completed **21:15:23 EDT**:

- Liveness, cached state, local-control readiness, scheduled jobs/categories,
  existing incident-monitor APIs and absence of the removed dashboard passed.
- `1h`, `24h`, `7d` queries, fixed-collector/service drill-down and `no-store`
  responses passed; missing/invalid/duplicate tokens, unapproved origin and
  unsupported/duplicate/refresh selectors were rejected as specified.
- A 130.1-second observation added two ordinary samples (6 → 8 total); measured
  recording intervals were approximately 60.06–60.08 seconds. No forced samples
  or fictitious pre-activation data were inserted. Coverage sums and unknown
  pre-recording buckets were verified.
- Private schema-1 DELETE-journal storage was 20,480 bytes at that checkpoint,
  with directory 0700 and DB 0600. Safe keys, reason/state allowlists, source
  timestamps, per-row and total storage bounds passed.
- A bounded history/auth/query read burst incremented **zero** collector,
  adapter-worker, security-read or oMLX counters and inserted zero samples.
  Longer-window concurrent native/other clients were not excluded; this is not
  an isolated idle-cadence benchmark or proof of future hardware reliability.
- Largest default response in this early live sample: 375,519 bytes (`7d`).
  Measured loopback query durations were 2.6–8.5 ms for the default windows;
  these are point-in-time readings, not latency guarantees at full retention.
- All **158** prior incident-history records remained unchanged; no incident
  migration/backfill occurred. Speed-test status was idle. Notifications stayed
  explicitly disabled.

`deployed.json`, `live-verification.json`, source manifests, frozen test logs and
protected-identity evidence are authoritative in the retained active artifact.

**Owner-authorized cleanup at 21:23 EDT:** the rollback folder (prior plist and
private incident backup) and unreferenced prior release
`20260926T022259Z-job-categories` were permanently removed. Active launch-agent,
process, working-directory and environment references were checked first. The
active history release, its source/configuration, both production databases and
unrelated app/older deployment artifacts were retained. `rollback-removal.json`
records the scope and completion. Historical verification records describe the
backup existing at verification time; the prior backend rollback is no longer
available. Source defaults remain disabled;
future deployments must explicitly preserve the approved enabled configuration.

The backend rollout gate is complete. Before native integration, preserve the
API's partial-coverage/freshness semantics and test the historical UI; app device
deployment remains a separate approval. Future backend changes/restarts also
require approval. This release's prior backend rollback has been removed by
owner request. Any future rollback requires a newly reviewed compatible artifact;
retain the separate chart DB and existing incident history.
