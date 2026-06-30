# Operation JARVIS

Unified project for a practical real-world JARVIS loop using:

1. **Discord** — command surface, conversation, files, live voice calls, and audit log.
2. **Dashboard phone voice** — browser/PWA wake word, phone microphone capture, Mac-side STT/LLM/TTS, and phone speaker playback.
3. **Google Cast** — spoken output plus TV/speaker media control.
4. **Dashboard** — LAN holographic HUD, telemetry, artifacts, and allowlisted room controls.
5. **Smart plugs** — local TP-Link Kasa HS103 control for devices around the house.
6. **Air purifier** — direct VeSync/Levoit Vital 200S-P status and control through `purifier-status` and `purifier-set`.
7. **Raspberry Pi room audio** — always-listening room microphone/speaker endpoint.

**Local/private operations note:** this README intentionally contains LAN IPs, device names, service paths, and other local runbook details. Keep it private; do not publish without redaction.

Created: 2026-05-14<br>
Integrated live Discord voice subsystem: 2026-05-15<br>
Integrated LAN dashboard/HUD: 2026-05-17<br>
Tested dashboard phone camera as a vision source: 2026-05-17<br>
Integrated local Kasa smart plugs: 2026-05-23<br>
Added dashboard phone voice mode and removed the camera panel from the active HUD: 2026-06-21<br>
Integrated Levoit/VeSync air purifier control: 2026-06-28

## Architecture

```text
Discord = interface + log + live voice calls
Dashboard phone voice = portable wake-word mic/speaker endpoint
Cast = room speaker/media output
Dashboard = LAN HUD/control room
Smart plugs = local house device power control
Air purifier = VeSync/Levoit air quality, filter, and purifier controls
Raspberry Pi room audio = room mic/speaker bridge
```

## Local SSH machine inventory

Verified 2026-06-11 EDT. These are private LAN endpoints; keep this table out of public docs.

| Role | Hostname | LAN IP | SSH user | Access notes |
|---|---|---|---|---|
| Raspberry Pi room endpoint | `raspberrypi` | `<private-lan-ip>` | `pi` | Key: `~/.ssh/jarvis_dashboard_host`; owns room-audio client/systemd service. |
| OMLX-64 / configured host SSH-tool host | `<host-name>` | `<private-lan-ip>` | `<ssh-user>` | Pi harness SSH alias: `<ssh-host-alias>`; also has `~/.ssh/jarvis_dashboard_host` authorized for Pi access. |

Quick checks:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> 'hostname; whoami'
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes <ssh-user>@<private-lan-ip> 'hostname; whoami'
```

From the configured host, Pi access was repaired/verified with:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> 'hostname; date; ping -c 3 1.1.1.1'
```

The Pi-facing room tool is loaded through the optional Pi tool group:

```text
load_tools({ groups: ["jarvis"] })
```

After the `jarvis` group is loaded, use the `jarvis` tool directly. It wraps Cast output, smart plugs, air-purifier actions, status checks, and legacy dashboard-camera actions. If a smaller/local model is unsure, the safe guide call is:

```json
{ "action": "help" }
```

## Project contents

```text
projects/operation-jarvis/
├── jarvis.py                   # unified Operation JARVIS adapter
├── jarvis-cli                  # wrapper for jarvis.py
├── voice/                      # Discord voice ASR → Pi RPC → Piper TTS subsystem
├── raspberry-pi/               # Pi hardware, helper scripts, docs, and room_audio subsystem
├── dashboard/                  # LAN HUD/control surface + dashboard phone voice client
├── smart-plug/                 # local TP-Link Kasa HS103 control subsystem
├── scripts/
│   ├── connect_chromecast.py   # Cast target resolution
│   └── tv.py                   # focused Cast command implementation used by jarvis.py
├── media/                      # local media/artifacts, including legacy dashboard-camera captures
├── data/                       # Cast speech/runtime artifacts
├── requirements.txt
├── pyproject.toml
└── *.md
```

## Pi tool actions

Guide/status actions:

- `help`
- `status`

Legacy dashboard camera actions (client UI is currently disabled on the active HUD):

- `look` / `photo`
- `video`
- `video-until`
- `analyze-view`

Cast actions:

- `speak`
- `cast-status`
- `cast-volume`
- `cast-mute`
- `cast-stop`
- `cast-youtube`
- `cast-play-url`
- `cast-spotify-devices`
- `cast-spotify`
- `cast-spotify-pause`
- `cast-spotify-next`
- `cast-spotify-previous`
- `cast-spotify-volume`
- `cast-spotify-queue-add`
- `cast-spotify-queue`
- `cast-spotify-seek`
- `cast-spotify-shuffle`
- `cast-spotify-repeat`

Smart-plug actions:

- `plug-list`
- `plug-status <plug>`
- `plug-on <plug>`
- `plug-off <plug>`
- `plug-toggle <plug>`
- `plug-discover`
- `plug-save-discovery`

## Setup

```bash
cd /path/to/JARVIS/projects/operation-jarvis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Main bot setup/run still lives at the repo root:

```bash
cd /path/to/JARVIS
source .venv/bin/activate
python discord_bot.py
```

## Start / stop / status quickstart

| Component | Start/check command | Notes |
|---|---|---|
| Main Discord bot | `cd /path/to/JARVIS && python discord_bot.py` | Owns text, Pi RPC, and live Discord voice. Do not run duplicate bot tokens. |
| Operation CLI status | `./jarvis-cli --json status --no-cast` | Safe local smoke check from this folder. |
| Dashboard | `cd dashboard && npm start` | LAN HUD, dashboard voice, and control surface. |
| Dashboard service | `cd dashboard && npm run install-service` | Installs login LaunchAgent. |
| Smart plugs | `./jarvis-cli plug-list` | Requires smart-plug venv/credentials. |
| Air purifier | `./jarvis-cli purifier-status` | Requires air-purifier venv/VeSync credentials. |
| Room audio server | `.venv/bin/python raspberry-pi/room_audio/room_audio_server.py --host 0.0.0.0 --port 8791` | Mac-side bridge used by Pi client. |
| Pi room audio client | `raspberry-pi/scripts/install-room-audio-service.sh` | Deploys/refreshes Pi systemd service. |

Safe smoke-test sequence:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json plug-list
curl -s http://127.0.0.1:8787/api/jarvis/status | python3 -m json.tool
```

The smart-plug subsystem uses its own Python 3.11+ virtualenv because HS103 hardware v5 needs newer `python-kasa` KLAP v2 support while the main Operation JARVIS venv may remain on Python 3.9:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/smart-plug
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -e .
```

Spotify actions (`cast-spotify*`) use Spotify Web API + Spotify Connect and require:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REFRESH_TOKEN`

These can be exported in your shell before running `jarvis-cli`.

To let JARVIS start Spotify on an idle Google Cast speaker/group without manually opening Spotify first, also set the optional Spotcast-style browser-cookie credentials:

- `SPOTIFY_SP_DC`
- `SPOTIFY_SP_KEY`

Get them from an incognito login at [open.spotify.com](https://open.spotify.com): DevTools → Application/Storage → Cookies → `https://open.spotify.com`. Close the incognito window without logging out. These cookies must belong to the same Spotify account as `SPOTIFY_REFRESH_TOKEN`.

## Local examples

```bash
cd /path/to/JARVIS/projects/operation-jarvis

# Safe local checks
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json status --device speakers

# Dashboard voice status
curl -s http://127.0.0.1:8787/api/jarvis/dashboard-voice/status | python3 -m json.tool

# Cast
./jarvis-cli cast-status --device speakers
./jarvis-cli cast-volume --device speakers 25
./jarvis-cli cast-youtube --device tv 'relaxing jazz'
./jarvis-cli speak --device speakers 'JARVIS online.'
./jarvis-cli cast-spotify-devices --device speakers
./jarvis-cli cast-spotify --device speakers 'Daft Punk Get Lucky'
./jarvis-cli cast-spotify --device speakers --resume
./jarvis-cli cast-spotify-pause --device speakers
./jarvis-cli cast-spotify-next --device speakers
./jarvis-cli cast-spotify-previous --device speakers
./jarvis-cli cast-spotify-volume --device speakers 25
./jarvis-cli cast-spotify-queue-add --device speakers 'Daft Punk Get Lucky'
./jarvis-cli cast-spotify-queue-add --device speakers --spotify-queue-type episode 'Lex Fridman'
./jarvis-cli cast-spotify-queue --limit 10
./jarvis-cli cast-spotify-seek --device speakers 1:30
./jarvis-cli cast-spotify-shuffle --device speakers toggle
./jarvis-cli cast-spotify-repeat --device speakers context

# Smart plugs
./jarvis-cli plug-list
./jarvis-cli plug-status <configured-plug-name>
./jarvis-cli plug-on <configured-plug-name>
./jarvis-cli plug-off <configured-plug-name>
./jarvis-cli plug-toggle <configured-plug-name>

```

## Dashboard phone voice

The dashboard lives in [`dashboard/`](dashboard/). Its fullscreen PWA now exposes a left-side **Voice** card instead of the old camera panel. Tap **Voice** to arm browser-side `hey_jarvis` wake detection; after a wake hit, the phone captures a short WAV, sends it to the Mac dashboard server, receives Mac-generated Piper audio, and plays the response through the phone speaker.

```text
Phone dashboard wake word + mic
  -> dashboard server /api/jarvis/dashboard-voice/turn
  -> existing Mac room-audio server for oMLX Whisper, Pi RPC, and Piper TTS
  -> phone dashboard audio playback
```

The Raspberry Pi room-audio endpoint remains independent. The right-side **Phone** ADB tile remains on the HUD.

Direct status endpoint:

```bash
curl -s http://127.0.0.1:8787/api/jarvis/dashboard-voice/status | python3 -m json.tool
```

Microphone access requires a secure browser context. On Android Chrome over LAN HTTP, whitelist the dashboard origin in **Insecure origins treated as secure** or serve the dashboard over HTTPS.

## LAN dashboard

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm start
```

Install/reinstall the login LaunchAgent from the integrated location:

```bash
npm run install-service
```

Dashboard actions are locked unless both `JARVIS_ENABLE_DASHBOARD_COMMANDS=true` and `JARVIS_DASHBOARD_WRITE_TOKEN` are set. `jarvis-cli` defaults `JARVIS_DASHBOARD_URL` to `http://127.0.0.1:8787`, so CLI actions emit best-effort lifecycle events to the dashboard automatically; use `JARVIS_DASHBOARD_EMIT_EVENTS=0` to suppress event emission for one process.

## Smart plugs

Smart-plug control lives in [`smart-plug/`](smart-plug/) and is exposed through `jarvis-cli`.

Configured plugs are loaded from ignored local config such as `smart-plug/plugs.json` or `--plug-config`:

```text
<configured-plug-name> -> <private-lan-ip>
```

Control examples:

```bash
./jarvis-cli plug-list
./jarvis-cli plug-status <configured-plug-name>
./jarvis-cli plug-on <configured-plug-name>
./jarvis-cli plug-off <configured-plug-name>
./jarvis-cli plug-toggle <configured-plug-name>
```

Pi tool usage for local models:

```json
{ "action": "list" }
{ "action": "status", "plug": "<configured-plug-name>" }
{ "action": "on", "plug": "<configured-plug-name>" }
{ "action": "off", "plug": "<configured-plug-name>" }
{ "action": "toggle", "plug": "<configured-plug-name>" }
```

Load it with `load_tools({ "groups": ["jarvis"] })`, then call the dedicated `smart_plug` tool. Its normal schema is intentionally small: `action` plus `plug` for control/status, or just `action: "list"`. The broader `jarvis` tool also still accepts `plug-list`, `plug-status`, `plug-on`, `plug-off`, and `plug-toggle` actions.

Credentials load from `smart-plug/.env`, `projects/operation-jarvis/.env`, then repo-root `.env`. All four plugs are verified locally controllable. Keep **Third-Party Compatibility** enabled in the Kasa/Tapo app; when disabled, plugs can still be discovered but local KLAP control may be rejected.

## Service / subsystem map

| Subsystem | Canonical docs | Runtime owner |
|---|---|---|
| Dashboard/HUD/phone voice | [`dashboard/README.md`](dashboard/README.md) | Node server / LaunchAgent |
| Live Discord voice | [`voice/README.md`](voice/README.md) | Root `discord_bot.py` |
| Raspberry Pi endpoint | [`raspberry-pi/README.md`](raspberry-pi/README.md) | Pi SSH/systemd + Mac room server |
| Room audio | [`raspberry-pi/room_audio/README.md`](raspberry-pi/room_audio/README.md) | Pi client + Mac HTTP bridge |
| Smart plugs | [`smart-plug/README.md`](smart-plug/README.md) | Dedicated Python 3.11+ venv |
| Air purifier | [`air-purifier/README.md`](air-purifier/README.md) | Dedicated Python 3.11+ venv, VeSync/Levoit |
| Cast/Spotify | this README + `scripts/tv.py` | `jarvis-cli` / Pi tool |

## Live Discord voice

Canonical voice files live in [`voice/`](voice/). The root [`../../discord_bot.py`](../../discord_bot.py) loads `voice/discord_voice.py` directly for the `jarvis` voice channel.

Voice path:

```text
Discord PCM → openWakeWord acoustic gate → oMLX Whisper ASR → transcript wake confirmation → Pi RPC voice session → Piper JARVIS TTS → Discord playback
```

## Raspberry Pi room audio

The Raspberry Pi room endpoint is consolidated under [`raspberry-pi/`](raspberry-pi/):

- [`raspberry-pi/room_audio/`](raspberry-pi/room_audio/) — Mac-side room-audio server plus Pi client.
- [`raspberry-pi/scripts/`](raspberry-pi/scripts/) — deployment, status, HDMI recovery, and PowerConf diagnostics helpers.
- [`raspberry-pi/docs/`](raspberry-pi/docs/) — Pi hardware notes, display recovery notes, and upgrade history.

Current deployed path:

```text
PowerConf Bluetooth mic/speaker → Pi VAD listener → Mac room-audio server → ASR → Pi RPC → Piper TTS → A2DP playback
```

The Pi uses SCO/HFP for microphone capture and A2DP for higher-quality playback. See [`raspberry-pi/room_audio/README.md`](raspberry-pi/room_audio/README.md) for run commands and tuning.
