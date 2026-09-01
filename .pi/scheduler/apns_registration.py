#!/usr/bin/env python3
"""Fixed stdin/stdout APNs device-registration boundary for the JARVIS apps.

This command is intended to run as one fixed SSH child command. It accepts one
small JSON object, never logs token material, performs an idempotent private
scheduler-database update, emits one bounded acknowledgement, and exits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __package__:  # pragma: no cover
    from . import runner as package_runner  # type: ignore
else:
    package_runner = None

MAX_INPUT_BYTES = 4096


def _load_runner():
    # Direct script execution has no package context.
    if package_runner is not None:
        return package_runner
    import importlib.util

    path = Path(__file__).with_name("runner.py")
    spec = importlib.util.spec_from_file_location("jarvis_apns_registration_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Notification registration is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Notification registration body is invalid")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Notification registration body must be an object")
        result = _load_runner().register_notification_device(payload)
        encoded = json.dumps(result, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode("utf-8")) > 1024:
            raise RuntimeError("Notification registration acknowledgement is invalid")
        print(encoded)
        return 0
    except Exception as exc:  # noqa: BLE001
        # Runner sanitization deliberately removes secret-like assignments and
        # local paths. Validation errors never contain the submitted token.
        try:
            message = _load_runner().sanitize_text(exc)
        except Exception:  # noqa: BLE001
            message = "Notification registration failed"
        print(json.dumps({"ok": False, "error": message[:160]}, separators=(",", ":")), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
