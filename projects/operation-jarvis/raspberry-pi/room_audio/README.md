# Operation JARVIS Room Audio

Raspberry Pi / Anker PowerConf room-audio endpoint for Operation JARVIS.

**Privacy/safety note:** this is an always-listening-adjacent room endpoint. Idle speech is filtered by the Pi-side wake word before reaching the Mac. While JARVIS is actively generating or speaking, short VAD clips bypass the wake gate so local Whisper can recognize an exact `stop`; logs, transcripts, and audio artifacts should be treated as private local data.

Canonical path: `projects/operation-jarvis/raspberry-pi/room_audio/`.

Architecture:

```text
PowerConf mic/speaker on Raspberry Pi
  -> Pi client continuously captures audio
  -> Pi-side openWakeWord gate filters non-JARVIS speech locally
  -> Discord-style RMS/VAD segments speech with preroll + silence end detection
  -> Mac room-audio server only receives locally wake-accepted utterances
  -> oMLX Whisper ASR
  -> Mac server trusts the Pi-side wake gate and responds to the transcription
  -> immediate processing acknowledgement while USB capture remains active
  -> Pi RPC JARVIS session
  -> Piper JARVIS TTS
  -> Pi client polls and plays final WAV through PowerConf
  -> while busy, a short bare "stop" utterance is transcribed and cancels playback/generation
```

## Machine endpoints

Verified SSH endpoints for this room-audio stack on 2026-06-11 EDT:

| Role | Hostname | LAN IP | SSH user | Access notes |
|---|---|---|---|---|
| Pi listener / PowerConf endpoint | `raspberrypi` | `<private-lan-ip>` | `pi` | SSH key: `~/.ssh/jarvis_dashboard_host`; runs `jarvis-room-audio.service`. |
| Native JARVIS room-audio host | `mac-mini-64` | `<private-lan-ip>` | `dylanrapanan` | Local service host; JARVIS reaches the Pi through explicit `raspberrypi` SSH. |

The room-audio server URL in the commands below remains `http://<private-lan-ip>:8791` unless `JARVIS_ROOM_AUDIO_SERVER_URL` is changed.

## Current hardware note

The active room endpoint uses the PowerConf as a 48 kHz USB full-duplex capture/playback device (`plughw:CARD=PowerConf,DEV=0`). USB allows the listener to keep microphone capture active during the processing acknowledgement, generation, and final playback. The client therefore supports busy-only voice barge-in: normal idle turns still require the local `hey_jarvis` wake gate, but while JARVIS is busy a short utterance is sent to the Mac-side Whisper ASR and an exact `stop` transcript cancels Pi generation, terminates local playback, and suppresses stale audio. Bluetooth SCO/A2DP remains an installer fallback but does not support barge-in because capture must be released for A2DP playback.

## Start the Mac-side server

From `/path/to/JARVIS`:

```bash
.venv/bin/python projects/operation-jarvis/raspberry-pi/room_audio/room_audio_server.py --host 0.0.0.0 --port 8791
```

Health check from the Pi:

```bash
curl http://<private-lan-ip>:8791/health
```

Optional environment variables:

- `JARVIS_ROOM_AUDIO_HOST` / `JARVIS_ROOM_AUDIO_PORT`
- `JARVIS_ROOM_AUDIO_TOKEN` — if set, clients must send `x-jarvis-room-token`
- `JARVIS_ROOM_AUDIO_PI_MODEL` — defaults to `DISCORD_VOICE_PI_MODEL`, then `DISCORD_PI_MODEL`
- `JARVIS_ROOM_AUDIO_PI_THINKING` — defaults to `DISCORD_PI_THINKING`; current JARVIS voice/room-audio setting is `xhigh`.
- `JARVIS_ROOM_AUDIO_WAKE_WORD` — legacy transcript-wake setting; room audio no longer uses it to reject turns after Pi-side openWakeWord has accepted them.
- `JARVIS_ROOM_AUDIO_TTS_LEADING_SILENCE_MS` — code default `450`; current `.env` uses `1000` for Bluetooth/A2DP first-syllable protection. If the acknowledgement ever clips again, raise this to about `1300`–`1500`.
- `JARVIS_ROOM_AUDIO_PROCESSING_ACK_ENABLED` — defaults to `DISCORD_VOICE_PROCESSING_ACK_ENABLED`; when enabled, accepted turns can immediately play the acknowledgement.
- `JARVIS_ROOM_AUDIO_PROCESSING_ACK_TEXT` — defaults to `DISCORD_VOICE_PROCESSING_ACK_TEXT` / `Generating your response, sir.`
- `JARVIS_ROOM_AUDIO_ASYNC_JOB_TTL_SECONDS` — default `900`; retention window for async final-answer jobs.
- `JARVIS_ROOM_AUDIO_INTERRUPT_WHILE_BUSY` — enables USB full-duplex bare-`stop` interruption while JARVIS is generating or speaking; the installed USB service enables it.
- `JARVIS_ROOM_AUDIO_INTERRUPT_VAD_SILENCE_SECONDS` — default `0.45`; busy-mode silence before a possible stop command is finalized.
- `JARVIS_ROOM_AUDIO_INTERRUPT_VAD_MAX_UTTERANCE_SECONDS` — default `2.0`; maximum busy-mode clip sent to Whisper.
- `JARVIS_ROOM_AUDIO_BT_PROFILE_SETTLE_SECONDS` / `JARVIS_ROOM_AUDIO_BT_PLAYBACK_DRAIN_SECONDS` — Bluetooth fallback timings; both are zero in the current USB service.
- `JARVIS_ROOM_AUDIO_VAD_RESTORE_CAPTURE_WHILE_WAITING` — legacy Bluetooth fallback behavior; disabled in the USB full-duplex service.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ENABLED` — Pi-client local wake-word gate; when enabled, ordinary speech is dropped on the Pi before the Mac/oMLX server sees it.
- `JARVIS_ROOM_AUDIO_OPENWAKEWORD_MODEL` — defaults to `hey_jarvis`; can also be a local `.tflite`/`.onnx` model path, or comma-separated models.
- `JARVIS_ROOM_AUDIO_OPENWAKEWORD_NCPU` — defaults to `2`; CPU threads for openWakeWord preprocessing. On the Pi 3 this gives better real-time headroom than the upstream default of `1`.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_THRESHOLD` — defaults to `0.75` in the installed Pi service; raise it to reduce false wakes, lower it to reduce missed wakes.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ARM_SECONDS` — defaults to `8.0`; after a wake hit, the current/next VAD utterance may pass through.
- `JARVIS_ROOM_AUDIO_TRUST_LOCAL_WAKE_WORD` — retained for older deployments; the current Mac room-audio server always trusts Pi-side openWakeWord and does not perform a transcript wake-word re-check.
- `JARVIS_ROOM_AUDIO_VAD_SILENCE_SECONDS` — defaults to `1.0`, matching Discord voice; room-audio waits this long after voice ends before finalizing an utterance.
- `JARVIS_ROOM_AUDIO_VAD_MIN_UTTERANCE_SECONDS` — defaults to `0.5`, matching Discord voice; shorter clips are dropped before ASR.
- `JARVIS_ROOM_AUDIO_GREETING_ENABLED` — defaults to `1`; enables `/greeting`; the current Pi service plays it on startup only, not on reconnect.
- `JARVIS_ROOM_AUDIO_GREETING_TEXT` — optional fixed greeting override. If unset, the room endpoint uses the same contextual style as Discord voice greetings.
- `JARVIS_ROOM_AUDIO_GREETING_TIMEOUT_SECONDS` — Pi-client timeout for optional greeting audio before listening anyway; default `30`.
- `JARVIS_ROOM_AUDIO_GREETING_STATE_PATH` — optional reconnect history path; defaults to `projects/operation-jarvis/data/room_audio_greeting_state.json`.

## Run the Pi listener

Current USB/VAD listener command on the Raspberry Pi:

```bash
python3 /home/pi/jarvis-room-audio-client.py \
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
  --bt-profile-settle-seconds 0 \
  --bt-playback-drain-seconds 0 \
  --startup-greeting \
  --no-greeting-on-reconnect \
  --async-ack
```

Say a wake-word phrase for a normal idle turn:

```text
Jarvis, say the room speaker is online.
```

While the acknowledgement, generation, or final answer is active, say only:

```text
stop
```

Bare `stop` is ignored while JARVIS is idle. The first release intentionally accepts only the exact normalized word `stop`; longer phrases such as `don't stop` are rejected.

The local wake-word dependency is required for the current listener. The service installer creates `/home/pi/jarvis-room-audio/.venv` and installs `openwakeword` there by default. If rebuilding manually, rerun:

```bash
projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh
```

The log should say `local wake word online`.

For fixed-window diagnostics without requiring the wake word:

```bash
python3 /home/pi/jarvis-room-audio-client.py --duration 5 --beep --no-wake-word
```

## Persistent Pi service

Install or refresh the boot-time listener from this repo:

```bash
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
3. **Wake detected but no answer:** check Mac server `/health`, oMLX ASR availability, and Pi RPC/model configuration.
4. **`stop` is not heard while busy:** confirm the service uses USB, `--interrupt-while-busy`, and `--no-vad-release-capture-during-turn`; then inspect interrupt-candidate/ASR logs.
5. **False stop:** confirm Whisper returned exactly `stop`; check PowerConf echo cancellation and raise the VAD threshold if speaker leakage is opening clips.
6. **False wakes:** raise `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_THRESHOLD` and enable score logging temporarily.
7. **Missed wakes:** lower the local wake threshold slightly and improve microphone placement.

## Notes

The VAD mode mirrors the Discord voice-call approach: continuous PCM input, RMS voice gate, preroll, minimum voiced duration, silence-based utterance finalization, and max-duration cutoff. With `--local-wake-word`, the same PCM stream is resampled to 16 kHz and fed to openWakeWord in 80 ms chunks; idle utterances that never trigger the local `hey_jarvis` model are discarded without a network request. While a USB turn is busy, short VAD clips bypass only that wake gate and go to the local Mac Whisper endpoint for exact `stop` matching. Once a normal locally wake-accepted utterance reaches the Mac, the server responds to whatever Whisper transcribes rather than checking for wake-word aliases again. Raspberry Pi hardware notes live in [`../README.md`](../README.md), with detailed hardware notes in [`../docs/audio-hardware.md`](../docs/audio-hardware.md).
