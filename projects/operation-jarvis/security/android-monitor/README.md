# Android doorbell monitor — presence helper

Security subproject for an Android 6 / API 23 handset. It controls the handset
display and a private, hardware-decoded RTSP/TCP viewer, **not** the doorbell's
settings, recordings, alarms, or computer. v1.5 replaced the leaking tinyCam
playback path; v1.6 adds listen-only audio, defaulting on in v1.6.1 at the owner's
request. v1.7 adds optional, phone-local GPU lens correction; v1.8 adds a lightweight
local Voice focus audio filter. tinyCam was subsequently
uninstalled at the owner's request; private rollback backups remain on the Mac.
DroidCam (`com.dev47apps.obsdroidcam`) was also uninstalled at the owner's request;
it is not part of this viewer's playback path.

## Architecture

```
Existing authenticated basement presence → dedicated Mac read-only TLS relay
                                         ← phone polls over home Wi-Fi every 5s
Phone: fresh away twice → DevicePolicyManager.lockNow()
       fresh nearby → wake screen → private viewer (only if no secure keyguard)
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
- A fresh initial nearby state may wake/open the selected viewer; initial away needs two checks.
- **Wall power required for automatic screen actions.** On battery the helper
  releases its CPU/Wi-Fi locks and pauses actions. There is no USB runtime dependency.
  No wireless ADB is enabled. Screen sleep is not full phone shutdown: while plugged
  in, a foreground service keeps a partial CPU and Wi-Fi lock to receive arrival.
- A persisted pending action blocks restart/replay after an uncertain crash. The
  owner reviews and explicitly re-enables in the helper. It is not silently retried.
- A nonsecure swipe keyguard may be dismissed to restore playback. A PIN/password
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
protocol version, `nearby`/`away`/`unknown`, and age. The presence relay never carries main JARVIS/camera credentials,
BLE identifiers, room inventory or RSSI. The viewer's separate camera account is
provisioned privately over USB, not sent by the relay. Request logging is
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
2000**; normal apps cannot use it. No credential readback route exists. Presence
pairing cannot be replaced; re-pairing requires a deliberate app-data reset
(disable/remove Administrator permission first if Android requires it). The separate
v1.5 camera configuration supports only explicit hash-matched replacement, below.

Source, tests, and docs are trackable. Only generated artifacts/secrets/caches are
ignored; private runtime is outside the repository. Do not publish configs or keys.

## Owner controls

Open **JARVIS Monitor** on the phone (or tap its persistent notification):

1. Grant screen-lock permission using Android's administrator prompt.
2. Enable automation after reviewing any pending-action error.
3. **Disable automation** stops the helper and releases locks without waking/sleeping.
4. **Test: sleep then wake in 8 seconds** tests only this phone, while externally powered.
5. **Open camera viewer** returns to playback. **Use private camera viewer** selects
   the new player; uncheck it only after separately reinstalling/configuring tinyCam.
6. In the viewer, **Audio: muted** enables listen-only sound; **Audio: on** mutes it.
   Android's media-volume buttons adjust the existing output volume. New foreground
   sessions/wakes default to audio on; there is no microphone, recording or talk-back.

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

Requires JDK 17, Python 3, OpenSSL, authorized USB ADB and build-tools 35 under
`android-15/`. `fetch_player_dependencies.py` downloads the checksum-locked API-33
compile platform and ExoPlayer dependencies under the supplied SDK cache, outside
the repository. Runtime minimum/target remain API 23. No Gradle or analytics is used.
The initial SDK archives were checked against Google's repository checksums.
JDK 17 was installed through Homebrew; no global Java/PATH change was made.

```sh
cd projects/operation-jarvis/security/android-monitor
PRIVATE="$HOME/Library/Application Support/JARVIS/android-monitor"
JAVA=/opt/homebrew/opt/openjdk@17
SDK="$HOME/Library/Caches/jarvis-android-sdk"

# FIRST setup only: refuses to overwrite an existing private directory.
python3 provision.py --host <MAC_LAN_IPV4> --private-dir "$PRIVATE" --java-home "$JAVA"
python3 fetch_player_dependencies.py --sdk "$SDK"
python3 build.py --sdk "$SDK" --java-home "$JAVA" --private-dir "$PRIVATE"
adb -s <USB_SERIAL> install -r "$PRIVATE/jarvis-monitor.apk"
python3 provision_phone.py --serial <USB_SERIAL> --private-dir "$PRIVATE"
python3 install_host.py --private-dir "$PRIVATE"
# Open JARVIS Monitor, grant force-lock permission, then enable.
```

For ordinary app code updates, rebuild and `adb install -r` with the retained signing
key. Pairing data and permission survive. From v1.6, Android's protected
`MY_PACKAGE_REPLACED` broadcast restarts only an already-enabled helper with no
pending action; it preserves the last applied presence state. Disabled/pending
helpers stay disabled/pending. Verify the service after installation rather than
assuming startup. Older builds require opening/re-enabling the helper. Never
clear its data casually.

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

## Native RTSP viewer (v1.5) — tinyCam OOM replacement

On 2026-10-01, updated tinyCam 15.3 (6640), using Hardware+, exhausted its
512 MiB Java heap after roughly 5.5 hours. Runtime logs retained 511 MiB/512 MiB
after GC and failed even 16-byte allocations, ending with `JavaBinder: Forcefully
exiting` at 23:41:09 EDT and process exit at 23:41:10. The separate crash buffer
did not record this exit. Several threads failed allocations; the retaining
component inside tinyCam remains unknown. The update and decoder setting were
**not** a fix.

The deployed solution **removes tinyCam from automatic playback**, rather than
restarting it on a timer. tinyCam was initially retained, then uninstalled during
owner-authorized cleanup. APK/data backups remain privately on the Mac, not the
phone. The temporary v1.4 process-relaunch workaround was superseded
and is not part of this source.

### Playback and lifecycle

- ExoPlayer 2.19.1 Java RTSP client, forced interleaved TCP, Android MediaCodec
  hardware video surface; no ads, WebView, per-frame bitmaps or recording. v1.5 was
  video-only; v1.6 adds listen-only audio, defaulting on in v1.6.1 as described below.
- Same camera endpoint/account/stream; no camera/hub/router setting changes, video
  relay, transcoder, host service, BLE policy change or USB runtime dependency.
- Non-exported, single-task `ViewerActivity` runs in a separate `:video` process.
  Presence polling stays in the original helper process.
- One player at a time. Pause/screen sleep releases player, sockets and decoder;
  resume creates a fresh session. Wake/Open reuse one viewer activity.
- Media buffer target 2 MiB, 0.5–1.5-second loading window. These bound the playback
  queue, **not total process memory**. No large-heap request.
- Missing rendered frames for 30 seconds or a playback error releases the player.
  At most five reconnects (5/10/20/30/60 seconds); then an explicit status-label tap
  or a new foreground session is required. Sixty seconds of healthy frames renews
  that budget. Retries never wake a screen or change presence.
- Holding the status label deliberately closes only this viewer's RTSP socket,
  useful for a scoped reconnection test; it does not change Wi-Fi or the camera.
- Existing fresh-nearby/two-fresh-away/unknown/keyguard/power/pending-action gates
  remain unchanged. Viewer startup never unlocks a secure keyguard.

### Optional lens correction (v1.7)

The top-left **lens/grid icon** cycles **original → mild → medium → strong → original**.
**v1.7.2 defaults to Strong**, as selected by the owner after visual comparison.
Existing saved choices take precedence; later manual choices remain saved rather
than being reset on wake. Earlier v1.7/v1.7.1 installs defaulted to original.
The lens choice is saved in private `viewer-renderer` preferences; it survives
sleep/wake and app recreation. v1.8 also saves the audio-filter choice there, never
listening/mute/focus permission or presence pairing/camera configuration.

- Hardware H.264 decoding feeds one external OES texture. An OpenGL ES 2 shader
  applies an approximate, centred equidistant-to-rectilinear mapping:
  `source = centre + (output - centre) * atan(r*k)/(r*k)`, with the zero-radius
  limit of 1. Radius accounts for video aspect ratio; strengths are 0 / 0.8 / 1.2 /
  1.55. SurfaceTexture's producer matrix handles texture orientation/crop.
- This is **not Tapo's calibrated correction**. Moderate correction visibly reduces
  bowing in this porch scene; too much can bend lines the other way. **Medium** was
  left selected after initial device acceptance; the owner subsequently preferred
  **Strong**, now the default. Stronger correction crops more peripheral
  view, stretches/softens edge detail and may remove the camera timestamp. Original
  restores the full uncorrected view; it still uses the GPU path for seamless toggles.
- The button changes only a shader uniform, not the RTSP session, decoder or audio.
  Rendering is frame-driven, not a busy loop; there are no CPU frame copies,
  readbacks, bitmap queues or added network services. Test screenshots are opt-in,
  outside Git, and are not a feature of the installed viewer.
- Playback's stall watchdog uses newly consumed GPU frames, not redraws of a frozen
  texture. Background/screen-off releases the player before the decoder Surface,
  SurfaceTexture and GL context. Resume builds a fresh output; generation checks
  reject stale callbacks. Known shader/draw/context-recreation failures fall back
  to the original native surface using the existing bounded retry budget, disabling
  the lens control until a new foreground session. GL initialization is timed out.
  Device GL failure injection remains untested; this does not guarantee recovery
  from every driver failure or prove that a drawn frame reached the physical panel.

Opt-in tests (already-awake, foreground viewer with nearby status; no forced wake):

```sh
python3 tests/handset_dewarp_acceptance.py --serial <USB_SERIAL> \
  --confirm-viewer-and-audible-test --leave-mode medium
# Optional --capture-dir "$PRIVATE/dewarp-comparison" saves private camera images.
```

Device acceptance verified all four modes with advancing video/GPU/audio counters
and no RTSP restart, inspected original/corrected screenshots, working audio controls,
and three sleep/automatic-wake cycles releasing the GPU and retaining the lens choice.
One deliberate viewer-socket interruption reconnected with correction and audio on.
A 303-second, six-sample observation held one process/player, advancing GPU/video/audio
counters and no retries: whole-video-process PSS 86,822–88,496 KiB, allocated Java heap
22,561–24,696 KiB and reported battery temperature steady at 41.6 °C. This is not a
GPU-only overhead measurement; Android 6 meminfo may itself request GC.

All 32 Python tests, 14,214 geometry assertions and 17 on-device URI assertions passed.
The unit suite includes bounded/monotonic geometry, aspect ratios, a synthetic-line
round trip and source-level lifecycle guards. Installed APK matched the build;
scoped source/APK/sampled-log credential scans were clean. Short tests are not overnight
stability or thermal certification; actual lens calibration remains approximate.

### Compact controls (v1.7.1)

The two large text buttons are now small white vector icons on translucent circular
backgrounds. They occupy the side margins on the Nexus's current 4:3 feed rather
than covering the picture. Each retains a **48dp touch target**, a 24dp glyph, ripple
feedback and an accessible description; unavailable controls dim.

- **Top left: grid/lens.** Curved grid and no lit dots means original. A straight
  grid with one/two/three lit dots means mild/medium/strong correction.
- **Top right: speaker.** Waves mean audio on; a cross means muted.
- v1.8 adds a sliders icon below the speaker for **Original / Voice focus**.
- Hold any enabled icon for a short text hint. Normal taps work as before; no
  stream restart, preference reset or audio-default change. The bottom status label
  and its recovery controls are unchanged.

v1.7.1 acceptance: 33 Python tests passed; all four lens modes and audio mute/unmute
worked through the icons without restarting RTSP. Device UI checks verified 48dp lens
touch targets and accessible state labels. One sleep/automatic-wake cycle retained
medium correction and restored audio on; final screenshot inspected privately.

v1.7.2 makes Strong the missing-preference default without overwriting saved choices.
The 33 Python tests passed; Strong survived the in-place update and one automatic
sleep/wake cycle with audio on and advancing GPU frames. Default selection is covered
by model/source tests, not by clearing the paired handset's app data. No new extended
Strong thermal/overnight soak is claimed.

### Lightweight Voice focus (v1.8)

The small **sliders icon below the speaker** switches **Original / Voice focus**.
A lit dot indicates Voice focus; hold for a text hint. Like the other icons it has
an accessible state description and 48dp touch target. Voice focus defaults on for
this owner-authorized feature; saved choices take precedence across sleep/wake and
app recreation (`viewer-renderer` / `voice-focus`). This preference does **not**
unmute audio or grant focus. Mute/focus/presence safeguards remain unchanged.

- Phone-local processing of decoded **8 kHz, mono, PCM16** before the audio sink.
  No neural model, resampling, new dependency, worker thread, service, network path,
  camera setting, microphone access, recording, volume boost, AGC or speech gate.
- A 120 Hz second-order Butterworth high-pass reduces low-frequency rumble. A small
  256-point, 50%-overlapped FFT applies conservative stationary-noise suppression:
  smoothed per-bin power, approximately two seconds of rolling minima, smoothed
  gains, and a 0.5 amplitude floor (at most 6 dB attenuation per spectral bin).
  Suppression starts after roughly half a second of learning. The high-pass can
  attenuate low frequencies more strongly than 6 dB.
- This is **not WebRTC/RNNoise or a human-voice classifier**. It should reduce rumble
  and steady background noise, not isolate a person perfectly. Sudden passing cars,
  wind overlapping speech, quiet/distant voices and microphone clipping remain
  difficult. Stronger suppression risks distorting speech, so this version is mild.
- Mode changes use a 64 ms crossfade without reconfiguring the player or RTSP tracks.
  Original returns bit-exact PCM after the transition and skips FFT/noise work;
  both modes keep the same small analysis buffer to switch without a timing jump.
  The processor holds 128–255 samples (16–32 ms); end-of-stream draining preserves
  the exact sample count and never overwrites an outstanding downstream buffer.
- About **22 KiB of primitive DSP arrays**, no per-frame DSP allocation, at most
  4096 input bytes consumed per call and a 4352-byte reusable output buffer. An EOS
  tail uses at most another 512 bytes. These are **not whole-app memory limits**.
  Flush/reset and player release discard buffered PCM/DSP; unsupported rates or
  channel formats bypass filtering and disable its control rather than resampling.
- Diagnostics contain only mode/support/sample-count and processing-thread CPU-time
  totals. CPU percentages divide processor CPU time by consumed audio duration;
  they do not measure the complete player, output audibility or physical A/V sync.

Tests (synthetic test does not play or record audio; live test requires nearby,
already-awake foreground playback with Voice focus and audio initially on):

```sh
python3 tests/handset_voice_processor_test.py --serial <USB_SERIAL> \
  --sdk "$SDK" --java-home "$JAVA_HOME" --private-dir "$PRIVATE" \
  --confirm-synthetic-cpu-test
python3 tests/handset_voice_acceptance.py --serial <USB_SERIAL> \
  --confirm-audible-filter-test
```

The synthetic harness precompiles only its temporary candidate APK/test copy on the
ARM handset: Android 6's uninstalled `app_process` interpreter otherwise grossly
overstates CPU cost. It tests the real ExoPlayer processor/pipeline, arbitrary chunk
sizes, Original bit identity, EOS/backpressure, reset, unsupported-format bypass,
synthetic rumble/noise attenuation and preservation of a modulated speech-band burst.
There is no real-speech recording or perceptual acceptance hidden in these tests.

Acceptance: 36 Python tests, 38,511 synthetic DSP assertions and 366,310 on-device
processor assertions passed. Compiled synthetic Voice focus cost about 2% of one
core; final live A/B measured 1.63% in Original and 3.93% in Voice focus (including
the PCM adapter). Clock scaling/workload differ; these are not whole-app CPU
percentages. Live toggles, mute-preserving filter changes and both modes' sleep/wake
persistence passed, with Strong lens retained and no RTSP restart during toggles.

A 303-second observation held one process/player, advancing GPU/audio/PCM and battery
temperature at 41.6 °C, with about 3.93% of one core used by the processor. That
observation preceded a final EOS-only buffer-ownership fix. The final APK repeated
A/B/mute and one sleep/wake test, followed by a 61-second, three-sample observation:
continuing counters, no retries, 41.6 °C and whole-process PSS 93,510–94,391 KiB.
These are short observations, not isolated thermal/memory-overhead measurements;
Android meminfo can trigger GC. Artifacts/metadata remain private. Actual speech
quality, distant-voice preservation, acoustic synchronisation and overnight thermal
stability still need owner listening/longer observation.

### Listen-only audio (v1.6; audio-on default in v1.6.1)

An authenticated, metadata-only check of this doorbell's `/stream2` advertised
one **PCMA / G.711 A-law, 8000 Hz, mono** track. ExoPlayer 2.19.1 supports its RTP
payload and the Nexus reports `OMX.google.g711.alaw.decoder` support. There is no
transcoder, relay, camera-setting change, microphone permission or audio recording.

- Audio is selected/decoded from session startup, with **player volume zero before
  prepare/play**. Muting is not disabling capture at the camera: the stream still
  contains audio, and the phone still receives/decodes it while the viewer is active.
  This avoids changing RTSP tracks/restarting video when toggling mute.
- At the owner's request, **v1.6.1 defaults to audio on** for a new foreground
  session/wake. A supported selected track, resumed/unlocked viewer and granted
  Android audio focus are still required. The top-right button toggles mute.
  No system-volume change or forced speaker routing: sound uses the current
  Android media output/volume.
- Mute, loss of focus (including transient/duck), or a becoming-noisy/headphone
  disconnect event silences the player and abandons focus. Focus returning never
  automatically unmutes. Muted playback does not request audio focus.
- Backgrounding/screen-off/sleep stops audio and releases both decoders, sockets,
  focus and player. Returning/waking/recreating the activity defaults to audio on.
  Within one foreground session, reconnect preserves the on/muted choice. Manual
  mute, focus loss/denial and headphone disconnect remain muted across reconnects;
  track callbacks never repeatedly request focus. No mute preference is persisted.
- No supported audio track disables the button without blocking video. An identified
  audio-renderer failure falls back to video-only for the rest of that foreground
  session, through the same bounded reconnect budget. Other failures retain the
  ordinary bounded recovery policy; audio cannot create an unbounded retry loop.
- Diagnostics expose only mute/focus/availability/fallback flags, numeric rendered
  audio-buffer counts, volume and a restricted decoder name—not samples or speech.
  Advancing buffers **do not prove audible speaker output**. A human ear test remains
  separate. The earlier v1.5 memory soak does not establish v1.6 audio reliability.

Opt-in device test (requires already-awake viewer and nearby status; never forces wake):

```sh
python3 tests/handset_audio_acceptance.py --serial <USB_SERIAL> \
  --confirm-audible-test --confirm-lifecycle-test
```

It briefly enables sound at the existing media volume, verifies advancing audio
buffers and video frames without a session restart, mutes/releases focus, and
optionally checks that leaving stops sound and returning restores the audio-on
default. Tests end muted unless `--leave-audio-on` is supplied. Temporary UI XML
is removed. Historical v1.6 acceptance on 2026-10-02 (before the default changed) passed
listen/mute without RTSP restart, advancing audio/video counters, reset-to-muted
after leaving an unmuted viewer, and a two-cycle sleep/automatic-wake run with
one viewer and muted audio. Playback was observed at 19–20 fps. In-place update
resumed the enabled helper without clearing pairing or its pending-action gate.
The 28 Python tests, 20 presence-policy / 70 player / 11 socket-guard / 60 audio
policy assertions, and 17 on-device URI assertions passed. The installed APK's
hash matched the build; scoped source/APK/sampled-log credential scans were clean.

At the owner's request, v1.6.1 changes the default to audio on. Its 28 Python
checks, 84 audio-policy assertions and 17 on-device URI assertions passed. Device
acceptance verified audio on without tapping, working mute/unmute, release when
backgrounded, audio on after reopening, and audio on after one automatic sleep/wake
cycle. Manual mute/focus denial/loss surviving reconnect is covered by policy tests,
not a new reconnect fault-injection test.

Acoustic output, focus-loss, actual headset unplug, unsupported-track and
audio-failure fallback still need device acceptance; host policy/source tests
are not a substitute for those physical/failure-injection checks. No long-duration
audio memory/availability claim is made.

### Credential and destination safety

`player.json` lives in app-private, non-backed-up storage, separate from presence
pairing. It is provisioned only through the existing signature-level DUMP **and**
exact shell-UID gate over already-authorized USB. Nothing secret is placed in
Intents, exported activities, APK assets, Git, screenshots or diagnostic output.
Only literal RFC1918 IPv4, port 554 and `/stream1` or `/stream2` are accepted.

The original ExoPlayer RTSP parser incorrectly splits **decoded** authority at the
first `@`, misrouting email-style camera usernames. The locked source is patched
at build time to strip user-info from **encoded** authority at the final delimiter.
Build fails if either patch no longer matches uniquely. Seventeen on-device tests
cover ordinary/email/multiple-`@` usernames, password colons/percent/slashes/spaces,
and unauthenticated URIs. Independently, `CameraSocketFactory` refuses every peer
except the configured numeric camera address and port, before DNS or connect, and
bounds connect time to five seconds. Library diagnostics are intercepted: only
whitelisted RTSP method/status tokens and counts are retained, never raw messages.

Prototype URI-parser warnings had included a password in the phone's ephemeral
main debug buffer. Those entries were cleared after retaining nonsecret failure
evidence; final raw/encoded-credential checks cover the running build. No such logs
were committed or sent to a third party. Earlier unpatched attempts produced
unanswered TCP connects to the misparsed domain; final socket guards prevent this.

The presence pairing remains immutable. An explicitly requested camera-config
replacement requires `--replace-existing-sha256` matching the current file bytes;
it atomically replaces **only** `player.json`, not pairing or app data. Never retry an
uncertain replacement. tinyCam backup preference strings were Base64-encoded and
had to be decoded privately during this owner's migration.

### Build/provision and rollback

See `THIRD_PARTY.md` and `player-dependencies.json` for exact sources/licenses/hashes.
Dependencies remain outside Git. API 33 is used **only for compilation**; the
manifest minimum and target stay API 23. No extra Android permission is added.

```sh
python3 fetch_player_dependencies.py --sdk "$SDK"
python3 build.py --sdk "$SDK" --java-home "$JAVA" --private-dir "$PRIVATE"
adb -s <USB_SERIAL> install -r "$PRIVATE/jarvis-monitor.apk"
# First viewer provisioning only: mode-0600 private JSON, not a file in this repo.
python3 provision_player.py --serial <USB_SERIAL> --config "$PRIVATE/player.json"
```

The private JSON has `version: 1`, `host`, `port: 554`, `path`, `username` and
`password`. Never put its contents on a command line or in an issue/commit.
Open the helper, review any pending error, enable automation and use **Open camera
viewer**. **Use private camera viewer** defaults on only after provisioning.
To use the tinyCam fallback after cleanup, deliberately reinstall/configure it
from the private rollback materials first, then uncheck the private-viewer option.
Backup restoration has not been validated; it is no longer a one-tap rollback.
Do not clear JARVIS data or re-pair. tinyCam's original memory exhaustion would
then be a known risk again.

### Tests and acceptance

```sh
python3 -m unittest discover -s tests -q
# Compile/run PolicyTest, PlayerTest and CameraSocketFactoryTest with JDK 17.
python3 tests/handset_uri_acceptance.py --serial <USB_SERIAL> --sdk "$SDK" \
  --java-home "$JAVA" --private-dir "$PRIVATE"
python3 tests/handset_viewer_acceptance.py --serial <USB_SERIAL> \
  --confirm-phone-viewer-test --confirm-audible-test --cycles 3
```

The lifecycle test normally requires fresh nearby. `--confirm-temporary-wake` is
an **explicit owner-operated screen test**, not fabricated presence: it permits
the existing eight-second phone-only self-test while away. It leaves video open
for observation; restore the prior screen state afterwards. It never acknowledges
pending errors or changes backend data.

Nonsecret diagnostics and bounded memory/frame observation:

```sh
adb -s <USB_SERIAL> shell dumpsys activity local.jarvis.monitor/.ViewerActivity
adb -s <USB_SERIAL> shell dumpsys activity service local.jarvis.monitor/.MonitorService
python3 tests/observe_player.py --serial <USB_SERIAL> --samples 11 --interval 60 \
  --output "$PRIVATE/viewer-observation.jsonl"
```

Verified on 2026-10-02: 19–20 fps with `OMX.qcom.video.decoder.avc`, advancing
camera timestamps, successful authenticated RTSP/TCP setup, and no tinyCam process.
One deliberate RTSP-socket interruption produced 0 fps followed by automatic fresh
playback, with opens/releases changing from 1/0 to 2/1. Three eight-second automatic
sleep/wake cycles each released the old player, reused one viewer and resumed
advancing rendered frames. Pairing, administrator permission and presence rules
survived. Shell Wi-Fi-disable requests left Wi-Fi enabled, so they are **not**
counted as an outage test; socket closure is the tested failure injection.

Final validation passed 24 Python tests, 20 presence-policy assertions, 70 player
assertions, 11 no-network socket-guard assertions and 17 installed-parser assertions.
The 605-second final soak contained 11 samples with the same PID, one active player,
no retries/restarts and rendered frames advancing from 1,141 to 13,224. PSS was
50,918–52,767 KiB; allocated Java heap was 17,622–20,191 KiB. The installed APK
matched the verified local build. Fresh-away screen sleep was restored afterwards;
the helper remained enabled, pending=false, and all five player instances had been
released. Numeric acceptance metadata is private; temporary images/XML were deleted.

Android 6 `dumpsys meminfo` can request GC; these sample ranges do not prove absence
of all leaks. Overnight and
physical BLE departure/return acceptance remain untested. This replaces the known
failing app path, not a claim that tinyCam's internal leak was repaired or that the
monitor can never fail. Prefer supported Android hardware/current Media3 long term.

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
between the selected viewer and the doorbell using the original URL, credentials,
RTSP-over-TCP and hardware decoder. Android's `arp_accept=0` can ignore an unsolicited reply when
no neighbour entry exists yet; recovery may wait for the viewer's next connection
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
JAVA="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
mkdir -p /tmp/jarvis-monitor-policy-test
"$JAVA/bin/javac" -d /tmp/jarvis-monitor-policy-test \
  android/src/local/jarvis/monitor/Policy.java tests/PolicyTest.java
"$JAVA/bin/java" -cp /tmp/jarvis-monitor-policy-test PolicyTest
```

The offline Python suite covers sanitization, auth, minimal/no-store responses, no proxy/write
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
