# Operation JARVIS Dashboard

LAN HUD and safe control surface for Operation JARVIS.

**Local/private operations note:** this README intentionally contains LAN addresses, local service paths, and device integration details. Keep it private; do not publish without review.

The dashboard now lives inside:

```text
projects/operation-jarvis/dashboard/
```

It is a Node.js server serving the phone-distance room display from `public/` with these endpoints:

- `/api/status`, `/api/projects`, `/api/events`, `/api/refresh`, `/api/live`, `/api/pulse`, `/ws`
- `/api/jarvis/status` — read-only Operation JARVIS local status
- `/api/jarvis/display` — phone-distance room display telemetry (weather, active Pi sessions, Pi session cost, uptime, OMLX-16/OMLX-64, and dashboard status)
- `/api/jarvis/dashboard-voice/*` — phone dashboard wake-word voice endpoint: browser wake word + Mac-side STT/LLM/TTS + phone speaker playback
- `/api/jarvis/events` — event bridge from `jarvis.py`
- `/api/jarvis/artifacts` — latest media/data artifacts
- `/api/jarvis/actions` — allowlisted actions, disabled unless explicitly armed

## Quick start

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm install  # first setup only, if node_modules is missing
npm start
```

Smoke checks:

```bash
curl -s http://127.0.0.1:8787/api/status | python3 -m json.tool
curl -s http://127.0.0.1:8787/api/jarvis/display | python3 -m json.tool
curl -s http://127.0.0.1:8787/api/jarvis/dashboard-voice/status | python3 -m json.tool
```

## Run manually

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm start
```

Default bind:

```text
0.0.0.0:8787
```

Print LAN URLs:

```bash
npm run url
```

## Alarm clock room display

Open this URL on a phone that will sit across the room:

```text
http://<dashboard-host>:8787
```

The root dashboard is intentionally glanceable as an alarm-clock-style display: huge configured local time, date, current configured-location weather, compact active Pi generation count, live dashboard uptime, and oMLX server online/offline status. It no longer renders the old device-health strip or Cast-ready tile. It does not implement alarm scheduling/snooze/dismiss behavior and it does not show the latest camera image.

The display also ships with a fullscreen landscape web app manifest (`public/manifest.webmanifest`) and a minimal pass-through service worker (`public/sw.js`). On Android Chrome, open the dashboard, use **Add to Home screen**, then launch it from the new JARVIS icon to minimize or remove browser chrome.

## Dashboard Voice Mode

The former left-side camera panel is now a **Voice** card. Tap it to arm dashboard voice mode on the phone:

```text
Phone dashboard:
  openWakeWord WASM detects “Hey Jarvis” locally
  → browser records a short 16 kHz WAV with pre-roll
  → POST /api/jarvis/dashboard-voice/turn

Mac mini:
  dashboard server proxies to the existing room-audio server
  → oMLX Whisper STT
  → Pi RPC JARVIS response
  → Piper JARVIS TTS WAV

Phone dashboard:
  plays returned ack/final WAV through the phone speaker
```

The right-side **Phone** ADB tile remains unchanged. The Raspberry Pi room-audio microphone/speaker path also remains unchanged; dashboard voice is an extra phone endpoint, not a replacement.

Useful checks:

```bash
curl -s http://127.0.0.1:8787/api/jarvis/dashboard-voice/status | python3 -m json.tool
```

Configuration:

- `JARVIS_DASHBOARD_VOICE_ROOM_AUDIO_URL` — room-audio server used for STT/LLM/TTS. Defaults to `JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVER_URL`, then `JARVIS_ROOM_AUDIO_SERVER_URL`, then `http://127.0.0.1:8791`.
- `JARVIS_DASHBOARD_VOICE_ROOM_AUDIO_TOKEN` — optional room-audio token override; defaults to `JARVIS_ROOM_AUDIO_TOKEN`.
- `JARVIS_DASHBOARD_VOICE_MAX_BYTES` — max uploaded WAV size, default 12 MiB.
- `JARVIS_DASHBOARD_VOICE_TIMEOUT_MS` — proxy timeout, default 45 seconds.

Browser URL tuning:

```text
?voiceThreshold=0.62&voiceGain=1.15
?voiceSilenceMs=1000&voiceMaxMs=10000&voicePreRollMs=1400
```

Microphone access requires a secure browser context. On Android Chrome over LAN HTTP, whitelist the dashboard origin in **Insecure origins treated as secure** or serve the dashboard over HTTPS. iOS Safari generally requires HTTPS for non-local microphone access.

## Run automatically at login

This installs the `com.operation-jarvis.dashboard` LaunchAgent. When the repository-level `.env` exists, the service loads it with Node's `--env-file` option so dashboard configuration survives service reinstalls and login restarts. Set `JARVIS_DASHBOARD_ENV_FILE` while installing to use a different env file. Explicit `HOST` and `PORT` installer values take precedence over values in the env file.

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm run install-service
```

Optional custom environment file:

```bash
JARVIS_DASHBOARD_ENV_FILE=/path/to/private-dashboard.env npm run install-service
```

Uninstall:

```bash
npm run uninstall-service
```

Logs:

```text
projects/operation-jarvis/dashboard/logs/launchd.out.log
projects/operation-jarvis/dashboard/logs/launchd.err.log
```

## Command safety

Dashboard commands are not shown on the alarm-clock display and are disabled server-side by default. Enable API actions only on the trusted LAN, and always set a local write token:

```bash
export JARVIS_ENABLE_DASHBOARD_COMMANDS=true
export JARVIS_DASHBOARD_WRITE_TOKEN='set-a-local-token'
```

Clients send the token as `x-jarvis-token` or `Authorization: Bearer ...`. If the token is missing, commands remain locked even when `JARVIS_ENABLE_DASHBOARD_COMMANDS=true`.

Allowed actions are intentionally limited: `status`, `cast-status`, `speak`, `cast-stop`, `cast-volume`, `look`, and `analyze-view`. Browser-camera snapshot/video commands use the separate `/api/jarvis/camera/*` endpoints above.

## Active Pi session count

The big room-display counter represents active Pi sessions only, not merely open idle terminals.

Active sources:

- Discord-managed active Pi RPC generations published to:

```text
.pi/runtime/pi-rpc-sessions.json
```

- local/direct Pi turns published by the Pi extension heartbeat under:

```text
.pi/runtime/local-pi-sessions/
```

- fallback local/direct Pi turns inferred from recently updated Pi session JSONL files under:

```text
~/.pi/agent/sessions/
```

Local/direct active detection prefers the extension heartbeat and falls back to a short recent-write window, default `5000` ms, configurable with `JARVIS_LOCAL_PI_ACTIVE_WINDOW_MS`. Heartbeat staleness defaults to `15000` ms and is configurable with `JARVIS_LOCAL_PI_STATUS_MAX_AGE_MS`. `/api/jarvis/display` returns the active `activeCount` / `totalSessions` plus breakdown fields such as `localActive`, `discordActiveGenerating`, `localOpen`, and `discordProcessOpen`. Open-but-idle Pi processes remain visible in the breakdown but do not increment the big counter.

The Node server watches the Discord status file and also polls once per second, then pushes `/ws` + `/api/events` `pi-sessions` updates as soon as active counts change.

## Raspberry Pi and phone status tiles

The right-side HUD cards auto-refresh every 30 seconds and can be tapped to run live health checks and controls:

- **RasPi** pings the Raspberry Pi over SSH shortly after page load, every 30 seconds, and after service toggles. It marks online only when the `jarvis-room-audio.service` health stack is good: systemd service running/enabled, client process present, `bluetooth.service` and `bluealsa.service` active, PowerConf connected, and the Mac room-audio `/health` endpoint reachable from the Pi. Reachable-but-unhealthy results show as degraded. Tapping the RasPi tile toggles the configured room-audio systemd unit with `sudo -n systemctl start|stop ...`, then polls real status briefly so `start` has time to become fully healthy before the tile settles.
- **Phone** pings the Android ADB bridge on the configured host host shortly after page load, every 30 seconds, and when tapped. It marks online only when the configured phone serial is connected as an ADB `device`.

SSH endpoints are private local configuration. Keep concrete hostnames, LAN IPs, SSH users, and aliases in ignored config such as `.env` or `.pi/ssh-hosts.json`.


Raspberry Pi configuration:

- `JARVIS_DASHBOARD_RASPBERRY_PI_SSH_HOST` / `JARVIS_RASPBERRY_PI_HOST` — local host/IP; configure in `.env`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_SSH_USER` / `JARVIS_RASPBERRY_PI_USER` — default: `pi`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_SSH_KEY` / `JARVIS_RASPBERRY_PI_SSH_KEY` — default: `~/.ssh/jarvis_dashboard_host`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_PATTERN` — process pattern to check. Default: `jarvis-room-audio-client.py`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVICE` / `JARVIS_RASPBERRY_PI_ROOM_AUDIO_SERVICE` — systemd unit to check. Default: `jarvis-room-audio.service`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVER_URL` / `JARVIS_ROOM_AUDIO_SERVER_URL` — room-audio server URL checked from the Pi. Default: configure locally, for example `http://<room-audio-host>:8791`.
- `JARVIS_DASHBOARD_RASPBERRY_PI_POWERCONF_MAC` / `JARVIS_ROOM_AUDIO_BLUETOOTH_MAC` — Bluetooth device checked with `bluetoothctl info`. Default: configure locally if Bluetooth health checks are used.

For tile toggling, the SSH user should have passwordless sudo only for the configured room-audio unit's `systemctl start` and `systemctl stop` commands, otherwise the toggle endpoint reports the sudo failure and leaves the tile grounded in the current status.

Phone ADB configuration:

- `JARVIS_DASHBOARD_PHONE_ADB_SERIAL` — target Android serial.
- `JARVIS_DASHBOARD_PHONE_ADB_PATH` — ADB path on the SSH host.
- `JARVIS_DASHBOARD_PHONE_ADB_SSH_HOST` / `JARVIS_DASHBOARD_PHONE_ADB_SSH_USER` / `JARVIS_DASHBOARD_PHONE_ADB_SSH_KEY` — SSH endpoint used for the ADB check.

## Dual oMLX HUD tiles

The top-right HUD card is now **OMLX-64** for a configured primary model host, while the existing oMLX card is labeled **OMLX-16**. Both tiles auto-refresh every 30 seconds, show online/offline/checking state, and can be tapped to SSH start/stop their configured oMLX server.

Pi session cost telemetry may still be present in `/api/jarvis/display`, but it is no longer rendered on the room display.

## Weather tile

The room display fetches current weather server-side from Open-Meteo, caches it for 10 minutes, and shows a compact temperature/condition tile above the active Pi session count. Defaults are <configured-weather-location> (`<latitude>,<longitude>`). Override with `JARVIS_DASHBOARD_WEATHER_LATITUDE`, `JARVIS_DASHBOARD_WEATHER_LONGITUDE`, `JARVIS_DASHBOARD_WEATHER_LOCATION`, `JARVIS_DASHBOARD_WEATHER_STATUS_TIMEOUT_MS`, and `JARVIS_DASHBOARD_WEATHER_STATUS_CACHE_MS`.

## oMLX status tiles

The room display checks each OpenAI-compatible oMLX `/models` endpoint server-side and shows blue/red compact HUD indicators. **OMLX-16** keeps the old defaults (`http://<private-lan-ip>:8000/v1`, SSH `<private-lan-ip>`) and can still be overridden with the unsuffixed legacy variables. **OMLX-64** defaults to `http://<private-lan-ip>:8000/v1` with SSH host `<private-lan-ip>`, SSH user `<ssh-user>`, and key `~/.ssh/jarvis_dashboard_host`.

Use suffixed overrides such as `JARVIS_DASHBOARD_OMLX_16_BASE_URL`, `JARVIS_DASHBOARD_OMLX_16_SSH_HOST`, `JARVIS_DASHBOARD_OMLX_64_BASE_URL`, and `JARVIS_DASHBOARD_OMLX_64_SSH_HOST`. Optional bearer auth can be supplied per server (`JARVIS_DASHBOARD_OMLX_64_API_KEY`) or through the shared `JARVIS_DASHBOARD_OMLX_API_KEY`, `DISCORD_VOICE_API_KEY`, or `OMLX_API_KEY`.

## Operation JARVIS event bridge

`jarvis-cli` now defaults `JARVIS_DASHBOARD_URL` to `http://127.0.0.1:8787`, so direct CLI actions emit best-effort lifecycle events to the dashboard automatically. If a dashboard write token is configured, also export it for CLI processes:

```bash
export JARVIS_DASHBOARD_TOKEN='same-local-token-if-configured'
```

Disable event emission for a process:

```bash
JARVIS_DASHBOARD_EMIT_EVENTS=0 ./jarvis-cli --json status --no-cast
```

Debug/test endpoints (`/api/refresh`, `/api/pulse`) are `POST`-only and limited to localhost by default. Set `JARVIS_ENABLE_DASHBOARD_DEBUG_ENDPOINTS=true` only if you intentionally want those endpoints available from other trusted clients.

## Documentation maintenance

This README is intentionally comprehensive but long. When adding substantial new dashboard settings, prefer moving deep configuration reference material into `docs/` and keeping this file focused on quickstart, architecture, safety, and troubleshooting links.

Existing support docs:

- [`docs/troubleshooting.md`](docs/troubleshooting.md)
- [`docs/performance-reliability-audit-2026-05-18.md`](docs/performance-reliability-audit-2026-05-18.md)

## Low-power display mode

The dashboard defaults to a low-power static alarm-clock HUD: no starfield canvas, no ambient pulse loop, no decorative CSS animations, no touch effects, no backdrop blur, and no automatic camera startup. The old `?fx=1` animated demo path is disabled so the room display stays calm. See [`docs/performance-reliability-audit-2026-05-18.md`](docs/performance-reliability-audit-2026-05-18.md) for the latest cleanup notes and follow-up backlog.

## Stable URL recommendation

Reserve the dashboard host LAN IP in the router DHCP settings, then use a stable URL such as:

```text
http://<dashboard-host>:8787
```

For public/out-of-home access, use an authenticated tunnel rather than raw router port forwarding.
