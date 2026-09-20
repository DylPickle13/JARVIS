#!/usr/bin/env python3
"""jarvisd — the shared Operation JARVIS control backend.

A stdlib-only HTTP daemon (ThreadingHTTPServer), independent of its native
iOS/watchOS clients. It aggregates cached state, runs allowlisted device workers,
ingests events, and manages registered LaunchAgents.

Authentication is explicit:

* ``trusted-network`` (default) accepts requests only from configured LAN /
  Tailscale CIDRs. This keeps the normal app zero-tap while avoiding a
  tokenless Internet-facing write surface.
* ``token`` requires ``JARVIS_API_TOKEN`` for the app API. Event ingestion uses
  ``JARVISD_EVENT_TOKEN`` when configured, otherwise the API token.

The state endpoint is deliberately cheap: collectors refresh in the
background and the HTTP handler composes a snapshot from last-good cache
entries. A slow VeSync/CLI call therefore cannot make every phone poll spawn a
new set of subprocesses.

Run: ``python jarvisd.py`` (env: JARVISD_AUTH_MODE, JARVIS_API_TOKEN,
JARVISD_TRUSTED_CIDRS, JARVISD_PORT, ...).
"""
from __future__ import annotations

import concurrent.futures
import copy
import datetime as dt
import http.client
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from jarvisd_core.control_http import ControlHTTPMixin, ControlHTTPServer, WRITES as V2_DEVICE_WRITES
from pathlib import Path
from typing import Any, Callable

from jarvisd_core import auth, commands, security_status
from jarvisd_core.config import _find_ancestor, _load_env_file, _resolve_jarvis_root
from jarvisd_core.commands import COMMANDS, CommandError, PURIFIER_MODES, PURIFIER_SPEEDS
from jarvisd_core.diagnostics import _safe_error
from jarvisd_core.events import EventInputError, EventStore
from jarvisd_core.http_input import RequestInputError, read_json
from jarvisd_core.logging import BoundedLogWriter, RoutineRequestLogGate
from jarvisd_core.state import StateCoordinator as CoreStateCoordinator
from jarvisd_core.admission import AdmissionError, WriteAdmission
from jarvisd_core.control import DeviceCommandDispatcher
from jarvisd_core.device_transport import DeviceAdapterRunner
from jarvisd_core.device_collectors import collect_plugs, collect_purifier
from jarvisd_core.devices import (
    _purifier_command_data, _purifier_expectation, _purifier_matches,
    _purifier_pending_command, _purifier_state, _purifier_id,
)

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

VERSION = "0.2.0"
START_TIME = time.time()


JARVISD_DIR = Path(__file__).resolve().parent


if os.environ.get("JARVISD_OPERATION_ROOT"):
    OPERATION_ROOT = Path(os.environ["JARVISD_OPERATION_ROOT"]).resolve()
else:
    OPERATION_ROOT = _find_ancestor(JARVISD_DIR, "jarvis-cli") or JARVISD_DIR.parent

PROJECT_ROOT_IS_EXPLICIT = bool(os.environ.get("JARVISD_PROJECT_ROOT"))
if PROJECT_ROOT_IS_EXPLICIT:
    PROJECT_ROOT = Path(os.environ["JARVISD_PROJECT_ROOT"]).resolve()
else:
    PROJECT_ROOT = _find_ancestor(JARVISD_DIR, ".env") or OPERATION_ROOT.parent


JARVIS_ROOT = _resolve_jarvis_root(
    source_dir=JARVISD_DIR,
    project_root=PROJECT_ROOT,
    project_root_is_explicit=PROJECT_ROOT_IS_EXPLICIT,
)

JARVIS_CLI = OPERATION_ROOT / "jarvis-cli"
DEVICE_WORKER = JARVISD_DIR / "device-worker.py"
_load_env_file(PROJECT_ROOT / ".env")

PORT = int(os.environ.get("JARVISD_PORT", "8790"))
# LAN + Tailscale access is required by the app. Authentication below narrows
# which clients may use the wildcard bind; do not change this to tokenless
# Internet exposure.
HOST = os.environ.get("JARVISD_HOST", "0.0.0.0")
AUTH_MODE = os.environ.get("JARVISD_AUTH_MODE", "trusted-network").strip().lower()
API_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")
EVENT_TOKEN = os.environ.get("JARVISD_EVENT_TOKEN", "")
# Opt-in local launcher path. No worker, cache, or startup device reads.
SECURITY_CLI = os.environ.get("JARVISD_SECURITY_CLI", "")
TRUSTED_CIDRS_RAW = os.environ.get(
    "JARVISD_TRUSTED_CIDRS",
    "127.0.0.0/8,::1/128,192.168.21.0/24,100.64.0.0/10",
)
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get("JARVISD_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
MAX_JSON_BODY_BYTES = int(os.environ.get("JARVISD_MAX_JSON_BODY_BYTES", str(64 * 1024)))
SERVICES_FILE = Path(os.environ.get("JARVISD_SERVICES_FILE", str(JARVISD_DIR / "services.json")))
EVENTS_FILE = Path(os.environ.get("JARVISD_EVENTS_FILE", str(JARVISD_DIR / "logs" / "events.jsonl")))
LOG_FILE = Path(os.environ.get("JARVISD_LOG_FILE", str(JARVISD_DIR / "logs" / "jarvisd.log"))).expanduser()
LOG_MAX_BYTES = min(
    16 * 1024 * 1024,
    max(64 * 1024, int(os.environ.get("JARVISD_LOG_MAX_BYTES", str(1024 * 1024)))),
)
LOG_BACKUP_COUNT = min(10, max(1, int(os.environ.get("JARVISD_LOG_BACKUP_COUNT", "3"))))
ROUTINE_REQUEST_LOG_INTERVAL = min(
    600.0,
    max(10.0, float(os.environ.get("JARVISD_ROUTINE_REQUEST_LOG_INTERVAL", "60"))),
)
SCHEDULER_RUNNER = Path(
    os.environ.get("JARVISD_SCHEDULER_RUNNER", str(JARVIS_ROOT / ".pi" / "scheduler" / "runner.py"))
).expanduser().resolve()
SCHEDULED_JOBS_TIMEOUT = min(15.0, max(1.0, float(os.environ.get("JARVISD_SCHEDULED_JOBS_TIMEOUT", "5"))))
MAX_SCHEDULED_JOBS = min(500, max(1, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOBS", "100"))))
MAX_SCHEDULED_JOBS_OUTPUT_BYTES = min(
    1024 * 1024,
    max(4096, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOBS_OUTPUT_BYTES", str(256 * 1024)))),
)
MAX_SCHEDULED_JOB_RESULTS = min(100, max(1, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOB_RESULTS", "100"))))
MAX_SCHEDULED_JOB_RESULT_BYTES = 64 * 1024
MAX_SCHEDULED_JOB_RESULTS_OUTPUT_BYTES = min(
    8 * 1024 * 1024,
    max(64 * 1024, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOB_RESULTS_OUTPUT_BYTES", str(7 * 1024 * 1024)))),
)
SCHEDULED_RESULT_SECRET_KEY_RE = re.compile(
    r"(?i)(?:token|secret|password|api_?key|authorization|cookie|sp_dc|sp_key)"
)
SCHEDULED_RESULT_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|api[_ -]?key|authorization)\b\s*([=:])\s*([^\s,;]+)"
)
SCHEDULED_RESULT_JSON_SECRET_RE = re.compile(
    r'''(?i)(["'](?:token|secret|password|api[_ -]?key|authorization)["']\s*:\s*["'])(.*?)(["'])'''
)
SCHEDULED_RESULT_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
CODEX_QUOTAS_SCRIPT = Path(
    os.environ.get(
        "JARVISD_CODEX_QUOTAS_SCRIPT",
        str(JARVIS_ROOT / "projects" / "operation-jarvis" / "quotas" / "quotas.py"),
    )
).expanduser().resolve()
CODEX_QUOTA_TIMEOUT = min(60.0, max(5.0, float(os.environ.get("JARVISD_CODEX_QUOTA_TIMEOUT", "45"))))
MAX_CODEX_QUOTA_OUTPUT_BYTES = min(
    2 * 1024 * 1024,
    max(4096, int(os.environ.get("JARVISD_MAX_CODEX_QUOTA_OUTPUT_BYTES", str(1024 * 1024)))),
)
TAILSCALE_IP_FALLBACK = os.environ.get("JARVISD_TAILSCALE_IP", "")
TAILSCALE_SOCKET = Path(os.environ.get("TAILSCALE_SOCKET", str(Path.home() / ".local/share/tailscale/tailscaled.socket")))
TAILSCALE_APP_CLI = Path(
    os.environ.get("JARVISD_TAILSCALE_APP_CLI", "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
)
LAUNCH_AGENTS_DIR = Path(
    os.environ.get("JARVISD_LAUNCH_AGENTS_DIR", str(Path.home() / "Library/LaunchAgents"))
).expanduser().resolve()
SIGNING_RENEWAL_SCRIPT = Path(
    os.environ.get("JARVISD_SIGNING_RENEWAL_SCRIPT", str(OPERATION_ROOT / "jarvis-app" / "scripts" / "renew-free-signing.sh"))
).expanduser().resolve()
SIGNING_RENEWAL_STATUS_FILE = Path(
    os.environ.get(
        "JARVISD_SIGNING_RENEWAL_STATUS_FILE",
        str(Path.home() / "Library/Application Support/JARVIS/signing-renewal/status.json"),
    )
).expanduser().resolve()
SIGNING_RENEWAL_LOG_DIR = Path(
    os.environ.get(
        "JARVISD_SIGNING_RENEWAL_LOG_DIR",
        str(Path.home() / "Library/Application Support/JARVIS/signing-renewal/logs"),
    )
).expanduser().resolve()
SIGNING_RENEWAL_START_LOCK = threading.Lock()
SIGNING_RENEWAL_STEPS = {
    "preparing", "provisioning", "building", "auditing",
    "installingIPhone", "installingWatch", "verifying",
}
SIGNING_RENEWAL_PHASES = SIGNING_RENEWAL_STEPS | {"idle", "queued", "succeeded", "failed"}

STATE_TIMEOUT = float(os.environ.get("JARVISD_STATE_TIMEOUT", "10"))
# Native HTTP requests are bounded to 30 seconds. Keep VeSync write
# verification below that boundary; a lagging cloud state is returned as
# verification_pending rather than allowing the daemon/client to time out.
PURIFIER_WRITE_WAIT_SECONDS = min(
    20.0,
    max(0.0, float(os.environ.get("JARVISD_PURIFIER_WRITE_WAIT_SECONDS", "15"))),
)
PI_LOCAL_SESSIONS = Path(os.environ.get("PI_LOCAL_SESSIONS", str(PROJECT_ROOT / ".pi/runtime/local-pi-sessions")))
PI_RPC_SESSIONS = Path(os.environ.get("PI_RPC_SESSIONS", str(PROJECT_ROOT / ".pi/runtime/pi-rpc-sessions.json")))
MOBILE_TMUX_BIN = Path("/opt/homebrew/bin/tmux")
MOBILE_TMUX_SOCKET = "jarvis-mobile"
MOBILE_TMUX_SESSIONS = (
    (1, "jarvis-ios"),
    (2, "jarvis-ios-2"),
    (3, "jarvis-ios-3"),
    (4, "jarvis-ios-4"),
    (5, "jarvis-ios-5"),
    (6, "jarvis-ios-6"),
    (7, "jarvis-ios-7"),
    (8, "jarvis-ios-8"),
    (9, "jarvis-ios-9"),
    (10, "jarvis-ios-10"),
)
MOBILE_PI_STATUS_MAX_AGE_SECONDS = min(
    60.0,
    max(4.0, float(os.environ.get("JARVISD_MOBILE_PI_STATUS_MAX_AGE_SECONDS", "10"))),
)
MAX_MOBILE_PI_STATUS_BYTES = 16 * 1024
MAX_MOBILE_PI_STATUS_FILES_PER_PID = 8
MAX_MOBILE_TMUX_OUTPUT_BYTES = 64 * 1024
MOBILE_PI_REPORTED_LIFECYCLES = frozenset({"new", "idle", "running", "compacting", "unknown"})
MOBILE_PI_ACTIVE_LIFECYCLES = frozenset({"running", "compacting"})
# Read only an exact path reported by the fresh PID telemetry. Never search for
# a latest history or mutate/reload live Pi processes to discover new sessions.
PI_SESSION_HISTORY_ROOT = Path.home() / ".pi" / "agent" / "sessions"
MAX_PI_HISTORY_PROBE_BYTES = 1024 * 1024
MAX_PI_HISTORY_PROBE_LINES = 4096
MOBILE_PI_PUBLIC_LIFECYCLES = MOBILE_PI_REPORTED_LIFECYCLES | {"offline", "unknown"}

PROTECTED_LABELS = {"com.operation-jarvis.jarvisd", "com.operation-jarvis.jarvisd-resurrector"}


def validate_config() -> None:
    """Fail early for unsafe/ambiguous daemon configuration."""
    auth.validate_config(mode=AUTH_MODE, api_token=API_TOKEN,
                         trusted_cidrs=TRUSTED_CIDRS_RAW, max_json_bytes=MAX_JSON_BODY_BYTES)


# --------------------------------------------------------------------------- #
# Bounded operational logging
# --------------------------------------------------------------------------- #


ROUTINE_REQUEST_LOG_PATHS = {"/health", "/api/v1/state", "/api/v1/omlx"}
ROUTINE_REQUEST_LOG_GATE = RoutineRequestLogGate(ROUTINE_REQUEST_LOG_INTERVAL)


def configure_bounded_stderr() -> BoundedLogWriter | None:
    """Move daemon stderr to private bounded rotation without risking startup."""
    original = sys.stderr
    try:
        writer = BoundedLogWriter(LOG_FILE, max_bytes=LOG_MAX_BYTES, backup_count=LOG_BACKUP_COUNT)
    except Exception as exc:  # noqa: BLE001
        original.write(f"[jarvisd] bounded logging unavailable: {exc}\n")
        return None
    sys.stderr = writer
    return writer


# --------------------------------------------------------------------------- #
# Command allowlist
# --------------------------------------------------------------------------- #

def _selected_purifier_selector(device_id: str) -> str:
    """Resolve only an already-known, freshly observed selected purifier."""
    with _PURIFIER_SELECTOR_LOCK:
        selector = _PURIFIER_SELECTORS.get(device_id)
    if selector is None:
        raise CommandError("Unknown purifier; refresh the device list first")
    item = STATE_COORDINATOR.snapshot().get("subsystems", {}).get("purifier", {}).get("devices", {}).get(device_id, {})
    if item.get("ok") is not True or item.get("stale") is not False or item.get("verificationPending") is True:
        raise CommandError("Fresh selected-purifier readings are required before a change")
    return selector


def _purifier_set_args(params: dict) -> list[str]:
    return commands.purifier_set_args(params, selected_purifier=_selected_purifier_selector)


def build_command(action: Any, params: Any) -> list[str]:
    return commands.build_command(action, params, cli=JARVIS_CLI,
                                  selected_purifier=_selected_purifier_selector)


WRITE_ADMISSION = WriteAdmission()


def run_device_adapter(argv: list[str], timeout: float = 20.0, env: dict[str, str] | None = None) -> dict:
    return DeviceAdapterRunner(
        cli=JARVIS_CLI, worker=DEVICE_WORKER, python=sys.executable,
        operation_root=OPERATION_ROOT, project_root=PROJECT_ROOT, run=run_cli_json,
    )(argv, timeout=timeout, env=env)


def dispatch_command(action: Any, params: Any) -> dict:
    return DeviceCommandDispatcher(
        state=STATE_COORDINATOR, admission=WRITE_ADMISSION, cli=JARVIS_CLI,
        run=run_device_adapter, selected_purifier=_selected_purifier_selector,
        purifier_wait_seconds=PURIFIER_WRITE_WAIT_SECONDS,
    ).execute(action, params)


# --------------------------------------------------------------------------- #
# Subprocess helpers
# --------------------------------------------------------------------------- #


def run_cli_json(argv: list[str], timeout: float = 20.0, env: dict[str, str] | None = None) -> dict:
    """Run an argv list without a shell and parse JSON stdout.

    ``Popen.communicate`` is used so a timed-out child is explicitly killed;
    request handlers never wait for a context manager to drain a hung pool.
    """
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(OPERATION_ROOT),
            env={**os.environ, **(env or {})},
            start_new_session=(os.name == "posix"),
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
            return {"ok": False, "error": f"timed out after {timeout:.0f}s", "stderr": _safe_error(stderr)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _safe_error(exc)}

    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    returncode = proc.returncode if proc else 1
    if returncode != 0:
        parsed = _try_json(stdout)
        if parsed is not None and isinstance(parsed, dict):
            parsed.setdefault("ok", False)
            if stderr:
                parsed["stderr"] = _safe_error(stderr, 2000)
            return parsed
        return {"ok": False, "error": _safe_error(stderr or stdout or f"exit {returncode}")}

    parsed = _try_json(stdout)
    if parsed is None:
        return {"ok": False, "error": "command returned non-JSON output", "stdout": stdout[-2000:]}
    return parsed if isinstance(parsed, dict) else {"ok": False, "error": "command returned a non-object JSON value"}


def _try_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        idx = text.find("{")
        if idx >= 0:
            try:
                return json.loads(text[idx:])
            except json.JSONDecodeError:
                return None
        return None


_PUBLIC_PLUG_FIELDS = ("name", "is_on", "host", "rssi", "alias")
_PUBLIC_PURIFIER_FIELDS = (
    "air_quality_level",
    "child_lock",
    "display_status",
    "fan_level",
    "fan_set_level",
    "filter_life",
    "is_on",
    "mode",
    "model",
    "name",
    "pm25",
    "power",
    "supported_fan_levels",
    "supported_modes",
    "timer",
    "verification_pending",
    "verification_warning",
    "write_accepted",
)


def _public_command_result(action: Any, result: dict) -> dict:
    """Return the bounded native-client contract, never adapter internals."""
    response: dict[str, Any] = {
        "ok": result.get("ok") is True,
        "action": action if isinstance(action, str) else None,
    }
    if result.get("summary"):
        response["summary"] = _safe_error(result["summary"], 1000)
    if response["ok"] is not True:
        response["error"] = _safe_error(result.get("error") or result.get("stderr") or "command failed")

    plug = result.get("plug")
    if isinstance(plug, dict):
        response["plug"] = {key: copy.deepcopy(plug[key]) for key in _PUBLIC_PLUG_FIELDS if key in plug}

    purifier = _purifier_command_data(result)
    if isinstance(purifier, dict):
        response["airPurifier"] = {
            "ok": response["ok"],
            "data": {key: copy.deepcopy(purifier[key]) for key in _PUBLIC_PURIFIER_FIELDS if key in purifier},
        }
    return response


# --------------------------------------------------------------------------- #
# State collectors
# --------------------------------------------------------------------------- #


# Read-only background collectors must not create user-visible lifecycle events.
COLLECTOR_ENV = {"JARVIS_EMIT_EVENTS": "0"}


def _lan_ip() -> str | None:
    for iface in ("en0", "en1"):
        try:
            out = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3)
            ip = out.stdout.strip()
            if ip:
                return ip
        except Exception:  # noqa: BLE001
            continue
    return None


def _tailscale_ip() -> str | None:
    if TAILSCALE_SOCKET.exists():
        try:
            conn = _UnixSocketHTTPConnection(str(TAILSCALE_SOCKET))
            conn.request("GET", "/localapi/v0/self")
            resp = conn.getresponse()
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                ips = (data.get("Self") or {}).get("TailscaleIPs") or []
                conn.close()
                if ips:
                    return ips[0]
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    # Network extensions do not always expose a local-api socket to a LaunchAgent.
    # The Tailscale tunnel still has an RFC 6598 address, so inspect only utun
    # interfaces before falling back to either CLI implementation.
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=5)
        interface = ""
        for line in out.stdout.splitlines():
            if line and not line[0].isspace():
                interface = line.partition(":")[0]
                continue
            match = re.match(r"\s+inet\s+(\S+)", line)
            if not interface.startswith("utun") or match is None:
                continue
            address = ipaddress.ip_address(match.group(1))
            if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"):
                return str(address)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    env = dict(os.environ, TSD_SOCKET=str(TAILSCALE_SOCKET))
    # The standalone Homebrew CLI talks to a Unix socket, while the signed
    # macOS app exposes its own CLI through the app bundle. Try both so a
    # Tailscale app reinstall/address rotation cannot leave stale network data.
    executables = [str(TAILSCALE_APP_CLI), "tailscale"]
    for executable in executables:
        try:
            out = subprocess.run(
                [executable, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
            address = ipaddress.ip_address(ip)
            if isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10"):
                return ip
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return TAILSCALE_IP_FALLBACK or None


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """Minimal HTTP connection over a unix socket for Tailscale localapi."""

    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):  # noqa: D102
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


def _pi_history_has_conversation(session_file: object) -> bool | None:
    """Bounded legacy-process bridge: True=history, False=empty, None=unknown.

    Only a complete, valid metadata-only JSONL is New. A missing, malformed,
    changing, oversized or out-of-scope file never proves an untouched session.
    Contents are neither logged nor returned to clients.
    """
    if not isinstance(session_file, str) or not session_file or len(session_file) > 4096:
        return None
    try:
        path = Path(session_file)
        if not path.is_absolute() or path.suffix != ".jsonl" or path.is_symlink():
            return None
        path = path.resolve(strict=True)
        if not path.is_relative_to(PI_SESSION_HISTORY_ROOT.resolve()) or not path.is_file():
            return None
        with path.open("rb") as history:
            before = os.fstat(history.fileno())
            remaining = MAX_PI_HISTORY_PROBE_BYTES
            for index in range(MAX_PI_HISTORY_PROBE_LINES):
                line = history.readline(remaining + 1)
                if not line:
                    after = os.fstat(history.fileno())
                    if index == 0 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        return None
                    return False
                if len(line) > remaining or not line.endswith(b"\n"):
                    return None
                remaining -= len(line)
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    return None
                kind = entry.get("type")
                if index == 0:
                    if kind != "session" or entry.get("version") not in {1, 2, 3}:
                        return None
                    continue
                if kind in {"compaction", "branch_summary"}:
                    return True
                if kind == "message":
                    message = entry.get("message")
                    if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                        return None
                    if message["role"] in {"user", "assistant"}:
                        return True
                elif kind not in {"model_change", "thinking_level_change", "custom", "custom_message", "label", "session_info"}:
                    return None
        return None
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _fresh_local_pi_lifecycle(pid: int, *, now: dt.datetime) -> str | None:
    """Return one Pi process's fresh lifecycle, or None for unknown evidence."""
    if not PI_LOCAL_SESSIONS.is_dir():
        return None

    candidates: list[Path] = []
    direct = PI_LOCAL_SESSIONS / f"{pid}.json"
    if direct.exists():
        candidates.append(direct)
    try:
        for path in PI_LOCAL_SESSIONS.glob(f"{pid}-*.json"):
            candidates.append(path)
            if len(candidates) > MAX_MOBILE_PI_STATUS_FILES_PER_PID:
                return None
    except OSError:
        return None

    freshest: tuple[dt.datetime, str, dict] | None = None
    for path in candidates:
        try:
            if path.is_symlink():
                continue
            with path.open("rb") as status_file:
                raw = status_file.read(MAX_MOBILE_PI_STATUS_BYTES + 1)
            if len(raw) > MAX_MOBILE_PI_STATUS_BYTES:
                continue
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or payload.get("source") != "pi-extension-local-session-status"
                or payload.get("pid") != pid
            ):
                continue

            version = payload.get("version")
            if version == 2 and payload.get("lifecycle") == "waiting":
                lifecycle = "running"  # legacy telemetry: conservative busy mapping
            elif version == 2 and payload.get("lifecycle") in MOBILE_PI_REPORTED_LIFECYCLES:
                lifecycle = payload["lifecycle"]
            elif version == 1 and isinstance(payload.get("active"), bool):
                # Preserve availability while live Build 142 Pi processes wait
                # for their owner-controlled manual /reload.
                lifecycle = "running" if payload["active"] else "idle"
            else:
                continue

            updated_at = payload.get("updatedAt")
            if not isinstance(updated_at, str) or len(updated_at) > 64:
                continue
            timestamp = dt.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                continue
            timestamp = timestamp.astimezone(dt.timezone.utc)
            age = (now - timestamp).total_seconds()
            if age < -5.0 or age > MOBILE_PI_STATUS_MAX_AGE_SECONDS:
                continue
            if freshest is None or timestamp > freshest[0]:
                freshest = (timestamp, lifecycle, payload)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if freshest is None:
        return None
    _, lifecycle, payload = freshest
    if lifecycle in {"new", "idle"}:
        # New extensions inspect the in-memory session tree (including ephemeral
        # sessions). Their explicit evidence avoids any disk scan.
        has_conversation = payload.get("hasConversation")
        if type(has_conversation) is not bool:
            has_conversation = _pi_history_has_conversation(payload.get("sessionFile"))
        return "idle" if has_conversation is True else "new" if has_conversation is False else "unknown"
    return lifecycle


def _mobile_pi_state(session_id: int, lifecycle: str) -> dict:
    """Build the lifecycle response with a Build 142 compatibility activity."""
    if lifecycle not in MOBILE_PI_PUBLIC_LIFECYCLES:
        lifecycle = "unknown"
    active: bool | None
    if lifecycle in MOBILE_PI_ACTIVE_LIFECYCLES:
        active = True
    elif lifecycle in {"new", "idle", "offline"}:
        active = False
    else:
        active = None
    return {"sessionID": session_id, "lifecycle": lifecycle, "active": active}


def _mobile_pi_session_states(*, now: dt.datetime | None = None) -> list[dict]:
    """Read fixed tmux identities and fresh Pi lifecycle without mutating either."""
    unknown = [_mobile_pi_state(session_id, "unknown") for session_id, _name in MOBILE_TMUX_SESSIONS]
    try:
        result = subprocess.run(
            [
                str(MOBILE_TMUX_BIN),
                "-L",
                MOBILE_TMUX_SOCKET,
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{pane_dead}\t#{pane_pid}",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return unknown

    stdout = result.stdout or ""
    if result.returncode != 0 or len(stdout.encode("utf-8")) > MAX_MOBILE_TMUX_OUTPUT_BYTES:
        return unknown

    fixed_names = {name for _session_id, name in MOBILE_TMUX_SESSIONS}
    rows_by_name: dict[str, list[tuple[str, str] | None]] = {name: [] for name in fixed_names}
    for raw_line in stdout.splitlines():
        fields = raw_line.split("\t")
        if not fields or fields[0] not in fixed_names:
            continue
        rows_by_name[fields[0]].append((fields[1], fields[2]) if len(fields) == 3 else None)

    observed_at = now or dt.datetime.now(dt.timezone.utc)
    states: list[dict] = []
    for session_id, name in MOBILE_TMUX_SESSIONS:
        rows = rows_by_name[name]
        if not rows:
            lifecycle = "offline"
        elif len(rows) != 1 or rows[0] is None:
            lifecycle = "unknown"
        else:
            pane_dead, raw_pid = rows[0]
            if pane_dead == "1":
                lifecycle = "offline"
            elif pane_dead != "0" or not raw_pid.isdecimal() or int(raw_pid) <= 0:
                lifecycle = "unknown"
            else:
                lifecycle = _fresh_local_pi_lifecycle(int(raw_pid), now=observed_at) or "unknown"
        states.append(_mobile_pi_state(session_id, lifecycle))
    return states


def _pi_sessions() -> dict:
    active_local = 0
    local_total = 0
    if PI_LOCAL_SESSIONS.is_dir():
        for f in PI_LOCAL_SESSIONS.glob("*.json"):
            local_total += 1
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                if payload.get("version") == 2:
                    if payload.get("lifecycle") in MOBILE_PI_ACTIVE_LIFECYCLES | {"waiting"}:
                        active_local += 1
                elif payload.get("version") == 1 and payload.get("active") is True:
                    active_local += 1
            except Exception:  # noqa: BLE001
                continue
    rpc_active = 0
    if PI_RPC_SESSIONS.is_file():
        try:
            data = json.loads(PI_RPC_SESSIONS.read_text(encoding="utf-8"))
            sessions = data.get("sessions", data if isinstance(data, list) else [])
            for session in sessions:
                if isinstance(session, dict) and session.get("active"):
                    rpc_active += 1
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": True,
        "active": active_local + rpc_active,
        "localActive": active_local,
        "localTotal": local_total,
        "rpcActive": rpc_active,
        "mobileSessions": _mobile_pi_session_states(),
    }


def _plugs() -> dict:
    return collect_plugs(run_cli_json=run_device_adapter, cli=JARVIS_CLI, env=COLLECTOR_ENV)


_PURIFIER_SELECTORS: dict[str, str] = {}
_PURIFIER_SELECTOR_LOCK = threading.RLock()


def _purifier(retry: bool = False) -> dict:
    result, selectors = collect_purifier(run_cli_json=run_device_adapter, cli=JARVIS_CLI,
                                         env=COLLECTOR_ENV, retry=retry)
    if selectors is not None:
        with _PURIFIER_SELECTOR_LOCK:
            _PURIFIER_SELECTORS.clear()
            _PURIFIER_SELECTORS.update(selectors)
    return result


def _launchctl_target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


def _service_allowed_actions(spec: dict) -> list[str]:
    raw = spec.get("allowedActions", [])
    if not isinstance(raw, list):
        return []
    allowed = {"start", "stop", "restart"}
    return [action for action in raw if isinstance(action, str) and action in allowed]


def _service_metadata(spec: dict) -> dict:
    display_name = spec.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = None
    description = spec.get("description")
    if not isinstance(description, str):
        description = None
    sort_order = spec.get("sortOrder")
    if isinstance(sort_order, bool) or not isinstance(sort_order, int):
        sort_order = None
    configured: bool | None = None
    if isinstance(spec.get("plist"), str) and spec.get("plist", "").strip():
        try:
            plist = _validated_plist(spec)
            configured = bool(plist and plist.is_file())
        except ValueError:
            configured = False
    return {
        "displayName": display_name.strip()[:120] if display_name else None,
        "description": description.strip()[:500] if description else None,
        "sortOrder": max(-1000, min(1000, sort_order)) if sort_order is not None else None,
        "critical": spec.get("critical") is True,
        "configured": configured,
        "allowedActions": _service_allowed_actions(spec),
    }


def _parse_launchctl_status(name: str, spec: dict, proc: subprocess.CompletedProcess[str]) -> dict:
    label = spec.get("label")
    text = proc.stdout or ""
    pid_match = re.search(r"(?:\"PID\"|\bpid)\s*=\s*(\d+)", text, re.IGNORECASE)
    state_match = re.search(r"\bstate\s*=\s*([A-Za-z]+)", text, re.IGNORECASE)
    pid = int(pid_match.group(1)) if pid_match else None
    loaded = proc.returncode == 0
    running = pid is not None or (state_match and state_match.group(1).lower() in {"running", "active"})
    return {
        "ok": True,
        "service": name,
        "label": label,
        "loaded": loaded,
        "running": bool(running) if loaded else False,
        "pid": pid,
        **_service_metadata(spec),
    }


def _service_status(name: str, spec: dict) -> dict:
    label = spec.get("label")
    metadata = _service_metadata(spec)
    if not isinstance(label, str) or not label:
        return {
            "ok": False,
            "service": name,
            "error": "service has no launchctl label",
            "running": None,
            **metadata,
        }
    try:
        proc = subprocess.run(
            ["launchctl", "print", _launchctl_target(label)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "service": name,
            "label": label,
            "error": _safe_error(exc),
            "running": None,
            **metadata,
        }
    if proc.returncode != 0:
        # A missing LaunchAgent is a normal stopped/unloaded state. Other
        # launchctl failures remain visible as unknown rather than stopped.
        stderr = (proc.stderr or "").lower()
        if "could not find service" in stderr or "service not found" in stderr or not stderr.strip():
            return {
                "ok": True,
                "service": name,
                "label": label,
                "loaded": False,
                "running": False,
                "pid": None,
                **metadata,
            }
        return {
            "ok": False,
            "service": name,
            "label": label,
            "loaded": None,
            "running": None,
            "pid": None,
            "error": _safe_error(proc.stderr or "launchctl status failed"),
            **metadata,
        }
    return _parse_launchctl_status(name, spec, proc)


def _services_state(services: dict) -> dict:
    return {name: _service_status(name, spec) for name, spec in services.items() if isinstance(spec, dict)}


def _load_services() -> dict:
    try:
        data = json.loads(SERVICES_FILE.read_text(encoding="utf-8"))
        services = data.get("services", {})
        return services if isinstance(services, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _scheduled_jobs_unavailable() -> dict:
    return {
        "ok": False,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {"total": 0, "enabled": 0, "running": 0, "errors": 0},
        "jobs": [],
        "error": "Scheduled-job status is unavailable.",
    }


def _scheduled_job_string(value: Any, *, limit: int, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("scheduled-job field must be a string")
    clean = " ".join(value.split())
    if not clean and not optional:
        raise ValueError("scheduled-job field cannot be empty")
    return clean[:limit] or None


def _public_scheduled_jobs(payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("scheduled-job runner returned an invalid result")
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or len(raw_jobs) > MAX_SCHEDULED_JOBS:
        raise ValueError("scheduled-job list is invalid")
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            raise ValueError("scheduled-job entry is invalid")
        job_id = _scheduled_job_string(raw.get("id"), limit=128)
        name = _scheduled_job_string(raw.get("name"), limit=120)
        kind = _scheduled_job_string(raw.get("kind"), limit=16)
        schedule = _scheduled_job_string(raw.get("schedule"), limit=120)
        if kind not in {"once", "interval", "cron"}:
            raise ValueError("scheduled-job kind is invalid")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id or "") or job_id in seen_ids:
            raise ValueError("scheduled-job id is invalid")
        enabled = raw.get("enabled")
        run_count = raw.get("runCount")
        if not isinstance(enabled, bool):
            raise ValueError("scheduled-job enabled state is invalid")
        if isinstance(run_count, bool) or not isinstance(run_count, int) or run_count < 0:
            raise ValueError("scheduled-job run count is invalid")
        last_status = _scheduled_job_string(raw.get("lastStatus"), limit=32, optional=True)
        next_run_at = _scheduled_job_string(raw.get("nextRunAt"), limit=64, optional=True)
        last_run_at = _scheduled_job_string(raw.get("lastRunAt"), limit=64, optional=True)
        description = _scheduled_job_string(raw.get("description"), limit=300, optional=True)
        if description:
            description = re.sub(
                r"(/Users/[^\s,;]+|/private/[^\s,;]+|/tmp/[^\s,;]+)",
                "<local-path>",
                description,
            )
        consecutive_errors = raw.get("consecutiveErrors", 0)
        if isinstance(consecutive_errors, bool) or not isinstance(consecutive_errors, int) or consecutive_errors < 0:
            raise ValueError("scheduled-job consecutive error count is invalid")
        jobs.append({
            "id": job_id,
            "name": name,
            "kind": kind,
            "schedule": schedule,
            "enabled": enabled,
            "nextRunAt": next_run_at,
            "lastRunAt": last_run_at,
            "lastStatus": last_status,
            "runCount": min(run_count, 2_147_483_647),
            "description": description,
            "lastSilentSuccessAt": _scheduled_job_string(raw.get("lastSilentSuccessAt"), limit=64, optional=True),
            "lastOutputAt": _scheduled_job_string(raw.get("lastOutputAt"), limit=64, optional=True),
            "lastErrorAt": _scheduled_job_string(raw.get("lastErrorAt"), limit=64, optional=True),
            "consecutiveErrors": min(consecutive_errors, 2_147_483_647),
        })
        seen_ids.add(job_id or "")
    return {
        "ok": True,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "total": len(jobs),
            "enabled": sum(1 for job in jobs if job["enabled"]),
            "running": sum(1 for job in jobs if job["lastStatus"] == "running"),
            "errors": sum(1 for job in jobs if job["lastStatus"] == "error"),
        },
        "jobs": jobs,
    }


def _scheduled_jobs() -> dict:
    if not SCHEDULER_RUNNER.is_file():
        return _scheduled_jobs_unavailable()
    try:
        proc = subprocess.run(
            [sys.executable, str(SCHEDULER_RUNNER), "--json", "list-public"],
            cwd=str(JARVIS_ROOT),
            capture_output=True,
            text=True,
            timeout=SCHEDULED_JOBS_TIMEOUT,
        )
        stdout = proc.stdout or ""
        if proc.returncode != 0 or len(stdout.encode("utf-8")) > MAX_SCHEDULED_JOBS_OUTPUT_BYTES:
            return _scheduled_jobs_unavailable()
        return _public_scheduled_jobs(json.loads(stdout))
    except Exception:  # noqa: BLE001
        return _scheduled_jobs_unavailable()


def _notification_status_unavailable() -> dict:
    return {
        "ok": False,
        "providerConfigured": False,
        "dispatchEnabled": False,
        "environment": None,
        "devices": {
            "iphone": {"registered": False, "registeredAt": None, "lastAcceptedAt": None},
            "watch": {"registered": False, "registeredAt": None, "lastAcceptedAt": None},
        },
        "pendingCount": 0,
        "failedCount": 0,
        "ambiguousCount": 0,
        "lastOutcome": None,
        "lastAttemptAt": None,
        "lastAcceptedAt": None,
        "error": "Notification status is unavailable.",
    }


def _public_notification_status(payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("notification runner returned an invalid result")

    def optional_text(value: Any, limit: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("notification text is invalid")
        clean = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
        return clean[:limit] or None
    allowed_outcomes = {None, "pending", "accepted", "suppressed", "failed", "ambiguous"}
    environment = payload.get("environment")
    if environment not in {None, "development", "production"}:
        raise ValueError("notification environment is invalid")
    last_outcome = payload.get("lastOutcome")
    if last_outcome not in allowed_outcomes:
        raise ValueError("notification outcome is invalid")
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, dict) or set(raw_devices) != {"iphone", "watch"}:
        raise ValueError("notification devices are invalid")
    devices: dict[str, dict] = {}
    for platform in ("iphone", "watch"):
        raw = raw_devices.get(platform)
        if not isinstance(raw, dict):
            raise ValueError("notification device is invalid")
        registered = raw.get("registered")
        if not isinstance(registered, bool):
            raise ValueError("notification registration state is invalid")
        registered_at = optional_text(raw.get("registeredAt"), 64)
        last_accepted_at = optional_text(raw.get("lastAcceptedAt"), 64)
        devices[platform] = {
            "registered": registered,
            "registeredAt": registered_at,
            "lastAcceptedAt": last_accepted_at,
        }

    def count(name: str) -> int:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
            raise ValueError("notification count is invalid")
        return value

    return {
        "ok": True,
        "providerConfigured": payload.get("providerConfigured") is True,
        "dispatchEnabled": payload.get("dispatchEnabled") is True,
        "environment": environment,
        "devices": devices,
        "pendingCount": count("pendingCount"),
        "failedCount": count("failedCount"),
        "ambiguousCount": count("ambiguousCount"),
        "lastOutcome": last_outcome,
        "lastAttemptAt": optional_text(payload.get("lastAttemptAt"), 64),
        "lastAcceptedAt": optional_text(payload.get("lastAcceptedAt"), 64),
        "error": optional_text(payload.get("error"), 160),
    }


def _notification_status() -> dict:
    if not SCHEDULER_RUNNER.is_file():
        return _notification_status_unavailable()
    try:
        proc = subprocess.run(
            [sys.executable, str(SCHEDULER_RUNNER), "--json", "notification-status"],
            cwd=str(JARVIS_ROOT),
            capture_output=True,
            text=True,
            timeout=SCHEDULED_JOBS_TIMEOUT,
        )
        stdout = proc.stdout or ""
        if proc.returncode != 0 or len(stdout.encode("utf-8")) > 16 * 1024:
            return _notification_status_unavailable()
        return _public_notification_status(json.loads(stdout))
    except Exception:  # noqa: BLE001
        return _notification_status_unavailable()


def _scheduled_job_results_unavailable() -> dict:
    return {
        "ok": False,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": [],
        "hasMore": False,
        "nextAfter": 0,
        "error": "Scheduled-job results are unavailable.",
    }


def _scheduled_result_text(value: Any, *, maximum_bytes: int, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("scheduled-job result field must be a string")
    clean = value.replace("\r\n", "\n").replace("\r", "\n")
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", clean)
    for key, secret in os.environ.items():
        if SCHEDULED_RESULT_SECRET_KEY_RE.search(key) and len(secret) >= 8 and secret in clean:
            clean = clean.replace(secret, "[REDACTED]")
    clean = SCHEDULED_RESULT_BEARER_RE.sub("Bearer [REDACTED]", clean)
    clean = SCHEDULED_RESULT_JSON_SECRET_RE.sub(
        lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}",
        clean,
    )
    clean = SCHEDULED_RESULT_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        clean,
    )
    clean = re.sub(r"(/Users/[^\s,;:'\"<>]+|/private/[^\s,;:'\"<>]+|/tmp/[^\s,;:'\"<>]+)", "<local-path>", clean)
    if len(clean.encode("utf-8")) > maximum_bytes:
        raise ValueError("scheduled-job result field exceeds its byte limit")
    if not clean and not optional:
        raise ValueError("scheduled-job result field cannot be empty")
    return clean or None


def _public_scheduled_job_results(payload: Any, *, requested_limit: int) -> dict:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("scheduled-job runner returned invalid results")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list) or len(raw_results) > requested_limit:
        raise ValueError("scheduled-job result list is invalid")
    results: list[dict] = []
    seen_sequences: set[int] = set()
    seen_ids: set[str] = set()
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise ValueError("scheduled-job result entry is invalid")
        sequence = raw.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0 or sequence in seen_sequences:
            raise ValueError("scheduled-job result sequence is invalid")
        result_id = _scheduled_job_string(raw.get("id"), limit=128)
        job_id = _scheduled_job_string(raw.get("jobId"), limit=128)
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", result_id or "") or result_id in seen_ids:
            raise ValueError("scheduled-job result id is invalid")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id or ""):
            raise ValueError("scheduled-job result job id is invalid")
        status = _scheduled_job_string(raw.get("status"), limit=16)
        output_kind = _scheduled_job_string(raw.get("outputKind"), limit=16)
        if status not in {"success", "error"} or output_kind not in {"direct", "pi", "scheduler"}:
            raise ValueError("scheduled-job result status is invalid")
        duration = raw.get("durationSeconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0 or duration > 7 * 24 * 60 * 60:
            raise ValueError("scheduled-job result duration is invalid")
        exit_code = raw.get("exitCode")
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            raise ValueError("scheduled-job result exit code is invalid")
        truncated = raw.get("truncated")
        if not isinstance(truncated, bool):
            raise ValueError("scheduled-job result truncation state is invalid")
        result = {
            "sequence": sequence,
            "id": result_id,
            "jobId": job_id,
            "jobName": _scheduled_result_text(raw.get("jobName"), maximum_bytes=240),
            "status": status,
            "outputKind": output_kind,
            "startedAt": _scheduled_job_string(raw.get("startedAt"), limit=64),
            "finishedAt": _scheduled_job_string(raw.get("finishedAt"), limit=64),
            "durationSeconds": round(float(duration), 3),
            "exitCode": exit_code,
            "title": _scheduled_result_text(raw.get("title"), maximum_bytes=320),
            "summary": _scheduled_result_text(raw.get("summary"), maximum_bytes=2048),
            "output": _scheduled_result_text(raw.get("output"), maximum_bytes=MAX_SCHEDULED_JOB_RESULT_BYTES, optional=True),
            "error": _scheduled_result_text(raw.get("error"), maximum_bytes=16 * 1024, optional=True),
            "truncated": truncated,
        }
        retained_text_bytes = sum(
            len(str(result[field] or "").encode("utf-8")) for field in ("output", "error")
        )
        if retained_text_bytes > MAX_SCHEDULED_JOB_RESULT_BYTES:
            raise ValueError("scheduled-job result exceeds its aggregate byte limit")
        results.append(result)
        seen_sequences.add(sequence)
        seen_ids.add(result_id or "")
    has_more = payload.get("hasMore")
    next_after = payload.get("nextAfter")
    if not isinstance(has_more, bool):
        raise ValueError("scheduled-job result continuation state is invalid")
    if isinstance(next_after, bool) or not isinstance(next_after, int) or next_after < 0:
        raise ValueError("scheduled-job result cursor is invalid")
    return {
        "ok": True,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": results,
        "hasMore": has_more,
        "nextAfter": next_after,
    }


def _scheduled_job_results(*, after: int | None, limit: int, job_id: str | None) -> dict:
    if not SCHEDULER_RUNNER.is_file():
        return _scheduled_job_results_unavailable()
    command = [sys.executable, str(SCHEDULER_RUNNER), "--json", "list-results-public", "--limit", str(limit)]
    if after is not None:
        command.extend(["--after", str(after)])
    if job_id is not None:
        command.extend(["--job-id", job_id])
    try:
        proc = subprocess.run(
            command,
            cwd=str(JARVIS_ROOT),
            capture_output=True,
            text=True,
            timeout=SCHEDULED_JOBS_TIMEOUT,
        )
        stdout = proc.stdout or ""
        if proc.returncode != 0 or len(stdout.encode("utf-8")) > MAX_SCHEDULED_JOB_RESULTS_OUTPUT_BYTES:
            return _scheduled_job_results_unavailable()
        return _public_scheduled_job_results(json.loads(stdout), requested_limit=limit)
    except Exception:  # noqa: BLE001
        return _scheduled_job_results_unavailable()


def _read_signing_renewal_status() -> dict:
    try:
        payload = json.loads(SIGNING_RENEWAL_STATUS_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _signing_renewal_pid_is_running(payload: dict) -> bool:
    pid = payload.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _signing_renewal_status(payload: dict | None = None) -> dict:
    raw = payload if isinstance(payload, dict) else _read_signing_renewal_status()
    available = SIGNING_RENEWAL_SCRIPT.is_file() and os.access(SIGNING_RENEWAL_SCRIPT, os.X_OK)
    phase = raw.get("phase")
    if phase not in SIGNING_RENEWAL_PHASES:
        phase = "idle"
    running = raw.get("running") is True and _signing_renewal_pid_is_running(raw)
    failed_phase = raw.get("failedPhase")
    if failed_phase not in SIGNING_RENEWAL_STEPS:
        failed_phase = None
    message = raw.get("message")
    if not isinstance(message, str):
        message = "Ready to renew JARVIS signing." if available else "Signing renewal is unavailable on this Mac."
    message = " ".join(message.split())[:300]
    message = re.sub(r"(/Users/[^\s,;]+|/private/[^\s,;]+|/tmp/[^\s,;]+)", "<local-path>", message)
    if raw.get("running") is True and not running:
        if phase in SIGNING_RENEWAL_STEPS:
            failed_phase = phase
        phase = "failed"
        message = "The previous signing renewal was interrupted."
    result = {
        "ok": raw.get("ok") is not False and available,
        "available": available,
        "phase": phase,
        "running": running,
        "message": message,
        "iPhoneInstalled": raw.get("iPhoneInstalled") is True,
        "watchInstalled": raw.get("watchInstalled") is True,
        "failedPhase": failed_phase,
    }
    for key in ("startedAt", "updatedAt", "completedAt", "expiresAt"):
        value = raw.get(key)
        result[key] = value[:64] if isinstance(value, str) else None
    return result


def _start_signing_renewal() -> tuple[bool, dict]:
    with SIGNING_RENEWAL_START_LOCK:
        current = _read_signing_renewal_status()
        if current.get("running") is True and _signing_renewal_pid_is_running(current):
            result = _signing_renewal_status(current)
            result["ok"] = False
            result["message"] = "A signing renewal is already running."
            return False, result
        if not SIGNING_RENEWAL_SCRIPT.is_file() or not os.access(SIGNING_RENEWAL_SCRIPT, os.X_OK):
            return False, _signing_renewal_status({
                "ok": False,
                "phase": "failed",
                "message": "Signing renewal is unavailable on this Mac.",
            })
        try:
            SIGNING_RENEWAL_LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            log_path = SIGNING_RENEWAL_LOG_DIR / "trigger.log"
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [str(SIGNING_RENEWAL_SCRIPT)],
                    cwd=str(SIGNING_RENEWAL_SCRIPT.parent.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError:
            return False, _signing_renewal_status({
                "ok": False,
                "phase": "failed",
                "message": "The Mac could not start the signing renewal.",
            })
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        return True, {
            "ok": True,
            "available": True,
            "phase": "queued",
            "running": True,
            "message": "Signing renewal started on the Mac.",
            "startedAt": now,
            "updatedAt": now,
            "completedAt": None,
            "expiresAt": None,
            "iPhoneInstalled": False,
            "watchInstalled": False,
        }


def _bounded_number(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not minimum <= number <= maximum:
        return None
    return round(number, 2)


def _codex_quota_window(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    used = _bounded_number(value.get("used_percent"), 0, 100)
    remaining = _bounded_number(value.get("remaining_percent"), 0, 100)
    if remaining is None and used is not None:
        remaining = round(100 - used, 2)
    reset_after = _bounded_number(value.get("reset_after_seconds"), 0, 366 * 24 * 60 * 60)
    reset_at_value = _bounded_number(value.get("reset_at"), 0, 4_102_444_800)
    reset_at = None
    if reset_at_value is not None:
        reset_at = dt.datetime.fromtimestamp(reset_at_value, dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "usedPercent": used,
        "remainingPercent": remaining,
        "resetAfterSeconds": int(reset_after) if reset_after is not None else None,
        "resetAt": reset_at,
    }


def _codex_quota_unavailable() -> dict:
    # The coordinator preserves the last good quota snapshot on failure. Its
    # non-critical classification keeps provider outages from marking plugs,
    # purifier, or other JARVIS state stale.
    return {"ok": False, "available": False, "error": "Codex quota unavailable"}


def _public_codex_quota(payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return _codex_quota_unavailable()
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return _codex_quota_unavailable()
    weekly = _codex_quota_window(usage.get("weekly"))
    if weekly is None:
        return _codex_quota_unavailable()
    plan_type = usage.get("plan_type")
    if not isinstance(plan_type, str) or not re.fullmatch(r"[A-Za-z0-9 _+.-]{1,32}", plan_type):
        plan_type = None
    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, str) or len(checked_at) > 64:
        checked_at = None
    credits = usage.get("credits") if isinstance(usage.get("credits"), dict) else {}
    primary_limit = usage.get("primary_limit") if isinstance(usage.get("primary_limit"), dict) else {}
    five_hour_status = primary_limit.get("status")
    if not isinstance(five_hour_status, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,32}", five_hour_status):
        five_hour_status = None
    return {
        "ok": True,
        "available": True,
        "checkedAt": checked_at,
        "planType": plan_type,
        "allowed": usage.get("allowed") if isinstance(usage.get("allowed"), bool) else None,
        "limitReached": usage.get("effective_limit_reached") if isinstance(usage.get("effective_limit_reached"), bool) else None,
        "weekly": weekly,
        "fiveHour": _codex_quota_window(usage.get("five_hour")),
        "fiveHourEnforced": primary_limit.get("enforced") if isinstance(primary_limit.get("enforced"), bool) else None,
        "fiveHourStatus": five_hour_status,
        "creditBalance": _bounded_number(credits.get("balance"), 0, 1_000_000_000),
        "error": None,
    }


def _codex_quota() -> dict:
    if not CODEX_QUOTAS_SCRIPT.is_file():
        return _codex_quota_unavailable()
    try:
        # This is Operation JARVIS's read-only Codex quota check. Never add a probe
        # flag here: probes make a model request and consume quota.
        proc = subprocess.run(
            [sys.executable, str(CODEX_QUOTAS_SCRIPT), "codex", "--json"],
            cwd=str(JARVIS_ROOT),
            capture_output=True,
            text=True,
            timeout=CODEX_QUOTA_TIMEOUT,
        )
        stdout = proc.stdout or ""
        if proc.returncode != 0 or len(stdout.encode("utf-8")) > MAX_CODEX_QUOTA_OUTPUT_BYTES:
            return _codex_quota_unavailable()
        return _public_codex_quota(json.loads(stdout))
    except Exception:  # noqa: BLE001
        return _codex_quota_unavailable()


class StateCoordinator(CoreStateCoordinator):
    """Compatibility constructor; collector wiring belongs to this host, not core."""

    def __init__(self, collectors=None, **kwargs):
        collectors = collectors or {
            "plugs": _plugs,
            "purifier": _purifier,
            "pi": _pi_sessions,
            "services": lambda: {"ok": True, "services": _services_state(_load_services())},
            "network": _collect_network,
            "codexQuota": _codex_quota,
        }
        retry = {"purifier": lambda recovery: _purifier(retry=recovery)} if collectors.get("purifier") is _purifier else {}
        super().__init__(collectors, version=VERSION, started_at=START_TIME,
                         retry_collectors=retry, **kwargs)


def _collect_network() -> dict:
    return {"ok": True, "macLanIp": _lan_ip(), "tailscaleIp": _tailscale_ip()}


# --------------------------------------------------------------------------- #
# Read-only oMLX activity (separate cache/lease from Home controls and Watch)
# --------------------------------------------------------------------------- #

OMLX_SERVER_IDS = ("mac-mini-64", "mac-mini-16")
OMLX_MAX_BODY = 256 * 1024
OMLX_FRESH_SECONDS = 6.0
OMLX_UPDATE_INTERVAL = 3600.0
OMLX_UPDATE_FRESH_SECONDS = 7200.0


def _omlx_number(value: Any, *, integer: bool = False) -> int | float | None:
    # JSON booleans, NaN, infinities, negatives and impractically large counters
    # are not measurements. Missing data remains absent, never a fabricated 0.
    if type(value) not in (int, float) or not 0 <= value <= 2**53:
        return None
    if integer:
        return int(value) if int(value) == value else None
    return value


def _omlx_activity(raw: Any) -> dict:
    """Allowlist dashboard counters only; never forward arbitrary admin JSON."""
    activity = raw.get("active_models") if isinstance(raw, dict) else None
    if not isinstance(activity, dict) or not isinstance(activity.get("models"), list):
        raise ValueError("unsupported activity schema")
    if len(activity["models"]) > 128:
        raise ValueError("too many models")
    models = []
    seen = set()
    for model in activity["models"]:
        if not isinstance(model, dict):
            raise ValueError("invalid model")
        model_id = model.get("id")
        active = _omlx_number(model.get("active_requests"), integer=True)
        queued = _omlx_number(model.get("waiting_requests"), integer=True)
        loading = model.get("is_loading")
        if (not isinstance(model_id, str) or not model_id or len(model_id) > 512
                or any(ord(c) < 32 for c in model_id) or model_id in seen
                or active is None or queued is None or type(loading) is not bool):
            raise ValueError("incomplete model state")
        seen.add(model_id)
        requests = []
        for source, phase, fields in (
            ("prefilling", "prefill", {"processed": "processedTokens", "total": "totalTokens",
                "speed": "tokensPerSecond", "elapsed": "elapsedSeconds"}),
            ("generating", "generating", {"generated_tokens": "generatedTokens",
                "tokens_per_second": "tokensPerSecond", "elapsed_seconds": "elapsedSeconds",
                "last_activity_age_seconds": "lastActivityAgeSeconds"}),
            ("activities", "processing", {"elapsed_seconds": "elapsedSeconds",
                "last_activity_age_seconds": "lastActivityAgeSeconds"}),
            ("waiting", "queued", {"queue_position": "queuePosition", "elapsed_seconds": "elapsedSeconds"}),
        ):
            entries = model.get(source, [])
            if not isinstance(entries, list) or len(entries) > 512:
                raise ValueError("invalid request list")
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise ValueError("invalid request")
                # Local ordinal, not the raw request ID, prompt, filenames,
                # arbitrary activity detail, output, or backend paths.
                request = {"id": f"{phase}-{index}", "phase": phase}
                for original, target in fields.items():
                    request[target] = _omlx_number(entry.get(original), integer=target.endswith("Tokens") or target == "queuePosition")
                requests.append(request)
        models.append({
            "id": model_id, "isLoading": loading,
            "activeRequests": active, "queuedRequests": queued, "requests": requests,
            "estimatedBytes": _omlx_number(model.get("estimated_size")),
            "observedBytes": _omlx_number(model.get("actual_size")),
            "loadingElapsedSeconds": _omlx_number(model.get("loading_elapsed_seconds")),
        })
    # Aggregate counters are built from this same list by oMLX. Missing or
    # contradictory evidence (especially an empty list with active work) is not
    # proof of Ready after an upstream schema change.
    for upstream, field in (("total_active_requests", "activeRequests"),
                            ("total_waiting_requests", "queuedRequests")):
        count = _omlx_number(activity.get(upstream), integer=True)
        if count is None or count != sum(model[field] for model in models):
            raise ValueError("incomplete aggregate state")
    pressure = activity.get("memory_pressure")
    pressure = pressure if isinstance(pressure, dict) else {}
    enabled = pressure.get("enabled") is True
    level = pressure.get("pressure_level") if enabled else None
    return {
        "ok": True, "models": sorted(models, key=lambda m: m["id"].casefold()),
        "memoryUsedBytes": _omlx_number(activity.get("model_memory_used")),
        "memoryLimitBytes": _omlx_number(activity.get("model_memory_max")),
        "memoryKind": "process" if enabled else "models",
        "memoryPressure": level if level in {"ok", "soft", "hard", "critical"} else None,
    }


def _omlx_update(raw: Any) -> dict:
    """Trust the server's own installed-version/channel comparison, not a guessed
    GitHub tag. Do not forward release URLs or arbitrary admin metadata.
    """
    if not isinstance(raw, dict) or type(raw.get("update_available")) is not bool:
        raise ValueError("unsupported update schema")
    available = raw["update_available"]
    latest = raw.get("latest_version")
    if available and (not isinstance(latest, str) or len(latest) > 64
                      or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}[a-zA-Z0-9.+-]*", latest)):
        raise ValueError("missing release version")
    return {"ok": True, "available": available, "latestVersion": latest if available else None}


def _omlx_collect(server_id: str) -> dict:
    return _omlx_read(server_id, path="/admin/api/activity", parser=_omlx_activity,
                      timeout=2.0, unavailable="oMLX activity unavailable.")


def _omlx_collect_update(server_id: str) -> dict:
    # oMLX owns its selected release channel and caches GitHub checks itself.
    # This endpoint only checks; it never downloads or installs an update.
    return _omlx_read(server_id, path="/admin/api/update-check", parser=_omlx_update,
                      timeout=7.0, unavailable="oMLX update check unavailable.")


def _omlx_read(server_id: str, *, path: str, parser, timeout: float, unavailable: str) -> dict:
    """Bounded GET to two operator-configured private IPs. No login, redirects,
    inference, automatic model loading or other writes, including on failure.
    """
    if path not in ("/admin/api/activity", "/admin/api/update-check"):
        return {"ok": False, "error": unavailable}
    suffix = {"mac-mini-64": "64", "mac-mini-16": "16"}[server_id]
    host = os.environ.get(f"JARVISD_OMLX_{suffix}_HOST", "127.0.0.1" if suffix == "64" else "192.168.21.30")
    connection = None
    response = None
    timeout_guard = None
    try:
        address = ipaddress.ip_address(host)  # literals: no unbounded DNS lookup
        if not (address.is_private or address.is_loopback) or address.is_unspecified or address.is_multicast:
            return {"ok": False, "error": "Invalid oMLX host configuration."}
        headers = {"Accept": "application/json"}
        cookie_file = os.environ.get(f"JARVISD_OMLX_{suffix}_COOKIE_FILE")
        if cookie_file:
            # Optional session cookie provisioned by the owner. Current servers
            # allow the read without one. Never log its value or transmit it to
            # a redirect destination; no credential appears in app snapshots.
            cookie_path = Path(cookie_file)
            stat = cookie_path.lstat()
            if cookie_path.is_symlink() or not cookie_path.is_file() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
                raise ValueError("insecure cookie file")
            with cookie_path.open("rb") as stream:
                cookie = stream.read(4097).decode("ascii").strip()
            if not cookie or len(cookie) > 4096 or "\r" in cookie or "\n" in cookie:
                raise ValueError("invalid cookie file")
            headers["Cookie"] = cookie
        deadline = time.monotonic() + timeout
        connection = http.client.HTTPConnection(host, 8000, timeout=timeout)
        connection.connect()
        transport = connection.sock
        def expire():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # A socket timeout alone restarts on every header byte. Enforce the
        # whole-read deadline too, so even a dripping header cannot pin a worker.
        timeout_guard = threading.Timer(max(0.001, deadline - time.monotonic()), expire)
        timeout_guard.daemon = True
        timeout_guard.start()
        transport.settimeout(max(0.001, deadline - time.monotonic()))
        connection.request("GET", path, headers=headers)
        transport.settimeout(max(0.001, deadline - time.monotonic()))
        response = connection.getresponse()
        if response.status in (401, 403):
            return {"ok": False, "error": "Authentication required."}
        if response.status != 200:
            return {"ok": False, "error": unavailable}
        chunks = []
        size = 0
        while not response.isclosed():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            # read1 avoids waiting for a full buffer from a slow/drip peer.
            # Keep our socket reference if HTTPConnection clears its own after
            # reading a Connection: close response (the response still owns it).
            transport.settimeout(remaining)
            chunk = response.read1(min(16384, OMLX_MAX_BODY + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > OMLX_MAX_BODY:
                raise ValueError("oversized activity")
        return parser(json.loads(b"".join(chunks)))
    except Exception:
        # Never expose exception strings, response bodies, cookies or paths.
        return {"ok": False, "error": unavailable}
    finally:
        if timeout_guard is not None:
            timeout_guard.cancel()
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()


OMLX_COORDINATOR = StateCoordinator(
    collectors={server: (lambda server=server: _omlx_collect(server)) for server in OMLX_SERVER_IDS},
    intervals={server: 2.0 for server in OMLX_SERVER_IDS},
    idle_intervals={server: 60.0 for server in OMLX_SERVER_IDS},
    freshness_limits={server: OMLX_FRESH_SECONDS for server in OMLX_SERVER_IDS},
    active_lease_seconds=6.0,
)


# Independent workers and an hourly cadence: an upstream release lookup must
# never delay activity samples or inherit the two-second dashboard cadence.
OMLX_UPDATE_COORDINATOR = StateCoordinator(
    collectors={server: (lambda server=server: _omlx_collect_update(server)) for server in OMLX_SERVER_IDS},
    intervals={server: OMLX_UPDATE_INTERVAL for server in OMLX_SERVER_IDS},
    idle_intervals={server: OMLX_UPDATE_INTERVAL for server in OMLX_SERVER_IDS},
    freshness_limits={server: OMLX_UPDATE_FRESH_SECONDS for server in OMLX_SERVER_IDS},
    active_lease_seconds=6.0,
)


def collect_omlx() -> dict:
    # A distinct lease: Watch/state/widget traffic cannot enable fast oMLX
    # collection. Cold reads return immediately, then independent workers fill
    # each server's last-good cache. Polling never waits for an upstream read.
    snapshot = OMLX_COORDINATOR.snapshot(client_active=True)
    updates = OMLX_UPDATE_COORDINATOR.snapshot(client_active=True)
    servers = []
    for server_id in OMLX_SERVER_IDS:
        data = snapshot["subsystems"][server_id]
        meta = snapshot["subsystemsMeta"][server_id]
        update = updates["subsystems"][server_id]
        update_meta = updates["subsystemsMeta"][server_id]
        servers.append({
            **data, "id": server_id, "ageSeconds": meta["ageSeconds"],
            "update": {**update, "ageSeconds": update_meta["ageSeconds"],
                       "stale": update_meta["stale"] or update_meta["error"] is not None},
            "lastSuccessAt": meta["updatedAt"],
            # Unlike control grace periods, a failed activity probe must not
            # keep last-known generation looking live even for six seconds.
            "stale": meta["stale"] or meta["error"] is not None,
            "error": meta["error"],
        })
    return {"ok": True, "version": 1, "servers": servers}


STATE_COORDINATOR = StateCoordinator()


def collect_state() -> dict:
    """Return state after renewing the bounded foreground-client lease."""
    return STATE_COORDINATOR.snapshot(client_active=True)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Event ring buffer
# --------------------------------------------------------------------------- #

# Imports must not read/rewrite live event history. Persistence is initialized
# explicitly by main() after configuration validation and logging setup.
EVENTS = EventStore(max_json_bytes=MAX_JSON_BODY_BYTES)


# --------------------------------------------------------------------------- #
# Service control
# --------------------------------------------------------------------------- #


def _validated_plist(spec: dict) -> Path | None:
    raw = spec.get("plist")
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = LAUNCH_AGENTS_DIR / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(LAUNCH_AGENTS_DIR)
    except ValueError:
        raise ValueError("service plist must be inside the user's LaunchAgents directory")
    if candidate.suffix != ".plist":
        raise ValueError("service plist must end in .plist")
    return candidate


def _run_launchctl(argv: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *argv], capture_output=True, text=True, timeout=timeout)


def _wait_for_service(name: str, spec: dict, *, loaded: bool | None = None, running: bool | None = None) -> dict:
    deadline = time.monotonic() + 5.0
    last = _service_status(name, spec)
    while time.monotonic() < deadline:
        last = _service_status(name, spec)
        if last.get("ok"):
            loaded_ok = loaded is None or last.get("loaded") is loaded
            running_ok = running is None or last.get("running") is running
            if loaded_ok and running_ok:
                return last
        time.sleep(0.15)
    return last


def _service_action(name: str, action: str) -> dict:
    services = _load_services()
    spec = services.get(name)
    if not isinstance(spec, dict):
        return {"ok": False, "service": name, "action": action, "error": f"unknown service {name!r}", "known": list(services)}
    label = spec.get("label")
    if not isinstance(label, str) or not label:
        return {"ok": False, "service": name, "action": action, "error": "service has no launchctl label"}
    if label in PROTECTED_LABELS:
        return {"ok": False, "service": name, "action": action, "error": "protected daemon service cannot be controlled"}
    if action not in {"status", "start", "stop", "restart"}:
        return _finish_service_action(name, action, False, "service action is not supported", label)
    if action != "status" and action not in _service_allowed_actions(spec):
        return _finish_service_action(name, action, False, "service action is not allowed", label)

    status = _service_status(name, spec)
    if action == "status":
        return status | {"action": action}
    if not status.get("ok") and action != "stop":
        result = status | {"action": action, "ok": False}
        EVENTS.add({"source": "jarvisd", "eventType": "service.action", "action": action, "ok": False,
                    "summary": f"Could not {action} {name}.", "error": result.get("error")})
        return result

    try:
        plist = _validated_plist(spec)
    except ValueError as exc:
        result = {"ok": False, "service": name, "action": action, "label": label, "error": str(exc)}
        EVENTS.add({"source": "jarvisd", "eventType": "service.action", "action": action, "ok": False,
                    "summary": f"Rejected {action} for {name}.", "error": str(exc)})
        return result

    target = _launchctl_target(label)
    commands: list[list[str]] = []
    expected_loaded: bool | None = None
    expected_running: bool | None = None
    if action == "stop":
        if status.get("loaded"):
            commands.append(["bootout", target])
        expected_loaded, expected_running = False, False
    elif action == "start":
        if not status.get("loaded"):
            if plist is None or not plist.is_file():
                return _finish_service_action(name, action, False, "service has no configured plist", label)
            commands.append(["bootstrap", f"gui/{os.getuid()}", str(plist)])
        commands.append(["kickstart", "-k", target])
        expected_loaded, expected_running = True, True
    elif action == "restart":
        if status.get("loaded"):
            commands.append(["kickstart", "-k", target])
        else:
            if plist is None or not plist.is_file():
                return _finish_service_action(name, action, False, "service has no configured plist", label)
            commands.extend([
                ["bootstrap", f"gui/{os.getuid()}", str(plist)],
                ["kickstart", "-k", target],
            ])
        expected_loaded, expected_running = True, True

    stderr = ""
    returncode = 0
    for command in commands:
        try:
            proc = _run_launchctl(command)
        except Exception as exc:  # noqa: BLE001
            return _finish_service_action(name, action, False, _safe_error(exc), label)
        returncode = proc.returncode
        stderr = _safe_error(proc.stderr)
        if proc.returncode != 0:
            return _finish_service_action(name, action, False, stderr or "launchctl action failed", label, returncode)

    verified = _wait_for_service(name, spec, loaded=expected_loaded, running=expected_running)
    ok = bool(verified.get("ok")) and verified.get("loaded") is expected_loaded and verified.get("running") is expected_running
    result = {
        **verified,
        "ok": ok,
        "action": action,
        "returncode": returncode,
        "stderr": stderr or None,
    }
    if not ok:
        result["error"] = "service did not reach the requested state"
    EVENTS.add({
        "source": "jarvisd",
        "eventType": "service.action",
        "action": action,
        "ok": ok,
        "summary": f"{action.capitalize()} {name} {'succeeded' if ok else 'failed'}.",
        "error": result.get("error"),
        "data": {"service": name, "label": label, "loaded": result.get("loaded"), "running": result.get("running")},
    })
    return result


def _finish_service_action(name: str, action: str, ok: bool, error: str | None, label: str, returncode: int | None = None) -> dict:
    result = {"ok": ok, "service": name, "action": action, "label": label, "returncode": returncode, "error": error}
    EVENTS.add({
        "source": "jarvisd",
        "eventType": "service.action",
        "action": action,
        "ok": ok,
        "summary": f"{action.capitalize()} {name} {'succeeded' if ok else 'failed'}.",
        "error": error,
        "data": {"service": name, "label": label},
    })
    return result


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #


class Handler(ControlHTTPMixin, BaseHTTPRequestHandler):
    server_version = f"jarvisd/{VERSION}"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
            self.log_message("client closed the connection")

    def log_request(self, code="-", size="-"):
        status = code.value if hasattr(code, "value") else code
        parsed = urllib.parse.urlsplit(self.path)
        normalized_path = parsed.path.rstrip("/") or "/"
        ip = self.client_address[0] if self.client_address else "?"
        if normalized_path == "/api/v1/security/status":
            # Do not log private device selectors or query strings.
            self.log_message("%s /api/v1/security/status %s", self.command, status)
            return
        if (
            self.command == "GET"
            and status == 200
            and not parsed.query
            and normalized_path in ROUTINE_REQUEST_LOG_PATHS
        ):
            emit, suppressed = ROUTINE_REQUEST_LOG_GATE.record(ip, normalized_path)
            if not emit:
                return
            if suppressed:
                self.log_message(
                    "coalesced %d successful GET %s requests",
                    suppressed,
                    normalized_path,
                )
        super().log_request(code, size)

    def log_message(self, fmt, *args):  # noqa: A002
        ts = time.strftime("%H:%M:%S")
        ip = self.client_address[0] if self.client_address else "?"
        request_id = getattr(self, "request_id", "-")
        sys.stderr.write(f"[jarvisd] {ts} {ip} [{request_id}] " + (fmt % args) + "\n")

    def _origin_headers(self) -> dict[str, str]:
        origin = self.headers.get("Origin", "").rstrip("/")
        if not origin:
            return {}
        if origin not in ALLOWED_ORIGINS:
            return {"Vary": "Origin"}
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "x-jarvis-token, content-type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Vary": "Origin",
        }

    def _send(self, code: int, body: dict, extra_headers: dict | None = None) -> None:
        self.request_id = getattr(self, "request_id", uuid.uuid4().hex[:12])
        data = b"" if code == 204 else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        if code != 204:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Request-ID", self.request_id)
        for key, value in self._origin_headers().items():
            self.send_header(key, value)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _reject_origin(self) -> bool:
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin and origin not in ALLOWED_ORIGINS:
            self.close_connection = True
            self._send(403, {"ok": False, "error": "origin not allowed"}, {"Connection": "close"})
            return True
        return False

    def _client_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        return auth.client_ip(self.client_address[0] if self.client_address else "")

    def _authorized(self, scope: str = "api") -> bool:
        return auth.authorized(
            mode=AUTH_MODE, address=self._client_ip(),
            token=self.headers.get("x-jarvis-token", ""), scope=scope,
            api_token=API_TOKEN, event_token=EVENT_TOKEN, trusted_cidrs=TRUSTED_CIDRS_RAW,
        )

    def _read_json(self) -> dict:
        try:
            return read_json(self.rfile, self.headers.get("Content-Length"), max_bytes=MAX_JSON_BODY_BYTES)
        except RequestInputError as exc:
            if exc.status == 413:
                self.close_connection = True
            raise

    def _auth_or_respond(self, scope: str = "api") -> bool:
        if self._reject_origin():
            return False
        if not self._authorized(scope):
            self.close_connection = True
            self._send(401 if AUTH_MODE == "token" else 403, {"ok": False, "error": "unauthorized"}, {"Connection": "close"})
            return False
        return True

    def do_OPTIONS(self):  # noqa: N802
        if self._reject_origin():
            return
        self._send(204, {}, {"Content-Length": "0"})

    def _method_not_allowed(self):
        self.close_connection = True
        self._send(405, {"ok": False, "error": "method not allowed"}, {"Allow": "GET, POST, OPTIONS", "Connection": "close"})

    def do_HEAD(self):  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self):  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self):  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self):  # noqa: N802
        self._method_not_allowed()

    def _room_audio(self, turn_id=None, speaker_id="pi"):
        port = {"pi": 8791, "mac": 8793}.get(speaker_id)
        if port is None:
            self._send(400, {"ok": False, "error": "Unknown room speaker"})
            return
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/control/" + ("stop" if turn_id is not None else "status"),
                data=json.dumps({"turnID": turn_id}).encode() if turn_id is not None else None,
                headers={"Content-Type": "application/json"})
            # Fixed loopback transport, no environment proxy or redirects.
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request(request.get_method(), urllib.parse.urlsplit(request.full_url).path,
                                   body=request.data, headers=dict(request.header_items()))
                response = connection.getresponse()
                data = response.read(4097)
                if len(data) > 4096 or response.status != 200: raise ValueError("unavailable")
                value = json.loads(data)
                if not isinstance(value, dict) or value.get("ok") is not True: raise ValueError("unavailable")
                safe = {key: value.get(key) for key in ("ok", "clientOnline", "phase", "turnID", "canStop", "ageSeconds")}
                if safe["phase"] not in {"idle", "processing", "speaking", "cancelling", "unavailable"}: raise ValueError("invalid phase")
                safe["speakerID"] = speaker_id
                self._send(200, safe)
            finally:
                connection.close()
        except Exception:
            self._send(503 if turn_id is None else 409, {"ok": False, "error": "Room audio unavailable or request changed."})

    def do_GET(self):  # noqa: N802
        self.request_id = uuid.uuid4().hex[:12]
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if self.path == "/api/v1/local-control":
            from jarvisd_core.local_control import authorized
            self.close_connection = True
            if not authorized(self):
                self._send(401, {"ok": False, "error": "unauthorized"})
            else:
                self._send(200, {"ok": True, "mode": "local-backend", "legacyDeviceWritesDisabled": True,
                    "durableOwnership": False})
            return
        if path == "/health":
            if self._reject_origin():
                return
            self._send(200, {"ok": True, "version": VERSION, "uptimeSeconds": round(time.time() - START_TIME, 1)})
            return
        if path == "/api/v1/security/status":
            if self._reject_origin():
                return
            # Occupancy-sensitive data requires the API token even when other
            # endpoints use trusted-network mode. No new credentials or scopes.
            if not auth.authorized(mode="token", address=self._client_ip(),
                    token=self.headers.get("x-jarvis-token", ""), scope="api",
                    api_token=API_TOKEN, event_token="", trusted_cidrs=""):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            selectors = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if set(selectors) != {"device"} or len(selectors["device"]) != 1:
                self._send(400, {"ok": False, "error": "one device selector required"})
                return
            code, body = security_status.read_status(SECURITY_CLI, selectors["device"][0])
            self._send(code, body)
            return
        if path == "/api/v1/omlx":
            if self._auth_or_respond(): self._send(200, collect_omlx())
            return
        if path.startswith("/api/v1/room-audio/"):
            if self._auth_or_respond(): self._room_audio(speaker_id=path.removeprefix("/api/v1/room-audio/"))
            return
        if path == "/api/v1/room-audio":
            if self._auth_or_respond(): self._room_audio()
            return
        if path == "/api/v1/state":
            if not self._auth_or_respond():
                return
            # Authenticated hosts may request an immediate refresh of the
            # read-only Codex usage collector. The response remains the fast
            # current snapshot; clients can observe `refreshing` and poll the
            # ordinary state endpoint for completion.
            for subsystem in query.get("refresh", []):
                if subsystem in {"codexQuota", "purifier"}:
                    if subsystem == "purifier":
                        STATE_COORDINATOR.request_refresh(subsystem, retry_cooldown=query.get("retryCooldown") == ["true"])
                    else:
                        STATE_COORDINATOR.request_refresh(subsystem)
            self._send(200, collect_state())
            return
        if path == "/api/v1/events":
            if not self._auth_or_respond():
                return
            since = query.get("since", [None])[0]
            limit = query.get("limit", ["100"])[0]
            try:
                since_i = int(since) if since is not None else None
                limit_i = int(limit)
            except (TypeError, ValueError):
                self._send(400, {"ok": False, "error": "since/limit must be integers"})
                return
            events = EVENTS.list(since=since_i, limit=limit_i)
            self._send(200, {"ok": True, "count": len(events), "events": events})
            return
        if path == "/api/v1/services":
            if not self._auth_or_respond():
                return
            self._send(200, {"ok": True, "services": _services_state(_load_services())})
            return
        if path == "/api/v1/scheduled-jobs":
            if not self._auth_or_respond():
                return
            self._send(200, _scheduled_jobs())
            return
        if path == "/api/v1/notification-status":
            if not self._auth_or_respond():
                return
            self._send(200, _notification_status())
            return
        if path == "/api/v1/scheduled-job-results":
            if not self._auth_or_respond():
                return
            raw_after = query.get("after", [None])[0]
            raw_limit = query.get("limit", ["50"])[0]
            raw_job_id = query.get("jobId", [None])[0]
            try:
                after = int(raw_after) if raw_after is not None else None
                limit = int(raw_limit)
            except (TypeError, ValueError):
                self._send(400, {"ok": False, "error": "after/limit must be integers"})
                return
            if after is not None and (after < 0 or after > 9_223_372_036_854_775_807):
                self._send(400, {"ok": False, "error": "after is out of range"})
                return
            if limit < 1 or limit > MAX_SCHEDULED_JOB_RESULTS:
                self._send(400, {"ok": False, "error": f"limit must be between 1 and {MAX_SCHEDULED_JOB_RESULTS}"})
                return
            if raw_job_id is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", raw_job_id):
                self._send(400, {"ok": False, "error": "jobId is invalid"})
                return
            self._send(200, _scheduled_job_results(after=after, limit=limit, job_id=raw_job_id))
            return
        if path == "/api/v1/signing/status":
            if not self._auth_or_respond():
                return
            self._send(200, _signing_renewal_status())
            return
        if path.startswith("/api/v1/services/"):
            if not self._auth_or_respond():
                return
            name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            self._send(200, _service_action(name, "status"))
            return
        self._send(404, {"ok": False, "error": "not found", "path": path})

    def do_POST(self):  # noqa: N802
        self.request_id = uuid.uuid4().hex[:12]
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/v1/room-audio/stop" or (path.startswith("/api/v1/room-audio/") and path.endswith("/stop")):
            if not self._auth_or_respond(): return
            speaker_id = "pi" if path == "/api/v1/room-audio/stop" else path.removeprefix("/api/v1/room-audio/").removesuffix("/stop")
            if speaker_id not in {"pi", "mac"}:
                self._send(400, {"ok": False, "error": "Unknown room speaker"})
                return
            try:
                payload = self._read_json()
                turn = payload.get("turnID")
                if set(payload) != {"turnID"} or not isinstance(turn, str) or not re.fullmatch(r"[a-f0-9]{32}", turn):
                    raise ValueError("invalid turn")
            except (RequestInputError, ValueError, TypeError):
                self._send(400, {"ok": False, "error": "Exact room turn ID required."})
                return
            self._room_audio(turn, speaker_id=speaker_id)
            return
        if path == "/api/jarvis/events":
            if not self._auth_or_respond("events"):
                return
            try:
                payload = self._read_json()
                event = EVENTS.add(payload)
            except (RequestInputError, EventInputError) as exc:
                if isinstance(exc, RequestInputError):
                    self._send(exc.status, {"ok": False, "error": exc.message})
                else:
                    self._send(400, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, "seq": event["seq"]})
            return
        if path == "/api/v1/signing/renew":
            if not self._auth_or_respond():
                return
            raw_length = self.headers.get("Content-Length")
            if raw_length not in (None, "0"):
                self.close_connection = True
                self._send(400, {"ok": False, "error": "signing renewal does not accept a request body"})
                return
            started, result = _start_signing_renewal()
            self._send(202 if started else 409, result)
            return
        if self.path == "/api/v1/device-command":
            if not self._auth_or_respond():
                return
            self.close_connection = True
            if not hasattr(self.server, "native_request_lock"):
                self._send(503, {"ok": False, "error": "Native device control unavailable"})
                return
            ids = self.headers.get_all("x-jarvis-request-id", [])
            if (len(ids) != 1 or re.fullmatch(r"[0-9a-f]{32}", ids[0]) is None
                    or self.headers.get_all("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length", [])) != 1
                    or self.headers.get("Content-Type") != "application/json"):
                self._send(400, {"ok": False, "error": "Invalid native command framing or request ID"})
                return
            from jarvisd_core.local_control import validated
            self.connection.settimeout(5)
            try:
                payload = self._read_json()
                action, params = validated(payload, STATE_COORDINATOR.snapshot)
            except RequestInputError as exc:
                self._send(exc.status, {"ok": False, "error": exc.message})
                return
            except (ValueError, TypeError):
                self._send(400, {"ok": False, "error": "Invalid native device command"})
                return
            with self.server.native_request_lock:
                if ids[0] in self.server.native_request_ids:
                    self._send(409, {"ok": False, "error": "Request already received; delivery may be unknown. Inspect state, do not resend."})
                    return
                if len(self.server.native_request_ids) >= 4096:
                    self._send(503, {"ok": False, "error": "Native request capacity reached; no command sent."})
                    return
                self.server.native_request_ids.add(ids[0])
            try:
                result = dispatch_command(action, params)
                self._send(200, _public_command_result(action, result))
            except CommandError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            except AdmissionError as exc:
                self._send(409, {"ok": False, "error": str(exc)})
            except Exception:
                self._send(503, {"ok": False, "error": "Command outcome unknown; inspect state, never retry automatically"})
            return
        if self.path == "/api/v1/local-control":
            from jarvisd_core.local_control import authorized, validated
            self.close_connection = True
            if not authorized(self):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            if (self.headers.get_all("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1
                    or self.headers.get("Content-Type") != "application/json"):
                self._send(400, {"ok": False, "error": "invalid framing"})
                return
            self.connection.settimeout(5)
            try:
                payload = self._read_json()
                action, params = validated(payload, STATE_COORDINATOR.snapshot)
            except RequestInputError as exc:
                self._send(exc.status, {"ok": False, "error": exc.message})
                return
            except (ValueError, TypeError):
                self._send(400, {"ok": False, "error": "Invalid local command or ambiguous purifier selector"})
                return
            try:
                result = dispatch_command(action, params)
                self._send(200, _public_command_result(action, result))
            except CommandError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            except AdmissionError as exc:
                self._send(409, {"ok": False, "error": str(exc)})
            except Exception:
                self._send(503, {"ok": False, "error": "Command outcome unknown; inspect state, never retry automatically"})
            return
        if path == "/api/v1/command":
            if not self._auth_or_respond():
                return
            try:
                payload = self._read_json()
            except RequestInputError as exc:
                self._send(exc.status, {"ok": False, "error": exc.message})
                return
            action = payload.get("action")
            params = payload.get("params", {})
            if (getattr(self.server, "legacy_device_writes_closed", False) is True
                    and type(action) is str and action in V2_DEVICE_WRITES):
                self._send(409, {"ok": False, "action": action,
                    "error": "Legacy device writes are disabled; use the local CLI/Pi client. Do not retry here."})
                return
            try:
                raw_result = dispatch_command(action, params)
            except CommandError as exc:
                self._send(400, {"ok": False, "error": str(exc), "action": action if isinstance(action, str) else None})
                return
            except AdmissionError as exc:
                self._send(409, {"ok": False, "error": str(exc), "action": action if isinstance(action, str) else None})
                return
            # Return only the native-client contract, never argv, local paths,
            # adapter stdout, or private device identifiers.
            self._send(200, _public_command_result(action, raw_result))
            return
        if path.startswith("/api/v1/services/"):
            if not self._auth_or_respond():
                return
            try:
                payload = self._read_json()
            except RequestInputError as exc:
                self._send(exc.status, {"ok": False, "error": exc.message})
                return
            name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            action = payload.get("action", "status")
            if not isinstance(action, str):
                self._send(400, {"ok": False, "error": "action must be a string"})
                return
            self._send(200, _service_action(name, action))
            STATE_COORDINATOR.request_refresh("services")
            return
        self._send(404, {"ok": False, "error": "not found", "path": path})


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(*, control_factory=None, local_control=False) -> int:
    global EVENTS
    if local_control and control_factory is not None:
        raise ValueError("Select one control mode")
    local_token = None
    if local_control:
        from jarvisd_core.local_control import read_token
        local_token = read_token()
    validate_config()
    log_writer = configure_bounded_stderr()
    EVENTS = EventStore(persist_path=EVENTS_FILE, max_json_bytes=MAX_JSON_BODY_BYTES)
    server = runtime = None
    try:
        STATE_COORDINATOR.start()
        if AUTH_MODE == "trusted-network":
            sys.stderr.write(f"[jarvisd] trusted-network mode; CIDRs={TRUSTED_CIDRS_RAW}\n")
        else:
            sys.stderr.write("[jarvisd] token mode enabled for app API\n")
        # Explicit trusted composition only. No env/body boolean can activate it.
        server_type = ControlHTTPServer if control_factory is not None or local_control else ThreadingHTTPServer
        server = server_type((HOST, PORT), Handler)
        server.daemon_threads = True
        if local_control:
            server.local_control_token = local_token
            server.native_request_lock = threading.Lock()
            server.native_request_ids = set()
        if control_factory is not None:
            from jarvisd_core.control_runtime import ControlRuntime
            runtime = control_factory(server)
            if type(runtime) is not ControlRuntime:
                runtime = None
                raise RuntimeError("Invalid control runtime composition")
            runtime.install(server)
        sys.stderr.write(f"[jarvisd] listening on {HOST}:{PORT} (version {VERSION})\n")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if runtime is not None:
                runtime.close()
        finally:
            if server is not None:
                server.server_close()
            STATE_COORDINATOR.stop()
            OMLX_COORDINATOR.stop()
            OMLX_UPDATE_COORDINATOR.stop()
            if log_writer is not None:
                log_writer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
