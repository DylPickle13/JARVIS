# Presence: basement and living room

See [Pi living-room integration and calibration](PI.md). Both zones are enrolled
and operational. The relocated Pi resolves Watch and iPhone identities privately;
the backend reports independent zone states. Initial seated movement tests passed
in both directions, and a short locked-phone/idle-Watch test passed. Longer-term
idle, address rotation, single-device fallback and outage acceptance remain untested.

First sensor: `mac-mini-64` in the **basement**. Read-only context, not security,
proof of human location, whole-home occupancy, or precise ranging.

## Running architecture

```
Mac CoreBluetooth / Bleak → private atomic snapshot → jarvisd /api/v1/presence
                                                   → operation_jarvis_presence
```

The local collector deliberately needs no MQTT broker. The initial Pi adapter
uses authenticated SSH snapshot requests; a later Theengs/MQTT adapter can produce
the same normalized state. Do not send every advertisement to apps or the model. No household actions or transition-event consumers are enabled.

Installed LaunchAgent: `com.operation-jarvis.presence`. Runtime directory:
`~/Library/Application Support/JARVIS/presence/` (0700; files 0600).
`config.json` holds private enrollment; `state.json` has no device identifiers.
Listener logs and optional discovery results stay there, outside Git.
The Python environment is `presence/.venv`, using `requirements.txt`.

Backend deployment: `20260921T051732Z-living-room-presence`. Its retained deployment
record includes rollback plist, source hashes and verification results. Only
jarvisd restarted; protected audio/terminal services were unchanged.

## Enrollment — maintenance reference (both devices already enrolled)

macOS gives Bleak **CoreBluetooth UUIDs**, not Bluetooth MAC addresses. This is
not the Pi/Theengs IRK resolver. UUID persistence/advertisement behavior must be
field-tested; do not claim identity based on an Apple manufacturer ID, a device
name or strongest RSSI. Do not copy IRKs into this listener's config.

Run a deliberate 30-second discovery session:

```sh
projects/operation-jarvis/presence/.venv/bin/python projects/operation-jarvis/presence/listener.py --discover
```

This writes private `candidates.json` with local UUIDs, names if available and RSSI.
Use controlled, separate device movement/power tests to confirm which identifiers
are yours; names alone are insufficient. Discovery is never invoked by the model's
status tool. Delete candidates after enrollment. Configure only verified devices:

```json
{
  "devices": {
    "watch": {
      "uuid": "REPLACE-WITH-VERIFIED-COREBLUETOOTH-UUID",
      "enterRssi": -65,
      "exitRssi": -70
    }
  }
}
```

Add `iphone` similarly, with independent thresholds. Restart only the listener
after editing config: `launchctl kickstart -k gui/$(id -u)/com.operation-jarvis.presence`.
Bluetooth permission may need approval in macOS Privacy & Security. Enrollment
starts empty: no unknown nearby device is automatically attributed to Dylan.

## Semantics and privacy

- States: `nearby`, `away` (from this sensor, not necessarily away from home), `unknown`.
- EWMA smoothing and per-device enter/exit thresholds; either device qualifies.
- Retain nearby for 10 seconds after the last qualifying reading. Both must expire
  before reporting away. The three-second publish interval adds up to three seconds
  of reporting latency; brief advertising gaps may now cause false departures.
- Empty enrollment and the initial observation window return unknown. Missing,
  invalid, future-dated or older-than-15-second listener snapshots return unknown.
- Three-second heartbeats. Failed/stopped scanner invalidates state; process crashes
  expire it. Radio silence despite a functioning scanner can still cause false away.
- Devices left behind can cause false nearby. Apple advertising behavior, screen-off,
  low-power mode, companion proximity and UUID persistence require physical tests.
- Backend endpoint requires an API token even in trusted-network mode, or the
  existing loopback local-control bearer credential. Responses are `no-store`.
  Presence is intentionally absent from the broadly accessible aggregate state.
- No raw identifiers, names, IRKs or RSSI are returned by the endpoint/tool.
- Status reads are on demand, not automatic injection of location into every prompt.
  Reload Pi extensions to register the new `operation_jarvis_presence` tool.

Read authenticated backend state locally:

```sh
projects/operation-jarvis/.venv/bin/python projects/operation-jarvis/presence/status.py
```

Tests: `python3 -m unittest discover -s projects/operation-jarvis/presence` plus
`jarvisd/verify.sh` (includes endpoint authentication), `verify-kasa-sdk.sh`, and
`verify-vesync-sdk.sh`. Initial two-way seated checks and 45 samples across three
42-second idle-device windows passed. This does not validate every position or
prove human location; no automations are enabled.
