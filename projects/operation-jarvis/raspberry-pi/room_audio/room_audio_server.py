#!/usr/bin/env python3
"""LAN room-audio bridge for Operation JARVIS.

Mac-side service:
  Raspberry Pi PowerConf WAV -> oMLX Whisper ASR -> Pi RPC JARVIS -> Piper TTS WAV.

The Raspberry Pi client records/plays audio locally, asks this server for startup
or reconnect greeting audio, and posts VAD/fixed-length turns here. This keeps the
heavier ASR, LLM/Pi RPC, and TTS stack on the Mac while using the Pi as the room
microphone/speaker endpoint.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def _find_operation_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if parent.name == "operation-jarvis" and (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError(f"Unable to locate operation-jarvis root from {start}")


def _find_project_root(operation_root: Path) -> Path:
    for parent in operation_root.parents:
        if (parent / "config.py").exists() and (parent / "llm.py").exists():
            return parent
    raise RuntimeError(f"Unable to locate JARVIS project root from {operation_root}")


OPERATION_ROOT = _find_operation_root(Path(__file__).resolve())
PROJECT_ROOT = _find_project_root(OPERATION_ROOT)
VOICE_ROOT = OPERATION_ROOT / "voice"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(VOICE_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICE_ROOT))

import config  # noqa: E402

config.load_project_env(PROJECT_ROOT / ".env")

import llm  # noqa: E402
import discord_voice  # noqa: E402

LOGGER = config.get_logger("operation_jarvis.room_audio")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8791
DEFAULT_MAX_REQUEST_BYTES = 25 * 1024 * 1024
DEFAULT_CHANNEL_ID = "room-audio"
DEFAULT_CHANNEL_NAME = "raspberry-pi-room-audio"
DEFAULT_TTS_LEADING_SILENCE_MS = config.get_int_env("JARVIS_ROOM_AUDIO_TTS_LEADING_SILENCE_MS", 450, minimum=0)
ASYNC_JOB_TTL_SECONDS = config.get_int_env("JARVIS_ROOM_AUDIO_ASYNC_JOB_TTL_SECONDS", 900, minimum=60)
ASYNC_POLL_AFTER_SECONDS = config.get_float_env("JARVIS_ROOM_AUDIO_ASYNC_POLL_AFTER_SECONDS", 0.25, minimum=0.05)
ROOM_AUDIO_PI_IDLE_NEW_SESSION_SECONDS = config.get_float_env(
    "JARVIS_ROOM_AUDIO_PI_IDLE_NEW_SESSION_SECONDS",
    config.get_float_env("DISCORD_VOICE_PI_IDLE_NEW_SESSION_SECONDS", 15 * 60.0, minimum=0.0),
    minimum=0.0,
)
PROCESSING_ACK_ENABLED = config.get_str_env(
    "JARVIS_ROOM_AUDIO_PROCESSING_ACK_ENABLED",
    config.get_str_env("DISCORD_VOICE_PROCESSING_ACK_ENABLED", "1"),
).lower() not in {"0", "false", "no", "off", ""}
PROCESSING_ACK_TEXT = config.get_str_env(
    "JARVIS_ROOM_AUDIO_PROCESSING_ACK_TEXT",
    config.get_str_env("DISCORD_VOICE_PROCESSING_ACK_TEXT", "Generating your response, sir."),
).strip()
ROOM_GREETING_ENABLED = config.get_str_env("JARVIS_ROOM_AUDIO_GREETING_ENABLED", "1").lower() not in {"0", "false", "no", "off", ""}
ROOM_GREETING_TEXT = config.get_str_env("JARVIS_ROOM_AUDIO_GREETING_TEXT", "").strip()
ROOM_GREETING_STATE_PATH = Path(
    config.get_str_env("JARVIS_ROOM_AUDIO_GREETING_STATE_PATH", str(OPERATION_ROOT / "data" / "room_audio_greeting_state.json"))
).expanduser()
ROOM_GREETING_LOCK = threading.Lock()

WAKE_WORDS = tuple(
    dict.fromkeys(
        word.strip()
        for word in re.split(r"[,;|]", config.get_str_env("JARVIS_ROOM_AUDIO_WAKE_WORD", config.get_str_env("DISCORD_VOICE_WAKE_WORD", "jarvis,arvis,charvis,travis,darvish,charmavis")))
        if word.strip()
    )
)


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _load_room_greeting_state_unlocked() -> dict[str, Any]:
    try:
        if not ROOM_GREETING_STATE_PATH.is_file():
            return {}
        payload = json.loads(ROOM_GREETING_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.debug("Failed to read room-audio greeting state", exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_room_greeting_state_unlocked(state: dict[str, Any]) -> None:
    try:
        ROOM_GREETING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROOM_GREETING_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        LOGGER.debug("Failed to write room-audio greeting state", exc_info=True)


def select_room_greeting() -> str:
    if not ROOM_GREETING_ENABLED:
        return ""
    if ROOM_GREETING_TEXT:
        return ROOM_GREETING_TEXT

    now_func = getattr(discord_voice, "_voice_local_now", None)
    parse_func = getattr(discord_voice, "_parse_voice_greeting_timestamp", None)
    format_func = getattr(discord_voice, "_format_contextual_join_greeting", None)
    if not (callable(now_func) and callable(parse_func) and callable(format_func)):
        return "JARVIS online. At your service, sir."

    now = now_func()
    with ROOM_GREETING_LOCK:
        state = _load_room_greeting_state_unlocked()
        last_connected_at = parse_func(state.get("last_connected_at"))
        state["last_connected_at"] = now.isoformat()
        _save_room_greeting_state_unlocked(state)
    return str(format_func(now, last_connected_at)).strip()


def load_room_append_system_prompt() -> str:
    parts = [
        _load_text(VOICE_ROOT / "APPEND_SYSTEM.md"),
        _load_text(PROJECT_ROOT / ".pi" / "APPEND_SYSTEM.md"),
        (
            "You are currently speaking through the Raspberry Pi room audio endpoint. "
            "The microphone and speaker are in the room, so answer naturally and briefly. "
            "Do not mention Discord unless asked."
        ),
    ]
    return "\n\n".join(part for part in parts if part)


def normalize_wake_words(transcript: str) -> str:
    normalizer = getattr(discord_voice, "_normalize_voice_transcript_wake_words", None)
    if callable(normalizer):
        return str(normalizer(transcript)).strip()
    return transcript.strip()


def combine_wavs(paths: list[Path]) -> bytes:
    if not paths:
        raise RuntimeError("No TTS audio paths were produced.")

    with wave.open(str(paths[0]), "rb") as first:
        channels = first.getnchannels()
        sample_width = first.getsampwidth()
        frame_rate = first.getframerate()
        comp_type = first.getcomptype()
        comp_name = first.getcompname()
        frame_blocks = [first.readframes(first.getnframes())]

    for path in paths[1:]:
        with wave.open(str(path), "rb") as handle:
            if (
                handle.getnchannels() != channels
                or handle.getsampwidth() != sample_width
                or handle.getframerate() != frame_rate
                or handle.getcomptype() != comp_type
            ):
                raise RuntimeError(f"Cannot concatenate WAVs with mismatched parameters: {path}")
            frame_blocks.append(handle.readframes(handle.getnframes()))

    leading_silence_frames = int(frame_rate * DEFAULT_TTS_LEADING_SILENCE_MS / 1000)
    leading_silence = b"\x00" * leading_silence_frames * channels * sample_width

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        combined_path = Path(tmp.name)
    try:
        with wave.open(str(combined_path), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sample_width)
            out.setframerate(frame_rate)
            out.setcomptype(comp_type, comp_name)
            if leading_silence:
                out.writeframes(leading_silence)
            for frame_block in frame_blocks:
                out.writeframes(frame_block)
        return combined_path.read_bytes()
    finally:
        combined_path.unlink(missing_ok=True)


class RoomAudioBridge:
    def __init__(self) -> None:
        model = config.get_str_env(
            "JARVIS_ROOM_AUDIO_PI_MODEL",
            config.get_str_env("DISCORD_VOICE_PI_MODEL", config.get_str_env("DISCORD_PI_MODEL", "")),
        )
        thinking = config.get_str_env("JARVIS_ROOM_AUDIO_PI_THINKING", llm.DISCORD_PI_THINKING)
        self._session = llm.PiRpcSession(
            model=model,
            thinking=thinking,
            append_system_prompt=load_room_append_system_prompt(),
            discord_channel_id=DEFAULT_CHANNEL_ID,
            discord_channel_name=DEFAULT_CHANNEL_NAME,
        )
        # The server returns a single final WAV to the Pi client, so do not stream
        # TTS chunks here. Discord voice still owns the streaming path.
        pipeline_config = discord_voice.VoicePipelineConfig(stream_tts=False)
        self._pipeline = discord_voice.OmlxVoicePipeline(pipeline_config, response_callback=self._run_pi_response)
        self._lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._ack_lock = threading.Lock()
        self._ack_audio_b64: str | None = None
        self._model = model
        self._thinking = thinking

    @property
    def model(self) -> str:
        return self._model

    @property
    def thinking(self) -> str:
        return self._thinking

    def warm_up(self) -> None:
        self._pipeline.warm_up()

    def close(self) -> None:
        self._session.stop()

    def _start_new_session_if_idle(self) -> None:
        if ROOM_AUDIO_PI_IDLE_NEW_SESSION_SECONDS <= 0:
            return
        idle_for = self._session.seconds_since_last_activity()
        idle_detail = f"{idle_for:.0f}s" if idle_for is not None else "unknown"
        try:
            started = self._session.start_new_session_if_idle(ROOM_AUDIO_PI_IDLE_NEW_SESSION_SECONDS)
        except Exception:
            LOGGER.warning(
                "Failed to start fresh room-audio Pi session after %s idle; restarting Pi RPC process",
                idle_detail,
                exc_info=True,
            )
            self._session.stop()
            return
        if started:
            LOGGER.info("Started fresh room-audio Pi session after %s idle", idle_detail)

    def _run_pi_response(self, transcript: str, on_delta: Any, _turn_context: object | None) -> str:
        prompt = normalize_wake_words(transcript).strip()
        text_parts: list[str] = []

        def handle_event(event: dict[str, Any]) -> None:
            if event.get("type") != "message_update":
                return
            message_event = event.get("assistantMessageEvent")
            if not isinstance(message_event, dict):
                return
            if message_event.get("type") != "text_delta":
                return
            delta = str(message_event.get("delta") or "")
            if not delta:
                return
            text_parts.append(delta)
            if on_delta is not None:
                on_delta(delta)

        # Keep one persistent Pi session for room audio, but serialize turns so a
        # second HTTP request cannot steer or corrupt the current spoken reply.
        with self._lock:
            self._start_new_session_if_idle()
            self._session.run_prompt(prompt, on_event=handle_event, timeout_seconds=llm.PI_CODING_AGENT_RPC_TIMEOUT_SECONDS)
        return "".join(text_parts).strip()

    def _synthesize_processing_ack(self) -> str:
        if not PROCESSING_ACK_ENABLED or not PROCESSING_ACK_TEXT:
            return ""
        with self._ack_lock:
            if self._ack_audio_b64 is not None:
                return self._ack_audio_b64
            ack_path: Path | None = None
            try:
                ack_path = self._pipeline.synthesize_notice(PROCESSING_ACK_TEXT)
                self._ack_audio_b64 = base64.b64encode(combine_wavs([ack_path])).decode("ascii")
                return self._ack_audio_b64
            finally:
                if ack_path is not None:
                    ack_path.unlink(missing_ok=True)

    def warm_processing_ack(self) -> None:
        if PROCESSING_ACK_ENABLED and PROCESSING_ACK_TEXT:
            self._synthesize_processing_ack()

    def synthesize_greeting(self) -> dict[str, Any]:
        greeting_text = select_room_greeting()
        if not greeting_text:
            return {
                "ok": True,
                "greetingEnabled": False,
                "greetingText": "",
                "audioWavBase64": "",
                "audioContentType": "",
            }

        greeting_path: Path | None = None
        try:
            greeting_path = self._pipeline.synthesize_notice(greeting_text)
            audio_bytes = combine_wavs([greeting_path])
            return {
                "ok": True,
                "greetingEnabled": True,
                "greetingText": greeting_text,
                "audioWavBase64": base64.b64encode(audio_bytes).decode("ascii"),
                "audioContentType": "audio/wav",
                "model": self.model,
                "thinking": self.thinking,
            }
        finally:
            if greeting_path is not None:
                greeting_path.unlink(missing_ok=True)

    def _synthesize_accepted_turn(
        self,
        wav_path: Path,
        *,
        transcript: str,
        input_seconds: float,
        asr_seconds: float,
        started_at: float,
        include_ack: bool,
    ) -> dict[str, Any]:
        ack_path: Path | None = None
        audio_paths: list[Path] = []
        try:
            if include_ack and PROCESSING_ACK_ENABLED and PROCESSING_ACK_TEXT:
                try:
                    ack_path = self._pipeline.synthesize_notice(PROCESSING_ACK_TEXT)
                except Exception:
                    LOGGER.warning("Failed to synthesize room-audio processing acknowledgement", exc_info=True)

            result = self._pipeline.synthesize_turn(
                wav_path,
                None,
                None,
                transcript=transcript,
                input_seconds=input_seconds,
                asr_seconds=asr_seconds,
                started_at=started_at,
            )
            audio_paths = ([ack_path] if ack_path is not None else []) + list(result.audio_paths)
            audio_bytes = combine_wavs(audio_paths)
            return {
                "ok": True,
                "accepted": True,
                "pending": False,
                "transcript": transcript,
                "normalizedTranscript": normalize_wake_words(transcript),
                "replyText": result.reply_text,
                "audioWavBase64": base64.b64encode(audio_bytes).decode("ascii"),
                "audioContentType": "audio/wav",
                "inputSeconds": result.input_seconds,
                "asrSeconds": result.asr_seconds,
                "llmSeconds": result.llm_seconds,
                "ttsSeconds": result.tts_seconds,
                "totalSeconds": result.total_seconds,
                "model": self.model,
                "thinking": self.thinking,
            }
        finally:
            paths_to_remove = list(audio_paths)
            if ack_path is not None and ack_path not in paths_to_remove:
                paths_to_remove.append(ack_path)
            for path in paths_to_remove:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    LOGGER.debug("Failed to remove temporary room TTS file %s", path, exc_info=True)

    def _prune_jobs_locked(self) -> None:
        cutoff = time.monotonic() - ASYNC_JOB_TTL_SECONDS
        for turn_id, job in list(self._jobs.items()):
            if float(job.get("createdMonotonic", 0.0)) < cutoff:
                self._jobs.pop(turn_id, None)

    def _finish_async_turn(
        self,
        turn_id: str,
        wav_path: Path,
        transcript: str,
        input_seconds: float,
        asr_seconds: float,
        started_at: float,
    ) -> None:
        try:
            response = self._synthesize_accepted_turn(
                wav_path,
                transcript=transcript,
                input_seconds=input_seconds,
                asr_seconds=asr_seconds,
                started_at=started_at,
                include_ack=False,
            )
            response.update({"turnId": turn_id, "status": "done"})
        except Exception as exc:
            LOGGER.exception("Room audio async turn failed: %s", turn_id)
            error_audio_b64 = ""
            try:
                notice_path = self._pipeline.synthesize_notice(
                    "I generated a response, sir, but the voice renderer failed before I could speak it."
                )
                try:
                    error_audio_b64 = base64.b64encode(combine_wavs([notice_path])).decode("ascii")
                finally:
                    notice_path.unlink(missing_ok=True)
            except Exception:
                LOGGER.warning("Failed to synthesize room-audio error notice", exc_info=True)
            response = {
                "ok": False,
                "accepted": True,
                "pending": False,
                "status": "error",
                "turnId": turn_id,
                "transcript": transcript,
                "normalizedTranscript": normalize_wake_words(transcript),
                "error": str(exc),
                "audioWavBase64": error_audio_b64,
                "audioContentType": "audio/wav" if error_audio_b64 else "",
                "inputSeconds": input_seconds,
                "asrSeconds": asr_seconds,
                "totalSeconds": time.monotonic() - started_at,
            }

        finally:
            wav_path.unlink(missing_ok=True)

        with self._jobs_lock:
            self._prune_jobs_locked()
            job = self._jobs.get(turn_id)
            if job is not None:
                job.update(
                    {
                        "status": response.get("status", "done"),
                        "pending": False,
                        "response": response,
                        "completedMonotonic": time.monotonic(),
                    }
                )

    def get_turn_result(self, turn_id: str) -> dict[str, Any] | None:
        with self._jobs_lock:
            self._prune_jobs_locked()
            job = self._jobs.get(turn_id)
            if job is None:
                return None
            if job.get("pending"):
                return {
                    "ok": True,
                    "accepted": True,
                    "pending": True,
                    "status": job.get("status", "running"),
                    "turnId": turn_id,
                    "transcript": job.get("transcript", ""),
                    "normalizedTranscript": job.get("normalizedTranscript", ""),
                    "elapsedSeconds": time.monotonic() - float(job.get("startedMonotonic", time.monotonic())),
                    "pollAfterSeconds": ASYNC_POLL_AFTER_SECONDS,
                }
            response = job.get("response")
            return dict(response) if isinstance(response, dict) else None

    def handle_wav_async_ack(self, wav_path: Path, *, require_wake_word: bool = True) -> dict[str, Any]:
        started = time.monotonic()
        transcript, input_seconds, asr_seconds = self._pipeline.transcribe_audio(wav_path)
        # Pi-side openWakeWord is the authoritative wake gate. Once a turn reaches
        # Whisper, answer the transcription as-is instead of applying a second,
        # fragile transcript wake-word check.

        ack_audio_b64 = ""
        if PROCESSING_ACK_ENABLED and PROCESSING_ACK_TEXT:
            try:
                ack_audio_b64 = self._synthesize_processing_ack()
            except Exception:
                LOGGER.warning("Failed to synthesize room-audio processing acknowledgement", exc_info=True)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as job_tmp:
            job_tmp.write(wav_path.read_bytes())
            job_wav_path = Path(job_tmp.name)

        turn_id = uuid.uuid4().hex
        with self._jobs_lock:
            self._prune_jobs_locked()
            self._jobs[turn_id] = {
                "status": "running",
                "pending": True,
                "transcript": transcript,
                "normalizedTranscript": normalize_wake_words(transcript),
                "createdMonotonic": time.monotonic(),
                "startedMonotonic": started,
            }

        threading.Thread(
            target=self._finish_async_turn,
            args=(turn_id, job_wav_path, transcript, input_seconds, asr_seconds, started),
            name=f"room-audio-turn-{turn_id[:8]}",
            daemon=True,
        ).start()

        return {
            "ok": True,
            "accepted": True,
            "pending": True,
            "status": "running",
            "turnId": turn_id,
            "transcript": transcript,
            "normalizedTranscript": normalize_wake_words(transcript),
            "ackText": PROCESSING_ACK_TEXT if PROCESSING_ACK_ENABLED else "",
            "audioWavBase64": ack_audio_b64,
            "audioContentType": "audio/wav" if ack_audio_b64 else "",
            "inputSeconds": input_seconds,
            "asrSeconds": asr_seconds,
            "totalSeconds": time.monotonic() - started,
            "pollAfterSeconds": ASYNC_POLL_AFTER_SECONDS,
            "model": self.model,
            "thinking": self.thinking,
        }

    def handle_wav(self, wav_path: Path, *, require_wake_word: bool = True) -> dict[str, Any]:
        started = time.monotonic()
        transcript, input_seconds, asr_seconds = self._pipeline.transcribe_audio(wav_path)
        # Pi-side openWakeWord is the authoritative wake gate. Once a turn reaches
        # Whisper, answer the transcription as-is instead of applying a second,
        # fragile transcript wake-word check.

        return self._synthesize_accepted_turn(
            wav_path,
            transcript=transcript,
            input_seconds=input_seconds,
            asr_seconds=asr_seconds,
            started_at=started,
            include_ack=PROCESSING_ACK_ENABLED,
        )


class RoomAudioHTTPServer(ThreadingHTTPServer):
    bridge: RoomAudioBridge
    token: str
    max_request_bytes: int


class RoomAudioHandler(BaseHTTPRequestHandler):
    server: RoomAudioHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = self.server.token
        if not token:
            return True
        return self.headers.get("x-jarvis-room-token", "") == token

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/turn-result":
            turn_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
            if not turn_id:
                self._send_json({"ok": False, "error": "id is required"}, HTTPStatus.BAD_REQUEST)
                return
            response = self.server.bridge.get_turn_result(turn_id)
            if response is None:
                self._send_json({"ok": False, "error": "turn not found", "turnId": turn_id}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(response)
            return
        if path == "/greeting":
            if not self._authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                self._send_json(self.server.bridge.synthesize_greeting())
            except Exception as exc:
                LOGGER.exception("Room audio greeting failed")
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path not in {"/", "/health"}:
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(
            {
                "ok": True,
                "service": "operation-jarvis-room-audio",
                "wakeWords": list(WAKE_WORDS),
                "transcriptWakeCheckEnabled": False,
                "model": self.server.bridge.model,
                "thinking": self.server.bridge.thinking,
                "ttsLeadingSilenceMs": DEFAULT_TTS_LEADING_SILENCE_MS,
                "processingAckEnabled": PROCESSING_ACK_ENABLED,
                "processingAckText": PROCESSING_ACK_TEXT if PROCESSING_ACK_ENABLED else "",
                "greetingSupported": True,
                "greetingEnabled": ROOM_GREETING_ENABLED,
                "greetingTextOverride": bool(ROOM_GREETING_TEXT),
                "asyncAckSupported": True,
                "asyncPollAfterSeconds": ASYNC_POLL_AFTER_SECONDS,
            }
        )

    def do_POST(self) -> None:  # noqa: N802 - stdlib method name
        if self.path.rstrip("/") != "/turn":
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return

        try:
            content_length = int(self.headers.get("content-length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0:
            self._send_json({"ok": False, "error": "empty request"}, HTTPStatus.BAD_REQUEST)
            return
        if content_length > self.server.max_request_bytes:
            self._send_json({"ok": False, "error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            audio_b64 = payload.get("audioWavBase64") or payload.get("audio_wav_b64")
            if not isinstance(audio_b64, str) or not audio_b64.strip():
                raise ValueError("audioWavBase64 is required")
            audio_bytes = base64.b64decode(audio_b64, validate=True)
            require_wake_word = bool(payload.get("requireWakeWord", payload.get("require_wake_word", True)))
            async_ack = bool(payload.get("asyncAck", payload.get("async_ack", False)))
        except Exception as exc:
            self._send_json({"ok": False, "error": f"bad request: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = Path(tmp.name)

        try:
            if async_ack:
                response = self.server.bridge.handle_wav_async_ack(wav_path, require_wake_word=require_wake_word)
            else:
                response = self.server.bridge.handle_wav(wav_path, require_wake_word=require_wake_word)
            self._send_json(response)
        except discord_voice.VoicePipelineNoOutputError as exc:
            self._send_json({"ok": True, "accepted": False, "reason": str(exc)})
        except Exception as exc:
            LOGGER.exception("Room audio turn failed")
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            wav_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config.get_str_env("JARVIS_ROOM_AUDIO_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=config.get_int_env("JARVIS_ROOM_AUDIO_PORT", DEFAULT_PORT, minimum=1))
    parser.add_argument("--token", default=config.get_str_env("JARVIS_ROOM_AUDIO_TOKEN", ""), help="Optional x-jarvis-room-token value")
    parser.add_argument("--max-request-bytes", type=int, default=config.get_int_env("JARVIS_ROOM_AUDIO_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES, minimum=1))
    parser.add_argument("--warm-up", action="store_true", help="Validate/preload ASR and TTS before serving")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bridge = RoomAudioBridge()
    try:
        bridge.warm_processing_ack()
    except Exception:
        LOGGER.warning("Failed to warm room-audio processing acknowledgement", exc_info=True)
    if args.warm_up:
        LOGGER.info("Warming up room-audio pipeline...")
        bridge.warm_up()
    server = RoomAudioHTTPServer((args.host, args.port), RoomAudioHandler)
    server.bridge = bridge
    server.token = args.token.strip()
    server.max_request_bytes = args.max_request_bytes
    LOGGER.info("Operation JARVIS room-audio server listening on http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Room-audio server stopping")
    finally:
        bridge.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
