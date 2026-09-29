# oMLX bridge

Entry point: `.pi/extensions/01-omlx.ts` (renamed from the longer provider/setup/recovery filename).
Shared modules: `lib/omlx-seeds.ts`, `lib/omlx-catalog.ts`, `lib/omlx-stream.ts`, and `lib/omlx-recovery.ts`.

## Configuration

Values come from the process environment, then the nearest ancestor `.env`. Existing provider IDs and model IDs remain unchanged.

| Setting | Purpose |
|---|---|
| `OMLX_BASE_URL` | `omlx` endpoint; falls back to `JARVIS_VOICE_BASE_URL`, then localhost:8000 |
| `OMLX_64_BASE_URL` | `omlx-64` endpoint; defaults to localhost:8000 |
| `OMLX_API_KEY` | Shared key; falls back to `JARVIS_VOICE_API_KEY`, then the dummy `local` key |
| `OMLX_64_API_KEY` | Optional separate key for `omlx-64`; otherwise uses the shared key |
| `OMLX_ADMIN_SESSION` | Optional `omlx_admin_session` cookie **value** for `omlx` |
| `OMLX_64_ADMIN_SESSION` | Optional separate admin session cookie value for `omlx-64` |
| `OMLX_STREAM_FIRST_DELTA_TIMEOUT_MS` | Request-to-first-meaningful-delta timeout, including connection/model load/prefill; default 120000; 0 disables |
| `OMLX_64_STREAM_FIRST_DELTA_TIMEOUT_MS` | Optional host-specific timeout; blank inherits the shared setting |
| `PI_OFFLINE` | `1`, `true`, or `yes` disables extension discovery, including explicit status refresh |

Admin cookies are optional. oMLX admin endpoints can require cookie authentication even when the API bearer key is valid. Without admin access, public model metadata remains usable, and `/omlx-status` explains the limitation. No automatic admin login, cookie harvesting, server configuration writes or load/unload API calls occur. Keep cookie values and keys only in private configuration, never in git. Restart/reload the extension to reread credentials.

## Discovery and cache

- Providers register synchronously using cached models or verified seed definitions. Startup performs no blocking network discovery.
- Discovery starts 500 ms after `session_start`, and runs through Pi's legacy `refreshModels` contract when the model registry refreshes (including `/model`). Each host refreshes independently, with per-host in-flight coalescing.
- Public `/v1/models/status` supplies the catalog; `/v1/models` is the fallback and architectural-limit source. Hidden models and explicitly non-chat model types (embeddings, rerankers, document converters, etc.) are excluded.
- Effective context limits prefer explicit per-model admin settings, then model-status limits, then global admin defaults, then model-list metadata, then last-known/seed limits. Architectural limits clamp larger values when available. Output limits similarly prefer per-model settings, public status, global defaults, then cached/seed limits.
- Unknown models without usable context/output limits are skipped with a diagnostic, rather than assigned invented large budgets. A failed or unusable empty discovery retains the last-known catalog; it does not erase offline models.
- Whole normalized catalogs are cached atomically at `.pi/runtime/omlx-catalog.json` (0600). Endpoint changes invalidate matching snapshots. Secrets, headers, cookies, inference payloads and model responses are never cached.
- The old `.pi/runtime/omlx-context-windows.json` is read for one-way migration; it is not deleted or rewritten.
- `source=live` means the snapshot came from a live discovery, not that the server is guaranteed currently online. Check the last attempt/error/success timestamps. Loaded flags and memory figures are last-reported values, not polling telemetry.

## Request behavior

Every model receives Pi's compatibility flags for non-developer roles and the explicit `max_tokens` output-limit field. Verified Qwen overrides preserve our existing reasoning history and Qwen3.8 effort mappings. Other models use advertised on/off controls or effort vocabularies; unknown templates are not guessed from names. Architectural thinking capability is distinct from whether thinking defaults on. Discovery never changes the user's selected thinking level.

Streaming delegates directly to Pi's concrete OpenAI implementation, retaining request/response/stream instrumentation, tool conversion, image conversion, usage accounting and cancellation. The first-delta watchdog ignores start/keepalive events, clears on meaningful text/thinking/tool progress, and never transparently replays a request. It is not an inactivity watchdog after the first meaningful delta. Pi's normal error retry policy remains Pi-owned.

## Diagnostics

- `/omlx-status`: immediate UI-only summary of endpoints, catalog origin, limits, loaded counts, reported model memory, current thinking selection, forced template keys and recovery state.
- `/omlx-status --refresh`: live discovery first, unless offline; respects cancellation.

Diagnostics do not enter model context. Raw provider failures and complete prompts are not logged by this extension; ordinary session errors remain visible through Pi. The display explains missing admin access and models skipped for missing limits.

## Recovery and limitations

- oMLX prompt-overflow, prefill memory-guard and recognized process-memory watermark errors are normalized for Pi's context-overflow recovery. Unrelated failures are not reclassified.
- Overflow compaction uses a local heuristic checkpoint rather than calling the overloaded model. Recent user constraints, latest request, modified files and recent progress get priority. All earlier raw model-context messages are discarded; original session history remains on disk.
- Emergency summaries obey both a character cap and a conservative model-agnostic estimated token budget (default ceiling 2500 tokens and 8% of model context). This is not an exact tokenizer guarantee, nor does it account for all system/tool prompt overhead. Heuristic extraction can lose details; unclear completion state must be verified before repeating side-effecting work.
- One continuation per user request is allowed after a successful stop containing no visible answer or tool call (empty or thinking-only). That one request asks to disable thinking/preservation. Server-enforced template settings may block the override; a second empty stop warns and does not continue again.
- Visible answers, tool calls/results, aborts, output-length stops, provider errors and already-proposed continuations do not trigger the empty-stop retry. There is no heuristic retry of “let me edit/run...” prose.
- Optional emergency settings: `OMLX_EMERGENCY_COMPACTION_MAX_TOKENS` (2500), `OMLX_EMERGENCY_COMPACTION_MAX_SUMMARY_CHARS` (10000), `OMLX_EMERGENCY_COMPACTION_MAX_URLS` (30), `OMLX_EMERGENCY_COMPACTION_MAX_NOTES` (28). These are process-environment settings.

## Tests and rollout

Offline tests (temporary caches, fake servers/streams, no real household tools):

```sh
node --test .pi/tests/omlx.test.mjs
node --test .pi/tests/*.test.mjs
```

Tests cover authenticated discovery, admin-cookie scoping, host isolation, limits, filtering, caches/migration, offline startup, thinking overrides, bounded retries, emergency context projection, cancellation, stream timeout and actual Pi request serialization against a local fixture HTTP server. `.pi/smoke-test.sh` includes the oMLX tests.

Opt-in live checks:

```sh
node .pi/scripts/smoke-omlx.mjs                    # discovery only; temporary cache
node .pi/scripts/smoke-omlx.mjs --generate         # inference on already-loaded models
node .pi/scripts/smoke-omlx.mjs --generate --allow-on-demand
```

The last option permits normal inference to load a model when none is already loaded; it does not call admin load/unload endpoints. Generation tests use harmless fixed prompts, synthetic echo tool results and a synthetic image. They never execute real model-requested tools. Unavailable hosts are explicitly skipped. No live memory-exhaustion/context-overflow stress test is performed.

Use `/reload` or a new Pi process to activate the rename and code changes in an existing session. No service restart is required.
