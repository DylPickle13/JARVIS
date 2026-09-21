# Raspberry Pi — living room

## Current deployment (2026-09-21)

- Backend deployment: `20260921T051732Z-living-room-presence`.
- `/api/v1/presence` retains the legacy `presence` basement field and adds `zones`
  containing basement and living room. No unique-room inference; signals may overlap.
- Pi source installed at `/home/pi/.local/share/jarvis-presence/` with its own venv,
  `policy.py`, `pi_listener.py`, and `pi_export.py`. Source hashes matched the repo.
- User unit `jarvis-presence.service` is enabled and running. Initial BlueZ
  `InProgress` failures were traced to controller/kernel errors (`Opcode 0x200c
  failed: -16`). Restarting Bluetooth alone did not fix them; the owner-authorized
  Pi reboot on 2026-09-21 restored continuous scanning, with zero service restarts
  during follow-up checks. User lingering is enabled for operation without login.
- Mac LaunchAgent `com.operation-jarvis.presence-pi-bridge` is running and delivers
  fresh Pi snapshots to the backend. Earlier `No route to host` errors also cleared
  after the Pi reboot. The suspected Mac privacy issue was NOT established; no
  firewall/TCC/Local Network settings were changed.
- Owner confirmed living-room placement on 2026-09-21. `positioned: true` is active,
  and both Watch and iPhone IRKs are enrolled and resolving fresh advertisements.
  The backend reports living room **nearby** from both devices and basement **away**
  during the owner's reported living-room visit. Both controlled listener restarts
  succeeded without another reboot or automatic service restart.
- Owner approved macOS Keychain access. The exact previously verified CoreBluetooth
  UUID labels identified the two `BluetoothLE` records in the System keychain.
  Secret values were captured privately, never printed, and transported over
  host-key-verified SSH stdin. The stored `Remote IRK` bytes required reversal into
  AES order: original bytes matched neither device; reversed bytes resolved their
  observed addresses, then fresh callbacks confirmed both independently.
- Nothing is attributed by name, manufacturer or RSSI alone. The owner's living-room
  seat is farther from the Pi than their basement seat was. Initial resolved signals
  comfortably exceeded -65 dBm, so thresholds remain enter -65/exit -70 dBm.
  Room-boundary calibration is still incomplete; signals may overlap.

## Architecture

The first Pi implementation deliberately uses the existing authenticated SSH path
instead of adding an MQTT broker or exposing a new ingestion port. The bridge holds
one fixed-host SSH session and requests a bounded sanitized snapshot every three
seconds. It reconnects after transport failure with a 15-second delay. No API token
or Bluetooth identity key is sent to the Mac by this collector. Host-key verification
and batch authentication are mandatory; no automatic host-key enrollment.

Pi-local monotonic sample age and boot ID prevent replaying pre-reboot state. The
Mac subtracts remote sample age plus round-trip duration before writing its private
cache. A missing scanner, aged snapshot, failed request, or stale bridge cannot
remain nearby. Backend reads do not invoke SSH or wait for networking.

IRK resolution uses `bluetooth-data-tools`, the resolver used by Home Assistant's
Private BLE Device integration, rather than custom cryptography. Theengs and MQTT
remain a future adapter option. Thresholds should begin at enter -65/exit -70 dBm,
with the shared 10-second departure policy; Pi antenna calibration is independent.
Transport/publication adds latency beyond the departure timer.

## Remaining steps

1. Initial seated living-room/basement movement passed in both directions: two
   backend checks roughly 30 seconds apart per position showed the correct zone
   nearby and the other away. Thresholds stayed unchanged. Other positions remain
   untested; do not infer a unique room when both sensors detect devices.
2. Owner-reported locked iPhone/idle Watch passed 45 samples in three 42-second
   windows: both remained nearby; all four backend checks showed basement away.
   Longer idle, address rotation, single-device fallback, packet gaps, bridge outage,
   power cycle and reconnection still require acceptance. Owner deferred further tests.
3. Avoid unnecessary scanner restarts. The original controller fault has not recurred
   in the enrollment reloads, but recovery may require a deliberate reboot if it does.

Private Pi `diagnostics.json` contains alias-only rolling 60-second RSSI summaries,
last-seen ages and matched-packet counts (at most 600 samples per device in memory).
It contains no addresses or keys and is not included in backend/tool responses.
Check its `updatedAt` before using it; a stopped collector can leave old diagnostics.

Private Pi `config.json` shape (0600; directory 0700):

```json
{
  "positioned": false,
  "devices": {
    "watch": {
      "irk": "REPLACE_PRIVATELY_WITH_32_HEX_DIGITS",
      "enterRssi": -65,
      "exitRssi": -70
    }
  }
}
```

An interactive enrollment helper is installed on the Pi. It accepts hexadecimal
or base64 via a hidden terminal prompt, never argv or logs:

```sh
~/.local/share/jarvis-presence/venv/bin/python ~/.local/share/jarvis-presence/pi_enroll.py watch
```

Run separately with `iphone` for the phone. It refuses alias replacement and
key duplication, preserves the current `positioned` setting, and saves mode 0600. It does not
restart the scanner or assert that a supplied key identifies a physical device.
Do not paste keys into chat or command arguments.

The resolver expects canonical AES-order IRK bytes (Home Assistant format);
do not blindly reverse keys. The public Bluetooth specification vector
`ec0234a357c8ad05341010a60a397d9b` / `70:81:94:0D:FB:AA` passed on the Pi;
a different key was rejected. This is synthetic evidence, not household enrollment. Confirm the enrolled key actually resolves
live advertisements before treating any observations as identity-confirmed.

User service operations: `systemctl --user status|restart|stop jarvis-presence`.
Restart only after validated config changes. Bluetooth power and daemon recovery
are separate operations; do not restart unrelated Pi/audio services.

The owner separately installed unrestricted passwordless sudo for `pi` at
`/etc/sudoers.d/zz-jarvis-admin` (root:root, 0440). This applies to every `pi`
process, not just JARVIS. One-off sudoers installer drafts have been removed from
the project; the installed owner-approved rule is unchanged. To revoke the broad
grant, remove only `/etc/sudoers.d/zz-jarvis-admin` using the owner's normal sudo access.
Never store a sudo password in `.env`.

Tests: eleven policy/transport/configuration/enrollment/calibration tests plus the backend's 623 tests
and both vendor safety suites passed. The Pi remained active with zero restarts after
reboot and no recurring scan-disable errors. Three backend checks 20 seconds apart
showed fresh living-room unknown/not-enrolled and basement away after the owner
reported taking both devices upstairs. Subsequent seated two-way movement and
short idle-device tests passed as detailed above. These observations are not
full physical accuracy or unique-room acceptance.
