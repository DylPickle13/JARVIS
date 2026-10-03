# Pi Extensions

Updated: 2026-10-02 EDT

JARVIS adds its tools and session helpers through `.pi/extensions/`. The read-only `.pi/smoke-test.sh` checks the extension list for additions or removals. Shared helpers in `.pi/extensions/lib/` are excluded because they are not standalone extensions.

## Built-in extension selection

Project settings and the tracked template disable `builtin:llama.cpp` and
`builtin:mcp`: this setup uses oMLX/Codex and has no MCP servers. Pi’s built-in
codemode and tool-search remain available. Remove the corresponding exclusion if
llama.cpp or MCP is introduced later.

The retired code/docs group is no longer advertised: its tool was not registered.
Use baseline repository search or stock web tools for external documentation.
The existing group loader and `/delete` are retained; migration to native deferred
tools/namespaces is a separate change so JARVIS playbooks are not lost.

Start a new Pi process or use an owner-controlled `/reload` to pick up these
extension/settings changes. This cleanup does not restart existing sessions or
remove legacy runtime artifacts that a running process may still use.

## Shared extension utilities

Extensions import these shared helpers from `.pi/extensions/lib/`:

- `lib/env.ts`: `.env` discovery/parsing and env lookup helpers.
- `lib/path.ts`: safe user path normalization helpers.
- `lib/text.ts`: bounded text truncation helper.
- `lib/attach/`: private transactional attachment storage, image preparation, native-picker invocation, temporary Mac SSH picker transport, and the exact-process mobile Unix-socket endpoint used by `/attach` and the native iPhone paperclip.
- `lib/ssh-pty.ts`: local `node-pty` wrapper and headless xterm screen used for bidirectional SSH terminal sessions. Runtime dependencies are declared in `lib/package.json`.

## Extension roots covered by smoke test

- `00-private-permissions.ts`: enforces owner-only permissions on ignored local configuration and private runtime directories.
- `pi-web-access`: stock pinned npm extension, loaded directly through `.pi/settings.json`.
- `02-web-search-policy.ts`: forces `web_search` tool-call input `includeContent` to `false`, including when explicitly requested as `true`, preventing background source fetches and later-turn completion notifications. Explicit `fetch_content` calls remain unchanged. Requires `/reload` or a new session after installation; does not cancel already-running fetches.
- `01-omlx.ts`: non-blocking two-host oMLX bridge with authenticated full-catalog discovery, metadata-driven thinking controls, verified per-model Qwen overrides, private offline caching, UI-only `/omlx-status`, deadline-free streaming, and bounded recovery. See [OMLX.md](OMLX.md) for configuration, safety limits and tests. The old context cache is read for migration; new snapshots use `.pi/runtime/omlx-catalog.json`.
- `03-codex-fast.ts`: optional `/fast` toggle for Codex priority service tier.
- `04-delete-current-session.ts`: current-session cleanup command.
- `04-room-audio-session.ts`: exact Session 10 voice ingress and presentation-only guidance; inactive outside its provisioned pane.
- `04-siri-new-session.ts`: private, exact-mobile-Pi ingress for Siri. Uses in-memory conversation evidence, busy/compaction/prompt/queue and empty-editor guards. Claims a New slot synchronously, guards overlapping input before attachment consumption, submits a literal user message and acknowledges only its message-start event. No history reset, PTY paste, runtime reload, exposed tool, or queued fallback. Existing Pi processes need an owner-controlled `/reload` after rollout to advertise this capability.
- `05-attach.ts`: the single parameterless `/attach` command plus the private exact-mobile-process endpoint: native selection, revisioned in-memory staging, and next-message image/path injection. It exposes no LLM tool or additional command.
- `10-jarvis-cron.ts`: private scheduled Pi jobs and bounded local result history.
- `30-google-access.ts`: Google Workspace tool.
- `34-maps.ts`: Google Maps places/geocode/routes natural-language tool.
- `35-memory.ts`: explicit durable project-local memory; no prompt-time auto-recall or system-prompt mutation.
- `44-notify.ts`: always-on `notify(title, message)` sends intentional, sanitized iPhone/Watch alerts through the existing backend. No lifecycle trigger, monitoring, or scheduling; see below.
- `45-jarvis.ts`: focused `operation_jarvis_media`, `operation_jarvis_plugs`, and `operation_jarvis_purifier` tools.
- `48-jarvis-security.ts`: `operation_jarvis_security` reads and guarded `operation_jarvis_automations` cloud rules; no polling/media.
- `46-local-pi-session-status.ts`: sends lifecycle heartbeats to `jarvisd`, reporting New, Idle, Running, Compacting, or fail-closed Unknown.
  - New means no user/assistant messages or conversation summaries in the in-memory session tree. Metadata alone does not count. A fresh message clears New; restored, forked, or compacted history stays Idle when inactive.
  - After compaction, heartbeats check `ctx.isIdle()`. There is no Waiting mode: open interactive prompts remain Running/busy for restart and completion safety.
  - Lifecycle/heartbeat events never send notifications. Automatic session-finish alerts and their one-minute cutoff are retired. The backend also rejects legacy lifecycle invocations from Pi processes that have not reloaded.
  - `jarvisd` derives Offline and fail-closed Unknown from the fixed tmux sessions.
- `47-watch-terminal-speech.ts`: publishes only the current tmux-bound Pi session's latest completed assistant text blocks to a private Watch-speech runtime marker; thinking and tool activity are excluded.
- `49-session-autoname.ts`: automatic, on-device session titles for `/resume`; see below.
- `50-browser/`: visible Chrome control through a persistent CDP bridge, hard-scoped to a dedicated JARVIS window in the user's signed-in profile.
- `55-ssh-exec.ts`: unrestricted configured SSH execution plus directly attached and stateful interactive PTY sessions.
- `56-github-cli.ts`: guarded GitHub CLI adapter.
- `58-reaper-bridge.ts`: live REAPER inline-Lua bridge.
- `60-pdf-read-result.ts`: PDF read-result replacement via oMLX MarkItDown with local `pdftotext` fallback.
- `98-slim-provider-payload.ts`: deterministic structured prompt/schema slimming, including OpenAI `additional_tools` and `tool_search_output` schemas. Never forces/flattens the initial prompt; see [prompt-cache compatibility](PROMPT_CACHE.md).
- `99-lazy-tools.ts`: additive lazy optional tool activation, plus opt-in direct-call auto-loading on the patched JARVIS Pi runtime.

## Intentional notifications

`notify({ title, message })` sends sir a custom JARVIS push from an approved,
PID-bound mobile session (slots 1–9). Use it for meaningful completed work,
blockers, or important updates—not every finished turn. An explicit request to
be notified when work is done should be honored after verifying the result.
It does not watch external conditions, schedule reminders, or keep Pi awake.

- The fixed backend helper receives a versioned, bounded envelope over stdin,
  never text in shell/argv. Existing APNs activation, device opt-in, topics,
  environment checks, private gates, and registry are retained unchanged.
- Titles are capped at 120 UTF-8 bytes; body previews at 140 characters.
  Known sensitive markers/paths fall back to generic text, links point back to
  the session, and control/bidi characters are removed. This is a heuristic,
  not a guarantee that arbitrary private prose can be recognized. Never submit
  credentials, raw prompts, or conversation excerpts to the tool.
- Identity-only receipts deduplicate a logical tool call without storing its
  text/tokens. Only definite transient APNs rejections can retry, within the
  existing four-attempt/five-minute limit. Unknown transmission, crashes, and
  partial acceptance are never automatically replayed or backfilled.
- `accepted` means Apple accepted the push, not screen delivery or readership.
  `partial`, `ambiguous`, `disabled`, and unavailable-device/session outcomes
  remain explicit tool errors; do not claim success or blindly resend.
- Taps retain the existing fixed-session routing on installed iPhone/Watch apps.
  The historical `pi-session-completed` wire name and cleanup types are retained
  for compatibility; they no longer imply an automatic finished-turn trigger.
  Scheduled-job alerts and foreground housekeeping are unchanged.
- Existing Pi sessions need owner-controlled `/reload` (or a new process) to
  expose `notify`; no service restart or app reinstall is needed for custom
  payloads. Revised native Settings copy is source-only until a later approved
  app build. No notification gate/registration is enabled by installing code.

Verification: 118 Pi/lifecycle tests and 68 backend tests passed; the shared app
package completed 290 tests (3 expected live-test skips), and the read-only smoke
check passed 188 checks. One explicit live implementation-ready alert was accepted
by Apple for both registered iPhone and Watch targets in slot 1. Its preview was
privacy-adjusted. Sir confirmed receiving the alert; delivery on each device
separately and tap-to-session acceptance remain unverified.
Sir subsequently reloaded Pi; a direct `notify` tool check was accepted for both
devices without preview adjustment. The shortened guidance was also reloaded.
No notification gate/registration change, service restart, agent-initiated Pi
reload, or native installation was performed.

Offline checks: `node --test .pi/tests/notify.test.mjs .pi/tests/lazy-tools.test.mjs
.pi/tests/cron.test.mjs .pi/scripts/tests/local-pi-session-status.test.mjs` and
`.venv/bin/python -m unittest discover -s
projects/operation-jarvis/jarvisd/tests/scheduler -v`.

## Automatic session names

`49-session-autoname.ts` calls `projects/apple-model/bin/apple-model` after `agent_settled` (once per completed response, not during tool cycles). No Pi core or apple-model changes or model-facing tools are needed. `/autoname-status` shows content-free diagnostic counters since the extension was loaded. Activate with `/reload` or a new Pi process; existing sessions are considered on their next completed response, not retroactively on startup.

- Input comes from the active in-memory branch: user text plus the last successful, tool-free assistant answer per user turn. Tools, thinking, images, custom messages, and abandoned branches are excluded. Compacted ancestors still present in that branch remain eligible; compaction summaries are not sent.
- Each message is capped at 1,600 characters. The original completed task and newest completed turns share a 6,000-character budget. This is a character bound, not a token guarantee; context errors are skipped safely.
- The fixed local binary receives conversation text and the current title via stdin, never shell interpolation or argv. No cloud fallback or transcript logging. Input is private conversation data; only the title and ownership metadata are persisted.
- Inference runs asynchronously with a 15-second timeout per attempt and 16 KiB combined output limit. Up to two retries use shorter transcripts (2,400 then 1,200 characters) and abortable 250/500 ms delays. Missing binaries, model unavailability, refusals, and non-local envelopes are not retried. New activity, navigation, compaction, and shutdown cancel work; failed/aborted turns and stale results never rename sessions.
- Single-line quotes, bold/backtick wrappers, and a `Title:` prefix are normalized conservatively. Multiline/ambiguous output, terminal controls, and bidirectional controls are rejected. After generation failure, an existing title is retained; an unnamed session receives a bounded prompt-derived title or `Untitled coding session`. Fallbacks filter common sensitive markers, paths, URLs, addresses, numbers, and long opaque strings; this is heuristic, not a guarantee that arbitrary sensitive prose can be detected. Fallback titles are extension-owned and eligible for future model improvements.
- Diagnostics distinguish malformed JSON, invalid titles, non-local envelopes, timeouts, output limits, missing binaries, spawn/stdin failures, context limits, refusals, unavailable models, and other exit failures. `/autoname-status` displays only in-memory category counters (including retained names, fallbacks, and renames); no prompts or raw model errors are logged. Cancellation is not reported as a model failure. Historical malformed JSONL is a separate backfill concern; this extension does not repair session files.
- Existing names are treated as manual unless a persisted ownership record matches the latest session-name entry and session ID. `/name` takes ownership even when its text equals the generated title; clearing a name also protects it. Ownership uses session-wide metadata, while conversation selection remains branch-local. Forks conservatively retain inherited names rather than taking ownership.
- The model receives a concrete-topic prompt with examples, not a request about a session picker. Generic naming metadata (such as `Session Picker Selection` or `Session title remains unchanged`) is rejected with a `generic_title` counter and retried. Unambiguous `Session Picker:`, `Session Picker for`, `Session Title:`, and similar label prefixes are removed; genuine topic names such as `Automatic Pi Session Naming` remain valid. This is a heuristic quality gate, not a guarantee of semantic accuracy.
- A weak existing title is not supplied as an anchor for generation or retained as the failure fallback. Prompt-derived fallbacks remove common conversational request prefixes and trailing filler words. Useful existing titles are retained unless the main topic changes; case/punctuation-only changes are suppressed. Semantic stability otherwise depends on the model.

Offline tests: `node --test .pi/tests/session-autoname.test.mjs`. They use an injected generator and temporary fake CLI, never the real model.

## Current tool surface

Always-on/baseline tools exposed by this project include local coding tools plus:

- `ssh`
- `web_search`, `fetch_content`, `get_search_content`
- `maps`
- `notify`
- `load_tools`

Optional tool groups are loaded with `load_tools({ groups: [...] })` or `/load-tools`:

| Group | Tools |
|---|---|
| `memory` | `memory` |
| `operation_jarvis` | `operation_jarvis_presence`, `operation_jarvis_plugs`, `operation_jarvis_purifier`, `operation_jarvis_media`, `operation_jarvis_security`, `operation_jarvis_automations` |
| `github` | `github_cli` |
| `google` | `google_workspace` |
| `cron` | `jarvis_cron` |
| `reaper` | `reaper_ping`, `reaper_lua` |
| `apple_notes` | `apple_notes_search`, `apple_notes_read`, `apple_notes_write`, `apple_notes_update`, `apple_notes_delete` |
| `browser` | `browser_status`, `browser_open`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_upload`, `browser_key`, `browser_scroll`, `browser_wait`, `browser_extract`, `browser_tabs`, `browser_close` |

`99-lazy-tools.ts` is the registry for group descriptions, prompt snippets, parameter help, and `/load-tools` usage. When the model calls `load_tools`, Pi adds tools without removing existing ones and records the new names in the result. Providers with native deferred loading, such as GPT-5.6, receive the definitions there rather than in a changed initial tool prefix. Other providers receive the normal full active-tool list. Manual `/load-tools` has no tool-result anchor, so it may refresh the provider cache once.

The [JARVIS lazy-execution runtime](PI_LAZY_EXECUTION.md) also accepts valid direct calls to registered optional tools. It activates the group and executes the call once through the usual validation and safety hooks. Unknown, removed, and CLI/SDK-excluded tools remain unavailable.

A direct call may refresh the provider prefix once because Pi keeps an already-used tool's schema immediate rather than deferring it. Use `load_tools` to discover unfamiliar schemas or take advantage of native deferred loading. Stock Pi requires explicit loading.

Optional tools omit active-only `promptSnippet`/`promptGuidelines`; their full group playbooks are returned by model-called `load_tools` (or appended to the original direct call's result after auto-loading) and remain in conversation context. Manual `/load-tools` queues the same hidden playbook for the next user turn. `98-slim-provider-payload.ts` preserves the registry-generated top-level `load_tools` description and also slims schemas nested in OpenAI `additional_tools` and `tool_search_output` items. Startup changes use structured prompt sections, not a forced whole-prompt replacement that would flatten later tool additions into the cached prefix. The smoke test checks these invariants for drift.

Memory is explicit: loading `memory` makes search, remember, update, forget, list, and status available. It does not recall memories automatically or change the system prompt between turns.

Prior Pi/JARVIS sessions are searched directly with baseline coding tools. The project-specific JSONL directory and raw-search workflow belong in ignored `.pi/APPEND_SYSTEM.md`; use `rg -l` to shortlist files, then parse/read only the relevant records.

The `operation_jarvis` group is the household-control suite, distinct from Pi coding, Minecraft, and cron jobs. Focused schemas retain short purpose/parameter descriptions even after provider slimming. No domain playbook is injected into the baseline system prompt. See [Operation JARVIS tools](OPERATION_JARVIS_TOOLS.md) for migration and examples. Existing sessions need an owner-controlled `/reload` or a new session; do not reset or restart live services.

Authenticated GitHub CLI access is intentionally lazy: discover its schema by loading `github`. Known valid direct calls also auto-load on the JARVIS runtime. Ordinary local `git` operations continue to use the baseline coding shell.

## Scheduled-job categories

Load `cron` and use `jarvis_cron`. Each job has one optional category; missing or
blank values display as **Uncategorized**. Labels are whitespace-normalized,
title-cased, and limited to 64 characters. Categories affect organization only,
not scheduling, notifications, execution, job identity, or history.

- Add with `category: "Shopping"` alongside the normal schedule/prompt.
- Filter with `{ action: "list", category: "Shopping" }`.
- Move with `{ action: "set_category", jobId: "gear-hunter", category: "Shopping" }`.
- Clear with `category: ""` or `category: "Uncategorized"` on `set_category`.
- `/jarvis-cron set-category "Keyboard lights" --category "Home Automation"`
  accepts quoted multiword arguments; no shell expressions are evaluated.

Lists group categories alphabetically, with Uncategorized last. The native
read-only Jobs views use the same sections for enabled jobs only. Category edits
require user intent. Existing Pi sessions need an owner-controlled `/reload` or a
new session to load the extended schema; native UI changes require updated app
builds and deployment of the daemon's additive category projection.

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
