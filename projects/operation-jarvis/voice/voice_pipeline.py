from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import random
import re
import queue
import tempfile
import threading
import time
import unicodedata
import wave
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from huggingface_hub import hf_hub_download
from piper import PiperVoice, SynthesisConfig
import requests

import config
import asr_backends

LOGGER = config.get_logger("operation_jarvis.voice.pipeline")

JARVIS_VOICE_WAKE_WORD = config.get_str_env(
    "JARVIS_VOICE_WAKE_WORD", "jarvis,arvis,charvis,travis,darvish,charmavis"
).strip()
JARVIS_VOICE_WAKE_WORDS = tuple(
    dict.fromkeys(
        word.strip()
        for word in re.split(r"[,;|]", JARVIS_VOICE_WAKE_WORD)
        if word.strip()
    )
)
JARVIS_VOICE_GREETING_COOLDOWN_MINUTES = config.get_float_env(
    "JARVIS_VOICE_GREETING_COOLDOWN_MINUTES", 10.0, minimum=0.0
)
JARVIS_VOICE_GREETING_INCLUDE_STATUS = config.get_str_env(
    "JARVIS_VOICE_GREETING_INCLUDE_STATUS", "1"
).lower() not in {"0", "false", "no", "off", ""}
JARVIS_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES = (
    "JARVIS online.",
    "Systems are online.",
    "Voice link established.",
    "At your service.",
)


def voice_local_now() -> datetime:
    return datetime.now(ZoneInfo("America/Toronto"))


def parse_voice_greeting_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/Toronto"))
    return parsed.astimezone(ZoneInfo("America/Toronto"))


def format_contextual_greeting(now: datetime, last_connected_at: datetime | None) -> str:
    if last_connected_at is not None:
        elapsed = now - last_connected_at
        if timedelta(0) <= elapsed <= timedelta(minutes=JARVIS_VOICE_GREETING_COOLDOWN_MINUTES):
            base = random.choice(("Back already, sir?", "Returned so soon, sir?", "Welcome back, sir. That was quick."))
            if not JARVIS_VOICE_GREETING_INCLUDE_STATUS:
                return base
            suffixes = (*JARVIS_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES, "I'll pretend not to judge.")
            return f"{base} {random.choice(suffixes)}"
    if 5 <= now.hour < 12:
        base = random.choice(("Good morning, sir.", "Morning, sir."))
    elif 12 <= now.hour < 18:
        base = random.choice(("Good afternoon, sir.", "Afternoon, sir."))
    elif 18 <= now.hour < 24:
        base = random.choice(("Good evening, sir.", "Evening, sir."))
    else:
        base = random.choice(("You're up late, sir.", "Late night, sir."))
    if not JARVIS_VOICE_GREETING_INCLUDE_STATUS:
        return base
    return f"{base} {random.choice(JARVIS_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES)}"


def normalize_voice_transcript_wake_words(transcript: str) -> str:
    """Replace wake-word aliases with the canonical `jarvis` before LLM prompting."""
    normalized = transcript or ""
    for wake_word in JARVIS_VOICE_WAKE_WORDS:
        if wake_word.casefold() == "jarvis":
            continue
        normalized = re.sub(rf"(?<!\w){re.escape(wake_word)}(?!\w)", "jarvis", normalized, flags=re.IGNORECASE)
    return normalized.strip()


def _delete_temporary_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            LOGGER.exception("Failed to delete temporary file %s", path)


DEFAULT_VOICE_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_VOICE_ASR_BACKEND = "omlx"
DEFAULT_VOICE_ASR_MODEL = "mlx-community/whisper-large-v3-turbo-asr-4bit"
DEFAULT_VOICE_APPLE_ASR_HELPER = str(
    Path(__file__).resolve().parent / "apple_asr" / ".build" / "release" / "jarvis-apple-asr"
)
DEFAULT_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS = (
    "Jarvis,stop,Pickering,PowerConf,oMLX,family room light,family room TV,"
    "family room speakers,Air Purifier"
)
DEFAULT_VOICE_LLM_MODEL = "Qwen3.5-9B-6bit"
DEFAULT_VOICE_TTS_BACKEND = "piper"
DEFAULT_VOICE_TTS_PIPER_REPO_ID = "jgkawell/jarvis"
DEFAULT_VOICE_TTS_PIPER_QUALITY = "high"
PIPER_JARVIS_MODEL_PATHS = {
    "medium": (
        "en/en_GB/jarvis/medium/jarvis-medium.onnx",
        "en/en_GB/jarvis/medium/jarvis-medium.onnx.json",
    ),
    "high": (
        "en/en_GB/jarvis/high/jarvis-high.onnx",
        "en/en_GB/jarvis/high/jarvis-high.onnx.json",
    ),
}
DEFAULT_VOICE_SYSTEM_PROMPT = (
    "You are JARVIS in a live voice call, and you should talk like him. "
    "Reply naturally for spoken audio. Keep responses concise. Usually one or two short sentences. "
    "Be only slightly sarcastic. Always refer to the person speaking with you as sir; never say the phrase 'the user'. "
    "Never respond with any emojis. "
    "Avoid markdown, bullets, tables, code blocks, and long lists unless explicitly requested. "
    "When speaking technical values, write units out in words, for example say megabytes per second instead of MB/s. "
    "If you need more time or context, say so briefly."
)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_THINKING_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_HTML_TAG_RE = re.compile(r"<[^>\n]+>")
_CHAT_MARKUP_RE = re.compile(r"<(?:(?:@!?|@&|#)\d+|a?:[A-Za-z0-9_~]+:\d+)>")
_MARKDOWN_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_REPEAT_DEDUPE_MIN_KEY_CHARS = 60
_TTS_SEGMENT_DEDUPE_MIN_KEY_CHARS = 40


def _repeat_dedupe_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def _dedupe_repeated_reply_text(text: str) -> str:
    """Collapse exact repeated generated replies such as "A B. A B." to "A B."."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(_repeat_dedupe_key(text)) < _REPEAT_DEDUPE_MIN_KEY_CHARS:
        return text

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(text) if part.strip()]
    for repeat_count in (2, 3):
        if len(sentences) < repeat_count or len(sentences) % repeat_count != 0:
            continue
        block_size = len(sentences) // repeat_count
        blocks = [" ".join(sentences[index * block_size : (index + 1) * block_size]).strip() for index in range(repeat_count)]
        first_key = _repeat_dedupe_key(blocks[0])
        if len(first_key) >= _REPEAT_DEDUPE_MIN_KEY_CHARS and all(_repeat_dedupe_key(block) == first_key for block in blocks[1:]):
            return blocks[0]

    words = text.split()
    for repeat_count in (2, 3):
        if len(words) < repeat_count or len(words) % repeat_count != 0:
            continue
        block_size = len(words) // repeat_count
        blocks = [" ".join(words[index * block_size : (index + 1) * block_size]).strip() for index in range(repeat_count)]
        first_key = _repeat_dedupe_key(blocks[0])
        if len(first_key) >= _REPEAT_DEDUPE_MIN_KEY_CHARS and all(_repeat_dedupe_key(block) == first_key for block in blocks[1:]):
            return blocks[0]

    return text


def _tts_segment_dedupe_key(text: str) -> str:
    key = _repeat_dedupe_key(text)
    return key if len(key) >= _TTS_SEGMENT_DEDUPE_MIN_KEY_CHARS else ""


def _bounded_tts_chunks(text: str, maximum_chars: int) -> list[str]:
    """Split prose at word boundaries without dropping any non-whitespace text."""
    remaining = re.sub(r"\s+", " ", text or "").strip()
    if not remaining:
        return []
    limit = max(1, maximum_chars)
    chunks: list[str] = []
    while len(remaining) > limit:
        cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _sanitize_text_for_piper_retry(text: str) -> str:
    """Conservative fallback for Piper segments with awkward Unicode/markup.

    Piper usually handles normal punctuation, but occasional generated strings
    can make synthesis fail before a WAV header is written. Retry with plain
    ASCII-ish prose rather than losing the entire room-audio response.
    """
    replacements = {
        "—": ", ",
        "–": "-",
        "−": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "•": ", ",
        "→": " to ",
        "←": " from ",
        "×": " by ",
        "&": " and ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 .,;:!?$%()'\"/+-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _env_bool(name: str, default: bool) -> bool:
    raw_default = "1" if default else "0"
    return config.get_str_env(name, raw_default).lower() not in {"0", "false", "no", "off"}


def _env_string_tuple(name: str, default: str = "") -> tuple[str, ...]:
    raw = config.get_str_env(name, default, strip=False)
    return tuple(
        dict.fromkeys(
            value.strip()
            for value in re.split(r"[,;|\n]", raw)
            if value.strip()
        )
    )[:100]


def _json_or_text(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


class VoicePipelineError(RuntimeError):
    """Base error for voice pipeline failures."""


class VoicePipelineNoOutputError(VoicePipelineError):
    """Raised when a valid voice turn produces no playable speech."""


VoiceResponseCallback = Callable[[str, Callable[[str], None] | None, object | None], str]
VoiceCancelCallback = Callable[[object | None], bool]
VoiceSteeringCallback = Callable[[object | None, str], bool]


@dataclass(frozen=True)
class VoicePipelineConfig:
    base_url: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_BASE_URL", DEFAULT_VOICE_BASE_URL).rstrip("/"))
    api_key: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_API_KEY", config.get_str_env("OMLX_API_KEY", "")))
    asr_backend: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_ASR_BACKEND", DEFAULT_VOICE_ASR_BACKEND))
    asr_fallback_backend: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_ASR_FALLBACK_BACKEND", ""))
    interrupt_asr_backend: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_INTERRUPT_ASR_BACKEND", ""))
    interrupt_asr_fallback_backend: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_INTERRUPT_ASR_FALLBACK_BACKEND", ""))
    asr_model: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_ASR_MODEL", DEFAULT_VOICE_ASR_MODEL))
    asr_language: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_ASR_LANGUAGE", "en"))
    apple_asr_helper_path: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_APPLE_ASR_HELPER", DEFAULT_VOICE_APPLE_ASR_HELPER))
    apple_asr_locale: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_APPLE_ASR_LOCALE", "en-CA"))
    apple_asr_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_APPLE_ASR_TIMEOUT_SECONDS", 15.0, minimum=1.0))
    apple_asr_contextual_strings: tuple[str, ...] = field(
        default_factory=lambda: _env_string_tuple(
            "JARVIS_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS",
            DEFAULT_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS,
        )
    )
    llm_model: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_LLM_MODEL", DEFAULT_VOICE_LLM_MODEL))
    llm_max_tokens: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_LLM_MAX_TOKENS", 120, minimum=16))
    llm_temperature: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_LLM_TEMPERATURE", 0.4, minimum=0.0))
    llm_top_p: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_LLM_TOP_P", 0.9, minimum=0.0))
    llm_history_turns: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_HISTORY_TURNS", 4, minimum=0))
    llm_disable_thinking: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_LLM_DISABLE_THINKING", True))
    tts_backend: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_TTS_BACKEND", DEFAULT_VOICE_TTS_BACKEND).lower())
    tts_speed: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_SPEED", 1.0, minimum=0.25))
    tts_piper_repo_id: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_TTS_PIPER_REPO_ID", DEFAULT_VOICE_TTS_PIPER_REPO_ID))
    tts_piper_quality: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_TTS_PIPER_QUALITY", DEFAULT_VOICE_TTS_PIPER_QUALITY).lower())
    tts_piper_length_scale: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_PIPER_LENGTH_SCALE", 1.15, minimum=0.1))
    tts_piper_volume: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_PIPER_VOLUME", 0.95, minimum=0.0))
    tts_piper_noise_scale: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_PIPER_NOISE_SCALE", 0.55, minimum=0.0))
    tts_piper_noise_w_scale: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_PIPER_NOISE_W_SCALE", 0.70, minimum=0.0))
    stream_tts: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_STREAM_TTS", True))
    stream_start_words: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_STREAM_START_WORDS", 0, minimum=0))
    tts_strip_urls: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_TTS_STRIP_URLS", True))
    tts_strip_code: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_TTS_STRIP_CODE", True))
    tts_strip_markdown: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_TTS_STRIP_MARKDOWN", True))
    tts_strip_chat_markup: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_TTS_STRIP_CHAT_MARKUP", True))
    max_tts_segments: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_TTS_MAX_SEGMENTS", 0, minimum=0))
    max_tts_chars_per_segment: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_TTS_MAX_CHARS_PER_SEGMENT", 220, minimum=40))
    system_prompt: str = field(default_factory=lambda: config.get_str_env("JARVIS_VOICE_SYSTEM_PROMPT", DEFAULT_VOICE_SYSTEM_PROMPT, strip=False).strip())
    asr_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_ASR_TIMEOUT_SECONDS", 120.0, minimum=1.0))
    llm_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_LLM_TIMEOUT_SECONDS", 120.0, minimum=1.0))
    tts_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_TTS_TIMEOUT_SECONDS", 180.0, minimum=1.0))
    model_load_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_MODEL_LOAD_TIMEOUT_SECONDS", 240.0, minimum=1.0))
    unload_between_stages: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_UNLOAD_BETWEEN_STAGES", False))
    request_retries: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_REQUEST_RETRIES", 2, minimum=0))
    request_retry_backoff_seconds: float = field(default_factory=lambda: config.get_float_env("JARVIS_VOICE_REQUEST_RETRY_BACKOFF_SECONDS", 0.75, minimum=0.0))
    tts_max_bytes: int = field(default_factory=lambda: config.get_int_env("JARVIS_VOICE_TTS_MAX_BYTES", 100 * 1024 * 1024, minimum=1))
    require_configured_models: bool = field(default_factory=lambda: _env_bool("JARVIS_VOICE_REQUIRE_CONFIGURED_MODELS", True))


@dataclass(frozen=True)
class VoicePipelineResult:
    transcript: str
    reply_text: str
    audio_paths: list[Path]
    input_seconds: float
    asr_seconds: float
    llm_seconds: float
    tts_seconds: float
    total_seconds: float

    @property
    def output_seconds(self) -> float:
        return sum(_audio_duration_seconds(path) for path in self.audio_paths)


class VoicePipeline:
    """Pluggable ASR, optional oMLX chat, and configurable local/oMLX TTS."""

    def __init__(
        self,
        pipeline_config: VoicePipelineConfig | None = None,
        *,
        response_callback: VoiceResponseCallback | None = None,
    ) -> None:
        self.config = pipeline_config or VoicePipelineConfig()
        self.response_callback = response_callback
        self._session = requests.Session()
        self._session_lock = threading.Lock()
        self._history: list[dict[str, str]] = []
        self._history_lock = threading.Lock()
        self._active_llm_response: requests.Response | None = None
        self._active_llm_response_lock = threading.Lock()
        self._piper_voice: PiperVoice | None = None
        self._piper_voice_key: tuple[str, str] | None = None
        self._piper_lock = threading.RLock()
        self._asr_status_lock = threading.Lock()
        self._asr_status_cached_at = 0.0
        self._asr_status_cache: dict[str, Any] = {}

        try:
            self._asr_backend = asr_backends.normalize_asr_backend(self.config.asr_backend)
            self._asr_fallback_backend = asr_backends.normalize_asr_backend(
                self.config.asr_fallback_backend,
                allow_empty=True,
            )
            raw_interrupt_backend = str(self.config.interrupt_asr_backend or "").strip()
            self._interrupt_asr_backend = (
                asr_backends.normalize_asr_backend(raw_interrupt_backend, allow_empty=True)
                or self._asr_backend
            )
            raw_interrupt_fallback = str(self.config.interrupt_asr_fallback_backend or "").strip()
            self._interrupt_asr_fallback_backend = asr_backends.normalize_asr_backend(
                raw_interrupt_fallback,
                allow_empty=True,
            )
            if not raw_interrupt_backend and not raw_interrupt_fallback:
                self._interrupt_asr_fallback_backend = self._asr_fallback_backend
        except ValueError as exc:
            raise VoicePipelineError(str(exc)) from exc

        if self._asr_fallback_backend == self._asr_backend:
            self._asr_fallback_backend = ""
        if self._interrupt_asr_fallback_backend == self._interrupt_asr_backend:
            self._interrupt_asr_fallback_backend = ""

        apple_settings = {
            "helper_path": Path(self.config.apple_asr_helper_path),
            "locale": self.config.apple_asr_locale,
            "timeout_seconds": self.config.apple_asr_timeout_seconds,
            "contextual_strings": self.config.apple_asr_contextual_strings,
        }
        self._asr_backends: dict[str, asr_backends.ASRBackend] = {
            "omlx": asr_backends.CallbackASRBackend("omlx", self._transcribe_omlx),
            "apple-speech": asr_backends.AppleSpeechASRBackend(
                asr_backends.AppleSpeechASRSettings(engine="speech", **apple_settings)
            ),
            "apple-dictation": asr_backends.AppleSpeechASRBackend(
                asr_backends.AppleSpeechASRSettings(engine="dictation", **apple_settings)
            ),
        }

    @property
    def configured_asr_backends(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                backend
                for backend in (
                    self._asr_backend,
                    self._asr_fallback_backend,
                    self._interrupt_asr_backend,
                    self._interrupt_asr_fallback_backend,
                )
                if backend
            )
        )

    @property
    def configured_models(self) -> tuple[str, ...]:
        models: list[str] = []
        if "omlx" in self.configured_asr_backends:
            models.append(self.config.asr_model)
        if self.response_callback is None:
            models.append(self.config.llm_model)
        return tuple(dict.fromkeys(model for model in models if model))

    @property
    def streams_tts_while_llm_generates(self) -> bool:
        return self.config.stream_tts and self.config.tts_backend == "piper"

    def asr_status(self) -> dict[str, Any]:
        with self._asr_status_lock:
            now = time.monotonic()
            if self._asr_status_cache and now - self._asr_status_cached_at < 30.0:
                return dict(self._asr_status_cache)
            status: dict[str, Any] = {
                "backend": self._asr_backend,
                "fallbackBackend": self._asr_fallback_backend,
                "interruptBackend": self._interrupt_asr_backend,
                "interruptFallbackBackend": self._interrupt_asr_fallback_backend,
            }
            try:
                primary_status = self._asr_backends[self._asr_backend].status()
                status.update(primary_status)
            except Exception:
                LOGGER.debug("Failed to query primary ASR status", exc_info=True)
                primary_status = {
                    "ok": False,
                    "backend": self._asr_backend,
                    "available": False,
                    "error": f"{self._asr_backend} unavailable",
                }
                status.update(primary_status)

            if self._interrupt_asr_backend == self._asr_backend:
                interrupt_status = dict(primary_status)
            else:
                try:
                    interrupt_status = self._asr_backends[self._interrupt_asr_backend].status()
                except Exception:
                    LOGGER.debug("Failed to query interrupt ASR status", exc_info=True)
                    interrupt_status = {
                        "ok": False,
                        "backend": self._interrupt_asr_backend,
                        "available": False,
                        "error": f"{self._interrupt_asr_backend} unavailable",
                    }
            status["interrupt"] = {
                "fallbackBackend": self._interrupt_asr_fallback_backend,
                **interrupt_status,
            }
            self._asr_status_cache = dict(status)
            self._asr_status_cached_at = now
            return status

    def cancel_active_response(self) -> bool:
        """Close an active direct-oMLX streaming response used by the standalone runner."""
        with self._active_llm_response_lock:
            response = self._active_llm_response
        if response is None:
            return False
        try:
            response.close()
        except Exception:
            LOGGER.debug("Failed to close active direct-oMLX voice response", exc_info=True)
        return True

    def _warm_apple_asr_backends(self) -> None:
        routes = (
            (self._asr_backend, self._asr_fallback_backend),
            (self._interrupt_asr_backend, self._interrupt_asr_fallback_backend),
        )
        for backend_name in self.configured_asr_backends:
            if not backend_name.startswith("apple-"):
                continue
            try:
                status = self._asr_backends[backend_name].warm_up()
                LOGGER.info("Apple ASR ready: %s", status)
            except Exception as exc:
                required = any(primary == backend_name and not fallback for primary, fallback in routes)
                if required:
                    raise VoicePipelineError(f"Required {backend_name} ASR backend is unavailable: {exc}") from exc
                LOGGER.warning("Optional %s ASR backend is unavailable; configured fallback remains active: %s", backend_name, exc)

    def warm_up(self) -> None:
        """Validate configured ASR/LLM stages and the selected TTS backend."""
        self._validate_tts_backend()
        self._warm_apple_asr_backends()
        LOGGER.info(
            "Voice pipeline: asr=%s fallback=%s interrupt_asr=%s interrupt_fallback=%s "
            "response_backend=%s llm=%s tts_backend=%s tts_voice=%s",
            self._asr_backend,
            self._asr_fallback_backend or "none",
            self._interrupt_asr_backend,
            self._interrupt_asr_fallback_backend or "none",
            "pi_rpc" if self.response_callback is not None else "omlx_chat",
            self.config.llm_model if self.response_callback is None else "n/a",
            self.config.tts_backend,
            f"{self.config.tts_piper_repo_id}:{self.config.tts_piper_quality}",
        )

        configured_models = self.configured_models
        if not configured_models:
            return

        models_url = f"{self.config.base_url}/models"
        response = self._request("GET", models_url, stage="models", headers=self._headers(), timeout=20)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise VoicePipelineError(f"Failed to query oMLX models: {response.text[:500]}") from exc

        payload = response.json()
        available = {
            item.get("id")
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        missing = [
            model
            for model in configured_models
            if model and model not in available and model.rsplit("/", 1)[-1] not in available
        ]
        if missing and self.config.require_configured_models:
            raise VoicePipelineError(
                "Configured oMLX voice model(s) are not installed/visible: " + ", ".join(missing)
            )

        load_targets = [model for model in configured_models if model not in missing]
        if load_targets:
            LOGGER.info("Preloading oMLX voice models concurrently: %s", load_targets)
            loaded: dict[str, str] = {}
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(load_targets),
                thread_name_prefix="jarvis-voice-preload",
            ) as executor:
                futures = {executor.submit(self._load_model, model): model for model in load_targets}
                for future in concurrent.futures.as_completed(futures):
                    requested_model = futures[future]
                    loaded[requested_model] = future.result()
            LOGGER.info("Preloaded oMLX voice models: %s", loaded)

    def synthesize_notice(self, text: str) -> Path:
        """Synthesize a short local voice notice, such as an acknowledgement."""
        cleaned = self._clean_text_for_tts(text)
        if not cleaned:
            raise VoicePipelineNoOutputError("Voice notice text is empty.")
        return self._synthesize_segment(cleaned)

    def synthesize_text(self, text: str) -> list[Path]:
        """Synthesize all playable final prose with the canonical JARVIS voice."""
        audio_paths: list[Path] = []
        try:
            # Clean while line structure is intact so Markdown tables can be
            # converted to speech before chunking. The old order collapsed the
            # response first, then silently shortened long sections to one
            # segment, producing a valid but incomplete Watch WAV every time.
            cleaned_text = self._clean_text_for_tts(text)
            for segment in self._split_for_tts(cleaned_text):
                if not segment:
                    continue
                audio_paths.append(self._synthesize_segment(segment))
        except Exception:
            for path in audio_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    LOGGER.debug("Failed to clean partial text TTS file %s", path, exc_info=True)
            raise
        if not audio_paths:
            raise VoicePipelineNoOutputError("Text contained no playable speech.")
        return audio_paths

    def _asr_route(self, purpose: str) -> tuple[str, str]:
        if purpose == "turn":
            return self._asr_backend, self._asr_fallback_backend
        if purpose == "interrupt":
            return self._interrupt_asr_backend, self._interrupt_asr_fallback_backend
        raise ValueError(f"Unsupported ASR purpose: {purpose!r}")

    def _transcribe_with_backend(self, backend_name: str, input_wav_path: Path) -> str:
        backend = self._asr_backends.get(backend_name)
        if backend is None:
            raise VoicePipelineError(f"ASR backend is not initialized: {backend_name}")
        transcript = " ".join(backend.transcribe(input_wav_path).split()).strip()
        if not transcript:
            raise VoicePipelineNoOutputError(f"{backend_name} ASR produced no transcript.")
        return transcript

    def transcribe_audio(self, input_wav_path: Path, *, purpose: str = "turn") -> tuple[str, float, float]:
        """Transcribe a WAV and return transcript, input duration, and ASR duration."""
        input_seconds = _audio_duration_seconds(input_wav_path)
        primary, fallback = self._asr_route(purpose)
        attempted: list[str] = []
        asr_started_at = time.monotonic()
        try:
            attempted.append(primary)
            try:
                transcript = self._transcribe_with_backend(primary, input_wav_path)
                used_backend = primary
            except Exception as primary_error:
                if not fallback:
                    if isinstance(primary_error, VoicePipelineError):
                        raise
                    raise VoicePipelineError(f"{primary} ASR failed: {primary_error}") from primary_error
                LOGGER.warning(
                    "Primary %s ASR failed for %s (%s); trying fallback %s",
                    primary,
                    purpose,
                    primary_error,
                    fallback,
                )
                attempted.append(fallback)
                try:
                    transcript = self._transcribe_with_backend(fallback, input_wav_path)
                    used_backend = fallback
                except Exception as fallback_error:
                    raise VoicePipelineError(
                        f"ASR primary {primary} failed ({primary_error}); fallback {fallback} failed ({fallback_error})"
                    ) from fallback_error
        finally:
            if self.config.unload_between_stages and "omlx" in attempted:
                self._unload_model(self.config.asr_model)
        asr_seconds = time.monotonic() - asr_started_at
        LOGGER.info(
            "Voice ASR: purpose=%s backend=%s input=%.2fs elapsed=%.2fs",
            purpose,
            used_backend,
            input_seconds,
            asr_seconds,
        )
        return transcript, input_seconds, asr_seconds

    def synthesize_turn(
        self,
        input_wav_path: Path,
        audio_path_callback: Callable[[Path, int], None] | None = None,
        turn_context: object | None = None,
        *,
        transcript: str | None = None,
        input_seconds: float | None = None,
        asr_seconds: float | None = None,
        started_at: float | None = None,
    ) -> VoicePipelineResult:
        """Run one user voice turn through ASR -> voice LLM -> TTS.

        When TTS streaming is enabled and a callback is supplied, complete
        sentence chunks are synthesized as the LLM stream arrives.  Each WAV
        path is passed to the callback as soon as it is ready, so local playback
        can begin before the LLM has finished the whole reply.
        """
        started_at = started_at if started_at is not None else time.monotonic()
        if transcript is None:
            transcript, input_seconds, asr_seconds = self.transcribe_audio(input_wav_path)
        else:
            transcript = transcript.strip()
            input_seconds = input_seconds if input_seconds is not None else _audio_duration_seconds(input_wav_path)
            asr_seconds = asr_seconds if asr_seconds is not None else 0.0
            if not transcript:
                raise VoicePipelineNoOutputError("ASR produced no transcript.")

        llm_transcript = normalize_voice_transcript_wake_words(transcript)

        audio_paths: list[Path] = []
        stream_tts = self.streams_tts_while_llm_generates and audio_path_callback is not None
        llm_started_at = time.monotonic()
        tts_seconds = 0.0
        try:
            if stream_tts:
                reply_text, tts_seconds = self._complete_and_synthesize_streaming(
                    llm_transcript,
                    audio_paths=audio_paths,
                    audio_path_callback=audio_path_callback,
                    turn_context=turn_context,
                )
            else:
                reply_text = self._complete(llm_transcript, turn_context=turn_context)
        except Exception:
            # If the caller is streaming playback, it owns cleanup for paths that
            # may already have been handed off. Otherwise clean partial TTS here.
            if audio_path_callback is None:
                for path in audio_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        LOGGER.debug("Failed to clean partial TTS file %s", path, exc_info=True)
            raise
        finally:
            if self.config.unload_between_stages and self.response_callback is None:
                self._unload_model(self.config.llm_model)
        llm_seconds = max(0.0, time.monotonic() - llm_started_at - tts_seconds)
        if not reply_text:
            raise VoicePipelineNoOutputError("Voice LLM produced no reply text.")

        if not stream_tts:
            tts_started_at = time.monotonic()
            spoken_tts_segment_keys: set[str] = set()
            try:
                for segment in self._split_for_tts(reply_text):
                    cleaned_segment = self._clean_text_for_tts(segment)
                    if not cleaned_segment:
                        continue
                    segment_key = _tts_segment_dedupe_key(cleaned_segment)
                    if segment_key and segment_key in spoken_tts_segment_keys:
                        LOGGER.debug("Skipping duplicate voice TTS segment: %r", cleaned_segment[:160])
                        continue
                    audio_paths.append(self._synthesize_segment(cleaned_segment))
                    if segment_key:
                        spoken_tts_segment_keys.add(segment_key)
            except Exception:
                for path in audio_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        LOGGER.debug("Failed to clean partial TTS file %s", path, exc_info=True)
                raise
            tts_seconds = time.monotonic() - tts_started_at

        if not audio_paths:
            raise VoicePipelineNoOutputError("TTS produced no audio.")

        total_seconds = time.monotonic() - started_at
        LOGGER.debug(
            "Voice pipeline turn: input=%.2fs asr=%.2fs llm=%.2fs tts=%.2fs total=%.2fs transcript=%r reply=%r",
            input_seconds,
            asr_seconds,
            llm_seconds,
            tts_seconds,
            total_seconds,
            transcript[:160],
            reply_text[:240],
        )
        return VoicePipelineResult(
            transcript=transcript,
            reply_text=reply_text,
            audio_paths=audio_paths,
            input_seconds=input_seconds,
            asr_seconds=asr_seconds,
            llm_seconds=llm_seconds,
            tts_seconds=tts_seconds,
            total_seconds=total_seconds,
        )

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {"Connection": "close"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _reset_session(self) -> None:
        with self._session_lock:
            old_session = self._session
            self._session = requests.Session()
        try:
            old_session.close()
        except Exception:
            LOGGER.debug("Failed to close stale oMLX HTTP session", exc_info=True)

    def _request(
        self,
        method: str,
        url: str,
        *,
        stage: str,
        rewind_on_retry: list[Any] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        attempts = max(1, self.config.request_retries + 1)
        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            if rewind_on_retry:
                for file_obj in rewind_on_retry:
                    try:
                        file_obj.seek(0)
                    except Exception:
                        LOGGER.debug("Failed to rewind request body before oMLX %s attempt", stage, exc_info=True)
            try:
                response = requests.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                self._reset_session()
                if attempt >= attempts:
                    break
                self._sleep_before_retry(stage, attempt, attempts, exc)
                continue

            if response.status_code in retry_statuses and attempt < attempts:
                last_error = VoicePipelineError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.close()
                self._reset_session()
                self._sleep_before_retry(stage, attempt, attempts, last_error)
                continue
            return response

        raise VoicePipelineError(f"oMLX {stage} request failed after {attempts} attempt(s): {last_error}") from last_error

    def _sleep_before_retry(self, stage: str, attempt: int, attempts: int, error: BaseException) -> None:
        delay = self.config.request_retry_backoff_seconds * attempt
        LOGGER.warning(
            "oMLX %s request failed on attempt %d/%d: %s; retrying in %.2fs",
            stage,
            attempt,
            attempts,
            error,
            delay,
        )
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _model_name_candidates(model_id: str) -> list[str]:
        candidates: list[str] = []
        for candidate in (model_id, model_id.rsplit("/", 1)[-1]):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _load_model(self, model_id: str) -> str:
        """Load a configured oMLX model, trying both full repo IDs and local short names."""
        last_response_text = ""
        for candidate in self._model_name_candidates(model_id):
            url = f"{self.config.base_url}/models/{quote(candidate, safe='')}/load"
            response = self._request(
                "POST",
                url,
                stage=f"load {candidate}",
                headers=self._headers(),
                timeout=self.config.model_load_timeout_seconds,
            )
            last_response_text = response.text[:500]
            if response.status_code == 404:
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise VoicePipelineError(f"Failed to load oMLX model {candidate}: {_json_or_text(response)}") from exc
            LOGGER.info("Loaded oMLX voice model: requested=%s loaded=%s", model_id, candidate)
            return candidate
        raise VoicePipelineError(f"Failed to load oMLX model {model_id}: model endpoint not found. {last_response_text}")

    def _unload_model(self, model_id: str) -> None:
        """Best-effort oMLX model unload to keep ASR/LLM/TTS from piling up in memory."""
        if not model_id:
            return

        for candidate in self._model_name_candidates(model_id):
            url = f"{self.config.base_url}/models/{quote(candidate, safe='')}/unload"
            try:
                response = self._request("POST", url, stage=f"unload {candidate}", headers=self._headers(), timeout=15)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                LOGGER.debug("Unloaded oMLX voice model after stage: %s", candidate)
                return
            except Exception:
                LOGGER.debug("Best-effort oMLX model unload failed for %s", candidate, exc_info=True)

    def _transcribe_omlx(self, audio_path: Path) -> str:
        url = f"{self.config.base_url}/audio/transcriptions"
        form: dict[str, str] = {
            "model": self.config.asr_model,
            "response_format": "json",
            "temperature": "0",
        }
        if self.config.asr_language:
            form["language"] = self.config.asr_language
        with audio_path.open("rb") as file_obj:
            response = self._request(
                "POST",
                url,
                stage="ASR",
                headers=self._headers(),
                data=form,
                files={"file": (audio_path.name, file_obj, "audio/wav")},
                timeout=self.config.asr_timeout_seconds,
                rewind_on_retry=[file_obj],
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise VoicePipelineError(f"oMLX ASR failed: {_json_or_text(response)}") from exc
        payload = response.json()
        text = payload.get("text", "") if isinstance(payload, dict) else ""
        return " ".join(str(text).split()).strip()

    def _complete(self, transcript: str, *, turn_context: object | None = None) -> str:
        if self.response_callback is not None:
            text = self.response_callback(transcript, None, turn_context)
            reply_text = self._clean_reply_text(text)
            self._remember_turn(transcript, reply_text)
            return reply_text

        url = f"{self.config.base_url}/chat/completions"
        with self._history_lock:
            messages: list[dict[str, str]] = [{"role": "system", "content": self.config.system_prompt}]
            messages.extend(self._history[-self.config.llm_history_turns * 2 :] if self.config.llm_history_turns else [])
            messages.append({"role": "user", "content": transcript})
        payload: dict[str, Any] = {
            "model": self.config.llm_model,
            "messages": messages,
            "max_tokens": self.config.llm_max_tokens,
            "temperature": self.config.llm_temperature,
            "top_p": self.config.llm_top_p,
            "stream": False,
        }
        if self.config.llm_disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            payload["thinking_budget"] = 0
        response = self._request(
            "POST",
            url,
            stage="voice LLM",
            headers=self._headers(json_body=True),
            data=json.dumps(payload),
            timeout=self.config.llm_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise VoicePipelineError(f"oMLX voice LLM failed: {_json_or_text(response)}") from exc
        data = response.json()
        text = ""
        if isinstance(data, dict):
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(message, dict):
                    text = str(message.get("content") or "")
        reply_text = self._clean_reply_text(text)
        self._remember_turn(transcript, reply_text)
        return reply_text

    def _complete_and_synthesize_streaming(
        self,
        transcript: str,
        *,
        audio_paths: list[Path],
        audio_path_callback: Callable[[Path, int], None],
        turn_context: object | None = None,
    ) -> tuple[str, float]:
        if self.response_callback is not None:
            return self._complete_with_callback_and_synthesize_streaming(
                transcript,
                audio_paths=audio_paths,
                audio_path_callback=audio_path_callback,
                turn_context=turn_context,
            )

        url = f"{self.config.base_url}/chat/completions"
        with self._history_lock:
            messages: list[dict[str, str]] = [{"role": "system", "content": self.config.system_prompt}]
            messages.extend(self._history[-self.config.llm_history_turns * 2 :] if self.config.llm_history_turns else [])
            messages.append({"role": "user", "content": transcript})
        payload: dict[str, Any] = {
            "model": self.config.llm_model,
            "messages": messages,
            "max_tokens": self.config.llm_max_tokens,
            "temperature": self.config.llm_temperature,
            "top_p": self.config.llm_top_p,
            "stream": True,
        }
        if self.config.llm_disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            payload["thinking_budget"] = 0

        response = self._request(
            "POST",
            url,
            stage="streaming voice LLM",
            headers=self._headers(json_body=True),
            data=json.dumps(payload),
            timeout=self.config.llm_timeout_seconds,
            stream=True,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise VoicePipelineError(f"oMLX streaming voice LLM failed: {_json_or_text(response)}") from exc

        with self._active_llm_response_lock:
            self._active_llm_response = response

        full_text_parts: list[str] = []
        pending_tts_text = ""
        spoken_segments = 0
        spoken_tts_segment_keys: set[str] = set()
        started_speaking = False
        tts_seconds = 0.0
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line:
                    continue
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    LOGGER.debug("Ignoring non-JSON streaming LLM line: %r", line[:200])
                    continue
                delta_text = self._extract_stream_delta_content(event)
                if not delta_text:
                    continue
                full_text_parts.append(delta_text)
                pending_tts_text += delta_text
                if not started_speaking:
                    first_segment, pending_tts_text = self._pop_initial_stream_tts_segment(pending_tts_text)
                    if first_segment:
                        ready_segments = [first_segment]
                        started_speaking = True
                    else:
                        ready_segments = []
                else:
                    ready_segments, pending_tts_text = self._pop_ready_stream_tts_segments(pending_tts_text)
                for segment in ready_segments:
                    if self._tts_segment_limit_reached(spoken_segments):
                        continue
                    segment_seconds = self._synthesize_stream_segment(segment, audio_paths, audio_path_callback, spoken_tts_segment_keys)
                    if segment_seconds <= 0:
                        continue
                    tts_seconds += segment_seconds
                    spoken_segments += 1
                    started_speaking = True
        finally:
            with self._active_llm_response_lock:
                if self._active_llm_response is response:
                    self._active_llm_response = None
            response.close()

        reply_text = self._clean_reply_text("".join(full_text_parts))
        if not self._tts_segment_limit_reached(spoken_segments):
            final_text = self._clean_reply_text(pending_tts_text)
            if final_text:
                for segment in self._split_for_tts(final_text):
                    if self._tts_segment_limit_reached(spoken_segments):
                        break
                    segment_seconds = self._synthesize_stream_segment(segment, audio_paths, audio_path_callback, spoken_tts_segment_keys)
                    if segment_seconds <= 0:
                        continue
                    tts_seconds += segment_seconds
                    spoken_segments += 1
        self._remember_turn(transcript, reply_text)
        return reply_text, tts_seconds

    def _complete_with_callback_and_synthesize_streaming(
        self,
        transcript: str,
        *,
        audio_paths: list[Path],
        audio_path_callback: Callable[[Path, int], None],
        turn_context: object | None,
    ) -> tuple[str, float]:
        if self.response_callback is None:
            raise VoicePipelineError("Voice response callback is not configured.")

        delta_queue: queue.Queue[str | None] = queue.Queue()
        result: dict[str, str] = {"text": ""}
        errors: list[BaseException] = []

        def _on_delta(delta: str) -> None:
            if delta:
                delta_queue.put(delta)

        def _run_callback() -> None:
            try:
                result["text"] = self.response_callback(transcript, _on_delta, turn_context)
            except BaseException as exc:
                errors.append(exc)
            finally:
                delta_queue.put(None)

        callback_thread = threading.Thread(
            target=_run_callback,
            name="jarvis-voice-pi-response",
            daemon=True,
        )
        callback_thread.start()

        full_text_parts: list[str] = []
        pending_tts_text = ""
        spoken_segments = 0
        spoken_tts_segment_keys: set[str] = set()
        started_speaking = False
        tts_seconds = 0.0
        last_steering_generation = _turn_context_steering_generation(turn_context)
        tts_paused_until = 0.0
        pending_steering_ack = False

        def _drain_stale_delta_queue_after_steering() -> None:
            saw_done = False
            while True:
                try:
                    queued_delta = delta_queue.get_nowait()
                except queue.Empty:
                    break
                if queued_delta is None:
                    saw_done = True
            if saw_done:
                delta_queue.put(None)

        def _emit_pending_steering_ack_if_ready(*, wait: bool) -> float:
            nonlocal pending_steering_ack
            if not pending_steering_ack or not JARVIS_VOICE_PROCESSING_ACK_ENABLED or not JARVIS_VOICE_PROCESSING_ACK_TEXT:
                return 0.0
            remaining_pause = tts_paused_until - time.monotonic()
            if remaining_pause > 0:
                if not wait:
                    return 0.0
                time.sleep(remaining_pause)
            pending_steering_ack = False
            cleaned_ack = self._clean_text_for_tts(JARVIS_VOICE_PROCESSING_ACK_TEXT)
            if not cleaned_ack:
                return 0.0
            started_at = time.monotonic()
            ack_path = self._synthesize_segment(cleaned_ack)
            elapsed = time.monotonic() - started_at
            audio_paths.append(ack_path)
            audio_path_callback(ack_path, last_steering_generation)
            return elapsed

        def _handle_steering_boundary() -> bool:
            nonlocal last_steering_generation, pending_tts_text, started_speaking, tts_paused_until, spoken_segments, pending_steering_ack
            current_generation = _turn_context_steering_generation(turn_context)
            if current_generation <= last_steering_generation:
                return False
            LOGGER.debug(
                "Voice TTS steering boundary detected: generation %s -> %s; dropping queued pre-steer TTS and pausing %.2fs",
                last_steering_generation,
                current_generation,
                _turn_context_steering_tts_delay_seconds(turn_context),
            )
            last_steering_generation = current_generation
            full_text_parts.clear()
            pending_tts_text = ""
            spoken_tts_segment_keys.clear()
            spoken_segments = 0
            started_speaking = False
            pending_steering_ack = JARVIS_VOICE_PROCESSING_ACK_ENABLED and bool(JARVIS_VOICE_PROCESSING_ACK_TEXT)
            _drain_stale_delta_queue_after_steering()
            delay_seconds = _turn_context_steering_tts_delay_seconds(turn_context)
            if delay_seconds > 0:
                tts_paused_until = max(tts_paused_until, time.monotonic() + delay_seconds)
            return True

        while True:
            _handle_steering_boundary()
            try:
                delta = delta_queue.get(timeout=0.1)
            except queue.Empty:
                if not callback_thread.is_alive():
                    break
                continue

            steering_changed = _handle_steering_boundary()
            if delta is None:
                break
            if steering_changed:
                continue
            full_text_parts.append(delta)
            pending_tts_text += delta
            if time.monotonic() < tts_paused_until:
                continue
            tts_seconds += _emit_pending_steering_ack_if_ready(wait=False)
            if not started_speaking:
                first_segment, pending_tts_text = self._pop_initial_stream_tts_segment(pending_tts_text)
                if first_segment:
                    ready_segments = [first_segment]
                    started_speaking = True
                else:
                    ready_segments = []
            else:
                ready_segments, pending_tts_text = self._pop_ready_stream_tts_segments(pending_tts_text)
            if ready_segments:
                tts_seconds += _emit_pending_steering_ack_if_ready(wait=True)
            for segment in ready_segments:
                if self._tts_segment_limit_reached(spoken_segments):
                    continue
                segment_seconds = self._synthesize_stream_segment(
                    segment,
                    audio_paths,
                    audio_path_callback,
                    spoken_tts_segment_keys,
                    steering_generation=last_steering_generation,
                )
                if segment_seconds <= 0:
                    continue
                tts_seconds += segment_seconds
                spoken_segments += 1
                started_speaking = True

        callback_thread.join(timeout=1)
        if errors:
            raise errors[-1]

        reply_text = self._clean_reply_text(result.get("text") or "".join(full_text_parts))
        tts_seconds += _emit_pending_steering_ack_if_ready(wait=True)
        if not self._tts_segment_limit_reached(spoken_segments):
            final_text = self._clean_reply_text(pending_tts_text)
            if not final_text and spoken_segments == 0 and reply_text:
                # Some response backends may only provide a final text string and
                # no deltas. Preserve streamed-playback callers by falling back
                # to normal segmented TTS in that case.
                final_text = reply_text
            if final_text:
                tts_seconds += _emit_pending_steering_ack_if_ready(wait=True)
                for segment in self._split_for_tts(final_text):
                    if self._tts_segment_limit_reached(spoken_segments):
                        break
                    segment_seconds = self._synthesize_stream_segment(
                        segment,
                        audio_paths,
                        audio_path_callback,
                        spoken_tts_segment_keys,
                        steering_generation=last_steering_generation,
                    )
                    if segment_seconds <= 0:
                        continue
                    tts_seconds += segment_seconds
                    spoken_segments += 1
        self._remember_turn(transcript, reply_text)
        return reply_text, tts_seconds

    def _tts_segment_limit_reached(self, spoken_segments: int) -> bool:
        return self.config.max_tts_segments > 0 and spoken_segments >= self.config.max_tts_segments

    def _synthesize_stream_segment(
        self,
        segment: str,
        audio_paths: list[Path],
        audio_path_callback: Callable[[Path, int], None],
        spoken_tts_segment_keys: set[str],
        *,
        steering_generation: int = 0,
    ) -> float:
        cleaned = self._clean_text_for_tts(segment)
        if not cleaned:
            return 0.0
        segment_key = _tts_segment_dedupe_key(cleaned)
        if segment_key and segment_key in spoken_tts_segment_keys:
            LOGGER.debug("Skipping duplicate streamed voice TTS segment: %r", cleaned[:160])
            return 0.0
        started_at = time.monotonic()
        path = self._synthesize_segment(cleaned)
        elapsed = time.monotonic() - started_at
        audio_paths.append(path)
        audio_path_callback(path, steering_generation)
        if segment_key:
            spoken_tts_segment_keys.add(segment_key)
        return elapsed

    @staticmethod
    def _extract_stream_delta_content(event: object) -> str:
        if not isinstance(event, dict):
            return ""
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if content is not None:
                return str(content)
        message = choice.get("message")
        if isinstance(message, dict) and message.get("content") is not None:
            return str(message.get("content"))
        return ""

    def _pop_initial_stream_tts_segment(self, text: str) -> tuple[str, str]:
        """Return the first streamed TTS segment.

        By default, wait for the first complete sentence before playback starts.
        If JARVIS_VOICE_STREAM_START_WORDS is set above zero, allow an earlier
        startup segment after that many words.
        """
        if not text.strip():
            return "", text
        target_words = self.config.stream_start_words
        if target_words <= 0:
            match = _SENTENCE_BOUNDARY_RE.search(text)
            if not match:
                return "", text
            cut = match.end()
        else:
            matches = list(re.finditer(r"\S+", text))
            if len(matches) < target_words:
                return "", text
            cut = matches[target_words - 1].end()
        segment = re.sub(r"\s+", " ", text[:cut]).strip()
        remainder = text[cut:].lstrip()
        if not segment:
            return "", text
        return segment, remainder

    def _pop_ready_stream_tts_segments(self, text: str) -> tuple[list[str], str]:
        if not text.strip():
            return [], text
        matches = list(_SENTENCE_BOUNDARY_RE.finditer(text))
        if matches:
            cut = matches[-1].end()
            ready_text = re.sub(r"\s+", " ", text[:cut]).strip()
            remainder = text[cut:].lstrip()
            return self._split_for_tts(ready_text), remainder
        if len(text) > self.config.max_tts_chars_per_segment:
            cut = text.rfind(" ", 0, self.config.max_tts_chars_per_segment)
            if cut <= 0:
                cut = self.config.max_tts_chars_per_segment
            ready_text = re.sub(r"\s+", " ", text[:cut]).strip()
            remainder = text[cut:].lstrip()
            return [ready_text], remainder
        return [], text

    def _remember_turn(self, transcript: str, reply_text: str) -> None:
        if not reply_text:
            return
        with self._history_lock:
            self._history.extend([
                {"role": "user", "content": transcript},
                {"role": "assistant", "content": reply_text},
            ])
            max_messages = self.config.llm_history_turns * 2
            if max_messages > 0:
                self._history = self._history[-max_messages:]
            else:
                self._history.clear()

    def _synthesize_segment(self, text: str) -> Path:
        self._validate_tts_backend()
        try:
            return self._synthesize_segment_piper(text)
        except Exception:
            retry_text = _sanitize_text_for_piper_retry(text)
            if retry_text and retry_text != text:
                LOGGER.warning("Piper TTS segment failed; retrying with conservative text sanitization", exc_info=True)
                return self._synthesize_segment_piper(retry_text)
            raise

    def _validate_tts_backend(self) -> None:
        if self.config.tts_backend != "piper":
            raise VoicePipelineError(
                f"Unsupported JARVIS_VOICE_TTS_BACKEND={self.config.tts_backend!r}; use 'piper'."
            )
        if self.config.tts_piper_quality not in PIPER_JARVIS_MODEL_PATHS:
            valid = ", ".join(sorted(PIPER_JARVIS_MODEL_PATHS))
            raise VoicePipelineError(
                f"Unsupported JARVIS_VOICE_TTS_PIPER_QUALITY={self.config.tts_piper_quality!r}; use one of: {valid}."
            )
        self._load_piper_voice()

    def _load_piper_voice(self) -> PiperVoice:
        quality = self.config.tts_piper_quality
        if quality not in PIPER_JARVIS_MODEL_PATHS:
            valid = ", ".join(sorted(PIPER_JARVIS_MODEL_PATHS))
            raise VoicePipelineError(
                f"Unsupported JARVIS_VOICE_TTS_PIPER_QUALITY={quality!r}; use one of: {valid}."
            )
        key = (self.config.tts_piper_repo_id, quality)
        with self._piper_lock:
            if self._piper_voice is not None and self._piper_voice_key == key:
                return self._piper_voice
            model_file, config_file = PIPER_JARVIS_MODEL_PATHS[quality]
            try:
                LOGGER.info(
                    "Loading Piper JARVIS TTS voice: repo=%s quality=%s",
                    self.config.tts_piper_repo_id,
                    quality,
                )
                model_path = hf_hub_download(repo_id=self.config.tts_piper_repo_id, filename=model_file)
                config_path = hf_hub_download(repo_id=self.config.tts_piper_repo_id, filename=config_file)
                voice = PiperVoice.load(model_path, config_path=config_path)
            except Exception as exc:
                raise VoicePipelineError(f"Failed to load Piper JARVIS TTS model: {exc}") from exc
            self._piper_voice = voice
            self._piper_voice_key = key
            return voice

    def _synthesize_segment_piper(self, text: str) -> Path:
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix="jarvis_voice_piper_")
        path = Path(handle.name).resolve()
        handle.close()
        syn_config = SynthesisConfig(
            length_scale=self.config.tts_piper_length_scale / max(self.config.tts_speed, 0.01),
            volume=self.config.tts_piper_volume,
            noise_scale=self.config.tts_piper_noise_scale,
            noise_w_scale=self.config.tts_piper_noise_w_scale,
        )
        try:
            # PiperVoice synthesis is kept under the same lock as model loading to
            # avoid sharing a voice instance across concurrent synthesis calls.
            with self._piper_lock:
                voice = self._load_piper_voice()
                wav_file = wave.open(str(path), "wb")
                synth_error: BaseException | None = None
                try:
                    voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                except BaseException as exc:
                    synth_error = exc
                    raise
                finally:
                    try:
                        wav_file.close()
                    except Exception:
                        # If Piper failed before writing a WAV header, wave.close()
                        # raises "# channels not specified" and masks the real
                        # synthesis exception. Preserve the original failure.
                        if synth_error is None:
                            raise
                        LOGGER.debug("Ignoring WAV close error after Piper synthesis failure", exc_info=True)
            if not path.exists() or path.stat().st_size <= 44:
                raise VoicePipelineNoOutputError("Piper JARVIS TTS produced no playable WAV audio.")
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _split_for_tts(self, text: str) -> list[str]:
        text = " ".join(text.split()).strip()
        if not text:
            return []

        raw_sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(text) if part.strip()]
        if not raw_sentences:
            raw_sentences = [text]

        limit = self.config.max_tts_chars_per_segment
        segments: list[str] = []
        current = ""
        for sentence in raw_sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                segments.append(current)
                current = ""
            sentence_chunks = _bounded_tts_chunks(sentence, limit)
            if sentence_chunks:
                segments.extend(sentence_chunks[:-1])
                current = sentence_chunks[-1]
        if current:
            segments.append(current)

        return segments if self.config.max_tts_segments <= 0 else segments[: self.config.max_tts_segments]

    def _clean_text_for_tts(self, text: str) -> str:
        """Remove text that should never be spoken by TTS.

        This is intentionally silent: URLs, code, markdown links, and chat
        markup are removed without spoken placeholders such as "link".
        """
        text = _THINKING_BLOCK_RE.sub("", text or "")
        if not text.strip():
            return ""

        if self.config.tts_strip_code:
            text = _FENCED_CODE_RE.sub(" ", text)
            text = _INLINE_CODE_RE.sub(" ", text)

        if self.config.tts_strip_urls:
            text = _MARKDOWN_LINK_RE.sub(" ", text)
            text = _URL_RE.sub(" ", text)
            text = re.sub(r"\b(?:the\s+)?(?:links?|urls?)\s*(?:for\s+you)?\s*[:：]?", " ", text, flags=re.IGNORECASE)

        if self.config.tts_strip_chat_markup:
            text = _CHAT_MARKUP_RE.sub(" ", text)

        if self.config.tts_strip_markdown:
            cleaned_lines: list[str] = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if _MARKDOWN_TABLE_DIVIDER_RE.match(line):
                    continue
                if "|" in line and line.count("|") >= 2:
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    cells = [cell for cell in cells if cell]
                    if not cells:
                        continue
                    if len(cells) >= 2:
                        line = f"{cells[0]}: {', '.join(cells[1:])}"
                    else:
                        line = cells[0]
                    if line[-1:] not in ".!?":
                        line += "."
                cleaned_lines.append(line)
            text = " ".join(cleaned_lines) if cleaned_lines else text
            text = _HTML_TAG_RE.sub(" ", text)
            text = text.replace("**", "").replace("__", "")
            text = re.sub(r"(?m)^\s*[-*+>]\s+", "", text)
            text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
            text = re.sub(r"(?:^|\s)\d+[.)]\s+", " ", text)
            text = re.sub(r"[#*_~|]+", " ", text)

        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"(?:\s*[,;:]\s*){2,}", ", ", text)
        text = re.sub(r"^[\s,.;:!?-]+|[\s,;:-]+$", "", text).strip()
        return text

    @staticmethod
    def _clean_reply_text(text: str) -> str:
        text = _THINKING_BLOCK_RE.sub("", text or "")
        text = _FENCED_CODE_RE.sub("", text)
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r"\s+", " ", text).strip()
        return _dedupe_repeated_reply_text(text)



# Backward-compatible name for callers that imported the original oMLX-specific class.
OmlxVoicePipeline = VoicePipeline


def _audio_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            framerate = wav_file.getframerate()
            if framerate <= 0:
                return 0.0
            return wav_file.getnframes() / framerate
    except Exception:
        return 0.0


def _turn_context_steering_generation(turn_context: object | None) -> int:
    provider = getattr(turn_context, "steering_generation_provider", None)
    if not callable(provider):
        return 0
    try:
        return max(0, int(provider()))
    except Exception:
        LOGGER.debug("Failed to read voice steering generation", exc_info=True)
        return 0


def _turn_context_steering_tts_delay_seconds(turn_context: object | None) -> float:
    value = getattr(turn_context, "steering_tts_delay_seconds", 0.0)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
