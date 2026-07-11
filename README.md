# JARVIS

JARVIS is a Discord-facing control layer for the [Pi coding agent](https://github.com/earendil-works/pi-coding-agent) and a local “Operation JARVIS” room stack. One main bot process handles Discord text chat, voice, attachments, Pi RPC sessions, scheduled jobs, memory/session search, and local tools for a dashboard, browser automation, phone status, Cast/Spotify media, smart plugs, the Levoit air purifier, and room audio.

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

Tracked files provide generic defaults and placeholders. Local deployments should copy [`.env.example`](.env.example) to `.env` and fill in only local values there. Private files intentionally ignored by git include:

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
| [`.env.example`](.env.example) | Full configuration template. Copy to `.env`; never commit secrets. |
| [`.pi/docs/`](.pi/docs/) | Cold-rebuild and Pi extension/tool documentation. |
| [`.pi/extensions/`](.pi/extensions/) | Project Pi extensions and lazy tool groups. |
| [`.pi/memory/`](.pi/memory/) | SQLite-backed project memory runner. |
| [`.pi/session-search/`](.pi/session-search/) | Semantic search over prior Pi/JARVIS sessions. |
| [`.pi/discord-cron/`](.pi/discord-cron/) | Independent scheduled Pi jobs that post results to Discord. |
| [`projects/operation-jarvis/`](projects/operation-jarvis/) | Dashboard, voice, room audio, Cast/media, camera vision, and smart-plug subsystems. |
| [`attachments/`](attachments/) | Runtime Discord attachment storage, ignored by git. |

## Quick Start

Requirements:

- Python 3.10+
- Pi CLI on `PATH`
- Discord bot token with Message Content and Voice States intents enabled
- oMLX/OpenAI-compatible endpoints for voice ASR, local models, and embeddings as configured
- `ffmpeg` for Discord voice playback
- Node.js for the dashboard

```bash
cd /path/to/JARVIS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with local tokens, model endpoints, and device settings
.pi/smoke-test.sh  # read-only/local; does not start services or touch hardware
python discord_bot.py
```

Run the dashboard separately when needed:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm start
```

Operation JARVIS local smoke check:

```bash
cd /path/to/JARVIS/projects/operation-jarvis
./jarvis-cli --json status --no-cast
```

## Configuration

All normal configuration lives in `.env`; [`.env.example`](.env.example) is the source of truth for available settings. Main groups:

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

Baseline tools stay small: local file/shell helpers, web search/content fetching, and `load_tools`. Optional groups are loaded on demand with `load_tools({ groups: [...] })`:

`memory`, `code_docs`, `image`, `video`, `jarvis`, `phone`, `google`, `cron`, `discord`, `sessions`, `browser`, or `all`.

YouTube metadata/search uses the always-on `web_search` tool with `provider: "youtube"`; it is not a `load_tools` group.

Use `image`/`video` for local media generation through `mac-mini-64:/Users/dylanrapanan/media-generation`; video uses local LTX-2.3 Q8 MLX and produces MP4s with synchronized audio. Generated files copy back to ignored `generated-images/` and `generated-videos/`. Use the Discord-specific tools for their narrow jobs: `discord_cron` for scheduled jobs, `discord_ping` for immediate user-facing pings/notifications and attachments, and `discord_send_file` only for verified local uploads to the current Discord channel.

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
