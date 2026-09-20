# Operation JARVIS Room Audio

**Current primary room endpoint:** the C230 camera now supplies microphone and
speaker audio directly to the Mac; the Raspberry Pi room-audio installation,
backups and dedicated PowerConf pairing have been removed at owner request. See [camera deployment and rollback](CAMERA.md). The Mac handles local
wake detection, transcription, Pi RPC (agent software), and speech synthesis.
The independent Mac USB PowerConf endpoint is unchanged.

The Raspberry Pi/Anker PowerConf instructions below are preserved as the legacy
setup/reinstallation reference, not an existing Pi installation or the active primary room transport.

**Microphone privacy:** capture runs continuously on the active endpoint (now the
camera-to-Mac path; historically the Pi). While idle, it drops speech that does not pass the local wake-word check. While JARVIS is generating or speaking, short speech clips go to the Mac without a wake word so it can recognize an exact `stop`. Keep logs, transcripts, and recordings private.

Code: `projects/operation-jarvis/raspberry-pi/room_audio/`.

**Additional Mac USB speaker:** [macOS deployment and rollback](MACOS.md).
The shared client now supports `--audio-backend coreaudio` with an explicitly
selected PowerConf. It uses an isolated loopback server on port `8793`; the Pi
continues using ALSA and its existing server on `8791`.

Architecture:

```text
PowerConf mic/speaker on Raspberry Pi
  -> Pi client continuously captures audio
  -> Pi-side openWakeWord gate filters non-JARVIS speech locally
  -> transport-neutral RMS/VAD segments speech with preroll + silence end detection
  -> Mac room-audio server only receives locally wake-accepted utterances
  -> Apple DictationTranscriber verifies an exact leading "Hey Jarvis" (on-device)
  -> silent rejection if missing or verification fails
  -> cached “Yes sir?” (no command execution from the wake clip)
  -> five-second window to start one request, no repeated wake phrase
  -> Apple SpeechTranscriber command ASR (on-device)
  -> “Generating your response, sir.” while USB capture remains active
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

Idle turns need the local `hey_jarvis` wake word. While busy, short speech clips go to Apple DictationTranscriber. An exact normalized `stop` cancels Pi generation, stops local playback, and prevents old audio from playing afterward. Conversations are strictly two-part: an independent Apple DictationTranscriber wake check triggers “Yes sir?”, then one separately spoken request uses Apple SpeechTranscriber. This setup uses Apple ASR only, with no fallback or installed oMLX Whisper model.

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
- `JARVIS_ROOM_AUDIO_WAKE_WORD`: legacy alias setting; the independent verifier ignores it and requires exact leading words `hey jarvis` (case/punctuation insensitive).
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
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_CONSECUTIVE_FRAMES`: defaults to `2`; the same model must stay above threshold for two consecutive 80 ms predictions.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_LOG_SCORES`: enable temporary numeric score logging; `--local-wake-word-log-seconds` limits it to 600 seconds after detector startup by default. No audio recordings are created by score logging.
- `JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ARM_SECONDS`: defaults to `3.0`; after a wake hit, the current/next VAD utterance may pass through. Authorization is consumed after one accepted ordinary turn.
- `JARVIS_ROOM_AUDIO_TRUST_LOCAL_WAKE_WORD`: retained for older deployments; it cannot bypass the Mac Dictation verifier, even if the client sends `requireWakeWord=false`.
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

Start a two-part conversation (USB full-duplex listener):

```text
You:    Hey Jarvis.
JARVIS: Yes sir?
You:    Say the room speaker is online.
JARVIS: Generating your response, sir.
JARVIS: [answer]
```

Start your request within five seconds after “Yes sir?” finishes. One-shot wake-plus-command clips are never executed; any extra words in that first clip are ignored.

While the acknowledgement, generation, or final answer is active, say only:

```text
stop
```

After “Yes sir?”, only the exact whole utterance `never mind` or `nevermind` silently cancels the follow-up. `cancel` and `stop` are not follow-up cancellation keywords. Bare `stop` outside an authorized follow-up is ignored while idle. During a turn, only the exact normalized word `stop` is accepted; longer phrases such as `don't stop` are rejected. This policy lives in `projects/operation-jarvis/voice/voice_commands.py` and is shared across transports. It allows cancellation during playback, but idle interrupt requests invoke neither ASR nor cancellation.

The local wake-word dependency is required for the current listener. The service installer creates `/home/pi/jarvis-room-audio/.venv` and installs `openwakeword` there by default. If rebuilding manually, provide both required endpoints:

```bash
PI_HOST=raspberrypi \
SERVER_URL=http://<private-lan-ip>:8791 \
projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh
```

The log should say `local wake word online`.

For legacy fixed-window capture/upload diagnostics only (these cannot complete the new two-part conversation):

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

With `--local-wake-word`, the same stream is resampled to 16 kHz and passed to openWakeWord in 80 ms chunks. Idle utterances without a `hey_jarvis` detection are dropped locally. A wake requires two consecutive predictions at or above 0.75 and allows one candidate wake clip within a 3-second start window. It does not authorize command execution. Busy-mode audio is excluded from wake inference; detector history and pending authorization are cleared across busy transitions so playback cannot arm a later turn. During a busy USB turn, short clips bypass only the wake check for exact `stop` recognition on the Mac. The Mac independently verifies an exact leading “Hey Jarvis” using Apple DictationTranscriber with no contextual hints or fallback. Missing phrases and verifier errors return a silent rejection. Legacy aliases such as “Travis” are not accepted. A verified wake returns only “Yes sir?” and a single-use authorization; only the subsequent request can reach command ASR, the processing acknowledgement, and Pi RPC.

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


## Two-part conversation and Mac wake verification

1. Say **“Hey Jarvis.”** The Pi wake gate and strict Mac Dictation verifier must
   both accept it. The initial clip is never sent to the LLM, even if it contains
   a command after the wake phrase.
2. JARVIS plays cached **“Yes sir?”** with 450 ms of leading silence to protect the first syllable during speaker startup (`JARVIS_ROOM_AUDIO_WAKE_ACK_LEADING_SILENCE_MS`).
3. Start a separately spoken request within **five seconds after playback ends**.
   The normal 30-second utterance limit applies; you do not need to finish within
   five seconds. Wait for the prompt before speaking—talk-over is not supported.
4. Command ASR completes, then **“Generating your response, sir.”** plays, followed
   by the answer. No speech within the window returns silently to idle.

The Mac issues a random, memory-only `wakeTicket`, bound to the client process ID
and source address. `/wake-followup` transitions it from `prompt` to `ready`
(after playback), then `claim` (at speech onset). Only a claimed ticket can
submit one command to `/turn`. Prompt tickets expire in 30 seconds, the listening
window is five seconds, and claimed tickets expire after 40 seconds to allow
capture/upload. Reuse, wrong clients, expired tickets, and unclaimed tickets are
rejected. New wakes revoke older tickets for that client. Cancellation, client
capture recovery, and restarts clear/revoke authorization (unused server tickets
also expire). These are on the same authenticated LAN transport as `/turn`, not
a substitute for TLS or speaker authentication.

The Pi never blocks PCM capture on the claim HTTP call. Busy/playback audio is
excluded from wake inference, and a partial playback clip/preroll is discarded
when busy mode ends so “Yes sir?” cannot become the request. A noise-triggered
speech start can consume the one-request window; say “Hey Jarvis” again if so.

`GET /health` reports `conversationMode: "two-part"`, `wakeAckText`,
`followupStartSeconds`, `transcriptWakeCheckEnabled: true`, and `wakeVerification`.
Wake success has `status: "awaiting_command"`, `pending: false`, and only the
“Yes sir?” audio. Rejections have `accepted: false`, `pending: false`, and no audio.
Client logs redact tickets; rejected transcripts are not logged. Uploaded WAVs
are deleted by the HTTP handler. Startup greetings, Watch speech synthesis, and
busy-only “stop” interruption remain separate. Saying exactly “never mind” or “nevermind” as the follow-up
request cancels silently, before the processing acknowledgement. Matching ignores
case and punctuation; longer phrases are ordinary requests. “Cancel” and “stop”
are not cancellation keywords in this listening phase. The separate busy-only
“stop” interrupt remains unchanged.

This flow requires the updated USB full-duplex Pi client. Legacy fixed-window
and Bluetooth clients cannot execute one-shot requests and receive
`two_part_client_required` after a verified wake.

Verify the helper if all wake clips are rejected:

```bash
projects/operation-jarvis/voice/apple_asr/.build/release/jarvis-apple-asr health --engine dictation --locale en-CA
```
