# Pi Extensions

Updated: 2026-08-10 EDT

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
- `01-omlx-provider-setup-and-recovery.ts` — non-blocking local oMLX provider registration plus prompt-too-long/prefill-memory recovery. Startup uses static seeds or the private last-known context-window cache at `.pi/runtime/omlx-context-windows.json`; live oMLX discovery refreshes the provider registry and cache after `session_start`, and the provider's native `refreshModels` callback reads the active server values whenever Pi refreshes `/model`. Unreachable providers silently retain their cached models and retry on the next refresh.
- `04-delete-current-session.ts` — current-session cleanup command.
- `10-discord-cron.ts` — scheduled Discord-backed Pi jobs.
- `15-discord-send-file.ts` — current-channel Discord file upload helper.
- `16-discord-ping.ts` — immediate Discord notifications and attachments.
- `20-session-search.ts` — prior Pi/JARVIS session search.
- `30-google-access.ts` — Google Workspace tool.
- `34-maps.ts` — Google Maps places/geocode/routes natural-language tool.
- `35-memory.ts` — explicit durable project-local memory; no prompt-time auto-recall or system-prompt mutation.
- `45-jarvis.ts` — Operation JARVIS Cast, smart plugs, and VeSync/Levoit air purifier actions.
- `46-local-pi-session-status.ts` — local Pi session heartbeat consumed by `jarvisd`.
- `50-browser/` — visible Chrome control through a persistent CDP bridge, hard-scoped to a dedicated JARVIS window in the user's signed-in profile.
- `50-minecraft-jarvis-chat.ts` — Minecraft jarvis bot chat/control.
- `55-ssh-exec.ts` — unrestricted configured SSH execution plus directly attached and stateful interactive PTY sessions.
- `56-github-cli.ts` — guarded GitHub CLI adapter.
- `58-reaper-bridge.ts` — live REAPER inline-Lua bridge.
- `60-pdf-read-result.ts` — PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `61-live-dictation.ts` — F1-controlled PowerConf live dictation through local oMLX Whisper transcription.
- `98-slim-provider-payload.ts` — deterministic provider payload/schema slimming, including OpenAI deferred `tool_search_output` schemas.
- `99-lazy-tools.ts` — additive lazy optional tool activation using Pi's native deferred-loading protocol where supported.
- `thinking-level-on-model-select.ts` — applies thinking levels pinned in `enabledModels`/`--models` on active model switches, falling back to `xhigh`; Qwen3.8 27B is pinned to `medium` in `.pi/settings.json`.

## Current tool surface

Always-on/baseline tools exposed by this project include local coding tools plus:

- `ssh`
- `web_search`, `fetch_content`, `get_search_content`
- `maps`
- `load_tools`

Optional tool groups are loaded with `load_tools({ groups: [...] })` or `/load-tools`:

| Group | Tools |
|---|---|
| `memory` | `memory` |
| `code_docs` | `code_search` |
| `jarvis` | `jarvis`, `smart_plug` |
| `minecraft_jarvis` | `minecraft_jarvis` |
| `github` | `github_cli` |
| `google` | `google_workspace` |
| `cron` | `discord_cron` |
| `discord` | `discord_ping`, `discord_send_file` |
| `sessions` | `session_search` |
| `reaper` | `reaper_ping`, `reaper_lua` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

The provider-visible `load_tools` description, prompt snippet, parameter help, and `/load-tools` usage are generated from the canonical registry in `99-lazy-tools.ts`. Model-called `load_tools` activation is purely additive: Pi records the added tool names on the tool result and, on capable providers such as GPT-5.6, anchors their definitions there with native deferred loading instead of changing the initial cached tool prefix. Other providers use Pi's normal full-tool fallback. Manual `/load-tools` remains available but has no tool-result anchor, so it may refresh the provider cache once.

Optional tools omit active-only `promptSnippet`/`promptGuidelines`; their full group playbooks are returned by model-called `load_tools` and remain in conversation context. Manual `/load-tools` queues the same hidden playbook for the next user turn. `98-slim-provider-payload.ts` preserves the registry-generated top-level `load_tools` description and also slims deferred schemas nested in OpenAI `tool_search_output` items. The smoke test checks these invariants for drift.

Durable memory is explicit-only. Loading the `memory` group preserves search/remember/update/forget/list/status functionality without performing prompt-time recall or changing the system prompt between user turns.

The `jarvis` group includes Operation JARVIS actions for Cast/Spotify workflows, smart plugs, and the Levoit/VeSync air purifier via `purifier-status` and `purifier-set`.

Minecraft bot chat/control and authenticated GitHub CLI access are intentionally lazy: load `minecraft_jarvis` before calling `minecraft_jarvis`, or load `github` before calling `github_cli`. Ordinary local `git` operations continue to use the baseline coding shell.

## SSH execution and interactive terminals

The always-on `ssh` tool requires an explicit configured remote host and pins its identity, user, and allowed working directories. Use coding tools—not SSH—for mac-mini-64.

- Captured command: `ssh({ host: "mac-mini-16", command: "hostname" })`.
- Local Pi TUI terminal: `ssh({ host: "mac-mini-16", command: "vim file.txt", pty: true })`.
- Discord/RPC terminal: start with `ssh({ action: "start", host: "mac-mini-16", command: "vim file.txt" })`, then use its `sessionId`.
- Send a line with `action: "input"`, `input: "text"`, and `key: "ENTER"`. Named keys include arrows, Escape, Backspace, Ctrl-C, Ctrl-D, Ctrl-Z, and Ctrl-L.
- `action: "read"` returns the current rendered terminal screen (so full-screen editors and TUIs remain intelligible) and consumes pending transcript output by default; pass `consume: false` to retain pending output.
- `action: "list"` lists active/exited sessions in the current Pi process.

Stateful sessions are process-local, retain a bounded terminal-output tail, expire after an idle period, and close on Pi session shutdown. Configure these with `JARVIS_SSH_INTERACTIVE_IDLE_SECONDS` and `JARVIS_SSH_INTERACTIVE_OUTPUT_BYTES`.

Install the PTY dependency after a fresh clone:

```bash
cd /path/to/JARVIS/.pi/extensions/lib
npm install
```

## Verification

Use:

```bash
cd /path/to/JARVIS
pi list
.pi/smoke-test.sh
```

The smoke test checks package presence, command availability, extension roots, browser package install state, CLI help paths, env key names, runtime-data presence, and doc links. It deliberately does not start Chrome, call oMLX/Google/Discord/web APIs, touch phone/ADB, or control Cast/Spotify/Kasa.
