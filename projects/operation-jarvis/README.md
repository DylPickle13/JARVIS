# Operation JARVIS

This directory connects JARVIS to the things around the house: plugs, the air purifier, speakers, and a Raspberry Pi microphone. It also contains the iPhone and Watch apps and their backend services.

## Components

- **[jarvisd](jarvisd/):** shared control backend on port `8790` for health, state, services, job results, and allowlisted device commands. Network allowlisting and token authentication are separate modes.
- **terminald:** mobile terminal relay on port `8792`, restricted to the protected `jarvis-mobile` tmux sessions.
- **[Pi Desk](pi-desk/):** lightweight living-room Raspberry Pi workspace: fullscreen session grid, live Pi status, three-pane SSH groups, recovery, and boot startup.
- **Room audio:** Raspberry Pi capture/playback with Mac-side Apple SpeechTranscriber for ordinary turns, DictationTranscriber for busy-only `stop`, Pi RPC, and Piper speech on port `8791`.
- **Apple apps:** iPhone, Watch, and two widgets per platform.
- **Smart plugs:** local TP-Link Kasa control through a fixed plug catalogue.
- **Security:** reviewed CLI source in `security/`, with private credentials/inventory/media kept ignored. jarvisd exposes token-protected on-demand status only. Pi tools add local reads and explicit Tapo cloud automation management; writes are gated by revision checks and readback verification.
- **Air purifier:** VeSync/Levoit Vital 200S-P status and validated controls.
- **[AJAZZ keyboard](ajazz-keyboard/):** tested wired-AK820 lighting CLI and liked-effect preferences, moved here without duplication. An owner-authorized local watcher checks authenticated basement proximity approximately every three seconds: either device nearby resumes minute-spaced liked effects; both away applies purple ripples once. The collector's 10-second nearby hold stays unchanged; unknown/stale leaves lighting unchanged. The private `Keyboard lights` scheduler job only relays alerts and checks watcher health. See [automation details](ajazz-keyboard/docs/AUTOMATION.md). No keyboard backend route or new HID protocol is added.
- **Media:** Google Cast, YouTube, Spotify Connect, and short room speech.
- **Provider quotas:** read-only Codex/Copilot status for `jarvisd` and the apps.
- **Private jobs:** the local scheduler and its limited, owner-only result history, shown read-only in Jobs.

## Layout

```text
projects/operation-jarvis/
├── air-purifier/               # VeSync adapter
├── ajazz-keyboard/             # manual AK820 lighting CLI, presets and offline tests
├── jarvisd/                    # shared control backend, API, tests, LaunchAgents
├── jarvis-app/                 # iPhone, Watch, widgets, JARVISKit, terminald
├── pi-desk/                    # living-room Pi terminal, boot service, backups, tests
├── quotas/                     # read-only provider quota collection
├── room-audio/                # Mac-hosted room conversations and audio endpoints
├── smart-plug/                 # local Kasa adapter and private catalogue
├── security/                   # reviewed CLI source; private runtime/config ignored
├── voice/                      # neutral ASR/Pi RPC/Piper voice pipeline
├── jarvis.py                   # closed Operation JARVIS CLI implementation
└── jarvis-cli                  # stable executable wrapper
```

The shared Pi RPC code is at [`../../pi_rpc.py`](../../pi_rpc.py). The scheduler backend is at [`jarvisd/jarvisd_core/scheduler/`](jarvisd/jarvisd_core/scheduler/); Pi exposes only thin adapters.

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

## Shared backend

`jarvisd` is independent of the Apple app. CLI/Pi plug and purifier writes use
its authenticated loopback route; current native clients use a separate app-authenticated
route through the same dispatcher. This is best-effort coordination, not exclusive
SDK ownership. Security controls remain in the standalone CLI; jarvisd exposes
only authenticated on-demand status. Smart Actions explicitly use Tapo cloud.
Terminal and audio processing remain separate services. See the [architecture and migration plan](docs/backend-architecture.md)
and [backend operations](jarvisd/README.md).

## Pi household-control tools

Load `operation_jarvis` for five focused tools: `operation_jarvis_plugs`,
`operation_jarvis_purifier`, `operation_jarvis_media`, `operation_jarvis_security`,
and `operation_jarvis_automations`. The former `jarvis` group/tool and `smart_plug`
tool are retired; CLI commands and backend routes are unchanged. See the
[tool guide](../../.pi/docs/OPERATION_JARVIS_TOOLS.md) for schemas, safety gates,
offline tests and rollout. No new daemon or polling is installed.

## Native app

See [`jarvis-app/README.md`](jarvis-app/README.md). The app provides:

- **Home:** system, plug, purifier, service, and quota status, including freshness;
- **JARVIS:** the protected Pi terminal;
- **Jobs:** read-only saved results, schedules, details, unread markers, and safe HTTP(S) links;
- **Settings:** connection and terminal preferences. Signing-renewal controls depend on the build; see the [signing notes](jarvis-app/scripts/README.md).

The Watch preserves native plug/purifier controls and terminal behavior. Each widget platform exposes only Neural Core and Open JARVIS.

## Private scheduler

The generic scheduler stores its database at `projects/operation-jarvis/data/scheduler/scheduler.sqlite` under the repository root. It retains at most 500 sanitized results of at most 64 KiB each:

- a successful run with no output updates health only;
- a successful run with output creates one result;
- every failure creates one result;
- prompt, model, command line, credentials, and local paths are not exposed by jarvisd;
- notifications need paid-program signing and explicit activation; check the [notification setup notes](jarvis-app/docs/architecture.md#notifications-and-privacy) rather than assuming they are active or dormant.

Read-only status:

```bash
cd /path/to/JARVIS
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json status
.venv/bin/python projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py --json list-public
```

## Room audio

The [Mac room-audio server](room-audio/room_audio_server.py) uses the [voice pipeline](voice/voice_pipeline.py), [Apple ASR helper](voice/apple_asr/), and root `pi_rpc.py`. Mac USB PowerConf and camera clients handle capture, voice activity detection (VAD), wake detection, playback, and exact busy-only `stop` interruption. Raspberry Pi hardware is no longer required; see the [room-audio guide](room-audio/README.md).

Keep room-service work separate from the protected mobile tmux sessions. Announce and obtain approval for a restart, then check `GET /health` before continuing.

## Development

```bash
# Python tests that do not touch hardware
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_asr_backends.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_pi_rpc.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python voice/test_voice_pipeline.py
PYTHONPATH="$PWD/../..:$PWD/voice" ../../.venv/bin/python room-audio/test_room_audio_interrupt.py

# Backend-only verification (isolated runtime; no hardware)
./jarvisd/verify.sh

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
