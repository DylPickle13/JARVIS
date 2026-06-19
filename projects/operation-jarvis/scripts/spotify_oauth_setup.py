#!/usr/bin/env python3
"""Generate and store a Spotify OAuth refresh token for Operation JARVIS.

This helper:
  1. Loads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from .env files.
  2. Opens Spotify's authorization page in the browser.
  3. Captures the local OAuth callback on http://127.0.0.1:8888/callback.
  4. Exchanges the code for a refresh token.
  5. Writes SPOTIFY_REFRESH_TOKEN back to the selected .env file.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import secrets
import shlex
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

OPERATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = OPERATION_ROOT.parents[1]
DEFAULT_SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            value = shlex.split(value, comments=False, posix=True)[0] if value else ""
        except ValueError:
            value = value.strip('"\'')
        if key:
            values[key] = value
    return values


def env_candidates() -> list[Path]:
    return [OPERATION_ROOT / ".env", PROJECT_ROOT / ".env"]


def load_spotify_env() -> tuple[dict[str, str], Optional[Path]]:
    merged: dict[str, str] = {}
    source_with_credentials: Optional[Path] = None
    for path in env_candidates():
        values = parse_env_file(path)
        if values:
            merged.update(values)
        if values.get("SPOTIFY_CLIENT_ID") and values.get("SPOTIFY_CLIENT_SECRET"):
            source_with_credentials = path
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN"):
        if os.environ.get(key):
            merged[key] = os.environ[key]
    return merged, source_with_credentials


def shell_quote_env(value: str) -> str:
    return json.dumps(value)


def upsert_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={shell_quote_env(value)}"
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        compare = stripped[len("export ") :].strip() if stripped.startswith("export ") else stripped
        if compare.startswith(f"{key}="):
            prefix = "export " if stripped.startswith("export ") else ""
            out.append(prefix + replacement)
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(replacement)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


class CallbackState:
    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.code: Optional[str] = None
        self.error: Optional[str] = None
        self.bad_state: Optional[str] = None
        self.event = threading.Event()


def make_handler(state: CallbackState):
    class SpotifyCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            returned_state = params.get("state", [""])[0]
            if returned_state != state.expected_state:
                state.bad_state = returned_state or "<missing>"
            elif params.get("error"):
                state.error = params.get("error", ["unknown"])[0]
            else:
                state.code = params.get("code", [None])[0]

            ok = bool(state.code) and not state.error and not state.bad_state
            title = "Spotify authorization captured" if ok else "Spotify authorization failed"
            body = (
                "You may close this tab and return to JARVIS."
                if ok
                else "Return to JARVIS for details."
            )
            page = f"""<!doctype html><html><head><title>{html.escape(title)}</title></head>
<body style='font-family: system-ui; margin: 3rem;'>
<h1>{html.escape(title)}</h1><p>{html.escape(body)}</p>
</body></html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            state.event.set()

        def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib signature
            return

    return SpotifyCallbackHandler


def exchange_code_for_refresh_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Spotify token exchange failed ({exc.code}): {detail}") from exc
    refresh_token = str(data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise RuntimeError(f"Spotify token exchange did not return a refresh_token: {data}")
    return refresh_token


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and store SPOTIFY_REFRESH_TOKEN for Operation JARVIS")
    parser.add_argument("--env-file", default=None, help=".env file to update; defaults to the file containing Spotify client credentials")
    parser.add_argument("--host", default="127.0.0.1", help="Local callback host")
    parser.add_argument("--port", type=int, default=8888, help="Local callback port; must match the Spotify app redirect URI")
    parser.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for browser authorization")
    parser.add_argument("--no-open", action="store_true", help="Print the authorization URL but do not open the browser")
    args = parser.parse_args(argv)

    env, source = load_spotify_env()
    client_id = env.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = env.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(
            "Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET. Add them to "
            f"{OPERATION_ROOT / '.env'} or {PROJECT_ROOT / '.env'} first.",
            file=sys.stderr,
        )
        return 2

    env_path = Path(args.env_file).expanduser() if args.env_file else (source or OPERATION_ROOT / ".env")
    if not env_path.is_absolute():
        env_path = OPERATION_ROOT / env_path

    redirect_uri = f"http://{args.host}:{args.port}/callback"
    oauth_state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(DEFAULT_SCOPES),
        "state": oauth_state,
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    callback_state = CallbackState(oauth_state)
    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(callback_state))
    except OSError as exc:
        print(f"Could not start local callback server at {redirect_uri}: {exc}", file=sys.stderr)
        return 3

    thread = threading.Thread(target=server.serve_forever, name="spotify-oauth-callback", daemon=True)
    thread.start()
    try:
        print(f"Listening for Spotify callback at {redirect_uri}", flush=True)
        print("Opening Spotify authorization in your browser...", flush=True)
        if args.no_open or not webbrowser.open(auth_url):
            print("Open this URL manually:", flush=True)
            print(auth_url, flush=True)
        print("Waiting for approval...", flush=True)
        if not callback_state.event.wait(timeout=max(1.0, args.timeout)):
            print("Timed out waiting for Spotify approval.", file=sys.stderr)
            print("If Spotify showed INVALID_CLIENT or INVALID_REDIRECT_URI, add this redirect URI in the Spotify app settings:", file=sys.stderr)
            print(f"  {redirect_uri}", file=sys.stderr)
            return 4
        if callback_state.bad_state:
            print("Callback state mismatch; refusing to exchange token.", file=sys.stderr)
            return 5
        if callback_state.error:
            print(f"Spotify authorization failed: {callback_state.error}", file=sys.stderr)
            return 6
        if not callback_state.code:
            print("Spotify callback did not include an authorization code.", file=sys.stderr)
            return 7

        refresh_token = exchange_code_for_refresh_token(client_id, client_secret, callback_state.code, redirect_uri)
        upsert_env_value(env_path, "SPOTIFY_REFRESH_TOKEN", refresh_token)
        print(f"Stored SPOTIFY_REFRESH_TOKEN in {env_path}")
        print("Token value was not printed. Quite sensible, really.")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.1)


if __name__ == "__main__":
    raise SystemExit(main())
