#!/usr/bin/env python3
"""jarvisd — the Operation JARVIS app backend.

A small stdlib-only HTTP daemon (ThreadingHTTPServer) that is the *only*
control plane for the iOS/watchOS app. It aggregates state, runs allowlisted
`jarvis-cli` commands, ingests events (same contract as the retired dashboard),
and manages registered services via launchctl.

Design notes
------------
- Auth: no-token by default (trusted home LAN / Tailscale tailnet) — every
  endpoint accepts a request with no `x-jarvis-token`. If a token IS sent and
  `JARVIS_API_TOKEN` is configured, it must match, so setting the token
  re-enables strict auth without any client change. The event *ingest*
  endpoint (`POST /api/jarvis/events`) is likewise lenient, which lets
  `jarvis.py` events repoint here with a one-line env change and zero code edits.
- `/state` runs subsystems in parallel threads with a hard cap; each subsystem
  reports its own `ok`/`error` so one slow source never blocks the snapshot.
- Commands go through a strict allowlist that builds argv from validated
  params — no shell, no string interpolation of untrusted input.

Run:  python jarvisd.py   (env: JARVIS_API_TOKEN, JARVISD_PORT, ...)
"""
from __future__ import annotations

import collections
import concurrent.futures
import datetime as dt
import http.client
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

VERSION = "0.1.0"
START_TIME = time.time()


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ.

    Only sets variables that are not already present (real env wins). Handles
    optional surrounding quotes and full-line comments. Never executes the
    file — safe against the repo .env's assorted values.
    """
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


# Repo layout. jarvisd lives in projects/operation-jarvis/jarvis-app/jarvisd/.
# Roots are detected by walking up from this file (so the daemon keeps working
# wherever the app folder is placed) and can be overridden via env.
JARVISD_DIR = Path(__file__).resolve().parent


def _find_ancestor(start: Path, marker: str) -> Path | None:
    """Return the nearest ancestor of `start` (inclusive) containing `marker`."""
    for directory in (start, *start.parents):
        if (directory / marker).exists():
            return directory
    return None


# operation-jarvis root = the directory containing the jarvis-cli wrapper.
if os.environ.get("JARVISD_OPERATION_ROOT"):
    OPERATION_ROOT = Path(os.environ["JARVISD_OPERATION_ROOT"]).resolve()
else:
    OPERATION_ROOT = _find_ancestor(JARVISD_DIR, "jarvis-cli") or JARVISD_DIR.parent.parent

# JARVIS home = the directory containing the repo .env (where the token lives).
if os.environ.get("JARVISD_PROJECT_ROOT"):
    PROJECT_ROOT = Path(os.environ["JARVISD_PROJECT_ROOT"]).resolve()
else:
    PROJECT_ROOT = _find_ancestor(JARVISD_DIR, ".env") or OPERATION_ROOT.parent

JARVIS_CLI = OPERATION_ROOT / "jarvis-cli"

# Load the repo .env (where JARVIS_API_TOKEN lives) before reading config.
_load_env_file(PROJECT_ROOT / ".env")

# Allow env overrides; sensible defaults otherwise.
PORT = int(os.environ.get("JARVISD_PORT", "8790"))
HOST = os.environ.get("JARVISD_HOST", "0.0.0.0")
API_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")
# Legacy dashboard write token — accepted on ingest only, for the zero-code
# repoint transition.
DASHBOARD_WRITE_TOKEN = os.environ.get("JARVIS_DASHBOARD_WRITE_TOKEN", "")
SERVICES_FILE = Path(os.environ.get("JARVISD_SERVICES_FILE", str(JARVISD_DIR / "services.json")))
EVENTS_FILE = Path(os.environ.get("JARVISD_EVENTS_FILE", str(JARVISD_DIR / "logs" / "events.jsonl")))
TAILSCALE_IP_FALLBACK = os.environ.get("JARVISD_TAILSCALE_IP", "")
TAILSCALE_SOCKET = Path(os.environ.get("TAILSCALE_SOCKET", str(Path.home() / ".local/share/tailscale/tailscaled.socket")))

# Weather (Open-Meteo, Pickering ON), cached for 10 minutes.
WEATHER_LAT = float(os.environ.get("JARVISD_WEATHER_LAT", "43.8465"))
WEATHER_LON = float(os.environ.get("JARVISD_WEATHER_LON", "-79.0762"))
WEATHER_TZ = "America/Toronto"
WEATHER_CACHE_SECONDS = 600

# Subsystem budget for /state (seconds).
STATE_TIMEOUT = float(os.environ.get("JARVISD_STATE_TIMEOUT", "10"))

# Pi session heartbeat locations.
PI_LOCAL_SESSIONS = Path(os.environ.get("PI_LOCAL_SESSIONS", str(PROJECT_ROOT / ".pi/runtime/local-pi-sessions")))
PI_RPC_SESSIONS = Path(os.environ.get("PI_RPC_SESSIONS", str(PROJECT_ROOT / ".pi/runtime/pi-rpc-sessions.json")))

# --------------------------------------------------------------------------- #
# Command allowlist
# --------------------------------------------------------------------------- #

PLUG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")

PURIFIER_SETTINGS = ("power", "mode", "speed", "display", "child-lock",
                     "light-detection", "auto-preference", "timer")
PURIFIER_MODES = ("auto", "manual", "sleep", "pet")
PURIFIER_SPEEDS = (1, 2, 3, 4)
PURIFIER_POWER_STATES = ("on", "off", "toggle")
PURIFIER_AUTO_PREFERENCES = ("default", "efficient", "quiet")


class CommandError(ValueError):
    """Raised when a command action or its params fail validation."""


def _require_str(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"missing required string param {key!r}")
    return value.strip()


def _plug_name(params: dict) -> str:
    name = _require_str(params, "plug")
    if not PLUG_NAME_RE.match(name):
        raise CommandError(f"invalid plug name {name!r}")
    return name


def _opt_int(params: dict, key: str, lo: int, hi: int):
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"param {key!r} must be an integer")
    if not (lo <= value <= hi):
        raise CommandError(f"param {key!r} must be between {lo} and {hi}")
    return value


def _opt_enum(params: dict, key: str, choices):
    value = params.get(key)
    if value is None:
        return None
    if value not in choices:
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
            raise CommandError(f"invalid state {value!r} for {setting}")
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


# action -> (builder(params) -> argv, description)
COMMANDS: dict[str, tuple] = {
    "status": (lambda p: ["status", "--no-cast"], "Overall Operation JARVIS status (no Cast)."),
    "plug-list": (lambda p: ["plug-list"], "List configured smart plugs."),
    "plug-status": (lambda p: ["plug-status", _plug_name(p)], "Show one plug's power state."),
    "plug-on": (lambda p: ["plug-on", _plug_name(p)], "Turn a plug on."),
    "plug-off": (lambda p: ["plug-off", _plug_name(p)], "Turn a plug off."),
    "plug-toggle": (lambda p: ["plug-toggle", _plug_name(p)], "Toggle a plug."),
    "purifier-status": (lambda p: ["purifier-status"], "Show air purifier status."),
    "purifier-set": (_purifier_set_args, "Set one air purifier setting."),
}


def build_command(action: str, params: dict) -> list[str]:
    if action not in COMMANDS:
        raise CommandError(f"action {action!r} is not allowlisted")
    builder, _ = COMMANDS[action]
    argv = builder(params or {})
    return [str(JARVIS_CLI), "--json", *argv]


# --------------------------------------------------------------------------- #
# Subprocess helpers
# --------------------------------------------------------------------------- #

def run_cli_json(argv: list[str], timeout: float = 20.0) -> dict:
    """Run a jarvis-cli argv and parse its JSON stdout."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(OPERATION_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout:.0f}s", "argv": argv}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "argv": argv}

    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0:
        # jarvis.py prints JSON even on some failures; try to parse, else report.
        parsed = _try_json(stdout)
        if parsed is not None:
            parsed.setdefault("ok", False)
            parsed["stderr"] = (proc.stderr or "").strip()[-2000:]
            return parsed
        return {"ok": False, "error": (proc.stderr or stdout or f"exit {proc.returncode}").strip()[-2000:], "argv": argv}

    parsed = _try_json(stdout)
    if parsed is None:
        return {"ok": False, "error": "non-JSON output", "stdout": stdout[-2000:], "argv": argv}
    return parsed


def _try_json(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some commands print a JSON object after a banner line; grab the first '{'.
        idx = text.find("{")
        if idx >= 0:
            try:
                return json.loads(text[idx:])
            except json.JSONDecodeError:
                return None
        return None


# --------------------------------------------------------------------------- #
# State subsystems
# --------------------------------------------------------------------------- #

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
    # 1) localapi over the userspace socket (works when the daemon allows it).
    if TAILSCALE_SOCKET.exists():
        try:
            req = urllib.request.Request("http://localhost/localapi/v0/self")
            # Route the request through the unix socket.
            import http.client
            conn = _UnixSocketHTTPConnection(str(TAILSCALE_SOCKET))
            conn.request("GET", "/localapi/v0/self")
            resp = conn.getresponse()
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                ips = (data.get("Self") or {}).get("TailscaleIPs") or []
                if ips:
                    return ips[0]
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    # 2) tailscale CLI (honours TSD_SOCKET in some builds).
    try:
        env = dict(os.environ, TSD_SOCKET=str(TAILSCALE_SOCKET))
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5, env=env)
        ip = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else ""
        if ip.startswith("100."):
            return ip
    except Exception:  # noqa: BLE001
        pass
    # 3) static fallback from env.
    return TAILSCALE_IP_FALLBACK or None


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """Minimal HTTP connection over a unix socket (for tailscale localapi)."""

    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):  # noqa: D102
        import socket as _socket
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


_weather_cache: dict = {"at": 0.0, "data": None}
_weather_lock = threading.Lock()


def _weather() -> dict:
    with _weather_lock:
        now = time.time()
        if _weather_cache["data"] is not None and (now - _weather_cache["at"]) < WEATHER_CACHE_SECONDS:
            return _weather_cache["data"]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
        f"&timezone={urllib.parse.quote(WEATHER_TZ)}"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            payload = json.loads(resp.read().decode())
        cur = payload.get("current", {})
        data = {
            "ok": True,
            "location": "Pickering, ON",
            "temperatureC": cur.get("temperature_2m"),
            "feelsLikeC": cur.get("apparent_temperature"),
            "humidityPercent": cur.get("relative_humidity_2m"),
            "windKph": cur.get("wind_speed_10m"),
            "weatherCode": cur.get("weather_code"),
            "at": cur.get("time"),
        }
        with _weather_lock:
            _weather_cache["at"] = time.time()
            _weather_cache["data"] = data
        return data
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _pi_sessions() -> dict:
    active_local = 0
    local_total = 0
    if PI_LOCAL_SESSIONS.is_dir():
        for f in PI_LOCAL_SESSIONS.glob("*.json"):
            local_total += 1
            try:
                data = json.loads(f.read_text())
                if data.get("active"):
                    active_local += 1
            except Exception:  # noqa: BLE001
                continue
    rpc_active = 0
    if PI_RPC_SESSIONS.is_file():
        try:
            data = json.loads(PI_RPC_SESSIONS.read_text())
            sessions = data.get("sessions", data if isinstance(data, list) else [])
            for s in sessions:
                if isinstance(s, dict) and s.get("active"):
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
    listing = run_cli_json([str(JARVIS_CLI), "--json", "plug-list"], timeout=12)
    plugs_map = (listing.get("plugs") or {}) if isinstance(listing, dict) else {}
    if not plugs_map:
        return {"ok": False, "error": "plug-list failed", "detail": listing}
    names = list(plugs_map.keys())
    results: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        futures = {name: pool.submit(run_cli_json, [str(JARVIS_CLI), "--json", "plug-status", name], 10) for name in names}
        for name, fut in futures.items():
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": str(exc)}
            plug = res.get("plug") if isinstance(res, dict) else None
            results[name] = {
                "ok": bool(res.get("ok")) if isinstance(res, dict) else False,
                "isOn": bool(plug.get("is_on")) if isinstance(plug, dict) else None,
                "host": plug.get("host") if isinstance(plug, dict) else plugs_map.get(name),
                "rssi": plug.get("rssi") if isinstance(plug, dict) else None,
                "alias": plug.get("alias") if isinstance(plug, dict) else None,
            }
    on_count = sum(1 for r in results.values() if r.get("isOn"))
    return {"ok": True, "count": len(results), "onCount": on_count, "plugs": results}


def _purifier() -> dict:
    res = run_cli_json([str(JARVIS_CLI), "--json", "purifier-status"], timeout=12)
    data = res.get("airPurifier", {}).get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        return {"ok": False, "error": "purifier-status failed", "detail": res}
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


def _services_state(services: dict) -> dict:
    out = {}
    uid = os.getuid()
    for name, spec in services.items():
        label = spec.get("label")
        if not label:
            out[name] = {"ok": False, "error": "no label", "running": None}
            continue
        try:
            proc = subprocess.run(["launchctl", "list", label], capture_output=True, text=True, timeout=5)
            running = False
            pid = None
            if proc.returncode == 0 and proc.stdout.strip():
                # Output is plist format, e.g. `"PID" = 1577;` when running.
                m = re.search(r'"PID"\s*=\s*(\d+);', proc.stdout)
                if m:
                    pid = int(m.group(1))
                    running = True
            out[name] = {
                "ok": True,
                "label": label,
                "running": running,
                "pid": pid,
                "description": spec.get("description", ""),
            }
        except Exception as exc:  # noqa: BLE001
            out[name] = {"ok": False, "error": str(exc), "running": None}
    return out


def _load_services() -> dict:
    try:
        data = json.loads(SERVICES_FILE.read_text())
        return data.get("services", {})
    except Exception:  # noqa: BLE001
        return {}


def collect_state() -> dict:
    services = _load_services()
    snapshot = {
        "ok": True,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "version": VERSION,
        "uptimeSeconds": round(time.time() - START_TIME, 1),
        "subsystems": {},
    }

    jobs = {
        "plugs": _plugs,
        "purifier": _purifier,
        "pi": _pi_sessions,
        "weather": _weather,
        "services": lambda: _services_state(services),
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs) + 2) as pool:
        futs = {name: pool.submit(fn) for name, fn in jobs.items()}
        futs["network"] = pool.submit(_collect_network)
        for name, fut in futs.items():
            try:
                result = fut.result(timeout=STATE_TIMEOUT)
            except concurrent.futures.TimeoutError:
                result = {"ok": False, "error": f"timed out after {STATE_TIMEOUT:.0f}s"}
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            snapshot["subsystems"][name] = result

    # Convenience top-level rollup for the app.
    subs = snapshot["subsystems"]
    plugs = subs.get("plugs", {})
    purifier = subs.get("purifier", {})
    pi = subs.get("pi", {})
    snapshot["summary"] = {
        "plugsOn": plugs.get("onCount"),
        "plugsTotal": plugs.get("count"),
        "purifierOn": purifier.get("isOn") if purifier.get("ok") else None,
        "pm25": purifier.get("pm25") if purifier.get("ok") else None,
        "piActive": pi.get("active") if pi.get("ok") else None,
    }
    return snapshot


def _collect_network() -> dict:
    return {
        "ok": True,
        "macLanIp": _lan_ip(),
        "tailscaleIp": _tailscale_ip(),
    }


# --------------------------------------------------------------------------- #
# Event ring buffer (in-memory + optional jsonl persistence)
# --------------------------------------------------------------------------- #

class EventStore:
    def __init__(self, max_events: int = 500, persist_path: Path | None = None):
        self._events: collections.deque = collections.deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._seq = 0
        self._persist_path = persist_path
        if persist_path:
            try:
                persist_path.parent.mkdir(parents=True, exist_ok=True)
                if persist_path.exists():
                    self._load(persist_path)
            except Exception:  # noqa: BLE001
                self._persist_path = None

    def _load(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        self._events.append(ev)
                        self._seq = max(self._seq, int(ev.get("seq", 0)))
                    except json.JSONDecodeError:
                        continue
        except Exception:  # noqa: BLE001
            pass

    def add(self, payload: dict) -> dict:
        with self._lock:
            self._seq += 1
            ev = dict(payload)
            ev["seq"] = self._seq
            ev.setdefault("receivedAt", dt.datetime.now(dt.timezone.utc).isoformat())
            self._events.append(ev)
            if self._persist_path:
                try:
                    with self._persist_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(ev) + "\n")
                except Exception:  # noqa: BLE001
                    pass
            return ev

    def list(self, since: int | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            events = list(self._events)
        if since:
            events = [e for e in events if int(e.get("seq", 0)) > int(since)]
        limit = max(1, min(int(limit), 500))
        return events[-limit:]


EVENTS = EventStore(persist_path=EVENTS_FILE)


# --------------------------------------------------------------------------- #
# Service control
# --------------------------------------------------------------------------- #

def _service_action(name: str, action: str) -> dict:
    services = _load_services()
    spec = services.get(name)
    if not spec:
        return {"ok": False, "error": f"unknown service {name!r}", "known": list(services.keys())}
    label = spec.get("label")
    if not label:
        return {"ok": False, "error": "service has no launchctl label"}
    uid = os.getuid()
    target = f"gui/{uid}/{label}"

    if action == "status":
        return _services_state({name: spec})[name] | {"ok": True}
    if action == "start":
        cmd = ["launchctl", "kickstart", "-k", target]
    elif action == "restart":
        cmd = ["launchctl", "kickstart", "-k", target]
    elif action == "stop":
        cmd = ["launchctl", "bootout", target]
    else:
        return {"ok": False, "error": f"unknown service action {action!r}"}

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        ok = proc.returncode == 0
        return {
            "ok": ok,
            "service": name,
            "action": action,
            "label": label,
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "").strip()[-1000:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "service": name, "action": action, "error": str(exc)}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = f"jarvisd/{VERSION}"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------- #
    def log_message(self, fmt, *args):  # noqa: A002
        ts = time.strftime("%H:%M:%S")
        ip = self.client_address[0] if self.client_address else "?"
        sys.stderr.write(f"[jarvisd] {ts} {ip} " + (fmt % args) + "\n")

    def _send(self, code: int, body: dict, extra_headers: dict | None = None) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "x-jarvis-token, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self, strict: bool) -> bool:
        # No-token mode (trusted home LAN / Tailscale tailnet): absence of a
        # token is always accepted on every endpoint. If a token IS sent and a
        # token is configured, it must match — so setting JARVIS_API_TOKEN
        # re-enables strict auth later without any client change.
        token = self.headers.get("x-jarvis-token", "")
        if not token:
            return True
        configured = {t for t in (API_TOKEN, DASHBOARD_WRITE_TOKEN) if t}
        if not configured:
            return True  # nothing configured; accept the (unverifiable) token
        return token in configured

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    # -- verbs -------------------------------------------------------------- #
    def do_OPTIONS(self):  # noqa: N802
        self._send(204, {})

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self._send(200, {"ok": True, "version": VERSION, "uptimeSeconds": round(time.time() - START_TIME, 1)})
            return

        if path == "/api/v1/state":
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, collect_state())
            return

        if path == "/api/v1/events":
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            since = query.get("since", [None])[0]
            limit = query.get("limit", ["100"])[0]
            try:
                since_i = int(since) if since else None
                limit_i = int(limit)
            except ValueError:
                self._send(400, {"ok": False, "error": "since/limit must be integers"})
                return
            events = EVENTS.list(since=since_i, limit=limit_i)
            self._send(200, {"ok": True, "count": len(events), "events": events})
            return

        if path == "/api/v1/services":
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True, "services": _services_state(_load_services())})
            return

        if path.startswith("/api/v1/services/"):
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            name = path.rsplit("/", 1)[-1]
            self._send(200, _service_action(name, "status"))
            return

        self._send(404, {"ok": False, "error": "not found", "path": path})

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/jarvis/events":
            # Ingest — lenient auth (see _authorized).
            if not self._authorized(strict=False):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            payload = self._read_json() or {}
            ev = EVENTS.add(payload)
            self._send(200, {"ok": True, "seq": ev["seq"]})
            return

        if path == "/api/v1/command":
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            payload = self._read_json() or {}
            action = payload.get("action")
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                self._send(400, {"ok": False, "error": "params must be an object"})
                return
            try:
                argv = build_command(action, params)
            except CommandError as exc:
                self._send(400, {"ok": False, "error": str(exc), "action": action})
                return
            result = run_cli_json(argv, timeout=30)
            result["action"] = action
            self._send(200, result)
            return

        if path.startswith("/api/v1/services/"):
            if not self._authorized(strict=True):
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            name = path.rsplit("/", 1)[-1]
            payload = self._read_json() or {}
            action = payload.get("action", "status")
            self._send(200, _service_action(name, action))
            return

        self._send(404, {"ok": False, "error": "not found", "path": path})


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    if not API_TOKEN:
        sys.stderr.write("[jarvisd] no-token mode: /api/v1/* accepts unauthenticated clients (trusted LAN/Tailscale).\n")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    sys.stderr.write(f"[jarvisd] listening on {HOST}:{PORT} (version {VERSION})\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
