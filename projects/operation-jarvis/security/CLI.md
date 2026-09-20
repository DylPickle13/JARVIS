# Standalone security CLI

The core CLI implementation is in **security_cli.py**, with offline tests in
**test_security_cli.py**. Experimental probes are separate scripts. `security` is a small shell launcher for the isolated
Python 3.13 environment. This CLI installs no Pi tools, daemon or scheduled task.
The separately deployed backend now wraps `status` in an API-token-protected
on-demand route; see [deployment evidence](../docs/security-integration-plan.md).
Reviewed source/docs/templates are tracked; credentials, inventories, media and
runtime/commissioning records stay ignored. See [repository privacy](README.md#repository-privacy).
Aliases below are command examples, not an installed-device inventory.

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

## Camera speaker audio

The commissioned C230 supports local custom audio through the permission-approved
**JARVIS Camera Audio.app** (go2rtc). D235 and all other models fail closed until
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
  `private-notes/audio-poc/JARVIS Camera Audio.app`; preserve its identity and
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
