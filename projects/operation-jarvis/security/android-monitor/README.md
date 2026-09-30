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

With discovery enabled, the dedicated relay listens on IPv4 TCP 8794 across Mac
interfaces so address changes do not require a restart. Before TLS it rejects peers
outside loopback and RFC1918 private-LAN ranges. The legacy fixed-address mode remains
available by setting `discovery` false in private `server.json`.
There is no port forwarding, public relay, cloud service, CORS API or write route.
`GET /v1/presence` requires a random monitor-only bearer credential and returns only
protocol version, `nearby`/`away`/`unknown`, and age. Main JARVIS/camera credentials,
BLE identifiers, room inventory and RSSI never reach the phone. Request logging is
disabled. Backend failure yields unknown, not cached away.

The app requires HTTPS, pins the exact SHA-256 server certificate, checks certificate
validity and the **originally paired** hostname/IP SAN identity, rejects redirects,
and bounds response size and timeouts. The discovered address is only a routing hint;
it never becomes the trusted identity. A different certificate fails closed before
the bearer credential is sent. The generated certificate expires after 825 days;
renewal requires deliberate re-pairing, but an IP change does not.

### Automatic LAN discovery (v1.2)

The Mac advertises `_jarvis-monitor._tcp` through its built-in Bonjour (`dns-sd`).
The instance name contains only a public certificate fingerprint prefix, never tokens,
presence, or camera details. Android's `NsdManager` resolves that instance directly,
without depending on Android 6's unsupported ordinary `.local` hostname lookup.
Discovery refreshes every 30 seconds and is stopped when the helper is disabled.
Only RFC1918 IPv4 destinations are accepted. The original configured endpoint remains
a fallback when no discovered address is available; failed discovery/TLS leaves the
screen unchanged. Spoofed advertisements can disrupt availability, not bypass pairing.

Different Wi-Fi names work **if both networks permit local traffic and multicast DNS**.
Guest isolation, different routed subnets, or blocked multicast may prevent discovery;
this is not remote/internet access. A DHCP reservation is an optional fallback, not
required on a reachable Bonjour-enabled LAN. No router or Wi-Fi settings are changed.

For an existing installation, rebuild/install the helper and set `"discovery": true`
in the private Mac `server.json`, then restart only `com.jarvis.android-monitor`.
Keep the original client URL, certificate, and bearer credential: no re-pairing or
app-data reset is required. New provisioning enables discovery by default.

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

Mac LaunchAgent: `com.jarvis.android-monitor`. This is the only Mac relay service.
The optional Pi ARP repair below is separate. To stop the Mac relay without touching
other services:

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

## Video recovery and launcher task reuse (v1.3)

On 2026-09-30, two separate faults were isolated on the Nexus 5 / Android 6.0.1
with tinyCam 6.7.9:

- **Intermittent LAN reachability (initially observed on 2.4 GHz):** the handset's doorbell ARP entry remained
  `INCOMPLETE`/`FAILED` on home 2.4 GHz while it could reach the Pi and indoor
  camera. The Pi, on the same access point, reached the doorbell's RTSP service;
  the owner also confirmed Tapo live view worked. Wi-Fi reconnects did not repair
  this path. A temporary suspend-optimization test was unsuccessful and reverted.
  Moving only the handset to the owner's home 5 GHz network restored ARP, RTSP,
  and hardware-decoded video temporarily. The failure subsequently recurred on
  5 GHz too; changing bands is not a durable fix. See the directed ARP repair below.
  The precise AP-versus-doorbell firmware responsibility is not established.
  Existing Wi-Fi credentials, camera URL/authentication, RTSP-over-TCP, Hub Storage,
  and doorbell power settings were not changed by this recovery.
- **Duplicate live-view activities on wake:** Android 6 treated the extra package
  restriction in `getLaunchIntentForPackage()` differently from the normal
  launcher intent. Repeated launches stacked tinyCam live-view activities; one
  long-idle test returned to a frozen frame with 0 fps despite working RTSP.
  `WakeActivity` and the helper's Open tinyCam button now remove that restriction
  from the already-explicit component and add `FLAG_ACTIVITY_RESET_TASK_IF_NEEDED`.
  They resume the existing task instead of starting another player.

The signed v1.3 update was installed with `adb install -r` and the retained signing
key, without provisioning again or clearing app data. Pairing and administrator
permission survived. After checking for a pending-action warning, the helper was
re-enabled through its owner UI. Fresh camera screenshots showed advancing
camera timestamps and H264 hardware decoding at 19–20 fps. Two consecutive
8-second automatic sleep/wake tests retained exactly one live view. A separate
90-second screen-off test kept RTSP reachable and resumed live video with one
activity. These are bounded checks, not proof of overnight stability or physical
BLE walk-away/return accuracy.

For a phone-only regression check (does not replace/stop the Mac relay):

```sh
python3 tests/handset_launch_acceptance.py --confirm-phone-screen-test \
  --serial <USB_SERIAL> --cycles 2
```

Requires external power, an enabled helper with fresh nearby status and no
pending-action error, and one existing tinyCam live view. It checks automatic
sleep/wake and task reuse, not decoded-video liveness; verify advancing camera
timestamps and nonzero FPS separately.

**Avoid stale diagnostic evidence:** a failed `uiautomator dump` can leave an old
XML file intact, especially with the display off. Remove both remote and local
previous dumps first, require a fresh successful dump, and do not interpret a
cached FPS label as current playback. Use fresh screenshots with the display on
and compare the camera's timestamp across samples. Delete temporary camera images
after inspection and keep any temporary captures private.

Duplicate TTL-255/TTL-64 ping replies alone are not proof of an IP conflict:
[TP-Link documents this D235 ping behavior](https://community.tp-link.com/en/smart-home/forum/topic/726482).

## Optional Pi directed ARP repair

A later 2026-09-30 recurrence isolated an address-resolution failure, not another
player launch failure. The Nexus still had strong 5 GHz association, one live-view
activity and the enabled foreground helper, but its doorbell neighbour entry was
`FAILED`/`INCOMPLETE` and TCP reported `No route to host`. The Pi reached RTSP using
its known doorbell MAC. Scoped packet tests showed:

- Ordinary **broadcast ARP** sometimes received no doorbell reply, while otherwise
  identical **unicast ARP** received replies. Gateway, indoor-camera and Nexus
  control probes answered broadcast requests.
- During 20 alternating active-video probe cycles, doorbell broadcast replies
  were absent in 3 cycles, unicast replied in all 20, and the indoor-camera broadcast
  control replied in all 20. Both doorbell reply variants used the same MAC.
- After verifying the phone and doorbell IP/MAC pairs, one directed request carrying
  the handset's ARP sender identity made the doorbell reply directly to the handset.
  The Nexus neighbour entry changed from `STALE` to `REACHABLE` without an intervening
  handset RTSP probe or a camera-setting change.

This narrows the failing mechanism to intermittent broadcast ARP delivery/handling
on the doorbell's LAN path. It does **not** establish which AP or doorbell firmware
component drops it, or prove that loss of the cached entry was caused by a specific
sleep/roam event. Duplicate replies alone are not an IP-conflict diagnosis. A later
fresh-cache Wi-Fi reconnect also worked without repair: the fault is intermittent,
not reproducible on every reconnect. The stale JARVIS device-registry routing hint
was separately corrected to the already-verified current address; the registered
read-only security status then authenticated the D235 successfully.

`arp_repair.py` bypasses that discovery fault on a Linux host on the same LAN:

1. Send ordinary directed queries and validate **both** current, configured IP/MAC
   associations. Discard queued old replies, reject inconsistent identities, and
   fail closed on timeouts, receive floods or a different subnet.
2. Relay the verified handset's lookup as a directed request to the doorbell. Keep
   the **Ethernet source as the Pi**, so neither device's bridge/FDB entry moves.
   Only the ARP sender fields carry the verified handset identity.
3. The **doorbell supplies its own real reply** directly to the handset. The repair
   process never fabricates an ARP reply, redirects camera traffic, opens a network
   listener or receives/decodes video. Successful dispatch is not proof of receipt.

The ten-second interval maintains/retries discovery; all video still flows directly
between tinyCam and the doorbell using the original URL, credentials, RTSP-over-TCP
and hardware decoder. Android's `arp_accept=0` can ignore an unsolicited reply when
no neighbour entry exists yet; recovery may wait for tinyCam's next connection
attempt to create an unresolved entry. This does not change that kernel setting.
No router configuration, camera RPC, pairing, Hub Storage, power mode, Android
preferences or presence policy is changed. No credential is
required by this process. MAC checks are LAN routing checks, **not cryptographic
identity authentication**; existing camera authentication remains unchanged.

### Explicit Linux installation / rollback

The reviewed source is installed at `/opt/jarvis-monitor-arp/arp_repair.py` and the
unit at `/etc/systemd/system/jarvis-monitor-arp.service`, root-owned and not writable
by its service user. The owner-created `/etc/jarvis-monitor-arp.env` (root 0600)
contains only `INTERFACE`, `PHONE_IP`, `PHONE_MAC`, `DOORBELL_IP`, `DOORBELL_MAC`.
Use actual, verified unicast MACs, not Android's `02:00:00:00:00:00` privacy placeholder.
Do not put camera passwords, bearer credentials or the security `.env` in this file.

After explicit installation on the chosen Linux host:

```sh
sudo systemd-analyze verify /etc/systemd/system/jarvis-monitor-arp.service
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-monitor-arp.service
sudo journalctl -u jarvis-monitor-arp.service -n 20 --no-pager
# Stop/retire just this optional support service:
sudo systemctl disable --now jarvis-monitor-arp.service
```

The unit uses a dynamic unprivileged user with **only `CAP_NET_RAW`**, no
`CAP_NET_ADMIN`, read-only system/home protections and restricted socket families.
It does not replace or restart the Pi presence service, Mac relay or any other host
service. It is enabled for boot; actual host reboot acceptance is separate.

**Operational limits:** this is a targeted workaround, not an AP/doorbell firmware
fix. The Pi must be available, and this service is independent of the handset's
Enable/Disable button. Stop it too when retiring the monitor. Configured phone and
doorbell addresses must still match their verified MACs; DHCP reservations are
recommended. It re-reads its own interface address every cycle, but does not implement
phone/doorbell IP rediscovery. Wrong or changed mappings fail closed. An actual
unreachable doorbell or failed decoder cannot be repaired by ARP requests.

Live acceptance on 2026-09-30:

- Two automatic eight-second sleep/wake cycles retained one player and resumed
  hardware-decoded video at 19 fps.
- A separate **900-second screen-off interval** retained the correct doorbell MAC
  in all 31 thirty-second samples, with no `FAILED`/`INCOMPLETE` entries. Three
  samples were normal `STALE` (a resolved, aged mapping), not lost resolution.
  No handset RTSP probes were run during this interval. Manual wake resumed the
  existing player at 19 fps without a restart; fresh camera timestamps advanced.
- With repair running, an explicit Wi-Fi off/on test cleared the handset neighbour
  cache, rejoined the original 5 GHz network, regained authenticated nearby status,
  and returned to one live view at 19 fps. A reconnect without repair also succeeded
  earlier, so this is recovery acceptance, not a deterministic failure-injection test.
- Subsequent fresh screenshots at 17:42:56, 17:51:41 and 17:55:26 EDT showed
  advancing camera timestamps and H264 hardware decoding at 18–19 fps across
  a 12.5-minute playback-check span. The support unit ran without crash restarts,
  and a deliberate restart of only this unit resumed lookup dispatch.
  Its installed source/unit checksums matched the reviewed files. The existing Pi
  presence service and Android foreground helper remained active.

These are bounded checks, not proof of overnight stability, actual BLE walk-away/
return, cold boot, future DHCP changes, or repair of arbitrary network/player faults.
Temporary camera screenshots and UI dumps are private diagnostic artifacts and are
removed after inspection, not stored in this repository.

## Tests and current acceptance

```sh
python3 -m unittest discover -s tests -v
mkdir -p /tmp/jarvis-monitor-policy-test
"$JAVA/bin/javac" -d /tmp/jarvis-monitor-policy-test \
  android/src/local/jarvis/monitor/Policy.java tests/PolicyTest.java
"$JAVA/bin/java" -cp /tmp/jarvis-monitor-policy-test PolicyTest
```

Eighteen Python tests cover sanitization, auth, minimal/no-store responses, no proxy/write
routes, LAN-only peer admission, credential-free discovery advertisements and the ARP
repair's frame construction, identity/subnet checks, fresh-reply requirement, bounded
receive draining and fail-closed dispatch. Twenty standalone Java policy assertions cover transitions, debounce, stale,
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

Live v1.2 verification: the Nexus discovered the Mac's new LAN address from a different
home Wi-Fi while keeping the old paired identity and token. Authenticated polling and
phone-only fixtures passed across relay/advertisement restarts. A spoofed-discovery test using the same service name and a different certificate
(with the same SAN) produced repeated TLS rejection and **zero HTTP requests**;
production polling recovered afterward. Run explicitly with:

```sh
python3 tests/handset_pin_acceptance.py --confirm-phone-discovery-test \
  --private-dir "$PRIVATE"
```

This temporarily replaces only the monitor relay and restores it in `finally`.
Actual future Wi-Fi switching and multicast-blocked networks are not covered by these tests.

Live verification: authenticated pinned-TLS Wi-Fi polling (no ADB reverse), screen-off
on two fresh away samples, remaining off for unknown/stale samples, screen-on on fresh
nearby, and return to tinyCam LiveViewActivity. The app's independent 8-second screen
test also passed. Live feed was verified after wake. Actual walk-away/return timing,
wall-charger-only operation over long periods, reboot recovery, and secure-PIN behavior
still need physical acceptance. Synthetic fixture tests are not proof of BLE accuracy.
