# Camera replacement for the Pi-connected PowerConf

The C230 can provide **both microphone PCM and speaker playback** to the existing
room conversation client. The Mac runs the camera transport and local wake model;
the existing **Pi-room server on loopback 8791** still handles Apple ASR, follow-up
policy, Pi RPC, JARVIS TTS, room controls and shared conversation state.

The Mac USB PowerConf endpoint on 8793 is independent and unchanged. Never run
the old Pi USB listener and this camera listener against 8791 simultaneously.

## Current deployment

Owner confirmed the camera conversation worked and requested a complete move off
the Raspberry Pi. The camera endpoint is installed as the login LaunchAgent
`com.operation-jarvis.room-audio-camera` in `~/Library/LaunchAgents/` and running.
At the owner's subsequent request, the Raspberry Pi room-audio installation was
**removed**, not merely disabled: service/drop-ins/backups, client scripts and
bytecode, private environment, dedicated venv/models/logs/backups, old PowerConf
test WAVs/logs, dedicated BlueALSA override, and PowerConf Bluetooth pairing.
Verification found no dedicated remaining paths or pairing; systemd reports
`LoadState=not-found`. General OS packages and unrelated Pi services were retained.
Both the reused room server (8791) and Mac USB endpoint (8793) reported online/idle
after the persistent switch. Room audio no longer requires Raspberry Pi hardware.

The existing server's historical “Pi-room” label and the `raspberry-pi/room_audio`
source directory do not imply a current hardware dependency. “Pi RPC” refers to
the AI agent software running on the Mac, not the Raspberry Pi.

## Components

- `pi_room_audio_client.py --audio-backend camera`: unchanged VAD/wake/turn policy,
  with camera capture/playback subprocesses instead of ALSA/Core Audio.
- `room_audio_camera.py`: owner-only session manifest; loopback-only RTSP audio
  capture to mono signed 16-bit PCM; custom audio sent through authenticated local
  go2rtc API. No camera credential appears in subprocess arguments.
- `camera_room_audio_service.py`: owns the permission-approved go2rtc app and room
  client. Keeps one camera stream available instead of reconnecting per reply.
  On exit, closes client/capture/playback processes and temporary session files.
- `test_room_audio_camera.py`: offline tests; never captures audio or changes a
  service.

Only the previously commissioned C230 is accepted. No D235 support is inferred.
The original named `JARVIS Camera Audio.app` remains the speaker-only CLI and
rollback dependency. The active microphone upgrade uses the separately approved
`JARVIS Camera Audio 16k.app` with **microphone-only** changes; its speaker code is
identical to upstream. See `../../security/AUDIO-QUALITY.md`.

## Privacy and limitations

- The camera microphone streams continuously to the Mac while this endpoint runs.
  The commissioned endpoint now preserves its **native PCMU/16 kHz** microphone
  audio through a minimal opt-in go2rtc patch. The original stock path downsampled
  it to 8 kHz before the client upsampled it; that loss is now avoided. Speaker
  replies remain on the correct-speed **PCMA/8 kHz** path. Advertised 16 kHz speaker
  support did not work correctly in listening tests and was rejected. See
  [audio quality evidence and build notes](../../security/AUDIO-QUALITY.md).
  Wake distance and transcription accuracy still need physical tests.
- Idle ordinary speech is discarded by the local wake gate. Only wake candidates,
  the authorized separate request, and busy-only interrupt clips go to the existing
  loopback server. Strict independent Apple wake verification remains enabled.
- No new audio archive is created. Existing room code uses temporary turn WAVs
  and may log accepted transcripts: keep endpoint logs private. The proprietary
  Tapo preview transport can carry video alongside audio internally; the client
  selects only audio and does not save video or snapshots.
- Microphone PCM continued during camera playback in a live transport test.
  This does **not** establish USB-equivalent echo cancellation, speech intelligibility,
  wake accuracy or voice-stop reliability. Confirm by speaking near the camera.
- Reply cancellation stops only the reply producer, not the persistent mic stream.
  A silent live worker test completed normally and cancelled in about 150 ms.
- Volume is digital gain, initially 30 percent, in this endpoint's private
  environment.json. It is independent of standalone security CLI saved defaults.
  Changing it requires restarting this endpoint; hardware volume is unchanged.
- A shared room session's microphone consumers remain active after a reply ends.
  Playback completion therefore watches reply producer IDs, not consumer count.
- Camera/network loss means this room cannot hear/respond until recovery; there
  is no automatic activation of a USB microphone. Returning to the Pi PowerConf
  would now require reinstalling its removed room-audio software.
- The existing capture watchdog restarts stale/failed capture. The supervisor
  restarts with launchd if its go2rtc app/client fails. No threshold was lowered
  and no wake/verifier/interrupt safeguard was bypassed.
- Speaker workers take the existing security device lock. Avoid simultaneous
  standalone camera announcements and conversational replies. Room controls,
  not `security audio status/stop`, own this continuous endpoint's conversation.

## Trial configuration and deployment

Private state: `~/Library/Application Support/JARVIS/room-audio-camera/` (0700).
Its environment.json and logs are owner-only. No token or recorded speech belongs
in Git. The Mac wake client's existing isolated venv/model cache is reused without
changing that endpoint's configuration or process.

From the JARVIS root:

```sh
projects/operation-jarvis/security/.venv-313/bin/python \
  projects/operation-jarvis/raspberry-pi/room_audio/camera_room_audio_service.py \
  configure --device indoor-camera --volume 30 --confirm
```

This creates a **trial.plist outside `~/Library/LaunchAgents`**, not an automatic
login installation. It refuses to overwrite existing configuration. It does not
stop/start anything. Camera credentials stay in security/.env. The existing
Pi-room token is copied privately from the root environment for the client.

1. Wait for the Pi room to be idle.
2. On the explicitly selected trusted `raspberrypi`, stop only
   `jarvis-room-audio.service`; leave it enabled and retain its files for rollback.
3. Start the trial on the Mac:

```sh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/Application Support/JARVIS/room-audio-camera/trial.plist"
```

Expected: `local wake word online` with threshold 0.75, two consecutive frames,
then a fresh `clientOnline:true` and `phase:idle` from
`http://127.0.0.1:8791/control/status`. That proves transport/heartbeat, not a
completed spoken conversation. Confirm that 8793 stays healthy and the Pi USB
service is stopped so there is only one client for 8791.

Acceptance sequence:

1. Say **Hey Jarvis**, wait for **Yes sir?**.
2. Start a separate request within five seconds.
3. Hear its complete JARVIS-voice answer from the camera.
4. During a long answer, say only **stop** and confirm prompt silence.
5. Test normal distance/background noise, and recovery after an approved network
   interruption, before retiring the USB hardware.

After physical acceptance, install the trial plist as
`~/Library/LaunchAgents/com.operation-jarvis.room-audio-camera.plist`, unload the
trial and bootstrap that permanent path. Disable (do not delete) the old Pi
listener's boot activation. **This promotion has now been completed.** The trial
file remains as a provisioning artifact, not a second running service.

## Rollback

First stop the camera trial on the Mac:

```sh
launchctl bootout "gui/$(id -u)/com.operation-jarvis.room-audio-camera"
```

To retain rollback across login, remove or move the camera plist out of
`~/Library/LaunchAgents/` after unloading it. Then, on the trusted Raspberry Pi,
re-provision the legacy Pi listener using the retained repository installer and
explicit trusted-host/server settings. **Simply enabling the service no longer
works: its Pi installation and backups have been deleted at owner request.**
Neither room server nor the Mac USB endpoint needs restarting. Verify the 8791
heartbeat returns to idle. Do not start both clients for the same server.

## Tests

```sh
.venv/bin/python -m unittest discover \
  -s projects/operation-jarvis/raspberry-pi/room_audio -p 'test_*.py' -q
```

At trial setup: 85 room tests passed. Live camera checks received PCM before,
during and after a 5.19-second speaker message; a separate silent worker test
verified reply EOF and termination while microphone PCM continued. Owner then
reported that the camera conversation test worked. Long-term wake distance,
background-noise performance and network-recovery reliability remain ongoing
acceptance items; do not claim USB-equivalent echo cancellation.
