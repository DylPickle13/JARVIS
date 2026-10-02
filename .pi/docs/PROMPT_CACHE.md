# Prompt-cache compatibility (Pi 1.0)

Updated: 2026-10-02 EDT

## Confirmed local invalidator

`98-slim-provider-payload.ts` previously returned `{ systemPrompt }` from
`before_agent_start`. In Pi 1.0 this sets `forceSystemPrompt`. Pi projects the
request onto one leading system message with **all current tools**, dropping the
later system/tool-addition messages. Loading an optional group therefore changed
the initial tool prefix, even though the persisted transcript looked append-only.
Prompt/addendum changes could also rewrite the initial instructions.

A regression test using the actual installed SDK's `session.prompt()` failed
against the old extension and passes after the fix. Inspecting just the persisted
transcript or calling `session.agent.prompt()` misses this projection.

## Current behaviour

- Startup slimming edits only generated `tools`, `rules`, and `docs` sections;
  it never returns a forced system prompt. Pi owns the resulting transcript deltas.
- Exact known lines are shortened. Unknown rules, permission gates, custom
  sections, room-audio guidance and web-tool snippets are preserved. The old
  wholesale `Guidelines:` replacement has been removed rather than adapted to
  erase a modern rules block.
- Both `additional_tools` and `tool_search_output` schemas receive the same
  deterministic slimming as initial tools. Codemode call/return guidance,
  validation constraints, parameter names and literal schema values survive.
- Stock pi-web-access schemas and focused `operation_jarvis_*` schemas remain
  untouched, including their nested descriptions.
- Cache keys, provider capabilities/transports, cache lifetimes, model defaults,
  compaction settings and live services are unchanged.

## Offline verification

```sh
node --test .pi/tests/slim-provider-payload.test.mjs .pi/scripts/tests/pi-codemode.test.mjs
node --test .pi/tests/*.test.mjs
bash .pi/smoke-test.sh
```

The SDK fixture uses an isolated temporary model runtime, inert authentication,
in-memory history, mocked streaming and an inert browser-status tool. No browser,
provider request, real credential or household operation is used. It exercises
actual startup hooks, optional-group activation and a second user turn with a
changed owner addendum. Assertions compare the unchanged historical prefix and
check that tool and prompt updates remain later messages. An offline A/B runs
both OpenAI addition converters against these contexts.

This establishes request-prefix stability, **not a guaranteed server cache hit**.
Expiry, routing, model changes and compaction can still cause misses. A fresh
process or owner-controlled `/reload` is needed to activate the extension; the
first request after changing prompt/schema formatting may itself miss the cache.
Existing sessions were not reloaded or restarted during this change.

## Follow-up measurement

After owner-controlled activation, inspect a small relevant session's assistant
usage immediately before/after its first `load_tools` call. Compare `cacheRead`
with the previous prompt size (`input + cacheRead + cacheWrite`), accounting for
new content, compaction, model changes and idle gaps. Avoid indiscriminate raw
request logging: prompts, tool results and provider headers can be private.

Current Codex catalog entries have no `promptCache` lifetime, so Pi's cache warmer
is not eligible for those models. Do not invent a lifetime or change cache keys
to hide misses. Only consider a live transport A/B if misses persist after this
fix, with isolated synthetic prompts and explicit awareness of inference usage.
