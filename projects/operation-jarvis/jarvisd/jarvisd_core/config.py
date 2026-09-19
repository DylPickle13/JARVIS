"""Explicit configuration helpers; no environment files are loaded on import."""
from __future__ import annotations

import os
from pathlib import Path
import sys

def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding the process env."""
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[jarvisd] could not load env file {path}: {exc}\n")


def _find_ancestor(start: Path, marker: str) -> Path | None:
    """Return the nearest ancestor containing ``marker``."""
    for directory in (start, *start.parents):
        if (directory / marker).exists():
            return directory
    return None


def _resolve_jarvis_root(*, source_dir: Path, project_root: Path, project_root_is_explicit: bool) -> Path:
    """Resolve runtime data from an explicit checkout before a user's global .pi directory."""
    if os.environ.get("JARVISD_JARVIS_ROOT"):
        return Path(os.environ["JARVISD_JARVIS_ROOT"]).expanduser().resolve()
    if project_root_is_explicit:
        return project_root
    return _find_ancestor(source_dir, ".pi") or project_root
