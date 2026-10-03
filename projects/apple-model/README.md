# apple-model

Standalone, on-device Apple Foundation Models CLI for **text + image input**.
No Pi dependency, API keys, HTTP server, external package dependencies, tools,
persistent transcript, or cloud fallback. Every `ask` creates a fresh session.

## Requirements

- macOS 27+ and an Xcode/Swift 6.4 SDK with FoundationModels image attachments.
- Supported Apple silicon with Apple Intelligence enabled and model assets downloaded.
- `SystemLanguageModel.default` available; `vision` capability required for images.

Initial Apple Intelligence setup/model downloads may require a network connection.
The application itself uses only `SystemLanguageModel.default`, never a cloud model.
It does not implement microphone/camera capture or save prompts/responses to disk.
Shell history and callers may still record command-line arguments; pipe sensitive text.

## Build and install

```bash
cd /Users/dylanrapanan/JARVIS/projects/apple-model
bash scripts/install.sh
```

Builds `bin/apple-model` and symlinks `~/.local/bin/apple-model` to it. The installer
refuses to overwrite unrelated files. Rebuilding updates the installed command.
This machine's interactive zsh already adds `~/.local/bin` to PATH.
For other shells:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

For launchd, cron, or applications without a shell PATH, use the absolute executable:

```text
/Users/dylanrapanan/JARVIS/projects/apple-model/bin/apple-model
```

An alternate installation directory can be set with `APPLE_MODEL_BIN_DIR`.
Build only: `bash scripts/build.sh`. To uninstall, remove the installed symlink.
The parent JARVIS repository tracks this package's source, scripts, documentation,
and tests. Generated `.build/` and `bin/` directories remain ignored; rebuild the
executable after cloning.

## Repository integration

This package stays standalone under `projects/apple-model/`. Pi-specific adapters
belong under `.pi/`; Operation JARVIS services can invoke the CLI without owning
its implementation.

The [Pi session-naming extension](../../.pi/extensions/49-session-autoname.ts)
invokes this package's `bin/apple-model` directly, resolving the path relative to
the extension. It does not require the `~/.local/bin` symlink or a shell PATH.
Building the CLI is optional for normal Pi operation; without it, session naming
uses its bounded fallback. See the [rebuild guide](../../.pi/docs/REBUILD_FROM_SCRATCH.md#6a-build-the-optional-apple-model-cli).

## Examples (from any directory)

```bash
apple-model status
apple-model status --json
apple-model ask 'Explain DNS briefly.'
cat notes.txt | apple-model ask 'Summarize the supplied notes.'
apple-model ask --instructions 'Be concise.' --max-tokens 128 'What is a semaphore?'
apple-model ask --image ~/Pictures/snapshot.jpg 'Describe what is visible.'
apple-model ask --image before.png --image after.png 'What changed between these images?'
apple-model ask --stream 'Write a short story.'
apple-model ask --json 'Explain DNS.'
apple-model ask --json --stream 'Explain DNS.'
```

`--image` accepts local image files decodable by ImageIO (e.g. JPEG/PNG/HEIC),
up to eight per request. Relative paths are relative to the caller's working
directory. Images are attached through native `Attachment<ImageAttachmentContent>`,
not represented by filenames in the text prompt. Orientation comes from the file.
Multi-frame/animated images are rejected rather than silently dropping frames.
Actual capacity depends on the model/context; eight attachments is a CLI limit,
not a guarantee that every combination will fit.

The public SDK inspected here exposes image attachments, **not native audio/video
attachments**. For video, extract selected frames separately and supply them as
images; the model will see only those frames, not full video, motion, or audio.
Speech must be transcribed separately. Neither preprocessing step is implemented
by this CLI. It is not an always-on monitor or a reliable standalone security alarm.

## Programmatic invocation

```python
import json
import subprocess

result = subprocess.run(
    ['/Users/dylanrapanan/JARVIS/projects/apple-model/bin/apple-model',
     'ask', '--json', '--image', '/absolute/path/snapshot.jpg',
     'Describe this scene briefly.'],
    input='', text=True, capture_output=True, check=True, timeout=60,
)
print(json.loads(result.stdout)['text'])
```

Use subprocess argument arrays (not shell interpolation). Pipe text with stdin;
close stdin after writing so generation can start. In noninteractive contexts,
stdin is consumed until EOF; use a closed pipe or `/dev/null` when there is no input.
`--stdin` explicitly enables input reading even in a terminal.

### Output contract

- Default: complete text followed by newline.
- `--json`: one JSON object with `text`, `backend`, and `localOnly`.
- `--stream`: incremental text followed by newline.
- `--stream --json`: newline-delimited JSON events:
  `{"type":"delta","text":"..."}` followed by
  `{"type":"done","text":"complete response"}`.
- Runtime failures: exit 1, diagnostic on stderr. In JSON mode this is an error
  object; JSON streaming instead emits a terminal `error` event on stdout and
  does not emit `done`. Argument parsing failures are plain stderr diagnostics.
- `status --json` reports availability, API capabilities, and context size;
  an unavailable model is a valid status response, while `ask` fails.
- Ctrl-C/SIGINT or SIGTERM terminates the process. There is no background worker.

JSON mode is an **output envelope**, not guided/validated JSON generation by the
model. Text inside the envelope can be arbitrary. Applications must validate model
judgments before using them for actions. No shell/tool execution is provided.

## Runtime limits and identity

On the tested machine, the framework reported:

- Context: **8,192 tokens**.
- Vision, guided generation, and tool calling: available.
- Reasoning: unavailable.

The CLI currently exposes text/image prompting, not tools or guided generation.
It defaults to 1,024 maximum response tokens and accepts `--max-tokens 1..2048`.
This is an application output cap, **not** a published model output limit.

macOS 27’s FoundationModels framework also exposes
`PrivateCloudComputeLanguageModel`. It is a separate server-side/PCC route with
larger context and stronger reasoning, but it requires network access, has daily
usage limits/eligibility, and is deliberately not used or imported by this CLI.

Instructions, prompt, attachments, and output share the model's context budget.
There is no automatic summarization, hidden history, or silent text truncation;
framework context/guardrail errors propagate to the caller.

On this Mac, `SystemLanguageModel.default.variant.displayName` reports
**AFM 3 Core Advanced**. The public SDK also names the two on-device variants
`AFM 3 Core` and `AFM 3 Core Advanced`; the runtime selects the backing variant
rather than this CLI choosing arbitrary weights. The exact weights, model build,
quantization, and CPU/GPU/Neural Engine allocation remain unexposed and can change
with OS/model-asset updates. `status --json` reports the runtime variant.

## Tests

```bash
python3 tests/smoke.py
```

Uses the actual local model and temporary synthetic red/blue PNGs. Tests text,
stdin, JSON, both streaming formats, single/multiple images, bad arguments/files,
oversized-input error propagation, and SIGINT. It invokes the binary from `/tmp`.
The oversized synthetic prompt triggered an Apple safety rejection in the initial
run, before a context-overflow error; this test does not prove exact token accounting.
An unavailable-model condition has a runtime guard but was not exercised by disabling
Apple Intelligence. Image semantic checks may fail if model behavior changes.
