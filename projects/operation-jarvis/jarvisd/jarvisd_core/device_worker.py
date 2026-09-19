"""Explicit private worker lifecycle; imports never load configuration or do I/O.

This local executable is not an API/authentication boundary. Only the daemon
routes admitted device actions here. It must never import the public jarvis CLI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from urllib.request import Request, urlopen

from .commands import PURIFIER_SETTINGS, PURIFIER_POWER_STATES
from .device_vendor import DeviceVendorAdapter


HANDLERS = MappingProxyType({
    "plug-list": "handle_plug_list", "plug-status": "handle_plug_status",
    "plug-on": "handle_plug_on", "plug-off": "handle_plug_off",
    "plug-toggle": "handle_plug_toggle", "purifier-status": "handle_purifier_status",
    "purifier-set": "handle_purifier_set", "purifier-status-all": "handle_purifier_collection",
    "status": "handle_local_status",
})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--operation-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for action in HANDLERS:
        sub = subparsers.add_parser(action, allow_abbrev=False)
        if action == "status":
            sub.add_argument("--no-cast", action="store_true", required=True)
        elif action.startswith("plug-"):
            sub.set_defaults(plug_timeout=30.0, discovery_target=None)
            if action != "plug-list":
                sub.add_argument("plug")
            if action in {"plug-on", "plug-off", "plug-toggle"}:
                sub.add_argument("--expected-host", required=True)
        else:
            sub.set_defaults(purifier_timeout=150.0)
            if action != "purifier-status-all":
                sub.add_argument("--purifier", default=None)
            if action in {"purifier-status", "purifier-status-all"}:
                sub.add_argument("--retry-cooldown", action="store_true")
            else:
                sub.add_argument("--expected-cid", required=True)
                sub.add_argument("setting", choices=PURIFIER_SETTINGS)
                sub.add_argument("value", nargs="*")
                sub.add_argument("--level", type=int, default=None)
                sub.add_argument("--state", choices=PURIFIER_POWER_STATES, default=None)
                sub.add_argument("--minutes", type=int, default=None)
                sub.add_argument("--room-size", type=int, default=None)
    return parser


def load_environment(project_root: Path, operation_root: Path, env: dict[str, str]) -> None:
    """Match the legacy CLI's explicit env precedence, including export lines."""
    for path in (project_root / ".env", operation_root / ".env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if not key or key in env:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            env[key] = value


class LifecycleBridge:
    """Existing best-effort lifecycle events, not a new command audit store."""
    def __init__(self, env, *, open_url=urlopen):
        self.env = env
        self.open_url = open_url

    def __call__(self, event_type, *, action, ok=None, summary="", error=None, artifacts=None, data=None):
        if self.env.get("JARVIS_EMIT_EVENTS", "1").lower() in {"0", "false", "no", "off"}:
            return
        base_url = self.env.get("JARVISD_URL", "http://127.0.0.1:8790").rstrip("/")
        if not base_url:
            return
        token = self.env.get("JARVISD_EVENT_TOKEN") or self.env.get("JARVIS_API_TOKEN")
        payload = {"source": "operation-jarvis", "eventType": event_type, "action": action,
                   "ok": ok, "summary": summary, "error": error, "artifacts": artifacts or [],
                   "data": data or None, "at": dt.datetime.now(dt.timezone.utc).isoformat()}
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if token:
            headers["x-jarvis-token"] = token
        try:
            request = Request(f"{base_url}/api/jarvis/events", data=body, headers=headers, method="POST")
            with self.open_url(request, timeout=2.0):
                pass
        except Exception:
            pass


def execute(args, *, adapter: DeviceVendorAdapter, emit) -> tuple[int, dict]:
    action = args.command
    handler = HANDLERS[action]  # Closed even for callers not using the parser.
    emit("action.start", action=action, summary=f"Starting {action}.")
    try:
        if action == "purifier-set" and (not args.expected_cid or args.purifier != args.expected_cid):
            raise ValueError("Purifier write requires the exact admitted CID")
        if action in {"plug-on", "plug-off", "plug-toggle"} and not args.expected_host.strip():
            raise ValueError("Plug write requires an admitted host")
        payload = getattr(adapter, handler)(args)
        payload.setdefault("operationRoot", str(args.operation_root))
        payload.setdefault("summary", payload.get("stdout") or "Operation JARVIS action completed.")
        emit("action.complete", action=action, ok=bool(payload.get("ok", True)),
             summary=str(payload.get("summary") or "Operation JARVIS action completed."),
             artifacts=payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else [],
             data={"device": payload.get("device")})
        return 0, payload
    except KeyboardInterrupt:
        code, message = 130, "Cancelled."
    except subprocess.TimeoutExpired as exc:
        code, message = 124, f"command timed out: {exc}"
    except Exception as exc:
        code, message = 1, str(exc)
    # New private binding arguments must not leak through vendor timeout/error
    # text into public errors or the legacy event bridge.
    for field in ("expected_cid", "purifier"):
        selector = getattr(args, field, None)
        if isinstance(selector, str) and selector:
            message = message.replace(selector, "[private device]")
    emit("action.error", action=action, ok=False, summary=message, error=message)
    return code, {"ok": False, "action": action, "error": message}


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    load_environment(args.project_root, args.operation_root, os.environ)
    adapter = DeviceVendorAdapter(operation_root=args.operation_root, project_root=args.project_root,
                                  env=os.environ, run=subprocess.run)
    code, payload = execute(args, adapter=adapter, emit=LifecycleBridge(os.environ))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code
