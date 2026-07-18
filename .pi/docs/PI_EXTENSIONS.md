# Pi Extensions

Updated: 2026-07-18 EDT

The local Pi extension inventory lives in `.pi/extensions/`. `.pi/smoke-test.sh` keeps a read-only manifest check so added or removed extension roots are visible during smoke testing. The manifest intentionally ignores the shared `.pi/extensions/lib/` directory.

## Shared extension utilities

Shared helpers live under `.pi/extensions/lib/` and are imported by project-local extensions; they are not standalone extension roots.

- `lib/env.ts` — `.env` discovery/parsing and env lookup helpers.
- `lib/path.ts` — safe user path normalization helpers.
- `lib/text.ts` — truncation and byte/message formatting helpers.
- `lib/discord.ts` — Discord filename and multipart request helpers.
- `lib/ssh-pty.ts` — local `node-pty` wrapper and headless xterm screen used for bidirectional SSH terminal sessions. Runtime dependencies are declared in `lib/package.json`.

## Extension roots covered by smoke test

- `00-private-permissions.ts` — enforces owner-only permissions on ignored local configuration and private runtime directories.
- `00-web-access-env.ts` — project-scoped `pi-web-access` bootstrap plus JARVIS web/search policy; never mutates or consumes global `~/.pi/web-search.json`.
- `01-omlx-provider-setup-and-recovery.ts` — non-blocking local oMLX provider registration plus prompt-too-long/prefill-memory recovery. Startup uses static seeds or the private last-known context-window cache at `.pi/runtime/omlx-context-windows.json`; live oMLX discovery refreshes the provider registry and cache in the background after `session_start`.
- `04-delete-current-session.ts` — current-session cleanup command.
- `10-discord-cron.ts` — scheduled Discord-backed Pi jobs.
- `15-discord-send-file.ts` — current-channel Discord file upload helper.
- `16-discord-ping.ts` — immediate Discord notifications and attachments.
- `20-session-search.ts` — prior Pi/JARVIS session search.
- `30-google-access.ts` — Google Workspace tool.
- `34-maps.ts` — Google Maps places/geocode/routes natural-language tool.
- `35-memory.ts` — explicit durable project-local memory; no prompt-time auto-recall or system-prompt mutation.
- `45-jarvis.ts` — Operation JARVIS dashboard/Cast, smart plugs, and VeSync/Levoit air purifier actions.
- `46-local-pi-session-status.ts` — dashboard-visible local Pi session heartbeat.
- `48-agent-phone.ts` — guarded LG-H933 Android phone adapter.
- `50-browser/` — visible Chrome browser control via Playwright CDP.
- `50-minecraft-jarvis-chat.ts` — Minecraft jarvis bot chat/control.
- `55-ssh-exec.ts` — unrestricted configured SSH execution plus directly attached and stateful interactive PTY sessions.
- `56-github-cli.ts` — guarded GitHub CLI adapter.
- `58-reaper-bridge.ts` — live REAPER inline-Lua bridge.
- `59-gx10-bridge.ts` — direct BOSS GX-10 CoreMIDI bridge exposing typed semantic reads/search, ping, and low-level unsaved inline Lua with transactional verified writes.
- `60-pdf-read-result.ts` — PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `70-image-generation.ts` — local Qwen image generation via mac-mini-64.
- `71-video-generation.ts` — local LTX-2.3 Q8 MLX MP4 audio-video generation via mac-mini-64.
- `98-slim-provider-payload.ts` — deterministic provider payload/schema slimming, including OpenAI deferred `tool_search_output` schemas.
- `99-lazy-tools.ts` — additive lazy optional tool activation using Pi's native deferred-loading protocol where supported.

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
| `reaper` | `reaper_ping`, `reaper_lua` |
| `gx10` | `gx10_ping`, `gx10_get`, `gx10_find`, `gx10_lua` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

The provider-visible `load_tools` description, prompt snippet, parameter help, and `/load-tools` usage are generated from the canonical registry in `99-lazy-tools.ts`. Model-called `load_tools` activation is purely additive: Pi records the added tool names on the tool result and, on capable providers such as GPT-5.6, anchors their definitions there with native deferred loading instead of changing the initial cached tool prefix. Other providers use Pi's normal full-tool fallback. Manual `/load-tools` remains available but has no tool-result anchor, so it may refresh the provider cache once.

Optional tools omit active-only `promptSnippet`/`promptGuidelines`; their full group playbooks are returned by model-called `load_tools` and remain in conversation context. Manual `/load-tools` queues the same hidden playbook for the next user turn. `98-slim-provider-payload.ts` preserves the registry-generated top-level `load_tools` description and also slims deferred schemas nested in OpenAI `tool_search_output` items. The smoke test checks these invariants for drift.

Durable memory is explicit-only. Loading the `memory` group preserves search/remember/update/forget/list/status functionality without performing prompt-time recall or changing the system prompt between user turns.

The `jarvis` group includes Operation JARVIS actions for dashboard/Cast/Spotify workflows, smart plugs, and the Levoit/VeSync air purifier via `purifier-status` and `purifier-set`.

The `gx10` group uses the canonical `/Users/dylanrapanan/gx10-bridge` Git repository on mac-mini-16. Prefer read-only `gx10_get` for ordinary live-patch questions and `gx10_find` for semantic discovery; `gx10_lua` remains the planning/custom/low-level escape hatch. Semantic edits first use RQ1-only `gx.plan_edit`, then require exact plan-ID approval before `tx:apply_plan` can queue a matching verified transaction. The native host uses only the standard GX-10 CoreMIDI endpoint, generates versioned semantic metadata from installed Tone Studio resources, and permits explicit writes only through snapshot/readback/rollback transactions. Its API documentation is the remote repository's `README.md`.

`minecraft_jarvis` remains accepted as a compatibility group but the tool is already always on.

## SSH execution and interactive terminals

The always-on `ssh` tool restricts connection selection to private configured host aliases, identities, users, and allowed remote working directories. It does not restrict command content.

- Captured command: `ssh({ command: "hostname" })` or `action: "exec"`.
- Local Pi TUI terminal: `ssh({ command: "vim file.txt", pty: true })`. Pi suspends its TUI, runs `ssh -tt` with inherited terminal I/O, and restores Pi when SSH exits.
- Discord/RPC terminal: start a stateful PTY with `ssh({ action: "start", command: "vim file.txt" })`; use the returned `sessionId` with `input`, `read`, `resize`, `signal`, and `close` actions.
- Send a line with `action: "input"`, `input: "text"`, and `key: "ENTER"`. Named keys include arrows, Escape, Backspace, Ctrl-C, Ctrl-D, Ctrl-Z, and Ctrl-L.
- `action: "read"` returns the current rendered terminal screen (so full-screen editors and TUIs remain intelligible) and consumes pending transcript output by default; pass `consume: false` to retain pending output.
- `action: "list"` lists active/exited sessions in the current Pi process.

Stateful sessions are process-local, retain a bounded terminal-output tail, expire after an idle period, and close on Pi session shutdown. Configure these with `JARVIS_SSH_INTERACTIVE_IDLE_SECONDS` and `JARVIS_SSH_INTERACTIVE_OUTPUT_BYTES`.

Install the PTY dependency after a fresh clone:

```bash
cd /path/to/JARVIS/.pi/extensions/lib
npm install
```

## Local media generation worker

The `image` and `video` groups use the private worker repo [`DylPickle13/local-media-generation`](https://github.com/DylPickle13/local-media-generation) on `mac-mini-64`.

- Canonical remote directory: `/Users/dylanrapanan/media-generation`
- Compatibility symlink: `/Users/dylanrapanan/image-generation -> media-generation`
- Local copied outputs: `generated-images/` and `generated-videos/` in this JARVIS repo, both ignored by git
- Video generation uses `dgrauet/ltx-2.3-mlx-q8` through `ltx-2-mlx`, producing MP4s with synchronized stereo audio by default.
- Pi extensions default to `~/media-generation`, export both `MEDIA_GENERATION_DIR` and legacy `IMAGE_GENERATION_DIR`, and set `JARVIS_GENERATION_SYNC=0` because the extensions handle their own copy-back and remote cleanup.
- Manual/README worker runs leave sync enabled: successful outputs copy back through SSH alias `jarvis-vm`, then remote media is deleted only after copy-back succeeds.

Remote verification on `mac-mini-64`:

```bash
cd ~/media-generation
bin/image-generate --health
bin/video-generate --health
bin/smoke-test
```

The worker `--health` JSON includes `sync.image` and `sync.video` checks confirming `jarvis-vm` can write to `/Users/gemma/JARVIS/generated-images/` and `/Users/gemma/JARVIS/generated-videos/`; video health also reports the LTX model/text-encoder cache state and `supportsAudio:true`. `bin/smoke-test` is a fast compile/health/fake-sync test; it does not run model inference.

## Verification

Use:

```bash
cd /path/to/JARVIS
pi list
.pi/smoke-test.sh
```

The smoke test checks package presence, command availability, extension roots, browser package install state, CLI help paths, env key names, runtime-data presence, and doc links. It deliberately does not start Chrome, call oMLX/Google/Discord/web APIs, touch phone/ADB, or control Cast/Spotify/Kasa.
