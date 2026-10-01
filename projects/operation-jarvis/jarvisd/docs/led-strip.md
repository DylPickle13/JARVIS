# Security light-strip backend tracking

Deployed 2026-09-30 EDT as `20261001T012512Z-led-backend`.
The Tapo L930-5 remains a **Security** device, not a Smart Plug.

## Read-only API and tracking

- `GET /api/v1/security/status?device=led-strip` accepts the authenticated
  `L930-5` CLI result and projects only power, brightness, HSV, white temperature,
  named effect, effect brightness, gradual on/off durations, and RSSI.
- `GET /api/v1/security/health` includes the strip's last attempt, last successful
  read, age, and failure count.
- `GET /api/v1/monitor/security/led-strip` exposes cached read availability.
  The configured alias also participates in existing security aggregate health
  and the existing monitor/history pipeline. No new history database is created.
- Existing API-token authorization remains required. No credentials, LAN
  addresses, device identifiers, or raw device payloads are exposed.

The installed serial security poller includes the strip alongside the two
existing sensors, using the existing 60-second completion-relative cadence and
120-second read-health expiry. Reading cached health does not contact hardware.
The existing paired sensor snapshot path is unchanged; the strip uses its own
bounded CLI read. No new service, scheduler job, SDK retry, or cloud call is added.

Power must be a known boolean for a successful lighting observation. Malformed,
missing, or errored optional fields remain null; powered-off is not unavailable.
A colour temperature of zero means colour mode. HSV and effect brightness are
reported configuration, not measurements of individual LEDs or physical appearance.
Health indicates data availability, not household security or physical acceptance.

## Control boundaries

This adds backend **read tracking**, not a new HTTP lighting-write route. Existing
Pi/security CLI controls remain the write path, retaining model checks, locks,
readback, and no replay after uncertain writes. Existing presence automation
continues to change power only; effects/colours and manual overrides are preserved.
No custom-zone default or automatic effect reset was installed.

## Deployment verification

The candidate is based on the previously installed frozen backend, with only the
security projection, generic read-monitor scope, and their tests changed. Its
frozen security reader includes the reviewed lighting support and retains private
runtime configuration outside the release. Frozen-reader import paths were tested
before activation; no credentials were copied into the release.

- 759 frozen backend tests passed.
- 300 frozen security-reader tests ran: 299 passed, one skipped.
- Authenticated installed LED status and cached monitor returned HTTP 200;
  live status reported power on and the existing Aurora effect.
- LED, door, and motion read-health records were available after activation.
- Backend activation took 0.349 seconds; watchdog supervision was restored.
  Protected long-running services, including the presence watcher, kept their PIDs.
- No device writes were issued. The first activation was conservatively rolled
  back when the existing sensor snapshots were temporarily unavailable. Their
  baseline reads recovered; the final activation waited for all three records.

The private release contains prior/candidate plists, manifest, test logs, and live
checks. Rollback restores the prior daemon plist, thereby restoring its matching
frozen security reader and polling aliases. The private installed deployment
record remains authoritative. This does not add a native-app lighting card.
