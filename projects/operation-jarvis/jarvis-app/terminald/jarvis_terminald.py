#!/usr/bin/env python3
"""Authenticated HTTPS snapshot/input bridge for the Apple Watch terminal.

This daemon is intentionally separate from jarvisd. It exposes only six fixed
jarvis-mobile tmux sessions and has no hardware, service, scheduler, or JARVIS
control-plane integration.
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
import stat
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

APP_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = APP_ROOT / "scripts" / "jarvis-mobile-terminal.sh"
TMUX = "/opt/homebrew/bin/tmux"
TMUX_SOCKET = "jarvis-mobile"
TMUX_SESSIONS = {
    1: "jarvis-ios",
    2: "jarvis-ios-2",
    3: "jarvis-ios-3",
    4: "jarvis-ios-4",
    5: "jarvis-ios-5",
    6: "jarvis-ios-6",
}
# Slot 1 aliases remain patchable for the existing focused tests and v1 clients.
TMUX_SESSION = TMUX_SESSIONS[1]
TMUX_TARGET = "=" + TMUX_SESSION + ":"
DEFAULT_PORT = 8792
DEFAULT_CIDRS = "127.0.0.0/8,192.168.0.0/16,100.64.0.0/10"
MAX_INPUT_BYTES = 4096
MAX_BODY_BYTES = 8192
MAX_SPEECH_REQUEST_BYTES = 1024
MAX_SPEECH_MARKER_BYTES = 256 * 1024
MAX_SPEECH_TEXT_BYTES = 32 * 1024
MAX_SPEECH_AUDIO_BYTES = 20 * 1024 * 1024
ROOM_SPEECH_URL = "http://127.0.0.1:8791/synthesize"
SPEECH_RESPONSE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LONG_POLL_SECONDS = 1.5
POLL_INTERVAL_SECONDS = 0.10
MAX_SCROLLBACK_ROWS = 160
MAX_HISTORY_PAGE_ROWS = 256
SGR_PATTERN = re.compile(r"\x1b\[[0-9:;]*m")
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "JARVIS" / "terminald"
TOKEN_PATH = RUNTIME_DIR / "token"
CERT_PATH = RUNTIME_DIR / "certificate.pem"
KEY_PATH = RUNTIME_DIR / "certificate-key.pem"
SPEECH_DIR = RUNTIME_DIR / "speech"


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


class RoomSpeechClient:
    def synthesize(self, text: str) -> bytes:
        payload = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            ROOM_SPEECH_URL,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
        )
        try:
            with urlopen(request, timeout=180) as response:
                content_type = response.headers.get_content_type()
                audio = response.read(MAX_SPEECH_AUDIO_BYTES + 1)
        except HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("error", "")
            except (AttributeError, json.JSONDecodeError):
                message = ""
            raise TerminalError(message or "The JARVIS voice service rejected the response.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise TerminalError("The JARVIS voice service is unavailable.") from error
        if content_type != "audio/wav":
            raise TerminalError("The JARVIS voice service returned an invalid audio type.")
        if len(audio) > MAX_SPEECH_AUDIO_BYTES:
            raise TerminalError("The JARVIS voice response exceeded the audio limit.")
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise TerminalError("The JARVIS voice service returned invalid WAV audio.")
        return audio


class TerminalService:
    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        speech_dir: Optional[Path] = None,
        room_speech_client: Optional[RoomSpeechClient] = None,
        session_id: int = 1,
    ) -> None:
        if type(session_id) is not int or session_id not in TMUX_SESSIONS:
            raise TerminalError("The terminal session identifier was invalid.")
        self.session_id = session_id
        self.tmux_session = TMUX_SESSION if session_id == 1 else TMUX_SESSIONS[session_id]
        self.tmux_target = TMUX_TARGET if session_id == 1 else "=" + self.tmux_session + ":"
        self.runner = runner or CommandRunner()
        self.speech_dir = speech_dir or SPEECH_DIR
        self.room_speech_client = room_speech_client or RoomSpeechClient()
        self.lock = threading.Lock()
        self.frame_condition = threading.Condition(self.lock)
        self.speech_synthesis_lock = threading.Lock()
        self.speech_synthesis_events: Dict[str, threading.Event] = {}
        self.sequence = 0
        self.last_digest: Optional[str] = None
        self.last_frame: Optional[Dict[str, Any]] = None
        self.processed_request_ids: Dict[str, float] = {}
        self.frame_poll_interval = POLL_INTERVAL_SECONDS
        self.long_poll_seconds = LONG_POLL_SECONDS
        self.capture_attempt = 0
        self.last_capture_error: Optional[TerminalError] = None
        self.sampler_active_until = 0.0
        self.next_sample_at = 0.0
        self.sampler_thread: Optional[threading.Thread] = None
        self.sampler_stopping = False

    @staticmethod
    def tmux_arguments(*arguments: str) -> List[str]:
        return [TMUX, "-L", TMUX_SOCKET] + list(arguments)

    def ensure_session(self) -> None:
        result = self.runner.run(
            [str(BOOTSTRAP), "--slot", str(self.session_id), "--ensure-only"],
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise TerminalError("The persistent JARVIS session could not be created.")

    def _activate_sampler_locked(self, active_until: float, force_sample: bool = False) -> None:
        if self.sampler_stopping:
            raise TerminalError("The terminal frame sampler is stopping.")
        self.sampler_active_until = max(self.sampler_active_until, active_until)
        if force_sample:
            self.next_sample_at = 0.0
        if self.sampler_thread is None:
            self.next_sample_at = 0.0
            thread = threading.Thread(
                target=self._sampler_loop,
                name="jarvis-terminal-frame-sampler-{}".format(self.session_id),
                daemon=True,
            )
            self.sampler_thread = thread
            thread.start()
        self.frame_condition.notify_all()

    def _sampler_loop(self) -> None:
        current_thread = threading.current_thread()
        try:
            while True:
                with self.frame_condition:
                    now = time.monotonic()
                    if self.sampler_stopping or now >= self.sampler_active_until:
                        return
                    wait_seconds = min(
                        max(0.0, self.next_sample_at - now),
                        max(0.0, self.sampler_active_until - now),
                    )
                    if wait_seconds > 0:
                        self.frame_condition.wait(timeout=wait_seconds)
                        continue
                    try:
                        self._capture_locked()
                        self.last_capture_error = None
                    except (TerminalError, OSError, subprocess.SubprocessError) as error:
                        self.last_capture_error = TerminalError(str(error) or "Terminal capture failed.")
                    self.capture_attempt += 1
                    self.next_sample_at = time.monotonic() + self.frame_poll_interval
                    self.frame_condition.notify_all()
        finally:
            with self.frame_condition:
                if self.sampler_thread is current_thread:
                    self.sampler_thread = None
                self.frame_condition.notify_all()

    def close(self) -> None:
        with self.frame_condition:
            self.sampler_stopping = True
            thread = self.sampler_thread
            self.frame_condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _read_speech_marker(
        self,
        pane_pid: int,
        pane_id: str,
        tmux_server_pid: int,
        session_created_at: int,
    ) -> Dict[str, Any]:
        empty = {"available": False, "generating": False, "responseID": ""}
        marker_path = self.speech_dir / "{}.json".format(pane_pid)
        try:
            metadata = marker_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                return empty
            if metadata.st_mode & 0o077 or metadata.st_size <= 0 or metadata.st_size > MAX_SPEECH_MARKER_BYTES:
                return empty
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return empty
        if not isinstance(payload, dict) or payload.get("version") != 1 or payload.get("pid") != pane_pid:
            return empty
        if payload.get("paneID") != pane_id or payload.get("tmuxServerPID") != tmux_server_pid:
            return empty
        publisher_started_at = payload.get("publisherStartedAt")
        updated_at = payload.get("updatedAt")
        if not isinstance(publisher_started_at, (int, float)) or not isinstance(updated_at, (int, float)):
            return empty
        if publisher_started_at < (session_created_at - 5) * 1000 or updated_at < publisher_started_at:
            return empty
        if publisher_started_at > (time.time() + 60) * 1000:
            return empty
        status = payload.get("status")
        if status == "generating":
            return {"available": False, "generating": True, "responseID": ""}
        if status != "ready":
            return empty
        response_id = payload.get("responseID")
        text = payload.get("text")
        text_byte_count = payload.get("textByteCount")
        if not isinstance(response_id, str) or SPEECH_RESPONSE_ID_PATTERN.fullmatch(response_id) is None:
            return empty
        if not isinstance(text, str) or not text.strip():
            return empty
        actual_text_bytes = len(text.encode("utf-8"))
        if actual_text_bytes > MAX_SPEECH_TEXT_BYTES or text_byte_count != actual_text_bytes:
            return empty
        return {
            "available": True,
            "generating": False,
            "responseID": response_id,
            "text": text,
        }

    def _pane_identity_locked(self) -> Tuple[int, str, int, int]:
        identity_format = "\t".join(
            ["#{pane_pid}", "#{pane_id}", "#{pid}", "#{session_created}", "#{pane_dead}"]
        )
        result = self.runner.run(
            self.tmux_arguments("display-message", "-p", "-t", self.tmux_target, identity_format),
            check=False,
        )
        if result.returncode != 0:
            self.ensure_session()
            result = self.runner.run(
                self.tmux_arguments("display-message", "-p", "-t", self.tmux_target, identity_format)
            )
        values = result.stdout.decode("utf-8", errors="replace").strip().split("\t")
        if len(values) != 5 or values[4] == "1" or not values[1].startswith("%"):
            raise TerminalError("The persistent JARVIS pane is unavailable.")
        try:
            return int(values[0]), values[1], int(values[2]), int(values[3])
        except ValueError as error:
            raise TerminalError("The JARVIS pane identity was invalid.") from error

    def _speech_cache_path(self, response_id: str) -> Path:
        return self.speech_dir / "{}-{}.wav".format(self.session_id, response_id)

    def remove_legacy_speech_cache(self) -> None:
        """Remove the retired unscoped Slot 1 WAV without following links."""
        if self.session_id != 1:
            return
        try:
            candidates = list(self.speech_dir.glob("*.wav"))
        except OSError:
            return
        for path in candidates:
            if re.fullmatch(r"[0-9a-f]{64}\.wav", path.name) is None:
                continue
            try:
                metadata = path.lstat()
                if stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid():
                    path.unlink()
            except OSError:
                pass

    def _read_cached_speech(self, response_id: str) -> Optional[bytes]:
        cache_path = self._speech_cache_path(response_id)
        try:
            metadata = cache_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                return None
            if metadata.st_mode & 0o077 or metadata.st_size < 12 or metadata.st_size > MAX_SPEECH_AUDIO_BYTES:
                return None
            audio = cache_path.read_bytes()
        except OSError:
            return None
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            return None
        return audio

    def _write_cached_speech(self, response_id: str, audio: bytes) -> None:
        self.speech_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.speech_dir, 0o700)
        cache_path = self._speech_cache_path(response_id)
        temporary_path = self.speech_dir / ".{}.{}.tmp".format(response_id, secrets.token_hex(8))
        descriptor = os.open(str(temporary_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            output = os.fdopen(descriptor, "wb")
            descriptor = -1
            with output:
                output.write(audio)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, cache_path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        # Retain exactly one complete response per fixed mobile slot. Other
        # slots' content-addressed WAVs are never removed by this service.
        for stale_path in self.speech_dir.glob("{}-*.wav".format(self.session_id)):
            if stale_path != cache_path:
                try:
                    stale_path.unlink()
                except OSError:
                    pass

    def synthesize_speech(self, response_id: str) -> bytes:
        if SPEECH_RESPONSE_ID_PATTERN.fullmatch(response_id) is None:
            raise TerminalError("The Watch speech response identifier was invalid.")
        with self.lock:
            pane_pid, pane_id, tmux_server_pid, session_created_at = self._pane_identity_locked()
            speech = self._read_speech_marker(pane_pid, pane_id, tmux_server_pid, session_created_at)
            if not speech.get("available") or speech.get("responseID") != response_id:
                raise TerminalError("The final JARVIS response is no longer available.")
            text = speech.get("text")
            if not isinstance(text, str):
                raise TerminalError("The final JARVIS response is unavailable.")

        cached_audio = self._read_cached_speech(response_id)
        if cached_audio is not None:
            return cached_audio

        # A Watch route can disappear while a long WAV is downloading. Coalesce
        # duplicate requests so the complete response is rendered once and the
        # next authenticated request receives the atomic local cache immediately.
        with self.speech_synthesis_lock:
            cached_audio = self._read_cached_speech(response_id)
            if cached_audio is not None:
                return cached_audio
            completion = self.speech_synthesis_events.get(response_id)
            owns_synthesis = completion is None
            if completion is None:
                completion = threading.Event()
                self.speech_synthesis_events[response_id] = completion

        if not owns_synthesis:
            if not completion.wait(timeout=185):
                raise TerminalError("The JARVIS voice response timed out.")
            cached_audio = self._read_cached_speech(response_id)
            if cached_audio is None:
                raise TerminalError("The JARVIS voice response could not be prepared.")
            return cached_audio

        try:
            # Never hold the terminal capture/input or synthesis coordination
            # lock while the loopback-only room voice service renders the WAV.
            audio = self.room_speech_client.synthesize(text)
            self._write_cached_speech(response_id, audio)
            return audio
        finally:
            with self.speech_synthesis_lock:
                self.speech_synthesis_events.pop(response_id, None)
                completion.set()

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
                "#{pane_pid}",
                "#{pane_id}",
                "#{pid}",
                "#{session_created}",
            ]
        )
        # One tmux client invocation emits both metadata and the exact ANSI
        # grid. tmux clamps an over-deep negative history start to the oldest
        # retained row, preserving the former bounded-tail semantics without a
        # preliminary process solely to calculate that start.
        capture_arguments = self.tmux_arguments(
            "display-message",
            "-p",
            "-t",
            self.tmux_target,
            metadata_format,
            ";",
            "capture-pane",
            "-p",
            "-e",
            "-N",
            "-S",
            str(-MAX_SCROLLBACK_ROWS),
            "-t",
            self.tmux_target,
        )
        combined = self.runner.run(capture_arguments, check=False)
        if combined.returncode != 0:
            self.ensure_session()
            combined = self.runner.run(capture_arguments)
        decoded = combined.stdout.decode("utf-8", errors="replace")
        metadata_line, separator, captured = decoded.partition("\n")
        if not separator:
            raise TerminalError("The JARVIS pane capture was invalid.")
        values = metadata_line.split("\t")
        if len(values) != 12 or values[7] == "1" or not values[9].startswith("%"):
            raise TerminalError("The persistent JARVIS pane is unavailable.")
        try:
            columns, rows, cursor_column, cursor_row, alternate, mouse, history, _ = [
                int(value or "0") for value in values[:8]
            ]
            pane_pid = int(values[8])
            pane_id = values[9]
            tmux_server_pid = int(values[10])
            session_created_at = int(values[11])
        except ValueError as error:
            raise TerminalError("The JARVIS pane metadata was invalid.") from error
        speech = self._read_speech_marker(pane_pid, pane_id, tmux_server_pid, session_created_at)

        # Preserve the actual tmux grid and its SGR attributes. Pi's thinking,
        # tool calls, token counters, and assistant output are not reconstructed
        # here; they remain ordinary terminal cells captured verbatim. A bounded
        # tail of tmux history lets the Watch Crown move a local, read-only
        # viewport without injecting unreliable mouse sequences into Pi.
        if captured.endswith("\n"):
            captured = captured[:-1]
        ansi_lines = captured.split("\n") if captured else []
        if len(ansi_lines) < rows:
            ansi_lines.extend([""] * (rows - len(ansi_lines)))
        lines = [SGR_PATTERN.sub("", line) for line in ansi_lines]
        screen_start = max(0, len(lines) - rows)

        content = {
            "sessionID": self.session_id,
            "columns": columns,
            "rows": rows,
            "paneID": pane_id,
            "cursorColumn": cursor_column,
            "cursorRow": cursor_row,
            "alternateScreen": bool(alternate),
            "mouseMode": bool(mouse),
            "historySize": history,
            "speech": {
                "available": bool(speech.get("available")),
                "generating": bool(speech.get("generating")),
                "responseID": speech.get("responseID", "") if speech.get("available") else "",
            },
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
        deadline = time.monotonic() + self.long_poll_seconds
        with self.frame_condition:
            starting_attempt = self.capture_attempt
            force_sample = self.last_frame is None or self.last_capture_error is not None
            self._activate_sampler_locked(
                deadline + self.frame_poll_interval,
                force_sample=force_sample,
            )
            while True:
                if self.last_frame is not None and self.last_frame["sequence"] > after:
                    return dict(self.last_frame)
                if self.capture_attempt > starting_attempt and self.last_capture_error is not None:
                    raise TerminalError(str(self.last_capture_error))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self.last_frame is not None:
                        return dict(self.last_frame)
                    if self.last_capture_error is not None:
                        raise TerminalError(str(self.last_capture_error))
                    raise TerminalError("The terminal frame capture timed out.")
                self.frame_condition.wait(timeout=remaining)

    def history_page(self, start: int, limit: int) -> Dict[str, Any]:
        """Capture one bounded, read-only page from the full tmux history.

        `start` is an oldest-first absolute history row. The endpoint never
        changes copy mode, attaches a client, resizes the pane, or emits input.
        Keeping each response bounded lets the Watch traverse tmux's complete
        100,000-row history without carrying it in every live poll.
        """
        if start < 0:
            raise TerminalError("The terminal history start was invalid.")
        if limit <= 0 or limit > MAX_HISTORY_PAGE_ROWS:
            raise TerminalError("The terminal history page size was invalid.")

        with self.lock:
            metadata_format = "\t".join(
                ["#{history_size}", "#{pane_dead}", "#{pane_id}"]
            )
            metadata = self.runner.run(
                self.tmux_arguments("display-message", "-p", "-t", self.tmux_target, metadata_format),
                check=False,
            )
            if metadata.returncode != 0:
                self.ensure_session()
                metadata = self.runner.run(
                    self.tmux_arguments("display-message", "-p", "-t", self.tmux_target, metadata_format)
                )
            values = metadata.stdout.decode("utf-8", errors="replace").strip().split("\t")
            if len(values) != 3 or values[1] == "1" or not values[2].startswith("%"):
                raise TerminalError("The persistent JARVIS pane is unavailable.")
            try:
                history_size = max(0, int(values[0] or "0"))
            except ValueError as error:
                raise TerminalError("The JARVIS history metadata was invalid.") from error
            pane_id = values[2]
            safe_start = min(start, history_size)
            safe_end = min(history_size, safe_start + limit)
            if safe_start == safe_end:
                return {
                    "sessionID": self.session_id,
                    "paneID": pane_id,
                    "historySize": history_size,
                    "start": safe_start,
                    "lines": [],
                    "ansiLines": [],
                }

            # tmux addresses history relative to the top of the live screen:
            # -history_size is the oldest retained row and -1 the newest.
            capture_start = safe_start - history_size
            capture_end = safe_end - history_size - 1
            captured = self.runner.run(
                self.tmux_arguments(
                    "capture-pane",
                    "-p",
                    "-e",
                    "-N",
                    "-S",
                    str(capture_start),
                    "-E",
                    str(capture_end),
                    "-t",
                    self.tmux_target,
                )
            ).stdout.decode("utf-8", errors="replace")
            if captured.endswith("\n"):
                captured = captured[:-1]
            ansi_lines = captured.split("\n") if captured else []
            expected = safe_end - safe_start
            # Fail closed if tmux returns an impossible range; accepting extra
            # rows would make Crown offsets point at the wrong terminal cells.
            if len(ansi_lines) > expected:
                ansi_lines = ansi_lines[:expected]
            elif len(ansi_lines) < expected:
                ansi_lines.extend([""] * (expected - len(ansi_lines)))
            return {
                "sessionID": self.session_id,
                "paneID": pane_id,
                "historySize": history_size,
                "start": safe_start,
                "lines": [SGR_PATTERN.sub("", line) for line in ansi_lines],
                "ansiLines": ansi_lines,
            }

    def _refresh_attached_clients_locked(self) -> None:
        """Best-effort redraw for SSH clients after out-of-band Watch input.

        Input reaches Pi through a detached tmux command rather than through an
        attached SSH client's tty. Explicitly redrawing each client keeps an
        already-open iPhone terminal on the live pane without reconnecting,
        resizing, or injecting any additional terminal bytes.
        """
        try:
            clients = self.runner.run(
                self.tmux_arguments("list-clients", "-t", "=" + self.tmux_session, "-F", "#{client_name}"),
                check=False,
            )
            if clients.returncode != 0:
                return
            for raw_name in clients.stdout.decode("utf-8", errors="replace").splitlines():
                client_name = raw_name.strip()
                if not client_name or len(client_name) > 512:
                    continue
                self.runner.run(
                    self.tmux_arguments("refresh-client", "-t", client_name),
                    check=False,
                )
        except (OSError, subprocess.SubprocessError):
            # The prompt was already delivered. A redraw failure must never
            # turn that confirmed write into an ambiguous/replayable request.
            return

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
                        self.tmux_target,
                    )
                )
            # Record successful delivery before the best-effort client redraw.
            # If redraw fails, this request still remains deduplicated forever
            # within the daemon lifetime and is acknowledged as delivered.
            self.processed_request_ids[request_id] = time.monotonic()
            self._refresh_attached_clients_locked()
            # If a Watch frame request is active, sample immediately after the
            # confirmed write instead of waiting for the ordinary cadence.
            if self.sampler_thread is not None:
                self.next_sample_at = 0.0
                self.frame_condition.notify_all()
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
        services: Optional[Dict[int, TerminalService]] = None,
    ) -> None:
        service_map = dict(services or {1: service})
        if service_map.get(1) is not service:
            raise TerminalError("Slot 1 must remain the legacy terminal service.")
        if any(
            type(session_id) is not int
            or session_id not in TMUX_SESSIONS
            or candidate.session_id != session_id
            for session_id, candidate in service_map.items()
        ):
            raise TerminalError("The terminal service map was invalid.")
        super().__init__(address, TerminalRequestHandler)
        self.service = service  # v1/test compatibility: always Slot 1.
        self.services = service_map
        self.token = token
        self.trusted_cidrs = trusted_cidrs

    def service_for(self, session_id: int) -> TerminalService:
        service = self.services.get(session_id)
        if service is None:
            raise TerminalError("The requested terminal session is unavailable.")
        return service

    def server_close(self) -> None:
        for service in set(self.services.values()):
            service.close()
        super().server_close()


class TerminalRequestHandler(BaseHTTPRequestHandler):
    server_version = "JARVISTerminal/2"
    protocol_version = "HTTP/1.1"

    @property
    def terminal_server(self) -> TerminalHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format_string: str, *arguments: Any) -> None:
        # Never log headers, request bodies, input text, bearer credentials, or
        # the selected conversation beyond the ordinary bounded request path.
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

    def _write_audio(self, payload: bytes, session_id: int) -> None:
        try:
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-JARVIS-Terminal-Session", str(session_id))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
            self.close_connection = True

    def _require_authorization(self) -> bool:
        if self._authorized():
            return True
        self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "Unauthorized."})
        return False

    @staticmethod
    def _v2_session_id(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("The terminal session identifier was invalid.")
        try:
            session_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("The terminal session identifier was invalid.") from error
        if str(session_id) != str(value) or session_id not in TMUX_SESSIONS:
            raise ValueError("The terminal session identifier was invalid.")
        return session_id

    def _v2_query_session(self, query: Dict[str, List[str]]) -> int:
        values = query.get("sessionID", [])
        if len(values) != 1:
            raise ValueError("The terminal session identifier was required.")
        return self._v2_session_id(values[0])

    @staticmethod
    def _v2_payload_session(value: Any) -> int:
        # JSON request identities are canonical integers. Strings, booleans,
        # and integral floating-point values must not select a conversation.
        if type(value) is not int or value not in TMUX_SESSIONS:
            raise ValueError("The terminal session identifier was invalid.")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            if not self._require_authorization():
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "jarvis-terminald",
                    "version": 2,
                    "sessionIDs": sorted(self.terminal_server.services),
                },
            )
            return
        routes = {
            "/v1/terminal/frame": (False, False),
            "/v1/terminal/history": (False, True),
            "/v2/terminal/frame": (True, False),
            "/v2/terminal/history": (True, True),
        }
        route = routes.get(parsed.path)
        if route is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        if not self._require_authorization():
            return
        is_v2, is_history = route
        query = parse_qs(parsed.query)
        try:
            session_id = self._v2_query_session(query) if is_v2 else 1
            service = self.terminal_server.service_for(session_id)
            if is_history:
                start = int(query.get("start", ["0"])[0])
                limit = int(query.get("limit", [str(MAX_HISTORY_PAGE_ROWS)])[0])
                self._write_json(HTTPStatus.OK, service.history_page(start, limit))
                return
            after = max(0, int(query.get("after", ["0"])[0]))
            self._write_json(HTTPStatus.OK, service.frame_after(after))
        except ValueError as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
        except (TerminalError, subprocess.SubprocessError) as error:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(error)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/v1/terminal/input": (False, False),
            "/v1/terminal/speech": (False, True),
            "/v2/terminal/input": (True, False),
            "/v2/terminal/speech": (True, True),
        }
        route = routes.get(parsed.path)
        if route is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        if not self._require_authorization():
            return
        is_v2, is_speech = route
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        maximum_length = MAX_SPEECH_REQUEST_BYTES if is_speech else MAX_BODY_BYTES
        if length <= 0 or length > maximum_length:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid request size."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("The terminal request was invalid.")
            session_id = self._v2_payload_session(payload.get("sessionID")) if is_v2 else 1
            service = self.terminal_server.service_for(session_id)
            if is_speech:
                response_id = payload.get("responseID", "")
                if not isinstance(response_id, str):
                    raise ValueError("The Watch speech request was invalid.")
                self._write_audio(service.synthesize_speech(response_id), session_id)
                return
            request_id = payload.get("requestID", "")
            encoded = payload.get("dataBase64", "")
            append_return = payload.get("appendReturn", False)
            if not isinstance(request_id, str) or not isinstance(encoded, str) or not isinstance(append_return, bool):
                raise ValueError("The terminal input request was invalid.")
            data = base64.b64decode(encoded, validate=True)
            service.send_input(request_id, data, append_return)
            self._write_json(
                HTTPStatus.OK,
                {"ok": True, "requestID": request_id, "sessionID": session_id},
            )
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
    services = {
        session_id: TerminalService(session_id=session_id)
        for session_id in sorted(TMUX_SESSIONS)
    }
    # Eagerly create missing Slots 2 through 6 while Slot 1's surviving pane
    # remains untouched. Each bootstrap is idempotent and never attaches or resizes.
    for service in services.values():
        service.ensure_session()
    services[1].remove_legacy_speech_cache()
    server = TerminalHTTPServer(
        (host, port),
        services[1],
        token,
        trusted_cidrs,
        services=services,
    )
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
