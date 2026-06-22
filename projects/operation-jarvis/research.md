# Operation JARVIS Research Notes

Consolidated: 2026-05-24

This file consolidates the previous Operation JARVIS research notes from:

- `research.md`
- `dashboard/docs/hosting-research.md`
- `voice/wake-word-gating-research-2026-05-20.md`

## Current scope

Operation JARVIS currently covers:

- Discord text/live voice command surface and audit trail.
- Dashboard phone camera vision and bounded short-video capture.
- Google Cast room speaker / TV output.
- LAN dashboard HUD, telemetry, artifacts, and local command bridge.
- Local TP-Link Kasa smart-plug control.
- Raspberry Pi room-audio endpoint.

## Current architecture

```text
Discord = command surface, conversation, live voice, audit trail
Dashboard phone camera = primary vision and short-video capture source
Google Cast = room speaker/TV output
Dashboard = fullscreen HUD, telemetry, camera client, artifacts, and local command bridge
Smart plugs = local Kasa HS103 power control
Raspberry Pi room audio = local room microphone/speaker bridge
```

## Dashboard phone camera and vision

The dashboard phone camera replaced the older standalone phone-camera adapter. Capture now happens through the dashboard PWA:

1. The phone opens the dashboard fullscreen PWA.
2. The browser grants camera permission and keeps the live preview active.
3. The dashboard server sends snapshot/video commands over `/ws`.
4. The browser captures from `getUserMedia()` and uploads media back to the server.
5. Captures are stored in `projects/operation-jarvis/media/dashboard-camera/` and exposed as artifacts.
6. `jarvis.py` uses those captures for `look`, `video`, `video-until`, and `analyze-view`.

### Primary local commands

```bash
./jarvis-cli --json status --no-cast
./jarvis-cli --json look
./jarvis-cli --json video --duration 5
./jarvis-cli --json analyze-view 'Describe what is visible.'
```

### Dashboard camera endpoints

```bash
curl http://127.0.0.1:8787/api/jarvis/camera/status
curl -X POST http://127.0.0.1:8787/api/jarvis/camera/snapshot -H 'content-type: application/json' -d '{"quality":0.86}'
curl -X POST http://127.0.0.1:8787/api/jarvis/camera/record -H 'content-type: application/json' -d '{"durationSeconds":5}'
```

Endpoints are localhost/token protected for commands. The browser upload path uses one-time per-command upload tokens.

### Visual analysis

`jarvis.py` analyzes dashboard-camera snapshots through an OpenAI-compatible oMLX `/v1/chat/completions` endpoint using a data-URL image payload. Relevant environment variables:

- `JARVIS_DASHBOARD_CAMERA_VISION_BASE_URL`
- `JARVIS_DASHBOARD_CAMERA_VISION_MODEL`
- `JARVIS_DASHBOARD_CAMERA_VISION_FALLBACK_MODEL`
- `JARVIS_DASHBOARD_CAMERA_VISION_SYSTEM_PROMPT`
- `JARVIS_DASHBOARD_CAMERA_VISION_MAX_TOKENS`
- `JARVIS_DASHBOARD_CAMERA_VISION_TIMEOUT`
- `JARVIS_DASHBOARD_CAMERA_VISION_API_KEY`
- `OMLX_BASE_URL`, `OMLX_VISION_MODEL`, `OMLX_API_KEY` as generic fallbacks

### Safety and privacy

- The phone dashboard must be open and camera permission must be granted.
- Camera commands are explicit, bounded, and visible in the HUD.
- Short videos require a finite `duration`.
- Monitoring requires a finite `maxDuration`.
- Captured artifacts are saved locally under `media/dashboard-camera/`.
- Android Chrome requires the dashboard origin to be treated as secure for `getUserMedia()`.

## LAN dashboard hosting research

Original research date: 2026-05-17

### Goal

Create a simple website that is reachable, at minimum, from any trusted device on the home Wi-Fi.

### Key networking facts

- `localhost` / `127.0.0.1` means "this same machine only". A phone on Wi-Fi cannot reach a server that only binds to localhost.
- A LAN-accessible service must bind to a real network interface, typically by listening on `0.0.0.0` for IPv4.
- Other devices then open `http://<host-LAN-IP>:<port>`.
- macOS may block inbound connections through the Application Firewall until the runtime/app is allowed.
- Orka Desktop without bridged networking leaves the macOS VM behind NAT. That makes direct LAN access to the VM awkward unless Orka offers port forwarding or the physical Mac host runs a relay/reverse proxy.

### Options considered

#### 1. Run the dashboard directly on the dashboard host host over LAN — chosen

**Design:**

```text
phone/laptop on Wi-Fi -> http://<dashboard-host-lan-ip>:8787 -> Node.js server on dashboard host
```

**Why this is the best first implementation:**

- Satisfies the requirement: any device on the same home Wi-Fi can access it.
- No domain, public DNS, router changes, SSL certificate, or VM network bridge required.
- Uses only Node.js and macOS built-in `launchd` for persistence.
- Avoids Orka NAT/bridged-networking issues.

**Operational requirements:**

- Server listens on `0.0.0.0:8787`.
- dashboard host remains awake/on.
- Other devices must be on the same LAN/subnet.
- macOS firewall must allow Node.js/incoming connections.
- Ideally reserve the dashboard host's IP in the router's DHCP settings so the URL stays stable.

#### 2. Run inside Orka VM with host forwarding — possible, not chosen

**Design:**

```text
phone/laptop -> <dashboard-host-lan-ip>:8787 -> host forwarder -> Orka-VM-NAT-IP:8787
```

This can work with a relay such as `socat`, nginx, Caddy, or a host-side reverse proxy, but it creates extra moving parts:

- VM internal IP can change.
- Host relay must stay running.
- App inside VM must still listen on `0.0.0.0`, not `localhost`.
- Debugging crosses two network boundaries.

Given bridged networking is unavailable, the dashboard host host is simpler and more reliable.

#### 3. Public domain + Cloudflare Tunnel — good future upgrade

**Design:**

```text
internet -> https://dashboard.example.com -> Cloudflare Tunnel -> localhost:8787 on dashboard host
```

This avoids router port forwarding and gives HTTPS, but it makes the dashboard reachable from outside the house. If used later, add authentication before exposing controls.

Useful official docs:

- [Cloudflare Tunnel: run as a macOS service](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/)
- [cloudflared GitHub repo](https://github.com/cloudflare/cloudflared)

#### 4. Router port forwarding — not recommended for this dashboard yet

Router forwarding would expose the dashboard host directly to the internet. It requires dynamic DNS/static public IP handling, router configuration, HTTPS, and real authentication. For a JARVIS control surface, this should not be the first deployment path.

### Implementation decision

This project implements option 1:

- A dependency-free Node.js static server.
- Default bind: `HOST=0.0.0.0`.
- Default port: `PORT=8787`.
- Status API at `/api/status` showing detected LAN URLs.
- Optional macOS LaunchAgent installer for automatic startup at login.

### References

- [Node.js `net.Server.listen()` documentation](https://nodejs.org/api/net.html) — explains host/interface binding.
- [Apple: Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) — launchd background jobs.
- [launchd.plist man page](https://keith.github.io/xcode-man-pages/launchd.plist.5.html) — `RunAtLoad`, `KeepAlive`, paths, and service keys.
- [Vite server host docs](https://vite.dev/config/server-options) — equivalent `host: 0.0.0.0` concept for frontend dev servers.

## Discord voice wake-word gating research

Original research date: 2026-05-20

### Question

Can the Discord voice pipeline avoid constantly calling oMLX Whisper ASR by running a much lighter wake-word detector first, and only sending audio to ASR after a wake word is detected?

### Short answer

Yes. The pipeline originally had a transcript wake-word gate, but that gate was downstream of oMLX ASR. A lightweight acoustic detector can be inserted upstream of ASR:

```text
Original:
Discord 48 kHz stereo PCM -> RMS/silence gate -> oMLX Whisper ASR -> transcript wake-word regex -> Pi/TTS

Recommended:
Discord 48 kHz stereo PCM -> 16 kHz mono conversion -> lightweight wake detector -> capture utterance -> oMLX Whisper ASR -> Pi/TTS
```

This dramatically reduces oMLX ASR calls because non-wake speech/noise never reaches Whisper. Operation JARVIS now uses openWakeWord-style upstream gating in the Discord voice and room-audio paths.

### Best candidate: openWakeWord

Sources:

- openWakeWord repository: <https://github.com/dscripka/openWakeWord>
- Python package: <https://pypi.org/project/openwakeword/>
- `hey_jarvis` model documentation: <https://github.com/dscripka/openWakeWord/blob/main/docs/models/hey_jarvis.md>
- openWakeWord release assets/model sizes: <https://github.com/dscripka/openWakeWord/releases/tag/v0.5.1>

Relevant findings:

- openWakeWord is offline and Python-native.
- It expects 16-bit, 16 kHz, mono PCM.
- Recommended streaming chunk size is 80 ms / 1280 samples, though v0.6 supports arbitrary input lengths with some latency trade-off.
- It has a pre-trained `hey_jarvis` model.
- Its `Model.predict(...)` returns scores from 0 to 1.
- It supports `threshold`, `patience`, and `debounce_time` controls for false-positive management.
- It can optionally use Silero VAD to reduce non-speech false activations.
- On macOS Apple Silicon, use `inference_framework="onnx"`; TFLite is mainly a Linux path because `tflite-runtime` is only a Linux dependency in the package metadata.
- Code is Apache 2.0, but bundled pre-trained models are CC BY-NC-SA 4.0, which is fine for personal/non-commercial use but worth noting.

### Important caveat: “Jarvis” vs “Hey Jarvis”

The pre-trained openWakeWord model is trained for **“hey jarvis”**, not reliably for **“jarvis”** alone. The model docs explicitly say similar phrases like just “jarvis” may work but with higher false-reject rates.

Local synthetic tests confirmed this:

| Test phrase | Max `hey_jarvis` score | Result |
| --- | ---: | --- |
| “hey jarvis what time is it” | 0.995 | strong detection |
| “jarvis what time is it” | 0.054 | no reliable detection |
| “travis what time is it” | 0.00009 | no detection |
| “hey charlie what time is it” | 0.591 | one-frame false positive at default 0.5 threshold |

Implication: if we use stock openWakeWord, the most reliable spoken wake phrase is **“Hey Jarvis”**. If **“Jarvis”** alone is required, train/download a custom openWakeWord model or consider Picovoice Porcupine.

### Local prototype benchmark on this Mac

Environment:

- macOS 15.6.1 arm64
- Python 3.13.13 in `/path/to/local/user`
- `onnxruntime==1.26.0`
- temporary `openwakeword==0.6.0` install, ONNX inference
- Model: `hey_jarvis`

Measured with 60 seconds of synthetic Discord-shaped silence:

```text
48 kHz stereo PCM -> audioop.tomono/ratecv -> 16 kHz mono -> openWakeWord ONNX
60.0s audio processed in 2.29s wall time
real-time factor: 0.038
~0.76 ms CPU work per 20 ms Discord input frame
```

With openWakeWord's optional Silero VAD enabled:

```text
60.0s audio processed in 2.57s wall time
real-time factor: 0.043
~0.86 ms CPU work per 20 ms Discord input frame
```

This is orders of magnitude lighter than repeatedly calling local Whisper ASR through oMLX.

### False positives / threshold strategy

The default 0.5 threshold can trigger borderline false positives. In local tests, “hey charlie” briefly scored 0.59. Recommended initial controls:

```text
threshold: 0.70 to 0.80
patience: optional 2 consecutive frames if threshold remains 0.5
confirmation: keep existing Whisper transcript wake-word regex as a second-stage guard initially
```

That means a false acoustic trigger may still cause one ASR call, but random non-wake speech will no longer cause constant ASR calls. Current deployed thresholds may be lower when transcript confirmation or controlled room conditions make that acceptable.

### Picovoice Porcupine alternative

Sources:

- Porcupine repository: <https://github.com/Picovoice/porcupine>
- Python API docs: <https://picovoice.ai/docs/api/porcupine-python/>
- PyPI package: <https://pypi.org/project/pvporcupine/>

Relevant findings:

- Also expects 16-bit, 16 kHz, mono PCM.
- Uses fixed `handle.frame_length` chunks and `handle.process(...)` returns `-1` or keyword index.
- Supports macOS arm64 and Python 3.9+.
- Has a built-in `jarvis` keyword in `pvporcupine.KEYWORDS`.
- Very efficient and mature.
- Requires a Picovoice AccessKey and proprietary model/licensing.

Porcupine is likely the best option if “Jarvis” alone must be preserved immediately and the access-key/licensing trade-off is acceptable. openWakeWord is better if we want fully open/local operation and can use “Hey Jarvis” or train a custom model.

### Integration design for `discord_voice.py`

Current code location:

- `projects/operation-jarvis/voice/discord_voice.py`
- Existing ASR call path: `_handle_utterance(...) -> self.manager.pipeline.transcribe_audio(...)`
- Existing wake-word check: `_transcript_has_wake_word(...)`
- Existing input format constants: Discord PCM is 48 kHz, stereo, 16-bit.

Recommended state machine per Discord member:

1. Keep receiving Discord PCM exactly as now.
2. Maintain a per-member rolling raw PCM buffer, at least 2 seconds.
3. Convert each member's incoming audio from 48 kHz stereo to 16 kHz mono using stateful `audioop.ratecv`.
4. Accumulate 1280-sample / 80 ms chunks for openWakeWord.
5. Run openWakeWord on those chunks.
6. On detection:
   - create/start the existing `_VoiceUserBuffer` using the rolling pre-roll buffer so “hey jarvis” is included for ASR;
   - continue appending only that utterance until acoustic silence;
   - then queue the utterance to the existing ASR/Pi/TTS path.
7. Initially keep the transcript wake-word check as confirmation; optionally make it configurable later.

Why per-member state matters:

- `discord-ext-voice-recv` delivers decoded PCM by user.
- openWakeWord has internal temporal buffers; interleaving multiple speakers into one model state would corrupt detection.
- Per-member detector state avoids cross-speaker contamination.

Implementation notes:

- Warm up each openWakeWord detector with about 0.5 seconds of zeros because openWakeWord suppresses initial frames after reset.
- Do not reset the detector between ordinary utterances; continuous state is expected.
- Add debounce/cooldown after activation so one wake phrase does not trigger multiple captures.
- If the dependency/model is missing, block voice ASR or use an explicit emergency fallback; do not silently return to always-ASR behavior.
- Use ONNX on this Mac. Do not use TFLite unless running on Linux with `tflite-runtime` available.

### Recommended path

Phase 1, safest:

- Add optional `openwakeword` acoustic gate using stock `hey_jarvis` ONNX model.
- Start with threshold around `0.75`.
- Keep existing transcript wake-word regex as second-stage confirmation.
- Document that the most reliable spoken wake phrase is **“Hey Jarvis”**.

Phase 2, better UX:

- Train or obtain an openWakeWord custom **“Jarvis”** model, or switch the backend to Porcupine built-in `jarvis` if Picovoice licensing/access-key is acceptable.
- After real-world false-positive testing, decide whether to disable transcript confirmation for lower latency.

### Conclusion

The upstream wake-word gate is technically compatible with the Discord voice pipeline and solves the constant oMLX Whisper load problem. openWakeWord is the recommended first implementation because it works locally on this Mac with ONNX, is lightweight in benchmarks, and fits the existing Python code. The main product decision is whether saying **“Hey Jarvis”** is acceptable; if not, use a custom wake model or Porcupine's built-in `jarvis` keyword.

## Roadmap

- Dashboard phone voice mode is now the active dashboard-side audio direction: browser-side `hey_jarvis` wake detection, WAV upload to the Mac room-audio pipeline, and phone speaker playback.
- Tune dashboard voice thresholds on the real phone: wake threshold, mic gain, silence timeout, max utterance length, and secure-origin setup.
- Consider a custom openWakeWord model for the shorter “Jarvis” wake phrase.
