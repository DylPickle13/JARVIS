# Optional codemode (Pi 1.0.0)

Enabled in `/Users/dylanrapanan/.pi/agent/settings.json` on mac-mini-64:

```json
{
  "defaultTools": ["+codemode"],
  "codemode": { "mode": "on" }
}
```

This adds orchestration without hiding ordinary tools. New CLI/RPC sessions inherit
it unless their tool selection overrides it. Existing sessions need `/reload` or a
restart; this rollout did not restart any running session or remote service.
SDK sessions must explicitly load Pi's codemode extension, as documented upstream.

## JARVIS integration

- `99-lazy-tools.ts` preserves already-selected codemode at startup and
  `/reset-tools`, without forcing it on when disabled or explicitly excluded.
- `98-slim-provider-payload.ts` retains Pi's appended `Codemode:` call/return-type
  guidance while keeping the original concise tool descriptions.
- Load optional groups **before** starting the script. Pi snapshots callable tools
  at script startup; `load_tools` inside a script does not make newly activated
  tools available until a subsequent script.
- Prefer independent reads, aggregation and filtering. Ordinary tools remain
  appropriate for simple operations and individually reviewed side effects.
  The added system guidance is deliberately one short rule:
  > Codemode: load groups before scripting; use tools.*, return/text(). After one failed correction, use direct tools; check completed actions before retrying.

  Sandbox details remain in Pi's existing tool description, not duplicated in
  the system prompt.
- Nested calls retain tool-call permission gates and exclusions. This is not a
  rollback mechanism or additional security boundary: completed actions survive
  later script failures.

## Verification — 2026-10-01

All seven enabled models completed at least one live read-only test: parallel
fixture reads, filtering to an exact expected result, catching a missing-file
error and successfully reading again. **Qwen3.6 was inconsistent on repetition**:
it passed the first run after self-correction, but a fresh repeat used unavailable
Node `require`, then repeatedly omitted explicit output, exhausting the test's
16-call budget before completing a corrected script. This supports optional
availability, not forcing codemode for that model. JARVIS guidance now emphasizes
explicit output and a bounded retry/direct-tool fallback.

Model switches replayed codemode history in both provider directions
(oMLX → Codex and Codex → oMLX).

| Model | Result |
| --- | --- |
| omlx-64/Qwen3.6-35B-A3B-4bit | Mixed: first run passed after corrections; fresh repeat exhausted the test budget |
| omlx-64/Qwen3.8-27B-4bit | Pass, including return to oMLX history |
| omlx-64/Qwen3.8-27B-Uncensored-MLX-4bit | Pass |
| omlx/Qwen3.5-9B-4bit | Pass on retry; first attempt hit a Metal GPU error before any tool call |
| openai-codex/gpt-6-astra | Pass |
| openai-codex/gpt-6.1-sol | Pass |
| openai-codex/gpt-6-luna | Pass |

This is a bounded compatibility smoke test, not a guarantee for arbitrary scripts,
all switching permutations, every third-party tool, or future model/server updates.
No production device or account operations were used in these tests.

Nine model-free integration tests cover startup/reset, opt-out/exclusion,
optional-group loading, callable snapshots, permission rejection with recovery,
excluded nested tools, cancellation and payload guidance preservation.
A real offline CLI/RPC startup also confirmed codemode alongside the full JARVIS
baseline. Current optional-group regression coverage also lives in
`.pi/tests/lazy-tools.test.mjs`.

## Re-run

From the JARVIS root:

```bash
node --test .pi/scripts/tests/pi-codemode.test.mjs
node .pi/scripts/pi-codemode-smoke.mjs
# Or selected models, in the history-replay order desired:
node .pi/scripts/pi-codemode-smoke.mjs openai-codex/gpt-6-astra omlx/Qwen3.5-9B-4bit
```

The live test uses configured credentials and may incur normal provider usage.
It uses in-memory settings/history, an isolated fixture directory, only the read
and codemode tools, and a fixture-path guard. Results stay under the ignored
`.pi/runtime/codemode-smoke/<timestamp>/` directory. It does not modify saved
model/thinking defaults. `PI_CODEMODE_TEST_TIMEOUT_MS` overrides the 180-second
per-model deadline; `PI_CODEMODE_TEST_RUNTIME` overrides the installed Pi package.

Initial artifacts:
- `.pi/runtime/codemode-smoke/2026-10-01T21-02-15-773Z/`
- `.pi/runtime/codemode-smoke/2026-10-01T21-07-45-130Z/`
- `.pi/runtime/codemode-smoke/2026-10-01T21-10-05-443Z/` (Qwen3.6 repeat failure)

## Disable / rollback

For one invocation:

```bash
pi --exclude-tools codemode
```

For a project, add `"defaultTools": ["-codemode"]` to its settings. To disable the
global default, remove `+codemode` from the global `defaultTools` list (preserving
other entries), then start a new session. Removing a default does not deactivate
an already-active tool on `/reload`.

The prior global settings are backed up at
`.pi/runtime/codemode-smoke/config-backup/agent-settings.before.json`; do not restore
that whole file over unrelated settings changed later.
