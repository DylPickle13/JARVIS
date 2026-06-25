#!/usr/bin/env python3
"""Capture and report Pi provider prompt/tool payload sizes without sending a provider request.

The script temporarily installs a late Pi extension that writes the assembled
provider payload to a private temporary directory, exits before the request is
sent, prints a size report to stdout, and removes all temporary files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

CAPTURE_EXIT_CODE = 42
DEFAULT_PROMPT = "system prompt audit probe"


def find_project_root(explicit: str | None = None) -> Path:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / ".pi" / "extensions").is_dir():
            raise SystemExit(f"Not a Pi project root or missing .pi/extensions: {root}")
        return root

    candidates: list[Path] = []
    candidates.extend([Path.cwd().resolve(), *Path.cwd().resolve().parents])
    try:
        here = Path(__file__).resolve()
        candidates.extend([here.parent, *here.parents])
    except NameError:
        pass

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".pi" / "extensions").is_dir():
            return candidate

    raise SystemExit("Could not find a Pi project root with .pi/extensions. Use --cwd.")


def compact_json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def rough_tokens(chars: int) -> int:
    return round(chars / 4)


def provider_tool_name(tool: Any) -> str | None:
    if not isinstance(tool, dict):
        return None
    if isinstance(tool.get("name"), str):
        return tool["name"]
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    tool_spec = tool.get("toolSpec")
    if isinstance(tool_spec, dict) and isinstance(tool_spec.get("name"), str):
        return tool_spec["name"]
    return None


def flatten_tool_entries(tools: Any, container: str) -> list[tuple[str, int, str]]:
    if not isinstance(tools, list):
        return []

    rows: list[tuple[str, int, str]] = []
    for index, tool in enumerate(tools):
        if isinstance(tool, dict) and isinstance(tool.get("functionDeclarations"), list):
            for declaration in tool["functionDeclarations"]:
                name = declaration.get("name") if isinstance(declaration, dict) else None
                rows.append((str(name or f"{container}[{index}].functionDeclaration"), compact_json_chars(declaration), container))
            continue

        name = provider_tool_name(tool) or f"{container}[{index}]"
        rows.append((name, compact_json_chars(tool), container))
    return rows


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict):
                for key in ("text", "content"):
                    value = part.get(key)
                    if isinstance(value, str):
                        pieces.append(value)
                        break
        return "\n".join(pieces)
    if isinstance(content, dict):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    return ""


def instruction_sources(payload: dict[str, Any]) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []

    instructions = text_from_content(payload.get("instructions"))
    if instructions:
        sources.append(("instructions", instructions))

    system = text_from_content(payload.get("system"))
    if system:
        sources.append(("system", system))

    system_instruction = payload.get("systemInstruction")
    if isinstance(system_instruction, dict):
        parts = text_from_content(system_instruction.get("parts"))
        if parts:
            sources.append(("systemInstruction.parts", parts))

    messages = payload.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"system", "developer"}:
                continue
            text = text_from_content(message.get("content"))
            if text:
                sources.append((f"messages[{index}].{role}", text))

    return sources


def conversation_messages(payload: dict[str, Any]) -> Any:
    if isinstance(payload.get("input"), list):
        return payload["input"]
    messages = payload.get("messages")
    if isinstance(messages, list):
        return [message for message in messages if not (isinstance(message, dict) and message.get("role") in {"system", "developer"})]
    return []


def tool_containers(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    containers: list[tuple[str, Any]] = []
    if isinstance(payload.get("tools"), list):
        containers.append(("tools", payload["tools"]))
    tool_config = payload.get("toolConfig")
    if isinstance(tool_config, dict) and isinstance(tool_config.get("tools"), list):
        containers.append(("toolConfig.tools", tool_config["tools"]))
    return containers


def make_capture_extension(meta_path: Path, payload_path: Path) -> str:
    meta_literal = json.dumps(str(meta_path))
    payload_literal = json.dumps(str(payload_path))
    return f"""import {{ writeFileSync }} from 'node:fs';
import type {{ ExtensionAPI }} from '@earendil-works/pi-coding-agent';

export default function systemPromptSizeCapture(pi: ExtensionAPI) {{
  pi.on('before_agent_start', (event) => {{
    const opts: any = (event as any).systemPromptOptions;
    writeFileSync({meta_literal}, JSON.stringify({{
      systemPromptChars: event.systemPrompt.length,
      selectedTools: opts?.selectedTools,
      selectedToolsCount: opts?.selectedTools?.length,
      promptGuidelinesCount: opts?.promptGuidelines?.length ?? null,
      toolSnippetsCount: opts?.toolSnippets ? Object.keys(opts.toolSnippets).length : null,
      skills: opts?.skills?.map((s: any) => s.name) ?? [],
    }}, null, 2));
  }});

  pi.on('before_provider_request', (event) => {{
    writeFileSync({payload_literal}, JSON.stringify((event as any).payload));
    process.exit({CAPTURE_EXIT_CODE});
  }});
}}
"""


def run_capture(root: Path, prompt: str, pi_bin: str, timeout: int) -> tuple[dict[str, Any], dict[str, Any]]:
    extension_dir = root / ".pi" / "extensions"
    extension_path = extension_dir / f"zzzz-system-prompt-size-capture-{int(time.time() * 1000)}.ts"

    with tempfile.TemporaryDirectory(prefix="pi-system-prompt-size-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        meta_path = temp_dir / "meta.json"
        payload_path = temp_dir / "payload.json"
        extension_path.write_text(make_capture_extension(meta_path, payload_path), encoding="utf-8")
        try:
            result = subprocess.run(
                [pi_bin, "-p", "--no-session", prompt],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            raise SystemExit(f"Pi executable not found: {pi_bin}")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            raise SystemExit(
                f"Pi capture timed out after {timeout}s.\n\nSTDOUT:\n{stdout[-4000:]}\n\nSTDERR:\n{stderr[-4000:]}"
            )
        finally:
            try:
                extension_path.unlink()
            except FileNotFoundError:
                pass

        if result.returncode != CAPTURE_EXIT_CODE:
            raise SystemExit(
                "Pi capture failed before provider-payload capture.\n"
                f"Expected exit code {CAPTURE_EXIT_CODE}, got {result.returncode}.\n\n"
                f"STDOUT:\n{result.stdout[-4000:]}\n\nSTDERR:\n{result.stderr[-4000:]}"
            )
        if not payload_path.exists():
            raise SystemExit("Pi capture exited successfully but did not write payload.json")

        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return payload, meta


def build_summary(payload: dict[str, Any], meta: dict[str, Any], root: Path, prompt: str) -> dict[str, Any]:
    sources = instruction_sources(payload)
    instruction_chars = sum(len(text) for _, text in sources)
    containers = tool_containers(payload)
    tools_chars = sum(compact_json_chars(tools) for _, tools in containers)
    tool_rows: list[tuple[str, int, str]] = []
    for container_name, tools in containers:
        tool_rows.extend(flatten_tool_entries(tools, container_name))
    tool_rows.sort(key=lambda row: row[1], reverse=True)

    convo = conversation_messages(payload)
    convo_chars = compact_json_chars(convo)
    full_payload_chars = compact_json_chars(payload)

    return {
        "projectRoot": str(root),
        "probePrompt": prompt,
        "model": payload.get("model"),
        "instructionSources": [{"source": source, "chars": len(text), "roughTok4": rough_tokens(len(text))} for source, text in sources],
        "instructionsChars": instruction_chars,
        "toolsChars": tools_chars,
        "toolCount": len(tool_rows),
        "conversationChars": convo_chars,
        "fullPayloadChars": full_payload_chars,
        "staticPromptAndToolsChars": instruction_chars + tools_chars,
        "meta": meta,
        "toolRows": [{"name": name, "chars": chars, "roughTok4": rough_tokens(chars), "container": container} for name, chars, container in tool_rows],
    }


def print_text_report(summary: dict[str, Any]) -> None:
    def line(label: str, chars: int) -> str:
        return f"{label:32s} chars={chars:6d} roughTok4={rough_tokens(chars):5d}"

    print("Pi system prompt size audit")
    print(f"Project: {summary['projectRoot']}")
    if summary.get("model"):
        print(f"Model:   {summary['model']}")
    print(f"Probe:   {summary['probePrompt']}")
    print()

    print("Top-level sizes")
    print(line("instructions/system", summary["instructionsChars"]))
    print(line("tool schemas", summary["toolsChars"]) + f"  toolCount={summary['toolCount']}")
    print(line("conversation/user messages", summary["conversationChars"]))
    print(line("full provider payload", summary["fullPayloadChars"]))
    print(line("static prompt + tools", summary["staticPromptAndToolsChars"]))
    print()

    meta = summary.get("meta") or {}
    selected = meta.get("selectedTools") if isinstance(meta, dict) else None
    if selected:
        print(f"Selected tools ({len(selected)}): {', '.join(selected)}")
    elif isinstance(meta, dict) and meta.get("selectedToolsCount") is not None:
        print(f"Selected tool count: {meta.get('selectedToolsCount')}")
    if isinstance(meta, dict):
        extras = []
        if meta.get("promptGuidelinesCount") is not None:
            extras.append(f"promptGuidelines={meta.get('promptGuidelinesCount')}")
        if meta.get("toolSnippetsCount") is not None:
            extras.append(f"toolSnippets={meta.get('toolSnippetsCount')}")
        if extras:
            print("Prompt metadata: " + ", ".join(extras))
    print()

    if summary["instructionSources"]:
        print("Instruction sources")
        for source in summary["instructionSources"]:
            print(f"{source['source']:32s} chars={source['chars']:6d} roughTok4={source['roughTok4']:5d}")
        print()

    print("Tool schema sizes")
    for row in summary["toolRows"]:
        print(f"{row['name']:28s} chars={row['chars']:6d} roughTok4={row['roughTok4']:5d}")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture the assembled Pi provider payload, abort before sending it, and print prompt/tool size estimates.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help=f"Probe prompt to use. Default: {DEFAULT_PROMPT!r}")
    parser.add_argument("--cwd", help="Pi project root. Defaults to nearest ancestor with .pi/extensions.")
    parser.add_argument("--pi-bin", default=shutil.which("pi") or "pi", help="Pi executable. Default: pi from PATH.")
    parser.add_argument("--timeout", type=int, default=180, help="Capture timeout in seconds. Default: 180.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON to stdout instead of text.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    root = find_project_root(args.cwd)
    payload, meta = run_capture(root=root, prompt=args.prompt, pi_bin=args.pi_bin, timeout=args.timeout)
    summary = build_summary(payload=payload, meta=meta, root=root, prompt=args.prompt)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_text_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
