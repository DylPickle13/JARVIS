"""Bounded legacy diagnostics. Not a general secret scrubber or audit API."""
from __future__ import annotations

import re
from typing import Any


def _safe_error(value: Any, limit: int = 1000) -> str:
    """Return a bounded diagnostic without exposing local argv/path details."""
    text = str(value or "").strip()
    text = re.sub(r"(/Users/[^\s]+|/private/[^\s]+|/tmp/[^\s]+)", "<local-path>", text)
    return text[-limit:]
