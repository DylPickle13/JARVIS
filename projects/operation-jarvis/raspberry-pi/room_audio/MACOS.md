# Additional USB PowerConf endpoint on macOS

This runs the **same room conversation client/server** on `mac-mini-64`, with a
Core Audio subprocess backend instead of Linux ALSA. Nothing is installed into
speaker firmware. The Raspberry Pi endpoint remains independent.

## Layout

| Component | Mac endpoint | Existing Pi endpoint |
|---|---|---|
| Server | `127.0.0.1:8793` (loopback only) | port `8791`, unchanged |
| RPC context | `room-audio-mac` / `mac-mini-64-room-audio` | `room-audio` / `raspberry-pi-room-audio` |
| Client | macOS Core Audio, exact name `PowerConf` | Pi ALSA, unchanged |
| Agents | `com.operation-jarvis.room-audio-mac-{server,client}` | existing services, unchanged |

State, private environment, isolated client venv and logs:
`~/Library/Application Support/JARVIS/room-audio-mac/`.

The server reuses `JARVIS/.venv`, the existing Apple ASR helper/assets and Piper
voice assets. The client has its own Python 3.13 environment, sounddevice,
openWakeWord 0.6.0 with ONNX, and audioop-lts for streaming resampling. No global
Python packages or default macOS audio routes are changed.

The server code defaults still name the Pi context. Only the new agent sets
`JARVIS_ROOM_AUDIO_CHANNEL_ID` and `JARVIS_ROOM_AUDIO_CHANNEL_NAME`. Each server
owns its own Pi RPC process, follow-up tickets, jobs and single-client controls.
The existing app's room status and Stop **still address the Pi on 8791**, not this
endpoint. Multi-room app controls are not implemented here.

## Provision

From the JARVIS root, with `uv` installed and the existing server venv available:

```sh
projects/operation-jarvis/raspberry-pi/scripts/install-macos-room-audio.sh
```

This installs the isolated client requirements and wake models, generates an
independent random token in `environment.json` (0600, state directory 0700), and
writes two owner-only LaunchAgents. It does **not** start or restart services.
Credentials never appear in arguments, plists, Git or diagnostic output. Do not
print/share `environment.json`.

The configurator refuses port 8791, occupied ports and existing Mac agent files.
For an update, stop only the two Mac agents first, then run the installer with
`--replace`; the private token is preserved. `--port` and `--device` can select a
different free port/exact device name. The default port 8793 was selected because
8792 already belongs to another service on this host.

Start the server first; first-use TTS initialization can take several seconds:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.operation-jarvis.room-audio-mac-server.plist"
# Wait for this to return ok:true before starting the listener:
curl -fsS http://127.0.0.1:8793/health
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.operation-jarvis.room-audio-mac-client.plist"
```

These are per-user **login agents**, not pre-login system daemons. They start at
login and restart after process failure. macOS microphone access must be allowed
for the Python/helper responsible for capture. If needed, run a foreground
capture check and approve the OS prompt; do not bypass TCC. Both Python
microphone access and Apple ASR permissions/assets must work under the agent.

## Audio and conversation behavior

- Explicit, exact `PowerConf` input/output selection, 48 kHz mono capture and
  stereo output. Missing or ambiguous endpoints fail closed: never use another
  mic, a monitor or the default headphones. With multiple identically named
  PowerConfs, device-UID selection is required before this can be used safely.
- `room_audio_coreaudio.py` initializes PortAudio in a fresh worker per stream.
  Reconnecting USB causes enumeration again rather than reusing stale indices.
  Capture uses 20 ms frames with 100 ms buffering; the client agent uses
  Interactive scheduling to avoid background-QoS capture overruns. Stream
  overflow fails/restarts capture so stale wake audio is not authorized.
- WAV replies are resampled to the speaker's native rate and mono is duplicated
  to stereo. Playback is cancellable by terminating its dedicated subprocess.
  The normal VAD/turn state machine remains shared with the Pi implementation.
- Local “Hey Jarvis” gating, strict Apple Dictation wake verification, “Yes sir?”,
  then five seconds to **start** one separate request. Busy-only exact “stop”
  cancels playback/generation. Capture stays open during normal replies; the
  existing startup-greeting path briefly releases capture before reopening it.
- A fixed startup greeting says “The Mac room speaker is online, sir.”
- Continuous capture is private to the local client until a wake candidate (or
  busy-only control clip) is submitted to the local server. No new audio archive
  is created. Temporary WAVs are deleted by the existing handlers. Logs can
  include accepted transcripts, so keep the state directory private.

## Checks

```sh
ROOM=projects/operation-jarvis/raspberry-pi/room_audio
STATE="$HOME/Library/Application Support/JARVIS/room-audio-mac"
"$STATE/.venv/bin/python" "$ROOM/room_audio_coreaudio.py" list
curl -fsS http://127.0.0.1:8793/health
curl -fsS http://127.0.0.1:8793/control/status
launchctl print "gui/$(id -u)/com.operation-jarvis.room-audio-mac-client"
tail -n 30 "$STATE/logs/client.out.log"
tail -n 30 "$STATE/logs/client.err.log"
```

Expected: `local wake word online`, fresh `clientOnline:true`, phase `idle` when
not speaking/processing. Idle telemetry proves PCM transport, not audible mic
signal. Quiet-room noise suppression may produce zeros; test by speaking and
checking numeric VAD activity. Confirm speaker output by ear.

Offline regression tests (no live device, launchd or production HTTP changes):

```sh
.venv/bin/python -m unittest discover -s projects/operation-jarvis/raspberry-pi/room_audio -p 'test_*.py'
```

Initial deployment checks: 69 unit tests passed; real PowerConf playback heard
by the owner; microphone speech-level PCM and continuous wake inference observed;
real silent-WAV playback cancellation completed in about 22 ms; deliberately
terminating the capture worker recovered to fresh idle with the same client
process. The original 8791 server PID did not change. Physical USB unplug/replug
and a user-spoken full conversation/voice-stop still require live confirmation.

## Stop / rollback

Wait for the endpoint to be idle, then unload **only the new agents**:

```sh
launchctl bootout "gui/$(id -u)/com.operation-jarvis.room-audio-mac-client"
launchctl bootout "gui/$(id -u)/com.operation-jarvis.room-audio-mac-server"
```

Allow a few seconds for removal to finish before bootstrapping again. To disable
future login starts, also remove the two `room-audio-mac-*.plist` files from
`~/Library/LaunchAgents/`. Keep or privately delete the endpoint state directory.
No Raspberry Pi restart, token change, system output-route restoration or main
room-audio server restart is required.
