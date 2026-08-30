# Operation JARVIS

Operation JARVIS is the physical-world and native-client layer of the local JARVIS stack.

## Components

1. **jarvisd** — authenticated native API on port `8790` for health, state, services, scheduled jobs/results, and closed hardware commands.
2. **terminald** — isolated mobile terminal relay on port `8792` for the protected `jarvis-mobile` tmux session.
3. **Room audio** — Raspberry Pi microphone/speaker client with Mac-side Apple SpeechTranscriber turn ASR, Apple DictationTranscriber busy-only `stop` ASR, neutral Pi RPC, and Piper speech on port `8791`.
4. **Native Apple app** — iPhone, Watch, and two widgets per platform.
5. **Smart plugs** — local TP-Link Kasa control through a closed plug catalogue.
6. **Air purifier** — VeSync/Levoit Vital 200S-P status and guarded writes.
7. **Media** — Google Cast, YouTube, Spotify Connect, and short room speech.
8. **Provider quotas** — read-only Codex/Copilot telemetry for jarvisd and native clients.
9. **Private jobs** — generic local scheduler plus bounded owner-only result history exposed read-only to iPhone Jobs.

## Layout

```text
projects/operation-jarvis/
├── air-purifier/               # VeSync adapter
├── jarvis-app/                 # iPhone, Watch, widgets, JARVISKit, jarvisd, terminald
├── quotas/                     # read-only provider quota collection
├── raspberry-pi/room_audio/    # Pi client and Mac room-audio server
├── smart-plug/                 # local Kasa adapter and private catalogue
├── voice/                      # neutral ASR/Pi RPC/Piper voice pipeline
├── jarvis.py                   # closed Operation JARVIS CLI implementation
└── jarvis-cli                  # stable executable wrapper
```

Shared neutral Pi RPC lives at repository root in [`../../pi_rpc.py`](../../pi_rpc.py). Scheduled jobs live at [`../../.pi/scheduler/`](../../.pi/scheduler/).

## Safe status checks

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json purifier-status
curl -fsS http://127.0.0.1:8790/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8791/health | python3 -m json.tool
```

Do not run hardware-write commands as a smoke test. Native plug and purifier writes require fresh authoritative state and exact confirmed outcomes.

## Native app

See [`jarvis-app/README.md`](jarvis-app/README.md). The app provides:

- **Home** — live system, plug, purifier, service, and quota state;
- **JARVIS** — protected Pi terminal;
- **Jobs** — read-only retained result inbox, schedules, details, unread state, and safe HTTP(S) links;
- **Settings** — connection, terminal, and fixed private signing renewal.

The Watch preserves native plug/purifier controls and terminal behavior. Each widget platform exposes only Neural Core and Open JARVIS.

## Private scheduler

The generic scheduler stores its database at `.pi/scheduler/scheduler.sqlite` under the repository root. It retains at most 500 sanitized results of at most 64 KiB each:

- a successful run with no output updates health only;
- a successful run with output creates one result;
- every failure creates one result;
- prompt, model, command line, credentials, and local paths are not exposed by jarvisd;
- notification delivery is dormant until direct Watch APNs is explicitly activated after paid enrollment.

Read-only status:

```bash
cd /path/to/JARVIS
.venv/bin/python .pi/scheduler/runner.py --json status
.venv/bin/python .pi/scheduler/runner.py --json list-public
```

## Room audio

The Mac service in [`raspberry-pi/room_audio/room_audio_server.py`](raspberry-pi/room_audio/room_audio_server.py) imports the transport-neutral [`voice/voice_pipeline.py`](voice/voice_pipeline.py), native [`voice/apple_asr/`](voice/apple_asr/) helper, and root `pi_rpc.py` modules. The Pi client owns USB capture, VAD, local wake detection, playback, and exact busy-only `stop` interruption.

The room service does not own the protected mobile tmux session. Restart it only as an announced controlled step, then validate `GET /health` before continuing.

## Development

```bash
# Python tests that do not touch hardware
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_asr_backends.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_pi_rpc.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_voice_pipeline.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python raspberry-pi/room_audio/test_room_audio_interrupt.py

# Native/daemon verification
cd jarvis-app
./scripts/verify-jarvis-app.sh
```

## Safety contracts

- Never expose public inbound control.
- Never log credentials, endpoint tokens, APNs device tokens, or private output.
- Never queue/replay hardware writes or retry ambiguous Watch writes.
- Refresh stale state before writes and confirm the requested final state.
- Preserve ports `8790–8792`, terminal byte ordering, PTY resize ordering, and the protected tmux pane.
- Do not add hardware-write paths to widgets or the native Jobs surface.
- Keep direct Watch APNs disabled until the paid Watch-host entitlement/profile/key/token flow is physically proven.
