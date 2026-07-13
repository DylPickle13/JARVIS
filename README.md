# JARVIS

JARVIS is a Discord-facing control layer for the [Pi coding agent](https://github.com/earendil-works/pi-coding-agent) and a local “Operation JARVIS” room stack. The main bot process handles Discord text chat, live voice, attachments, and persistent Pi RPC sessions. The repository also provides scheduled jobs, memory/session search, and local tools for a dashboard, browser automation, phone status, Cast/Spotify media, smart plugs, the Levoit air purifier, and room audio.

The repository is public by design, but it expects private local configuration. Secrets, device mappings, LAN hosts, SSH targets, runtime databases, generated media, and personal prompt overrides belong in ignored files such as `.env`, `.pi/APPEND_SYSTEM.md`, `.pi/ssh-hosts.json`, and Operation JARVIS hardware config files.

This root README is a map and quick-start guide. Detailed subsystem notes live in the linked project READMEs below.

## What’s Included

- **Discord bot** — [`discord_bot.py`](discord_bot.py) runs a `discord.py` client for configured text channels and the `jarvis` voice channel text chat. It streams Pi output back into Discord, handles busy/cancel states, slash commands, attachments, voice-message transcription, and live voice integration.
- **Pi RPC sessions** — [`llm.py`](llm.py) keeps persistent per-channel `pi --mode rpc` sessions with model/thinking controls, steering, cancellation, session deletion, manual compaction, and dashboard status publishing.
- **Inputs** — text prompts, saved file attachments, native image attachments, and Discord mobile voice messages transcribed through an OpenAI-compatible oMLX Whisper endpoint.
- **Live voice** — [`projects/operation-jarvis/voice/`](projects/operation-jarvis/voice/) is loaded by the main bot: Discord PCM → openWakeWord → oMLX Whisper ASR → Pi RPC → Piper JARVIS TTS → Discord playback.
- **Pi extensions** — [`.pi/extensions/`](.pi/extensions/) provides web/search helpers, lazy tool loading, memory, session search, Discord cron/ping/file upload tools, browser/phone/Google/Maps/YouTube integrations, and Operation JARVIS tools.
- **Operation JARVIS** — [`projects/operation-jarvis/`](projects/operation-jarvis/) contains the room-facing stack: LAN dashboard, phone-camera vision, Cast/Spotify media, TP-Link Kasa smart plugs, Levoit/VeSync air-purifier control, and Raspberry Pi room audio.
- **Runtime data** — `.env`, attachments, generated media/data, SQLite indexes, logs, cron runs, and Pi runtime status files are ignored by git.

## Public/Private Configuration Model

Tracked files provide generic defaults and placeholders. Local deployments should copy [`.env.example`](.env.example)—the primary template for common deployment settings—to `.env` and fill in only local values there. Advanced subsystem settings may retain safe source defaults or be documented in the relevant project README. Private files intentionally ignored by git include:

- `.env` and environment-specific `.env.*` files.
- `.pi/APPEND_SYSTEM.md` for private assistant persona/location/device guidance.
- `.pi/ssh-hosts.json` for trusted SSH host aliases.
- `projects/operation-jarvis/smart-plug/plugs.json` for local plug aliases and IPs.
- Runtime folders for attachments, media captures, SQLite indexes, logs, Pi sessions, and scheduled-job runs.

## Repository Map

| Path | Purpose |
|---|---|
| [`discord_bot.py`](discord_bot.py) | Main Discord bot: text channels, slash commands, attachments, voice-message ASR, live voice wiring. |
| [`llm.py`](llm.py) | Pi CLI/RPC process management and persistent Discord channel sessions. |
| [`config.py`](config.py), [`api_backoff.py`](api_backoff.py) | Shared environment, logging, paths, and retry helpers. |
| [`.env.example`](.env.example) | Primary tracked configuration template. Copy to `.env`; never commit secrets. |
| [`.pi/docs/`](.pi/docs/) | Cold-rebuild and Pi extension/tool documentation. |
| [`.pi/extensions/`](.pi/extensions/) | Project Pi extensions and lazy tool groups. |
| [`.pi/memory/`](.pi/memory/) | SQLite-backed project memory runner. |
| [`.pi/session-search/`](.pi/session-search/) | Semantic search over prior Pi/JARVIS sessions. |
| [`.pi/discord-cron/`](.pi/discord-cron/) | Independent scheduled Pi jobs that post results to Discord. |
| [`projects/operation-jarvis/`](projects/operation-jarvis/) | Dashboard, voice, room audio, Cast/media, camera vision, and smart-plug subsystems. |
| `attachments/` | Runtime Discord attachment storage, created locally and ignored by git. |

## Quick Start

Requirements:

- Python 3.13+; Python 3.13 is the tested/recommended runtime for the current voice dependency pins
- Pi CLI on `PATH`
- Discord bot token with Message Content and Voice States intents enabled
- oMLX/OpenAI-compatible endpoints for voice ASR, local models, and embeddings as configured
- `ffmpeg` for Discord voice playback
- Node.js 20+ for the dashboard

```bash
cd /path/to/JARVIS
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
# edit .env with local tokens, model endpoints, and device settings
.pi/smoke-test.sh  # read-only/local; does not start services or touch hardware
python discord_bot.py
```

The root [`requirements.txt`](requirements.txt) intentionally lists direct dependencies for the main bot and its loaded live-voice module; pip resolves their transitive packages. Operation JARVIS Cast, smart-plug, and purifier components use the dedicated environments documented in the subsystem READMEs.

Run the dashboard separately when needed:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm install
npm start
```

Operation JARVIS local smoke check:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json status --no-cast
```

## Configuration

Common deployment configuration lives in `.env`; [`.env.example`](.env.example) is the tracked template. Advanced tuning knobs may use source defaults and are documented with their subsystem. Main groups:

- **Discord** — bot token, target channels, stream throttles, attachment caps, auto-thread members, voice-message ASR, and live voice channel.
- **Pi/model** — Pi command, workdir, RPC timeout, default text model, voice model override, thinking level, and `/jarvis model` options.
- **Voice/oMLX/TTS** — ASR endpoint/model, wake-word gates, Piper voice settings, TTS streaming, and idle session refresh.
- **Dashboard/room hardware** — dashboard URL, camera vision model, Raspberry Pi room-audio status, Android phone ADB status, and room-audio tuning.
- **Local SSH machines (private)** — configure trusted SSH aliases locally with ignored `.pi/ssh-hosts.json` or `JARVIS_SSH_*` environment variables. The `ssh` tool supports unrestricted captured commands, directly attached local-TUI terminals, and stateful Discord/RPC PTY sessions. See [`.pi/docs/PI_EXTENSIONS.md`](.pi/docs/PI_EXTENSIONS.md).
- **Tools** — Exa-backed web access, Google/YouTube APIs, memory, session search embeddings, Discord cron/ping/file upload, and Kasa smart-plug credentials.

## Discord Usage

Slash commands are grouped under `/jarvis` in configured text channels and the configured voice channel text chat:

- `/jarvis new` — start a fresh Pi session for the channel.
- `/jarvis delete` — delete the current saved Pi session for the channel.
- `/jarvis cancel` — abort active work in the channel.
- `/jarvis model` — show model controls, quota refresh, and model-selection buttons.
- `/jarvis thinking [level]` — show or change the channel thinking level.
- `/jarvis compact [instructions]` — compact the current channel session.
- `/jarvis restart` — safely restart the bot after checking for active work.

Legacy `>` control commands are not registered.

## Pi Tool Surface

Baseline tools include local coding/file helpers plus `ssh`, `web_search`, `fetch_content`, `get_search_content`, `minecraft_jarvis`, `maps`, `github_cli`, and `load_tools`. Optional groups are loaded on demand with `load_tools({ groups: [...] })`:

`memory`, `code_docs`, `image`, `video`, `jarvis`, `phone`, `google`, `cron`, `discord`, `sessions`, `browser`, `reaper`, `gx10`, or `all`.

`minecraft_jarvis` is already always on; its compatibility group remains accepted but does not need to be loaded.

YouTube metadata/search uses the always-on `web_search` tool with `provider: "youtube"`; it is not a `load_tools` group.

Use `image`/`video` for local media generation through `mac-mini-64:/Users/dylanrapanan/media-generation`; video uses local LTX-2.3 Q8 MLX and produces MP4s with synchronized audio. Generated files copy back to ignored `generated-images/` and `generated-videos/`. In the `gx10` group, use `gx10_get` for ordinary read-only live-patch questions, `gx10_find` for semantic discovery, and `gx10_lua` for custom reads or edits. Semantic edits require an RQ1-only `gx.plan_edit` dry run, exact plan-ID approval, and `tx:apply_plan` in a verified transaction on mac-mini-16, without depending on REAPER. Use the Discord-specific tools for their narrow jobs: `discord_cron` for scheduled jobs, `discord_ping` for immediate user-facing pings/notifications and attachments, and `discord_send_file` only for verified local uploads to the current Discord channel.

## Safety Notes

- Keep `.env` and ignored hardware config files private.
- Do not run duplicate Discord bot processes with the same token.
- The provided smoke test is read-only/local and avoids hardware actions.
- Tools that touch external services, browser sessions, SSH hosts, smart plugs, the air purifier, Cast devices, or Discord channels are intended to stay explicit and bounded.

## Deeper Docs

- [Pi extensions and tool surface](.pi/docs/PI_EXTENSIONS.md)
- [Rebuild JARVIS from scratch](.pi/docs/REBUILD_FROM_SCRATCH.md)
- [Operation JARVIS overview](projects/operation-jarvis/README.md)
- [Dashboard](projects/operation-jarvis/dashboard/README.md)
- [Live Discord voice](projects/operation-jarvis/voice/README.md)
- [Raspberry Pi endpoint](projects/operation-jarvis/raspberry-pi/README.md)
- [Raspberry Pi room audio](projects/operation-jarvis/raspberry-pi/room_audio/README.md)
- [Smart plugs](projects/operation-jarvis/smart-plug/README.md)
- [Air purifier](projects/operation-jarvis/air-purifier/README.md)

Do not run the standalone voice bot with the same Discord token while the main bot is running; the main bot already owns the voice subsystem.

## License

This project is released under the [MIT License](LICENSE).
