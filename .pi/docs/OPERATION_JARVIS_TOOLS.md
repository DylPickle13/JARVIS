# Operation JARVIS household-control tools

Pi remains a coding harness, but this project also controls household systems.
The single optional group is `operation_jarvis`:

```text
load_tools({ groups: ["operation_jarvis"] })
```

| Tool | Actions | Boundary |
|---|---|---|
| `operation_jarvis_plugs` | list, status, on, off, toggle | Configured local Kasa aliases; electrical power, not playback |
| `operation_jarvis_purifier` | list, status, status-all, set | Existing VeSync adapter; one selected device per write |
| `operation_jarvis_media` | status, volume, mute, stop, youtube, play-url, speak, spotify-* | Cast/Spotify playback and speaker speech; not camera audio |
| `operation_jarvis_security` | devices, status, capabilities | Configured Tapo aliases; read-only and on demand |
| `operation_jarvis_automations` | list, describe, enable, disable | Explicit Tapo CLOUD rules; guarded automation changes, not shortcut execution or Pi jobs |

`45-jarvis.ts` wraps existing `jarvis.py` commands. `48-jarvis-security.ts` wraps
the existing `security/security` isolated Python launcher. No daemon, SDK update,
polling, backend control route or service restart is introduced.

## Compact discovery

The group catalogue and one short household-routing clause live in the existing
lazy loader. No additional APPEND_SYSTEM section, intent classifier, prompt-time
rule inventory or per-tool prompt injection is added. Detailed guidance arrives
only in the loader result (or the existing direct-call auto-load result).

The provider slimmer preserves the focused tools' concise descriptions and
parameter meanings, including units and safety distinctions. These schemas are
absent from the baseline until loaded. They are also preserved in deferred
OpenAI tool outputs. Names, revisions, inventory and automation state are read
on demand, not hardcoded into the system prompt. The loader's prompt metadata
is 1,833 characters versus 1,919 before; its post-slimming Chat schema is 1,450
versus 1,514. These are component character counts, not full-prompt token counts.

## Examples (synthetic selectors)

```text
operation_jarvis_plugs({ action: "on", plug: "example-light" })
operation_jarvis_purifier({ action: "set", setting: "mode", value: "auto" })
operation_jarvis_media({ action: "speak", text: "Ready, sir." })
operation_jarvis_security({ action: "status", device: "example-sensor" })
operation_jarvis_automations({ action: "describe", name: "Example protocol" })
```

Discover unclear selectors first. Purifier `list` discovers devices without
refreshing readings; `status-all` explicitly reads them. `retryCooldown` is only
an owner-authorized recovery read, never an automatic retry or write bypass.

## Security guarantees and limits

- Fixed launcher/argv, no shell, credential/host/path overrides or arbitrary RPC.
- Minimal subprocess environment; stderr is discarded. 256 KiB streaming stdout
  bound, 120-second deadline per invocation, cancellation kills/reaps the dedicated
  CLI process group including workers. No automatic retries.
- Concurrent security calls within the extension fail busy; the CLI also retains
  its cross-process device/account locks. There is no queued command replay.
- Output is allowlisted: no raw device identifiers/locations, credentials, raw
  rules, private backup paths, arbitrary nested payloads or firmware inventory.
  Configured aliases, rule names, rule references/revisions and sensor readings
  are still private household data in the Pi conversation.
- Sensors remain hub snapshots, with radio freshness unknown and security
  assessment not assessed. An enabled rule does not prove a home is secure.
- `smart-actions describe` returns a partial allowlisted configuration summary
  without generating a raw export. Unknown trigger combination codes and action
  semantics remain uninterpreted; configured alarm parameters are not physical
  acceptance. Unknown schedule details stay unknown.
- Full rule CRUD, shortcut execution, chime/alarm actions, camera media, recording
  changes and archive downloads are deliberately not exposed by these tools.

## Automation changes

Enable/disable performs a fresh list, unique case-insensitive exact-name match,
and a fresh description with matching revision. Ambiguity or concurrent edits
fail closed. Already-desired state is a read-only no-op.

Changes are live in both interactive and headless sessions (owner approval,
2026-09-20; the former commissioning gate was removed). Enabling can cause
immediate or later actions; disabling does not stop an already sounding alarm.
The CLI checks the exact revision again, saves private backups, sends at most one
mutation and verifies readback. This is not a server-atomic conditional write: avoid
simultaneous app edits. Timeout/cancel/malformed reply after invocation is an
unknown outcome, not permission to retry or roll back. Inspect current state and
private recovery backups before further action.

## Migration and activation

The model-visible `jarvis` group/tool and `smart_plug` tool are retired, with no
duplicate aliases in the catalogue. CLI commands and backend routes remain
unchanged. Map old calls as follows:

- `smart_plug action=on` → `operation_jarvis_plugs action=on`.
- `jarvis action=purifier-status` → `operation_jarvis_purifier action=status`.
- `jarvis action=cast-status` → `operation_jarvis_media action=status`.

Advanced CLI-only options (arbitrary config paths, host/port overrides, discovery
maintenance and tuning timeouts) are not part of the everyday tool schemas.

Use an owner-controlled `/reload` or start a new Pi session. Existing live sessions
retain their old schemas until then; no live sessions/services were automatically
reloaded or restarted. Old tool calls in conversation history may remain historical
text but are not callable definitions after reload.

## Verification

Offline, no hardware:

```bash
node --test .pi/scripts/tests/jarvis-purifiers.test.mjs \
  .pi/tests/operation-jarvis-security.test.mjs \
  .pi/tests/slim-provider-payload.test.mjs \
  .pi/scripts/tests/pi-lazy-tools.test.mjs
(cd projects/operation-jarvis/security && \
  .venv-313/bin/python -m unittest test_security_smart_actions test_security_cli -q)
```

Opt-in local-model routing evaluation (Qwen 3.6 only for acceptance):

```bash
node .pi/scripts/eval-operation-jarvis.mjs --model Qwen3.6-35B-A3B-4bit
```

The evaluator submits real post-slimming schemas to the existing loopback model
endpoint. It executes only the schema loader; household execute functions are
never invoked. It includes actual loader guidance and synthetic list results for
safe preflights. It is a bounded routing sample, not a full Pi integration or
physical acceptance test. No service configuration is changed.

2026-09-20 verification:
- 57 Node tests passed, including SDK/deferred loading, renamed group, fixed argv,
  stale revisions, privacy, uncertainty, output
  limits and process-group cancellation.
- 171 security CLI/Smart Actions Python tests passed.
- Qwen3.6-35B-A3B-4bit: final 16/16 discovery/action/boundary checks passed,
  including an owner-supplied protocol name, real loader guidance, synthetic
  preflight results and **zero hardware calls**. A private test name can be supplied
  through `OPERATION_JARVIS_EVAL_PROTOCOL`; it is not embedded in code/prompts.
  Earlier probes exposed malformed calls without loader-result context and
  misrouted bare protocol questions; the final short routing clause explicitly
  covers named door/security protocols, including explanations. This small sample
  does not establish perfect model reliability.
- Broader jarvisd verification: 612/612 passed. At the owner's request, mobile
  restart tests now expect ten sessions, ten unique attachments, and terminal
  groups of 1/3/3/3. The tenth session is covered by new/idle and busy guards.
  No services were restarted. The pre-existing control_runtime.py finally-return
  SyntaxWarning remains.
