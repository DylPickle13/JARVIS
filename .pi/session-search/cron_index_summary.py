#!/usr/bin/env python3
"""Run session-search indexing and print a concise Discord-friendly summary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".pi" / "session-search" / "session_search.py"
PYTHON = ROOT / ".venv" / "bin" / "python"


def run_json(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(PYTHON), str(RUNNER), "--json", *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"session_search {' '.join(args)} failed with exit code {proc.returncode}: {details}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"session_search {' '.join(args)} returned invalid JSON: {proc.stdout[:1000]}") from exc
    if not payload.get("ok", False):
        raise RuntimeError(str(payload.get("error") or payload))
    return payload


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def main() -> int:
    try:
        indexed = run_json("index")
        status = run_json("status")
    except Exception as exc:
        print(f"❌ Session search indexing failed: {exc}")
        return 1

    indexed_files = int(indexed.get("indexed_files") or 0)
    indexed_chunks = int(indexed.get("indexed_chunks") or 0)
    skipped_files = int(indexed.get("skipped_files") or 0)
    removed_files = int(indexed.get("removed_files") or 0)
    duration = float(indexed.get("duration_seconds") or 0.0)

    total_indexed = int(status.get("indexed_files") or 0)
    total_sessions = int(status.get("session_files") or 0)
    pending = int(status.get("pending_files") or 0)
    changed = int(status.get("changed_files") or 0)

    if indexed_files:
        first_line = f"✅ {plural(indexed_files, 'session')} indexed successfully ({plural(indexed_chunks, 'chunk')})."
    else:
        first_line = "✅ No new sessions to index."

    print(first_line)
    print(
        f"Index now: {total_indexed}/{total_sessions} sessions indexed; "
        f"{pending} pending, {changed} changed."
    )
    print(f"Skipped {skipped_files}; removed {removed_files}; duration {duration:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
