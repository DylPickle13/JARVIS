# Native jarvisd monitoring

## Passive coverage — 2026-09-22 EDT

Active release: `20260922T143035Z-passive-monitoring`. Adds separate `onDemand`
read-health entries for purifier, presence, and Pi/Mac room audio. No new hardware
reads, cloud authentication, recovery attempts, incident tracking or notification
work is introduced. Missing/expired observations mean unavailable **data**, not a
physical outage. Purifier uses its existing cache; presence/audio use completed
GET observations, which expire after 120 seconds. A diagnostics read does not
refresh them. These entries are not part of the nine background incident monitors.

653 frozen-backend tests passed. Live authentication, disabled refresh, unknown
selectors, absence of dashboard, and retained background polling were checked.
Purifier cache was unavailable/expired and presence/audio had not been checked;
no checks were forced. Sensor polling showed intermittent failed reads/recoveries,
so this activation is not evidence of uniformly reliable sensors. Monitor-store
samples may lag the immediate read-health view by up to the sampling interval.
Notifications remain disabled; protected terminal/audio identities were unchanged.

## Expanded monitoring — 2026-09-22 EDT

Release: `20260922T142353Z-expanded-monitoring`. Configuration-only extension
adds `pi`, `services`, `network`, and `codexQuota` to existing `plugs` monitoring.
These sample existing caches without changing collection intervals, issuing
commands, or renewing foreground leases. All nine configured monitor read-health
checks were available after activation, including both sensor background reads.
650 frozen-backend tests passed, including simulated failure/recovery, expiry,
persistence and no-replay cases. Physical transitions and real hub outage/recovery
remain unverified; the owner chose to skip physical testing. No dashboard or
notifications were enabled; protected terminal/audio identities were unchanged.

## Dashboard removal — 2026-09-22 EDT

Release: `20260922T141423Z-remove-monitor-dashboard`. Dashboard HTML/JS and
routes removed; both live URLs return 404. Frozen backend: 650 tests passed.
Background polling resumed with both sensor reads available. Authenticated
history/status APIs remain; notifications are still disabled. Protected
terminal/audio identities were unchanged. Prior release retained for rollback.

## Initial deployment checkpoint — 2026-09-22 EDT

Installed release: `20260922T135534Z-native-monitoring`. Monitoring/polling enabled;
**notifications explicitly disabled**. Door and motion sensors each completed two
background checks; latest reads were available hub snapshots. Plug and both oMLX
read-health monitors were available. Dashboard and token rejection verified.
650 tests passed against the frozen backend. Terminal/audio service identities
were unchanged; only jarvisd and its watchdog were cycled. The prior release/plist
and verification records are retained in the private deployment directory.
Unrelated network-speed changes were excluded. Physical sensor transitions and
notification delivery were not tested or claimed.

No Kuma, VM, container, separate daemon, new Python package, or duplicate device
poller is required. The already installed Python stdlib supplies SQLite. The
existing jarvisd process owns security polling, cache-health evaluation, history,
and a small browser dashboard. This is not a Kuma clone.

The unused Colima, Docker, Docker Compose and Lima packages installed during the
abandoned Kuma setup were removed. No VM or Kuma container was created.

## Configuration (apply only during an approved deployment)

```text
JARVISD_MONITORING_ENABLED=true
JARVISD_SECURITY_POLL_ALIASES=door-sensor,motion-sensor
JARVISD_SECURITY_POLL_INTERVAL=60
JARVISD_MONITOR_INTEGRATIONS=plugs
JARVISD_MONITOR_NOTIFICATIONS=false
```

Existing `JARVIS_API_TOKEN` and absolute `JARVISD_SECURITY_CLI` configuration are
required. Never commit credentials or the private registry. Defaults: monitoring
disabled, notifications disabled, security aliases empty. Aliases are explicit,
unique, at most eight and validated again by the CLI registry. Interval 30–300s.
Additional integration names: `pi`, `services`, `network`, `codexQuota`. Both
configured oMLX servers are included when monitoring is enabled.

Purifier background recovery is deliberately excluded. Its existing cloud
cooldown/explicit recovery policy remains unchanged. Device writes, service
restarts, audio stop, signing renewal and event ingestion are never polled or
replayed by monitoring. No physical action is triggered by availability changes.

## Data acquisition and status

- Security reads are serial across configured aliases. Each next read is due
  one configured interval after completion, with no catch-up bursts. Slow reads
  can lengthen other devices' effective cadence.
- On-demand reads share the adapter lock. Existing CLI hub locks exclude security
  writes. A busy result does not replace or freshen an observation; persistent
  contention eventually expires it.
- Sensor status/capabilities use at most three fresh-connection attempts within
  one shared 60s deadline; the backend subprocess allows 65s including cleanup.
  Retry only explicit transient transport/timeouts/unreachable errors. No retries
  for authentication, registry/identity, missing/ambiguous child, generic SDK
  failures or writes. A full-budget timeout leaves no time for another attempt.
- Required door/motion state must be present. Optional battery/RSSI can be missing.
  Success is **hub snapshot read availability**, not proof of radio freshness or
  physical sensor connectivity. No stale device reading substitutes for failure.
- Security observations expire after max(120s, twice the polling interval).
- Existing subsystem workers retain their cadence and safety protections. oMLX
  activity workers start at daemon startup only when monitoring is enabled, using
  their existing 60s idle cadence. Cache-health requests never renew active leases
  or request a device refresh.
- oMLX monitoring uses a 120s successful-read window, distinct from its six-second
  UI activity freshness. Latest read errors invalidate it immediately. The UI's
  stricter generation/activity contract is unchanged.

The in-process monitor worker evaluates these cached results every 60s. Three
unavailable evaluations spanning at least 120s open an incident. These are cache
health checks, **not necessarily three independent device failures**. A successful
check closes the incident. Transient failures recovering before the threshold do
not generate incidents or notifications. No repeated alerts while one incident
remains open. Current availability can change before the incident threshold.

## Persistence and resource bounds

Only incident/recovery transitions are written, not every poll. Storage:

`~/Library/Application Support/JARVIS/monitoring/history.sqlite3`

Directory 0700, DB 0600; local disk only. At most 64 configured monitor keys,
1,000 history events, and 1,024 SQLite pages (normally 4 MiB of DB pages), with a
bounded DELETE rollback journal and no accumulating WAL. Private aliases and
UTC timestamps are stored, never tokens, sensor state, raw errors or credentials.
History is not published through the existing trusted-network `/api/v1/events`.
There is no per-sample uptime-percentage calculation or continuous time-series DB.

Open incidents persist across restarts. Prior successes do not become current
successes after restart; current status begins unavailable until checked. No
notifications replay after restart. Recovery of an open incident requires a new
successful evaluation. Do not infer uninterrupted observation during a stopped
Mac/process; the daemon cannot monitor or notify about its own total host outage.
A stalled monitor worker makes its dashboard observations expire after 90s.

## Notifications

Set `JARVISD_MONITOR_NOTIFICATIONS=true` only if local Mac Notification Center
alerts are wanted. The bounded `/usr/bin/osascript` submission uses fixed, generic
text (no aliases or occupancy on the lock screen), no shell, and a five-second
deadline. One submission per outage/recovery transition. It is recorded before
sending, so an uncertain result/crash is not automatically replayed.

History labels: `disabled`, `attempted`, `submitted`, `failed`. Submitted means
macOS accepted the request, not proof that a user saw it. macOS notification
settings, Focus, and the daemon's GUI-session context can prevent display. Verify
on the actual deployed account before relying on alerts. There is no iPhone/APNs,
email, external webhook, or retry/outbox integration in this implementation.

## Monitoring API (no dashboard)

The browser dashboard was removed at the owner's request. `/monitoring` and
`/monitoring.js` return 404; no HTML/JavaScript dashboard module is shipped.
Background polling, incident history, and the authenticated APIs remain.
All data endpoints require `x-jarvis-token` even in trusted-network mode.
API reads do not trigger sampling or device I/O. Notifications remain disabled.

| GET endpoint | Contract |
| --- | --- |
| `/health` | Existing public daemon liveness only |
| `/api/v1/monitor/status` | Background `monitors` plus separate passive `onDemand` read-health entries; 200 means query succeeded |
| `/api/v1/monitor/on-demand/<name>` | Cache-only read health for `purifier`, `presence`, `room-audio-pi`, `room-audio-mac`; 200 available / 503 unavailable |
| `/api/v1/monitor/history` | Authenticated last 100 incident/recovery events; newest first |
| `/api/v1/monitor/security/<configured-alias>` | Cache-only 200 available / 503 unavailable |
| `/api/v1/monitor/integrations/<subsystem>` | Existing cache-freshness 200/503 projection |
| `/api/v1/monitor/omlx/<server-id>` | Recent-read-health 200/503 projection |
| `/api/v1/health`, `/api/v1/security/health` | Bounded in-memory diagnostics, not aggregate uptime checks |

Unknown monitors return 404; missing/invalid API token 401; query parameters are
not supported. Disabled monitoring or storage failure returns sanitized 503 on
status/history APIs. No raw subprocess/SQLite/filesystem errors are exposed. Binary
Available/Unavailable refers to **status data**, not physical hardware. Do not
interpret a successful overview query as every device being available.

## Validation and rollout

Offline tests use fake clocks/readers/notification transports and temporary DBs.
They cover thresholds, duplicate evaluations, expiry, recovery, restart/no replay,
private permissions, bounded retention, auth, sanitization, cache-only endpoints,
and rejection of removed dashboard routes. Existing read-retry and write-safety
tests remain required.

Source edits alone do not activate polling/alerts or restart anything. The
checkpoint above records the approved polling-only activation. For future rollouts:
review the full deployment diff (there may be unrelated work), back up the existing
package, approve jarvisd restart, enable monitoring initially with notifications
off, verify live poll load and physical door transitions, then perform controlled
hub loss/recovery and a local notification test. Enable alerts only after that.
Rollback disables monitoring and restarts only jarvisd through the approved
procedure; the private SQLite history can remain for later inspection.
