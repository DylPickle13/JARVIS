#!/usr/bin/env python3
"""Focused Cast CLI used internally by Operation JARVIS.

The public interface is `jarvis.py` / `jarvis-cli`; this script keeps only the
explicit Cast commands needed by that adapter.

Examples:
  python scripts/tv.py status
  python scripts/tv.py volume 35
  python scripts/tv.py mute on
  python scripts/tv.py play-url https://example.com/video.mp4 --type video/mp4
  python scripts/tv.py youtube "Animals As Leaders CAFO official music video"
  python scripts/tv.py --device speakers status
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

# Allow importing the connection helpers from the neighboring script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from connect_chromecast import (  # noqa: E402
    DEFAULT_CAST_PORT,
    DEFAULT_DEVICE_ALIAS,
    DEFAULT_DISCOVERY_TIMEOUT,
    DEFAULT_SOCKET_TIMEOUT,
    apply_target_defaults,
    check_tcp_port,
    find_cast,
    import_pychromecast,
    iter_targets,
    print_cast_summary,
    stop_discovery,
)

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SPOTIFY_LINK_RE = re.compile(r"^https?://open\.spotify\.com/(track|album|playlist|artist|episode)/([A-Za-z0-9]+)")
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_WEB_SERVER_TIME_URL = "https://open.spotify.com/server-time"
SPOTIFY_WEB_ACCESS_TOKEN_URL = "https://open.spotify.com/api/token"
SPOTIFY_LEGACY_WEB_ACCESS_TOKEN_URL = "https://open.spotify.com/get_access_token"
SPOTIFY_TOTP_SECRET_DICT_URL = "https://code.thetadev.de/ThetaDev/spotify-secrets/raw/branch/main/secrets/secretDict.json"
SPOTIFY_DEVICE_AUTH_URL = "https://spclient.wg.spotify.com/device-auth/v1/refresh"
SPOTIFY_CAST_APP_ID = "CC32E753"
SPOTIFY_CAST_NAMESPACE = "urn:x-cast:com.spotify.chromecast.secure.v1"
SPOTIFY_CAST_POLL_INTERVAL_SECONDS = 1.5
SPOTIFY_CAST_TOTP_CIPHER_BASE = (12, 56, 76, 33, 88, 44, 88, 33, 78, 78, 11, 66, 22, 22, 55, 69, 54)
SPOTIFY_FALLBACK_TOTP_SECRET_VERSION = 61
SPOTIFY_FALLBACK_TOTP_SECRET = (44, 55, 47, 42, 70, 40, 34, 114, 76, 74, 50, 111, 120, 97, 75, 76, 94, 102, 43, 69, 49, 120, 118, 80, 64, 78)
OPERATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = OPERATION_ROOT.parents[1]


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


def add_common_args(parser: argparse.ArgumentParser) -> None:
    default_device = os.environ.get("OPERATION_JARVIS_CAST_DEVICE", DEFAULT_DEVICE_ALIAS)
    parser.add_argument("--device", default=default_device, help="Configured Cast target alias, e.g. tv or speakers")
    parser.add_argument("--name", default=None, help="Override Chromecast friendly name")
    parser.add_argument("--host", default=None, help="Override Chromecast IP address or hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_CAST_PORT, help="Chromecast Cast V2 TCP port")
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=DEFAULT_DISCOVERY_TIMEOUT,
        help="Seconds to wait for mDNS/known-host discovery",
    )
    parser.add_argument(
        "--socket-timeout",
        type=float,
        default=DEFAULT_SOCKET_TIMEOUT,
        help="Seconds to wait for socket operations",
    )
    parser.add_argument(
        "--skip-tcp-check",
        action="store_true",
        help="Skip the quick TCP reachability check before PyChromecast discovery",
    )


def get_connected_cast(args: argparse.Namespace) -> Tuple[Any, Any, Any]:
    """Return (pychromecast, cast, browser) for the configured target."""
    apply_target_defaults(args)

    if not args.skip_tcp_check:
        if not check_tcp_port(args.host, args.port, timeout=min(args.socket_timeout, 5.0)):
            print("Continuing anyway; PyChromecast may still provide more detail.")

    pychromecast = import_pychromecast()
    if pychromecast is None:
        raise SystemExit(2)

    cast, browser = find_cast(
        pychromecast=pychromecast,
        name=args.name,
        host=args.host,
        discovery_timeout=args.discovery_timeout,
        socket_timeout=args.socket_timeout,
    )
    if cast is None:
        stop_discovery(browser)
        raise RuntimeError(f'Could not find/connect to Chromecast "{args.name}" at {args.host}')

    cast.wait(timeout=args.socket_timeout)
    return pychromecast, cast, browser


@contextlib.contextmanager
def connected_cast(args: argparse.Namespace):
    cast = None
    browser = None
    try:
        pychromecast, cast, browser = get_connected_cast(args)
        yield pychromecast, cast
    finally:
        if cast is not None:
            try:
                cast.disconnect(timeout=3, blocking=True)
            except Exception:
                pass
        stop_discovery(browser)


def parse_volume(value: str) -> float:
    raw = float(value.strip().rstrip("%"))
    level = raw / 100.0 if raw > 1 else raw
    return max(0.0, min(1.0, level))


def extract_youtube_id(text: str) -> Optional[str]:
    text = text.strip()
    if YOUTUBE_ID_RE.match(text):
        return text

    parsed = urlparse(text)
    host = parsed.netloc.lower().removeprefix("www.")

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id and YOUTUBE_ID_RE.match(query_id):
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"} and YOUTUBE_ID_RE.match(parts[1]):
            return parts[1]

    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if YOUTUBE_ID_RE.match(video_id):
            return video_id

    return None


def search_youtube(query: str) -> Dict[str, Any]:
    """Search YouTube and return the top result metadata."""
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
    }

    # yt-dlp currently prints a Python 3.9 deprecation notice directly to stderr.
    # Capture it so the CLI output stays focused on the TV action.
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception as exc:
        captured = stderr.getvalue().strip()
        if captured:
            print(captured, file=sys.stderr)
        raise RuntimeError(f'YouTube search failed for query "{query}": {exc}') from exc

    entries = info.get("entries") or []
    if not entries:
        raise RuntimeError(f'No YouTube results found for "{query}"')

    entry = entries[0]
    video_id = entry.get("id") or extract_youtube_id(entry.get("url", ""))
    if not video_id:
        raise RuntimeError(f"Could not determine video ID from top result: {entry}")

    return {
        "id": video_id,
        "title": entry.get("title") or video_id,
        "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        "channel": entry.get("channel") or entry.get("uploader"),
        "duration": entry.get("duration"),
    }


def resolve_youtube_target(text: str, no_search: bool = False) -> Dict[str, Any]:
    video_id = extract_youtube_id(text)
    if video_id:
        return {
            "id": video_id,
            "title": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": None,
            "duration": None,
        }

    if no_search:
        raise RuntimeError(f'"{text}" is not a YouTube video URL or 11-character video ID')

    return search_youtube(text)


def cast_youtube(args: argparse.Namespace, query_or_url: str, enqueue: bool = False, no_search: bool = False) -> int:
    result = resolve_youtube_target(query_or_url, no_search=no_search)
    video_id = result["id"]

    print("YouTube selection:")
    print(f"  title:   {result['title']}")
    if result.get("channel"):
        print(f"  channel: {result['channel']}")
    print(f"  url:     https://www.youtube.com/watch?v={video_id}")

    with connected_cast(args) as (pychromecast, cast):
        from pychromecast import quick_play  # type: ignore

        print(f'Casting YouTube video to "{cast.name}"...')
        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                quick_play.quick_play(cast, "youtube", {"media_id": video_id, "enqueue": enqueue})
                time.sleep(2)
                print("Cast command sent.")
                return 0
            except Exception as exc:
                last_error = exc
                if attempt >= 3:
                    break
                print(f"YouTube cast attempt {attempt} failed: {exc}")
                print("Waiting a few seconds and retrying; some TVs need the YouTube app to wake up first...")
                time.sleep(7)
                try:
                    cast.wait(timeout=args.socket_timeout)
                except Exception:
                    pass

        raise RuntimeError(f"YouTube cast failed after 3 attempts: {last_error}")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep Spotify web-auth redirects visible so expired-cookie errors are useful."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def spotify_web_cookie_header(args: argparse.Namespace) -> str:
    sp_dc = str(getattr(args, "spotify_sp_dc", None) or os.environ.get("SPOTIFY_SP_DC") or os.environ.get("SP_DC") or "").strip()
    sp_key = str(getattr(args, "spotify_sp_key", None) or os.environ.get("SPOTIFY_SP_KEY") or os.environ.get("SP_KEY") or "").strip()
    if not sp_dc or not sp_key:
        raise RuntimeError(
            "Missing Spotify Cast-wake credentials: SPOTIFY_SP_DC and SPOTIFY_SP_KEY. "
            "Add the open.spotify.com sp_dc/sp_key browser cookies to .env to wake idle Google Cast Spotify targets."
        )
    return f"sp_dc={sp_dc}; sp_key={sp_key}"


def has_spotify_web_cookies(args: argparse.Namespace) -> bool:
    try:
        spotify_web_cookie_header(args)
        return True
    except RuntimeError:
        return False


def spotify_web_headers(args: argparse.Namespace) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Cookie": spotify_web_cookie_header(args),
    }


def spotify_web_json(
    url: str,
    *,
    args: argparse.Namespace,
    params: Optional[dict[str, Any]] = None,
    timeout: float = 15.0,
    no_redirect: bool = False,
) -> dict[str, Any]:
    if params:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        if query:
            url = f"{url}?{query}"
    req = urllib.request.Request(url, headers=spotify_web_headers(args), method="GET")
    opener = urllib.request.build_opener(NoRedirectHandler()) if no_redirect else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            payload = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        location = exc.headers.get("Location", "") if exc.headers else ""
        location_query = parse_qs(urlparse(location).query) if location else {}
        if exc.code in {301, 302, 303, 307, 308} and location_query.get("_authfailed", ["0"])[0] == "1":
            raise RuntimeError("Spotify web cookies were rejected or expired; refresh SPOTIFY_SP_DC/SPOTIFY_SP_KEY.") from exc
        detail = body or location or exc.reason
        raise RuntimeError(f"Spotify web request failed ({exc.code}): {detail}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Spotify web request returned non-JSON content from {url}") from exc

    if isinstance(payload, dict):
        return payload
    return {"value": payload}


def spotify_latest_totp_secret() -> tuple[int, tuple[int, ...]]:
    try:
        req = urllib.request.Request(SPOTIFY_TOTP_SECRET_DICT_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError("secret dictionary was empty")
        version_text = max((str(key) for key in payload.keys()), key=lambda value: int(value))
        secret = payload.get(version_text)
        if not isinstance(secret, list) or not all(isinstance(item, int) for item in secret):
            raise RuntimeError(f"secret for version {version_text} was not an integer list")
        return int(version_text), tuple(int(item) for item in secret)
    except Exception:
        return SPOTIFY_FALLBACK_TOTP_SECRET_VERSION, SPOTIFY_FALLBACK_TOTP_SECRET


def spotify_totp_at(
    server_time: int,
    *,
    cipher_secret: tuple[int, ...] = SPOTIFY_CAST_TOTP_CIPHER_BASE,
    digits: int = 6,
    interval: int = 30,
) -> str:
    """Generate the Spotify web-player TOTP without adding pyotp as a dependency."""
    cipher_bytes = [value ^ (index % 33 + 9) for index, value in enumerate(cipher_secret)]
    secret_hex_source = "".join(str(value) for value in cipher_bytes).encode("utf-8")
    secret_hex = secret_hex_source.hex()
    secret_bytes = bytes.fromhex(secret_hex)
    counter = int(server_time) // interval
    digest = hmac.new(secret_bytes, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


def spotify_browser_access_token(args: argparse.Namespace) -> tuple[str, int]:
    try:
        server_payload = spotify_web_json(SPOTIFY_WEB_SERVER_TIME_URL, args=args, timeout=8.0)
        server_time = int(float(server_payload["serverTime"]))
    except Exception:
        # Spotify has changed/removed this endpoint at times; local clock is
        # sufficient for the current /api/token TOTP flow if the Mac clock is sane.
        server_time = int(time.time())

    version, cipher_secret = spotify_latest_totp_secret()
    totp = spotify_totp_at(server_time, cipher_secret=cipher_secret)
    token_error: Optional[Exception] = None
    for url, params in (
        (
            SPOTIFY_WEB_ACCESS_TOKEN_URL,
            {
                "reason": "init",
                "productType": "web-player",
                "totp": totp,
                "totpServer": totp,
                "totpVer": version,
            },
        ),
        (
            SPOTIFY_WEB_ACCESS_TOKEN_URL,
            {
                "reason": "init",
                "productType": "web-player",
                "totp": totp,
                "totpServer": totp,
                "totpVer": version,
                "ts": server_time,
            },
        ),
        (
            SPOTIFY_LEGACY_WEB_ACCESS_TOKEN_URL,
            {
                "reason": "transport",
                "productType": "web-player",
                "totp": spotify_totp_at(server_time),
                "totpServer": spotify_totp_at(server_time),
                "totpVer": 5,
                "sTime": server_time,
                "cTime": server_time,
            },
        ),
    ):
        try:
            token_payload = spotify_web_json(url, args=args, params=params, timeout=15.0, no_redirect=True)
            break
        except Exception as exc:
            token_error = exc
    else:
        raise RuntimeError(f"Spotify web token request failed; refresh SPOTIFY_SP_DC/SPOTIFY_SP_KEY. Last error: {token_error}") from token_error

    token = str(token_payload.get("accessToken") or "").strip()
    if not token:
        raise RuntimeError("Spotify web token response did not include accessToken; refresh SPOTIFY_SP_DC/SPOTIFY_SP_KEY.")

    # Do not spend an extra Web API request validating the token here; Spotify
    # rate-limits /me aggressively and the Cast device-auth step will validate it.
    expires_ms = token_payload.get("accessTokenExpirationTimestampMs")
    expires_at = 0
    try:
        expires_at = int(expires_ms) // 1000 if expires_ms is not None else 0
    except (TypeError, ValueError):
        expires_at = 0
    return token, max(0, expires_at - int(time.time()))


def spotify_cast_device_auth_blob(access_token: str, client_id: str, device_id: str, *, timeout: float) -> str:
    request_body = json.dumps({"clientId": client_id, "deviceId": device_id}).encode("utf-8")
    req = urllib.request.Request(SPOTIFY_DEVICE_AUTH_URL, data=request_body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "text/plain;charset=UTF-8")
    req.add_header("Authority", "spclient.wg.spotify.com")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Spotify Cast device-auth failed ({exc.code}): {body or exc.reason}") from exc
    blob = str(payload.get("accessToken") or "").strip()
    if not blob:
        raise RuntimeError(f"Spotify Cast device-auth did not return accessToken: {payload}")
    return blob


def cast_friendly_name(cast: Any) -> str:
    cast_info = getattr(cast, "cast_info", None)
    return str(getattr(cast_info, "friendly_name", None) or getattr(cast, "name", None) or "Spotify Cast")


def spotify_cast_device_id_for_name(name: str) -> str:
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def make_spotify_cast_controller_class(base_controller: Any):
    class _SpotifyCastLaunchController(base_controller):
        def __init__(self, cast: Any, access_token: str, expires: int):
            super().__init__(SPOTIFY_CAST_NAMESPACE, SPOTIFY_CAST_APP_ID)
            self.cast = cast
            self.access_token = access_token
            self.expires = expires
            self.device: Optional[str] = None
            self.client: Optional[str] = None
            self.is_launched = False
            self.credential_error = False
            self.error: Optional[str] = None
            self.waiting = threading.Event()

        def spotify_device_id(self) -> str:
            return spotify_cast_device_id_for_name(cast_friendly_name(self.cast))

        def receive_message(self, _message: Any, data: dict[str, Any]) -> bool:
            try:
                message_type = data.get("type")
                if message_type == "getInfoResponse":
                    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                    self.client = str(payload.get("clientID") or "").strip()
                    if not self.client:
                        raise RuntimeError(f"Spotify Cast getInfoResponse did not include clientID: {data}")
                    self.device = self.spotify_device_id()
                    blob = spotify_cast_device_auth_blob(
                        self.access_token,
                        self.client,
                        self.device,
                        timeout=15.0,
                    )
                    self.send_message({"type": "addUser", "payload": {"blob": blob, "tokenType": "accesstoken"}})
                elif message_type == "addUserResponse":
                    self.is_launched = True
                    self.waiting.set()
                elif message_type == "addUserError":
                    self.credential_error = True
                    self.error = f"Spotify Cast addUserError: {data.get('payload') or data}"
                    self.waiting.set()
            except Exception as exc:
                self.error = str(exc)
                self.waiting.set()
            return True

        def launch_app(self, timeout: float) -> None:
            def callback(*_: Any) -> None:
                self.device = self.spotify_device_id()
                self.send_message(
                    {
                        "type": "getInfo",
                        "payload": {
                            "remoteName": cast_friendly_name(self.cast),
                            "deviceID": self.device,
                            "deviceAPI_isGroup": False,
                        },
                    }
                )

            self.device = self.spotify_device_id()
            self.credential_error = False
            self.error = None
            self.is_launched = False
            self.waiting.clear()
            self.launch(callback_function=callback)
            self.waiting.wait(max(1.0, timeout))
            if self.error:
                raise RuntimeError(self.error)
            if not self.is_launched:
                raise RuntimeError("Timed out waiting for Spotify Cast app authorization.")

    return _SpotifyCastLaunchController


def launch_spotify_cast_app(args: argparse.Namespace, web_access_token: str, expires: int) -> tuple[str, str]:
    from pychromecast.controllers import BaseController  # type: ignore

    timeout = float(getattr(args, "spotify_cast_wake_timeout", 25.0) or 25.0)
    controller_cls = make_spotify_cast_controller_class(BaseController)
    with connected_cast(args) as (_pychromecast, cast):
        controller = controller_cls(cast, web_access_token, expires)
        cast.register_handler(controller)
        controller.launch_app(timeout=timeout)
        device_id = controller.device or controller.spotify_device_id()
        friendly_name = cast_friendly_name(cast)
        print(f'Launched Spotify Cast app on "{friendly_name}" ({device_id}).')
        return device_id, friendly_name


def should_wake_spotify_cast(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "no_spotify_cast_wake", False)):
        return False
    if str(getattr(args, "spotify_device_id", None) or "").strip():
        return False
    apply_target_defaults(args)
    requested_name = str(getattr(args, "spotify_device_name", None) or "").strip()
    if not requested_name:
        return True
    requested_key = normalize_match_key(requested_name)
    cast_keys = [normalize_match_key(str(getattr(args, "name", "") or "")), normalize_match_key(str(getattr(args, "device", "") or ""))]
    return any(key and (requested_key == key or requested_key in key or key in requested_key) for key in cast_keys)


def wait_for_spotify_cast_device(
    args: argparse.Namespace,
    access_token: str,
    *,
    device_id: str,
    friendly_name: str,
) -> dict[str, Any]:
    timeout = max(5.0, float(getattr(args, "spotify_cast_wake_timeout", 25.0) or 25.0))
    deadline = time.monotonic() + timeout
    last_devices: list[dict[str, Any]] = []
    while True:
        last_devices = spotify_devices(access_token, timeout=args.socket_timeout)
        for item in last_devices:
            if str(item.get("id") or "").strip() == device_id:
                return item
        matched = match_spotify_device_by_candidates(args, last_devices)
        if matched is not None:
            return matched
        friendly_key = normalize_match_key(friendly_name)
        for item in last_devices:
            device_key = normalize_match_key(str(item.get("name") or ""))
            if friendly_key and (friendly_key == device_key or friendly_key in device_key or device_key in friendly_key):
                return item
        if time.monotonic() >= deadline:
            break
        time.sleep(SPOTIFY_CAST_POLL_INTERVAL_SECONDS)

    names = ", ".join(str(item.get("name") or "unknown") for item in last_devices) or "none"
    raise RuntimeError(
        f'Launched Spotify on "{friendly_name}", but Spotify Web API did not list device id {device_id}. '
        f"Visible devices: {names}. Make sure SPOTIFY_SP_DC/SPOTIFY_SP_KEY belong to the same Spotify account as SPOTIFY_REFRESH_TOKEN."
    )


def wake_spotify_cast_and_select(args: argparse.Namespace, access_token: str, *, previous_error: Exception) -> dict[str, Any]:
    if not should_wake_spotify_cast(args):
        raise previous_error
    if not has_spotify_web_cookies(args):
        raise RuntimeError(
            f"{previous_error} To wake idle Google Cast Spotify targets automatically, add SPOTIFY_SP_DC and SPOTIFY_SP_KEY "
            "from open.spotify.com to the local .env file."
        ) from previous_error

    print("No matching Spotify Connect target is visible; attempting Spotify Cast wake-up...")
    web_token, expires = spotify_browser_access_token(args)
    device_id, friendly_name = launch_spotify_cast_app(args, web_token, expires)
    selected = wait_for_spotify_cast_device(args, access_token, device_id=device_id, friendly_name=friendly_name)
    print(f'Woke Spotify Connect target: "{selected.get("name") or friendly_name}" ({selected.get("id") or device_id}).')
    return selected


def add_spotify_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spotify-client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"), help="Spotify app client ID (or env SPOTIFY_CLIENT_ID)")
    parser.add_argument("--spotify-client-secret", default=os.environ.get("SPOTIFY_CLIENT_SECRET"), help="Spotify app client secret (or env SPOTIFY_CLIENT_SECRET)")
    parser.add_argument("--spotify-refresh-token", default=os.environ.get("SPOTIFY_REFRESH_TOKEN"), help="Spotify OAuth refresh token (or env SPOTIFY_REFRESH_TOKEN)")
    parser.add_argument("--spotify-sp-dc", default=os.environ.get("SPOTIFY_SP_DC") or os.environ.get("SP_DC"), help="Optional open.spotify.com sp_dc cookie used to wake idle Google Cast Spotify targets")
    parser.add_argument("--spotify-sp-key", default=os.environ.get("SPOTIFY_SP_KEY") or os.environ.get("SP_KEY"), help="Optional open.spotify.com sp_key cookie used to wake idle Google Cast Spotify targets")
    parser.add_argument("--no-spotify-cast-wake", action="store_true", help="Disable automatic Spotify Cast wake-up fallback")
    parser.add_argument("--spotify-cast-wake-timeout", type=float, default=25.0, help="Seconds to wait for a woken Cast target to appear in Spotify Connect")


def spotify_credentials(args: argparse.Namespace) -> tuple[str, str, str]:
    client_id = (args.spotify_client_id or "").strip()
    client_secret = (args.spotify_client_secret or "").strip()
    refresh_token = (args.spotify_refresh_token or "").strip()
    missing = []
    if not client_id:
        missing.append("SPOTIFY_CLIENT_ID")
    if not client_secret:
        missing.append("SPOTIFY_CLIENT_SECRET")
    if not refresh_token:
        missing.append("SPOTIFY_REFRESH_TOKEN")
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(
            "Missing Spotify credentials: "
            f"{missing_text}. Set these environment variables (or pass command flags) "
            "for OAuth refresh-token playback control."
        )
    return client_id, client_secret, refresh_token


def _http_json(
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if not body:
                return {}
            try:
                value = json.loads(body)
            except json.JSONDecodeError:
                return {"body": body}
            if isinstance(value, dict):
                return value
            return {"value": value}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                error = parsed.get("error")
                if isinstance(error, dict):
                    message = error.get("message")
                    status = error.get("status")
                    if message and status:
                        detail = f"{status}: {message}"
                    elif message:
                        detail = str(message)
                elif error:
                    detail = str(error)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"HTTP {method.upper()} {url} failed ({exc.code}): {detail}") from exc


def spotify_access_token(args: argparse.Namespace) -> str:
    client_id, client_secret, refresh_token = spotify_credentials(args)
    body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode("utf-8")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(SPOTIFY_TOKEN_URL, data=body, method="POST")
    req.add_header("Authorization", f"Basic {basic}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Spotify token refresh failed ({exc.code}): {body_text}") from exc

    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError(f"Spotify token refresh did not return access_token: {payload}")
    return token


def spotify_api(
    method: str,
    path: str,
    *,
    access_token: str,
    params: Optional[dict[str, Any]] = None,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    url = f"{SPOTIFY_API_BASE}{path}"
    if params:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        if query:
            url = f"{url}?{query}"
    return _http_json(
        method,
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        payload=payload,
        timeout=timeout,
    )


def spotify_devices(access_token: str, *, timeout: float) -> list[dict[str, Any]]:
    payload = spotify_api("GET", "/me/player/devices", access_token=access_token, timeout=timeout)
    devices = payload.get("devices")
    if isinstance(devices, list):
        return [item for item in devices if isinstance(item, dict)]
    return []


def normalize_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def match_spotify_device_by_candidates(args: argparse.Namespace, devices: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    requested_id = (getattr(args, "spotify_device_id", None) or "").strip()
    if requested_id:
        for item in devices:
            if str(item.get("id") or "").strip() == requested_id:
                return item
        return None

    candidates = [
        str(getattr(args, "spotify_device_name", "") or "").strip(),
        str(getattr(args, "name", "") or "").strip(),
        str(getattr(args, "device", "") or "").strip(),
    ]
    candidates = [item for item in candidates if item]

    for candidate in candidates:
        key = normalize_match_key(candidate)
        for item in devices:
            if normalize_match_key(str(item.get("name") or "")) == key:
                return item

    for candidate in candidates:
        key = normalize_match_key(candidate)
        for item in devices:
            device_key = normalize_match_key(str(item.get("name") or ""))
            if key and (key in device_key or device_key in key):
                return item

    return None


def select_spotify_device(args: argparse.Namespace, devices: list[dict[str, Any]]) -> dict[str, Any]:
    if not devices:
        raise RuntimeError(
            "No Spotify Connect devices found. Open Spotify on your phone/desktop and keep the target speaker awake, then retry."
        )

    requested_id = (getattr(args, "spotify_device_id", None) or "").strip()
    matched = match_spotify_device_by_candidates(args, devices)
    if matched is not None:
        return matched
    if requested_id:
        raise RuntimeError(f"Spotify device id not found: {requested_id}")

    active = next((item for item in devices if bool(item.get("is_active"))), None)
    if active is not None:
        return active

    unrestricted = [item for item in devices if not bool(item.get("is_restricted"))]
    if len(unrestricted) == 1:
        return unrestricted[0]

    names = ", ".join(str(item.get("name") or "unknown") for item in devices)
    raise RuntimeError(
        "Could not match a Spotify Connect device to this Cast target. "
        f"Available Spotify devices: {names}. "
        "Pass --spotify-device-name or --spotify-device-id explicitly."
    )


def normalize_spotify_uri(value: str) -> Optional[str]:
    text = value.strip()
    if not text:
        return None
    if text.startswith("spotify:"):
        return text
    match = SPOTIFY_LINK_RE.match(text)
    if match:
        kind, identifier = match.group(1), match.group(2)
        return f"spotify:{kind}:{identifier}"
    return None


def resolve_spotify_item(args: argparse.Namespace, access_token: str) -> tuple[Optional[dict[str, Any]], str]:
    query = " ".join(getattr(args, "query", []) or []).strip()
    uri = normalize_spotify_uri(getattr(args, "uri", "") or "")

    if not uri and query:
        uri = normalize_spotify_uri(query)

    if uri:
        if uri.startswith(("spotify:track:", "spotify:episode:")):
            return {"uris": [uri]}, f"item {uri}"
        if uri.startswith(("spotify:album:", "spotify:artist:", "spotify:playlist:")):
            return {"context_uri": uri}, f"context {uri}"
        raise RuntimeError(f"Unsupported Spotify URI type: {uri}")

    if args.resume and not query:
        return None, "resume current playback"

    if not query:
        raise RuntimeError("Provide a Spotify query, Spotify URI/URL, or use --resume")

    search_type = args.spotify_type
    types_param = "track,album,playlist,artist" if search_type == "any" else search_type
    params = {"q": query, "type": types_param, "limit": 1, "market": args.market}
    results = spotify_api("GET", "/search", access_token=access_token, params=params, timeout=20.0)

    ordered_types = ["track", "album", "playlist", "artist"] if search_type == "any" else [search_type]
    for item_type in ordered_types:
        bucket = results.get(f"{item_type}s")
        items = bucket.get("items") if isinstance(bucket, dict) else None
        if isinstance(items, list) and items:
            item = items[0] if isinstance(items[0], dict) else {}
            uri_value = str(item.get("uri") or "").strip()
            name = str(item.get("name") or uri_value or query).strip()
            if not uri_value:
                continue
            if item_type == "track":
                return {"uris": [uri_value]}, f'track "{name}"'
            return {"context_uri": uri_value}, f'{item_type} "{name}"'

    raise RuntimeError(f'No Spotify {search_type} results found for "{query}"')


def spotify_transfer_to_device(access_token: str, device_id: str, *, timeout: float) -> None:
    spotify_api(
        "PUT",
        "/me/player",
        access_token=access_token,
        payload={"device_ids": [device_id], "play": False},
        timeout=timeout,
    )


def selected_spotify_device(args: argparse.Namespace, access_token: str, *, wake_cast: bool = False) -> dict[str, Any]:
    apply_target_defaults(args)
    devices = spotify_devices(access_token, timeout=args.socket_timeout)

    # For Cast-targeted playback, do not silently fall back to an unrelated
    # active Spotify device (for example a TV in another room). If the requested
    # Cast target is not already visible as Spotify Connect, wake that target.
    if wake_cast and should_wake_spotify_cast(args):
        selected = match_spotify_device_by_candidates(args, devices)
        if selected is None:
            if devices:
                names = ", ".join(str(item.get("name") or "unknown") for item in devices)
                previous_error = RuntimeError(f"No Spotify Connect device matched this Cast target. Visible devices: {names}.")
            else:
                previous_error = RuntimeError(
                    "No Spotify Connect devices found. Open Spotify on your phone/desktop and keep the target speaker awake, then retry."
                )
            selected = wake_spotify_cast_and_select(args, access_token, previous_error=previous_error)
    else:
        try:
            selected = select_spotify_device(args, devices)
        except RuntimeError as exc:
            if not wake_cast:
                raise
            selected = wake_spotify_cast_and_select(args, access_token, previous_error=exc)

    device_id = str(selected.get("id") or "").strip()
    if not device_id:
        raise RuntimeError(f"Selected Spotify device has no id: {selected}")
    return selected


def spotify_device_query(selected: dict[str, Any]) -> dict[str, str]:
    return {"device_id": str(selected.get("id") or "").strip()}


def spotify_current_playback(access_token: str, *, timeout: float) -> dict[str, Any]:
    return spotify_api("GET", "/me/player", access_token=access_token, timeout=timeout)


def format_duration_ms(value: Any) -> str:
    try:
        total_seconds = max(0, int(value) // 1000)
    except (TypeError, ValueError):
        return "?:??"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def describe_spotify_item(item: Any) -> str:
    if not isinstance(item, dict):
        return "unknown item"
    item_type = str(item.get("type") or "item")
    name = str(item.get("name") or item.get("uri") or "unknown")
    detail = ""
    if item_type == "track":
        artists = item.get("artists")
        if isinstance(artists, list):
            names = [str(artist.get("name")) for artist in artists if isinstance(artist, dict) and artist.get("name")]
            if names:
                detail = " — " + ", ".join(names)
    elif item_type == "episode":
        show = item.get("show")
        if isinstance(show, dict) and show.get("name"):
            detail = " — " + str(show.get("name"))
    elif item.get("publisher"):
        detail = " — " + str(item.get("publisher"))
    duration = format_duration_ms(item.get("duration_ms"))
    uri = str(item.get("uri") or "")
    suffix = f" [{duration}]" if duration != "?:??" else ""
    if uri:
        suffix += f" ({uri})"
    return f'{item_type}: "{name}"{detail}{suffix}'


def parse_position_ms(value: str) -> int:
    text = value.strip().lower()
    if not text:
        raise RuntimeError("Seek position cannot be empty")
    if text.endswith("ms"):
        return max(0, int(float(text[:-2].strip())))
    if text.endswith("s"):
        return max(0, int(float(text[:-1].strip()) * 1000))
    if text.endswith("m"):
        return max(0, int(float(text[:-1].strip()) * 60_000))
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in {2, 3}:
            raise RuntimeError(f"Invalid timestamp: {value}")
        numbers = [float(part) for part in parts]
        if len(numbers) == 2:
            minutes, seconds = numbers
            total_seconds = minutes * 60 + seconds
        else:
            hours, minutes, seconds = numbers
            total_seconds = hours * 3600 + minutes * 60 + seconds
        return max(0, int(total_seconds * 1000))
    # Bare numbers are treated as seconds for human-friendly CLI use.
    return max(0, int(float(text) * 1000))


def resolve_spotify_queue_item(args: argparse.Namespace, access_token: str) -> tuple[str, str]:
    query = " ".join(getattr(args, "query", []) or []).strip()
    uri = normalize_spotify_uri(getattr(args, "uri", "") or "")
    if not uri and query:
        uri = normalize_spotify_uri(query)
    if uri:
        if uri.startswith(("spotify:track:", "spotify:episode:")):
            return uri, uri
        raise RuntimeError(f"Only Spotify track or episode URIs can be queued: {uri}")
    if not query:
        raise RuntimeError("Provide a Spotify track/episode query or URI/URL to add to the queue")

    item_type = getattr(args, "spotify_queue_type", "track")
    if item_type not in {"track", "episode"}:
        raise RuntimeError("Queue item type must be track or episode")
    params = {"q": query, "type": item_type, "limit": 1, "market": getattr(args, "market", None)}
    results = spotify_api("GET", "/search", access_token=access_token, params=params, timeout=20.0)
    bucket_name = "episodes" if item_type == "episode" else "tracks"
    bucket = results.get(bucket_name)
    items = bucket.get("items") if isinstance(bucket, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError(f'No Spotify {item_type} results found for "{query}"')
    item = items[0] if isinstance(items[0], dict) else {}
    uri_value = str(item.get("uri") or "").strip()
    if not uri_value:
        raise RuntimeError(f"Spotify search result had no URI: {item}")
    return uri_value, describe_spotify_item(item)


def handle_spotify_devices(args: argparse.Namespace) -> int:
    apply_target_defaults(args)
    access_token = spotify_access_token(args)
    devices = spotify_devices(access_token, timeout=args.socket_timeout)

    if not devices:
        print("No Spotify Connect devices found.")
        return 0

    print("Spotify Connect devices:")
    for item in devices:
        marker = "*" if item.get("is_active") else " "
        print(
            f"{marker} {item.get('name')}"
            f"  id={item.get('id')}"
            f"  type={item.get('type')}"
            f"  restricted={item.get('is_restricted')}"
            f"  volume={item.get('volume_percent')}"
        )
    return 0


def handle_spotify_play(args: argparse.Namespace) -> int:
    apply_target_defaults(args)
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token, wake_cast=True)
    device_id = str(selected.get("id") or "").strip()
    device_name = str(selected.get("name") or "unknown")

    print(f'Using Spotify Connect device: "{device_name}" ({device_id})')
    spotify_transfer_to_device(access_token, device_id, timeout=args.socket_timeout)

    play_payload, detail = resolve_spotify_item(args, access_token)
    spotify_api(
        "PUT",
        "/me/player/play",
        access_token=access_token,
        params={"device_id": device_id},
        payload=play_payload if play_payload is not None else {},
        timeout=max(20.0, args.socket_timeout),
    )
    print(f"Spotify play command sent ({detail}).")
    return 0


def handle_spotify_pause(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    spotify_api(
        "PUT",
        "/me/player/pause",
        access_token=access_token,
        params=spotify_device_query(selected),
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify pause command sent to "{device_name}".')
    return 0


def handle_spotify_next(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    spotify_api(
        "POST",
        "/me/player/next",
        access_token=access_token,
        params=spotify_device_query(selected),
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify next-track command sent to "{device_name}".')
    return 0


def handle_spotify_previous(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    spotify_api(
        "POST",
        "/me/player/previous",
        access_token=access_token,
        params=spotify_device_query(selected),
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify previous-track command sent to "{device_name}".')
    return 0


def handle_spotify_volume(args: argparse.Namespace) -> int:
    volume = int(args.volume_percent)
    if volume < 0 or volume > 100:
        raise RuntimeError("Spotify volume must be between 0 and 100")
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    params = spotify_device_query(selected)
    params["volume_percent"] = str(volume)
    spotify_api(
        "PUT",
        "/me/player/volume",
        access_token=access_token,
        params=params,
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify volume set to {volume}% on "{device_name}".')
    return 0


def handle_spotify_queue_add(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    uri, detail = resolve_spotify_queue_item(args, access_token)
    params = spotify_device_query(selected)
    params["uri"] = uri
    spotify_api(
        "POST",
        "/me/player/queue",
        access_token=access_token,
        params=params,
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Added Spotify queue item on "{device_name}": {detail}')
    return 0


def handle_spotify_queue(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    queue_payload = spotify_api("GET", "/me/player/queue", access_token=access_token, timeout=args.socket_timeout)
    current = queue_payload.get("currently_playing")
    queue = queue_payload.get("queue")
    print("Spotify current queue:")
    if current:
        print(f"  now: {describe_spotify_item(current)}")
    else:
        print("  now: nothing currently playing")
    if not isinstance(queue, list) or not queue:
        print("  queue: empty")
        return 0
    limit = max(1, int(getattr(args, "limit", 20) or 20))
    for index, item in enumerate(queue[:limit], start=1):
        print(f"  {index}. {describe_spotify_item(item)}")
    if len(queue) > limit:
        print(f"  ... {len(queue) - limit} more item(s)")
    return 0


def handle_spotify_seek(args: argparse.Namespace) -> int:
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    if getattr(args, "position_ms", None) is not None:
        position_ms = int(args.position_ms)
    elif getattr(args, "position", None) is not None:
        position_ms = parse_position_ms(str(args.position))
    else:
        raise RuntimeError("Provide a seek position, e.g. 90s, 1:30, or --position-ms 90000")
    if position_ms < 0:
        raise RuntimeError("Seek position must be zero or greater")
    params = spotify_device_query(selected)
    params["position_ms"] = str(position_ms)
    spotify_api(
        "PUT",
        "/me/player/seek",
        access_token=access_token,
        params=params,
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify seek command sent to "{device_name}" ({format_duration_ms(position_ms)}).')
    return 0


def handle_spotify_shuffle(args: argparse.Namespace) -> int:
    requested = str(getattr(args, "state", "toggle") or "toggle")
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    if requested == "toggle":
        current = spotify_current_playback(access_token, timeout=args.socket_timeout)
        shuffle_state = bool(current.get("shuffle_state"))
        enabled = not shuffle_state
    else:
        enabled = requested == "on"
    params = spotify_device_query(selected)
    params["state"] = "true" if enabled else "false"
    spotify_api(
        "PUT",
        "/me/player/shuffle",
        access_token=access_token,
        params=params,
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify shuffle {"enabled" if enabled else "disabled"} on "{device_name}".')
    return 0


def handle_spotify_repeat(args: argparse.Namespace) -> int:
    requested = str(getattr(args, "state", "toggle") or "toggle")
    access_token = spotify_access_token(args)
    selected = selected_spotify_device(args, access_token)
    device_name = str(selected.get("name") or "unknown")
    if requested == "toggle":
        current = spotify_current_playback(access_token, timeout=args.socket_timeout)
        current_repeat = str(current.get("repeat_state") or "off")
        repeat_state = "context" if current_repeat == "off" else "off"
    else:
        repeat_state = requested
    if repeat_state not in {"track", "context", "off"}:
        raise RuntimeError("Repeat state must be off, context, track, or toggle")
    params = spotify_device_query(selected)
    params["state"] = repeat_state
    spotify_api(
        "PUT",
        "/me/player/repeat",
        access_token=access_token,
        params=params,
        payload=None,
        timeout=args.socket_timeout,
    )
    print(f'Spotify repeat set to {repeat_state} on "{device_name}".')
    return 0


def handle_devices(args: argparse.Namespace) -> int:
    print("Configured Cast targets:")
    for target in iter_targets():
        print(f"  {target.alias}: {target.name} ({target.host}) [{target.cast_type}]")
        print(f"    location: {target.location}")
        print(f"    {target.description}")
    return 0


def handle_status(args: argparse.Namespace) -> int:
    with connected_cast(args) as (_pychromecast, cast):
        print_cast_summary(cast)
    return 0


def handle_volume(args: argparse.Namespace) -> int:
    level = parse_volume(args.level)
    with connected_cast(args) as (_pychromecast, cast):
        new_level = cast.set_volume(level)
        print(f"Set volume to {new_level:.0%}.")
    return 0


def handle_mute(args: argparse.Namespace, state: Optional[str] = None) -> int:
    requested = state or args.state
    with connected_cast(args) as (_pychromecast, cast):
        current = bool(getattr(cast.status, "volume_muted", False))
        muted = not current if requested == "toggle" else requested == "on"
        cast.set_volume_muted(muted)
        print("Muted." if muted else "Unmuted.")
    return 0


def handle_stop(args: argparse.Namespace, quit_app: bool = False) -> int:
    should_quit_app = quit_app or bool(getattr(args, "quit_app", True))
    with connected_cast(args) as (_pychromecast, cast):
        if should_quit_app:
            cast.quit_app()
            print("Quit current Cast app.")
        else:
            cast.media_controller.stop()
            print("Stop command sent to media controller.")
    return 0


def _raise_launch_failure(cast: Any, hint: str = "") -> None:
    receiver = cast.socket_client.receiver_controller
    failure = getattr(receiver, "launch_failure", None)
    if failure is None:
        return

    reason = getattr(failure, "reason", None) or "unknown"
    base = f"Cast app launch failed: {reason}."
    if reason == "NOT_ALLOWED":
        extra = " Target refused app launch (common when targeting a stereo-pair child speaker). Use the group/pair endpoint instead."
    else:
        extra = ""
    raise RuntimeError((base + extra + (f" {hint}" if hint else "")).strip())


def handle_play_url(args: argparse.Namespace) -> int:
    with connected_cast(args) as (_pychromecast, cast):
        print(f'Casting URL to "{cast.name}"...')
        cast.media_controller.play_media(args.url, args.content_type)

        # Wait for the media controller to become active, then confirm a real
        # media session exists (content_id/app_id). Some non-castable targets
        # acknowledge volume/status but reject app launch with NOT_ALLOWED.
        cast.media_controller.block_until_active(timeout=args.socket_timeout)

        deadline = time.time() + max(1.0, args.socket_timeout)
        while time.time() < deadline:
            _raise_launch_failure(cast)
            cast.socket_client.receiver_controller.update_status()
            cast.media_controller.update_status()
            media_status = cast.media_controller.status
            if getattr(media_status, "content_id", None):
                print("Media command sent.")
                return 0
            time.sleep(0.25)

        _raise_launch_failure(cast, hint="No active media session appeared before timeout.")
        raise RuntimeError(
            "Cast command sent but no media session became active. "
            f"app_id={getattr(cast.status, 'app_id', None)} content_id={getattr(cast.media_controller.status, 'content_id', None)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    devices_parser = subparsers.add_parser("devices", help="List configured Cast targets")
    devices_parser.set_defaults(func=handle_devices)

    status_parser = subparsers.add_parser("status", help="Show TV/Cast status")
    status_parser.set_defaults(func=handle_status)

    volume_parser = subparsers.add_parser("volume", help="Set Cast volume, e.g. 35 or 0.35")
    volume_parser.add_argument("level")
    volume_parser.set_defaults(func=handle_volume)

    mute_parser = subparsers.add_parser("mute", help="Mute, unmute, or toggle mute")
    mute_parser.add_argument("state", nargs="?", default="on", choices=["on", "off", "toggle"])
    mute_parser.set_defaults(func=handle_mute)

    unmute_parser = subparsers.add_parser("unmute", help="Unmute")
    unmute_parser.set_defaults(func=lambda args: handle_mute(args, state="off"))

    stop_parser = subparsers.add_parser("stop", help="Stop current casted media and quit the Cast app by default")
    stop_parser.add_argument("--quit-app", dest="quit_app", action="store_true", default=True, help="Quit the current Cast app after stopping media; default")
    stop_parser.add_argument("--media-only", dest="quit_app", action="store_false", help="Only stop media playback; leave the Cast app open")
    stop_parser.set_defaults(func=handle_stop)

    quit_parser = subparsers.add_parser("quit-app", help="Quit the current Cast app")
    quit_parser.set_defaults(func=lambda args: handle_stop(args, quit_app=True))

    play_url_parser = subparsers.add_parser("play-url", help="Cast a direct media URL")
    play_url_parser.add_argument("url")
    play_url_parser.add_argument("--type", dest="content_type", default="video/mp4", help="MIME type, e.g. video/mp4 or audio/mp3")
    play_url_parser.set_defaults(func=handle_play_url)

    youtube_parser = subparsers.add_parser("youtube", aliases=["yt"], help="Cast a YouTube video ID/URL or search query")
    youtube_parser.add_argument("query", nargs="+", help="Video ID, URL, or search query")
    youtube_parser.add_argument("--enqueue", action="store_true", help="Add to YouTube queue instead of playing now")
    youtube_parser.add_argument("--no-search", action="store_true", help="Require query to be a video URL or ID")
    youtube_parser.set_defaults(
        func=lambda args: cast_youtube(
            args,
            query_or_url=" ".join(args.query),
            enqueue=args.enqueue,
            no_search=args.no_search,
        )
    )

    spotify_devices_parser = subparsers.add_parser("spotify-devices", help="List Spotify Connect devices for your account")
    add_spotify_auth_args(spotify_devices_parser)
    spotify_devices_parser.set_defaults(func=handle_spotify_devices)

    spotify_play_parser = subparsers.add_parser("spotify-play", help="Play Spotify content on a Spotify Connect device")
    add_spotify_auth_args(spotify_play_parser)
    spotify_play_parser.add_argument("query", nargs="*", help="Search query (or Spotify URL/URI)")
    spotify_play_parser.add_argument("--uri", default=None, help="Explicit Spotify URI or open.spotify.com URL")
    spotify_play_parser.add_argument("--resume", action="store_true", help="Resume current playback when no query/uri is provided")
    spotify_play_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_play_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_play_parser.add_argument("--type", dest="spotify_type", choices=["track", "album", "playlist", "artist", "any"], default="track", help="Spotify search type when using query text")
    spotify_play_parser.add_argument("--market", default=None, help="Spotify market code (e.g., CA, US)")
    spotify_play_parser.set_defaults(func=handle_spotify_play)

    spotify_pause_parser = subparsers.add_parser("spotify-pause", help="Pause Spotify playback on a Spotify Connect device")
    add_spotify_auth_args(spotify_pause_parser)
    spotify_pause_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_pause_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_pause_parser.set_defaults(func=handle_spotify_pause)

    spotify_next_parser = subparsers.add_parser("spotify-next", help="Skip to the next Spotify track")
    add_spotify_auth_args(spotify_next_parser)
    spotify_next_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_next_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_next_parser.set_defaults(func=handle_spotify_next)

    spotify_previous_parser = subparsers.add_parser("spotify-previous", aliases=["spotify-prev"], help="Skip to the previous Spotify track")
    add_spotify_auth_args(spotify_previous_parser)
    spotify_previous_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_previous_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_previous_parser.set_defaults(func=handle_spotify_previous)

    spotify_volume_parser = subparsers.add_parser("spotify-volume", help="Set Spotify Connect device volume percent")
    add_spotify_auth_args(spotify_volume_parser)
    spotify_volume_parser.add_argument("volume_percent", type=int, help="Volume percent, 0-100")
    spotify_volume_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_volume_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_volume_parser.set_defaults(func=handle_spotify_volume)

    spotify_queue_add_parser = subparsers.add_parser("spotify-queue-add", aliases=["spotify-add-queue"], help="Add a Spotify track or episode to the playback queue")
    add_spotify_auth_args(spotify_queue_add_parser)
    spotify_queue_add_parser.add_argument("query", nargs="*", help="Track/episode search query (or Spotify URL/URI)")
    spotify_queue_add_parser.add_argument("--uri", default=None, help="Explicit Spotify track/episode URI or open.spotify.com URL")
    spotify_queue_add_parser.add_argument("--type", dest="spotify_queue_type", choices=["track", "episode"], default="track", help="Search type when using query text")
    spotify_queue_add_parser.add_argument("--market", default=None, help="Spotify market code (e.g., CA, US)")
    spotify_queue_add_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_queue_add_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_queue_add_parser.set_defaults(func=handle_spotify_queue_add)

    spotify_queue_parser = subparsers.add_parser("spotify-queue", help="Read the current Spotify playback queue")
    add_spotify_auth_args(spotify_queue_parser)
    spotify_queue_parser.add_argument("--limit", type=int, default=20, help="Maximum queue items to print")
    spotify_queue_parser.set_defaults(func=handle_spotify_queue)

    spotify_seek_parser = subparsers.add_parser("spotify-seek", help="Seek the current Spotify playback to a timestamp")
    add_spotify_auth_args(spotify_seek_parser)
    spotify_seek_parser.add_argument("position", nargs="?", default=None, help="Timestamp, e.g. 90, 90s, 1:30, 1:02:03, or 90000ms")
    spotify_seek_parser.add_argument("--position-ms", type=int, default=None, help="Explicit seek position in milliseconds")
    spotify_seek_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_seek_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_seek_parser.set_defaults(func=handle_spotify_seek)

    spotify_shuffle_parser = subparsers.add_parser("spotify-shuffle", help="Set or toggle Spotify shuffle")
    add_spotify_auth_args(spotify_shuffle_parser)
    spotify_shuffle_parser.add_argument("state", nargs="?", default="toggle", choices=["on", "off", "toggle"], help="Shuffle state; default toggle")
    spotify_shuffle_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_shuffle_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_shuffle_parser.set_defaults(func=handle_spotify_shuffle)

    spotify_repeat_parser = subparsers.add_parser("spotify-repeat", help="Set or toggle Spotify repeat")
    add_spotify_auth_args(spotify_repeat_parser)
    spotify_repeat_parser.add_argument("state", nargs="?", default="toggle", choices=["off", "context", "track", "toggle"], help="Repeat state; default toggle (off <-> context)")
    spotify_repeat_parser.add_argument("--spotify-device-name", default=None, help="Spotify Connect device name override")
    spotify_repeat_parser.add_argument("--spotify-device-id", default=None, help="Spotify Connect device id override")
    spotify_repeat_parser.set_defaults(func=handle_spotify_repeat)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
