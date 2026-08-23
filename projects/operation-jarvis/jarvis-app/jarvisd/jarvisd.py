#!/usr/bin/env python3
"""jarvisd — the Operation JARVIS app backend.

A stdlib-only HTTP daemon (ThreadingHTTPServer) that is the only control plane
for the native iOS/watchOS app. It aggregates cached state, runs allowlisted
``jarvis-cli`` commands, ingests events, and manages registered LaunchAgents.

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

import collections
import concurrent.futures
import copy
import datetime as dt
import hmac
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

VERSION = "0.2.0"
START_TIME = time.time()


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


JARVISD_DIR = Path(__file__).resolve().parent


def _find_ancestor(start: Path, marker: str) -> Path | None:
    """Return the nearest ancestor containing ``marker``."""
    for directory in (start, *start.parents):
        if (directory / marker).exists():
            return directory
    return None


if os.environ.get("JARVISD_OPERATION_ROOT"):
    OPERATION_ROOT = Path(os.environ["JARVISD_OPERATION_ROOT"]).resolve()
else:
    OPERATION_ROOT = _find_ancestor(JARVISD_DIR, "jarvis-cli") or JARVISD_DIR.parent.parent

if os.environ.get("JARVISD_PROJECT_ROOT"):
    PROJECT_ROOT = Path(os.environ["JARVISD_PROJECT_ROOT"]).resolve()
else:
    PROJECT_ROOT = _find_ancestor(JARVISD_DIR, ".env") or OPERATION_ROOT.parent
JARVIS_ROOT = _find_ancestor(JARVISD_DIR, ".pi") or PROJECT_ROOT

JARVIS_CLI = OPERATION_ROOT / "jarvis-cli"
_load_env_file(PROJECT_ROOT / ".env")

PORT = int(os.environ.get("JARVISD_PORT", "8790"))
# LAN + Tailscale access is required by the app. Authentication below narrows
# which clients may use the wildcard bind; do not change this to tokenless
# Internet exposure.
HOST = os.environ.get("JARVISD_HOST", "0.0.0.0")
AUTH_MODE = os.environ.get("JARVISD_AUTH_MODE", "trusted-network").strip().lower()
API_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")
EVENT_TOKEN = os.environ.get("JARVISD_EVENT_TOKEN", "")
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
DISCORD_CRON_RUNNER = Path(
    os.environ.get("JARVISD_DISCORD_CRON_RUNNER", str(JARVIS_ROOT / ".pi" / "discord-cron" / "runner.py"))
).expanduser().resolve()
SCHEDULED_JOBS_TIMEOUT = min(15.0, max(1.0, float(os.environ.get("JARVISD_SCHEDULED_JOBS_TIMEOUT", "5"))))
MAX_SCHEDULED_JOBS = min(500, max(1, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOBS", "100"))))
MAX_SCHEDULED_JOBS_OUTPUT_BYTES = min(
    1024 * 1024,
    max(4096, int(os.environ.get("JARVISD_MAX_SCHEDULED_JOBS_OUTPUT_BYTES", str(256 * 1024)))),
)
CODEX_QUOTAS_SCRIPT = Path(
    os.environ.get("JARVISD_CODEX_QUOTAS_SCRIPT", str(JARVIS_ROOT / "projects" / "quotas" / "quotas.py"))
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

AUTH_MODES = {"trusted-network", "token"}
PROTECTED_LABELS = {"com.operation-jarvis.jarvisd", "com.operation-jarvis.jarvisd-resurrector"}


def _trusted_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in TRUSTED_CIDRS_RAW.split(","):
        raw = raw.strip()
        if raw:
            networks.append(ipaddress.ip_network(raw, strict=False))
    return tuple(networks)


def validate_config() -> None:
    """Fail early for unsafe/ambiguous daemon configuration."""
    if AUTH_MODE not in AUTH_MODES:
        raise RuntimeError(f"JARVISD_AUTH_MODE must be one of {sorted(AUTH_MODES)}")
    if MAX_JSON_BODY_BYTES < 1024 or MAX_JSON_BODY_BYTES > 10 * 1024 * 1024:
        raise RuntimeError("JARVISD_MAX_JSON_BODY_BYTES must be between 1024 and 10485760")
    if AUTH_MODE == "token" and not API_TOKEN:
        raise RuntimeError("JARVISD_AUTH_MODE=token requires JARVIS_API_TOKEN")
    if AUTH_MODE == "trusted-network" and not _trusted_networks():
        raise RuntimeError("trusted-network mode requires at least one trusted CIDR")


# --------------------------------------------------------------------------- #
# Command allowlist
# --------------------------------------------------------------------------- #

PLUG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
PURIFIER_SETTINGS = (
    "power", "mode", "speed", "display", "child-lock", "light-detection", "auto-preference", "timer"
)
PURIFIER_MODES = ("auto", "manual", "sleep", "pet")
PURIFIER_SPEEDS = (1, 2, 3, 4)
PURIFIER_POWER_STATES = ("on", "off", "toggle")
PURIFIER_AUTO_PREFERENCES = ("default", "efficient", "quiet")


class CommandError(ValueError):
    """Raised when a command action or params fail validation."""


def _require_str(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"missing required string param {key!r}")
    return value.strip()


def _plug_name(params: dict) -> str:
    name = _require_str(params, "plug")
    if not PLUG_NAME_RE.fullmatch(name):
        raise CommandError("invalid plug name")
    return name


def _opt_int(params: dict, key: str, lo: int, hi: int) -> int | None:
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"param {key!r} must be an integer")
    if not (lo <= value <= hi):
        raise CommandError(f"param {key!r} must be between {lo} and {hi}")
    return value


def _opt_enum(params: dict, key: str, choices: tuple[str, ...]) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value not in choices:
        raise CommandError(f"param {key!r} must be one of {', '.join(choices)}")
    return value


def _purifier_set_args(params: dict) -> list[str]:
    setting = _require_str(params, "setting")
    if setting not in PURIFIER_SETTINGS:
        raise CommandError(f"unsupported purifier setting {setting!r}")
    args = ["purifier-set", setting]

    value = params.get("value")
    if value is not None:
        if not isinstance(value, str) or not value.strip():
            raise CommandError("param 'value' must be a non-empty string")
        value = value.strip()
        if setting == "mode" and value not in PURIFIER_MODES:
            raise CommandError(f"invalid mode {value!r}")
        if setting in ("power", "display", "child-lock", "light-detection") and value not in PURIFIER_POWER_STATES:
            raise CommandError(f"invalid state for {setting}")
        if setting == "auto-preference" and value not in PURIFIER_AUTO_PREFERENCES:
            raise CommandError(f"invalid auto-preference {value!r}")
        args.append(value)

    level = _opt_int(params, "level", 1, 4)
    if level is not None:
        args += ["--level", str(level)]
    state = _opt_enum(params, "state", PURIFIER_POWER_STATES)
    if state is not None:
        args += ["--state", state]
    minutes = _opt_int(params, "minutes", 1, 24 * 60)
    if minutes is not None:
        args += ["--minutes", str(minutes)]
    room_size = _opt_int(params, "roomSize", 1, 10000)
    if room_size is not None:
        args += ["--room-size", str(room_size)]
    return args


COMMANDS: dict[str, tuple[Callable[[dict], list[str]], str]] = {
    "status": (lambda p: ["status", "--no-cast"], "Overall Operation JARVIS status (no Cast)."),
    "plug-list": (lambda p: ["plug-list"], "List configured smart plugs."),
    "plug-status": (lambda p: ["plug-status", _plug_name(p)], "Show one plug's power state."),
    "plug-on": (lambda p: ["plug-on", _plug_name(p)], "Turn a plug on."),
    "plug-off": (lambda p: ["plug-off", _plug_name(p)], "Turn a plug off."),
    # Retained for compatibility with other local callers; the native UI uses
    # desired-state plug-on/plug-off so repeated taps are not invertible.
    "plug-toggle": (lambda p: ["plug-toggle", _plug_name(p)], "Toggle a plug."),
    "purifier-status": (lambda p: ["purifier-status"], "Show air purifier status."),
    "purifier-set": (_purifier_set_args, "Set one air purifier setting."),
}


def build_command(action: Any, params: Any) -> list[str]:
    if not isinstance(action, str) or action not in COMMANDS:
        raise CommandError(f"action {action!r} is not allowlisted")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise CommandError("params must be an object")
    argv = COMMANDS[action][0](params)
    return [str(JARVIS_CLI), "--json", *argv]


# --------------------------------------------------------------------------- #
# Subprocess helpers
# --------------------------------------------------------------------------- #


def _safe_error(value: Any, limit: int = 1000) -> str:
    """Return a bounded diagnostic without exposing local argv/path details."""
    text = str(value or "").strip()
    text = re.sub(r"(/Users/[^\s]+|/private/[^\s]+|/tmp/[^\s]+)", "<local-path>", text)
    return text[-limit:]


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


def _purifier_command_data(result: dict) -> dict | None:
    air_purifier = result.get("airPurifier")
    if isinstance(air_purifier, dict) and isinstance(air_purifier.get("data"), dict):
        return air_purifier["data"]
    purifier = result.get("purifier")
    return purifier if isinstance(purifier, dict) else None


def _purifier_expectation(params: Any) -> dict | None:
    if not isinstance(params, dict):
        return None
    setting = params.get("setting")
    value = params.get("value")
    if setting == "power" and value in {"on", "off"}:
        return {"isOn": value == "on"}
    if setting == "mode" and value in PURIFIER_MODES:
        return {"mode": value}
    if setting == "speed":
        level = params.get("level", value)
        if isinstance(level, float) and level.is_integer():
            level = int(level)
        if isinstance(level, int) and level in PURIFIER_SPEEDS:
            return {"mode": "manual", "fanLevel": level}
    return None


def _purifier_matches(state: dict, expected: dict) -> bool:
    for key, value in expected.items():
        if key == "fanLevel":
            if state.get("fanSetLevel") != value and state.get("fanLevel") != value:
                return False
        elif state.get(key) != value:
            return False
    return True


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


def _pi_sessions() -> dict:
    active_local = 0
    local_total = 0
    if PI_LOCAL_SESSIONS.is_dir():
        for f in PI_LOCAL_SESSIONS.glob("*.json"):
            local_total += 1
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("active"):
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
    }


def _plugs() -> dict:
    listing = run_cli_json([str(JARVIS_CLI), "--json", "plug-list"], timeout=12, env=COLLECTOR_ENV)
    plugs_map = (listing.get("plugs") or {}) if isinstance(listing, dict) else {}
    if not isinstance(plugs_map, dict):
        return {"ok": False, "error": "plug-list returned invalid data"}
    # An empty configured list is valid. It is different from a failed list.
    if listing.get("ok") is False and not plugs_map:
        return {"ok": False, "error": "plug-list failed"}
    names = list(plugs_map.keys())
    results: dict[str, dict] = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(len(names), 8)))
    futures = {
        name: pool.submit(
            run_cli_json,
            [str(JARVIS_CLI), "--json", "plug-status", name],
            timeout=10,
            env=COLLECTOR_ENV,
        )
        for name in names
    }
    try:
        for name, future in futures.items():
            try:
                result = future.result(timeout=11)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": _safe_error(exc)}
            plug = result.get("plug") if isinstance(result, dict) else None
            results[name] = {
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "isOn": plug.get("is_on") if isinstance(plug, dict) else None,
                "host": plug.get("host") if isinstance(plug, dict) else plugs_map.get(name),
                "rssi": plug.get("rssi") if isinstance(plug, dict) else None,
                "alias": plug.get("alias") if isinstance(plug, dict) else None,
                "error": _safe_error(result.get("error")) if isinstance(result, dict) and result.get("error") else None,
            }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    successful = [r for r in results.values() if r.get("ok")]
    on_count = sum(1 for result in successful if result.get("isOn") is True)
    return {
        "ok": bool(names == [] or successful),
        "count": len(results),
        "onCount": on_count,
        "plugs": results,
    }


def _purifier_state(data: dict) -> dict:
    return {
        "ok": True,
        "isOn": data.get("is_on"),
        "power": data.get("power"),
        "mode": data.get("mode"),
        "fanLevel": data.get("fan_level"),
        "fanSetLevel": data.get("fan_set_level"),
        "pm25": data.get("pm25"),
        "airQualityLevel": data.get("air_quality_level"),
        "filterLife": data.get("filter_life"),
        "childLock": data.get("child_lock"),
        "display": data.get("display_status"),
        "timer": data.get("timer"),
        "name": data.get("name"),
        "model": data.get("model"),
    }


def _purifier() -> dict:
    result = run_cli_json([str(JARVIS_CLI), "--json", "purifier-status"], timeout=12, env=COLLECTOR_ENV)
    data = result.get("airPurifier", {}).get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "error": "purifier-status failed"}
    return _purifier_state(data)


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
    if not DISCORD_CRON_RUNNER.is_file():
        return _scheduled_jobs_unavailable()
    try:
        proc = subprocess.run(
            [sys.executable, str(DISCORD_CRON_RUNNER), "--json", "list-public"],
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
        # This is the quotas project's read-only Codex check. Never add a probe
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


class StateCoordinator:
    """Background, single-flight subsystem cache for the state endpoint."""

    NONCRITICAL_SUBSYSTEMS = frozenset({"codexQuota"})
    DEFAULT_INTERVALS = {
        "pi": 5.0,
        "plugs": 10.0,
        "services": 15.0,
        "purifier": 45.0,
        "network": 60.0,
        "codexQuota": 300.0,
    }

    def __init__(
        self,
        collectors: dict[str, Callable[[], dict]] | None = None,
        intervals: dict[str, float] | None = None,
        now: Callable[[], float] = time.time,
    ):
        self.collectors = collectors or {
            "plugs": _plugs,
            "purifier": _purifier,
            "pi": _pi_sessions,
            "services": lambda: {"ok": True, "services": _services_state(_load_services())},
            "network": _collect_network,
            "codexQuota": _codex_quota,
        }
        self.intervals = {**self.DEFAULT_INTERVALS, **(intervals or {})}
        self._now = now
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {
            name: {
                "data": None,
                "updatedAt": None,
                "lastGoodAt": None,
                "error": None,
                "stale": True,
                "refreshing": False,
                "nextDue": 0.0,
                "revision": 0,
                "pending": None,
            }
            for name in self.collectors
        }
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._scheduler: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop.clear()
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(2, len(self.collectors)))
            self._scheduler = threading.Thread(target=self._run_scheduler, name="jarvisd-state", daemon=True)
            self._scheduler.start()

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._stop.set()
            executor = self._executor
            scheduler = self._scheduler
            self._started = False
            self._executor = None
            self._scheduler = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if scheduler is not None:
            scheduler.join(timeout=0.5)

    def request_refresh(self, name: str) -> None:
        with self._lock:
            if name in self._records:
                self._records[name]["nextDue"] = 0.0
        self.start()

    def _apply_authoritative_locked(self, name: str, data: dict) -> None:
        record = self._records[name]
        now = self._now()
        record["data"] = copy.deepcopy(data)
        record["updatedAt"] = _iso_now()
        record["lastGoodAt"] = now
        record["error"] = None
        record["stale"] = False
        record["nextDue"] = 0.0
        record["revision"] += 1

    def apply_plug_result(self, plug: Any) -> bool:
        """Merge an authoritative desired-state command into the cache."""
        if not isinstance(plug, dict):
            return False
        name = plug.get("name")
        is_on = plug.get("is_on")
        if not isinstance(name, str) or not name or not isinstance(is_on, bool):
            return False
        with self._lock:
            record = self._records.get("plugs")
            if record is None:
                return False
            data = copy.deepcopy(record["data"]) if isinstance(record["data"], dict) else {"ok": True, "plugs": {}}
            plugs = copy.deepcopy(data.get("plugs")) if isinstance(data.get("plugs"), dict) else {}
            state = copy.deepcopy(plugs.get(name)) if isinstance(plugs.get(name), dict) else {}
            state.update({"ok": True, "isOn": is_on, "error": None})
            for source, target in (("host", "host"), ("rssi", "rssi"), ("alias", "alias")):
                if source in plug:
                    state[target] = copy.deepcopy(plug[source])
            plugs[name] = state
            data.update({
                "ok": True,
                "count": len(plugs),
                "onCount": sum(1 for value in plugs.values() if isinstance(value, dict) and value.get("isOn") is True),
                "plugs": plugs,
            })
            self._apply_authoritative_locked("plugs", data)
        self.start()
        return True

    def apply_purifier_result(self, data: Any, expected: dict | None = None) -> bool:
        if not isinstance(data, dict):
            return False
        state = _purifier_state(data)
        with self._lock:
            record = self._records.get("purifier")
            if record is None:
                return False
            if data.get("verification_pending") is True and expected:
                # VeSync accepted the write but returned old cloud state. Keep
                # that data visible only as stale and poll quickly until the
                # desired state is observed; controls remain disabled meanwhile.
                record["data"] = copy.deepcopy(state)
                record["updatedAt"] = _iso_now()
                record["error"] = None
                record["stale"] = True
                record["nextDue"] = self._now() + 2.0
                record["pending"] = {
                    "expected": copy.deepcopy(expected),
                    "deadline": self._now() + 90.0,
                }
                record["revision"] += 1
            else:
                record["pending"] = None
                self._apply_authoritative_locked("purifier", state)
        self.start()
        return True

    def _run_scheduler(self) -> None:
        while not self._stop.is_set():
            now = self._now()
            with self._lock:
                executor = self._executor
                if executor is not None:
                    for name, record in self._records.items():
                        if not record["refreshing"] and now >= record["nextDue"]:
                            record["refreshing"] = True
                            revision = record["revision"]
                            future = executor.submit(self._collect_one, name)
                            future.add_done_callback(lambda f, n=name, r=revision: self._complete(n, f, r))
            self._stop.wait(0.25)

    def _collect_one(self, name: str) -> dict:
        try:
            return self.collectors[name]()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _safe_error(exc)}

    def _complete(self, name: str, future: concurrent.futures.Future, revision: int) -> None:
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": _safe_error(exc)}
        now = self._now()
        with self._lock:
            record = self._records[name]
            record["refreshing"] = False
            if revision != record["revision"]:
                # A command supplied newer authoritative data while this
                # collection was in flight. Discard the old read and collect
                # again rather than reverting the UI to pre-command state.
                record["nextDue"] = 0.0
                return
            pending = record.get("pending")
            if (
                name == "purifier"
                and isinstance(pending, dict)
                and isinstance(result, dict)
                and result.get("ok") is True
            ):
                expected = pending.get("expected")
                if isinstance(expected, dict) and _purifier_matches(result, expected):
                    record["pending"] = None
                elif now < float(pending.get("deadline", 0.0)):
                    record["data"] = copy.deepcopy(result)
                    record["updatedAt"] = _iso_now()
                    record["error"] = None
                    record["stale"] = True
                    record["nextDue"] = now + 3.0
                    return
                else:
                    record["data"] = copy.deepcopy(result)
                    record["updatedAt"] = _iso_now()
                    record["error"] = "purifier write verification is still pending"
                    record["stale"] = True
                    record["pending"] = None
                    record["nextDue"] = now + max(0.5, float(self.intervals.get(name, 30.0)))
                    return
            record["nextDue"] = now + max(0.5, float(self.intervals.get(name, 30.0)))
            if isinstance(result, dict) and result.get("ok") is True:
                record["data"] = copy.deepcopy(result)
                record["updatedAt"] = _iso_now()
                record["lastGoodAt"] = now
                record["error"] = None
                record["stale"] = False
            else:
                record["error"] = _safe_error(result.get("error") if isinstance(result, dict) else result)
                record["stale"] = True

    def snapshot(self) -> dict:
        self.start()
        with self._lock:
            records = copy.deepcopy(self._records)
        subsystems: dict[str, dict] = {}
        metadata: dict[str, dict] = {}
        now = self._now()
        for name, record in records.items():
            data = copy.deepcopy(record["data"]) if record["data"] is not None else {
                "ok": False,
                "error": record["error"] or "loading",
            }
            data["stale"] = bool(record["stale"])
            data["refreshing"] = bool(record["refreshing"])
            if record["updatedAt"]:
                data["updatedAt"] = record["updatedAt"]
            if record["error"]:
                data["lastError"] = record["error"]
            subsystems[name] = data
            age = None if record["lastGoodAt"] is None else max(0.0, now - record["lastGoodAt"])
            metadata[name] = {
                "ok": data.get("ok") is True,
                "updatedAt": record["updatedAt"],
                "ageSeconds": round(age, 1) if age is not None else None,
                "stale": bool(record["stale"]),
                "refreshing": bool(record["refreshing"]),
                "error": record["error"],
            }

        plugs = subsystems.get("plugs", {})
        purifier = subsystems.get("purifier", {})
        pi = subsystems.get("pi", {})
        critical_records = {
            name: record for name, record in records.items() if name not in self.NONCRITICAL_SUBSYSTEMS
        }
        ages = [
            metadata[name]["ageSeconds"]
            for name in critical_records
            if metadata[name]["ageSeconds"] is not None
        ]
        return {
            "ok": True,
            "loading": any(record["data"] is None for record in critical_records.values()),
            "refreshing": any(record["refreshing"] for record in critical_records.values()),
            "stale": any(record["stale"] for record in critical_records.values()),
            "generatedAt": _iso_now(),
            "ageSeconds": round(max(ages), 1) if ages else None,
            "version": VERSION,
            "uptimeSeconds": round(time.time() - START_TIME, 1),
            "subsystems": subsystems,
            "subsystemsMeta": metadata,
            "summary": {
                "plugsOn": plugs.get("onCount") if plugs.get("ok") else None,
                "plugsTotal": plugs.get("count") if plugs.get("ok") else None,
                "purifierOn": purifier.get("isOn") if purifier.get("ok") else None,
                "pm25": purifier.get("pm25") if purifier.get("ok") else None,
                "piActive": pi.get("active") if pi.get("ok") else None,
            },
        }


def _collect_network() -> dict:
    return {"ok": True, "macLanIp": _lan_ip(), "tailscaleIp": _tailscale_ip()}


STATE_COORDINATOR = StateCoordinator()


def collect_state() -> dict:
    """Compatibility wrapper; returns the fast cached composition."""
    return STATE_COORDINATOR.snapshot()


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Event ring buffer
# --------------------------------------------------------------------------- #

EVENT_FIELDS = {"source", "eventType", "action", "ok", "summary", "error", "artifacts", "data", "at"}
EVENT_STRING_LIMITS = {"source": 120, "eventType": 160, "action": 160, "summary": 2000, "error": 2000, "at": 80}


class EventInputError(ValueError):
    """Raised when an event payload is not safe to persist."""


def _validate_event(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise EventInputError("event body must be a JSON object")
    unknown = set(payload) - EVENT_FIELDS
    if unknown:
        raise EventInputError("event contains unsupported fields")
    event: dict[str, Any] = {}
    for key, value in payload.items():
        if key in EVENT_STRING_LIMITS:
            if value is not None and (not isinstance(value, str) or len(value) > EVENT_STRING_LIMITS[key]):
                raise EventInputError(f"event field {key!r} is invalid or too long")
            event[key] = value
        elif key == "ok":
            if value is not None and not isinstance(value, bool):
                raise EventInputError("event field 'ok' must be boolean or null")
            event[key] = value
        elif key == "artifacts":
            if value is not None and (not isinstance(value, list) or len(value) > 20):
                raise EventInputError("event artifacts must be an array of at most 20 items")
            event[key] = value or []
        elif key == "data":
            if value is not None and not isinstance(value, dict):
                raise EventInputError("event data must be an object or null")
            event[key] = value
    encoded_size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
    if encoded_size > MAX_JSON_BODY_BYTES:
        raise EventInputError("event payload is too large")
    return event


class EventStore:
    def __init__(self, max_events: int = 500, persist_path: Path | None = None):
        self._max_events = max(1, int(max_events))
        self._events: collections.deque[dict] = collections.deque(maxlen=self._max_events)
        self._lock = threading.RLock()
        self._seq = 0
        self._persist_path = persist_path
        if persist_path:
            try:
                persist_path.parent.mkdir(parents=True, exist_ok=True)
                if persist_path.exists():
                    self._load(persist_path)
                    self._rewrite_locked()
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"[jarvisd] event store unavailable: {_safe_error(exc)}\n")
                self._persist_path = None

    def _load(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            continue
                        self._events.append(event)
                        self._seq = max(self._seq, int(event.get("seq", 0)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError:
            return

    def _rewrite_locked(self) -> None:
        if not self._persist_path:
            return
        path = self._persist_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def add(self, payload: dict) -> dict:
        event = _validate_event(payload)
        with self._lock:
            evicted = len(self._events) == self._max_events
            self._seq += 1
            event["seq"] = self._seq
            event.setdefault("receivedAt", _iso_now())
            self._events.append(event)
            if self._persist_path:
                try:
                    if evicted or (self._persist_path.exists() and self._persist_path.stat().st_size > 1024 * 1024):
                        self._rewrite_locked()
                    else:
                        with self._persist_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                except Exception as exc:  # noqa: BLE001
                    sys.stderr.write(f"[jarvisd] could not persist event: {_safe_error(exc)}\n")
            return copy.deepcopy(event)

    def list(self, since: int | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            events = list(self._events)
        if since is not None:
            events = [event for event in events if int(event.get("seq", 0)) > int(since)]
        limit = max(1, min(int(limit), self._max_events))
        return copy.deepcopy(events[-limit:])


EVENTS = EventStore(persist_path=EVENTS_FILE)


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


class RequestInputError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
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
        raw = self.client_address[0] if self.client_address else ""
        try:
            address = ipaddress.ip_address(raw)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                return address.ipv4_mapped
            return address
        except ValueError:
            return None

    def _authorized(self, scope: str = "api") -> bool:
        if AUTH_MODE == "trusted-network":
            address = self._client_ip()
            if address is None:
                return False
            return any(address in network for network in _trusted_networks())
        token = self.headers.get("x-jarvis-token", "")
        expected = EVENT_TOKEN if scope == "events" and EVENT_TOKEN else API_TOKEN
        return bool(token and expected and hmac.compare_digest(token, expected))

    def _read_json(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestInputError(411, "Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RequestInputError(400, "invalid Content-Length") from exc
        if length <= 0:
            raise RequestInputError(400, "JSON body is required")
        if length > MAX_JSON_BODY_BYTES:
            self.close_connection = True
            raise RequestInputError(413, "JSON body is too large")
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise RequestInputError(400, "incomplete request body")
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise RequestInputError(400, "request body must be UTF-8 JSON") from exc
        except json.JSONDecodeError as exc:
            raise RequestInputError(400, "malformed JSON") from exc
        if not isinstance(payload, dict):
            raise RequestInputError(400, "JSON body must be an object")
        return payload

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

    def do_GET(self):  # noqa: N802
        self.request_id = uuid.uuid4().hex[:12]
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            if self._reject_origin():
                return
            self._send(200, {"ok": True, "version": VERSION, "uptimeSeconds": round(time.time() - START_TIME, 1)})
            return
        if path == "/api/v1/state":
            if not self._auth_or_respond():
                return
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
            try:
                argv = build_command(action, params)
            except CommandError as exc:
                self._send(400, {"ok": False, "error": str(exc), "action": action if isinstance(action, str) else None})
                return
            command_env = None
            if action in {"purifier-set", "purifier-status"}:
                command_env = {"JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS": f"{PURIFIER_WRITE_WAIT_SECONDS:g}"}
            raw_result = run_cli_json(argv, timeout=30, env=command_env)
            if raw_result.get("ok") is True and action in {"plug-on", "plug-off", "plug-toggle"}:
                STATE_COORDINATOR.apply_plug_result(raw_result.get("plug"))
                STATE_COORDINATOR.request_refresh("plugs")
            elif raw_result.get("ok") is True and action in {"purifier-set", "purifier-status"}:
                STATE_COORDINATOR.apply_purifier_result(
                    _purifier_command_data(raw_result),
                    _purifier_expectation(params) if action == "purifier-set" else None,
                )
                STATE_COORDINATOR.request_refresh("purifier")
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


def main() -> int:
    validate_config()
    STATE_COORDINATOR.start()
    if AUTH_MODE == "trusted-network":
        sys.stderr.write(f"[jarvisd] trusted-network mode; CIDRs={TRUSTED_CIDRS_RAW}\n")
    else:
        sys.stderr.write("[jarvisd] token mode enabled for app API\n")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    sys.stderr.write(f"[jarvisd] listening on {HOST}:{PORT} (version {VERSION})\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        STATE_COORDINATOR.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
