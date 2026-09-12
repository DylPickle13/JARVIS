# Rebuild JARVIS From Scratch

Updated: 2026-08-30 EDT

Use this guide for a new machine or fresh clone. It covers the repository, Pi extensions, scheduler, and optional tools. You will need your private credentials and configuration backups; Git does not contain them. Do not use the setup commands to overwrite an existing live installation.

## 0. What must be backed up separately

Git contains the code. It does **not** contain secrets or most runtime state.

Back up or be prepared to recreate:

| Data | Path / owner | Required? | Notes |
|---|---|---:|---|
| Main secrets | `.env` | Yes | Recreate from [`.env.example`](../../.env.example). Never commit. |
| Project Pi settings | `.pi/settings.json` | Yes | Machine/model choices; recreate from [`.pi/settings.example.json`](../settings.example.json) or restore a private backup. |
| Local system-prompt context | `.pi/APPEND_SYSTEM.md` | Recommended | Preferences and machine-specific operating rules; recreate from [`.pi/APPEND_SYSTEM.example.md`](../APPEND_SYSTEM.example.md). |
| Trusted SSH host allowlist | `.pi/ssh-hosts.json` | If SSH tools are used | Hostnames/IPs, usernames, key paths, and allowed directories; recreate from [`.pi/ssh-hosts.example.json`](../ssh-hosts.example.json). Never put private keys in this file. |
| Operation JARVIS secrets | `projects/operation-jarvis/.env`, `projects/operation-jarvis/smart-plug/.env`, `projects/operation-jarvis/air-purifier/.env` | If used | Can also be consolidated into root `.env` for many settings. |
| Pi auth/session provider state | `~/.pi/agent/` | Usually | Contains Pi login/auth and session history unless API keys are used. |
| Project Pi sessions | `~/.pi/agent/sessions/<project-session-dir>` | Optional but valuable | Used for direct historical lookup with baseline coding tools; record the project-specific path in `.pi/APPEND_SYSTEM.md`. |
| Durable JARVIS memory | `.pi/memory/memory.sqlite*` | Optional but valuable | Project memories; ignored by git. |
| Scheduled jobs and retained results | `.pi/scheduler/scheduler.sqlite*` | Optional but valuable | If absent, recreate jobs with the scheduler CLI or `jarvis_cron`. |
| Browser profile | `~/.pi/agent/browser-profile` or `PI_BROWSER_PROFILE_DIR` | Optional | Preserves visible-browser cookies/session state. Do not commit. |
| Google Workspace OAuth | external `gws` token/config store | If Workspace tools are used | Run `gws auth ...` if not restored. |
| Operation data artifacts | `projects/operation-jarvis/data/*` | Optional | Runtime state (greeting history, logs); ignored by git. |
| Pi attachment copies | `attachments/*` | Optional but needed for old attachment paths | Private files selected through `/attach`; ignored by git. The live staged queue is intentionally not persisted. |

## 1. Install system prerequisites

On the Mac host:

```bash
# Homebrew if needed: https://brew.sh/
brew install node python@3.13 ffmpeg git trash poppler
xcode-select --install  # if Apple command-line developer tools are not already installed
```

The project-local `/attach` picker uses `/usr/bin/swiftc` plus AppKit and compiles its private helper on first use. The attachment-enabled SSH launcher also requires OpenSSH stream-local forwarding on both Macs.

Also install/configure as needed:

- Pi CLI: [pi.dev](https://pi.dev) / `@earendil-works/pi-coding-agent`.
- `gws` CLI for Google Workspace access.
- SSH for explicitly configured remote hosts, if remote tools are used.
- Google Chrome or Chromium for the visible browser extension.
- Access to the local oMLX/OpenAI-compatible endpoints used for Pi provider setup, PDF conversion, and ASR.

Install or update Pi:

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

Authenticate with Pi's `/login` or supply the selected provider's API keys through `.env` or the shell. Pi RPC needs a working `pi` command on `PATH` when run from this repository.

## 2. Clone the repo

Use any local working path; this document uses `/path/to/JARVIS` as a placeholder:

```bash
mkdir -p /path/to
cd /path/to
git clone <REPO_URL> JARVIS
cd /path/to/JARVIS
```

If you use a different path, update path-sensitive values in `.env`, `.pi/settings.json`, the native `jarvisd` launchd plists, and any SSH/watchdog scripts.

## 3. Restore configuration

```bash
cd /path/to/JARVIS
install -m 600 .env.example .env
install -m 600 .pi/settings.example.json .pi/settings.json
install -m 600 .pi/APPEND_SYSTEM.example.md .pi/APPEND_SYSTEM.md
install -m 600 .pi/ssh-hosts.example.json .pi/ssh-hosts.json
install -d -m 700 .pi/runtime .pi/memory .pi/scheduler
```

Customize these ignored local files before starting Pi:

- `.env`: restore secrets from the private secret store.
- `.pi/settings.json`: replace placeholder provider/model values while retaining the pinned package source.
- `.pi/APPEND_SYSTEM.md`: restore preferred address, timezone, aliases, local operating rules, and the project-specific Pi session JSONL directory for direct historical lookup.
- `.pi/ssh-hosts.json`: replace example hosts with only explicitly trusted machines and narrow allowed directory prefixes.

If you have private backups, restore those instead of copying templates. Set the four local files to `chmod 600` and the private directories to `chmod 700`. Keep them out of Git. The templates contain placeholders; fill in your own host addresses, usernames, key locations, device aliases, and preferences.

`.pi/extensions/00-private-permissions.ts` reapplies these owner-only modes whenever Pi starts, including mode `0700` on `attachments/` and mode `0600` on loose attachment files. The memory and scheduler runners also enforce mode `0600` on their SQLite databases and sidecars, with mode `0700` on their default data directories.

Minimum root `.env` for basic local Pi operation:

- `PI_CODING_AGENT_COMMAND`
- `JARVIS_PI_MODEL`
- any provider/API-key settings required by the selected Pi model

Then fill subsystem settings as needed:

- Web/search: optional `EXA_API_KEY`; optional `YOUTUBE_API_KEY` or `GOOGLE_API_KEY` for `web_search` YouTube metadata/search
- Maps: `GOOGLE_MAPS_API_KEY` plus optional `GOOGLE_MAPS_DEFAULT_*` and `GOOGLE_MAPS_HOME_ADDRESS`
- oMLX/PDF/voice: `OMLX_API_KEY`, `OMLX_64_BASE_URL`, optional `OMLX_PDF_*`, `JARVIS_VOICE_*`
- Scheduler: `JARVIS_SCHEDULER_*`; leave `JARVIS_APNS_ENABLED=0` until paid enrollment and the Watch-only push activation procedure are complete
- Browser: optional `PI_BROWSER_CHROME_PATH`, `PI_BROWSER_PROFILE_DIR`, `PI_BROWSER_KEEP_OPEN_ON_SHUTDOWN`
- Operation JARVIS: `JARVISD_*`, `JARVIS_API_TOKEN`, `JARVIS_EMIT_EVENTS`, `SPOTIFY_*`, `KASA_*`, `VESYNC_*`, `JARVIS_AIR_PURIFIER_*`
- Native Apple clients: `jarvis-app/` uses `jarvisd` discovery and endpoint settings; no client secrets are stored in the app bundle.

Never commit `.env` or copied secret files.

## 4. Install Python dependencies

Root runtime environment (Python 3.13+ is required; 3.13 is the tested/recommended runtime):

```bash
cd /path/to/JARVIS
python3.13 -m venv .venv
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

## 5. Install Node/browser dependencies

Visible-browser extension dependencies:

```bash
cd /path/to/JARVIS/.pi/extensions/50-browser
npm install
```

Shared extension runtime dependencies (currently `node-pty` for interactive SSH terminals; `/attach` itself uses only Node built-ins and Pi's image utilities):

```bash
cd /path/to/JARVIS/.pi/extensions/lib
npm install
```

## 6. Reinstall Pi packages/extensions

The private package configuration is `.pi/settings.json`; start from [`.pi/settings.example.json`](../settings.example.json) if needed. Both pin the reviewed `pi-web-access` release and enable its stock extension directly. The former JARVIS wrapper is archived outside extension discovery in `.pi/disabled-extensions/00-web-access-env.ts.disabled`. Reinstall the pinned version:

```bash
cd /path/to/JARVIS
pi install -l npm:pi-web-access@0.28.0
pi list
```

Expected project package source and installed version:

```text
npm:pi-web-access@0.28.0
pi-web-access@0.28.0
```

Keep the exact version, not a range or unversioned package. Do not add `"extensions": []` to this package: that disables its stock extension. Pi packages have full system access, so review upgrades before changing the pin in both settings files.

Web access now uses upstream defaults and its ordinary configuration lookup (normally `~/.pi/web-search.json`, with upstream environment/XDG overrides). The former scoped config is archived as `.pi/runtime/pi-web-access/web-search.json.disabled` and is not used. The wrapper's `.env` credential loading, forced routing/workflows, and notification filtering no longer apply. Restart Pi after migration to clear cached modules and wrapper mutations.

## 7. Restore optional runtime databases

If you have backups, restore them now before smoke tests:

```bash
# Examples only; adjust backup paths.
cp /backup/JARVIS/.pi/memory/memory.sqlite* .pi/memory/ 2>/dev/null || true
cp /backup/JARVIS/.pi/scheduler/scheduler.sqlite* .pi/scheduler/ 2>/dev/null || true
# Optional browser profile restore, if backed up:
# rsync -a /backup/pi-browser-profile/ ~/.pi/agent/browser-profile/
```

If you restored old Pi session JSONL files, record their project-specific directory in `.pi/APPEND_SYSTEM.md` so baseline coding tools can search them directly.

## 8. Smoke-test the extension/tool stack

Start with the read-only smoke test:

```bash
cd /path/to/JARVIS
.pi/smoke-test.sh
```

It checks files, installed packages, commands and CLI `--help`, environment key names, runtime-data presence, and documentation links. It does not start services, call models or oMLX/Google APIs, launch Chrome, touch Apple devices, control Cast/Spotify/Kasa, or open SQLite status commands that could create databases.

For more detail, these status commands open the local SQLite-backed runners:

```bash
cd /path/to/JARVIS
pi list
.venv/bin/python .pi/memory/memory.py --json status
.venv/bin/python .pi/scheduler/runner.py --json status
```

Operation JARVIS safe checks:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json help
./jarvis-cli --json status --no-cast
./jarvis-cli --json purifier-status
```

Native daemon health check (only when `jarvisd` is intentionally running):

```bash
curl -fsS http://127.0.0.1:8790/health | python3 -m json.tool
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

A simple Pi session should show baseline tools plus `load_tools`. Inside Pi, check:

```text
/lazy-tools
/load-tools memory,browser
/reset-tools
```

The project also exposes exactly one parameterless attachment command:

```text
/attach
```

On the local Mac, `/attach` opens the native file picker. From another Mac, connect with `.pi/scripts/jarvis-pi-ssh <host>` from a JARVIS checkout before starting Pi. Plain SSH cannot open a picker on the client computer.

Selected files go into ignored `attachments/` with owner-only permissions. The unsent queue stays in memory and clears when Pi exits. To test without opening a picker:

```bash
node --test .pi/scripts/tests/pi-attach-*.test.mjs .pi/scripts/tests/jarvis-pi-ssh.test.mjs
/usr/bin/swiftc -typecheck -framework AppKit .pi/scripts/pi-attach-picker.swift
```

## 9. Recreate private scheduled jobs

If `.pi/scheduler/scheduler.sqlite*` was restored, check status:

```bash
.venv/bin/python .pi/scheduler/runner.py --json status
.venv/bin/python .pi/scheduler/runner.py --json list
```

Add jobs either through the Pi tool (`load_tools({ groups: ["cron"] })`) or directly:

```bash
.venv/bin/python .pi/scheduler/runner.py --json add \
  --name example-job \
  --schedule '+5m' \
  --prompt 'Say hello from the rebuilt scheduler.'
```

On macOS, install the one-minute launchd runner explicitly:

```bash
.venv/bin/python .pi/scheduler/runner.py --json install
```

The owner-only database keeps up to 500 sanitized results from successes with output and from failures. A successful check with no output updates job health without adding an inbox item.

## 10. Post-rebuild verification checklist

- [ ] `pi --version` works.
- [ ] `pi list` shows `pi-web-access`.
- [ ] `ffmpeg -version` and `pdftotext -v` work.
- [ ] Browser extension dependencies exist under `.pi/extensions/50-browser/node_modules`.
- [ ] `.env`, `.pi/settings.json`, `.pi/APPEND_SYSTEM.md`, and `.pi/ssh-hosts.json` were privately restored or created from their tracked templates.
- [ ] All four local files remain ignored by git and have mode `0600`.
- [ ] `.pi/runtime`, `.pi/memory`, and `.pi/scheduler` have mode `0700`; private databases and sidecars have mode `0600`.
- [ ] `.pi/settings.json` retains `npm:pi-web-access@0.28.0`; `pi list` and the installed package metadata agree.
- [ ] `/lazy-tools` works in Pi.
- [ ] `memory.py --json status` works.
- [ ] The Pi session JSONL directory recorded in `.pi/APPEND_SYSTEM.md` exists and can be searched with baseline coding tools.
- [ ] `.pi/scheduler/runner.py --json status` reports the expected private jobs.
- [ ] `jarvis-cli --json status --no-cast` works.
- [ ] `jarvisd` starts and answers `/health`; native app verification passes.
- [ ] `gws --help` and `google_workspace` work if Workspace access is needed.
- [ ] `maps({ query: "status" })` works if Maps access is needed.
- [ ] Browser tools load with `/load-tools browser`; `browser_open` is used only when launching Chrome is intended.
- [ ] Phone control is still guarded by explicit permission/authentication before use in shared sessions.

## 11. Troubleshooting quick map

| Symptom | First check |
|---|---|
| Pi does not see custom tools | Run `pi list`, then `/reload`; verify files under `.pi/extensions/`, `.pi/extensions/50-browser/node_modules`, and package installs under `.pi/npm/node_modules/`. |
| Optional tool hidden | Call `load_tools({ groups: ["<group>"] })` or `/load-tools <group>`. For automatic direct-call activation, build/install the [version-pinned lazy-execution runtime](PI_LAZY_EXECUTION.md). |
| Web search unavailable | Check stock pi-web-access package loading, provider availability, and upstream configuration (normally `~/.pi/web-search.json`). The custom `/web-access-config` command is retired. |
| Maps unavailable | Check `GOOGLE_MAPS_API_KEY`; confirm Places API (New), Geocoding API, and Routes API are enabled for the key. |
| Browser tools unavailable | Run `npm install` in `.pi/extensions/50-browser`; check Google Chrome path or set `PI_BROWSER_CHROME_PATH`. |
| PDF reads fail | Check local oMLX `OMLX_PDF_*` settings first; ensure `pdftotext` from `poppler` is installed for fallback. |
| Scheduled jobs unavailable | Check `.pi/scheduler/scheduler.sqlite`, owner-only permissions, `com.jarvis.pi-scheduler`, and `runner.py --json status`. |
| Prior-session lookup fails | Verify the project-specific session JSONL directory in `.pi/APPEND_SYSTEM.md`; use `rg -l` to shortlist files before parsing matching records. |
| Memory unavailable | Load the `memory` group, run `memory` with `action: "status"`, and verify `.pi/memory/memory.sqlite`; automatic prompt-time recall is intentionally disabled. |
| `jarvis` tool fails | Run `projects/operation-jarvis/jarvis-cli --json help`; check the Operation venv, Cast, Spotify, Kasa, purifier, and `jarvisd` configuration as appropriate. |

Keep this file and [`PI_EXTENSIONS.md`](PI_EXTENSIONS.md) updated whenever a tool, env var, runtime DB, or package changes.
