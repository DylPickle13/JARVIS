# Android doorbell monitor — presence helper

Security subproject for an Android 6 / API 23 handset running tinyCam. It controls
**only the handset display**, not the doorbell, recordings, alarms, or computer.
No custom video viewer/transcoder is installed. tinyCam keeps its existing camera
settings and hardware-decoded stream.

## Architecture

```
Existing authenticated basement presence → dedicated Mac read-only TLS relay
                                         ← phone polls over home Wi-Fi every 5s
Phone: fresh away twice → DevicePolicyManager.lockNow()
       fresh nearby → wake screen → tinyCam (only if no secure keyguard)
```

Uses the **same basement signal as Computer presence**, not a new BLE scanner or
modified cron job. The computer watcher, scheduler, and presence backend are
unchanged. The separate phone service has finer polling than the minute-based
cron alert relay. BLE presence is an estimate, not proof that a person is present.

- Two consecutive fresh away checks normally add 5–10 seconds after the backend
  reports away; the collector also has its own nearby hold. Nearby normally reacts
  on the next poll. Slow requests extend the interval; no catch-up polling.
- Unknown/stale/error responses, age outside 0–15 seconds, Wi-Fi loss, and Mac
  outages leave the screen unchanged. Fetch/dispatch latency counts toward age.
- Unknown, unplugging, clock reversal, or a polling gap over 15 seconds breaks
  consecutive-away confirmation. Repeated known states do not repeat actions.
- A fresh initial nearby state may wake/open tinyCam; initial away needs two checks.
- **Wall power required for automatic screen actions.** On battery the helper
  releases its CPU/Wi-Fi locks and pauses actions. There is no USB runtime dependency.
  No wireless ADB is enabled. Screen sleep is not full phone shutdown: while plugged
  in, a foreground service keeps a partial CPU and Wi-Fi lock to receive arrival.
- A persisted pending action blocks restart/replay after an uncertain crash. The
  owner reviews and explicitly re-enables in the helper. It is not silently retried.
- A nonsecure swipe keyguard may be dismissed to restore tinyCam. A PIN/password
  keyguard is **never bypassed**. Administrator permission requests only force-lock,
  not wipe, password changes, camera control, accessibility, or device-owner status.
- Boot receiver restarts an enabled helper after reboot and when power is connected,
  waiting for fresh presence before acting. Boot and long-duration wall-charger
  acceptance remain untested.

## Security / private state

The dedicated relay binds only the configured Mac LAN IPv4 address on TCP 8794.
There is no port forwarding, public relay, cloud service, CORS API or write route.
`GET /v1/presence` requires a random monitor-only bearer credential and returns only
protocol version, `nearby`/`away`/`unknown`, and age. Main JARVIS/camera credentials,
BLE identifiers, room inventory and RSSI never reach the phone. Request logging is
disabled. Backend failure yields unknown, not cached away.

The app requires HTTPS, pins the exact SHA-256 server certificate, checks certificate
validity and normal hostname/IP SAN matching, rejects redirects, and bounds response
size and timeouts. A different certificate fails closed. The generated certificate
expires after 825 days; renewal requires deliberate re-pairing. Use a stable/reserved
Mac LAN address; an IP change requires updating the certificate and pairing, not
relaxing TLS validation.

Private runtime: `~/Library/Application Support/JARVIS/android-monitor/` (0700;
keys/configs 0600). Includes separate TLS/signing keys, token, provision file, signed
APK, and quiet relay logs. Android configuration is internal app storage with backup
and debugging disabled. **No credential is compiled into the APK.** One-time USB
provisioning requires Android's signature-level DUMP permission **and shell UID
2000**; normal apps cannot use it. No readback route or replacement of an existing
config is allowed. Re-pairing requires a deliberate app-data reset (disable/remove
Administrator permission first if Android requires it).

Source, tests, and docs are trackable. Only generated artifacts/secrets/caches are
ignored; private runtime is outside the repository. Do not publish configs or keys.

## Owner controls

Open **JARVIS Monitor** on the phone (or tap its persistent notification):

1. Grant screen-lock permission using Android's administrator prompt.
2. Enable automation after reviewing any pending-action error.
3. **Disable automation** stops the helper and releases locks without waking/sleeping.
4. **Test: sleep then wake in 8 seconds** tests only this phone, while externally powered.
5. Open tinyCam to return to the existing viewer.

Before uninstalling, disable the helper, then remove JARVIS Monitor under Android
Settings → Security → Device administrators. Do not change the camera app credentials.

Mac LaunchAgent: `com.jarvis.android-monitor`. Only this new relay service is installed.
To stop it without touching other services:

```sh
launchctl bootout gui/$(id -u)/com.jarvis.android-monitor
# Restart it:
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.jarvis.android-monitor.plist"
```

Stopping the Mac relay intentionally leaves the phone's screen unchanged. Disable
the phone helper too if retiring the feature. The Mac must stay awake/logged in;
its displays can sleep normally.

## Build and install

Requires JDK 17, Python 3, OpenSSL, authorized USB ADB, official Android platform 23
and build-tools 35. No Gradle, Maven dependencies, analytics, or third-party Android
libraries. The initial SDK archives were verified against Google's repository
checksums. `build.py` expects extracted `android-6.0/android.jar` and `android-15/`
build tools beneath the supplied SDK directory. JDK 17 was installed through Homebrew;
no global Java/PATH change was made.

```sh
cd projects/operation-jarvis/security/android-monitor
PRIVATE="$HOME/Library/Application Support/JARVIS/android-monitor"
JAVA=/opt/homebrew/opt/openjdk@17
SDK="$HOME/Library/Caches/jarvis-android-sdk"

# FIRST setup only: refuses to overwrite an existing private directory.
python3 provision.py --host <MAC_LAN_IPV4> --private-dir "$PRIVATE" --java-home "$JAVA"
python3 build.py --sdk "$SDK" --java-home "$JAVA" --private-dir "$PRIVATE"
adb -s <USB_SERIAL> install -r "$PRIVATE/jarvis-monitor.apk"
python3 provision_phone.py --serial <USB_SERIAL> --private-dir "$PRIVATE"
python3 install_host.py --private-dir "$PRIVATE"
# Open JARVIS Monitor, grant force-lock permission, then enable.
```

For ordinary app code updates, rebuild and `adb install -r` with the retained signing
key. Pairing data and permission survive. Open the helper and re-enable after updates;
no package-replaced auto-start assumption. Never clear its data casually.

## Tests and current acceptance

```sh
python3 -m unittest discover -s tests -v
mkdir -p /tmp/jarvis-monitor-policy-test
"$JAVA/bin/javac" -d /tmp/jarvis-monitor-policy-test \
  android/src/local/jarvis/monitor/Policy.java tests/PolicyTest.java
"$JAVA/bin/java" -cp /tmp/jarvis-monitor-policy-test PolicyTest
```

Six Python tests cover sanitization, auth, minimal/no-store responses and no proxy/write
routes. Twenty standalone Java policy assertions cover transitions, debounce, stale,
unknown, age/clock/gap bounds, power gating, persisted states and no replay.

`tests/handset_acceptance.py` is an **explicit, physical screen test**, not an automatic
unit test. It temporarily stops only this relay and supplies phone-only TLS fixtures
at the same endpoint; the real presence backend and computer automation are untouched.
Its `finally` restores the production relay. Do not interrupt the process forcibly;
if interrupted outside normal cleanup, bootstrap the LaunchAgent above.

```sh
python3 tests/handset_acceptance.py --confirm-phone-screen-test \
  --serial <USB_SERIAL> --private-dir "$PRIVATE"
```

Live verification: authenticated pinned-TLS Wi-Fi polling (no ADB reverse), screen-off
on two fresh away samples, remaining off for unknown/stale samples, screen-on on fresh
nearby, and return to tinyCam LiveViewActivity. The app's independent 8-second screen
test also passed. Live feed was verified after wake. Actual walk-away/return timing,
wall-charger-only operation over long periods, reboot recovery, and secure-PIN behavior
still need physical acceptance. Synthetic fixture tests are not proof of BLE accuracy.
