# Operation JARVIS

This directory connects JARVIS to the things around the house: plugs, the air purifier, speakers, and a Raspberry Pi microphone. It also contains the iPhone and Watch apps and their backend services.

## Components

- **jarvisd:** native API on port `8790` for health, state, services, job results, and allowlisted device commands. Network allowlisting and token authentication are separate modes.
- **terminald:** mobile terminal relay on port `8792`, restricted to the protected `jarvis-mobile` tmux sessions.
- **Room audio:** Raspberry Pi capture/playback with Mac-side Apple SpeechTranscriber for ordinary turns, DictationTranscriber for busy-only `stop`, Pi RPC, and Piper speech on port `8791`.
- **Apple apps:** iPhone, Watch, and two widgets per platform.
- **Smart plugs:** local TP-Link Kasa control through a fixed plug catalogue.
- **Air purifier:** VeSync/Levoit Vital 200S-P status and validated controls.
- **Media:** Google Cast, YouTube, Spotify Connect, and short room speech.
- **Provider quotas:** read-only Codex/Copilot status for `jarvisd` and the apps.
- **Private jobs:** the local scheduler and its limited, owner-only result history, shown read-only in Jobs.

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

The shared Pi RPC code is at [`../../pi_rpc.py`](../../pi_rpc.py). The scheduler is at [`../../.pi/scheduler/`](../../.pi/scheduler/).

## Safe status checks

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json purifier-status
curl -fsS http://127.0.0.1:8790/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8791/health | python3 -m json.tool
```

Do not switch devices as a smoke test. Plug and purifier changes require fresh device state and confirmation of the requested result.

## Native app

See [`jarvis-app/README.md`](jarvis-app/README.md). The app provides:

- **Home:** system, plug, purifier, service, and quota status, including freshness;
- **JARVIS:** the protected Pi terminal;
- **Jobs:** read-only saved results, schedules, details, unread markers, and safe HTTP(S) links;
- **Settings:** connection and terminal preferences. Signing-renewal controls depend on the build; see the [signing notes](jarvis-app/scripts/README.md).

The Watch preserves native plug/purifier controls and terminal behavior. Each widget platform exposes only Neural Core and Open JARVIS.

## Private scheduler

The generic scheduler stores its database at `.pi/scheduler/scheduler.sqlite` under the repository root. It retains at most 500 sanitized results of at most 64 KiB each:

- a successful run with no output updates health only;
- a successful run with output creates one result;
- every failure creates one result;
- prompt, model, command line, credentials, and local paths are not exposed by jarvisd;
- notifications need paid-program signing and explicit activation; check the [notification setup notes](jarvis-app/docs/architecture.md#notifications-and-privacy) rather than assuming they are active or dormant.

Read-only status:

```bash
cd /path/to/JARVIS
.venv/bin/python .pi/scheduler/runner.py --json status
.venv/bin/python .pi/scheduler/runner.py --json list-public
```

## Room audio

The [Mac room-audio server](raspberry-pi/room_audio/room_audio_server.py) uses the [voice pipeline](voice/voice_pipeline.py), [Apple ASR helper](voice/apple_asr/), and root `pi_rpc.py`. The Pi client handles USB capture, voice activity detection (VAD), local wake detection, playback, and exact busy-only `stop` interruption.

Keep room-service work separate from the protected mobile tmux sessions. Announce and obtain approval for a restart, then check `GET /health` before continuing.

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
