# Shared paired sensor reader — deployed 2026-09-30

Owner-authorized deployment `20260930T180949Z-shared-sensor-reader` removes dashboard
sensor polling contention with the departure watcher. The installed release was
copied from `20260930T165244Z-omlx-auth`; only `jarvisd_core/security_status.py` and
new `jarvisd_core/security_snapshot.py` differ. Other installed files were compared
byte-for-byte, preserving unrelated changes. Only jarvisd, its watchdog and the
departure watcher were reloaded.

`JARVISD_SECURITY_SHARED_SNAPSHOT` opts in to the owner-only absolute snapshot path
published by the departure watcher. Both HTTP status reads and background polling
for `motion-sensor`/`door-sensor` consume it, without a competing CLI subprocess.
Missing/stale/invalid data returns HTTP 503, never a direct-device fallback. Other
aliases and deployments without this setting keep the original CLI path.

Validation requires a private regular non-symlink file, exact alias/model/state
schema, and wall-clock plus monotonic age within eight seconds. Responses preserve
sample observation time, `source: hub_snapshot`, unknown radio freshness, and null
battery/RSSI. They add `sharedReader` and `sampleAgeSeconds`. This is not a security
assessment or proof of fresh radio contact.

The departure watcher owns sampling. Disabling it makes these dashboard readings
unavailable; speech/person-check work can also temporarily age out the snapshot.
No snapshot can authorize departure speech. Explicit operations from other clients
can still interrupt the shared reader; continuity must never be fabricated.

## Security tool status reads

The repository security CLI now routes `status motion-sensor` and `status door-sensor`
through `security_shared_status.py`, reusing this same strict snapshot validator.
This also covers `operation_jarvis_security` without reloading the watcher or
jarvisd: its subprocess loads the updated CLI on each invocation. The snapshot
location is fixed to the owner's departure runtime; there is no network fallback.
Missing, stale, or malformed snapshots return `shared_snapshot_unavailable`.
Sample timestamps are preserved and battery/RSSI/radio freshness remain unknown.
Other aliases, explicit `capabilities` reads, and device writes retain their
existing behavior and may still compete for the hub. The Pi extension's new
allowlisted unavailable reason takes effect on extension reload; older loaded
extensions safely report a generic read failure instead.

## Validation

- Departure tests: 91 passed.
- Focused backend security tests: 22 passed.
- Full backend suite: 818 run, 20 vendor-staging hash-check errors outside these
  modules (`Reviewed vendor source drift`); no hash gates were changed.
- Installed HTTP check: 264/264 successful shared-snapshot reads over 150 seconds,
  57 paired samples, maximum sample gap 3.244 seconds, no contention/fault/playback.

Private rollback plist: departure runtime `shared-reader-jarvisd-before.plist`.
Restore only with owner authorization; it points back to the previous intact
release and removes the snapshot opt-in. Doing so restores competing dashboard
reads, so the departure trial should not then be represented as uninterrupted.
The private audit is `shared-reader-deployment-audit.json` in the same runtime.
