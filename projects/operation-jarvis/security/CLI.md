# Standalone security CLI

The core CLI implementation is in **security_cli.py**, with offline tests in
**test_security_cli.py**. Audio, video, doorbell and recording adapters have
separate modules and offline test suites. The legacy archive probes also supply
helpers used by the supported clip-download path. `security` is a small shell launcher for the isolated
Python 3.13 environment. This CLI installs no daemon or scheduled task. The
project's optional [Operation JARVIS Pi tools](../../../.pi/docs/OPERATION_JARVIS_TOOLS.md)
wrap bounded reads and guarded automation enable/disable.
The separately deployed backend now wraps `status` in an API-token-protected
on-demand route; see [deployment evidence](../docs/security-integration-plan.md).
Reviewed source/docs/templates are tracked; credentials, inventories, media and
runtime/commissioning records stay ignored. See [repository privacy](README.md#repository-privacy).
Aliases below are command examples, not an installed-device inventory.

## Experimental Tapo cloud Smart Actions

Unlike local device commands, `smart-actions` explicitly authenticates to **TP-Link's
cloud**. It manages app shortcuts/automations, not per-device recording schedules.
No daemon, polling, automatic MFA requests, or login/write retry. A stable JARVIS
terminal identity and cloud session are persisted in ignored, owner-only (0600)
`private-smart-actions/terminal.json` and `session.json` (directory 0700).
Ordinary calls reuse the token without logging in. A missing/rejected session
requires explicit reauthentication; unknown cloud errors also stop without login.
Never commit, print, or share these files. Delete `session.json` to forget the local
token; this does not revoke the session at TP-Link. Keep `terminal.json` to retain
the device identity.

Initial sign-in or renewal: `./security --json smart-actions list --reauthenticate`
(owner-operated CLI only). In Pi, use automations `action: "list", reauthenticate: true` to sign in and
cache the session, including from voice. Reload Pi extensions after updating to expose this
parameter. Sign-in may trigger an account email; token reuse is intended to reduce
alerts, not guarantee their absence.

```bash
./security --json smart-actions list
./security --json smart-actions describe REF  # allowlisted partial summary; no export
./security --json smart-actions show REF
# show prints a private JSON file path; it never dumps device IDs/locations to stdout.
# REF and REVISION below come from a recent list/show, not a device alias.
./security smart-actions rename REF --revision REVISION --name 'New name' --confirm
./security smart-actions disable REF --revision REVISION --confirm
./security smart-actions enable REF --revision REVISION --confirm
./security smart-actions update REF --revision REVISION --file PRIVATE_RULE.json --confirm
./security smart-actions create --file PRIVATE_NEW_RULE.json --confirm
./security smart-actions delete REF --revision REVISION --confirm
# Real device actions; this is NOT a verification step:
./security smart-actions execute REF --revision REVISION --confirm --allow-actions
```

**Acceptance:** cloud listing and a temporary name change/restoration were live
verified. The integrated CLI passed a live read-only smoke test. Create, full
update, enable/disable, delete, and execute are implemented and tested against
synthetic offline peers, **not yet live-accepted**. The Pi suite now exposes
enable/disable live (owner approval 2026-09-20); other mutations remain CLI-only.

- `list` returns names, opaque references, kind, enabled status and SHA256 revisions.
  These summaries are still private household data; don't publish CLI output.
- `describe` returns bounded allowlisted trigger/action configuration, not raw
  device IDs, location, RPCs or private files. Unknown fields and trigger combination
  semantics remain uninterpreted; it is not proof of physical behaviour.
- `show` saves the exact rule to a fresh owner-only file in `private-smart-actions/`.
  Edit that file locally for `update`. Keep the same ID and all fields you intend to
  preserve: **update replaces the complete rule**, it is not a JSON merge/patch.
- `create` uses a complete SmartInfo JSON object **without `id`**; a new eight-character
  base62 ID is generated and collision-checked. Required core fields: `name`, boolean
  `enabled`, `triggerSetting` with boolean `isManual`, and object `actionSetting`.
  Device IDs, trigger syntax and action schemas must be valid for the cloud/devices;
  the CLI checks the envelope, not every firmware-specific nested action.
  Start with `enabled: false`. Creating an enabled rule, or updating a rule that is
  enabled before or after the edit, additionally requires `--allow-active`.
  Renaming an enabled rule also requires `--allow-active`, since it saves the rule.
- `enable` explicitly approves activating an automation. It may trigger physical
  actions immediately or later. `execute` only accepts manual shortcuts and requires
  `--allow-actions`; acknowledgement is **not proof of completed physical actions**.
- Existing-rule mutations and execution require an exact fresh `--revision`.
  A stale revision fails before any write. This is a client-side preflight check,
  **not a server-atomic conditional write**: don't simultaneously edit in the app.
- Every write saves an exclusive owner-only before/requested backup before sending.
  At most one mutation request is sent per invocation. CRUD writes read back the
  complete account list and require exact target/other-rule equality; harmless
  server normalization or concurrent edits can therefore produce outcome unknown.
  There is no blind rollback, automatic restore, auto-delete cleanup or replay.
- `write_outcome_unknown` exits 3. Inspect current state and the private recovery
  backup before any further operation; don't simply repeat a timed-out command.
  Worker interruption may require locating the backup under `private-smart-actions/`.
- Bounded to 100 rules/five pages, 14 HTTP requests, eight-second per-request timeout,
  and a 110-second parent deadline. Larger/inconsistent listings fail closed, not
  silently truncated. No generic RPC, firmware/account management or URL overrides.

### Cloud setup and trust

The commissioned username lives in owner-only ignored
`private-notes/smart-actions/account.json` as `{"username":"YOUR_CLOUD_EMAIL"}`.
The password is read from the existing private `--env-file` (default `.env`);
local device usernames are **not** silently rewritten or changed. A different cloud
password can use a separate owner-only env file with `JARVIS_SECURITY_PASSWORD`.
No email/password/token is included in command arguments or normal output.

Transport uses Python's standard library and scoped TLS trust with certificate and
hostname verification enabled. No system trust changes, redirects, environment
proxies or TLS-disable fallback. The private CA bundle and static signing reference
are pinned by SHA256 in `security_smart_actions.py`, sourced from
[piekstra/tplink-cloud-api at d516245](https://github.com/piekstra/tplink-cloud-api/tree/d516245e89b911a5e765f66d767366378fde5f6b/tplinkcloud).
Required ignored owner-only files under `private-notes/smart-actions/` are
`reference-signing.py` (from `signing.py`) and `tplink-ca-chain.pem` (from `certs/`).
Only two static constants are parsed from the reference; that source is never
executed/imported. Missing/changed files fail closed; setup performs no downloads.
This trusts the pinned published vendor-CA bundle, not an independent security audit.

Save/delete/execute routes and new-ID format come from the decompiled
[Tapo API interface](https://github.com/flyingsnake5254/tapo110/blob/master/com/tplink/iot/c/b/i.java)
and [SmartRepository](https://github.com/flyingsnake5254/tapo110/blob/master/com/tplink/libtpnetwork/IoTNetwork/repository/SmartRepository.java).
These are unofficial historical contracts; API availability can change.

## Experimental D100C chime

```bash
./security --json chime status
./security --json chime capabilities
# Audible action; only run intentionally:
./security chime ring --tone 1 --volume 1 --seconds 1 --confirm
./security chime stop --confirm
```

Discovers exactly one D100C advertising TPAP/HTTP/PAKE-2, then authenticates and
verifies its model before further requests. Multiple matches fail closed; no
registry alias is currently used. Status/capabilities are live authenticated reads,
not offline advertised assumptions. Six preset tone IDs were read successfully.
The reported volume is the chime's persistent configuration, not camera playback gain.

**Custom sound files/TTS are not supported by this adapter.** No upload/stream API
was found, and the usual Tapo media/RTSP ports were unreachable during the bounded
check. This is not proof that all firmware can never support custom audio. Use the
D235/C230 speaker audio commands for custom sound or JARVIS speech instead.

Preset ring/stop commands are implemented. A low-volume, one-second preset request
and subsequent stop were acknowledged; saved settings matched in a separate
readback. The owner subsequently confirmed hearing tone 1 at normal volume with a
three-second request; automatic readback verified saved settings unchanged.
The owner also confirmed that stop cut an actively sounding chime off early.
Ring defaults to tone 1, low volume and one requested second; allowed test overrides
are tone 1–6, volume 1–3 (low/normal/high), duration 1–5 seconds. Tone IDs are checked
against the live list. Uses per-play `alarm_type`, `alarm_volume`, `alarm_duration`,
not a persistent config setter. Firmware acceptance and duration behavior need an
owner test. Timeouts after sending an action report outcome unknown; never auto-retry.
There is no custom-file `play` command, arbitrary RPC, cloud access or background service.

The Node worker has a 25-second deadline (30-second parent timeout), six HTTP
requests maximum (seven for ring, including automatic settings readback), per-request limits, no redirects/proxy, device proof and response
sequence checks. Credentials travel over stdin only; output is allowlisted.
Actions require confirmation before discovery; hub/doorbell/chime locks prevent
concurrent control sessions. Status is verified. The later owner-authorized preset test is separate from the
custom-audio investigation; ringing a preset does not establish custom sound support.

Transport source is `security_chime_transport.mjs`: a narrow PAKE-2/P-256/SHA256/
AES128-CCM implementation using Node's native HTTP/crypto and pinned
`@noble/curves` 2.4.0 in ignored `private-notes/chime-tpap-v2/`. It only accepts
the verified D100C password transformation and negotiated suite. No fallback
identities, alternate-password attempts, Axios, bn.js or elliptic are used.
The superseded TPAP prototype and its dependencies have been deleted.

The worker verifies transport-source and runtime-dependency digests before import.
Unexpected modifications or non-CLI dependency symlinks fail closed. Ring reports
whether persistent settings matched before/after readback. Temporary session keys
are cleared on close; no logs or credential files are written. Dependencies are
separate from `requirements.txt`; missing/changed dependencies fail closed.

The replacement passed synthetic peer/proof/tamper/sequence/bounds/HTTP guard tests
and live authenticated status. Its npm audit reported **zero known vulnerabilities**
at commissioning; this is not a security guarantee or independent protocol audit.
The integration remains experimental. No unattended service has been enabled.

## Staged doorbell events (delivery disabled)

```bash
./security --json events front-doorbell status
./security --json events front-doorbell history --minutes 10
./security --json events front-doorbell preview --minutes 10
```

`status` is offline. `history` performs one authenticated H200 detection-history
query for the uniquely resolved D235, with hub/device locks and the isolated
45-second worker limit. Window: 1–60 minutes; at most 20 source rows, no automatic
paging or polling. No media is captured. `preview` adds **suppressed** notification
decisions and never sends anything. No notification destination is configured.

This is staging, not working real-time notifications: actual event delivery,
child attribution, timestamps and button/motion type mapping await a controlled
physical test. An empty list does not prove absence of activity. Unknown schemas
and invalid timestamps fail closed; arbitrary source text and IDs are stripped.
Types stay `unknown`, even if a numeric code is present; motion is never inferred
to mean a button press. Duplicate normalized rows within one query are collapsed;
there is no persistent cursor or cross-run deduplication yet.

Before activation: verify separate motion/press events, arrival delay and clock
semantics; implement validated mappings and persistent deduplication/backfill
policy; choose/approve a destination and delivery rate limits; then explicitly
authorize any background worker. None of those services is installed by these commands.

## Doorbell live video and snapshots

```bash
./security --json snapshot front-doorbell --confirm
./security live front-doorbell --seconds 30 --confirm
./security --json live front-doorbell --seconds 2 --verify-only --confirm
```

D235 direct-host entries only. All media access requires explicit confirmation
before networking, authenticated identity verification and hub/device locks.
Defaults to the dedicated local HEVC bridge and **HD preview** (`subtype=0`)
for both live view and snapshots. Use `--quality low` for the original H.264
preview (`subtype=1`). Neither path is a native camera RTSP endpoint. The local bridge listens only on
loopback; its API uses a per-session token. Its RTSP listener is loopback-only,
not separately authenticated: other local processes can access it while active.
Nothing is exposed to the LAN or cloud. No recording settings are changed.

- `snapshot`: one JPEG, unique non-overwriting name under `private-snapshots/`;
  directory mode 0700, file mode 0600. Never automatically displayed or uploaded.
  Capture is bounded to 25 seconds after setup. Snapshot retention is manual.
- `live`: local FFplay window, muted, no recording; default 30 seconds, range
  1–120. The wall-clock viewer limit includes buffering/startup. Close the window
  early or press Ctrl-C to stop. Viewer completion is not owner-confirmed visibility.
- `live --verify-only`: FFmpeg decodes video to a null sink; reports decoded frame
  count, displays/saves no footage. Verification has a bounded startup allowance.
- Session processes and temporary credential/config files are cleaned up after
  completion, failure or cancellation. No persistent viewer service is installed.

Live commissioning decoded 40 frames and saved a 1280×960 snapshot. HD through
the existing H.264-only Tapo adapter did not decode; HD/HEVC decoding and owner-visible live view are verified. The HD default uses a
separate ad-hoc-signed `JARVIS Doorbell Video.app` with the explicit HEVC patch in
`go2rtc-doorbell-hevc.patch` (applied on top of the native16 source). Neither the
existing audio bundle nor any room service is replaced. Initial HD tests failed
with `no route to host`. After local-network permission approval, a two-second
HD test decoded 39 frames successfully and a 30-second HD viewer run completed.
The owner selected HD as the default; `--quality low` remains available. Allow the new app
under System Settings → Privacy & Security → Local Network before retesting:

```bash
./security --json live front-doorbell --quality hd --verify-only --seconds 2 --confirm
```

Audio capture/playback and archive playback are not part of this feature.

## Quick start

From this directory (the launcher also works by absolute path):

```bash
./security --help
./security devices
./security --json status hub
./security --json status indoor-camera
./security --json capabilities indoor-camera
./security --json storage hub
.venv-313/bin/python -m unittest test_security_cli -q
```

`devices` is offline. Other commands above perform an explicit bounded device read.
Global options (`--json`, `--env-file`, `--registry`) go BEFORE the command.
Direct equivalent: `.venv-313/bin/python security_cli.py ...`.

`devices.json` maps aliases to model and private LAN host. `@hub` resolves to the
host in the owner-only `.env`. Hub/camera operations use the Tapo credentials
loaded privately from that file. RTSP Camera Account credentials
are separate and are not used by these commands. No credentials are accepted as
CLI arguments or emitted in output. Never shell-source `.env`.

## Paired sensors

T100 motion and T110 contact sensors are supported as H200 children, not separate
LAN hosts. A private registry entry selects a hub alias, sensor model and exact
owner-configured Tapo name. The following hypothetical aliases must exist in your
private registry before use:

```bash
./security --json status motion-sensor
./security --json status door-sensor
```

Sensor `status` and `capabilities` are read-only and expose motion/contact,
low-battery warning, and signal where available. No battery percentage is assumed.
Selection requires exactly one matching model and Tapo name; renaming in Tapo
requires updating `devices.json`. Missing/duplicate matches fail closed.
Reads share the hub's lock. No sensor writes or pairing actions are supported.
Results are **hub-reported snapshots**, not proof of fresh radio contact or
continuous monitoring. Missing/errored features are unknown. No event history,
notifications, or alarm automation is installed.

## D235 doorbell

Direct D235 entries use `model: D235`, `hub: hub`, and a privately configured
`host` after authenticated identity verification. Direct access uses pytapo over
HTTPS rather than UDP discovery (a camera may answer HTTPS but not discovery).
Every invocation checks model **and** device type. It shares the hub lock with
legacy hub-metadata reads and does not inherit C230 movement/audio controls.

```bash
./security --json status front-doorbell
./security --json capabilities front-doorbell
```

Reports 30 fields covering battery/power, privacy, LED, detection and sensitivity,
speaker/microphone configuration, recorded audio, PIR, night vision, ring enable,
chime schedule enable and clip configuration. Missing/failed fields stay unknown.
Advertised component names/versions are separately labeled: an advertised feature
is not a working CLI command. Neither status nor capabilities captures media.

Implemented settings (explicit `--confirm` required; **writes were not exercised
on the live device during development**):

| Setting | Values |
|---|---|
| `privacy` | `on`, `off`; also `privacy front-doorbell on/off` |
| `led` | `auto`, `off` |
| `motion_detection`, `person_detection`, `vehicle_detection`, `pet_detection`, `package_detection` | `on`, `off` |
| `person_sensitivity`, `vehicle_sensitivity`, `pet_sensitivity`, `package_sensitivity` | 1–100 |
| `pir_sensitivity` | 10–100 |
| `speaker_volume`, `microphone_volume` | 0–100 (device settings, not C230 playback gain) |
| `microphone_mute`, `noise_cancelling`, `record_audio` | `on`, `off` |

Examples below are device writes, not setup/test commands:

```bash
./security set front-doorbell person_detection on --confirm
./security set front-doorbell speaker_volume 35 --confirm
./security privacy front-doorbell on --confirm
```

A setting's getter must work before a setter is sent. Only that setting is written,
followed by a fresh getter. Transport/session/HTTP request replay is disabled on
this connection; errors after the write starts report `write_outcome_unknown`,
never silently retry. Verified readback is not physical acceptance. A timeout on
a write is conservatively unknown. Re-query status before deciding to retry.

Two-way audio, quick-response playback, real-time event delivery, persistent chime
configuration, an archive playback viewer, power-mode changes, spotlight/night-vision controls,
pairing and firmware remain **not implemented**. Local live view and private
snapshots are implemented above; native camera RTSP is not verified.
Recording schedules, hub archive indexes and bounded clip downloads are now
available below. D100C direct authentication is separate; seeing it on LAN does
not establish control. No siren or chime test was performed. Short speaker
transmission tests completed, and the owner confirmed clear JARVIS speech with
1.5-second leading padding. Transport completion alone still does not prove
audibility on subsequent runs.

`security_doorbell.py` launches `security_doorbell_direct.py` in the existing
isolated `.venv-archive/bin/python`, pinned by `requirements-archive.txt`. Each
worker has a 45-second bound (90 seconds for clip download/verification) and
returns an explicit allowlist of fields, never
credentials, host addresses, device IDs, Wi-Fi data or custom response text.
No background polling or deployment is installed.

Legacy entries without `host` remain read-only hub snapshots, selecting exactly
one D235 from H200's camera list. They report hub storage/24-hour-plan/Wi-Fi-backup
and network mode. Network mode is not electrical power mode; hub storage enabled
does not prove recordings exist. Legacy entries reject all writes.

### Recording and hub archive commands

```bash
# Read-only plan, actual power mode and hub-storage readiness:
./security --json recording front-doorbell status

# Device writes: replace all seven days with continuous or event-only recording:
./security recording front-doorbell continuous --confirm
./security recording front-doorbell events --confirm

# Custom weekly plan (device-local time), explicit write:
./security recording front-doorbell schedule --schedule-file weekly.json --confirm

# Hub metadata only; defaults to preceding hour, excluding newest 60 seconds:
./security --json recordings front-doorbell
./security --json recordings front-doorbell --start '2026-01-01T12:00:00-05:00' --end '2026-01-01T12:30:00-05:00'

# Local media download: use ACTUAL recent timestamps from the index above.
# Example dates are illustrative and must be replaced with dates in the past day.
./security --json clip front-doorbell --start '2026-01-01T12:05:00-05:00' --end '2026-01-01T12:05:05-05:00' --confirm
```

Weekly JSON must contain exactly `monday` through `sunday`, each an array of at
most ten sorted, non-overlapping `HHMM-HHMM:1` (continuous) or `HHMM-HHMM:2`
(event-only) segments. For example, a day's array may be
`["0000-0800:1", "0800-2400:2"]`. Empty arrays/gaps mean no scheduled recording
in those periods. Every schedule write enables the plan and replaces all seven
days; no audio/detection settings are changed. Continuous segments require a
fresh `wired_always_on` read. All writes require enabled/online hub storage,
perform no retries, and verify the complete plan by readback. An already matching
plan is left untouched. A schedule does not prove recorded media continuity.

Archive queries accept Unix seconds or ISO timestamps **with an explicit UTC
offset**. Query ranges must be within the past 24 hours and at least 60 seconds
old. One page of at most 20 clips is returned; narrow the range if truncated.
Index entries are not proof that every frame is readable. Timestamps emitted in
ISO format are UTC; supplied EDT offsets are accepted normally.

`clip` requires a range covered by a returned index entry and requests at most
10 seconds. The media transport is capped at 12 MiB and 35 seconds. Codec/keyframe
boundaries may make the saved duration slightly different from the requested
interval. A completion notification and nonzero bytes are required. Files use
random names in ignored, owner-only `security/private-archive/`; no arbitrary
output paths, overwrites, uploads or automatic display are offered. Ordinary
failures remove partial files; a killed worker may leave an ignored `.partial.ts`.

If FFmpeg/FFprobe are installed, the completed clip is locally probed and video
decoded (no images displayed). `video_decode_verified` explicitly reports the
outcome; **audio decoding remains unassessed**. A successful transfer alone is
not successful playback, and one decoded sample does not prove uninterrupted
coverage. The commands do not download tools or change power/storage settings.

## Camera controls

Examples below are actual writes when explicitly executed with `--confirm`:

```bash
./security privacy indoor-camera on --confirm
./security privacy indoor-camera off --confirm
./security set indoor-camera led off --confirm
./security set indoor-camera motion_detection on --confirm
./security set indoor-camera person_detection on --confirm
./security set indoor-camera pet_detection on --confirm
./security set indoor-camera baby_cry_detection off --confirm
./security set indoor-camera tamper_detection on --confirm
./security move indoor-camera left --degrees 10 --confirm
./security move indoor-camera right --degrees 10 --confirm
./security move indoor-camera up --degrees 5 --confirm
./security move indoor-camera down --degrees 5 --confirm
```

`privacy on` sets SDK camera `state` OFF; it does not turn off electrical power.
`privacy off` permits capture again. `set indoor-camera state on|off` is also
supported, but the explicit privacy command is less ambiguous.

Movement is ONE request of 1–30 requested degrees, not an absolute position or a
promise that the motor travelled that far. SDK action aliases `pan_left`,
`pan_right`, `tilt_up`, `tilt_down` are also accepted by `action`; these use the
SDK defaults (30 degrees pan, 10 degrees tilt). Prefer `move` for explicit bounds.
The SDK's step settings are process-local: they are not offered as persistent
settings, and `move` configures the step in the same invocation.

## Camera and doorbell speaker audio

The direct-host D235 supports the same `audio speak/play/status/stop/volume`
commands as the C230. Shared audio preparation now waits for child-process
completion rather than sleeping out fixed polling intervals, retaining bounded
cancellation checks. This applies to standalone speech/file playback and the
room-camera playback worker. A single muted C230 comparison measured preparation
at 0.985 → 0.789 seconds and total runtime at 4.375 → 4.031 seconds; network and
synthesized phrase duration varied, so these are not guaranteed savings. C230
identity already took about 0.25 seconds; no doorbell padding was added. The room
camera continues reusing its existing session; no service restart was performed.

Speech defaults to our **JARVIS (Piper)** voice; no
`--voice` override is needed. D235 identity is checked over direct HTTPS with
hub/device locks before connecting to the PCMA/8 kHz speaker transport. This
fresh identity-only check skips the full settings snapshot to reduce startup
delay; authentication and model/type verification are not cached or skipped.

```sh
./security audio speak front-doorbell --text 'Hello, sir.' --confirm
./security audio play front-doorbell /path/to/message.mp3 --volume 30 --confirm
```

Local WAV, AIFF, MP3, M4A/AAC, FLAC, Ogg and supported media containers are
converted to mono speaker audio; URLs/playlists are not supported. Codec support
depends on local FFmpeg. Short live speech transmissions, including the default
JARVIS voice, completed. The owner selected and confirmed clear playback with
1.5 seconds of leading silence and two seconds of trailing silence; this padding is now
automatic for D235 only.
Explicit duration limits include padding. The owner confirmed clear speech at
60%, then requested a saved front-doorbell gain of 100%, verified by readback. Playback gain does not change persistent doorbell speaker settings.


The commissioned C230 supports local custom audio through the permission-approved
**JARVIS Camera Audio 16k.app** (go2rtc). D235 and all other models fail closed until
separately commissioned. This is foreground CLI functionality, not a backend route
or an automatically installed service.

```bash
# Default voice: the existing local Piper JARVIS voice, not the macOS system voice.
./security audio speak indoor-camera --text 'Good evening, sir.' --confirm
./security audio speak indoor-camera --text-file message.txt --volume 40 --confirm
printf 'Good evening, sir.' | ./security audio speak indoor-camera --text-file - --confirm

# Entire local file; no arbitrary duration cutoff.
./security audio play indoor-camera /path/to/announcement.mp3 --volume 50 --confirm
# Optional duration cap, or repeat until explicitly stopped.
./security audio play indoor-camera /path/to/sound.wav --duration 20 --confirm
./security audio play indoor-camera /path/to/sound.wav --loop --confirm

# Another terminal can inspect or stop preparation/playback.
./security --json audio status indoor-camera
./security audio stop indoor-camera --confirm
# Ctrl-C in the playback terminal also stops and cleans up.

# Read/save the default gain for FUTURE sessions (not current playback).
./security audio volume indoor-camera
./security audio volume indoor-camera 35 --confirm
# Explicit alternative installed macOS voice; never used as a silent fallback.
./security audio speak indoor-camera --text 'Hello, sir.' --voice Daniel --confirm
```

### Volume and duration

- Volume is **digital signal gain, 0–100 percent**; 0 is muted, 100 is full source
  level. The initial default is 30. This does **not** read/change the camera's
  hardware speaker-volume setting. Physical loudness depends on that setting and
  the source recording. Saved defaults apply on the next invocation, not mid-play.
- By default there is **no playback-duration limit or text truncation**. The CLI
  waits for file completion. `--loop` repeats indefinitely until stop/Ctrl-C;
  repetitions have a small gap. `--duration SECONDS` is an optional positive cap,
  including across loops; it excludes synthesis/connection time. A poll or network
  request can delay stopping slightly; it is not a sample-accurate timing promise.
- Synthesis and conversion can take time and temporary disk space proportional to
  input size. Whole-file preparation happens before playback; speech is chunked
  without dropping text. This is not a live microphone or network-radio interface.
- Network setup/requests retain short timeouts. The completion watchdog scales
  with the actual media duration plus 30 seconds; it is not the general CLI's
  25-second bound. A transport error during playback is an uncertain outcome,
  never an automatic replay.

### Dependencies and permissions

- FFmpeg must be on PATH; macOS `open` launches an explicitly permission-approved
  go2rtc app. This host's approved bundle remains at
  `private-notes/audio-poc/native16/JARVIS Camera Audio 16k.app`; preserve its identity and
  Local Network permission. `--app /path/to/Your.app` selects another reviewed
  compatible bundle containing `Contents/MacOS/go2rtc`. The CLI does not download,
  re-sign, install, or auto-approve apps.
- Default speech uses `../.venv/bin/python`, Piper and the already-cached
  `jgkawell/jarvis` voice (high quality by default). The worker reads only the
  project's `JARVIS_VOICE_TTS_*` synthesis preferences and environment overrides.
  No model download, LLM call or microphone capture occurs. Missing dependencies
  or cached models fail rather than silently switching voices.
- Backend implementation: `security_audio.py`; isolated synthesis worker:
  `security_tts.py`; offline tests: `test_security_audio.py`.

### Privacy and results

`--confirm` approves audible output. Prefer stdin or `--text-file` for private
speech so it is not stored in shell history/process arguments. Only configured
C230 hosts are used, with a fresh live identity check and the normal device lock.
While audio holds that lock, other CLI camera operations fail busy; audio
status/stop remain available. Local files only; playlists and network-fetching
FFmpeg protocols are disallowed. Output is mono 8 kHz speech-quality audio.
This is the physically verified speaker format: higher advertised speaker rates
failed listening tests. The separate room listener can preserve native 16 kHz
microphone input without changing this output path; see [quality evidence](AUDIO-QUALITY.md).

`audio_completed` means the transport session finished, not microphone-verified
physical playback. `audio_stop_requested` is a cooperative request; inspect status
or wait for the playback command's `audio_stopped` result. Status is local session
state, not a fresh camera capability/status query.

Runtime metadata in `.audio-runtime/` and defaults in `.audio-settings/` are
owner-only and ignored by Git. Speech, converted audio, authentication hashes and
random loopback API credentials are temporary. The API is bound to loopback with
an ephemeral credential; RTSP is loopback-only; WebRTC/STUN are disabled. Other
users/processes with access to the local account remain trusted, not sandboxed.
Normal completion, Ctrl-C, SIGTERM, stop and handled errors terminate the exact
session's app/FFmpeg processes and remove temporary files. Forced SIGKILL, power
loss or an OS crash cannot run cleanup; do not use SIGKILL as the normal stop path.
No persistent camera audio setting or long-running service is changed.

Run offline regression tests:

```bash
.venv-313/bin/python -m unittest test_security_cli test_security_audio -q
```

## Hub controls

```bash
./security capabilities hub
./security set hub led on --confirm
./security set hub alarm_volume 3 --confirm
./security set hub alarm_duration 10 --confirm
./security set hub alarm_sound '<exact choice from capabilities>' --confirm
./security action hub stop_alarm --confirm
./security action hub test_alarm --confirm --allow-audible
```

Alarm volume/duration are validated against the SDK's reported ranges. Alarm
sound must exactly match a reported choice. Starting a test additionally requires
a freshly read configured duration of **1–60 seconds**. The configured duration
is enforced by the hub, not by a scheduled Mac stop command; local behavior still
requires commissioning. `stop_alarm` is explicit, never automatic.

A capability being listed is not evidence its control works or has passed physical
acceptance. The CLI exposes only the reviewed SDK
features; new/unknown vendor capabilities are not automatically executable.

## Results and safeguards

- JSON contains fixed error reasons, allowlisted values, and a timestamp. No raw
  responses, device IDs, account credentials, images, or sensor histories.
- `security_assessment` always remains `not_assessed`.
- Device/model validation precedes controls. Requests target one configured host.
- One operation at a time per alias across CLI processes, using a local file lock.
- Non-audio network work has a 25-second overall bound plus up to 2 seconds for disconnect.
  Audio has bounded setup/requests, but playback runs to media completion by default.
- Protocol queries use zero SDK retries. No automatic retry of writes.
- Settings are reread after writes with module cache timestamps invalidated.
- `verified` means the read-back matched; it is not physical/security verification.
- Actions return `acknowledged`, not a claim the physical effect was observed.
- Any exception after a write begins reports `write_outcome_unknown`; inspect
  status before deciding whether to repeat a command.
- An errored feature is unknown, never silently false/off.
- `storage` success means the query succeeded; inspect `card_state`. An offline
  card does not prove absence. Healthy storage does not prove recording/playback.

Exit codes: **0** successful read / matched setting / acknowledged action;
**2** validation, unsupported operation, credentials, or read failure;
**3** uncertain write or mismatched read-back; **130** cancellation before a
write. Cancellation during a write is conservatively an uncertain outcome.

`--confirm` is explicit operator intent, NOT authentication or an authorization
boundary. Anyone who can run this CLI with access to its credentials can control
the devices. The backend currently exposes only authenticated status; any future
write route must enforce its own permissions and confirmation.
Status/settings are private household data: do not publish results or forward
them into external telemetry. There is no persistent result/audit log.

## Preserved diagnostic commands

```bash
./security check-env --env-file .env
./security check-env --env-file .env --identity-only
./security storage-probe                  # offline; no credential load/network
./security storage-probe --env-file .env --probe
./security commission                     # private interactive terminal only
./security offline-status status          # earlier offline hub contract
```

The legacy diagnostic commands retain their original JSON/exit semantics. The
old `python -m jarvis_security...` paths have been removed by consolidation.

## Not exposed by this CLI

Pairing/unpairing, formatting, factory reset, firmware changes, recording schedules,
clip listing/download, RTSP viewing, live microphone streaming, tracking, presets, zones, notification
rules, and general raw vendor RPCs. Separate experimental archive and recording-plan
scripts are described in [README.md](README.md); they are not CLI/backend commands.
These capabilities are not all exposed by the pinned SDK;
unsafe guesses at undocumented write endpoints are not used. Offline sensor/frame
contracts are retained in the same file. Sensor snapshots are now available as
above, but no continuous sensor tracker or video pipeline is connected. Add functionality only after its protocol and safeguards are
understood and its commissioning is approved.
