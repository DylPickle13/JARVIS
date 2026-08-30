# JARVIS

JARVIS is a private local automation and control stack built around the [Pi coding agent](https://github.com/earendil-works/pi-coding-agent). It combines persistent Pi RPC sessions, bounded scheduled-job history, durable memory, browser and Google tooling, Cast/Spotify media, smart plugs, a Levoit air purifier, Raspberry Pi room audio, and native iOS/watchOS clients through `jarvisd`.

## Architecture

- **Pi** — local coding-agent UI, RPC process management, extensions, tools, and model selection.
- **Private scheduler** — [`.pi/scheduler/runner.py`](.pi/scheduler/runner.py) executes four preserved jobs and stores sanitized output-producing successes plus every failure in an owner-only bounded SQLite database.
- **Native Apple clients** — [`projects/operation-jarvis/jarvis-app/`](projects/operation-jarvis/jarvis-app/) provides Home, JARVIS terminal, Jobs, and Settings on iPhone plus guarded Watch controls and widgets.
- **jarvisd** — authenticated read-only state/results APIs and closed, validated native hardware commands on port `8790`.
- **terminald** — isolated mobile terminal relay on port `8792`, bound to the protected `jarvis-mobile` tmux session.
- **Room audio** — Raspberry Pi microphone/speaker endpoint → oMLX Whisper → neutral Pi RPC → Piper speech through the Mac service on port `8791`.
- **Operation JARVIS tools** — Cast, Spotify, local Kasa plugs, and VeSync/Levoit purifier control.

## Repository map

| Path | Purpose |
|---|---|
| [`pi_rpc.py`](pi_rpc.py) | Neutral Pi CLI/RPC process management and persistent local sessions. |
| [`.pi/extensions/`](.pi/extensions/) | Project-local tools, lazy schemas, native attachment picker, memory, scheduler, browser, Google, Maps, GitHub, SSH, REAPER, and Operation JARVIS integrations. |
| [`.pi/scheduler/`](.pi/scheduler/) | Generic scheduler, bounded results, dormant fail-closed APNs provider scaffold, and tests. |
| [`.pi/memory/`](.pi/memory/) | Explicit owner-only durable memory. |
| [`projects/operation-jarvis/`](projects/operation-jarvis/) | Physical-world control, room audio, quotas, and native app. |
| [`projects/operation-jarvis/voice/`](projects/operation-jarvis/voice/) | Transport-neutral ASR, response, normalization, streaming, interruption, and Piper pipeline. |
| [`projects/operation-jarvis/jarvis-app/`](projects/operation-jarvis/jarvis-app/) | Native iPhone, Watch, widgets, JARVISKit, jarvisd, and terminald. |

## Setup

```bash
cd /path/to/JARVIS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
npm install --prefix .pi/extensions/lib
npm install --prefix .pi/extensions/50-browser
```

Install Pi and project packages as documented in [`.pi/docs/REBUILD_FROM_SCRATCH.md`](.pi/docs/REBUILD_FROM_SCRATCH.md), then run the read-only smoke test:

```bash
.pi/smoke-test.sh
```

## Private scheduled jobs

```bash
# Read-only status/list
.venv/bin/python .pi/scheduler/runner.py --json status
.venv/bin/python .pi/scheduler/runner.py --json list

# Install the one-minute launchd runner
.venv/bin/python .pi/scheduler/runner.py --json install
```

The database is `.pi/scheduler/scheduler.sqlite` with directory/file modes `0700/0600`. Retention is 500 results, each capped at 64 KiB. Successful checks with no output update health only. Output-producing successes and all failures appear in the native Jobs inbox. The native API never exposes prompts, models, command lines, credentials, or local paths.

Inside Pi, load the optional `cron` group and use `jarvis_cron` for scheduler management. The iPhone Jobs surface is intentionally read-only.

## Native app

The app project is generated from `projects/operation-jarvis/jarvis-app/project.yml`:

```bash
cd projects/operation-jarvis/jarvis-app
xcodegen generate
./scripts/verify-jarvis-app.sh
```

Physical deployment uses the fixed private signing-renewal script and allowlisted devices. Do not rebuild between archive audit and installation. See the app [README](projects/operation-jarvis/jarvis-app/README.md) for deployment and safety contracts.

## Room audio

The Mac service uses:

- [`pi_rpc.py`](pi_rpc.py) for neutral persistent Pi RPC;
- [`voice_pipeline.py`](projects/operation-jarvis/voice/voice_pipeline.py) for oMLX ASR and Piper TTS;
- [`room_audio_server.py`](projects/operation-jarvis/raspberry-pi/room_audio/room_audio_server.py) for the bounded LAN bridge.

Read-only health:

```bash
curl -fsS http://127.0.0.1:8791/health | python3 -m json.tool
```

The Raspberry Pi capture/playback client and service installer remain under [`projects/operation-jarvis/raspberry-pi/room_audio/`](projects/operation-jarvis/raspberry-pi/room_audio/).

## Pi tool loading

Always-on tools cover coding, SSH, web research/fetch, Maps, and `load_tools`. Optional groups include:

`memory`, `code_docs`, `jarvis`, `minecraft_jarvis`, `github`, `google`, `cron`, `browser`, and `reaper`.

Load only the group needed for the current task. Hardware operations remain explicit and bounded; scheduler and native Jobs reads are separate from hardware actions.

## Security and runtime rules

- Never commit `.env`, API credentials, device selectors, APNs keys, tokens, runtime databases, or private archives.
- Keep `.env`, SQLite files, and sidecars mode `0600`; private runtime directories use `0700`.
- The future APNs `.p8` key must live outside Git in an owner-only `0700/0600` location.
- Do not expose JARVIS services publicly. Trusted LAN/Tailscale access and endpoint policy remain fail-closed.
- Hardware writes require fresh authoritative state and are never queued, inferred, replayed, or retried after ambiguous delivery.
- Do not disturb terminald or the protected `jarvis-mobile` tmux session while changing unrelated services.
- Use exact audited archive products for physical Apple-device deployment.

## Documentation

- [Pi extensions](.pi/docs/PI_EXTENSIONS.md)
- [Rebuild from scratch](.pi/docs/REBUILD_FROM_SCRATCH.md)
- [Operation JARVIS](projects/operation-jarvis/README.md)
- [Native app](projects/operation-jarvis/jarvis-app/README.md)
- [Room audio](projects/operation-jarvis/raspberry-pi/room_audio/README.md)
