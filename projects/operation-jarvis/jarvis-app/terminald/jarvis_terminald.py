#!/usr/bin/env python3
"""Authenticated HTTPS snapshot/input bridge for the Apple Watch terminal.

This daemon is intentionally separate from jarvisd. It exposes only the existing
jarvis-mobile/jarvis-ios tmux pane and has no hardware, service, scheduler, or
JARVIS control-plane integration.
"""

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

APP_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = APP_ROOT / "scripts" / "jarvis-mobile-terminal.sh"
TMUX = "/opt/homebrew/bin/tmux"
TMUX_SOCKET = "jarvis-mobile"
TMUX_SESSION = "jarvis-ios"
TMUX_TARGET = "jarvis-ios:"
DEFAULT_PORT = 8792
DEFAULT_CIDRS = "127.0.0.0/8,192.168.0.0/16,100.64.0.0/10"
MAX_INPUT_BYTES = 4096
MAX_BODY_BYTES = 8192
LONG_POLL_SECONDS = 1.5
POLL_INTERVAL_SECONDS = 0.10
MAX_SCROLLBACK_ROWS = 160
SGR_PATTERN = re.compile(r"\x1b\[[0-9:;]*m")
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "JARVIS" / "terminald"
TOKEN_PATH = RUNTIME_DIR / "token"
CERT_PATH = RUNTIME_DIR / "certificate.pem"
KEY_PATH = RUNTIME_DIR / "certificate-key.pem"


class TerminalError(RuntimeError):
    pass


def _secure_write(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, value.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def ensure_runtime_credentials() -> Tuple[str, Path, Path]:
    RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUNTIME_DIR, 0o700)
    if not TOKEN_PATH.exists():
        _secure_write(TOKEN_PATH, secrets.token_hex(32) + "\n")
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if len(token.encode("utf-8")) < 32:
        raise TerminalError("terminal token is invalid")

    if not CERT_PATH.exists() or not KEY_PATH.exists():
        temporary_cert = CERT_PATH.with_suffix(".tmp")
        temporary_key = KEY_PATH.with_suffix(".tmp")
        for path in (temporary_cert, temporary_key):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        subprocess.run(
            [
                "/usr/bin/openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-days",
                "3650",
                "-nodes",
                "-subj",
                "/CN=JARVIS Watch Terminal",
                "-keyout",
                str(temporary_key),
                "-out",
                str(temporary_cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        os.chmod(temporary_cert, 0o600)
        os.chmod(temporary_key, 0o600)
        temporary_cert.replace(CERT_PATH)
        temporary_key.replace(KEY_PATH)
    os.chmod(CERT_PATH, 0o600)
    os.chmod(KEY_PATH, 0o600)
    return token, CERT_PATH, KEY_PATH


def certificate_fingerprint(path: Path) -> str:
    pem = path.read_text(encoding="utf-8")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return hashlib.sha256(der).hexdigest()


def provisioning_code(host: str) -> str:
    token, cert_path, _ = ensure_runtime_credentials()
    clean_host = host.strip()
    if not clean_host or any(character in clean_host for character in "/?#@"):
        raise TerminalError("a valid host or IP is required")
    payload = {
        "certificateSHA256": certificate_fingerprint(cert_path),
        "endpoint": "https://{}:{}".format(clean_host, DEFAULT_PORT),
        "token": token,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class CommandRunner:
    def run(
        self,
        arguments: Sequence[str],
        input_data: Optional[bytes] = None,
        timeout: float = 5,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        return subprocess.run(
            list(arguments),
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            timeout=timeout,
            env=environment,
        )


class TerminalService:
    def __init__(self, runner: Optional[CommandRunner] = None) -> None:
        self.runner = runner or CommandRunner()
        self.lock = threading.Lock()
        self.sequence = 0
        self.last_digest: Optional[str] = None
        self.last_frame: Optional[Dict[str, Any]] = None
        self.processed_request_ids: Dict[str, float] = {}

    @staticmethod
    def tmux_arguments(*arguments: str) -> List[str]:
        return [TMUX, "-L", TMUX_SOCKET] + list(arguments)

    def ensure_session(self) -> None:
        result = self.runner.run(
            [str(BOOTSTRAP), "--ensure-only"],
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise TerminalError("The persistent JARVIS session could not be created.")

    def _capture_locked(self) -> Dict[str, Any]:
        metadata_format = "\t".join(
            [
                "#{pane_width}",
                "#{pane_height}",
                "#{cursor_x}",
                "#{cursor_y}",
                "#{alternate_on}",
                "#{mouse_any_flag}",
                "#{history_size}",
                "#{pane_dead}",
            ]
        )
        metadata = self.runner.run(
            self.tmux_arguments("display-message", "-p", "-t", TMUX_TARGET, metadata_format),
            check=False,
        )
        if metadata.returncode != 0:
            self.ensure_session()
            metadata = self.runner.run(
                self.tmux_arguments("display-message", "-p", "-t", TMUX_TARGET, metadata_format)
            )
        values = metadata.stdout.decode("utf-8", errors="replace").strip().split("\t")
        if len(values) != 8 or values[7] == "1":
            raise TerminalError("The persistent JARVIS pane is unavailable.")
        try:
            columns, rows, cursor_column, cursor_row, alternate, mouse, history, _ = [int(value or "0") for value in values]
        except ValueError as error:
            raise TerminalError("The JARVIS pane metadata was invalid.") from error

        # Preserve the actual tmux grid and its SGR attributes. Pi's thinking,
        # tool calls, token counters, and assistant output are not reconstructed
        # here; they remain ordinary terminal cells captured verbatim. A bounded
        # tail of tmux history lets the Watch Crown move a local, read-only
        # viewport without injecting unreliable mouse sequences into Pi.
        history_start = -min(max(0, history), MAX_SCROLLBACK_ROWS)
        captured = self.runner.run(
            self.tmux_arguments(
                "capture-pane",
                "-p",
                "-e",
                "-N",
                "-S",
                str(history_start),
                "-t",
                TMUX_TARGET,
            )
        ).stdout.decode("utf-8", errors="replace")
        if captured.endswith("\n"):
            captured = captured[:-1]
        ansi_lines = captured.split("\n") if captured else []
        if len(ansi_lines) < rows:
            ansi_lines.extend([""] * (rows - len(ansi_lines)))
        lines = [SGR_PATTERN.sub("", line) for line in ansi_lines]
        screen_start = max(0, len(lines) - rows)

        content = {
            "columns": columns,
            "rows": rows,
            "cursorColumn": cursor_column,
            "cursorRow": cursor_row,
            "alternateScreen": bool(alternate),
            "mouseMode": bool(mouse),
            "historySize": history,
            # Preserve build-38 compatibility: `lines` remains exactly the live
            # screen. Build 39 opts into the bounded history mirror through the
            # additive captured fields, so daemon/app rollout order is safe.
            "screenStart": screen_start,
            "lines": lines[screen_start:],
            "ansiLines": ansi_lines[screen_start:],
            "capturedLines": lines,
            "capturedANSILines": ansi_lines,
        }
        digest = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if digest != self.last_digest:
            self.sequence += 1
            self.last_digest = digest
            self.last_frame = dict(content, sequence=self.sequence)
        if self.last_frame is None:
            self.sequence = 1
            self.last_frame = dict(content, sequence=self.sequence)
        return dict(self.last_frame)

    def frame_after(self, after: int) -> Dict[str, Any]:
        deadline = time.monotonic() + LONG_POLL_SECONDS
        while True:
            with self.lock:
                frame = self._capture_locked()
            if frame["sequence"] > after or time.monotonic() >= deadline:
                return frame
            time.sleep(POLL_INTERVAL_SECONDS)

    def send_input(self, request_id: str, data: bytes, append_return: bool) -> None:
        if not request_id or len(request_id) > 128:
            raise TerminalError("The terminal request identifier was invalid.")
        if len(data) > MAX_INPUT_BYTES:
            raise TerminalError("Terminal input exceeded the 4096-byte limit.")
        if not data and not append_return:
            raise TerminalError("Terminal input was empty.")

        with self.lock:
            if request_id in self.processed_request_ids:
                return
            self.ensure_session()
            # Keep the requested Return in the same exact tmux buffer as the
            # text. This makes Siri's prompt plus submission one ordered PTY
            # write instead of racing a paste against a second send-keys call.
            payload = data + (b"\r" if append_return else b"")
            if payload:
                buffer_name = "jarvis-watch-{}".format(request_id.replace("-", "")[:32])
                self.runner.run(
                    self.tmux_arguments("load-buffer", "-b", buffer_name, "-"),
                    input_data=payload,
                )
                self.runner.run(
                    self.tmux_arguments(
                        "paste-buffer",
                        "-S",
                        "-r",
                        "-d",
                        "-b",
                        buffer_name,
                        "-t",
                        TMUX_TARGET,
                    )
                )
            self.processed_request_ids[request_id] = time.monotonic()
            if len(self.processed_request_ids) > 100:
                oldest = sorted(self.processed_request_ids.items(), key=lambda item: item[1])[:25]
                for key, _ in oldest:
                    self.processed_request_ids.pop(key, None)


class TerminalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: Tuple[str, int],
        service: TerminalService,
        token: str,
        trusted_cidrs: Sequence[ipaddress._BaseNetwork],
    ) -> None:
        super().__init__(address, TerminalRequestHandler)
        self.service = service
        self.token = token
        self.trusted_cidrs = trusted_cidrs


class TerminalRequestHandler(BaseHTTPRequestHandler):
    server_version = "JARVISTerminal/1"
    protocol_version = "HTTP/1.1"

    @property
    def terminal_server(self) -> TerminalHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format_string: str, *arguments: Any) -> None:
        # Never log headers, request bodies, input text, or bearer credentials.
        message = "%s - %s\n" % (self.address_string(), format_string % arguments)
        self.server.stderr.write(message) if hasattr(self.server, "stderr") else None

    def _remote_allowed(self) -> bool:
        try:
            remote = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(remote in network for network in self.terminal_server.trusted_cidrs)

    def _authorized(self) -> bool:
        if not self._remote_allowed():
            return False
        authorization = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            return False
        return hmac.compare_digest(authorization[len(prefix):], self.terminal_server.token)

    def _write_json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
            # Wrist-down/background cancellation is expected during a long poll.
            self.close_connection = True

    def _require_authorization(self) -> bool:
        if self._authorized():
            return True
        self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "Unauthorized."})
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            if not self._require_authorization():
                return
            self._write_json(HTTPStatus.OK, {"ok": True, "service": "jarvis-terminald", "version": 1})
            return
        if parsed.path != "/v1/terminal/frame":
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        if not self._require_authorization():
            return
        query = parse_qs(parsed.query)
        try:
            after = max(0, int(query.get("after", ["0"])[0]))
            frame = self.terminal_server.service.frame_after(after)
            self._write_json(HTTPStatus.OK, frame)
        except (ValueError, TerminalError, subprocess.SubprocessError) as error:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(error)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/v1/terminal/input":
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        if not self._require_authorization():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid request size."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request_id = payload.get("requestID", "")
            encoded = payload.get("dataBase64", "")
            append_return = payload.get("appendReturn", False)
            if not isinstance(request_id, str) or not isinstance(encoded, str) or not isinstance(append_return, bool):
                raise TerminalError("The terminal input request was invalid.")
            data = base64.b64decode(encoded, validate=True)
            self.terminal_server.service.send_input(request_id, data, append_return)
            self._write_json(HTTPStatus.OK, {"ok": True, "requestID": request_id})
        except (ValueError, json.JSONDecodeError, TerminalError, subprocess.SubprocessError) as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})


def parse_cidrs(raw: str) -> List[ipaddress._BaseNetwork]:
    networks: List[ipaddress._BaseNetwork] = []
    for item in raw.split(","):
        clean = item.strip()
        if clean:
            networks.append(ipaddress.ip_network(clean, strict=False))
    if not networks:
        raise TerminalError("at least one trusted CIDR is required")
    return networks


def run_server(host: str, port: int) -> None:
    token, cert_path, key_path = ensure_runtime_credentials()
    trusted_cidrs = parse_cidrs(os.environ.get("JARVIS_TERMINAL_TRUSTED_CIDRS", DEFAULT_CIDRS))
    server = TerminalHTTPServer((host, port), TerminalService(), token, trusted_cidrs)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print("jarvis-terminald listening on https://{}:{}".format(host, port), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS Apple Watch terminal bridge")
    parser.add_argument("--host", default=os.environ.get("JARVIS_TERMINAL_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_TERMINAL_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--print-provisioning", metavar="HOST")
    arguments = parser.parse_args()
    if arguments.print_provisioning:
        print(provisioning_code(arguments.print_provisioning))
        return
    run_server(arguments.host, arguments.port)


if __name__ == "__main__":
    main()
