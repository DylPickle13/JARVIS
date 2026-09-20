# Room audio

Mac-hosted room conversations: microphone capture, wake detection, two-part turns,
room ownership, playback, and exact busy-only `stop`. Room audio does not depend
on Raspberry Pi hardware. Pi RPC means the AI agent software running on the Mac.

## Endpoint map

These are documented deployment roles, not a fresh live health check.

| Endpoint | Transport | Server | Guide |
|---|---|---|---|
| Mac USB PowerConf | Explicit Core Audio microphone/speaker | Loopback 8793 | [Mac endpoint](MACOS.md) |
| C230 camera | Camera microphone/speaker through local go2rtc | Loopback 8791 | [Camera endpoint](CAMERA.md) |
| Raspberry Pi | Retired; installation, repository scripts, and setup guides removed | None active | — |

The Raspberry Pi is currently offline per the owner. Its absence is not a room
conversation failure. Family-room Cast speaker commands are a separate transport;
this directory owns the documented conversational microphone/speaker endpoints.

## Components

- `room_audio_server.py`: Apple ASR, wake verification, follow-up authorization,
  agent responses, TTS, and room controls. Shared ASR/TTS lives in [`../voice/`](../voice/).
- `pi_room_audio_client.py`: shared client with Core Audio, camera, and legacy ALSA
  backends. The historical filename is retained for compatibility, not hardware ownership.
- `room_audio_coreaudio.py` / `room_audio_camera.py`: device-specific transports.
- `shared_room_wake.py`: shared inference with separate per-room wake state and
  ownership arbitration; see [shared wake](SHARED-WAKE.md).
- `shared_room_session.py` / `room_session10_service.py`: shared conversation and
  retained Session 10 supervision. Keep existing history and runtime identity.
- `macos_room_audio_service.py` / `camera_room_audio_service.py`: endpoint provisioning/supervision.
- `scripts/install-macos-room-audio.sh`: Mac provisioning; does not start services.

Say “Hey Jarvis”, wait for “Yes sir?”, then start a separate request within five
seconds. During a response, exact `stop` interrupts. Endpoint capture is continuous;
idle ordinary speech is discarded by wake gating. Keep credentials, transcripts,
and endpoint state private; do not add them to the repository.

## Checks

Offline regression suite from the repository root:

```sh
.venv/bin/python -m unittest discover -s projects/operation-jarvis/room-audio -p 'test_*.py'
```

For endpoint health, deployment, and rollback, use the endpoint guides above.
Do not reinstall the retired Pi listener as a remedy for a Mac endpoint failure.
Retired Pi scripts and documentation have been deleted; tracked history remains in Git.

## Completed source-path cutover

On 2026-09-20, the six installed LaunchAgents (Mac client/server, camera, main
room server, shared wake, and Session 10 supervisor) were updated to this canonical
source directory and reloaded during an owner-approved idle maintenance window.
Both endpoints recovered online/idle; Session 10's owner descriptor was unchanged.
Ports, credentials, state directories, service labels, and conversation history
were preserved. Human spoken wake/request/reply verification remains required.

The compatibility symlink and empty `raspberry-pi/` directory have been removed.
Use the canonical Mac installer path. Private pre-cutover agent definitions are
retained outside Git at
`~/Library/Application Support/JARVIS/room-audio-path-migration/20260920-122103/`.
To roll back paths, first recreate `raspberry-pi/room_audio -> ../room-audio`, then
restore/reload those definitions in an approved idle window. Do not restore the
saved owner descriptor over a live conversation; it is verification evidence only.

Keep shared configuration opt-ins when updating agents; do not blindly rerun
endpoint installers. A future cleanup may rename the historical client module
and organize transports/tests into packages; this migration deliberately does not.
