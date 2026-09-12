# Operation JARVIS Room Audio

The Raspberry Pi listens through an Anker PowerConf and plays JARVIS's replies through the same speaker. The Mac handles transcription, Pi RPC, and speech synthesis.

**Microphone privacy:** capture runs continuously on the Pi. While idle, it drops speech that does not pass the local wake-word check. While JARVIS is generating or speaking, short speech clips go to the Mac without a wake word so it can recognize an exact `stop`. Keep logs, transcripts, and recordings private.

Code: `projects/operation-jarvis/raspberry-pi/room_audio/`.

Architecture:

```text
PowerConf mic/speaker on Raspberry Pi
  -> Pi client continuously captures audio
  -> Pi-side openWakeWord gate filters non-JARVIS speech locally
  -> transport-neutral RMS/VAD segments speech with preroll + silence end detection
  -> Mac room-audio server only receives locally wake-accepted utterances
  -> Apple SpeechTranscriber turn ASR (on-device)
  -> Apple DictationTranscriber busy-only stop ASR (on-device)
  -> Mac server trusts the Pi-side wake gate and responds to the transcription
  -> immediate processing acknowledgement while USB capture remains active
  -> Pi RPC JARVIS session
  -> Piper JARVIS TTS
  -> Pi client polls and plays final WAV through PowerConf
  -> while busy, a short bare "stop" utterance is transcribed and cancels playback/generation
```

## Machine endpoints

Endpoints recorded and checked on 2026-08-30 EDT; confirm your configuration before connecting:

| Role | Hostname | LAN IP | SSH user | Access notes |
|---|---|---|---|---|
| Pi listener / PowerConf endpoint | `raspberrypi` | `<private-lan-ip>` | `pi` | SSH key: `~/.ssh/jarvis_dashboard_host`; runs `jarvis-room-audio.service`. |
| Native JARVIS room-audio host | `mac-mini-64` | `<private-lan-ip>` | `dylanrapanan` | Local service host; JARVIS reaches the Pi through explicit `raspberrypi` SSH. |

The room-audio server URL in the commands below remains `http://<private-lan-ip>:8791` unless `JARVIS_ROOM_AUDIO_SERVER_URL` is changed.

## Current hardware note

The documented setup uses the PowerConf over USB at 48 kHz (`plughw:CARD=PowerConf,DEV=0`). USB supports capture and playback at the same time, so the microphone stays open through acknowledgement, generation, and the spoken response.

Idle turns need the local `hey_jarvis` wake word. While busy, short speech clips go to Apple DictationTranscriber. An exact normalized `stop` cancels Pi generation, stops local playback, and prevents old audio from playing afterward. Ordinary turns use Apple SpeechTranscriber. This setup uses Apple ASR only, with no fallback or installed oMLX Whisper model.

Bluetooth SCO/A2DP is still available as an installer fallback. It cannot support voice interruption because capture must stop for A2DP playback.

## Start the Mac-side server

Build and provision the native Apple helper once on macOS 26 before enabling `apple-speech` or `apple-dictation`:

```bash
projects/operation-jarvis/voice/apple_asr/build.sh
HELPER=projects/operation-jarvis/voice/apple_asr/.build/release/jarvis-apple-asr
"$HELPER" install-assets --engine speech --locale en-CA
"$HELPER" install-assets --engine dictation --locale en-CA
"$HELPER" health --engine speech --locale en-CA
"$HELPER" health --engine dictation --locale en-CA
```

Then, from `/path/to/JARVIS`:

```bash
.venv/bin/python projects/operation-jarvis/raspberry-pi/room_audio/room_audio_server.py --host 0.0.0.0 --port 8791
```

Health check from the Pi:

```bash
curl http://<private-lan-ip>:8791/health
```

The Watch terminal reuses Piper through `POST /synthesize`. This route accepts
length-limited final-response text only from loopback sources such as `127.0.0.1`,
not LAN clients. It runs neither ASR nor Pi RPC and returns no-store `audio/wav`
without the room speaker's Bluetooth leading-silence padding. It normalizes
Markdown table rows for speech and splits long prose at word boundaries without
losing text.

Optional environment variables:

- `JARVIS_ROOM_AUDIO_HOST` / `JARVIS_ROOM_AUDIO_PORT`
- `JARVIS_ROOM_AUDIO_TOKEN`: if set, clients must send `x-jarvis-room-token`
- `JARVIS_ROOM_AUDIO_PI_MODEL`: defaults to `JARVIS_PI_MODEL`
- `JARVIS_ROOM_AUDIO_PI_THINKING`: defaults to `JARVIS_PI_THINKING`; current room-audio setting is `high`.
- `JARVIS_ROOM_AUDIO_ASR_BACKEND`: room-turn ASR override; current deployment uses `apple-speech`.
- `JARVIS_ROOM_AUDIO_ASR_FALLBACK_BACKEND`: optional fallback override; blank in the current Apple-only deployment.
- `JARVIS_ROOM_AUDIO_INTERRUPT_ASR_BACKEND` / `JARVIS_ROOM_AUDIO_INTERRUPT_ASR_FALLBACK_BACKEND`: busy-only control-path overrides; the current deployment uses `apple-dictation` with no fallback.
- `JARVIS_VOICE_APPLE_ASR_HELPER`, `JARVIS_VOICE_APPLE_ASR_LOCALE`, `JARVIS_VOICE_APPLE_ASR_TIMEOUT_SECONDS`, `JARVIS_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS`: native helper path, locale, timeout, and up to 100 short hints. See [`../../voice/README.md`](../../voice/README.md).
- `JARVIS_ROOM_AUDIO_WAKE_WORD`: legacy transcript-wake setting; room audio no longer uses it to reject turns after Pi-side openWakeWord has accepted them.
- `JARVIS_ROOM_AUDIO_TTS_LEADING_SILENCE_MS`: code default `450`; the current room-speaker deployment retains `1000` ms of leading silence, originally added for A2DP first-syllable protection. Change it only after validating acknowledgement and final-answer playback on the active USB path.
- `JARVIS_ROOM_AUDIO_PROCESSING_ACK_ENABLED`: defaults to `JARVIS_VOICE_PROCESSING_ACK_ENABLED`; when enabled, accepted turns can immediately play the acknowledgement.
- `JARVIS_ROOM_AUDIO_PROCESSING_ACK_TEXT`: defaults to `JARVIS_VOICE_PROCESSING_ACK_TEXT` / `Generating your response, sir.`
- `JARVIS_ROOM_AUDIO_ASYNC_JOB_TTL_SECONDS`: default `900`; retention window for async final-answer jobs.
- `JARVIS_ROOM_AUDIO_INTERRUPT_WHILE_BUSY`: enables USB full-duplex bare-`stop` interruption while JARVIS is generating or speaking; the installed USB service enables it.
- `JARVIS_ROOM_AUDIO_INTERRUPT_VAD_SILENCE_SECONDS`: default `0.45`; busy-mode silence before a possible stop command is finalized.
- `JARVIS_ROOM_AUDIO_INTERRUPT_VAD_MAX_UTTERANCE_SECONDS`: default `2.0`; maximum busy-mode clip sent to the configured control ASR.
- `JARVIS_ROOM_AUDIO_BT_PROFILE_SETTLE_SECONDS` / `JARVIS_ROOM_AUDIO_BT_PLAYBACK_DRAIN_SECONDS`: Bluetooth fallback timings; both are zero in the current USB service.
- `JARVIS_ROOM_AUDIO_VAD_RESTORE_CAPTURE_WHILE_WAITING`: legacy Bluetooth fallback behavior; disabled in the USB full-duplex service.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ENABLED`: Pi-client local wake-word gate; when enabled, ordinary speech is dropped on the Pi before the Mac room-audio server sees it.
- `JARVIS_ROOM_AUDIO_OPENWAKEWORD_MODEL`: defaults to `hey_jarvis`; can also be a local `.tflite`/`.onnx` model path, or comma-separated models.
- `JARVIS_ROOM_AUDIO_OPENWAKEWORD_NCPU`: defaults to `2`; CPU threads for openWakeWord preprocessing. On the Pi 3 this gives better real-time headroom than the upstream default of `1`.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_THRESHOLD`: defaults to `0.75` in the installed Pi service; raise it to reduce false wakes, lower it to reduce missed wakes.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ARM_SECONDS`: defaults to `8.0`; after a wake hit, the current/next VAD utterance may pass through.
- `JARVIS_ROOM_AUDIO_TRUST_LOCAL_WAKE_WORD`: retained for older deployments; the current Mac room-audio server always trusts Pi-side openWakeWord and does not perform a transcript wake-word re-check.
- `JARVIS_ROOM_AUDIO_VAD_SILENCE_SECONDS`: defaults to `1.0`; room audio waits this long after voice ends before finalizing an utterance.
- `JARVIS_ROOM_AUDIO_VAD_MIN_UTTERANCE_SECONDS`: defaults to `0.5`; shorter clips are dropped before ASR.
- `JARVIS_ROOM_AUDIO_GREETING_ENABLED`: defaults to `1`; enables `/greeting`; the current Pi service plays it on startup only, not on reconnect.
- `JARVIS_ROOM_AUDIO_GREETING_TEXT`: optional fixed greeting override. If unset, the room endpoint uses its contextual local greeting style.
- `JARVIS_ROOM_AUDIO_GREETING_TIMEOUT_SECONDS`: Pi-client timeout for optional greeting audio before listening anyway; default `30`.
- `JARVIS_ROOM_AUDIO_GREETING_STATE_PATH`: optional reconnect history path; defaults to `projects/operation-jarvis/data/room_audio_greeting_state.json`.

## Run the Pi listener

Current USB/VAD listener command on the Raspberry Pi:

```bash
/home/pi/jarvis-room-audio/.venv/bin/python \
  /home/pi/jarvis-room-audio-client.py \
  --server-url http://<private-lan-ip>:8791 \
  --device 'plughw:CARD=PowerConf,DEV=0' \
  --playback-device 'plughw:CARD=PowerConf,DEV=0' \
  --rate 48000 \
  --vad-loop \
  --vad-rms-threshold 300 \
  --vad-silence-seconds 1.0 \
  --vad-min-utterance-seconds 0.5 \
  --vad-max-utterance-seconds 30 \
  --vad-preroll-ms 500 \
  --vad-min-voiced-ms 200 \
  --capture-read-timeout-seconds 5 \
  --no-vad-release-capture-during-turn \
  --no-vad-restore-capture-while-waiting \
  --interrupt-while-busy \
  --interrupt-vad-silence-seconds 0.45 \
  --interrupt-vad-max-utterance-seconds 2.0 \
  --local-wake-word \
  --openwakeword-model hey_jarvis \
  --openwakeword-ncpu 2 \
  --local-wake-word-threshold 0.75 \
  --trust-local-wake-word \
  --bt-profile-settle-seconds 0 \
  --bt-playback-drain-seconds 0 \
  --startup-greeting \
  --no-greeting-on-reconnect \
  --async-ack \
  --poll-interval 0.25 \
  --result-timeout 300 \
  --interval 1.0
```

Say a wake-word phrase for a normal idle turn:

```text
Jarvis, say the room speaker is online.
```

While the acknowledgement, generation, or final answer is active, say only:

```text
stop
```

Bare `stop` is ignored while idle. During a turn, only the exact normalized word `stop` is accepted; longer phrases such as `don't stop` are rejected. This policy lives in `projects/operation-jarvis/voice/voice_commands.py` and is shared across transports. It allows cancellation during playback, but idle interrupt requests invoke neither ASR nor cancellation.

The local wake-word dependency is required for the current listener. The service installer creates `/home/pi/jarvis-room-audio/.venv` and installs `openwakeword` there by default. If rebuilding manually, provide both required endpoints:

```bash
PI_HOST=raspberrypi \
SERVER_URL=http://<private-lan-ip>:8791 \
projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh
```

The log should say `local wake word online`.

For fixed-window diagnostics without requiring the wake word:

```bash
/home/pi/jarvis-room-audio/.venv/bin/python \
  /home/pi/jarvis-room-audio-client.py \
  --server-url http://<private-lan-ip>:8791 \
  --duration 5 --beep --no-wake-word
```

## Persistent Pi service

Install or refresh the boot-time listener from this repo. The script fails closed unless both `PI_HOST` and `SERVER_URL` are provided:

```bash
PI_HOST=raspberrypi \
SERVER_URL=http://<private-lan-ip>:8791 \
projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh
```

The service is named `jarvis-room-audio.service`. In the default `AUDIO_TRANSPORT=usb` mode it starts after `network-online.target`, opens the PowerConf for full-duplex 48 kHz capture/playback, enables busy-only interruption, plays a JARVIS greeting after service startup, and restarts automatically if the client exits. Set `AUDIO_TRANSPORT=bluetooth` plus `POWERCONF_MAC` only for the legacy non-interruptible SCO/A2DP fallback.

Useful Pi checks:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> \
  'systemctl status jarvis-room-audio --no-pager; tail -n 80 /home/pi/jarvis-room-audio/logs/client.log'
```

## Troubleshooting decision tree

1. **No response at all:** check `jarvis-room-audio.service` status and tail the client log.
2. **Service running but no wake:** confirm the log says `local wake word online`; temporarily run fixed-window diagnostics with `--no-wake-word`.
3. **Wake detected but no answer:** inspect the Mac server `/health` `asr` object, confirm the configured Apple helper and locale asset are available, and check Pi RPC/model configuration.
4. **`stop` is not heard while busy:** confirm the service uses USB, `--interrupt-while-busy`, and `--no-vad-release-capture-during-turn`; then inspect interrupt-candidate/control-ASR logs.
5. **False stop:** confirm the control ASR returned exactly `stop`; check PowerConf echo cancellation and raise the VAD threshold if speaker leakage is opening clips.
6. **False wakes:** raise `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_THRESHOLD` and enable score logging temporarily.
7. **Missed wakes:** lower the local wake threshold slightly and improve microphone placement.

## Notes

VAD reads continuous PCM audio, uses an RMS threshold to detect speech, keeps preroll, and waits for silence to end an utterance. Minimum voiced duration and maximum clip length limit what is sent.

With `--local-wake-word`, the same stream is resampled to 16 kHz and passed to openWakeWord in 80 ms chunks. Idle utterances without a `hey_jarvis` detection are dropped locally. During a busy USB turn, short clips bypass only the wake check for exact `stop` recognition on the Mac. For ordinary accepted turns, the Mac transcribes and responds without checking wake-word aliases again.

See the [Pi overview](../README.md) and [audio hardware notes](../docs/audio-hardware.md) for the hardware setup.

The Build 148 notes below are retained from that candidate review. Their token, session-count, and deployment statements have not been rechecked against the live setup.

## Native Home status and exact-turn Stop (Build 148 candidate)

The full-duplex `--interrupt-while-busy` listener sends one bounded content-free heartbeat per second to `/client-state`: a process-instance ID, monotonic sequence, opaque turn ID, and phase only. Processing includes upload/ASR/generation; Talking is reported around actual local acknowledgement/final/greeting WAV playback. Capture failure without an active turn reports Unavailable. No transcript, response, audio, model, device token, or credential is included in telemetry.

This **requires a nonempty matching `JARVIS_ROOM_AUDIO_TOKEN` on both Mac and Pi**. The new telemetry endpoint fails closed without it (older optional-token voice behavior is unchanged). The current local configuration was checked only for presence, not logged; the token is not configured yet. At approved deployment, provision a cryptographically random shared token in the existing owner-only environment files on both machines, without command-line arguments, Git, logs or artifacts. Coordinate activation only after both sides have matching configuration.

`GET /control/status` and `POST /control/stop` are loopback-only; jarvisd exposes authenticated `/api/v1/room-audio` and `/api/v1/room-audio/stop`. Six-second freshness is required for controls. Stop must name the current exact turn; no "stop latest" behavior. The server aborts only the matching Pi RPC turn and retains its cancellation for the player's next heartbeat, which stops local playback too. Cancellation arriving during upload/ASR is checked before generation. The single current cancellation survives a long in-flight call; older records are bounded to 256 and ten minutes after leaving that turn. Client instances and sequence checks reject replayed telemetry. Stopping remains visible until the actual worker/player settles.

Rollback/deployment: wait for room audio to be idle; obtain owner approval before coordinated Mac jarvisd/room-audio and Raspberry Pi listener updates/restarts. Do not interrupt the six mobile Pi sessions or automatically `/reload` them. Before deployment, the new app safely shows Unavailable against an old server/client. Legacy non-full-duplex diagnostics do not fabricate player telemetry.

Offline verification (no live playback, requests or service mutations):

```sh
cd projects/operation-jarvis/raspberry-pi/room_audio
/path/to/JARVIS/.venv/bin/python -m unittest test_room_audio_control test_room_audio_interrupt
```
