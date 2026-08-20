#!/usr/bin/env python3
"""Unified Operation JARVIS adapter.

This is the single local adapter for the focused Operation JARVIS scope:
Discord + Google Cast + smart plugs + air purifier.

It controls Cast speech/media output, local Kasa smart plugs, and the
VeSync/Levoit air purifier. Native Apple-client state and commands use
``jarvisd`` as their sole control plane.
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPERATION_ROOT = Path(__file__).resolve().parent


def load_local_env_files() -> None:
    """Load simple KEY=VALUE pairs from repo/project .env files without overriding the process env."""
    for env_path in (PROJECT_ROOT / ".env", OPERATION_ROOT / ".env"):
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


load_local_env_files()

CAST_SCRIPTS_DIR = OPERATION_ROOT / "scripts"
TV_SCRIPT = CAST_SCRIPTS_DIR / "tv.py"
CAST_AUDIO_DIR = OPERATION_ROOT / "data" / "cast-audio"
SMART_PLUG_DIR = OPERATION_ROOT / "smart-plug"
SMART_PLUG_CONFIG = SMART_PLUG_DIR / "plugs.json"
AIR_PURIFIER_DIR = OPERATION_ROOT / "air-purifier"
AIR_PURIFIER_CLI = AIR_PURIFIER_DIR / "purifier-cli"

DEFAULT_SPEAK_DEVICE = "speakers"
DEFAULT_MEDIA_DEVICE = "tv"
DEFAULT_CAST_TIMEOUT = 45.0
DEFAULT_SMART_PLUG_TIMEOUT = 30.0
DEFAULT_AIR_PURIFIER_TIMEOUT = 150.0
DEFAULT_MAX_SPOKEN_CHARS = 500
DEFAULT_SPEAK_RATE = 185
DEFAULT_SERVE_BIND = "0.0.0.0"
DEFAULT_SERVE_PORT = 8766
DEFAULT_POST_CAST_SERVE_SECONDS = 60.0
DEFAULT_EVENT_TIMEOUT = 2.0
DEVICE_CHOICES = ("tv", "speakers")
TORCH_CHOICES = ("on", "off", "toggle")
MUTE_STATES = ("on", "off", "toggle")
SPOTIFY_QUEUE_TYPES = ("track", "episode")
SPOTIFY_REPEAT_STATES = ("off", "context", "track", "toggle")
PURIFIER_SETTINGS = ("power", "mode", "speed", "display", "child-lock", "light-detection", "auto-preference", "timer")
PURIFIER_POWER_STATES = ("on", "off", "toggle")
PURIFIER_MODES = ("auto", "manual", "sleep", "pet")
PURIFIER_SPEEDS = (1, 2, 3, 4)
PURIFIER_ON_OFF_STATES = ("on", "off")
PURIFIER_AUTO_PREFERENCES = ("default", "efficient", "quiet")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Import only target-resolution helpers from the bundled Cast scripts.
sys.path.insert(0, str(CAST_SCRIPTS_DIR))
try:
    from connect_chromecast import resolve_target  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - optional helper for LAN IP detection
    resolve_target = None  # type: ignore


class JarvisError(RuntimeError):
    """Expected Operation JARVIS adapter failure."""


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def events_enabled() -> bool:
    return os.environ.get("JARVIS_EMIT_EVENTS", "1").lower() not in {"0", "false", "no", "off"}


def _event_targets() -> list[tuple[str, Optional[str]]]:
    """Return the sole Operation JARVIS event-ingest target."""
    jarvisd = os.environ.get("JARVISD_URL", "http://127.0.0.1:8790").rstrip("/")
    if not jarvisd:
        return []
    # In trusted-network mode this remains tokenless. In token mode the
    # dedicated ingest token is preferred and is never used for app commands.
    event_token = os.environ.get("JARVISD_EVENT_TOKEN") or os.environ.get("JARVIS_API_TOKEN")
    return [(jarvisd, event_token)]


def emit_event(
    event_type: str,
    *,
    action: Optional[str],
    ok: Optional[bool] = None,
    summary: str = "",
    error: Optional[str] = None,
    artifacts: Optional[list[dict[str, Any]]] = None,
    data: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort lifecycle event bridge to jarvisd; never fails the CLI action."""
    if not events_enabled():
        return
    targets = _event_targets()
    if not targets:
        return

    payload = {
        "source": "operation-jarvis",
        "eventType": event_type,
        "action": action,
        "ok": ok,
        "summary": summary,
        "error": error,
        "artifacts": artifacts or [],
        "data": data or None,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    body = json.dumps(payload).encode("utf-8")

    for base_url, token in targets:
        headers = {"content-type": "application/json"}
        if token:
            headers["x-jarvis-token"] = token
        try:
            request = Request(f"{base_url}/api/jarvis/events", data=body, headers=headers, method="POST")
            with urlopen(request, timeout=DEFAULT_EVENT_TIMEOUT):
                pass
        except Exception:
            continue


def choose_python() -> str:
    """Prefer the Operation JARVIS venv, then the repo venv, then current Python."""
    candidates = [
        OPERATION_ROOT / ".venv" / "bin" / "python",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable or "python3"


def run_subprocess(cmd: list[str], *, timeout: float) -> dict[str, Any]:
    result = subprocess.run(
        cmd,
        cwd=str(OPERATION_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    stdout = strip_ansi(result.stdout).strip()
    stderr = strip_ansi(result.stderr).strip()
    if result.returncode != 0:
        raise JarvisError(stderr or stdout or f"command exited with code {result.returncode}: {' '.join(cmd)}")
    return {
        "ok": True,
        "command": cmd,
        "stdout": stdout,
        "stderr": stderr,
    }


def run_tv_command(args: list[str], *, timeout: float) -> dict[str, Any]:
    if not TV_SCRIPT.exists():
        raise JarvisError(f"Cast script not found: {TV_SCRIPT}")
    return run_subprocess([choose_python(), str(TV_SCRIPT), *args], timeout=timeout)


def choose_smart_plug_python() -> str:
    """Use the smart-plug Python 3.11+ venv, separate from the main Python 3.9 venv."""
    candidates = [
        SMART_PLUG_DIR / ".venv" / "bin" / "python",
        Path("/opt/homebrew/bin/python3.13"),
        Path("/opt/homebrew/bin/python3.12"),
        Path("/opt/homebrew/bin/python3.11"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python3"


def smart_plug_config_path(args: argparse.Namespace) -> Path:
    raw = getattr(args, "plug_config", None)
    if not raw:
        return SMART_PLUG_CONFIG
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else (OPERATION_ROOT / path)


def run_air_purifier_command(args: list[str], *, timeout: float) -> dict[str, Any]:
    if not AIR_PURIFIER_CLI.exists():
        raise JarvisError(f"Air-purifier CLI not found: {AIR_PURIFIER_CLI}")

    command = [str(AIR_PURIFIER_CLI), "--json", *args]
    result = subprocess.run(
        command,
        cwd=str(AIR_PURIFIER_DIR),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    stdout = strip_ansi(result.stdout).strip()
    stderr = strip_ansi(result.stderr).strip()
    data: Any
    try:
        data = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        data = {"stdout": stdout}
    if result.returncode != 0:
        message = ""
        if isinstance(data, dict):
            message = str(data.get("error") or "")
        raise JarvisError(message or stderr or stdout or f"purifier-cli exited with code {result.returncode}")
    return {
        "ok": True,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "data": data if isinstance(data, dict) else {"value": data},
    }


def run_smart_plug_command(args: list[str], *, timeout: float, config_path: Optional[Path] = None, discovery_target: Optional[str] = None) -> dict[str, Any]:
    if not SMART_PLUG_DIR.exists():
        raise JarvisError(f"Smart-plug subsystem not found: {SMART_PLUG_DIR}")
    command = [
        choose_smart_plug_python(),
        "-m",
        "smart_plug.cli",
        "--json",
        "--config",
        str(config_path or SMART_PLUG_CONFIG),
        *args,
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("KASA_TIMEOUT", str(max(1, int(timeout))))
    if discovery_target:
        env["KASA_DISCOVERY_TARGET"] = discovery_target

    result = subprocess.run(
        command,
        cwd=str(SMART_PLUG_DIR),
        text=True,
        capture_output=True,
        timeout=timeout + 10.0,
        env=env,
    )
    stdout = strip_ansi(result.stdout).strip()
    stderr = strip_ansi(result.stderr).strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = stdout
    if result.returncode != 0:
        message = stderr or stdout or f"smart-plug command exited with code {result.returncode}: {' '.join(command)}"
        if "Device response did not match our challenge" in message:
            message += " Credentials may be correct; newer Kasa/Tapo firmware can reject local third-party KLAP auth unless Third-Party Compatibility is enabled in the Kasa/Tapo app."
        raise JarvisError(message)
    return {
        "ok": True,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "data": payload,
    }


def smart_plug_status_summary(status: dict[str, Any]) -> str:
    name = str(status.get("name") or status.get("alias") or status.get("host") or "smart plug")
    state_value = status.get("is_on")
    state = "on" if state_value is True else "off" if state_value is False else "unknown"
    host = status.get("host")
    alias = status.get("alias")
    label = f"{name} is {state}"
    details = []
    if host:
        details.append(f"host={host}")
    if alias and alias != name:
        details.append(f"alias={alias!r}")
    return f"{label}." + (f" {'; '.join(details)}." if details else "")


def smart_plug_many_summary(plugs: Any, *, verb: str) -> str:
    if not isinstance(plugs, dict) or not plugs:
        return f"No smart plugs {verb}."
    bits: list[str] = []
    for name, value in sorted(plugs.items()):
        if isinstance(value, dict):
            host = value.get("host")
            is_on = value.get("is_on")
            state = "on" if is_on is True else "off" if is_on is False else None
            bits.append(f"{name}={host or '?'}" + (f" ({state})" if state else ""))
        else:
            bits.append(f"{name}={value}")
    return f"Smart plugs {verb}: " + ", ".join(bits) + "."


def get_target_host(device: str) -> Optional[str]:
    if resolve_target is None:
        return None
    try:
        return resolve_target(device=device).host
    except Exception:
        return None


def get_lan_ip(prefer_remote_host: Optional[str] = None) -> str:
    remote = prefer_remote_host or "8.8.8.8"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((remote, 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        return


def start_file_server(directory: Path, bind_host: str, port: int) -> http.server.ThreadingHTTPServer:
    directory.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(QuietHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer((bind_host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="operation-jarvis-cast-http", daemon=True)
    thread.start()
    return server


def speech_text_from_output(text: str, max_chars: int) -> str:
    text = strip_ansi(text)
    text = re.sub(r"```.*?```", " I included a code block in Discord. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"https?://\S+", " link ", text)
    cleaned_lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        line = re.sub(r"^\s*\d+[.)]\s+", "", line)
        line = line.strip()
        if line:
            cleaned_lines.append(line)
    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "I do not have anything to say."
    if max_chars > 0 and len(text) > max_chars:
        truncated = text[:max_chars].rsplit(".", 1)[0].strip()
        if len(truncated) < max_chars * 0.5:
            truncated = text[:max_chars].rsplit(" ", 1)[0].strip()
        text = (truncated or text[:max_chars].strip()) + ". The full answer is in Discord."
    return text


def generate_tts_audio(
    responses_dir: Path,
    run_id: str,
    text: str,
    *,
    voice: Optional[str],
    rate: Optional[int],
) -> Tuple[Path, str]:
    if shutil.which("say") is None:
        raise JarvisError("macOS 'say' command was not found; cannot generate local TTS audio")

    responses_dir.mkdir(parents=True, exist_ok=True)
    text_path = responses_dir / f"{run_id}.speech.txt"
    aiff_path = responses_dir / f"{run_id}.aiff"
    m4a_path = responses_dir / f"{run_id}.m4a"
    text_path.write_text(text, encoding="utf-8")

    say_cmd = ["say", "-f", str(text_path), "-o", str(aiff_path)]
    if voice:
        say_cmd.extend(["-v", voice])
    if rate:
        say_cmd.extend(["-r", str(rate)])
    subprocess.run(say_cmd, check=True)

    if shutil.which("afconvert"):
        subprocess.run(["afconvert", str(aiff_path), str(m4a_path), "-f", "m4af", "-d", "aac"], check=True)
        return m4a_path, "audio/mp4"

    if shutil.which("ffmpeg"):
        mp3_path = responses_dir / f"{run_id}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff_path), "-codec:a", "libmp3lame", str(mp3_path)],
            check=True,
        )
        return mp3_path, "audio/mpeg"

    raise JarvisError("Neither afconvert nor ffmpeg was found; cannot convert TTS audio for Cast playback")


def cast_audio(
    audio_path: Path,
    content_type: str,
    *,
    device: str,
    serve_host_for_url: str,
    serve_port: int,
    cast_timeout: float,
) -> dict[str, Any]:
    url = f"http://{serve_host_for_url}:{serve_port}/{audio_path.name}"
    result = run_tv_command(["--device", device, "play-url", url, "--type", content_type], timeout=cast_timeout)
    result["url"] = url
    return result


def add_speak_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", default=DEFAULT_SPEAK_DEVICE, choices=DEVICE_CHOICES, help="Cast speaker target")
    parser.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT, help="Cast timeout seconds")
    parser.add_argument("--voice", default=None, help="macOS say voice")
    parser.add_argument("--rate", type=int, default=None, help="macOS say speech rate")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_SPOKEN_CHARS, help="Max spoken characters; 0 disables truncation")
    parser.add_argument("--serve-port", type=int, default=None, help="Local HTTP server port for Cast audio")
    parser.add_argument("--serve-host", default=None, help="LAN host/IP Chromecast should use")
    parser.add_argument("--post-cast-serve-seconds", type=float, default=None, help="Keep server alive after Cast command")


def add_spotify_control_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spotify-client-id", default=None, help="Spotify app client ID (falls back to SPOTIFY_CLIENT_ID)")
    parser.add_argument("--spotify-client-secret", default=None, help="Spotify app client secret (falls back to SPOTIFY_CLIENT_SECRET)")
    parser.add_argument("--spotify-refresh-token", default=None, help="Spotify OAuth refresh token (falls back to SPOTIFY_REFRESH_TOKEN)")
    parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device-name override")
    parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device-id override")


def add_spotify_options(parser: argparse.ArgumentParser) -> None:
    add_spotify_control_options(parser)
    parser.add_argument("--spotify-type", choices=["track", "album", "playlist", "artist", "any"], default="track", help="Spotify search type for text queries")
    parser.add_argument("--market", default=None, help="Spotify market code, e.g. CA or US")


def cloud_tts_url(text: str, *, language: str = "en", max_len: int = 180) -> str:
    trimmed = text.strip()
    if len(trimmed) > max_len:
        clipped = trimmed[:max_len].rsplit(" ", 1)[0].strip()
        trimmed = clipped or trimmed[:max_len]
    query = urlencode({"ie": "UTF-8", "client": "tw-ob", "tl": language, "q": trimmed})
    return f"https://translate.google.com/translate_tts?{query}"


def cast_speak(text: str, args: argparse.Namespace) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise JarvisError("speech text cannot be empty")
    if args.max_chars is not None and args.max_chars < 0:
        raise JarvisError("max-chars must be 0 or greater")
    post_seconds = args.post_cast_serve_seconds if args.post_cast_serve_seconds is not None else DEFAULT_POST_CAST_SERVE_SECONDS
    if post_seconds < 0:
        raise JarvisError("post-cast-serve-seconds must be 0 or greater")

    spoken_text = speech_text_from_output(text, args.max_chars)

    # Default path: cloud-hosted TTS URL (no local callback HTTP needed).
    # This avoids LAN routing issues where Cast devices cannot reach the
    # workstation's local IP.
    cast_result: dict[str, Any] = {}
    transport = "cloud"
    tts_url = cloud_tts_url(spoken_text)
    try:
        cast_result = run_tv_command(["--device", args.device, "play-url", tts_url, "--type", "audio/mpeg"], timeout=args.cast_timeout)
        if post_seconds > 0:
            time.sleep(min(post_seconds, 3.0))
        return {
            "ok": True,
            "action": "speak",
            "device": args.device,
            "text": text,
            "spokenText": spoken_text,
            "audioPath": None,
            "contentType": "audio/mpeg",
            "serveUrl": tts_url,
            "stdout": cast_result.get("stdout", ""),
            "stderr": cast_result.get("stderr", ""),
            "command": cast_result.get("command"),
            "transport": transport,
            "summary": f"Spoken response cast to {args.device}.",
        }
    except Exception:
        # Fallback path: local generated audio served over local HTTP.
        transport = "local"

    run_id = f"jarvis-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    audio_path, content_type = generate_tts_audio(
        CAST_AUDIO_DIR,
        run_id,
        spoken_text,
        voice=args.voice,
        rate=args.rate or DEFAULT_SPEAK_RATE,
    )

    server = start_file_server(CAST_AUDIO_DIR, DEFAULT_SERVE_BIND, args.serve_port or DEFAULT_SERVE_PORT)
    actual_port = int(server.server_address[1])
    serve_host = args.serve_host or get_lan_ip(get_target_host(args.device))
    try:
        cast_result = cast_audio(
            audio_path,
            content_type,
            device=args.device,
            serve_host_for_url=serve_host,
            serve_port=actual_port,
            cast_timeout=args.cast_timeout,
        )
        if post_seconds > 0:
            time.sleep(post_seconds)
    finally:
        server.shutdown()
        server.server_close()

    return {
        "ok": True,
        "action": "speak",
        "device": args.device,
        "text": text,
        "spokenText": spoken_text,
        "audioPath": str(audio_path),
        "contentType": content_type,
        "serveUrl": cast_result.get("url"),
        "stdout": cast_result.get("stdout", ""),
        "stderr": cast_result.get("stderr", ""),
        "command": cast_result.get("command"),
        "transport": transport,
        "summary": f"Spoken response cast to {args.device}.",
    }


def handle_help(_args: argparse.Namespace) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "help",
        "summary": "Operation JARVIS help: load the optional jarvis tool group first, then call the jarvis tool directly for Cast/Spotify, smart-plug, or air-purifier workflows.",
        "guide": {
            "tool": "jarvis",
            "availability": "optional provider-visible tool group; load with load_tools({groups:[\"jarvis\"]})",
            "scope": "Discord interface/log + Google Cast speech/media + Spotify Connect playback/control + local Kasa smart-plug control + VeSync/Levoit air purifier control",
            "defaults": {
                "speechDevice": DEFAULT_SPEAK_DEVICE,
                "mediaDevice": DEFAULT_MEDIA_DEVICE,
            },
            "devices": list(DEVICE_CHOICES),
            "castTargets": {
                "tv": {"name": "configured TV Cast target", "host": "configured locally", "useFor": ["TV media", "YouTube", "Spotify on TV"]},
                "speakers": {"name": "configured speaker/group Cast target", "host": "configured locally", "useFor": ["speech", "speaker/group media", "Spotify on speakers"]},
            },
            "spotifyConnectGuide": {
                "deviceAliases": {"tv": "configured TV Cast alias", "speakers": "configured speaker/group Cast alias"},
                "knownDeviceNames": [],
                "selectionRules": [
                    "Use device='tv' or device='speakers' for configured Cast aliases when possible.",
                    "Use spotifyDeviceName for explicit Spotify Connect targets discovered with cast-spotify-devices or documented in private local config.",
                    "Prefer spotifyDeviceName over spotifyDeviceId because Spotify device IDs can change.",
                    "If a Google Cast Spotify target is missing, cast-spotify can wake it automatically when SPOTIFY_SP_DC/SPOTIFY_SP_KEY are configured; otherwise ask for cast-spotify-devices and retry after Spotify is opened once.",
                ],
            },
            "smartPlugTargets": {
                "source": "smart-plug/plugs.json or --plug-config",
                "note": "Run plug-list to see locally configured plug aliases.",
            },
            "airPurifierTarget": {
                "source": "air-purifier/.env",
                "note": "Default purifier is configured locally as JARVIS_AIR_PURIFIER_NAME. Use purifier-status before changing settings. VeSync writes can lag; accepted-but-stale writes return verification_pending instead of a hard failure.",
                "supportedModes": list(PURIFIER_MODES),
                "supportedFanSpeeds": list(PURIFIER_SPEEDS),
            },
            "safeChecks": [
                {"action": "help"},
                {"action": "status", "noCast": True},
                {"action": "cast-status", "device": DEFAULT_SPEAK_DEVICE},
                {"action": "purifier-status"},
            ],
            "castActions": {
                "speak": {"required": ["text"], "defaultDevice": DEFAULT_SPEAK_DEVICE, "example": {"action": "speak", "text": "JARVIS online.", "device": DEFAULT_SPEAK_DEVICE}},
                "cast-status": {"required": [], "defaultDevice": DEFAULT_MEDIA_DEVICE, "example": {"action": "cast-status", "device": DEFAULT_MEDIA_DEVICE}},
                "cast-volume": {"required": ["level"], "defaultDevice": DEFAULT_SPEAK_DEVICE, "example": {"action": "cast-volume", "level": 25, "device": DEFAULT_SPEAK_DEVICE}},
                "cast-mute": {"required": [], "defaultState": "on", "example": {"action": "cast-mute", "state": "toggle", "device": DEFAULT_SPEAK_DEVICE}},
                "cast-stop": {"required": [], "defaultDevice": DEFAULT_MEDIA_DEVICE, "defaultBehavior": "quit current Cast app for a stronger stop", "mediaOnlyOverride": {"quitApp": False}, "example": {"action": "cast-stop", "device": DEFAULT_MEDIA_DEVICE, "quitApp": True}},
                "cast-youtube": {"required": ["query"], "defaultDevice": DEFAULT_MEDIA_DEVICE, "example": {"action": "cast-youtube", "query": "relaxing jazz", "device": DEFAULT_MEDIA_DEVICE}},
                "cast-play-url": {"required": ["url"], "defaultDevice": DEFAULT_MEDIA_DEVICE, "example": {"action": "cast-play-url", "url": "https://example.com/video.mp4", "device": DEFAULT_MEDIA_DEVICE}},
                "cast-spotify-devices": {"required": [], "defaultDevice": "speakers", "notes": "Lists currently visible Spotify Connect devices. Credentials load from local .env when present.", "example": {"action": "cast-spotify-devices", "device": "speakers"}},
                "cast-spotify": {"required": ["query or spotifyUri or resume=true"], "defaultDevice": "speakers", "notes": "Uses Spotify Connect; can wake idle Google Cast Spotify targets when SPOTIFY_SP_DC/SPOTIFY_SP_KEY are configured.", "examples": [{"action": "cast-spotify", "device": "speakers", "query": "Daft Punk Get Lucky"}, {"action": "cast-spotify", "device": "tv", "resume": True}, {"action": "cast-spotify", "device": "speakers", "spotifyDeviceName": "<spotify-device-name>", "resume": True}]},
                "cast-spotify-pause": {"required": [], "defaultDevice": "speakers", "example": {"action": "cast-spotify-pause", "device": "speakers"}},
                "cast-spotify-next": {"required": [], "defaultDevice": "speakers", "example": {"action": "cast-spotify-next", "device": "speakers"}},
                "cast-spotify-previous": {"required": [], "defaultDevice": "speakers", "example": {"action": "cast-spotify-previous", "device": "speakers"}},
                "cast-spotify-volume": {"required": ["level"], "defaultDevice": "speakers", "example": {"action": "cast-spotify-volume", "device": "speakers", "level": 25}},
                "cast-spotify-queue-add": {"required": ["query or spotifyUri"], "defaultDevice": "speakers", "notes": "Adds a track or episode to the selected Spotify Connect device queue.", "examples": [{"action": "cast-spotify-queue-add", "device": "speakers", "query": "Daft Punk Get Lucky"}, {"action": "cast-spotify-queue-add", "device": "speakers", "spotifyQueueType": "episode", "query": "Lex Fridman"}]},
                "cast-spotify-queue": {"required": [], "defaultDevice": "current active Spotify playback", "notes": "Reads the current Spotify queue.", "example": {"action": "cast-spotify-queue", "limit": 10}},
                "cast-spotify-seek": {"required": ["position or positionMs"], "defaultDevice": "speakers", "example": {"action": "cast-spotify-seek", "device": "speakers", "position": "1:30"}},
                "cast-spotify-shuffle": {"required": [], "defaultDevice": "speakers", "states": ["on", "off", "toggle"], "example": {"action": "cast-spotify-shuffle", "device": "speakers", "state": "toggle"}},
                "cast-spotify-repeat": {"required": [], "defaultDevice": "speakers", "states": ["off", "context", "track", "toggle"], "example": {"action": "cast-spotify-repeat", "device": "speakers", "repeatState": "toggle"}},
            },
            "purifierActions": {
                "purifier-status": {"required": [], "example": {"action": "purifier-status"}},
                "purifier-set": {
                    "required": ["setting"],
                    "writeSemantics": "If a write returns verification_pending, report that VeSync accepted it and check status later; do not immediately issue fallback commands unless explicitly asked.",
                    "settings": {
                        "power": ["on", "off", "toggle"],
                        "mode": ["auto", "manual", "sleep", "pet"],
                        "speed": [1, 2, 3, 4],
                        "display": ["on", "off"],
                        "child-lock": ["on", "off"],
                        "light-detection": ["on", "off"],
                        "auto-preference": ["default", "efficient", "quiet"],
                        "timer": "minutes, or value='clear'",
                    },
                    "examples": [
                        {"action": "purifier-set", "setting": "mode", "value": "sleep"},
                        {"action": "purifier-set", "setting": "speed", "level": 2},
                        {"action": "purifier-set", "setting": "timer", "minutes": 60},
                    ],
                },
            },
            "smartPlugActions": {
                "plug-list": {"required": [], "example": {"action": "plug-list"}},
                "plug-status": {"required": ["plug"], "example": {"action": "plug-status", "plug": "<configured-plug-name>"}},
                "plug-on": {"required": ["plug"], "example": {"action": "plug-on", "plug": "<configured-plug-name>"}},
                "plug-off": {"required": ["plug"], "example": {"action": "plug-off", "plug": "<configured-plug-name>"}},
                "plug-toggle": {"required": ["plug"], "example": {"action": "plug-toggle", "plug": "<configured-plug-name>"}},
                "plug-discover": {"required": [], "notes": "Broadcast discovery can fail from a VM; direct IP mapping in smart-plug/plugs.json is preferred."},
                "plug-save-discovery": {"required": [], "notes": "Overwrites smart-plug/plugs.json with discovered devices."},
            },
            "safetyRules": [
                "Keep spoken output short; keep full details in Discord.",
            ],
        },
    }


def handle_status(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "action": "status",
        "operationRoot": str(OPERATION_ROOT),
        "castScript": str(TV_SCRIPT),
        "python": choose_python(),
        "checks": {
            "operationRootExists": OPERATION_ROOT.exists(),
            "castScriptExists": TV_SCRIPT.exists(),
            "smartPlugSubsystemExists": SMART_PLUG_DIR.exists(),
            "smartPlugConfigExists": SMART_PLUG_CONFIG.exists(),
            "airPurifierSubsystemExists": AIR_PURIFIER_DIR.exists(),
            "airPurifierCliExists": AIR_PURIFIER_CLI.exists(),
        },
        "smartPlug": {
            "root": str(SMART_PLUG_DIR),
            "config": str(SMART_PLUG_CONFIG),
            "python": choose_smart_plug_python(),
            "configured": SMART_PLUG_CONFIG.exists(),
        },
        "airPurifier": {
            "root": str(AIR_PURIFIER_DIR),
            "cli": str(AIR_PURIFIER_CLI),
            "configured": AIR_PURIFIER_CLI.exists(),
        },
    }
    if not args.no_cast:
        cast = run_tv_command(["--device", args.device, "status"], timeout=args.cast_timeout)
        payload["cast"] = {"ok": True, "action": "cast-status", "device": args.device, **cast}
        payload["summary"] = f"Operation JARVIS is installed. Cast status checked for {args.device}; smart plugs configured={SMART_PLUG_CONFIG.exists()}."
    else:
        payload["summary"] = f"Operation JARVIS local files are installed. Cast status was skipped; smart plugs configured={SMART_PLUG_CONFIG.exists()}."
    return payload


def handle_speak(args: argparse.Namespace) -> dict[str, Any]:
    text = " ".join(args.text).strip()
    cast_payload = cast_speak(text, args)
    return {"ok": True, "action": "speak", "text": text, "cast": cast_payload, "summary": cast_payload.get("summary") or f"Spoke on {args.device}."}


def handle_cast_status(args: argparse.Namespace) -> dict[str, Any]:
    payload = {"ok": True, "action": "cast-status", "device": args.device, **run_tv_command(["--device", args.device, "status"], timeout=args.cast_timeout)}
    return {**payload, "summary": payload.get("stdout") or f"Status checked for {args.device}.", "cast": payload}


def handle_cast_volume(args: argparse.Namespace) -> dict[str, Any]:
    if args.level < 0 or args.level > 100:
        raise JarvisError("level must be between 0 and 100")
    payload = {"ok": True, "action": "cast-volume", "device": args.device, "level": args.level, **run_tv_command(["--device", args.device, "volume", str(args.level)], timeout=args.cast_timeout)}
    return {**payload, "summary": f"Set {args.device} volume to {args.level}.", "cast": payload}


def handle_cast_mute(args: argparse.Namespace) -> dict[str, Any]:
    payload = {"ok": True, "action": "cast-mute", "device": args.device, "state": args.state, **run_tv_command(["--device", args.device, "mute", args.state], timeout=args.cast_timeout)}
    return {**payload, "summary": f"Set {args.device} mute state to {args.state}.", "cast": payload}


def handle_cast_stop(args: argparse.Namespace) -> dict[str, Any]:
    quit_app = bool(getattr(args, "quit_app", True))
    tv_args = ["--device", args.device, "stop"]
    if quit_app:
        tv_args.append("--quit-app")
    else:
        tv_args.append("--media-only")
    payload = {"ok": True, "action": "cast-stop", "device": args.device, "quitApp": quit_app, **run_tv_command(tv_args, timeout=args.cast_timeout)}
    summary = f"Stopped Cast playback on {args.device} and quit the Cast app." if quit_app else f"Stopped Cast playback on {args.device}."
    return {**payload, "summary": summary, "cast": payload}


def handle_cast_youtube(args: argparse.Namespace) -> dict[str, Any]:
    query = " ".join(args.query).strip()
    if not query:
        raise JarvisError("query is required")
    tv_args = ["--device", args.device, "youtube", query]
    if args.enqueue:
        tv_args.append("--enqueue")
    if args.no_search:
        tv_args.append("--no-search")
    payload = {"ok": True, "action": "cast-youtube", "device": args.device, "query": query, **run_tv_command(tv_args, timeout=args.cast_timeout + 60.0)}
    return {**payload, "summary": f"Sent YouTube cast command to {args.device}: {query}", "cast": payload}


def handle_cast_play_url(args: argparse.Namespace) -> dict[str, Any]:
    if not args.url.strip():
        raise JarvisError("url is required")
    payload = {"ok": True, "action": "cast-play-url", "device": args.device, "url": args.url, "contentType": args.content_type, **run_tv_command(["--device", args.device, "play-url", args.url, "--type", args.content_type], timeout=args.cast_timeout)}
    return {**payload, "summary": f"Sent media URL to {args.device}.", "cast": payload}


def _append_spotify_auth_flags(tv_args: list[str], args: argparse.Namespace) -> None:
    if args.spotify_client_id:
        tv_args.extend(["--spotify-client-id", args.spotify_client_id])
    if args.spotify_client_secret:
        tv_args.extend(["--spotify-client-secret", args.spotify_client_secret])
    if args.spotify_refresh_token:
        tv_args.extend(["--spotify-refresh-token", args.spotify_refresh_token])


def handle_cast_spotify_devices(args: argparse.Namespace) -> dict[str, Any]:
    tv_args = ["--device", args.device, "spotify-devices"]
    _append_spotify_auth_flags(tv_args, args)
    payload = {
        "ok": True,
        "action": "cast-spotify-devices",
        "device": args.device,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 30.0),
    }
    return {**payload, "summary": payload.get("stdout") or f"Listed Spotify devices for {args.device}.", "cast": payload}


def handle_cast_spotify(args: argparse.Namespace) -> dict[str, Any]:
    query = " ".join(args.query).strip()
    spotify_uri = (args.spotify_uri or "").strip()
    if not query and not spotify_uri and not args.resume:
        raise JarvisError("Provide query, spotify-uri, or resume=true for cast-spotify")

    tv_args = ["--device", args.device, "spotify-play"]
    _append_spotify_auth_flags(tv_args, args)

    if spotify_uri:
        tv_args.extend(["--uri", spotify_uri])
    if args.resume:
        tv_args.append("--resume")
    if args.spotify_device_name:
        tv_args.extend(["--spotify-device-name", args.spotify_device_name])
    if args.spotify_device_id:
        tv_args.extend(["--spotify-device-id", args.spotify_device_id])
    if args.spotify_type:
        tv_args.extend(["--type", args.spotify_type])
    if args.market:
        tv_args.extend(["--market", args.market])
    if query:
        tv_args.append(query)

    payload = {
        "ok": True,
        "action": "cast-spotify",
        "device": args.device,
        "query": query or None,
        "spotifyUri": spotify_uri or None,
        "resume": bool(args.resume),
        "spotifyType": args.spotify_type,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 45.0),
    }

    target_desc = spotify_uri or query or "resume"
    return {**payload, "summary": f"Sent Spotify playback command to {args.device}: {target_desc}", "cast": payload}


def _append_spotify_device_flags(tv_args: list[str], args: argparse.Namespace) -> None:
    if args.spotify_device_name:
        tv_args.extend(["--spotify-device-name", args.spotify_device_name])
    if args.spotify_device_id:
        tv_args.extend(["--spotify-device-id", args.spotify_device_id])


def _handle_spotify_control(args: argparse.Namespace, *, action: str, tv_command: str, summary_verb: str, extra_args: Optional[list[str]] = None) -> dict[str, Any]:
    tv_args = ["--device", args.device, tv_command]
    _append_spotify_auth_flags(tv_args, args)
    _append_spotify_device_flags(tv_args, args)
    if extra_args:
        tv_args.extend(extra_args)
    payload = {
        "ok": True,
        "action": action,
        "device": args.device,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 30.0),
    }
    return {**payload, "summary": f"Sent Spotify {summary_verb} command to {args.device}.", "cast": payload}


def handle_cast_spotify_pause(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_spotify_control(args, action="cast-spotify-pause", tv_command="spotify-pause", summary_verb="pause")


def handle_cast_spotify_next(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_spotify_control(args, action="cast-spotify-next", tv_command="spotify-next", summary_verb="next-track")


def handle_cast_spotify_previous(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_spotify_control(args, action="cast-spotify-previous", tv_command="spotify-previous", summary_verb="previous-track")


def handle_cast_spotify_volume(args: argparse.Namespace) -> dict[str, Any]:
    if args.level < 0 or args.level > 100:
        raise JarvisError("Spotify volume level must be between 0 and 100")
    payload = _handle_spotify_control(
        args,
        action="cast-spotify-volume",
        tv_command="spotify-volume",
        summary_verb=f"volume {args.level}%",
        extra_args=[str(int(args.level))],
    )
    payload["level"] = args.level
    return payload


def handle_cast_spotify_queue_add(args: argparse.Namespace) -> dict[str, Any]:
    query = " ".join(args.query).strip()
    spotify_uri = (args.spotify_uri or "").strip()
    if not query and not spotify_uri:
        raise JarvisError("Provide query or spotify-uri for cast-spotify-queue-add")
    tv_args = ["--device", args.device, "spotify-queue-add"]
    _append_spotify_auth_flags(tv_args, args)
    _append_spotify_device_flags(tv_args, args)
    if spotify_uri:
        tv_args.extend(["--uri", spotify_uri])
    if args.spotify_queue_type:
        tv_args.extend(["--type", args.spotify_queue_type])
    if args.market:
        tv_args.extend(["--market", args.market])
    if query:
        tv_args.append(query)
    payload = {
        "ok": True,
        "action": "cast-spotify-queue-add",
        "device": args.device,
        "query": query or None,
        "spotifyUri": spotify_uri or None,
        "spotifyQueueType": args.spotify_queue_type,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 45.0),
    }
    target_desc = spotify_uri or query
    return {**payload, "summary": f"Added Spotify queue item on {args.device}: {target_desc}", "cast": payload}


def handle_cast_spotify_queue(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit <= 0:
        raise JarvisError("limit must be greater than 0")
    tv_args = ["--device", args.device, "spotify-queue"]
    _append_spotify_auth_flags(tv_args, args)
    if args.limit:
        tv_args.extend(["--limit", str(args.limit)])
    payload = {
        "ok": True,
        "action": "cast-spotify-queue",
        "device": args.device,
        "limit": args.limit,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 30.0),
    }
    return {**payload, "summary": payload.get("stdout") or "Read Spotify queue.", "cast": payload}


def handle_cast_spotify_seek(args: argparse.Namespace) -> dict[str, Any]:
    if args.position_ms is None and not args.position:
        raise JarvisError("Provide position or position-ms for cast-spotify-seek")
    tv_args = ["--device", args.device, "spotify-seek"]
    _append_spotify_auth_flags(tv_args, args)
    _append_spotify_device_flags(tv_args, args)
    if args.position_ms is not None:
        tv_args.extend(["--position-ms", str(int(args.position_ms))])
    else:
        tv_args.append(str(args.position))
    payload = {
        "ok": True,
        "action": "cast-spotify-seek",
        "device": args.device,
        "position": args.position,
        "positionMs": args.position_ms,
        **run_tv_command(tv_args, timeout=args.cast_timeout + 30.0),
    }
    target_desc = f"{args.position_ms}ms" if args.position_ms is not None else str(args.position)
    return {**payload, "summary": f"Sent Spotify seek command to {args.device}: {target_desc}", "cast": payload}


def handle_cast_spotify_shuffle(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_spotify_control(
        args,
        action="cast-spotify-shuffle",
        tv_command="spotify-shuffle",
        summary_verb=f"shuffle {args.state}",
        extra_args=[args.state],
    )


def handle_cast_spotify_repeat(args: argparse.Namespace) -> dict[str, Any]:
    repeat_state = args.repeat_state or "toggle"
    return _handle_spotify_control(
        args,
        action="cast-spotify-repeat",
        tv_command="spotify-repeat",
        summary_verb=f"repeat {repeat_state}",
        extra_args=[repeat_state],
    )


def add_air_purifier_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--purifier", default=None, help="Optional VeSync purifier name/CID/model override")
    parser.add_argument("--purifier-timeout", type=float, default=DEFAULT_AIR_PURIFIER_TIMEOUT, help="Air-purifier command timeout seconds")


def purifier_summary(status: dict[str, Any]) -> str:
    name = status.get("name") or "Air purifier"
    power = status.get("power") or ("on" if status.get("is_on") else "off")
    mode = status.get("mode") or "unknown"
    fan = status.get("fan_level")
    pm25 = status.get("pm25")
    filter_life = status.get("filter_life")
    display = status.get("display_status") or status.get("display_set_status")
    bits = [f"{name}: {power}", f"mode {mode}"]
    if fan is not None:
        bits.append(f"fan {fan}")
    if pm25 is not None:
        bits.append(f"PM2.5 {pm25}")
    if filter_life is not None:
        bits.append(f"filter {filter_life}%")
    if display is not None:
        bits.append(f"display {display}")
    supported_modes = status.get("supported_modes")
    if isinstance(supported_modes, list) and supported_modes:
        bits.append("modes " + "/".join(str(mode) for mode in supported_modes))
    supported_fan_levels = status.get("supported_fan_levels")
    if isinstance(supported_fan_levels, list) and supported_fan_levels:
        bits.append("speeds " + "/".join(str(level) for level in supported_fan_levels))
    if status.get("verification_pending"):
        bits.append("write accepted; verification pending")
    return ", ".join(bits) + "."


def _purifier_device_args(args: argparse.Namespace) -> list[str]:
    purifier = (getattr(args, "purifier", None) or "").strip()
    return [purifier] if purifier else []


def _canon_purifier_setting(value: str) -> str:
    setting = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "lock": "child-lock",
        "childlock": "child-lock",
        "child-lock": "child-lock",
        "display-lock": "child-lock",
        "light": "light-detection",
        "light-detect": "light-detection",
        "light-detection": "light-detection",
        "auto": "auto-preference",
        "auto-pref": "auto-preference",
        "auto-preference": "auto-preference",
        "preference": "auto-preference",
        "fan": "speed",
        "fan-speed": "speed",
        "speed": "speed",
        "mode": "mode",
        "power": "power",
        "timer": "timer",
        "display": "display",
    }
    return aliases.get(setting, setting)


def _canon_on_off(value: str, *, allow_toggle: bool = False) -> str:
    clean = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "true": "on",
        "yes": "on",
        "enable": "on",
        "enabled": "on",
        "start": "on",
        "turn-on": "on",
        "false": "off",
        "no": "off",
        "disable": "off",
        "disabled": "off",
        "stop": "off",
        "turn-off": "off",
        "flip": "toggle",
    }
    clean = aliases.get(clean, clean)
    valid = set(PURIFIER_ON_OFF_STATES)
    if allow_toggle:
        valid.add("toggle")
    if clean not in valid:
        raise JarvisError(f"Expected {'on/off/toggle' if allow_toggle else 'on/off'}, got {value!r}")
    return clean


def _value_from_args(args: argparse.Namespace) -> str:
    values = getattr(args, "value", None) or []
    return " ".join(values).strip()


def _purifier_set_cli_args(args: argparse.Namespace) -> list[str]:
    setting = _canon_purifier_setting(args.setting)
    value = _value_from_args(args)
    state = getattr(args, "state", None)
    level = getattr(args, "level", None)
    minutes = getattr(args, "minutes", None)
    purifier = _purifier_device_args(args)

    if setting not in PURIFIER_SETTINGS:
        raise JarvisError(f"Unsupported purifier setting {args.setting!r}; expected one of {', '.join(PURIFIER_SETTINGS)}")

    if setting == "power":
        desired = _canon_on_off(value or state or "", allow_toggle=True)
        return [desired, *purifier]

    if setting == "mode":
        mode = (value or "").strip().lower()
        if mode not in PURIFIER_MODES:
            raise JarvisError(f"Invalid purifier mode {mode!r}; expected one of {', '.join(PURIFIER_MODES)}")
        return ["mode", mode, *purifier]

    if setting == "speed":
        raw_level = level if level is not None else value
        try:
            speed = int(raw_level)
        except (TypeError, ValueError) as exc:
            raise JarvisError("Purifier speed requires level 1-4") from exc
        if speed not in PURIFIER_SPEEDS:
            raise JarvisError("Purifier speed must be 1, 2, 3, or 4")
        return ["speed", str(speed), *purifier]

    if setting == "display":
        desired = _canon_on_off(value or state or "")
        return ["display", desired, *purifier]

    if setting == "child-lock":
        desired = _canon_on_off(value or state or "")
        return ["child-lock", desired, *purifier]

    if setting == "light-detection":
        desired = _canon_on_off(value or state or "")
        return ["light-detection", desired, *purifier]

    if setting == "auto-preference":
        preference = (value or "").strip().lower()
        if preference not in PURIFIER_AUTO_PREFERENCES:
            raise JarvisError(f"Invalid auto preference {preference!r}; expected one of {', '.join(PURIFIER_AUTO_PREFERENCES)}")
        cli_args = ["auto-preference", preference, *purifier]
        room_size = getattr(args, "room_size", None)
        if room_size is not None:
            cli_args.extend(["--room-size", str(room_size)])
        return cli_args

    if setting == "timer":
        if (value or "").strip().lower() in {"clear", "cancel", "off", "none"}:
            return ["clear-timer", *purifier]
        raw_minutes = minutes if minutes is not None else value
        try:
            timer_minutes = int(raw_minutes)
        except (TypeError, ValueError) as exc:
            raise JarvisError("Purifier timer requires minutes, or value='clear'") from exc
        if timer_minutes <= 0 or timer_minutes > 1440:
            raise JarvisError("Purifier timer minutes must be between 1 and 1440")
        return ["timer", str(timer_minutes), *purifier]

    raise JarvisError(f"Unsupported purifier setting {setting!r}")


def handle_purifier_status(args: argparse.Namespace) -> dict[str, Any]:
    result = run_air_purifier_command(
        ["status", *_purifier_device_args(args)],
        timeout=args.purifier_timeout,
    )
    status = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": "purifier-status",
        "airPurifierRoot": str(AIR_PURIFIER_DIR),
        "purifier": status,
        "summary": purifier_summary(status),
        "airPurifier": result,
    }


def handle_purifier_set(args: argparse.Namespace) -> dict[str, Any]:
    cli_args = _purifier_set_cli_args(args)
    result = run_air_purifier_command(cli_args, timeout=args.purifier_timeout)
    status = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": "purifier-set",
        "setting": _canon_purifier_setting(args.setting),
        "airPurifierRoot": str(AIR_PURIFIER_DIR),
        "purifier": status,
        "summary": purifier_summary(status),
        "airPurifier": result,
    }


def add_smart_plug_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plug-config", default=None, help=f"Smart-plug config path; default: {SMART_PLUG_CONFIG}")
    parser.add_argument("--discovery-target", default=None, help="Kasa discovery broadcast target, e.g. a LAN broadcast address")
    parser.add_argument("--plug-timeout", type=float, default=DEFAULT_SMART_PLUG_TIMEOUT, help="Smart-plug command timeout seconds")


def handle_plug_list(args: argparse.Namespace) -> dict[str, Any]:
    result = run_smart_plug_command(
        ["list"],
        timeout=args.plug_timeout,
        config_path=smart_plug_config_path(args),
        discovery_target=args.discovery_target,
    )
    plugs = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": "plug-list",
        "smartPlugRoot": str(SMART_PLUG_DIR),
        "plugs": plugs,
        "summary": smart_plug_many_summary(plugs, verb="configured"),
        "smartPlug": result,
    }


def handle_plug_discover(args: argparse.Namespace) -> dict[str, Any]:
    result = run_smart_plug_command(
        ["discover"],
        timeout=args.plug_timeout,
        config_path=smart_plug_config_path(args),
        discovery_target=args.discovery_target,
    )
    plugs = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": "plug-discover",
        "smartPlugRoot": str(SMART_PLUG_DIR),
        "plugs": plugs,
        "summary": smart_plug_many_summary(plugs, verb="discovered"),
        "smartPlug": result,
    }


def handle_plug_save_discovery(args: argparse.Namespace) -> dict[str, Any]:
    result = run_smart_plug_command(
        ["save-discovery"],
        timeout=args.plug_timeout,
        config_path=smart_plug_config_path(args),
        discovery_target=args.discovery_target,
    )
    plugs = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": "plug-save-discovery",
        "smartPlugRoot": str(SMART_PLUG_DIR),
        "plugs": plugs,
        "summary": smart_plug_many_summary(plugs, verb="saved from discovery"),
        "smartPlug": result,
    }


def _handle_plug_power_action(args: argparse.Namespace, command: str, action: str) -> dict[str, Any]:
    result = run_smart_plug_command(
        [command, args.plug],
        timeout=args.plug_timeout,
        config_path=smart_plug_config_path(args),
        discovery_target=args.discovery_target,
    )
    status = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": True,
        "action": action,
        "smartPlugRoot": str(SMART_PLUG_DIR),
        "plugName": status.get("name") or args.plug,
        "plug": status,
        "summary": smart_plug_status_summary(status),
        "smartPlug": result,
    }


def handle_plug_status(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_plug_power_action(args, "status", "plug-status")


def handle_plug_on(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_plug_power_action(args, "on", "plug-on")


def handle_plug_off(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_plug_power_action(args, "off", "plug-off")


def handle_plug_toggle(args: argparse.Namespace) -> dict[str, Any]:
    return _handle_plug_power_action(args, "toggle", "plug-toggle")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    help_cmd = subparsers.add_parser("help", help="Show a machine-readable Operation JARVIS action guide")
    help_cmd.set_defaults(func=handle_help)

    status = subparsers.add_parser("status", help="Check Operation JARVIS install and optionally a Cast target")
    status.add_argument("--device", default=DEFAULT_MEDIA_DEVICE, choices=DEVICE_CHOICES)
    status.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    status.add_argument("--no-cast", action="store_true", help="Only check local files; do not contact Cast devices")
    status.set_defaults(func=handle_status)

    speak = subparsers.add_parser("speak", help="Speak text through a Cast speaker")
    add_speak_options(speak)
    speak.add_argument("text", nargs="+")
    speak.set_defaults(func=handle_speak)

    cast_status = subparsers.add_parser("cast-status", help="Show Cast target status")
    cast_status.add_argument("--device", default=DEFAULT_MEDIA_DEVICE, choices=DEVICE_CHOICES)
    cast_status.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    cast_status.set_defaults(func=handle_cast_status)

    cast_volume = subparsers.add_parser("cast-volume", help="Set Cast target volume")
    cast_volume.add_argument("level", type=float)
    cast_volume.add_argument("--device", default=DEFAULT_SPEAK_DEVICE, choices=DEVICE_CHOICES)
    cast_volume.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    cast_volume.set_defaults(func=handle_cast_volume)

    cast_mute = subparsers.add_parser("cast-mute", help="Mute, unmute, or toggle Cast target")
    cast_mute.add_argument("state", choices=MUTE_STATES)
    cast_mute.add_argument("--device", default=DEFAULT_SPEAK_DEVICE, choices=DEVICE_CHOICES)
    cast_mute.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    cast_mute.set_defaults(func=handle_cast_mute)

    cast_stop = subparsers.add_parser("cast-stop", help="Stop Cast target playback and quit the Cast app by default")
    cast_stop.add_argument("--device", default=DEFAULT_MEDIA_DEVICE, choices=DEVICE_CHOICES)
    cast_stop.add_argument("--quit-app", dest="quit_app", action="store_true", default=True, help="Quit the current Cast app after stopping playback; default")
    cast_stop.add_argument("--media-only", dest="quit_app", action="store_false", help="Only stop media playback; leave the Cast app open")
    cast_stop.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    cast_stop.set_defaults(func=handle_cast_stop)

    cast_youtube = subparsers.add_parser("cast-youtube", help="Cast a YouTube query/URL/video ID")
    cast_youtube.add_argument("query", nargs="+")
    cast_youtube.add_argument("--device", default=DEFAULT_MEDIA_DEVICE, choices=DEVICE_CHOICES)
    cast_youtube.add_argument("--cast-timeout", type=float, default=90.0)
    cast_youtube.add_argument("--enqueue", action="store_true")
    cast_youtube.add_argument("--no-search", action="store_true")
    cast_youtube.set_defaults(func=handle_cast_youtube)

    cast_play = subparsers.add_parser("cast-play-url", help="Cast a direct media URL")
    cast_play.add_argument("url")
    cast_play.add_argument("--type", dest="content_type", default="video/mp4")
    cast_play.add_argument("--device", default=DEFAULT_MEDIA_DEVICE, choices=DEVICE_CHOICES)
    cast_play.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    cast_play.set_defaults(func=handle_cast_play_url)

    cast_spotify_devices = subparsers.add_parser("cast-spotify-devices", help="List Spotify Connect devices available to your Spotify account")
    cast_spotify_devices.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_devices.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_options(cast_spotify_devices)
    cast_spotify_devices.set_defaults(func=handle_cast_spotify_devices)

    cast_spotify = subparsers.add_parser("cast-spotify", help="Play Spotify content using your Spotify account via Spotify Connect")
    cast_spotify.add_argument("query", nargs="*")
    cast_spotify.add_argument("--spotify-uri", default=None, help="Spotify URI or open.spotify.com URL")
    cast_spotify.add_argument("--resume", action="store_true", help="Resume current Spotify playback")
    cast_spotify.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify.add_argument("--cast-timeout", type=float, default=90.0)
    add_spotify_options(cast_spotify)
    cast_spotify.set_defaults(func=handle_cast_spotify)

    cast_spotify_pause = subparsers.add_parser("cast-spotify-pause", help="Pause Spotify playback on the selected Spotify Connect device")
    cast_spotify_pause.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_pause.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_pause)
    cast_spotify_pause.set_defaults(func=handle_cast_spotify_pause)

    cast_spotify_next = subparsers.add_parser("cast-spotify-next", help="Skip to the next Spotify track")
    cast_spotify_next.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_next.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_next)
    cast_spotify_next.set_defaults(func=handle_cast_spotify_next)

    cast_spotify_previous = subparsers.add_parser("cast-spotify-previous", aliases=["cast-spotify-prev"], help="Skip to the previous Spotify track")
    cast_spotify_previous.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_previous.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_previous)
    cast_spotify_previous.set_defaults(func=handle_cast_spotify_previous)

    cast_spotify_volume = subparsers.add_parser("cast-spotify-volume", help="Set Spotify Connect volume percent")
    cast_spotify_volume.add_argument("level", type=int, help="Volume percent, 0-100")
    cast_spotify_volume.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_volume.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_volume)
    cast_spotify_volume.set_defaults(func=handle_cast_spotify_volume)

    cast_spotify_queue_add = subparsers.add_parser("cast-spotify-queue-add", aliases=["cast-spotify-add-queue"], help="Add a Spotify track or episode to the playback queue")
    cast_spotify_queue_add.add_argument("query", nargs="*", help="Track/episode search query, Spotify URL, or Spotify URI")
    cast_spotify_queue_add.add_argument("--spotify-uri", default=None, help="Explicit Spotify track/episode URI or open.spotify.com URL")
    cast_spotify_queue_add.add_argument("--spotify-queue-type", choices=SPOTIFY_QUEUE_TYPES, default="track", help="Search type when query text is used")
    cast_spotify_queue_add.add_argument("--market", default=None, help="Spotify market code, e.g. CA or US")
    cast_spotify_queue_add.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_queue_add.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_queue_add)
    cast_spotify_queue_add.set_defaults(func=handle_cast_spotify_queue_add)

    cast_spotify_queue = subparsers.add_parser("cast-spotify-queue", help="Read the current Spotify playback queue")
    cast_spotify_queue.add_argument("--limit", type=int, default=20, help="Maximum queue items to print")
    cast_spotify_queue.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_queue.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_queue)
    cast_spotify_queue.set_defaults(func=handle_cast_spotify_queue)

    cast_spotify_seek = subparsers.add_parser("cast-spotify-seek", help="Seek Spotify playback to a timestamp")
    cast_spotify_seek.add_argument("position", nargs="?", default=None, help="Timestamp, e.g. 90, 90s, 1:30, 1:02:03, or 90000ms")
    cast_spotify_seek.add_argument("--position-ms", type=int, default=None, help="Explicit seek position in milliseconds")
    cast_spotify_seek.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_seek.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_seek)
    cast_spotify_seek.set_defaults(func=handle_cast_spotify_seek)

    cast_spotify_shuffle = subparsers.add_parser("cast-spotify-shuffle", help="Set or toggle Spotify shuffle")
    cast_spotify_shuffle.add_argument("state", nargs="?", default="toggle", choices=MUTE_STATES, help="Shuffle state; default toggle")
    cast_spotify_shuffle.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_shuffle.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_shuffle)
    cast_spotify_shuffle.set_defaults(func=handle_cast_spotify_shuffle)

    cast_spotify_repeat = subparsers.add_parser("cast-spotify-repeat", help="Set or toggle Spotify repeat")
    cast_spotify_repeat.add_argument("repeat_state", nargs="?", default="toggle", choices=SPOTIFY_REPEAT_STATES, help="Repeat state; default toggle (off <-> context)")
    cast_spotify_repeat.add_argument("--device", default="speakers", choices=DEVICE_CHOICES)
    cast_spotify_repeat.add_argument("--cast-timeout", type=float, default=DEFAULT_CAST_TIMEOUT)
    add_spotify_control_options(cast_spotify_repeat)
    cast_spotify_repeat.set_defaults(func=handle_cast_spotify_repeat)

    purifier_status = subparsers.add_parser("purifier-status", help="Show Levoit/VeSync air purifier status")
    add_air_purifier_options(purifier_status)
    purifier_status.set_defaults(func=handle_purifier_status)

    purifier_set = subparsers.add_parser("purifier-set", help="Set one air purifier setting")
    add_air_purifier_options(purifier_set)
    purifier_set.add_argument("setting", choices=PURIFIER_SETTINGS, help="Setting to control")
    purifier_set.add_argument("value", nargs="*", help="Setting value, e.g. on/off/auto/sleep/clear")
    purifier_set.add_argument("--level", type=int, default=None, help="Speed level for setting=speed, 1-4")
    purifier_set.add_argument("--state", choices=PURIFIER_POWER_STATES, default=None, help="Power/display/lock state convenience field")
    purifier_set.add_argument("--minutes", type=int, default=None, help="Timer minutes for setting=timer")
    purifier_set.add_argument("--room-size", type=int, default=None, help="Room size in square feet for setting=auto-preference")
    purifier_set.set_defaults(func=handle_purifier_set)

    plug_list = subparsers.add_parser("plug-list", help="List configured smart plugs")
    add_smart_plug_options(plug_list)
    plug_list.set_defaults(func=handle_plug_list)

    plug_discover = subparsers.add_parser("plug-discover", help="Discover Kasa smart plugs on the LAN")
    add_smart_plug_options(plug_discover)
    plug_discover.set_defaults(func=handle_plug_discover)

    plug_save_discovery = subparsers.add_parser("plug-save-discovery", help="Discover Kasa smart plugs and save smart-plug/plugs.json")
    add_smart_plug_options(plug_save_discovery)
    plug_save_discovery.set_defaults(func=handle_plug_save_discovery)

    plug_status = subparsers.add_parser("plug-status", help="Show smart-plug power state")
    add_smart_plug_options(plug_status)
    plug_status.add_argument("plug", help="Configured plug alias or a direct IP address")
    plug_status.set_defaults(func=handle_plug_status)

    plug_on = subparsers.add_parser("plug-on", help="Turn a smart plug on")
    add_smart_plug_options(plug_on)
    plug_on.add_argument("plug", help="Configured plug alias or a direct IP address")
    plug_on.set_defaults(func=handle_plug_on)

    plug_off = subparsers.add_parser("plug-off", help="Turn a smart plug off")
    add_smart_plug_options(plug_off)
    plug_off.add_argument("plug", help="Configured plug alias or a direct IP address")
    plug_off.set_defaults(func=handle_plug_off)

    plug_toggle = subparsers.add_parser("plug-toggle", help="Toggle a smart plug")
    add_smart_plug_options(plug_toggle)
    plug_toggle.add_argument("plug", help="Configured plug alias or a direct IP address")
    plug_toggle.set_defaults(func=handle_plug_toggle)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    action = getattr(args, "command", None)
    emit_event("action.start", action=action, summary=f"Starting {action}.")
    try:
        payload = args.func(args)
        payload.setdefault("operationRoot", str(OPERATION_ROOT))
        payload.setdefault("summary", payload.get("stdout") or "Operation JARVIS action completed.")
        emit_event(
            "action.complete",
            action=action,
            ok=bool(payload.get("ok", True)),
            summary=str(payload.get("summary") or "Operation JARVIS action completed."),
            artifacts=payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else [],
            data={"device": payload.get("device")},
        )
        if args.json:
            json_print(payload)
        else:
            print(payload.get("summary") or json.dumps(payload, indent=2))
        return 0
    except KeyboardInterrupt:
        error = {"ok": False, "action": action, "error": "Cancelled."}
        emit_event("action.error", action=action, ok=False, summary="Cancelled.", error="Cancelled.")
        if getattr(args, "json", False):
            json_print(error)
        else:
            print("Cancelled.", file=sys.stderr)
        return 130
    except subprocess.TimeoutExpired as exc:
        error = {"ok": False, "action": action, "error": f"command timed out: {exc}"}
        emit_event("action.error", action=action, ok=False, summary=error["error"], error=error["error"])
        if getattr(args, "json", False):
            json_print(error)
        else:
            print(f"Error: {error['error']}", file=sys.stderr)
        return 124
    except Exception as exc:
        error = {"ok": False, "action": action, "error": str(exc)}
        emit_event("action.error", action=action, ok=False, summary=str(exc), error=str(exc))
        if getattr(args, "json", False):
            json_print(error)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
