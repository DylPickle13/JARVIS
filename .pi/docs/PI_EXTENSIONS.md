# Pi Extensions

Updated: 2026-08-31 EDT

JARVIS adds its tools and session helpers through `.pi/extensions/`. The read-only `.pi/smoke-test.sh` checks the extension list for additions or removals. Shared helpers in `.pi/extensions/lib/` are excluded because they are not standalone extensions.

## Shared extension utilities

Extensions import these shared helpers from `.pi/extensions/lib/`:

- `lib/env.ts`: `.env` discovery/parsing and env lookup helpers.
- `lib/path.ts`: safe user path normalization helpers.
- `lib/text.ts`: bounded text truncation helper.
- `lib/attach/`: private transactional attachment storage, image preparation, native-picker invocation, temporary Mac SSH picker transport, and the exact-process mobile Unix-socket endpoint used by `/attach` and the native iPhone paperclip.
- `lib/ssh-pty.ts`: local `node-pty` wrapper and headless xterm screen used for bidirectional SSH terminal sessions. Runtime dependencies are declared in `lib/package.json`.

## Extension roots covered by smoke test

- `00-private-permissions.ts`: enforces owner-only permissions on ignored local configuration and private runtime directories.
- `pi-web-access`: stock pinned npm extension, loaded directly through `.pi/settings.json`. The old wrapper is archived at `.pi/disabled-extensions/00-web-access-env.ts.disabled`; its scoped config and policy overrides no longer apply after restarting Pi.
- `01-omlx-provider-setup-and-recovery.ts`: non-blocking local oMLX provider registration plus prompt-too-long/prefill-memory recovery. Startup uses static seeds or the private last-known context-window cache at `.pi/runtime/omlx-context-windows.json`; live oMLX discovery refreshes the provider registry and cache after `session_start`, and the provider's native `refreshModels` callback reads the active server values whenever Pi refreshes `/model`. Unreachable providers silently retain their cached models and retry on the next refresh.
- `04-delete-current-session.ts`: current-session cleanup command.
- `04-siri-new-session.ts`: private, exact-mobile-Pi ingress for Siri. Uses in-memory conversation evidence, busy/compaction/prompt/queue and empty-editor guards. Claims a New slot synchronously, guards overlapping input before attachment consumption, submits a literal user message and acknowledges only its message-start event. No history reset, PTY paste, runtime reload, exposed tool, or queued fallback. Existing Pi processes need an owner-controlled `/reload` after rollout to advertise this capability.
- `05-attach.ts`: the single parameterless `/attach` command plus the private exact-mobile-process endpoint: native selection, revisioned in-memory staging, and next-message image/path injection. It exposes no LLM tool or additional command.
- `10-jarvis-cron.ts`: private scheduled Pi jobs and bounded local result history.
- `30-google-access.ts`: Google Workspace tool.
- `34-maps.ts`: Google Maps places/geocode/routes natural-language tool.
- `35-memory.ts`: explicit durable project-local memory; no prompt-time auto-recall or system-prompt mutation.
- `45-jarvis.ts`: Operation JARVIS Cast, smart plugs, and VeSync/Levoit air purifier actions.
- `46-local-pi-session-status.ts`: sends lifecycle heartbeats to `jarvisd`, reporting New, Idle, Running, Compacting, or fail-closed Unknown.
  - New means no user/assistant messages or conversation summaries in the in-memory session tree. Metadata alone does not count. A fresh message clears New; restored, forked, or compacted history stays Idle when inactive.
  - After compaction, heartbeats check `ctx.isIdle()`. There is no Waiting mode: open interactive prompts remain Running/busy for restart and completion safety.
  - A successful, settled mobile turn can call the content-free APNs completion helper only when its private gate is enabled. It does not replay history or reload Pi.
  - `jarvisd` derives Offline and fail-closed Unknown from the fixed tmux sessions.
- `47-watch-terminal-speech.ts`: publishes only the current tmux-bound Pi session's latest completed assistant text blocks to a private Watch-speech runtime marker; thinking and tool activity are excluded.
- `50-browser/`: visible Chrome control through a persistent CDP bridge, hard-scoped to a dedicated JARVIS window in the user's signed-in profile.
- `50-minecraft-jarvis-chat.ts`: Minecraft jarvis bot chat/control.
- `55-ssh-exec.ts`: unrestricted configured SSH execution plus directly attached and stateful interactive PTY sessions.
- `56-github-cli.ts`: guarded GitHub CLI adapter.
- `58-reaper-bridge.ts`: live REAPER inline-Lua bridge.
- `60-pdf-read-result.ts`: PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `98-slim-provider-payload.ts`: deterministic provider payload/schema slimming, including OpenAI deferred `tool_search_output` schemas.
- `99-lazy-tools.ts`: additive lazy optional tool activation, plus opt-in direct-call auto-loading on the patched JARVIS Pi runtime.

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
| `cron` | `jarvis_cron` |
| `reaper` | `reaper_ping`, `reaper_lua` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

`99-lazy-tools.ts` is the registry for group descriptions, prompt snippets, parameter help, and `/load-tools` usage. When the model calls `load_tools`, Pi adds tools without removing existing ones and records the new names in the result. Providers with native deferred loading, such as GPT-5.6, receive the definitions there rather than in a changed initial tool prefix. Other providers receive the normal full active-tool list. Manual `/load-tools` has no tool-result anchor, so it may refresh the provider cache once.

The [JARVIS lazy-execution runtime](PI_LAZY_EXECUTION.md) also accepts valid direct calls to registered optional tools. It activates the group and executes the call once through the usual validation and safety hooks. Unknown, removed, and CLI/SDK-excluded tools remain unavailable.

A direct call may refresh the provider prefix once because Pi keeps an already-used tool's schema immediate rather than deferring it. Use `load_tools` to discover unfamiliar schemas or take advantage of native deferred loading. Stock Pi requires explicit loading.

Optional tools omit active-only `promptSnippet`/`promptGuidelines`; their full group playbooks are returned by model-called `load_tools` (or appended to the original direct call's result after auto-loading) and remain in conversation context. Manual `/load-tools` queues the same hidden playbook for the next user turn. `98-slim-provider-payload.ts` preserves the registry-generated top-level `load_tools` description and also slims deferred schemas nested in OpenAI `tool_search_output` items. The smoke test checks these invariants for drift.

Memory is explicit: loading `memory` makes search, remember, update, forget, list, and status available. It does not recall memories automatically or change the system prompt between turns.

Prior Pi/JARVIS sessions are searched directly with baseline coding tools. The project-specific JSONL directory and raw-search workflow belong in ignored `.pi/APPEND_SYSTEM.md`; use `rg -l` to shortlist files, then parse/read only the relevant records.

The `jarvis` group includes Operation JARVIS actions for Cast/Spotify workflows, smart plugs, and the Levoit/VeSync air purifier via `purifier-status` and `purifier-set`.

Minecraft bot chat/control and authenticated GitHub CLI access are intentionally lazy: discover their schemas by loading `minecraft_jarvis` or `github`. Known valid direct calls also auto-load on the JARVIS runtime. Ordinary local `git` operations continue to use the baseline coding shell.

## Native file attachments

`05-attach.ts` adds `/attach`, a command with no arguments, aliases, subcommands, or LLM tool. It opens an AppKit dialog where you can select, remove, replace, or clear files. **Done** applies the selection; cancelling or closing keeps the previous queue. The next ordinary interactive prompt consumes the staged set atomically.

Selected files are copied directly into the ignored private `attachments/` directory with owner-only modes and readable collision suffixes such as `photo-2.png`. The staged queue exists only in the live Pi process: no manifests, per-session directories, or other attachment metadata are written. Restarting Pi clears any unsent queue while leaving its copied files in place. Defaults are 10 files, 50 MiB per file, and 100 MiB total; bounded `PI_ATTACH_MAX_FILES`, `PI_ATTACH_MAX_FILE_BYTES`, and `PI_ATTACH_MAX_TOTAL_BYTES` environment overrides are available. Images supported by the active model are normalized through Pi's image pipeline and included as native image blocks; every attachment is also represented by its flat local path and bounded prompt metadata. Non-image files remain local for `read`, the PDF extension, or other explicit tools. Consumed files are retained because later session turns may refer to those paths; files explicitly removed before submission are deleted.

Direct local use invokes `.pi/scripts/pi-attach-picker`, which compiles the checked-in AppKit helper into ignored mode-`0700` runtime storage on first use. The six-process attachment setup described here can retain stale SSH variables from process creation, even when viewed locally. For later session layouts, see the [app status notes](../../projects/operation-jarvis/jarvis-app/docs/planned-work.md). `/attach` treats that inheritance as stale only when the exact allowlisted tmux session is currently attached exclusively by client processes descended from the local `/Applications/Visual Studio Code.app`; missing, mixed, raced, or genuinely remote client evidence still fails closed. This changes no tmux state and never infers a picker target merely from the presence of any local client.

Plain SSH cannot ask the client computer to open a dialog. For attachment-enabled SSH, connect from the client checkout with:

```bash
.pi/scripts/jarvis-pi-ssh [ssh options] <host>
```

The launcher starts a temporary client-loopback bridge and creates a random, token-protected reverse Unix-socket forwarding inside SSH. A versioned picker protocol returns retained staged IDs plus newly selected files, so remove/clear/cancel behavior is identical locally and over SSH; only new file bytes cross the encrypted connection. No browser, public listener, cloud intermediary, persistent daemon, or globally installed Pi extension is used. A plain SSH session fails closed with reconnection guidance rather than opening a dialog on the remote Mac.

The native iPhone implementation adds Photos/Files review behind a paperclip without typing `/attach` or writing terminal bytes. Checked-in `project.yml` keeps the iPhone target's `JARVIS_NATIVE_ATTACHMENTS` compilation condition disabled; audited attachment candidates enable it only in generated artifact input. The app streams bounded file bodies over a separate typed SSH session child to `.pi/scripts/pi-attach-mobile-receiver.mjs`. The command has no picker-controlled arguments: it accepts only an app-generated fixed `--slot 1|2|3|4|5|6` selector and defaults to Slot 1 for Build 132 compatibility. Each one-shot proxy can reach only the owner-mode endpoint published by the exact allowlisted `jarvis-mobile` session process (`jarvis-ios` through `jarvis-ios-6`); Slot 1 remains pane `%0` and retains the legacy descriptor. Reconcile commits use generation/revision checks, byte counts, SHA-256, collision-safe loose files, and bounded memory-only request outcomes; ambiguous delivery permits one read-only status query and never an automatic upload retry. The receiver is not a daemon, HTTP endpoint, general SSH command surface, or persistent queue. Architecture and acceptance gates are documented in the consolidated [six-session contract](../../projects/operation-jarvis/jarvis-app/docs/README.md#six-fixed-mobile-pi-conversations) and [attachment plan](../../projects/operation-jarvis/jarvis-app/docs/README.md#iphone-terminal-keyboard-avoidance-and-native-attach-implementation-plan).

## SSH execution and interactive terminals

The always-on `ssh` tool requires an explicit configured remote host and pins its identity, user, and allowed working directories. Use local coding tools for mac-mini-64, not SSH.

- Captured command: `ssh({ host: "mac-mini-16", command: "hostname" })`.
- Local Pi TUI terminal: `ssh({ host: "mac-mini-16", command: "vim file.txt", pty: true })`.
- RPC terminal: start with `ssh({ action: "start", host: "mac-mini-16", command: "vim file.txt" })`, then use its `sessionId`.
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
node --test .pi/scripts/tests/pi-attach-*.test.mjs .pi/scripts/tests/jarvis-pi-ssh.test.mjs
.pi/smoke-test.sh
```

The smoke test checks package presence, command availability, extension roots, browser package install state, CLI help paths, env key names, runtime-data presence, and doc links. It deliberately does not start Chrome, call oMLX/Google/web APIs, touch phone/ADB, or control Cast/Spotify/Kasa.
