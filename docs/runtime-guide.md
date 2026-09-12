# JARVIS setup and runtime guide

[Project overview](../README.md) · [Native app operations](../projects/operation-jarvis/jarvis-app/docs/operations.md)

JARVIS is a personal deployment with separately configured components. These commands are for a development setup, not an instruction to recreate or restart an existing live system. Keep credentials and runtime state outside Git.

## Initial setup

From a development checkout:

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

Copy `.env.example` only during initial setup; do not overwrite an existing private configuration. Install Pi and project packages using the [detailed rebuild instructions](../.pi/docs/REBUILD_FROM_SCRATCH.md). Integration credentials, model providers, host mappings, and devices must be configured for the components you intend to use.

On a configured host, the documented read-only smoke test is:

```bash
.pi/smoke-test.sh
```

Read its scope before running it against a live environment. This documentation change did not run runtime smoke tests, contact devices, or restart services.

## Component map

| Component | Location |
|---|---|
| Pi CLI/RPC process management and persistent sessions | [`pi_rpc.py`](../pi_rpc.py) |
| Tools, lazy schemas, attachments, and integrations | [`.pi/extensions/`](../.pi/extensions/) |
| Explicit durable memory | [`.pi/memory/`](../.pi/memory/) |
| Private scheduler and retained results | [`.pi/scheduler/`](../.pi/scheduler/) |
| Native apps, `jarvisd`, and `terminald` | [`jarvis-app/`](../projects/operation-jarvis/jarvis-app/) |
| Mac-side voice processing | [`voice/`](../projects/operation-jarvis/voice/) |
| Raspberry Pi capture/playback transport | [`room_audio/`](../projects/operation-jarvis/raspberry-pi/room_audio/) |
| Device control, media, and related integrations | [`operation-jarvis/`](../projects/operation-jarvis/) |

## Private scheduled jobs

Read-only inventory:

```bash
.venv/bin/python .pi/scheduler/runner.py --json status
.venv/bin/python .pi/scheduler/runner.py --json list
```

The private database is `.pi/scheduler/scheduler.sqlite`; directory/file modes are `0700/0600`. Retention is bounded to 500 results, each capped at 64 KiB. Silent successful checks update health without creating a result; output-producing successes and failures are retained. Native Jobs reads expose sanitized bounded results, not prompts, models, command lines, credentials, or private runtime paths.

Inside Pi, load the optional `cron` tool group and use `jarvis_cron`. Native Jobs is intentionally read-only. Installing or changing the scheduler is a separate owner-authorized operation. For initial host setup only, after that authorization, the installation command is:

```bash
.venv/bin/python .pi/scheduler/runner.py --json install
```

That command installs the periodic launchd runner; it is not a status check. Notification implementation and activation are separate. Do not infer that APNs is dormant or active from old README wording; consult the [notification boundaries](../projects/operation-jarvis/jarvis-app/docs/architecture.md#notifications-and-privacy).

## Native app

The Xcode project is generated from [`project.yml`](../projects/operation-jarvis/jarvis-app/project.yml). In an isolated Mac development checkout:

```bash
cd projects/operation-jarvis/jarvis-app
./scripts/verify-jarvis-app.sh
```

The verifier includes XcodeGen project generation and writes build artifacts. Read [operations](../projects/operation-jarvis/jarvis-app/docs/operations.md) for prerequisites, test opt-ins, signing, and physical deployment gates. Never rebuild between archive audit and installation; use only separately authorized exact audited products and approved devices.

## Room audio

The Mac service uses [Pi RPC](../pi_rpc.py), the [voice pipeline](../projects/operation-jarvis/voice/voice_pipeline.py), [ASR backends](../projects/operation-jarvis/voice/asr_backends.py), and the [LAN bridge](../projects/operation-jarvis/raspberry-pi/room_audio/room_audio_server.py). Raspberry Pi capture/playback and its service installer remain separate.

Read-only health on a configured Mac host:

```bash
curl -fsS http://127.0.0.1:8791/health | python3 -m json.tool
```

See the [room-audio README](../projects/operation-jarvis/raspberry-pi/room_audio/README.md) for backend-specific setup. Health access is not permission to start, stop, install, or reconfigure audio services.

## Pi tool loading

Always-on tools cover coding, SSH, web research/fetch, Maps, and `load_tools`. Optional groups include `memory`, `code_docs`, `jarvis`, `minecraft_jarvis`, `github`, `google`, `cron`, `browser`, and `reaper`.

Load only the group needed for a task. Hardware actions remain explicit and bounded; scheduler and Jobs reads are separate from device actions. See [Pi extension documentation](../.pi/docs/PI_EXTENSIONS.md).

## Runtime safety

- Never commit `.env`, API credentials, device selectors, APNs keys/tokens, private databases, conversation history, archives, or unreviewed screenshots.
- Keep private configuration and SQLite files/sidecars mode `0600`; private runtime directories use `0700`. Provider keys belong outside Git in an owner-only location.
- Do not expose JARVIS services publicly. LAN/Tailscale policy and authentication modes must remain explicit and fail closed.
- Hardware writes require fresh authoritative state and must not be inferred, queued, replayed, or retried after ambiguous delivery.
- Do not disturb `terminald` or protected `jarvis-mobile` tmux sessions while changing unrelated services.
- Historical signing commands and build labels are not current deployment authorization.
