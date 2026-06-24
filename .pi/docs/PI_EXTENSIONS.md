# Pi Extensions

Updated: 2026-06-24 EDT

The local Pi extension inventory lives in `.pi/extensions/`. `.pi/smoke-test.sh` keeps a read-only manifest check so added or removed extension roots are visible during smoke testing. The manifest intentionally ignores the shared `.pi/extensions/lib/` directory.

## Extension roots covered by smoke test

- `00-web-access-env.ts` — web/search environment defaults.
- `01-omlx-provider-setup-and-recovery.ts` — local oMLX provider registration plus prompt-too-long/prefill-memory recovery.
- `04-delete-current-session.ts` — current-session cleanup command.
- `10-discord-cron.ts` — scheduled Discord-backed Pi jobs.
- `15-discord-send-file.ts` — current-channel Discord file upload helper.
- `16-discord-ping.ts` — immediate Discord notifications and attachments.
- `20-session-search.ts` — prior Pi/JARVIS session search.
- `30-google-access.ts` — Google Workspace tool.
- `34-maps.ts` — Google Maps places/geocode/routes natural-language tool.
- `35-memory.ts` — durable project-local memory.
- `45-jarvis.ts` — Operation JARVIS dashboard/Cast plus `smart_plug`.
- `46-local-pi-session-status.ts` — dashboard-visible local Pi session heartbeat.
- `47-token-rate-status.ts` — UI token-rate status.
- `48-agent-phone.ts` — guarded LG-H933 Android phone adapter.
- `50-browser/` — visible Chrome browser control via Playwright CDP.
- `50-minecraft-jarvis-chat.ts` — Minecraft jarvis bot chat/control.
- `55-ssh-exec.ts` — configured SSH command execution.
- `60-pdf-read-result.ts` — PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `98-slim-provider-payload.ts` — provider payload/schema slimming.
- `99-lazy-tools.ts` — lazy optional tool-group visibility.

## Current tool surface

Always-on/baseline tools exposed by this project include local coding tools plus:

- `ssh`
- `web_search`, `fetch_content`, `get_search_content`
- `minecraft_jarvis`
- `maps`
- `load_tools`

Optional tool groups are loaded with `load_tools({ groups: [...] })` or `/load-tools`:

| Group | Tools |
|---|---|
| `memory` | `memory` |
| `code_docs` | `code_search` |
| `jarvis` | `jarvis`, `smart_plug` |
| `phone` | `agent_phone` |
| `google` | `google_workspace` |
| `cron` | `discord_cron` |
| `discord` | `discord_ping`, `discord_send_file` |
| `sessions` | `session_search` |
| `youtube` | `youtube_api` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

`minecraft_jarvis` remains accepted as a compatibility group but the tool is already always on.

## Verification

Use:

```bash
cd /path/to/JARVIS
pi list
.pi/smoke-test.sh
```

The smoke test checks package presence, command availability, extension roots, browser package install state, CLI help paths, env key names, runtime-data presence, and doc links. It deliberately does not start Chrome, call oMLX/Google/Discord/web APIs, touch phone/ADB, or control Cast/Spotify/Kasa.
