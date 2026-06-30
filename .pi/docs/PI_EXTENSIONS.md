# Pi Extensions

Updated: 2026-06-30 EDT

The local Pi extension inventory lives in `.pi/extensions/`. `.pi/smoke-test.sh` keeps a read-only manifest check so added or removed extension roots are visible during smoke testing. The manifest intentionally ignores the shared `.pi/extensions/lib/` directory.

## Shared extension utilities

Shared helpers live under `.pi/extensions/lib/` and are imported by project-local extensions; they are not standalone extension roots.

- `lib/env.ts` — `.env` discovery/parsing and env lookup helpers.
- `lib/path.ts` — safe user path normalization helpers.
- `lib/text.ts` — truncation and byte/message formatting helpers.
- `lib/discord.ts` — Discord filename and multipart request helpers.

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
- `45-jarvis.ts` — Operation JARVIS dashboard/Cast, smart plugs, and VeSync/Levoit air purifier actions.
- `46-local-pi-session-status.ts` — dashboard-visible local Pi session heartbeat.
- `48-agent-phone.ts` — guarded LG-H933 Android phone adapter.
- `50-browser/` — visible Chrome browser control via Playwright CDP.
- `50-minecraft-jarvis-chat.ts` — Minecraft jarvis bot chat/control.
- `55-ssh-exec.ts` — configured SSH command execution.
- `56-github-cli.ts` — guarded GitHub CLI adapter.
- `60-pdf-read-result.ts` — PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `70-image-generation.ts` — local Qwen image generation via mac-mini-64.
- `71-video-generation.ts` — local Wan/MLX-Gen MP4 video generation via mac-mini-64.
- `98-slim-provider-payload.ts` — provider payload/schema slimming.
- `99-lazy-tools.ts` — lazy optional tool-group visibility.

## Current tool surface

Always-on/baseline tools exposed by this project include local coding tools plus:

- `ssh`
- `web_search`, `fetch_content`, `get_search_content`
- `minecraft_jarvis`
- `maps`
- `github_cli`
- `load_tools`

Optional tool groups are loaded with `load_tools({ groups: [...] })` or `/load-tools`:

| Group | Tools |
|---|---|
| `memory` | `memory` |
| `code_docs` | `code_search` |
| `image` | `generate_image` |
| `video` | `generate_video` |
| `jarvis` | `jarvis`, `smart_plug` |
| `phone` | `agent_phone` |
| `google` | `google_workspace` |
| `cron` | `discord_cron` |
| `discord` | `discord_ping`, `discord_send_file` |
| `sessions` | `session_search` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

The `jarvis` group includes Operation JARVIS actions for dashboard/Cast/Spotify workflows, smart plugs, and the Levoit/VeSync air purifier via `purifier-status` and `purifier-set`.

`minecraft_jarvis` remains accepted as a compatibility group but the tool is already always on.

## Local media generation worker

The `image` and `video` groups use the private worker repo [`DylPickle13/local-media-generation`](https://github.com/DylPickle13/local-media-generation) on `mac-mini-64`.

- Canonical remote directory: `/Users/dylanrapanan/media-generation`
- Compatibility symlink: `/Users/dylanrapanan/image-generation -> media-generation`
- Local copied outputs: `generated-images/` and `generated-videos/` in this JARVIS repo, both ignored by git
- Pi extensions default to `~/media-generation`, export both `MEDIA_GENERATION_DIR` and legacy `IMAGE_GENERATION_DIR`, and set `JARVIS_GENERATION_SYNC=0` because the extensions handle their own copy-back and remote cleanup.
- Manual/README worker runs leave sync enabled: successful outputs copy back through SSH alias `jarvis-vm`, then remote media is deleted only after copy-back succeeds.

Remote verification on `mac-mini-64`:

```bash
cd ~/media-generation
bin/image-generate --health
bin/video-generate --health
bin/smoke-test
```

The worker `--health` JSON includes `sync.image` and `sync.video` checks confirming `jarvis-vm` can write to `/Users/gemma/JARVIS/generated-images/` and `/Users/gemma/JARVIS/generated-videos/`. `bin/smoke-test` is a fast compile/health/fake-sync test; it does not run model inference.

## Verification

Use:

```bash
cd /path/to/JARVIS
pi list
.pi/smoke-test.sh
```

The smoke test checks package presence, command availability, extension roots, browser package install state, CLI help paths, env key names, runtime-data presence, and doc links. It deliberately does not start Chrome, call oMLX/Google/Discord/web APIs, touch phone/ADB, or control Cast/Spotify/Kasa.
