# Device monitoring coverage

Extends the existing jarvisd monitoring worker, incident store and authenticated
health APIs. No parallel daemon, dashboard server or notification service.

## Picture-frame availability — deployed 2026-10-06 EDT

Release `20261006T193632Z-picture-frame-health` adds one read-only, identity-checked
frame entry to the existing worker: **27 entries**, with the original 26 unchanged.
The actual backend launch-context check and later periodic observations passed.
Only jarvisd/watchdog restarted; alerts remain disabled, and unrelated services,
Pi identities, configuration and SQLite history/cadence were preserved. See
[picture-frame scope, verification and rollback](picture-frame-health.md).

## Device-coverage deployment — 2026-09-30 EDT

The device-coverage slice shipped as `20261001T015215Z-device-coverage`. Its frozen backend
passed 777 tests. The prior installed backend passed 759 tests before preparation.
The operational source checkout's broader suite has 20 pre-existing vendor-fence
pin errors; those pins were not refreshed or weakened. The candidate was built
from the passing installed release, with only the device-coverage patch applied.

After the owner's scope corrections, the private registry has 26 device/integration
entries: 26 background checks, including direct TCP reachability for the hardwired
doorbell; all 26 passed the latest warm verification.
iPhone USB, Watch and Master Chief are intentionally excluded, not coverage gaps.
Existing BLE presence enrollment is unchanged. See the [workflow dependency map](workflow-health-map.md)
for the System-only UI planning; the LED strip belongs to Computer presence. The owner
confirmed that the D235 doorbell is hardwired; the original battery assumption
was incorrect. Hardwired power does not itself establish a supported health check. USB attachment is not app or peripheral
functional health; TCP success is not an authenticated integration check. These
are scoped observations, not certification that 27 devices work physically.

Notifications remain disabled. Only jarvisd and its watchdog were cycled; existing
terminal, room audio, sensor reader and keyboard watcher services were left alone.
The speaker's stale private Cast address was corrected separately after discovery
and a successful connection. No authentication, enrollment, device writes or
recovery retries were added.

**Owner UI correction:** Health information belongs on the System tab, not Home.
The owner rejected the Home card after installation. The exact audited build 234
was restored on the iPhone and its version/running process verified; no app data
was removed. The Home card insertion was removed from the working source.
Backend monitoring remains active. Subsequently, build 236 implemented the owner's
Computer/Security/Cast grouping in System and was installed and version/process
verified on both iPhone and Watch. Home is unchanged. See
[workflow mapping and verification](workflow-health-map.md).

Historical build 235 verification (subsequently rolled back):
The proposed iPhone Home **Device health** disclosure used the existing state stream.
Build 235 was prepared from installed build 234 with only the coverage additions.
259 JARVISKit tests ran (3 live tests skipped, no failures), 61 iOS tests passed,
and the Release archive passed signature/profile/entitlement and payload audits.
The exact sealed archive was installed on the approved iPhone; installed version
235 and the running process were independently verified. Build 234 is retained
for rollback. No direct Watch installation was performed. Physical UI acceptance
remains for the owner to confirm. The compact System visuals were preserved.

## Configuration

`JARVISD_DEVICE_REGISTRY` optionally names an absolute, owner-only JSON file.
It is read once at startup. Blank means no inventory, not complete coverage.
A malformed file fails startup; it never silently drops entries or invents green.
Up to 40 devices are allowed, and total existing plus device monitor keys must fit
the existing 64-key bound. Aliases and display names are validated; no addresses,
opaque cloud identifiers, filesystem paths, credentials, occupancy or raw errors
are emitted in `deviceHealth`.

Example (illustrative private addresses, not production configuration):

```json
{
  "version": 1,
  "devices": [
    {"id": "lamp", "name": "Lamp", "kind": "plug", "selector": "lamp", "expectation": "always"},
    {"id": "hub", "name": "Hub", "kind": "tcp", "host": "192.168.1.2", "port": 443, "expectation": "always"},
    {"id": "door", "name": "Door sensor", "kind": "security", "selector": "door-sensor", "dependsOn": ["hub"], "expectation": "always"},
    {"id": "doorbell", "name": "Battery doorbell", "kind": "unmonitored", "dependsOn": ["hub"], "expectation": "optional"}
  ]
}
```

Check kinds:

| Kind | Evidence / policy |
| --- | --- |
| `plug` | Exact alias in existing plug cache; off is not failure |
| `purifier` | Exact opaque device ID in existing multi-device cache; no new cloud calls or cooldown bypass |
| `security` | Existing recorded read outcome; background only if already in configured polling aliases |
| `omlx` | Existing server cache; 120s health expiry, not the six-second activity UI expiry |
| `tcp` | One connect/close to a configured numeric private/Tailscale IPv4 address and port; 2s timeout; no DNS/discovery/retry |
| `usb` | One bounded local IORegistry enumeration per cycle; exact `vendorID`/`productID`; never opens HID control handles |
| `heartbeat` | Owner-only bounded JSON file, `path`, `timestampKey`, `maxAge` (30–300s), `faultKey`; current process heartbeat only |
| `frame` | Opt-in pinned Frameo identity/package read through a bounded worker; no controls or photo reads. [Deployed status-only scope](picture-frame-health.md) |
| `unmonitored` | Explicit coverage gap; never healthy by omission |

The probe worker runs serially, waiting 60s after each completed cycle, with no
catch-up burst. TCP/USB/heartbeat checks were added in the deployed coverage slice;
the optional frame check is the separately deployed status-only addition. Probe evidence expires at
150s; existing caches retain their own expiry. HTTP overview requests do not run
probes, renew oMLX foreground leases or create hub sessions. Shared sensor polling
and departure logic are unchanged. A probe cannot restart a service or device.

`expectation: optional` means an unreachable check becomes **unknown**, not a
required-device incident. It does not assert that the device is intentionally off.
Use this for equipment that legitimately sleeps/disconnects. It is not a way to
hide a required integration failure.

`dependsOn` is validated for references and cycles. An unsuccessful child check
lists unavailable/unknown dependencies. Its device incident is suppressed while
a dependency is unavailable; an already-open incident is retained, not falsely
recovered. Successful independent child evidence is not overridden by a failed
parent probe. Dependencies are diagnostic hints, not physical causal proof.

## APIs, incidents and app

`deviceHealth` is added to:

- `/api/v1/state` (same existing app authorization)
- `/api/v1/health` (API token required)
- `/api/v1/monitor/status` (API token required)

It includes scoped per-device state, coverage, source age, last success, last
attempt and failed-attempt count when available, dependency hints, incident start
and whether an incident is open. Cache-only adapters do not invent last-attempt
timestamps or counters when the collector only exposes last-good metadata.

The summary separates total/background/on-demand/unmonitored coverage from
available/unavailable/unknown evidence. `available` means only the displayed check
succeeded. The legacy `health.healthy` keeps its existing component scope; it is
not expanded into an unsupported whole-home guarantee. `/health` is unchanged:
public daemon liveness only.

Required background device checks feed existing `devices/<id>` incident keys.
The existing three evaluations over at least 120s threshold, bounded private
SQLite store, restart/no-replay policy, and `/api/v1/monitor/history` are reused.
These are **data/check availability** incidents, not necessarily three independent
physical failures. Optional/unmonitored/on-demand entries do not open incidents.
Existing aggregate monitor keys remain for compatibility. Notifications stay off;
review aggregate-vs-device alert grouping before enabling them.

The app disclosure expires frozen evidence locally and labels TCP, USB, process
heartbeat and status reads separately. It does not start polls of its own or
claim that attachment proves an Android dashboard is rendering correctly.

## Remaining coverage work

- Hardwired doorbell now has a direct TCP 443 connect/close check, using its
  configured address and the backend's existing bounded probe worker. An explicit
  authenticated status read also succeeded during setup, but that read is not
  repeated by this monitor. There is no new hub session or hub dependency for this
  direct endpoint check. TCP reachability does not establish video, recording,
  chime or button functionality. Stronger passive functional evidence remains
  possible future work.
- Apple Watch and Master Chief: excluded at the owner's request; no checks needed.
- USB/TCP-only entries can later gain stronger app/integration checks. For
  example, USB attachment does not establish Android rendering, microphone
  capture, HID control success, or webcam video availability.
- Inventory is an explicit reviewed snapshot, not automatic LAN discovery. New
  configured devices must be added and verified; coverage totals cannot detect
  unknown household hardware.
- This Mac cannot report its own complete host/network outage while offline.
  An external observer would be a separate design/authorization.

## Rollback

Restore the recorded prior daemon plist and restart only jarvisd using the normal
watchdog-coordinated deployment process. Preserve current private incident history,
credentials and all existing device/sensor state. The optional response field is
backward compatible with older apps. The private deployment folder contains the
prior/candidate plists, tested source, verification logs and a private environment
backup for the single speaker-address correction. Never commit that folder.
