# Rebuild JARVIS From Scratch

Updated: 2026-06-24 EDT

This runbook rebuilds the JARVIS repo, Pi extensions, Discord bot, and local tool surface from a fresh machine or fresh clone. It assumes you have access to the private secrets that are intentionally not stored in git.

## 0. What must be backed up separately

Git contains the code. It does **not** contain secrets or most runtime state.

Back up or be prepared to recreate:

| Data | Path / owner | Required? | Notes |
|---|---|---:|---|
| Main secrets | `.env` | Yes | Recreate from [`.env.example`](../../.env.example). Never commit. |
| Operation JARVIS secrets | `projects/operation-jarvis/.env`, `projects/operation-jarvis/smart-plug/.env`, `projects/operation-jarvis/air-purifier/.env` | If used | Can also be consolidated into root `.env` for many settings. |
| Pi auth/session provider state | `~/.pi/agent/` | Usually | Contains Pi login/auth and session history unless API keys are used. |
| Project Pi sessions | `~/.pi/agent/sessions/<project-session-dir>` | Optional | Needed for historical session continuity. |
| Durable JARVIS memory | `.pi/memory/memory.sqlite*` | Optional but valuable | Project memories; ignored by git. |
| Discord scheduled jobs | `.pi/discord-cron/discord-cron.sqlite*` | Optional but valuable | If absent, recreate jobs via `discord_cron add`. |
| Session-search index | `.pi/session-search/index.sqlite*` | No | Can be rebuilt from session files. |
| Browser profile | `~/.pi/agent/browser-profile` or `PI_BROWSER_PROFILE_DIR` | Optional | Preserves visible-browser cookies/session state. Do not commit. |
| Google Workspace OAuth | external `gws` token/config store | If Workspace tools are used | Run `gws auth ...` if not restored. |
| Phone/ADB host SSH keys | `~/.ssh/...` and configured ADB host config | If phone/dashboard status is used | See [`projects/phone/README.md`](../../projects/phone/README.md). |
| Operation media/data artifacts | `projects/operation-jarvis/data/*`, `projects/operation-jarvis/media/*` | Optional | Captures, TTS files, runtime state; ignored by git. |

## 1. Install system prerequisites

On the Mac host:

```bash
# Homebrew if needed: https://brew.sh/
brew install node python ffmpeg git trash poppler
```

Also install/configure as needed:

- Pi CLI: [pi.dev](https://pi.dev) / `@earendil-works/pi-coding-agent`.
- `gws` CLI for Google Workspace access.
- Android platform-tools, SSH, and optional `scrcpy` for the phone stack.
- Google Chrome or Chromium for the visible browser extension.
- Access to the local oMLX/OpenAI-compatible endpoints used for Pi provider setup, PDF conversion, ASR, vision, and embeddings.

Install or update Pi:

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

Authenticate Pi with `/login` or provide API keys in `.env`/shell. For Discord/Pi RPC operation, the important setting is that the `pi` command on `PATH` works from this repo.

## 2. Clone the repo

Use any local working path; this document uses `/path/to/JARVIS` as a placeholder:

```bash
mkdir -p /path/to
cd /path/to
git clone <REPO_URL> JARVIS
cd /path/to/JARVIS
```

If you use a different path, update path-sensitive values in `.env`, `.pi/settings.json`, launchd plists, dashboard service files, and any SSH/watchdog scripts.

## 3. Restore configuration

```bash
cd /path/to/JARVIS
cp .env.example .env
# Fill .env from the private secret store.
```

Minimum root `.env` for basic Discord/Pi operation:

- `DISCORD_BOT_TOKEN`
- `PI_CODING_AGENT_COMMAND`
- `DISCORD_PI_MODEL`
- any provider/API-key settings required by the selected Pi model

Then fill subsystem settings as needed:

- Web/search: optional `EXA_API_KEY`; optional `YOUTUBE_API_KEY` or `GOOGLE_API_KEY` for `web_search` YouTube metadata/search
- Maps: `GOOGLE_MAPS_API_KEY` plus optional `GOOGLE_MAPS_DEFAULT_*` and `GOOGLE_MAPS_HOME_ADDRESS`
- oMLX/PDF/voice/vision/embeddings: `OMLX_API_KEY`, `OMLX_64_BASE_URL`, optional `OMLX_PDF_*`, `DISCORD_VOICE_*`, `SESSION_SEARCH_*`, `JARVIS_DASHBOARD_CAMERA_*`
- Discord helpers: `DISCORD_CRON_*`, `DISCORD_PING_*`, `JARVIS_DISCORD_SEND_FILE_MAX_BYTES`
- Browser: optional `PI_BROWSER_CHROME_PATH`, `PI_BROWSER_PROFILE_DIR`, `PI_BROWSER_KEEP_OPEN_ON_SHUTDOWN`
- Operation JARVIS: `JARVIS_DASHBOARD_*`, `SPOTIFY_*`, `KASA_*`, `VESYNC_*`, `JARVIS_AIR_PURIFIER_*`
- Phone/dashboard status: `JARVIS_DASHBOARD_PHONE_*`

Never commit `.env` or copied secret files.

## 4. Install Python dependencies

Root bot environment:

```bash
cd /path/to/JARVIS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Operation JARVIS environment:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Smart-plug environment, if local TP-Link/Kasa control is needed:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/smart-plug
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -e .
```

## 5. Install Node/dashboard/browser dependencies

Dashboard dependencies:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm install
```

Visible-browser extension dependencies:

```bash
cd /path/to/JARVIS/.pi/extensions/50-browser
npm install
```

Shared extension runtime dependencies (currently `node-pty` for interactive SSH terminals):

```bash
cd /path/to/JARVIS/.pi/extensions/lib
npm install
```

Start the dashboard manually:

```bash
npm start
```

Optional login service:

```bash
npm run install-service
```

## 6. Reinstall Pi packages/extensions

Project package config lives in [`.pi/settings.json`](../settings.json). Reinstall the local Pi packages:

```bash
cd /path/to/JARVIS
pi install -l npm:pi-web-access
pi list
```

Expected project packages:

```text
npm:pi-web-access
```

Current observed versions on this machine when this runbook was written:

```text
pi-web-access@0.12.0
```

For exact reproducibility, pin package versions in `.pi/settings.json` or reinstall with explicit npm versions. For ordinary maintenance, the unpinned package names allow updates.

## 7. Restore optional runtime databases

If you have backups, restore them now before smoke tests:

```bash
# Examples only; adjust backup paths.
cp /backup/JARVIS/.pi/memory/memory.sqlite* .pi/memory/ 2>/dev/null || true
cp /backup/JARVIS/.pi/discord-cron/discord-cron.sqlite* .pi/discord-cron/ 2>/dev/null || true
cp /backup/JARVIS/.pi/session-search/index.sqlite* .pi/session-search/ 2>/dev/null || true
# Optional browser profile restore, if backed up:
# rsync -a /backup/pi-browser-profile/ ~/.pi/agent/browser-profile/
```

If you restored old Pi session JSONL files, rebuild session search later with:

```bash
/path/to/JARVIS/.venv/bin/python .pi/session-search/session_search.py --json index
```

## 8. Smoke-test the extension/tool stack

Run the one-command, non-mutating smoke test first:

```bash
cd /path/to/JARVIS
.pi/smoke-test.sh
```

That script is intentionally read-only: it checks files, local package installs, command availability, CLI `--help` paths, env key names, runtime-data presence, and doc links. It does **not** start services, call LLMs, post to Discord, launch Chrome, touch the phone, control Cast/Spotify/Kasa, call dashboard/oMLX/Google APIs, or open SQLite status commands that could initialize databases.

Deeper local status checks, if you intentionally want to open/read the local SQLite-backed runners:

```bash
cd /path/to/JARVIS
pi list
.venv/bin/python .pi/memory/memory.py --json status
.venv/bin/python .pi/session-search/session_search.py --json status
.venv/bin/python .pi/discord-cron/runner.py --json status
```

Operation JARVIS safe checks:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json purifier-status
```

Dashboard check:

```bash
curl -s http://127.0.0.1:8787/api/jarvis/status | python3 -m json.tool
```

Browser automation checks:

```bash
# Read-only install/presence checks; does not launch Chrome.
test -f .pi/extensions/50-browser/index.ts
test -d .pi/extensions/50-browser/node_modules
```

Inside Pi, only when you intentionally want to launch/control the visible browser:

```text
/load-tools browser
browser_status({})
browser_open({ url: "about:blank" })
browser_close({})
```

PDF fallback check:

```bash
pdftotext -v
```

Google Workspace check, if installed:

```bash
gws --help
```

Maps check, if `GOOGLE_MAPS_API_KEY` is configured:

```text
maps({ query: "status" })
```

Phone check, only after explicit permission/authentication:

```bash
cd /path/to/JARVIS
projects/phone/agent-phone --json status
```

A simple Pi session should show baseline tools plus `load_tools`. Inside Pi, check:

```text
/lazy-tools
/load-tools memory,sessions,browser
/reset-tools
```

## 9. Recreate Discord scheduled jobs

If `.pi/discord-cron/discord-cron.sqlite*` was restored, check status:

```bash
.venv/bin/python .pi/discord-cron/runner.py --json status
.venv/bin/python .pi/discord-cron/runner.py --json list
```

If not restored, set up Discord output and scheduler:

```bash
.venv/bin/python .pi/discord-cron/runner.py --json setup
```

Add jobs either through the Pi tool (`load_tools({ groups: ["cron"] })`) or directly:

```bash
.venv/bin/python .pi/discord-cron/runner.py --json add \
  --name example-job \
  --schedule '+5m' \
  --prompt 'Say hello from the rebuilt scheduler.'
```

On macOS, `setup` installs a launchd job at:

```text
~/Library/LaunchAgents/com.jarvis.pi-discord-cron.plist
```

## 10. Run the main Discord bot

```bash
cd /path/to/JARVIS
source .venv/bin/activate
python discord_bot.py
```

Do not run another bot process with the same token at the same time. The root bot owns text channels, Pi RPC sessions, scheduled interaction surfaces, and live Discord voice.

## 11. Post-rebuild verification checklist

- [ ] `pi --version` works.
- [ ] `pi list` shows `pi-web-access`.
- [ ] `ffmpeg -version` and `pdftotext -v` work.
- [ ] Browser extension dependencies exist under `.pi/extensions/50-browser/node_modules`.
- [ ] Root `.venv` imports `discord.py` and runs `python discord_bot.py`.
- [ ] `.env` exists locally and is not tracked by git.
- [ ] `/lazy-tools` works in Pi.
- [ ] `memory.py --json status` works.
- [ ] `session_search.py --json status` works; `index` works if embedding endpoint is available.
- [ ] `runner.py --json status` works for Discord cron.
- [ ] `jarvis-cli --json status --no-cast` works.
- [ ] Dashboard starts and answers `/api/jarvis/status`.
- [ ] `gws --help` and `google_workspace` work if Workspace access is needed.
- [ ] `maps({ query: "status" })` works if Maps access is needed.
- [ ] Browser tools load with `/load-tools browser`; `browser_open` is used only when launching Chrome is intended.
- [ ] Phone control is still guarded by explicit permission/authentication before use in shared sessions.

## 12. Troubleshooting quick map

| Symptom | First check |
|---|---|
| Pi does not see custom tools | Run `pi list`, then `/reload`; verify files under `.pi/extensions/`, `.pi/extensions/50-browser/node_modules`, and package installs under `.pi/npm/node_modules/`. |
| Optional tool hidden | Call `load_tools({ groups: ["<group>"] })` or `/load-tools <group>`. |
| Web search unavailable | Run `/web-access-config`; check Exa MCP/package availability, optional `EXA_API_KEY`, and `~/.pi/web-search.json`. |
| Maps unavailable | Check `GOOGLE_MAPS_API_KEY`; confirm Places API (New), Geocoding API, and Routes API are enabled for the key. |
| Browser tools unavailable | Run `npm install` in `.pi/extensions/50-browser`; check Google Chrome path or set `PI_BROWSER_CHROME_PATH`. |
| PDF reads fail | Check local oMLX `OMLX_PDF_*` settings first; ensure `pdftotext` from `poppler` is installed for fallback. |
| Discord cron cannot post | Check `DISCORD_BOT_TOKEN`, guild/channel IDs, bot permissions, and `runner.py --json setup`. |
| Session search fails | `status` first; then verify embedding endpoint/model and `SESSION_SEARCH_*` env vars. |
| Memory recall absent | Check `JARVIS_MEMORY_AUTO_RECALL`, memory DB status, and whether relevant memories exist. |
| `jarvis` tool fails | Run `projects/operation-jarvis/jarvis-cli --json help`; check Operation venv, dashboard, Cast, Spotify, Kasa env as appropriate. |
| Phone unavailable | Do not use raw ADB by default. Check `projects/phone/README.md`, the configured ADB host, and permission/authentication status. |

Keep this file and [`PI_EXTENSIONS.md`](PI_EXTENSIONS.md) updated whenever a tool, env var, runtime DB, or package changes.
