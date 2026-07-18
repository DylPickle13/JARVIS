# System Prompt Token Audit Workflow

Updated: 2026-06-24 EDT

This note records how to measure a Pi agent system-prompt footprint for future slimming work.

## What is being measured

A Pi provider request usually contains:

- `instructions`: system/developer/project prompt text after extensions modify it.
- `tools`: provider-visible tool schemas.
- `input` / messages: the user prompt and conversation context.

Provider `usage.input` is the closest exact token count, but it includes the user message and any conversation context. For a fresh first turn, the user message is usually small, so `usage.input` is a good practical measure of the static prompt/tool overhead.

For breakdowns, capture the provider payload before it is sent, then inspect char sizes for `instructions`, `tools`, and individual schemas. Char counts are not exact tokens, but `chars / 4` is a useful rough estimate.

## Method A — exact first-turn usage from session logs

Use this after a real first turn has completed.

```bash
python3 - <<'PY'
import json
from pathlib import Path

session_root = Path.home() / ".pi/agent/sessions"
current_cwd = str(Path.cwd())

candidates = []
for path in session_root.glob("*/*.jsonl"):
    try:
        header = json.loads(path.open().readline())
    except Exception:
        continue
    if header.get("cwd") == current_cwd:
        candidates.append(path)

session = max(candidates, key=lambda p: p.stat().st_mtime)
print("session", session)

for line_no, line in enumerate(session.open(), 1):
    event = json.loads(line)
    if event.get("type") != "message":
        continue
    msg = event.get("message") or {}
    if msg.get("role") == "assistant" and msg.get("usage"):
        usage = msg["usage"]
        effective_input = (usage.get("input") or 0) + (usage.get("cacheRead") or 0) + (usage.get("cacheWrite") or 0)
        print("line", line_no)
        print(json.dumps(usage, indent=2))
        print("effectiveInput", effective_input)
        break
PY
```

Notes:

- `usage.input` is uncached input for that request.
- `effectiveInput = input + cacheRead + cacheWrite` is useful when prompt caching is active.
- This is exact provider-reported usage, but it includes the user message and any prior conversation context.

## Method B — capture provider payload for component breakdown

Use this to see what is making the prompt large.

Create a temporary capture extension **inside `.pi/extensions` with a late lexicographic name** so it runs after slimming/filtering extensions such as `98-slim-provider-payload.ts` and `99-lazy-tools.ts`.

> Important: this extension intentionally exits Pi before the provider request is sent. Remove it immediately after the capture or all future Pi requests will abort.

```bash
cat > .pi/extensions/zzzz-capture-provider-payload.ts <<'TS'
import { writeFileSync } from 'node:fs';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

export default function captureProviderPayload(pi: ExtensionAPI) {
  pi.on('before_agent_start', (event) => {
    const opts: any = (event as any).systemPromptOptions;
    writeFileSync('/tmp/pi-system-prompt-meta.json', JSON.stringify({
      systemPromptChars: event.systemPrompt.length,
      selectedTools: opts?.selectedTools,
      selectedToolsCount: opts?.selectedTools?.length,
      promptGuidelinesCount: opts?.promptGuidelines?.length ?? null,
      toolSnippetsCount: opts?.toolSnippets ? Object.keys(opts.toolSnippets).length : null,
      skills: opts?.skills?.map((s: any) => s.name) ?? [],
    }, null, 2));
  });

  pi.on('before_provider_request', (event) => {
    writeFileSync('/tmp/pi-provider-payload.json', JSON.stringify((event as any).payload));
    process.exit(42);
  });
}
TS

rm -f /tmp/pi-system-prompt-meta.json /tmp/pi-provider-payload.json
(pi -p --no-session "system prompt audit probe" \
  >/tmp/pi-prompt-capture.out 2>/tmp/pi-prompt-capture.err; echo exit:$?)

rm -f .pi/extensions/zzzz-capture-provider-payload.ts
```

Expected exit code is `42`.

If the extension is not removed, remove it manually:

```bash
rm -f .pi/extensions/zzzz-capture-provider-payload.ts
```

## Analyze the captured payload

```bash
python3 - <<'PY'
import json
from pathlib import Path

payload_path = Path('/tmp/pi-provider-payload.json')
meta_path = Path('/tmp/pi-system-prompt-meta.json')

payload = json.loads(payload_path.read_text())
meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

def compact_json_chars(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))

def tool_name(tool):
    return tool.get('name') or tool.get('function', {}).get('name') or tool.get('toolSpec', {}).get('name')

instructions = payload.get('instructions') or payload.get('system') or ''
tools = payload.get('tools') or []
input_part = payload.get('input') or payload.get('messages') or []
deferred_tools = [
    tool
    for item in input_part if isinstance(item, dict) and item.get('type') == 'tool_search_output'
    for tool in item.get('tools', [])
]

print('## Meta')
print(json.dumps(meta, indent=2))

print('\n## Top-level sizes')
print('instructions chars:', len(instructions), 'rough tokens:', round(len(instructions) / 4))
print('top-level tools chars:', compact_json_chars(tools), 'rough tokens:', round(compact_json_chars(tools) / 4), 'tool count:', len(tools))
print('input/messages chars:', compact_json_chars(input_part), 'rough tokens:', round(compact_json_chars(input_part) / 4))
print('deferred tool count:', len(deferred_tools))
print('full payload chars:', compact_json_chars(payload), 'rough tokens:', round(compact_json_chars(payload) / 4))

print('\n## Tool schema sizes')
rows = sorted(
    ((tool_name(t), compact_json_chars(t)) for t in [*tools, *deferred_tools]),
    key=lambda row: row[1],
    reverse=True,
)
for name, chars in rows:
    print(f'{name:24s} chars={chars:5d} roughTok4={chars/4:6.0f}')

print('\n## Instruction sections')
markers = [
    'Available tools:',
    'Guidelines:',
    'Pi docs only when relevant:',
    '## User/local context',
    '## Helpful Information',
    'Current date:',
    'Current working directory:',
    'Web research workflow:',
]
positions = []
for marker in markers:
    index = instructions.find(marker)
    if index >= 0:
        positions.append((index, marker))
positions.append((len(instructions), 'END'))
positions.sort()

if positions and positions[0][0] > 0:
    print(f'{"prefix":32s} chars={positions[0][0]:5d} roughTok4={positions[0][0]/4:6.0f}')

for idx, (start, marker) in enumerate(positions[:-1]):
    end = positions[idx + 1][0]
    chars = end - start
    print(f'{marker[:32]:32s} chars={chars:5d} roughTok4={chars/4:6.0f}')
PY
```

## Measuring after prompt slimming changes

After editing prompt-slimming files, rerun Method B and compare:

- `instructions chars`
- top-level and deferred tool-schema sizes
- `full payload chars`
- individual tool schema rows

For this project, the relevant slimming files have been:

- `.pi/extensions/98-slim-provider-payload.ts`
- `.pi/extensions/99-lazy-tools.ts`
- `.pi/APPEND_SYSTEM.md`
- `.pi/extensions/01-omlx-provider-setup-and-recovery.ts` for local model/provider registration and recovery behavior

## Last recorded reference point from 2026-06-19

After the SSH schema trim and safe-bundle trim, a fresh baseline capture showed roughly:

- Instructions: `3,083` chars
- Baseline tool schemas: `5,033` chars across 14 tools
- Full provider payload: `8,545` chars
- Rough static prompt/tool baseline: about `~2.1k` token-ish by chars/4

The current 2026-06-24 tool surface also includes always-on `maps`, `minecraft_jarvis`, `ssh`, web/fetch tools, and lazy browser/Discord/Google/phone/session groups. Rerun Method B after prompt-slimming changes to capture a fresh exact component breakdown.

Previous pre-slimming captures were roughly:

- Instructions: `12,025` chars
- Tool schemas: `39,769` chars
- Full prompt-ish overhead: about `~13k` rough tokens

## Caveats

- Do not commit or publish captured provider payloads. They can contain local context, memories, and prompt text.
- The capture command starts a fresh non-session Pi run. It measures the baseline visible tool set, not optional groups loaded in an existing interactive session.
- Baseline currently includes project always-on tools such as `ssh`, web/fetch tools, `minecraft_jarvis`, `maps`, and `load_tools`; use `/load-tools` in an interactive session if you need to measure optional groups separately.
- To measure exact provider tokens, use Method A after a real request. To see what contributes to size, use Method B.
- If prompt caching is active, use `effectiveInput = input + cacheRead + cacheWrite` for full effective input.
- Durable memory is explicit-only and does not mutate the system prompt. Load/search the `memory` tool when a task needs stored context.
- On OpenAI models with native deferred loading, newly loaded schemas appear inside `input` as `tool_search_output` items rather than changing the initial top-level tool prefix.
