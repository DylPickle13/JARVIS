# Wi-Fi transport — September 7, 2026

> Historical/reference document. Use [OPERATIONS.md](OPERATIONS.md) for the current single-Mac workflow and recovery rules.

## Implemented now

The dashboard remains on **mac-mini-64** at http://127.0.0.1:8768/. Its shared remote controller on **mac-mini-16** now selects **Wi-Fi explicitly for LG + Dyl Cam**, including status, framing, camera commands and post-stop ADB pulls. It does not silently fall back to USB.

| Phone | Current endpoint | Security / recovery |
|---|---|---|
| LG Wide Angle | `192.168.21.113:5555` | Legacy unencrypted ADB; `ro.adb.secure=1` observed. Trusted LAN only. USB may be needed to enable TCP mode again after a reboot. |
| Samsung Dyl Cam | `192.168.21.12:34115` | Paired Wireless Debugging (TLS); hardware serial verified. Connection-port discovery uses only its previously paired Bonjour service. |
| iPhone | `https://192.168.21.158:4444` | Existing certificate pin verified; camera API reads work; managed control adds only explicit record/stop POSTs. Network-only Apple file access passed an 8 MiB cable-free diagnostic with two independent reads. Now included in managed dashboard Start/Stop; live wireless video collection remains untested. |

Do not forward ADB ports through the router or use LG wireless ADB on shared/public Wi-Fi. `ro.adb.secure=1` is a property observation, not a penetration test or proof against an active LAN attacker. Samsung pairing codes are not persisted in project configuration or reports.

## Selection and identity guards

- Implementation: `android_transport.py`, imported by `pair_control.py`; connection metadata appears in `remote_jobs.snapshot()` and dashboard camera cards.
- Active selection: **mac-mini-16:`~/phone-recording/android-transports.json`**. The local `templates/android-transports.wifi.json` is the deployed example, not a second active controller configuration.
- No config file means the original USB serials. Both roles must be present. Wi-Fi addresses must remain in the approved `192.168.21.0/24` subnet.
- Each controller ADB operation checks `ro.serialno` against the role's fixed hardware identity before sending the camera/filesystem command. Identity mismatch fails closed, without discovery or a camera toggle.
- Reconnecting ADB and looking up the Samsung port are connection/read-only operations. A timed-out camera command is **never replayed**. No Wi-Fi→USB fallback is implemented.
- Changed Samsung ports can be rediscovered for the same paired service. Changed IP addresses or a new pairing service require deliberate configuration updates. LG needs manual re-enablement if TCP mode disappears.
- Existing durable jobs, locks, pre-start media inventories, pending-take recovery and hash-before-delete remain in force. Collection uses the selected endpoint and the existing verified-transfer engine.

## Live validation (not a recording test)

- Dashboard refresh observed both phones **idle over Wi-Fi**.
- Visible Chrome showed **Wi-Fi** on both cards and real idle framing screenshots from both wireless endpoints. No continuous preview.
- `validate_android_wifi.py` created a unique **8 MiB non-media diagnostic file per phone**, uploaded it, checked the phone SHA-256, downloaded it, compared SHA-256 and checked the phone again. Only its own verified diagnostic files were removed. No camera media was read, recorded or deleted by this test.
- LG roundtrip: **4.890 s**; Samsung: **1.540 s**, including verification/control overhead. These are not large-video throughput guarantees.
- Local result: `validation/android-wifi-validation-result.json`. Retained remote diagnostic bytes/report: `~/phone-recording/.wifi-validation/a39c079ed5c54203a8e09edbf28bc002/` on mac-mini-16.
- **120 tests passed**, including nine Android transport tests and six iPhone Network identity/selection/session-cleanup tests; Android coverage includes config scope, identity rejection, same-service port changes, no fallback and no ambiguous mutation replay. Existing collection/dashboard/framing/audio tests still pass.
- No new wireless recording/managed-video collection, long-session reliability, reboot recovery or intensive REAPER listening test has been performed. REAPER was untouched.

## Restore USB deliberately

Do this only with recording stopped, no active dashboard job and no pending take (otherwise inspect/recover first). Connect both phones to mac-mini-16. Under the controller's `.pair-control.lock`, replace `android-transports.json` with the retained `android-transports-before-wifi.json` (both roles `{"mode":"usb"}`). Then refresh and verify both phones idle before Start. USB code/dependencies and pairing were retained.

Restoring the config alone does **not** close the LG network listener. To disable legacy LG network ADB, connect LG by USB and run the retained ADB executable with `-s LGH873bb5b4b79 usb`; then verify USB status. Do not restart ADB during a take. Samsung Wireless Debugging can be turned off in Developer options when unused.

## iPhone wireless file access — now proven with diagnostic bytes

`iphone_wifi.py` successfully reads the existing pinned Blackmagic API; settings remain 4K/30 HEVC High, off-speed disabled, proxies off. Reviewed Blackmagic clips documentation exposes metadata, not a proven file-download endpoint. Apple House Arrest provides the separate file-access path.

Initially, usbmuxd listed no Apple devices, and direct TCP lockdown reset. After the user reconnected USB, the phone advertised Wi-Fi support but had no `EnableWifiConnections` value. Using its **existing pairing with `autopair=False`**, only `set_enable_wifi_connections(True)` was sent; readback was true. No automatic content-sync, backup, Music/Photos, certificate-trust or pairing settings were changed. Finder checkbox automation was not used. Apple's documented Wi-Fi setup also requires an initial cable connection: https://support.apple.com/en-gb/guide/mac-help/mchlada1d602/mac .

The OS then exposed a **Network** device. Direct TCP could read the product but did not locate the existing pairing; the working path is `create_using_usbmux(serial=<bound identity>, autopair=False, connection_type='Network')`. Here `usbmux` is the Apple service broker, **not evidence of USB transport**: both the lockdown and child app-file connections explicitly retain Network selection.

- `iphone_network.py` binds to the USB-verified device identity, rejects an unexpected model/identity or returned USB connection, and opens only Blackmagic's Documents through House Arrest. Sessions close on success/error and must never remain open during capture.
- Identity-only configuration: **mac-mini-16:`~/phone-recording/.iphone-network.json`**, mode 0600, excluded from version control. No pairing keys/certificates were copied into the project.
- `validate_iphone_wifi.py` tested a unique 8 MiB diagnostic file outside Media, with **two independent network reads**, matching SHA-256, local rereads and removal of only the verified fixture.
- USB-attached Network-only test: `iphone-wifi-cabled-validation-result.json`, 5.460 s.
- After the user unplugged USB, usbmuxd showed **Network only**. Cable-free test: `iphone-wifi-cable-free-validation-result.json`, **zero USB devices**, 5.474 s, phone verified idle before/after. No recording or camera-media access/deletion occurred.
- Remote diagnostic copies/reports remain under `.wifi-validation/447fec44caad41c78f4904da85ae8e56/` and `.wifi-validation/4c3faa068bfa456a98203fa7bc210304/`.

**Managed integration is now deployed:** see [THREE-CAMERA.md](THREE-CAMERA.md). The dashboard controls LG + Samsung + iPhone. A bounded real wireless recording/collection test and long-session/reboot validation remain outstanding. Overhead is planned as the fourth camera; see [CAMERA-PLAN.md](CAMERA-PLAN.md). To disable Apple wireless connections later, deliberately set the flag false through the existing USB pairing while idle; do not change it during a take.
