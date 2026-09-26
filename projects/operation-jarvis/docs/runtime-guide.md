# JARVIS setup and runtime guide

[Project overview](../../../README.md) · [Operation JARVIS](../README.md) · [Native app operations](../jarvis-app/docs/operations.md)

Set up only the components you plan to use. Work in a development checkout, leave existing live services alone, and keep credentials and runtime state out of Git.

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

Copy `.env.example` only for a new setup; do not overwrite an existing configuration. Follow the [rebuild instructions](../../../.pi/docs/REBUILD_FROM_SCRATCH.md) to install Pi and the project packages, then configure your model provider, credentials, hosts, and devices.

On a configured host, the documented read-only smoke test is:

```bash
.pi/smoke-test.sh
```

Check the script's scope before running it against a live environment. The documentation review did not run it or restart any services.

## Component map

| Component | Location |
|---|---|
| Pi CLI/RPC process management and persistent sessions | [`pi_rpc.py`](../../../pi_rpc.py) |
| Tools, lazy schemas, attachments, and integrations | [`.pi/extensions/`](../../../.pi/extensions/) |
| Explicit durable memory | [`.pi/memory/`](../../../.pi/memory/) |
| Private scheduler and retained results | [`jarvisd/jarvisd_core/scheduler/`](../jarvisd/jarvisd_core/scheduler/) |
| Shared control backend (`jarvisd`) | [`jarvisd/`](../jarvisd/) |
| Native apps and `terminald` | [`jarvis-app/`](../jarvis-app/) |
| Mac-side voice processing | [`voice/`](../voice/) |
| Mac-hosted room conversations and device transports | [`room-audio/`](../room-audio/) |
| Device control, media, and related integrations | [`operation-jarvis/`](../) |

## Private scheduled jobs

Read-only inventory:

```bash
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json status
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json list
```

The scheduler uses `projects/operation-jarvis/data/scheduler/scheduler.sqlite`, with directory/file permissions of `0700/0600`. It keeps up to 500 results, each at most 64 KiB. A successful check with no output updates health without adding a result; successes with output and failures are saved. The native Jobs view receives sanitized results, without prompts, models, command lines, credentials, or private paths.

Inside Pi, load `cron` and use `jarvis_cron`. Jobs support one category, defaulting to **Uncategorized**: `list` accepts a `category` filter, and `set_category` with `jobId` and `category` changes only organizational metadata. The native iPhone/Watch Jobs views group enabled jobs by category and remain read-only. See [scheduler categories](../jarvisd/jarvisd_core/scheduler/README.md#job-categories) for CLI usage and compatibility. Installing or changing the scheduler requires owner approval. Once approved, use this command for initial host setup:

```bash
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json install
```

This installs the periodic launchd runner; it is not a status check. Notifications also need their own configuration and approval. See [notification setup and privacy](../jarvis-app/docs/architecture.md#notifications-and-privacy) rather than relying on old APNs activation notes.

## Native app

The Xcode project is generated from [`project.yml`](../jarvis-app/project.yml). In an isolated Mac development checkout:

```bash
cd projects/operation-jarvis/jarvis-app
./scripts/verify-jarvis-app.sh
```

The verifier regenerates the Xcode project and writes build artifacts. See [operations](../jarvis-app/docs/operations.md) for dependencies, optional tests, signing, and device installation. Install only the approved, audited build on approved devices. Do not rebuild it between audit and installation.

## Room audio

The Mac service uses [Pi RPC](../../../pi_rpc.py), the [voice pipeline](../voice/voice_pipeline.py), [ASR backends](../voice/asr_backends.py), and the [room bridge](../room-audio/room_audio_server.py). Active endpoints use Mac USB PowerConf and camera audio; retired Raspberry Pi scripts and installation guides have been removed.

Read-only health on a configured Mac host:

```bash
curl -fsS http://127.0.0.1:8791/health | python3 -m json.tool
```

See the [room-audio README](../room-audio/README.md) for backend-specific setup. A health check does not authorize starting, stopping, installing, or reconfiguring audio services.

## Pi tool loading

Always-on tools cover coding, SSH, web research/fetch, Maps, and `load_tools`. Optional groups include `memory`, `code_docs`, `jarvis`, `github`, `google`, `cron`, `browser`, and `reaper`.

Load only the group you need. Reading Jobs or scheduler status does not authorize device actions. See the [Pi extension guide](../../../.pi/docs/PI_EXTENSIONS.md).

## Runtime safety

- Never commit `.env`, API credentials, device selectors, APNs keys/tokens, private databases, conversation history, archives, or unreviewed screenshots.
- Keep private configuration and SQLite files/sidecars mode `0600`; private runtime directories use `0700`. Provider keys belong outside Git in an owner-only location.
- Do not expose JARVIS services publicly. LAN/Tailscale policy and authentication modes must remain explicit and fail closed.
- Hardware writes require fresh authoritative state and must not be inferred, queued, replayed, or retried after ambiguous delivery.
- Do not disturb `terminald` or protected `jarvis-mobile` tmux sessions while changing unrelated services.
- Historical signing commands and build labels are not current deployment authorization.
