from __future__ import annotations

import array
import asyncio
import concurrent.futures
import json
import logging
import os
import queue
from collections import deque
from datetime import datetime, timedelta
import random
import re
import sys
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from huggingface_hub import hf_hub_download
from piper import PiperVoice, SynthesisConfig

try:
    import audioop
except ImportError:  # pragma: no cover - audioop-lts supplies this on Python builds without stdlib audioop
    audioop = None  # type: ignore[assignment]

import requests

import discord
from discord.opus import Decoder as DiscordOpusDecoder
from discord.opus import OpusError as DiscordOpusError

try:
    from discord.ext import voice_recv
except Exception:  # pragma: no cover - optional dependency for Discord voice receive
    voice_recv = None

import config

LOGGER = config.get_logger("operation_jarvis.voice.discord_voice")

MAX_DISCORD_MESSAGE_LENGTH = 2000
DISCORD_VOICE_ENABLED = config.get_str_env("DISCORD_VOICE_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_CHANNEL_NAME = config.get_str_env("DISCORD_VOICE_CHANNEL_NAME", "jarvis").lower()
# Keep these segmentation defaults aligned with raspberry-pi/room_audio/pi_room_audio_client.py.
DISCORD_VOICE_SILENCE_SECONDS = config.get_float_env("DISCORD_VOICE_SILENCE_SECONDS", 1.0, minimum=0.1)
DISCORD_VOICE_MONITOR_INTERVAL_SECONDS = config.get_float_env("DISCORD_VOICE_MONITOR_INTERVAL_SECONDS", 0.1, minimum=0.05)
DISCORD_VOICE_MIN_UTTERANCE_SECONDS = config.get_float_env("DISCORD_VOICE_MIN_UTTERANCE_SECONDS", 0.5, minimum=0.1)
DISCORD_VOICE_MAX_UTTERANCE_SECONDS = config.get_float_env("DISCORD_VOICE_MAX_UTTERANCE_SECONDS", 30.0, minimum=1.0)
DISCORD_VOICE_QUEUE_MAX_SIZE = config.get_int_env("DISCORD_VOICE_QUEUE_MAX_SIZE", 8, minimum=1)
DISCORD_VOICE_INGEST_QUEUE_MAX_FRAMES = config.get_int_env("DISCORD_VOICE_INGEST_QUEUE_MAX_FRAMES", 400, minimum=20)
DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME = config.get_str_env("DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME", "").lower()
DISCORD_VOICE_PREPROCESS_AUDIO = config.get_str_env("DISCORD_VOICE_PREPROCESS_AUDIO", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_SILENCE_RMS_THRESHOLD = config.get_int_env("DISCORD_VOICE_SILENCE_RMS_THRESHOLD", 300, minimum=0)
DISCORD_VOICE_MIN_VOICED_MS = config.get_int_env("DISCORD_VOICE_MIN_VOICED_MS", 200, minimum=0)
DISCORD_VOICE_PREROLL_MS = config.get_int_env("DISCORD_VOICE_PREROLL_MS", 500, minimum=0)
DISCORD_VOICE_SILENCE_PADDING_MS = config.get_int_env("DISCORD_VOICE_SILENCE_PADDING_MS", 500, minimum=0)
DISCORD_VOICE_INPUT_SAMPLE_RATE = config.get_int_env("DISCORD_VOICE_INPUT_SAMPLE_RATE", 24_000, minimum=8_000)
DISCORD_VOICE_INPUT_MIN_SECONDS = config.get_float_env("DISCORD_VOICE_INPUT_MIN_SECONDS", 1.0, minimum=0.0)
DISCORD_VOICE_MONO_MODE = config.get_str_env("DISCORD_VOICE_MONO_MODE", "left").lower()
DISCORD_VOICE_NORMALIZE_TARGET_PEAK = config.get_int_env("DISCORD_VOICE_NORMALIZE_TARGET_PEAK", 16_000, minimum=0)
DISCORD_VOICE_NORMALIZE_TARGET_RMS = config.get_int_env("DISCORD_VOICE_NORMALIZE_TARGET_RMS", 2_500, minimum=0)
DISCORD_VOICE_NORMALIZE_MAX_GAIN = config.get_float_env("DISCORD_VOICE_NORMALIZE_MAX_GAIN", 12.0, minimum=1.0)
DISCORD_VOICE_SUPPRESS_RECV_CRYPTO_ERRORS = config.get_str_env(
    "DISCORD_VOICE_SUPPRESS_RECV_CRYPTO_ERRORS",
    "1",
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_DROP_WHILE_BUSY = config.get_str_env("DISCORD_VOICE_DROP_WHILE_BUSY", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_JOIN_WHEN_EMPTY = config.get_str_env("DISCORD_VOICE_JOIN_WHEN_EMPTY", "0").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_PRELOAD_ON_JOIN = config.get_str_env("DISCORD_VOICE_PRELOAD_ON_JOIN", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_CONTEXTUAL_GREETINGS = config.get_str_env("DISCORD_VOICE_CONTEXTUAL_GREETINGS", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_GREETING_COOLDOWN_MINUTES = config.get_float_env("DISCORD_VOICE_GREETING_COOLDOWN_MINUTES", 10.0, minimum=0.0)
DISCORD_VOICE_GREETING_INCLUDE_STATUS = config.get_str_env("DISCORD_VOICE_GREETING_INCLUDE_STATUS", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_DEFAULT_VOICE_GREETING_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "voice_greeting_state.json"
DISCORD_VOICE_GREETING_STATE_PATH = Path(
    config.get_str_env("DISCORD_VOICE_GREETING_STATE_PATH", str(_DEFAULT_VOICE_GREETING_STATE_PATH))
).expanduser()
DISCORD_VOICE_PROCESSING_ACK_ENABLED = config.get_str_env("DISCORD_VOICE_PROCESSING_ACK_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_PROCESSING_ACK_TEXT = config.get_str_env("DISCORD_VOICE_PROCESSING_ACK_TEXT", "Generating your response, sir.").strip()
DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS = config.get_float_env("DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS", 2.0, minimum=0.0)
DISCORD_VOICE_STATUS_DIAGNOSTICS = config.get_str_env("DISCORD_VOICE_STATUS_DIAGNOSTICS", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_JOIN_GREETINGS = (
    "Nice to see you again, sir.",
    "Good to see you again, sir.",
    "Welcome back, sir.",
    "Nice to hear from you again, sir.",
    "JARVIS online. Nice to see you again, sir.",
)
DISCORD_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES = (
    "JARVIS online.",
    "Systems are online.",
    "Voice link established.",
    "At your service.",
)
_VOICE_GREETING_STATE_LOCK = threading.Lock()
DISCORD_VOICE_WAKE_WORD = config.get_str_env("DISCORD_VOICE_WAKE_WORD", "jarvis,arvis,charvis,travis,darvish,charmavis").strip()
DISCORD_VOICE_WAKE_WORDS = tuple(
    dict.fromkeys(
        word.strip()
        for word in re.split(r"[,;|]", DISCORD_VOICE_WAKE_WORD)
        if word.strip()
    )
)
DISCORD_VOICE_LOCAL_WAKE_WORD_ENABLED = config.get_str_env("DISCORD_VOICE_LOCAL_WAKE_WORD_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR = config.get_str_env(
    "DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR",
    "0",
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_LOCAL_WAKE_WORD_ENGINE = config.get_str_env("DISCORD_VOICE_LOCAL_WAKE_WORD_ENGINE", "openwakeword").strip().lower()
DISCORD_VOICE_LOCAL_WAKE_WORD_THRESHOLD = config.get_float_env("DISCORD_VOICE_LOCAL_WAKE_WORD_THRESHOLD", 0.5, minimum=0.0)
DISCORD_VOICE_LOCAL_WAKE_WORD_COOLDOWN_SECONDS = config.get_float_env("DISCORD_VOICE_LOCAL_WAKE_WORD_COOLDOWN_SECONDS", 2.0, minimum=0.0)
DISCORD_VOICE_LOCAL_WAKE_WORD_ARM_SECONDS = config.get_float_env("DISCORD_VOICE_LOCAL_WAKE_WORD_ARM_SECONDS", 8.0, minimum=0.0)
DISCORD_VOICE_LOCAL_WAKE_WORD_CHUNK_MS = config.get_int_env("DISCORD_VOICE_LOCAL_WAKE_WORD_CHUNK_MS", 80, minimum=10)
DISCORD_VOICE_LOCAL_WAKE_WORD_LOG_SCORES = config.get_str_env("DISCORD_VOICE_LOCAL_WAKE_WORD_LOG_SCORES", "0").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_OPENWAKEWORD_MODEL = config.get_str_env("DISCORD_VOICE_OPENWAKEWORD_MODEL", "hey_jarvis").strip()
DISCORD_VOICE_OPENWAKEWORD_INFERENCE = config.get_str_env("DISCORD_VOICE_OPENWAKEWORD_INFERENCE", "onnx").strip().lower()
DISCORD_VOICE_OPENWAKEWORD_MODEL_DIR = config.get_str_env("DISCORD_VOICE_OPENWAKEWORD_MODEL_DIR", "").strip()
DISCORD_VOICE_OPENWAKEWORD_AUTO_DOWNLOAD = config.get_str_env("DISCORD_VOICE_OPENWAKEWORD_AUTO_DOWNLOAD", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_TRUST_LOCAL_WAKE_WORD = config.get_str_env("DISCORD_VOICE_TRUST_LOCAL_WAKE_WORD", "0").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_PCM_SAMPLE_RATE = 48_000
DISCORD_PCM_CHANNELS = 2
DISCORD_PCM_SAMPLE_WIDTH_BYTES = 2
DISCORD_PCM_BYTES_PER_SECOND = DISCORD_PCM_SAMPLE_RATE * DISCORD_PCM_CHANNELS * DISCORD_PCM_SAMPLE_WIDTH_BYTES


def _voice_local_now() -> datetime:
    return datetime.now(ZoneInfo("America/Toronto"))


def _parse_voice_greeting_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/Toronto"))
    return parsed.astimezone(ZoneInfo("America/Toronto"))


def _load_voice_greeting_state_unlocked() -> dict[str, Any]:
    try:
        if not DISCORD_VOICE_GREETING_STATE_PATH.is_file():
            return {}
        payload = json.loads(DISCORD_VOICE_GREETING_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.debug("Failed to read Discord voice greeting state", exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_voice_greeting_state_unlocked(state: dict[str, Any]) -> None:
    try:
        DISCORD_VOICE_GREETING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DISCORD_VOICE_GREETING_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        LOGGER.debug("Failed to write Discord voice greeting state", exc_info=True)


def _format_contextual_join_greeting(now: datetime, last_joined_at: datetime | None) -> str:
    if last_joined_at is not None:
        elapsed = now - last_joined_at
        if timedelta(0) <= elapsed <= timedelta(minutes=DISCORD_VOICE_GREETING_COOLDOWN_MINUTES):
            base = random.choice(
                (
                    "Back already, sir?",
                    "Returned so soon, sir?",
                    "Welcome back, sir. That was quick.",
                )
            )
            suffixes = (*DISCORD_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES, "I'll pretend not to judge.")
            return f"{base} {random.choice(suffixes)}" if DISCORD_VOICE_GREETING_INCLUDE_STATUS else base

    hour = now.hour
    if 5 <= hour < 12:
        base = random.choice(("Good morning, sir.", "Morning, sir."))
    elif 12 <= hour < 18:
        base = random.choice(("Good afternoon, sir.", "Afternoon, sir."))
    elif 18 <= hour < 24:
        base = random.choice(("Good evening, sir.", "Evening, sir."))
    else:
        base = random.choice(("You're up late, sir.", "Late night, sir."))

    if not DISCORD_VOICE_GREETING_INCLUDE_STATUS:
        return base
    return f"{base} {random.choice(DISCORD_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES)}"


def _select_join_greeting(*, guild_id: int, channel_id: int) -> str:
    if not DISCORD_VOICE_CONTEXTUAL_GREETINGS:
        return random.choice(DISCORD_VOICE_JOIN_GREETINGS)

    now = _voice_local_now()
    channel_key = f"{guild_id}:{channel_id}"
    with _VOICE_GREETING_STATE_LOCK:
        state = _load_voice_greeting_state_unlocked()
        by_channel = state.get("last_joined_at_by_channel")
        if not isinstance(by_channel, dict):
            by_channel = {}
        last_joined_at = _parse_voice_greeting_timestamp(by_channel.get(channel_key) or state.get("last_joined_at"))
        by_channel[channel_key] = now.isoformat()
        state["last_joined_at"] = now.isoformat()
        state["last_joined_at_by_channel"] = by_channel
        _save_voice_greeting_state_unlocked(state)

    return _format_contextual_join_greeting(now, last_joined_at)


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    return [text[index : index + MAX_DISCORD_MESSAGE_LENGTH] for index in range(0, len(text), MAX_DISCORD_MESSAGE_LENGTH)]


def _discord_block_quote(text: str) -> str:
    lines = (text or "").strip().splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _format_voice_transcript_message(transcript: str) -> str:
    return f"The user said:\n{_discord_block_quote(transcript)}"


def _format_voice_response_message(response: str) -> str:
    return response.strip()


def _format_voice_steering_message(transcript: str) -> str:
    steering_text = " ".join((transcript or "").split()).strip()
    if not steering_text:
        return "Steering said."
    if len(steering_text) > 1500:
        steering_text = f"{steering_text[:1497].rstrip()}..."
    return f"Steering said:\n{_discord_block_quote(steering_text)}"


def _normalize_voice_transcript_wake_words(transcript: str) -> str:
    """Replace wake-word aliases with the canonical `jarvis` before LLM prompting."""
    normalized = transcript or ""
    for wake_word in DISCORD_VOICE_WAKE_WORDS:
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
DEFAULT_VOICE_ASR_MODEL = "mlx-community/whisper-large-v3-turbo-asr-4bit"
DEFAULT_VOICE_LLM_MODEL = "Qwen3.5-9B-4bit"
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
    "You are JARVIS in a live Discord voice call, and you should talk like him. "
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
_DISCORD_MARKUP_RE = re.compile(r"<(?:(?:@!?|@&|#)\d+|a?:[A-Za-z0-9_~]+:\d+)>")
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


def _json_or_text(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


class VoicePipelineError(RuntimeError):
    """Base error for Discord voice pipeline failures."""


class VoicePipelineNoOutputError(VoicePipelineError):
    """Raised when a valid voice turn produces no playable speech."""


VoiceResponseCallback = Callable[[str, Callable[[str], None] | None, object | None], str]
VoiceCancelCallback = Callable[[object | None], bool]
VoiceSteeringCallback = Callable[[object | None, str], bool]
VoiceSessionLifecycleCallback = Callable[[discord.VoiceChannel], None]


@dataclass(frozen=True)
class VoicePipelineConfig:
    base_url: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_BASE_URL", DEFAULT_VOICE_BASE_URL).rstrip("/"))
    api_key: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_API_KEY", config.get_str_env("OMLX_API_KEY", "")))
    asr_model: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_ASR_MODEL", DEFAULT_VOICE_ASR_MODEL))
    asr_language: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_ASR_LANGUAGE", "en"))
    llm_model: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_LLM_MODEL", DEFAULT_VOICE_LLM_MODEL))
    llm_max_tokens: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_LLM_MAX_TOKENS", 120, minimum=16))
    llm_temperature: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_LLM_TEMPERATURE", 0.4, minimum=0.0))
    llm_top_p: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_LLM_TOP_P", 0.9, minimum=0.0))
    llm_history_turns: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_HISTORY_TURNS", 4, minimum=0))
    llm_disable_thinking: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_LLM_DISABLE_THINKING", True))
    tts_backend: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_TTS_BACKEND", DEFAULT_VOICE_TTS_BACKEND).lower())
    tts_speed: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_SPEED", 1.0, minimum=0.25))
    tts_piper_repo_id: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_TTS_PIPER_REPO_ID", DEFAULT_VOICE_TTS_PIPER_REPO_ID))
    tts_piper_quality: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_TTS_PIPER_QUALITY", DEFAULT_VOICE_TTS_PIPER_QUALITY).lower())
    tts_piper_length_scale: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_PIPER_LENGTH_SCALE", 1.15, minimum=0.1))
    tts_piper_volume: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_PIPER_VOLUME", 0.95, minimum=0.0))
    tts_piper_noise_scale: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_PIPER_NOISE_SCALE", 0.55, minimum=0.0))
    tts_piper_noise_w_scale: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_PIPER_NOISE_W_SCALE", 0.70, minimum=0.0))
    stream_tts: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_STREAM_TTS", True))
    stream_start_words: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_STREAM_START_WORDS", 0, minimum=0))
    tts_strip_urls: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_TTS_STRIP_URLS", True))
    tts_strip_code: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_TTS_STRIP_CODE", True))
    tts_strip_markdown: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_TTS_STRIP_MARKDOWN", True))
    tts_strip_discord_markup: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_TTS_STRIP_DISCORD_MARKUP", True))
    max_tts_segments: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_TTS_MAX_SEGMENTS", 0, minimum=0))
    max_tts_chars_per_segment: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_TTS_MAX_CHARS_PER_SEGMENT", 220, minimum=40))
    system_prompt: str = field(default_factory=lambda: config.get_str_env("DISCORD_VOICE_SYSTEM_PROMPT", DEFAULT_VOICE_SYSTEM_PROMPT, strip=False).strip())
    asr_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_ASR_TIMEOUT_SECONDS", 120.0, minimum=1.0))
    llm_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_LLM_TIMEOUT_SECONDS", 120.0, minimum=1.0))
    tts_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_TTS_TIMEOUT_SECONDS", 180.0, minimum=1.0))
    model_load_timeout_seconds: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_MODEL_LOAD_TIMEOUT_SECONDS", 240.0, minimum=1.0))
    unload_between_stages: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_UNLOAD_BETWEEN_STAGES", False))
    request_retries: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_REQUEST_RETRIES", 2, minimum=0))
    request_retry_backoff_seconds: float = field(default_factory=lambda: config.get_float_env("DISCORD_VOICE_REQUEST_RETRY_BACKOFF_SECONDS", 0.75, minimum=0.0))
    tts_max_bytes: int = field(default_factory=lambda: config.get_int_env("DISCORD_VOICE_TTS_MAX_BYTES", 100 * 1024 * 1024, minimum=1))
    require_configured_models: bool = field(default_factory=lambda: _env_bool("DISCORD_VOICE_REQUIRE_CONFIGURED_MODELS", True))


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


class OmlxVoicePipeline:
    """Speech-to-text and chat via oMLX, with configurable local or oMLX text-to-speech."""

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
        self._piper_voice: PiperVoice | None = None
        self._piper_voice_key: tuple[str, str] | None = None
        self._piper_lock = threading.RLock()

    @property
    def configured_models(self) -> tuple[str, ...]:
        models = [self.config.asr_model]
        if self.response_callback is None:
            models.append(self.config.llm_model)
        return tuple(models)

    @property
    def streams_tts_while_llm_generates(self) -> bool:
        return self.config.stream_tts and self.config.tts_backend == "piper"

    def warm_up(self) -> None:
        """Validate the configured ASR/LLM stack and selected TTS backend before the first call."""
        self._validate_tts_backend()
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
            for model in self.configured_models
            if model and model not in available and model.rsplit("/", 1)[-1] not in available
        ]
        LOGGER.info(
            "Voice pipeline models: asr=%s response_backend=%s llm=%s tts_backend=%s tts_voice=%s missing=%s",
            self.config.asr_model,
            "pi_rpc" if self.response_callback is not None else "omlx_chat",
            self.config.llm_model if self.response_callback is None else "n/a",
            self.config.tts_backend,
            f"{self.config.tts_piper_repo_id}:{self.config.tts_piper_quality}",
            missing or "none",
        )
        if missing and self.config.require_configured_models:
            raise VoicePipelineError(
                "Configured oMLX voice model(s) are not installed/visible: " + ", ".join(missing)
            )

        load_targets = [model for model in dict.fromkeys(self.configured_models) if model and model not in missing]
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

    def transcribe_audio(self, input_wav_path: Path) -> tuple[str, float, float]:
        """Transcribe an input WAV and return transcript, input seconds, and ASR seconds."""
        input_seconds = _audio_duration_seconds(input_wav_path)
        asr_started_at = time.monotonic()
        try:
            transcript = self._transcribe(input_wav_path)
        finally:
            if self.config.unload_between_stages:
                self._unload_model(self.config.asr_model)
        asr_seconds = time.monotonic() - asr_started_at
        if not transcript:
            raise VoicePipelineNoOutputError("ASR produced no transcript.")
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
        path is passed to the callback as soon as it is ready, so Discord playback
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

        llm_transcript = _normalize_voice_transcript_wake_words(transcript)

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

    def _transcribe(self, audio_path: Path) -> str:
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
            if not pending_steering_ack or not DISCORD_VOICE_PROCESSING_ACK_ENABLED or not DISCORD_VOICE_PROCESSING_ACK_TEXT:
                return 0.0
            remaining_pause = tts_paused_until - time.monotonic()
            if remaining_pause > 0:
                if not wait:
                    return 0.0
                time.sleep(remaining_pause)
            pending_steering_ack = False
            cleaned_ack = self._clean_text_for_tts(DISCORD_VOICE_PROCESSING_ACK_TEXT)
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
            pending_steering_ack = DISCORD_VOICE_PROCESSING_ACK_ENABLED and bool(DISCORD_VOICE_PROCESSING_ACK_TEXT)
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
        If DISCORD_VOICE_STREAM_START_WORDS is set above zero, allow an earlier
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
                f"Unsupported DISCORD_VOICE_TTS_BACKEND={self.config.tts_backend!r}; use 'piper'."
            )
        if self.config.tts_piper_quality not in PIPER_JARVIS_MODEL_PATHS:
            valid = ", ".join(sorted(PIPER_JARVIS_MODEL_PATHS))
            raise VoicePipelineError(
                f"Unsupported DISCORD_VOICE_TTS_PIPER_QUALITY={self.config.tts_piper_quality!r}; use one of: {valid}."
            )
        self._load_piper_voice()

    def _load_piper_voice(self) -> PiperVoice:
        quality = self.config.tts_piper_quality
        if quality not in PIPER_JARVIS_MODEL_PATHS:
            valid = ", ".join(sorted(PIPER_JARVIS_MODEL_PATHS))
            raise VoicePipelineError(
                f"Unsupported DISCORD_VOICE_TTS_PIPER_QUALITY={quality!r}; use one of: {valid}."
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

        segments: list[str] = []
        current = ""
        for sentence in raw_sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= self.config.max_tts_chars_per_segment:
                current = candidate
                continue
            if current:
                segments.append(current)
            current = sentence
        if current:
            segments.append(current)

        shortened: list[str] = []
        limited_segments = segments if self.config.max_tts_segments <= 0 else segments[: self.config.max_tts_segments]
        for segment in limited_segments:
            if len(segment) <= self.config.max_tts_chars_per_segment:
                shortened.append(segment)
                continue
            shortened.append(segment[: self.config.max_tts_chars_per_segment].rsplit(" ", 1)[0].strip() or segment)
        return shortened

    def _clean_text_for_tts(self, text: str) -> str:
        """Remove text that should never be spoken by TTS.

        This is intentionally silent: URLs, code, markdown links, and Discord
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

        if self.config.tts_strip_discord_markup:
            text = _DISCORD_MARKUP_RE.sub(" ", text)

        if self.config.tts_strip_markdown:
            cleaned_lines: list[str] = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if _MARKDOWN_TABLE_DIVIDER_RE.match(line):
                    continue
                if "|" in line and line.count("|") >= 2:
                    continue
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


@dataclass(frozen=True)
class _VoicePacketMetadata:
    ssrc: int | None = None
    sequence: int | None = None
    timestamp: int | None = None
    opus_bytes: int = 0
    pcm_bytes: int = 0
    fake_packet: bool = False


@dataclass
class _VoiceBufferStats:
    packet_count: int = 0
    ssrc: int | None = None
    first_sequence: int | None = None
    last_sequence: int | None = None
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    sequence_gap_count: int = 0
    missing_packet_count: int = 0
    timestamp_gap_count: int = 0
    opus_bytes: int = 0
    pcm_bytes: int = 0
    chunk_lengths: dict[int, int] = field(default_factory=dict)
    _last_pcm_frames: int | None = None

    def observe(self, metadata: _VoicePacketMetadata | None, pcm: bytes) -> None:
        pcm_bytes = len(pcm)
        current_pcm_frames = pcm_bytes // (DISCORD_PCM_CHANNELS * DISCORD_PCM_SAMPLE_WIDTH_BYTES)
        previous_pcm_frames = self._last_pcm_frames
        self.packet_count += 1
        self.pcm_bytes += pcm_bytes
        self.chunk_lengths[pcm_bytes] = self.chunk_lengths.get(pcm_bytes, 0) + 1
        if metadata is None:
            self._last_pcm_frames = current_pcm_frames
            return

        self.opus_bytes += metadata.opus_bytes
        if metadata.ssrc is not None and self.ssrc is None:
            self.ssrc = metadata.ssrc
        if metadata.sequence is not None:
            if self.first_sequence is None:
                self.first_sequence = metadata.sequence
            if self.last_sequence is not None:
                sequence_gap = (metadata.sequence - self.last_sequence) % 65536
                if sequence_gap != 1:
                    self.sequence_gap_count += 1
                    if 1 < sequence_gap < 1000:
                        self.missing_packet_count += sequence_gap - 1
            self.last_sequence = metadata.sequence
        if metadata.timestamp is not None:
            if self.first_timestamp is None:
                self.first_timestamp = metadata.timestamp
            if self.last_timestamp is not None and previous_pcm_frames is not None:
                timestamp_gap = (metadata.timestamp - self.last_timestamp) % (2**32)
                expected_gap = previous_pcm_frames
                if timestamp_gap != expected_gap:
                    self.timestamp_gap_count += 1
            self.last_timestamp = metadata.timestamp
        self._last_pcm_frames = current_pcm_frames

    def chunk_summary(self) -> str:
        return ",".join(f"{length}x{count}" for length, count in sorted(self.chunk_lengths.items())) or "none"

    def to_dict(self) -> dict[str, object]:
        return {
            "packet_count": self.packet_count,
            "ssrc": self.ssrc,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "sequence_gap_count": self.sequence_gap_count,
            "missing_packet_count": self.missing_packet_count,
            "timestamp_gap_count": self.timestamp_gap_count,
            "opus_bytes": self.opus_bytes,
            "pcm_bytes": self.pcm_bytes,
            "chunk_lengths": {str(length): count for length, count in sorted(self.chunk_lengths.items())},
        }


@dataclass(frozen=True)
class _VoicePreRollFrame:
    pcm: bytes
    metadata: _VoicePacketMetadata | None
    received_at: float
    is_voiced: bool
    rms: int


@dataclass(frozen=True)
class _VoiceIncomingFrame:
    member: discord.Member
    pcm: bytes
    metadata: _VoicePacketMetadata | None
    received_at: float


@dataclass
class _VoiceUserBuffer:
    member: discord.Member
    chunks: list[bytes] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    last_packet_at: float = field(default_factory=time.monotonic)
    last_voice_at: float = field(default_factory=time.monotonic)
    total_bytes: int = 0
    voiced_ms: float = 0.0
    max_rms: int = 0
    stats: _VoiceBufferStats = field(default_factory=_VoiceBufferStats)
    local_wake_gate_active: bool = False
    local_wake_accepted: bool = False
    local_wake_model: str = ""
    local_wake_score: float = 0.0
    local_wake_max_model: str = ""
    local_wake_max_score: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return self.total_bytes / DISCORD_PCM_BYTES_PER_SECOND

    def append(
        self,
        pcm: bytes,
        now: float,
        metadata: _VoicePacketMetadata | None = None,
        *,
        is_voiced: bool = True,
        rms: int = 0,
    ) -> None:
        self.chunks.append(pcm)
        self.total_bytes += len(pcm)
        self.last_packet_at = now
        if is_voiced:
            self.last_voice_at = now
            self.voiced_ms += (len(pcm) / DISCORD_PCM_BYTES_PER_SECOND) * 1000.0
        self.max_rms = max(self.max_rms, rms)
        self.stats.observe(metadata, pcm)


@dataclass(frozen=True)
class _VoiceUtterance:
    member: discord.Member
    pcm: bytes
    duration_seconds: float
    voiced_ms: float
    max_rms: int
    stats: _VoiceBufferStats
    queued_at: float
    last_packet_at: float
    last_voice_at: float
    transcript: str | None = None
    input_seconds: float | None = None
    asr_seconds: float | None = None
    preprocess: _VoicePreprocessDiagnostics | None = None
    is_steering_fallback: bool = False
    local_wake_gate_active: bool = False
    local_wake_accepted: bool = False
    local_wake_model: str = ""
    local_wake_score: float = 0.0
    local_wake_max_model: str = ""
    local_wake_max_score: float = 0.0


@dataclass(frozen=True)
class _StreamedAudioPath:
    path: Path
    steering_generation: int


@dataclass(frozen=True)
class _VoicePreprocessDiagnostics:
    input_seconds: float
    output_seconds: float
    mono_mode: str
    selected_rms: int
    normalized_rms: int
    selected_peak: int
    normalized_peak: int
    gain: float
    clipped_percent: float


@dataclass(frozen=True)
class _VoiceInputWav:
    path: Path
    diagnostics: _VoicePreprocessDiagnostics


@dataclass(frozen=True)
class _LocalWakeWordHit:
    model: str
    score: float
    scores: dict[str, float]


class _DiscordOpenWakeWordDetector:
    """Streaming openWakeWord adapter for Discord voice PCM.

    Discord voice receive gives us 48 kHz, stereo, signed 16-bit PCM.  The
    stock openWakeWord models expect 16 kHz, mono, signed 16-bit PCM in roughly
    80 ms chunks, so this class mirrors the room-audio gate by downmixing,
    resampling, buffering, and then scoring the acoustic wake word before any
    oMLX Whisper ASR call is made.
    """

    target_rate = 16_000

    def __init__(self, *, user_label: str = "") -> None:
        if DISCORD_VOICE_LOCAL_WAKE_WORD_ENGINE != "openwakeword":
            raise RuntimeError(f"unsupported Discord local wake-word engine: {DISCORD_VOICE_LOCAL_WAKE_WORD_ENGINE}")
        if audioop is None:
            raise RuntimeError("Discord local wake-word resampling requires audioop/audioop-lts")
        try:
            import numpy as np  # type: ignore[import-not-found]
            import openwakeword  # type: ignore[import-not-found]
            import openwakeword.utils as openwakeword_utils  # type: ignore[import-not-found]
            from openwakeword.model import Model  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(
                "Discord local wake word requires openWakeWord; install the voice requirements "
                "or add openwakeword and onnxruntime to the active JARVIS Python environment"
            ) from exc

        self._np = np
        self._buffer = bytearray()
        self._ratecv_state: object | None = None
        self._last_score_log_at = 0.0
        self._cooldown_until = 0.0
        self.last_model = ""
        self.last_score = 0.0
        self.max_model = ""
        self.max_score = 0.0
        self.threshold = max(0.0, min(1.0, float(DISCORD_VOICE_LOCAL_WAKE_WORD_THRESHOLD)))
        self.cooldown_seconds = max(0.0, float(DISCORD_VOICE_LOCAL_WAKE_WORD_COOLDOWN_SECONDS))
        self.chunk_samples = max(
            160,
            int(round(self.target_rate * (max(10, DISCORD_VOICE_LOCAL_WAKE_WORD_CHUNK_MS) / 1000.0))),
        )
        self.chunk_bytes = self.chunk_samples * DISCORD_PCM_SAMPLE_WIDTH_BYTES
        self.log_scores = bool(DISCORD_VOICE_LOCAL_WAKE_WORD_LOG_SCORES)
        self.inference_framework = DISCORD_VOICE_OPENWAKEWORD_INFERENCE or "onnx"
        model_specs = self._resolve_model_specs(openwakeword, openwakeword_utils)
        self._model = Model(wakeword_models=model_specs, inference_framework=self.inference_framework)
        self.model_names = tuple(model_specs)
        self._prime_model()
        LOGGER.info(
            "Discord local wake word online: user=%s engine=openwakeword models=%s threshold=%.2f chunk=%.0fms cooldown=%.1fs inference=%s",
            user_label or "unknown",
            ",".join(model_specs),
            self.threshold,
            self.chunk_samples / self.target_rate * 1000.0,
            self.cooldown_seconds,
            self.inference_framework,
        )

    def _resolve_model_specs(self, openwakeword: object, openwakeword_utils: object) -> list[str]:
        raw_specs = DISCORD_VOICE_OPENWAKEWORD_MODEL.strip()
        specs = [item.strip() for item in raw_specs.split(",") if item.strip()] or ["hey_jarvis"]
        model_dir = Path(DISCORD_VOICE_OPENWAKEWORD_MODEL_DIR).expanduser() if DISCORD_VOICE_OPENWAKEWORD_MODEL_DIR else None
        if model_dir is not None:
            model_dir.mkdir(parents=True, exist_ok=True)
        resolved: list[str] = []
        official_models = getattr(openwakeword, "MODELS", None) or getattr(openwakeword, "models", {})

        for spec in specs:
            spec_path = Path(spec).expanduser()
            if spec_path.is_file():
                resolved.append(str(spec_path))
                continue

            key = spec.lower().replace(" ", "_").replace("-", "_")
            model_info = official_models.get(key) if isinstance(official_models, dict) else None
            if not isinstance(model_info, dict):
                # Let openWakeWord attempt to resolve future built-in aliases.
                resolved.append(spec)
                continue

            download_models = getattr(openwakeword_utils, "download_models", None)
            if DISCORD_VOICE_OPENWAKEWORD_AUTO_DOWNLOAD and callable(download_models):
                if model_dir is not None:
                    download_models(model_names=[key], target_directory=str(model_dir))
                else:
                    download_models(model_names=[key])

            if model_dir is not None:
                filename = str(model_info.get("download_url") or model_info.get("model_path") or "").rstrip("/").split("/")[-1]
                if self.inference_framework == "onnx":
                    filename = filename.replace(".tflite", ".onnx")
                resolved.append(str(model_dir / filename))
            else:
                path = str(model_info.get("model_path", spec))
                if self.inference_framework == "onnx":
                    path = path.replace(".tflite", ".onnx")
                resolved.append(path)

        return resolved

    def _prime_model(self) -> None:
        # openWakeWord keeps temporal buffers.  Prime them with silence so the
        # first spoken "hey Jarvis" after join/reset is not lost to empty state.
        zero_chunk = self._np.zeros(self.chunk_samples, dtype=self._np.int16)
        for _ in range(max(1, int(round(0.5 * self.target_rate / self.chunk_samples)))):
            self._model.predict(zero_chunk)

    def reset_stream(self) -> None:
        self._buffer.clear()
        self._ratecv_state = None
        self.last_model = ""
        self.last_score = 0.0
        self.max_model = ""
        self.max_score = 0.0
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
        self._prime_model()

    def process_frame(self, pcm: bytes, *, now: float) -> _LocalWakeWordHit | None:
        if not pcm:
            return None
        if audioop is None:
            raise RuntimeError("Discord local wake-word resampling requires audioop/audioop-lts")
        frame = _discord_pcm_to_local_wake_pcm(pcm, ratecv_state_holder=self)
        if not frame:
            return None
        self._buffer.extend(frame)

        hit: _LocalWakeWordHit | None = None
        while len(self._buffer) >= self.chunk_bytes:
            chunk = bytes(self._buffer[: self.chunk_bytes])
            del self._buffer[: self.chunk_bytes]
            samples = self._np.frombuffer(chunk, dtype=self._np.int16)
            prediction = self._model.predict(samples)
            scores: dict[str, float] = {}
            if isinstance(prediction, dict):
                for name, value in prediction.items():
                    try:
                        scores[str(name)] = float(value)
                    except Exception:
                        continue
            if not scores:
                continue

            model_name, score = max(scores.items(), key=lambda item: item[1])
            self.last_model = model_name
            self.last_score = score
            if score > self.max_score:
                self.max_model = model_name
                self.max_score = score
            if self.log_scores and now - self._last_score_log_at >= 1.0:
                self._last_score_log_at = now
                LOGGER.info("Discord local wake score: model=%s score=%.3f", model_name, score)
            if score >= self.threshold and now >= self._cooldown_until:
                self._cooldown_until = now + self.cooldown_seconds
                hit = _LocalWakeWordHit(model=model_name, score=score, scores=scores)
                reset = getattr(self._model, "reset", None)
                if callable(reset):
                    reset()
                self._buffer.clear()
                self._ratecv_state = None
                self._prime_model()
        return hit


def _format_voice_diagnostic_message(
    *,
    member: discord.Member,
    duration_seconds: float,
    voiced_ms: float,
    max_rms: int,
    outcome: str,
    preprocess: _VoicePreprocessDiagnostics | None = None,
    asr_seconds: float | None = None,
    transcript: str | None = None,
    local_wake_gate_active: bool = False,
    local_wake_accepted: bool | None = None,
    local_wake_model: str = "",
    local_wake_score: float | None = None,
    local_wake_max_model: str = "",
    local_wake_max_score: float | None = None,
) -> str:
    parts = [
        f"Voice diagnostic for {member.display_name}: {outcome}.",
        f"heard={duration_seconds:.2f}s",
        f"voiced={voiced_ms:.0f}ms",
        f"max_rms={max_rms}",
        f"gate_rms={DISCORD_VOICE_SILENCE_RMS_THRESHOLD}",
    ]
    if local_wake_gate_active:
        if local_wake_accepted is not None:
            parts.append(f"local_wake={'accepted' if local_wake_accepted else 'missed'}")
        if local_wake_model and local_wake_score is not None:
            parts.append(f"wake={local_wake_model}:{local_wake_score:.3f}")
        if local_wake_max_model and local_wake_max_score is not None:
            parts.append(f"wake_max={local_wake_max_model}:{local_wake_max_score:.3f}")
    if preprocess is not None:
        parts.extend(
            [
                f"input_rms={preprocess.selected_rms}",
                f"normalized_rms={preprocess.normalized_rms}",
                f"gain={preprocess.gain:.2f}x",
                f"peak={preprocess.normalized_peak}",
                f"clipped={preprocess.clipped_percent:.2f}%",
            ]
        )
    if asr_seconds is not None:
        parts.append(f"asr={asr_seconds:.2f}s")
    message = " ".join(parts)
    if transcript is not None:
        clean_transcript = transcript.strip() or "<empty>"
        message += f"\nASR transcript:\n{_discord_block_quote(clean_transcript[:800])}"
    return message



_VOICE_RECV_DECODER_PATCHED = False
_VOICE_DIAG_LAST_LOG: dict[str, float] = {}


def _voice_diag_log(key: str, message: str, *args: object, interval_seconds: float = 5.0) -> None:
    now = time.monotonic()
    last = _VOICE_DIAG_LAST_LOG.get(key, 0.0)
    if now - last < interval_seconds:
        return
    _VOICE_DIAG_LAST_LOG[key] = now
    LOGGER.debug(message, *args)


class _VoiceRecvCryptoErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "CryptoError decoding packet data"


def _patch_voice_recv_opus_decoder() -> None:
    """Make discord-ext-voice-recv tolerate malformed/lost packets without dropping buffered speech."""
    global _VOICE_RECV_DECODER_PATCHED
    if _VOICE_RECV_DECODER_PATCHED or voice_recv is None:
        return
    try:
        from discord.ext.voice_recv import opus as voice_recv_opus
        from discord.ext.voice_recv import rtp as voice_recv_rtp
        from discord.ext.voice_recv import reader as voice_recv_reader
        from discord.ext.voice_recv import utils as voice_recv_utils
    except Exception:
        return
    try:
        import davey
    except Exception:  # pragma: no cover - discord.py can run with DAVE disabled
        davey = None  # type: ignore[assignment]

    if DISCORD_VOICE_SUPPRESS_RECV_CRYPTO_ERRORS:
        crypto_filter = _VoiceRecvCryptoErrorFilter()
        if not any(isinstance(item, _VoiceRecvCryptoErrorFilter) for item in voice_recv_reader.log.filters):
            voice_recv_reader.log.addFilter(crypto_filter)

    original_audio_reader_init = voice_recv_reader.AudioReader.__init__
    original_decoder_init = voice_recv_opus.PacketDecoder.__init__
    original_decode_packet = voice_recv_opus.PacketDecoder._decode_packet
    original_event_register = voice_recv_utils.MultiDataEvent.register

    def _dave_decrypt_payload(voice_client: object, packet: object, payload: bytes) -> bytes:
        if davey is None:
            return payload
        state = getattr(voice_client, "_connection", None)
        dave_session = getattr(state, "dave_session", None)
        if dave_session is None:
            return payload

        ssrc = getattr(packet, "ssrc", None)
        if not getattr(dave_session, "ready", False):
            # Discord.py 2.7 enables DAVE/MLS voice privacy.  Until the MLS
            # session is ready, the transport-decrypted payload may still be
            # DAVE-encrypted and will decode as clipped garbage.
            _voice_diag_log("dave-not-ready", "Discord voice packet silenced because DAVE is not ready: ssrc=%s", ssrc)
            return voice_recv_rtp.OPUS_SILENCE

        user_id = None
        get_id_from_ssrc = getattr(voice_client, "_get_id_from_ssrc", None)
        if callable(get_id_from_ssrc):
            user_id = get_id_from_ssrc(ssrc)
        if user_id is None:
            _voice_diag_log("dave-no-user", "Discord voice packet silenced because ssrc has no user mapping yet: ssrc=%s", ssrc)
            return voice_recv_rtp.OPUS_SILENCE

        try:
            decrypted = dave_session.decrypt(int(user_id), davey.MediaType.audio, payload)
            _voice_diag_log("dave-ok", "Discord DAVE decrypted voice packets: user_id=%s ssrc=%s opus_bytes=%s", user_id, ssrc, len(decrypted), interval_seconds=15.0)
            return decrypted
        except Exception as exc:
            # During DAVE passthrough/downgrade windows, discord.py's send path
            # may intentionally keep payloads unencrypted.  In that one case,
            # keep the transport-decrypted payload; otherwise silence the frame
            # instead of sending encrypted garbage to Opus/voice pipeline.
            if "UnencryptedWhenPassthroughDisabled" in str(exc):
                return payload
            LOGGER.debug("DAVE decrypt failed for Discord voice packet; substituting Opus silence", exc_info=True)
            return voice_recv_rtp.OPUS_SILENCE

    def _patched_audio_reader_init(self: object, sink: object, voice_client: object, *, after: object = None) -> None:
        original_audio_reader_init(self, sink, voice_client, after=after)
        original_callback = getattr(self, "callback", None)
        if callable(original_callback):
            def _callback_with_diagnostics(packet_data: bytes) -> None:
                if isinstance(packet_data, (bytes, bytearray)) and len(packet_data) > 12:
                    _voice_diag_log("raw-voice-packet", "Discord voice UDP packets are arriving: bytes=%s", len(packet_data), interval_seconds=10.0)
                original_callback(packet_data)

            setattr(self, "callback", _callback_with_diagnostics)
        decryptor = getattr(self, "decryptor", None)
        if decryptor is None:
            return
        transport_decrypt_rtp = getattr(decryptor, "decrypt_rtp", None)
        if not callable(transport_decrypt_rtp):
            return

        def _decrypt_rtp_with_dave(packet: object) -> bytes:
            payload = transport_decrypt_rtp(packet)
            return _dave_decrypt_payload(voice_client, packet, payload)

        setattr(decryptor, "decrypt_rtp", _decrypt_rtp_with_dave)

    def _patched_decoder_init(self: object, router: object, ssrc: int) -> None:
        original_decoder_init(self, router, ssrc)
        try:
            # The default jitter buffer is very small. A slightly deeper buffer
            # is more forgiving of Discord/mobile/network jitter before we
            # decide packets are missing.
            setattr(self, "_buffer", voice_recv_opus.JitterBuffer(maxsize=60, prefsize=1, prefill=3))
        except Exception:
            LOGGER.debug("Failed to enlarge Discord voice jitter buffer", exc_info=True)

    def _unique_event_register(self: object, item: object) -> None:
        items = getattr(self, "_items", None)
        if isinstance(items, list) and item in items:
            ready = getattr(self, "_ready", None)
            if ready is not None:
                try:
                    ready.set()
                except Exception:
                    pass
            return
        original_event_register(self, item)

    def _safe_decode_packet(self: object, packet: object) -> tuple[object, bytes]:
        try:
            return original_decode_packet(self, packet)
        except DiscordOpusError as exc:
            ssrc = getattr(self, "ssrc", "?")
            LOGGER.debug("Skipping malformed Discord Opus packet from ssrc=%s: %s", ssrc, exc)
            try:
                setattr(self, "_decoder", DiscordOpusDecoder())
            except Exception:
                pass
            return packet, b""

    def _gap_filling_get_next_packet(self: object, timeout: float = 0) -> object | None:
        buffer = getattr(self, "_buffer", None)
        if buffer is None:
            return None

        last_seq = getattr(self, "_last_seq", -1)
        try:
            next_packet = buffer.peek(all=True)
        except Exception:
            next_packet = None
        if next_packet is not None and isinstance(last_seq, int) and last_seq >= 0:
            next_sequence = getattr(next_packet, "sequence", None)
            if isinstance(next_sequence, int):
                expected_sequence = (last_seq + 1) % 65536
                sequence_gap = (next_sequence - expected_sequence + 65536) % 65536
                if 0 < sequence_gap < 1000:
                    fake_packet = self._make_fakepacket()
                    try:
                        setattr(buffer, "_last_tx_seq", fake_packet.sequence)
                        update_has_item = getattr(buffer, "_update_has_item", None)
                        if callable(update_has_item):
                            update_has_item()
                    except Exception:
                        LOGGER.debug("Failed to advance Discord jitter buffer over pre-pop packet gap", exc_info=True)
                    return fake_packet

        packet = buffer.pop(timeout=timeout)
        if packet is None:
            if buffer:
                # discord-ext-voice-recv's default behavior flushes the jitter
                # buffer here and returns only the first packet, discarding the
                # remaining buffered speech.  In real Discord calls this can
                # turn ordinary missing RTP packets into huge audio dropouts.
                # Feed one synthetic missing packet instead; the Opus decoder
                # will use FEC/PLC and the next loop can continue in sequence.
                last_seq = getattr(self, "_last_seq", -1)
                if isinstance(last_seq, int) and last_seq >= 0:
                    fake_packet = self._make_fakepacket()
                    try:
                        # Keep the jitter buffer's own sequence cursor aligned
                        # with the decoder cursor.  Without this, the buffer can
                        # stay permanently "not ready" after a gap and we keep
                        # generating fake packets instead of returning to the
                        # buffered real packets.
                        setattr(buffer, "_last_tx_seq", fake_packet.sequence)
                        update_has_item = getattr(buffer, "_update_has_item", None)
                        if callable(update_has_item):
                            update_has_item()
                    except Exception:
                        LOGGER.debug("Failed to advance Discord jitter buffer over missing packet", exc_info=True)
                    return fake_packet
                packets = buffer.flush()
                return packets[0] if packets else None
            return None
        if not packet:
            fake_packet = self._make_fakepacket()
            try:
                setattr(buffer, "_last_tx_seq", fake_packet.sequence)
            except Exception:
                pass
            return fake_packet
        return packet

    voice_recv_reader.AudioReader.__init__ = _patched_audio_reader_init
    voice_recv_opus.PacketDecoder.__init__ = _patched_decoder_init
    voice_recv_opus.PacketDecoder._decode_packet = _safe_decode_packet
    voice_recv_opus.PacketDecoder._get_next_packet = _gap_filling_get_next_packet
    voice_recv_utils.MultiDataEvent.register = _unique_event_register
    _VOICE_RECV_DECODER_PATCHED = True


if voice_recv is not None:
    class _JarvisVoiceSink(voice_recv.AudioSink):  # type: ignore[misc]
        def __init__(self, conversation: "_JarvisVoiceConversation") -> None:
            super().__init__()
            self.conversation = conversation

        def wants_opus(self) -> bool:
            # Use discord-ext-voice-recv's jitter buffer and decoder for normal
            # packets; the startup patch above turns corrupted packets into
            # empty frames so one bad packet does not kill listening.
            return False

        def write(self, user: discord.Member | discord.User | None, data: object) -> None:
            if user is None:
                _voice_diag_log("sink-no-user", "Discord voice sink received decoded audio with no user mapping.")
                return
            member = user if isinstance(user, discord.Member) else self.conversation.guild.get_member(user.id)
            if member is None:
                _voice_diag_log("sink-no-member", "Discord voice sink received audio for unknown user_id=%s", getattr(user, "id", None))
                return
            packet = getattr(data, "packet", None)
            pcm = self._decode_voice_data(data)
            if not pcm:
                _voice_diag_log("sink-empty-pcm", "Discord voice sink received empty PCM for %s", member.display_name)
                return
            if audioop is not None:
                try:
                    rms = audioop.rms(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES)
                except Exception:
                    rms = -1
            else:
                rms = -1
            _voice_diag_log(
                f"sink-pcm-{member.id}",
                "Discord voice sink received PCM for %s: bytes=%s rms=%s packet_truthy=%s",
                member.display_name,
                len(pcm),
                rms,
                bool(packet) if packet is not None else None,
                interval_seconds=5.0,
            )
            metadata = _voice_packet_metadata(packet, pcm)
            self.conversation.ingest_pcm_from_voice_thread(member, pcm, metadata)

        def _decode_voice_data(self, data: object) -> bytes:
            packet = getattr(data, "packet", None)
            pcm = getattr(data, "pcm", None)
            if not isinstance(pcm, (bytes, bytearray)) or not pcm:
                return b""
            if packet is not None and not bool(packet):
                # Preserve timing across missing RTP packets, but do not feed
                # Opus packet-loss-concealment audio into the voice pipeline; PLC frames can
                # be buzzy/loud and look like speech.  Silence keeps the real
                # decoded speech in the right positions.
                return b"\x00" * len(pcm)
            return bytes(pcm)

        def cleanup(self) -> None:
            return
else:
    _JarvisVoiceSink = None  # type: ignore[assignment]


def _voice_packet_metadata(packet: object, pcm: bytes) -> _VoicePacketMetadata:
    decrypted_data = getattr(packet, "decrypted_data", None)
    return _VoicePacketMetadata(
        ssrc=getattr(packet, "ssrc", None),
        sequence=getattr(packet, "sequence", None),
        timestamp=getattr(packet, "timestamp", None),
        opus_bytes=len(decrypted_data) if isinstance(decrypted_data, (bytes, bytearray)) else 0,
        pcm_bytes=len(pcm),
        fake_packet=not bool(packet) if packet is not None else False,
    )


class _JarvisVoiceConversation:
    def __init__(
        self,
        *,
        manager: "JarvisVoiceManager",
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        voice_client: discord.VoiceClient,
    ) -> None:
        self.manager = manager
        self.guild = guild
        self.voice_channel = voice_channel
        self.voice_client = voice_client
        self.loop = manager.client.loop
        self.channel_key = f"voice:{guild.id}:{voice_channel.id}"
        self._buffers: dict[int, _VoiceUserBuffer] = {}
        self._voice_preroll: dict[int, deque[_VoicePreRollFrame]] = {}
        self._quiet_voice_candidates: dict[int, tuple[float, int, float]] = {}
        self._local_wake_detectors: dict[int, _DiscordOpenWakeWordDetector] = {}
        self._local_wake_warming_user_ids: set[int] = set()
        self._local_wake_tasks: set[asyncio.Task[None]] = set()
        self._local_wake_armed_until: dict[int, float] = {}
        self._local_wake_last_hits: dict[int, _LocalWakeWordHit] = {}
        self._local_wake_disabled_reason: str | None = None
        self._local_wake_waiting_notice_at: dict[int, float] = {}
        self._ingest_queue: asyncio.Queue[_VoiceIncomingFrame] = asyncio.Queue(maxsize=DISCORD_VOICE_INGEST_QUEUE_MAX_FRAMES)
        self._queue: asyncio.Queue[_VoiceUtterance] = asyncio.Queue(maxsize=DISCORD_VOICE_QUEUE_MAX_SIZE)
        self._ingest_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._warmup_task: asyncio.Task[None] | None = None
        self._greeting_task: asyncio.Task[None] | None = None
        self._interrupt_tasks: set[asyncio.Task[None]] = set()
        self._active_pipeline_task: asyncio.Task[VoicePipelineResult] | None = None
        self._active_turn_context: VoiceTurnContext | None = None
        self._sink: object | None = None
        self._stopped = False
        self._processing_utterance = False
        self._interrupt_requested = False
        self._interrupt_in_progress = False
        self._steering_tts_generation = 0
        self._steering_tts_resume_at = 0.0
        self._queued_turn_cutover_generation = 0
        self._processing_incoming_frame = False
        self._last_ingest_queue_full_log_at = 0.0
        self._playback_lock = asyncio.Lock()
        self._status_channel = self._find_status_channel()

    def start(self) -> None:
        if voice_recv is None or _JarvisVoiceSink is None:
            raise RuntimeError("discord-ext-voice-recv is required for Discord voice listening.")
        _patch_voice_recv_opus_decoder()
        self._sink = _JarvisVoiceSink(self)
        listen = getattr(self.voice_client, "listen", None)
        if listen is None:
            raise RuntimeError("Discord voice client does not support receive/listen. Is VoiceRecvClient installed?")
        listen(self._sink, after=self._after_listen)
        self._ingest_task = asyncio.create_task(self._process_incoming_voice_frames())
        self._monitor_task = asyncio.create_task(self._monitor_utterances())
        self._worker_task = asyncio.create_task(self._process_utterances())
        if self._local_wake_gate_configured():
            for member in self.voice_channel.members:
                if not member.bot:
                    self._schedule_local_wake_detector_warmup(member)
        if DISCORD_VOICE_PRELOAD_ON_JOIN:
            self._warmup_task = asyncio.create_task(self._warm_up_voice_pipeline())
        self._greeting_task = asyncio.create_task(self._play_join_greeting())
        connected_channel = getattr(self.voice_client, "channel", None)
        voice_state = getattr(self.voice_client, "_connection", None)
        dave_session = getattr(voice_state, "dave_session", None)
        if self.manager.session_start_callback is not None:
            try:
                self.manager.session_start_callback(self.voice_channel)
            except Exception:
                LOGGER.warning("Voice session start callback failed", exc_info=True)
        LOGGER.debug(
            "JARVIS voice listener started in guild=%s channel=%s channel_id=%s voice_client_channel=%s voice_client_channel_id=%s dave_protocol=%s dave_ready=%s members=%s",
            self.guild.id,
            self.voice_channel.name,
            self.voice_channel.id,
            getattr(connected_channel, "name", None),
            getattr(connected_channel, "id", None),
            getattr(voice_state, "dave_protocol_version", None),
            getattr(dave_session, "ready", None) if dave_session is not None else None,
            [member.display_name for member in self.voice_channel.members],
        )

    async def _warm_up_voice_pipeline(self) -> None:
        try:
            await asyncio.to_thread(self.manager.pipeline.warm_up)
        except Exception as exc:
            LOGGER.exception("Failed to warm up voice pipeline")
            await self._send_status_message(f"⚠️ Failed to warm up the voice pipeline: {exc}")

    @staticmethod
    def _local_wake_gate_configured() -> bool:
        return DISCORD_VOICE_LOCAL_WAKE_WORD_ENABLED and bool(DISCORD_VOICE_WAKE_WORDS)

    @staticmethod
    def _local_wake_gate_required() -> bool:
        return _JarvisVoiceConversation._local_wake_gate_configured() and not DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR

    def _schedule_local_wake_detector_warmup(self, member: discord.Member) -> None:
        if (
            self._stopped
            or member.bot
            or not self._local_wake_gate_configured()
            or self._local_wake_disabled_reason is not None
            or member.id in self._local_wake_detectors
            or member.id in self._local_wake_warming_user_ids
        ):
            return
        self._local_wake_warming_user_ids.add(member.id)
        task = asyncio.create_task(self._warm_up_local_wake_detector(member))
        self._local_wake_tasks.add(task)

        def _discard(done_task: asyncio.Task[None]) -> None:
            self._local_wake_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception("Failed to initialize Discord local wake-word detector for %s", member)

        task.add_done_callback(_discard)

    async def _warm_up_local_wake_detector(self, member: discord.Member) -> None:
        try:
            detector = await asyncio.to_thread(_DiscordOpenWakeWordDetector, user_label=member.display_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._disable_local_wake_gate(exc)
            return
        finally:
            self._local_wake_warming_user_ids.discard(member.id)
        if not self._stopped and self._local_wake_disabled_reason is None:
            self._local_wake_detectors[member.id] = detector

    def _disable_local_wake_gate(self, reason: BaseException | str) -> None:
        if self._local_wake_disabled_reason is not None:
            return
        self._local_wake_disabled_reason = str(reason)
        self._local_wake_detectors.clear()
        if DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR:
            for buffer in self._buffers.values():
                buffer.local_wake_gate_active = False
                buffer.local_wake_accepted = False
        LOGGER.warning(
            "Discord local wake-word gate unavailable; falling back to transcript-gated ASR: %s",
            reason,
            exc_info=isinstance(reason, BaseException),
        )
        if not self.loop.is_closed() and not self._stopped:
            asyncio.create_task(
                self._send_status_message(
                    (
                        "⚠️ Discord local wake-word gate is unavailable; falling back to transcript-gated ASR. "
                        if DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR
                        else "⚠️ Discord local wake-word gate is unavailable; voice ASR is blocked until it is fixed. "
                    )
                    + "Install/update openwakeword and onnxruntime in the JARVIS Python environment."
                )
            )

    def _get_local_wake_detector(self, member: discord.Member) -> _DiscordOpenWakeWordDetector | None:
        if not self._local_wake_gate_configured() or self._local_wake_disabled_reason is not None:
            return None
        detector = self._local_wake_detectors.get(member.id)
        if detector is not None:
            return detector
        self._schedule_local_wake_detector_warmup(member)
        return None

    async def _play_join_greeting(self) -> None:
        audio_paths: list[Path] = []
        try:
            # Give Discord a brief moment to settle after joining before speaking.
            await asyncio.sleep(0.6)
            if self._stopped or not self.voice_client.is_connected():
                return
            greeting = _select_join_greeting(guild_id=self.guild.id, channel_id=self.voice_channel.id)
            greeting_path = await asyncio.to_thread(self.manager.pipeline.synthesize_notice, greeting)
            audio_paths.append(greeting_path)
            if self._stopped or not self.voice_client.is_connected():
                return
            await self._play_audio_file(greeting_path)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.warning("Failed to play Discord voice join greeting", exc_info=True)
        finally:
            _delete_temporary_paths(audio_paths)

    async def _wait_for_warmup_if_needed(self) -> None:
        task = self._warmup_task
        if task is not None and not task.done():
            LOGGER.debug("Waiting for voice pipeline warmup before processing voice utterance")
            await task

    async def stop(self) -> None:
        self._stopped = True
        stop_listening = getattr(self.voice_client, "stop_listening", None)
        if callable(stop_listening):
            try:
                stop_listening()
            except Exception:
                LOGGER.debug("Failed to stop Discord voice listening cleanly", exc_info=True)
        else:
            try:
                self.voice_client.stop()
            except Exception:
                LOGGER.debug("Failed to stop Discord voice client cleanly", exc_info=True)

        self._interrupt_requested = True
        cancel_callback = self.manager.cancel_callback
        if cancel_callback is not None and self._active_turn_context is not None:
            try:
                cancel_callback(self._active_turn_context)
            except Exception:
                LOGGER.debug("Failed to cancel active voice Pi task during shutdown", exc_info=True)
        try:
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()
        except Exception:
            LOGGER.debug("Failed to stop Discord voice playback during shutdown", exc_info=True)

        tasks = [
            task
            for task in (self._ingest_task, self._monitor_task, self._worker_task, self._warmup_task, self._greeting_task)
            if task is not None
        ]
        tasks.extend(self._interrupt_tasks)
        tasks.extend(self._local_wake_tasks)
        self._interrupt_tasks.clear()
        self._local_wake_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            if self.voice_client.is_connected():
                await self.voice_client.disconnect(force=True)
        except Exception:
            LOGGER.debug("Failed to disconnect Discord voice client", exc_info=True)
        if self.manager.session_end_callback is not None:
            try:
                self.manager.session_end_callback(self.voice_channel)
            except Exception:
                LOGGER.warning("Voice session end callback failed", exc_info=True)
        LOGGER.debug("JARVIS voice listener stopped in guild=%s channel=%s", self.guild.id, self.voice_channel.name)

    def ingest_pcm_from_voice_thread(
        self,
        member: discord.Member,
        pcm: bytes,
        metadata: _VoicePacketMetadata | None = None,
    ) -> None:
        if self.loop.is_closed() or self._stopped:
            return
        # Keep the Discord voice receive/event-loop heartbeat path light.  The
        # openWakeWord ONNX call can briefly monopolize the interpreter if it is
        # run inline, which is enough for Discord's voice websocket to miss
        # heartbeats and close with 4006.  Queue raw frames and let one async
        # worker offload acoustic wake scoring to a thread in packet order.
        self.loop.call_soon_threadsafe(
            self._enqueue_incoming_frame,
            member,
            bytes(pcm),
            metadata,
            time.monotonic(),
        )

    def _enqueue_incoming_frame(
        self,
        member: discord.Member,
        pcm: bytes,
        metadata: _VoicePacketMetadata | None,
        received_at: float,
    ) -> None:
        if self._stopped or member.bot:
            return
        try:
            self._ingest_queue.put_nowait(
                _VoiceIncomingFrame(member=member, pcm=pcm, metadata=metadata, received_at=received_at)
            )
        except asyncio.QueueFull:
            now = time.monotonic()
            if now - self._last_ingest_queue_full_log_at >= 5.0:
                self._last_ingest_queue_full_log_at = now
                LOGGER.warning(
                    "Dropping Discord voice frames because ingest queue is full: guild=%s channel=%s queued=%s max=%s",
                    self.guild.id,
                    self.voice_channel.name,
                    self._ingest_queue.qsize(),
                    DISCORD_VOICE_INGEST_QUEUE_MAX_FRAMES,
                )

    async def _process_incoming_voice_frames(self) -> None:
        try:
            while not self._stopped:
                frame = await self._ingest_queue.get()
                self._processing_incoming_frame = True
                try:
                    await self._ingest_pcm(frame.member, frame.pcm, frame.metadata, received_at=frame.received_at)
                finally:
                    self._processing_incoming_frame = False
                    self._ingest_queue.task_done()
        except asyncio.CancelledError:
            return
        finally:
            self._processing_incoming_frame = False

    async def _ingest_pcm(
        self,
        member: discord.Member,
        pcm: bytes,
        metadata: _VoicePacketMetadata | None = None,
        *,
        received_at: float | None = None,
    ) -> None:
        if self._stopped or member.bot:
            return
        if DISCORD_VOICE_DROP_WHILE_BUSY and self._is_busy_with_voice_turn() and not self._wake_word_gate_enabled():
            return
        now = received_at if received_at is not None else time.monotonic()
        local_wake_detector = self._get_local_wake_detector(member)
        local_wake_hit: _LocalWakeWordHit | None = None
        if local_wake_detector is not None:
            try:
                detector_now = time.monotonic()
                local_wake_hit = await asyncio.to_thread(local_wake_detector.process_frame, pcm, now=detector_now)
            except Exception as exc:
                self._disable_local_wake_gate(exc)
                local_wake_detector = None
            else:
                self._update_member_local_wake_state(member, local_wake_detector, local_wake_hit, time.monotonic())

        is_voiced, rms = _pcm_frame_has_voice_energy(pcm)
        if self._local_wake_gate_required() and local_wake_detector is None:
            self._store_voice_preroll(member.id, pcm, metadata, now, is_voiced=is_voiced, rms=rms)
            self._track_local_wake_waiting_candidate(member, time.monotonic(), is_voiced=is_voiced, rms=rms)
            return
        buffer = self._buffers.get(member.id)
        if buffer is None:
            if not is_voiced:
                self._store_voice_preroll(member.id, pcm, metadata, now, is_voiced=is_voiced, rms=rms)
                self._track_quiet_voice_candidate(member, now, rms)
                return
            self._quiet_voice_candidates.pop(member.id, None)
            pre_roll = list(self._voice_preroll.pop(member.id, ()))
            started_at = pre_roll[0].received_at if pre_roll else now
            buffer = _VoiceUserBuffer(
                member=member,
                started_at=started_at,
                last_packet_at=started_at,
                last_voice_at=now,
                local_wake_gate_active=local_wake_detector is not None,
            )
            for frame in pre_roll:
                buffer.append(frame.pcm, frame.received_at, frame.metadata, is_voiced=frame.is_voiced, rms=frame.rms)
            self._buffers[member.id] = buffer
        buffer.append(pcm, now, metadata, is_voiced=is_voiced, rms=rms)
        if local_wake_detector is not None and buffer.local_wake_gate_active:
            self._apply_local_wake_to_buffer(buffer, local_wake_detector, local_wake_hit, time.monotonic())
        if buffer.duration_seconds >= DISCORD_VOICE_MAX_UTTERANCE_SECONDS:
            self._finalize_user_buffer(member.id, reason="max-duration")

    def _update_member_local_wake_state(
        self,
        member: discord.Member,
        detector: _DiscordOpenWakeWordDetector,
        hit: _LocalWakeWordHit | None,
        now: float,
    ) -> None:
        buffer = self._buffers.get(member.id)
        if buffer is not None and buffer.local_wake_gate_active:
            self._update_buffer_local_wake_score(buffer, detector)
        if hit is None:
            return
        self._local_wake_armed_until[member.id] = now + DISCORD_VOICE_LOCAL_WAKE_WORD_ARM_SECONDS
        self._local_wake_last_hits[member.id] = hit
        if buffer is not None and buffer.local_wake_gate_active:
            self._mark_buffer_local_wake_hit(buffer, hit)
        LOGGER.info(
            "Discord local wake detected: guild=%s channel=%s member=%s model=%s score=%.3f armed_for=%.1fs",
            self.guild.id,
            self.voice_channel.name,
            member.display_name,
            hit.model,
            hit.score,
            max(0.0, self._local_wake_armed_until[member.id] - now),
        )

    def _apply_local_wake_to_buffer(
        self,
        buffer: _VoiceUserBuffer,
        detector: _DiscordOpenWakeWordDetector,
        hit: _LocalWakeWordHit | None,
        now: float,
    ) -> None:
        buffer.local_wake_gate_active = True
        self._update_buffer_local_wake_score(buffer, detector)
        if hit is not None:
            self._mark_buffer_local_wake_hit(buffer, hit)
            return
        if now <= self._local_wake_armed_until.get(buffer.member.id, 0.0):
            buffer.local_wake_accepted = True
            last_hit = self._local_wake_last_hits.get(buffer.member.id)
            if last_hit is not None and not buffer.local_wake_model:
                self._mark_buffer_local_wake_hit(buffer, last_hit)

    @staticmethod
    def _update_buffer_local_wake_score(buffer: _VoiceUserBuffer, detector: _DiscordOpenWakeWordDetector) -> None:
        if detector.last_score > buffer.local_wake_max_score:
            buffer.local_wake_max_score = detector.last_score
            buffer.local_wake_max_model = detector.last_model

    @staticmethod
    def _mark_buffer_local_wake_hit(buffer: _VoiceUserBuffer, hit: _LocalWakeWordHit) -> None:
        buffer.local_wake_accepted = True
        buffer.local_wake_model = hit.model
        buffer.local_wake_score = hit.score
        if hit.score > buffer.local_wake_max_score:
            buffer.local_wake_max_score = hit.score
            buffer.local_wake_max_model = hit.model

    @staticmethod
    def _buffer_local_wake_diag_kwargs(buffer: _VoiceUserBuffer) -> dict[str, object]:
        return {
            "local_wake_gate_active": buffer.local_wake_gate_active,
            "local_wake_accepted": buffer.local_wake_accepted,
            "local_wake_model": buffer.local_wake_model,
            "local_wake_score": buffer.local_wake_score if buffer.local_wake_model else None,
            "local_wake_max_model": buffer.local_wake_max_model,
            "local_wake_max_score": buffer.local_wake_max_score if buffer.local_wake_max_model else None,
        }

    @staticmethod
    def _utterance_local_wake_diag_kwargs(utterance: _VoiceUtterance) -> dict[str, object]:
        return {
            "local_wake_gate_active": utterance.local_wake_gate_active,
            "local_wake_accepted": utterance.local_wake_accepted,
            "local_wake_model": utterance.local_wake_model,
            "local_wake_score": utterance.local_wake_score if utterance.local_wake_model else None,
            "local_wake_max_model": utterance.local_wake_max_model,
            "local_wake_max_score": utterance.local_wake_max_score if utterance.local_wake_max_model else None,
        }

    def _track_local_wake_waiting_candidate(self, member: discord.Member, now: float, *, is_voiced: bool, rms: int) -> None:
        if not is_voiced:
            return
        last_sent_at = self._local_wake_waiting_notice_at.get(member.id, 0.0)
        if now - last_sent_at < 10.0:
            return
        self._local_wake_waiting_notice_at[member.id] = now
        reason = self._local_wake_disabled_reason or "detector warming"
        LOGGER.info(
            "Discord voice audio from %s was blocked before ASR because local wake-word detector is not ready: %s rms=%s",
            member.display_name,
            reason,
            rms,
        )
        if self._local_wake_disabled_reason is not None and self._status_channel is not None:
            asyncio.create_task(
                self._send_status_message(
                    "⚠️ Local wake-word detection is enabled, but openWakeWord is not ready, so I am blocking voice ASR instead of using the old path."
                )
            )

    def _store_voice_preroll(
        self,
        user_id: int,
        pcm: bytes,
        metadata: _VoicePacketMetadata | None,
        now: float,
        *,
        is_voiced: bool,
        rms: int,
    ) -> None:
        if DISCORD_VOICE_PREROLL_MS <= 0 or not pcm:
            return
        frames = self._voice_preroll.setdefault(user_id, deque())
        frames.append(_VoicePreRollFrame(pcm=pcm, metadata=metadata, received_at=now, is_voiced=is_voiced, rms=rms))
        max_bytes = int(DISCORD_PCM_BYTES_PER_SECOND * (DISCORD_VOICE_PREROLL_MS / 1000.0))
        frame_alignment = DISCORD_PCM_SAMPLE_WIDTH_BYTES * DISCORD_PCM_CHANNELS
        max_bytes -= max_bytes % frame_alignment
        total_bytes = sum(len(frame.pcm) for frame in frames)
        while frames and total_bytes > max_bytes:
            removed = frames.popleft()
            total_bytes -= len(removed.pcm)

    def _track_quiet_voice_candidate(self, member: discord.Member, now: float, rms: int) -> None:
        if not DISCORD_VOICE_STATUS_DIAGNOSTICS or rms <= 0 or DISCORD_VOICE_SILENCE_RMS_THRESHOLD <= 0:
            return
        started_at, max_rms, last_sent_at = self._quiet_voice_candidates.get(member.id, (now, 0, 0.0))
        if now - started_at > max(DISCORD_VOICE_SILENCE_SECONDS, 1.0):
            started_at = now
            max_rms = 0
        max_rms = max(max_rms, rms)
        duration = now - started_at
        if (
            duration >= DISCORD_VOICE_MIN_UTTERANCE_SECONDS
            and max_rms >= int(DISCORD_VOICE_SILENCE_RMS_THRESHOLD * 0.35)
            and now - last_sent_at >= 5.0
        ):
            last_sent_at = now
            self._schedule_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=member,
                    duration_seconds=duration,
                    voiced_ms=0.0,
                    max_rms=max_rms,
                    outcome="not sent to ASR: below voice gate",
                )
            )
        self._quiet_voice_candidates[member.id] = (started_at, max_rms, last_sent_at)

    async def _monitor_utterances(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(DISCORD_VOICE_MONITOR_INTERVAL_SECONDS)
                if self._processing_incoming_frame or not self._ingest_queue.empty():
                    continue
                now = time.monotonic()
                for user_id, buffer in list(self._buffers.items()):
                    if now - buffer.last_voice_at >= DISCORD_VOICE_SILENCE_SECONDS:
                        self._finalize_user_buffer(user_id, reason="acoustic-silence")
        except asyncio.CancelledError:
            return

    def _finalize_user_buffer(self, user_id: int, *, reason: str) -> None:
        self._quiet_voice_candidates.pop(user_id, None)
        self._voice_preroll.pop(user_id, None)
        buffer = self._buffers.pop(user_id, None)
        if buffer is None:
            return
        duration = buffer.duration_seconds
        if duration < DISCORD_VOICE_MIN_UTTERANCE_SECONDS:
            LOGGER.debug("Dropped short voice utterance from %s: %.2fs", buffer.member, duration)
            self._schedule_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=buffer.member,
                    duration_seconds=duration,
                    voiced_ms=buffer.voiced_ms,
                    max_rms=buffer.max_rms,
                    outcome="dropped before ASR: too short",
                    **self._buffer_local_wake_diag_kwargs(buffer),
                )
            )
            return
        pcm = b"".join(buffer.chunks)
        if not _pcm_has_enough_voice_energy(pcm):
            LOGGER.debug("Dropped quiet/silent voice utterance from %s: %.2fs", buffer.member, duration)
            self._schedule_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=buffer.member,
                    duration_seconds=duration,
                    voiced_ms=buffer.voiced_ms,
                    max_rms=buffer.max_rms,
                    outcome="dropped before ASR: below voice gate",
                    **self._buffer_local_wake_diag_kwargs(buffer),
                )
            )
            return
        if buffer.local_wake_gate_active and not buffer.local_wake_accepted:
            LOGGER.debug(
                "Dropped voice utterance from %s before ASR because local wake word was not detected: duration=%.2fs wake_max=%.3f model=%s",
                buffer.member,
                duration,
                buffer.local_wake_max_score,
                buffer.local_wake_max_model or "-",
            )
            self._schedule_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=buffer.member,
                    duration_seconds=duration,
                    voiced_ms=buffer.voiced_ms,
                    max_rms=buffer.max_rms,
                    outcome="dropped before ASR: local wake word not detected",
                    **self._buffer_local_wake_diag_kwargs(buffer),
                )
            )
            return
        queued_at = time.monotonic()
        utterance = _VoiceUtterance(
            member=buffer.member,
            pcm=pcm,
            duration_seconds=duration,
            voiced_ms=buffer.voiced_ms,
            max_rms=buffer.max_rms,
            stats=buffer.stats,
            queued_at=queued_at,
            last_packet_at=buffer.last_packet_at,
            last_voice_at=buffer.last_voice_at,
            local_wake_gate_active=buffer.local_wake_gate_active,
            local_wake_accepted=buffer.local_wake_accepted,
            local_wake_model=buffer.local_wake_model,
            local_wake_score=buffer.local_wake_score,
            local_wake_max_model=buffer.local_wake_max_model,
            local_wake_max_score=buffer.local_wake_max_score,
        )
        if self._processing_utterance and self._wake_word_gate_enabled():
            self._schedule_interrupt_candidate(utterance)
            LOGGER.debug("Queued interrupt-candidate voice utterance from %s (%.2fs, %s)", buffer.member, duration, reason)
        else:
            try:
                self._queue.put_nowait(utterance)
            except asyncio.QueueFull:
                LOGGER.warning("Dropping voice utterance from %s because the processing queue is full", buffer.member)
                self._schedule_voice_diagnostic(
                    _format_voice_diagnostic_message(
                        member=buffer.member,
                        duration_seconds=duration,
                        voiced_ms=buffer.voiced_ms,
                        max_rms=buffer.max_rms,
                        outcome="dropped before ASR: processing queue full",
                        **self._buffer_local_wake_diag_kwargs(buffer),
                    )
                )
                return
            LOGGER.debug("Queued voice utterance from %s (%.2fs, %s)", buffer.member, duration, reason)
        LOGGER.debug(
            "Discord voice receive diagnostics: guild=%s channel=%s member=%s duration=%.2fs voiced_ms=%.0f max_rms=%s packets=%s pcm_bytes=%s opus_bytes=%s ssrc=%s seq=%s-%s ts=%s-%s seq_gaps=%s missing_packets=%s timestamp_gaps=%s chunk_lengths=%s",
            self.guild.id,
            self.voice_channel.name,
            buffer.member,
            duration,
            buffer.voiced_ms,
            buffer.max_rms,
            buffer.stats.packet_count,
            buffer.stats.pcm_bytes,
            buffer.stats.opus_bytes,
            buffer.stats.ssrc,
            buffer.stats.first_sequence,
            buffer.stats.last_sequence,
            buffer.stats.first_timestamp,
            buffer.stats.last_timestamp,
            buffer.stats.sequence_gap_count,
            buffer.stats.missing_packet_count,
            buffer.stats.timestamp_gap_count,
            buffer.stats.chunk_summary(),
        )

    def _schedule_interrupt_candidate(self, utterance: _VoiceUtterance) -> None:
        task = asyncio.create_task(self._handle_interrupt_candidate(utterance))
        self._interrupt_tasks.add(task)

        def _discard(done_task: asyncio.Task[None]) -> None:
            self._interrupt_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception("Failed to process Discord voice interrupt candidate from %s", utterance.member)

        task.add_done_callback(_discard)

    async def _handle_interrupt_candidate(self, utterance: _VoiceUtterance) -> None:
        if self._stopped or self._interrupt_in_progress:
            return
        voice_input = await asyncio.to_thread(_write_voice_input_wav_tempfile, utterance.pcm)
        wav_path = voice_input.path
        try:
            await self._wait_for_warmup_if_needed()
            try:
                transcript, input_seconds, asr_seconds = await asyncio.to_thread(
                    self.manager.pipeline.transcribe_audio,
                    wav_path,
                )
            except VoicePipelineNoOutputError:
                LOGGER.debug("Interrupt candidate ASR produced no transcript for utterance from %s", utterance.member)
                await self._send_voice_diagnostic(
                    _format_voice_diagnostic_message(
                        member=utterance.member,
                        duration_seconds=utterance.duration_seconds,
                        voiced_ms=utterance.voiced_ms,
                        max_rms=utterance.max_rms,
                        outcome="interrupt candidate: ASR returned no transcript",
                        preprocess=voice_input.diagnostics,
                        **self._utterance_local_wake_diag_kwargs(utterance),
                    )
                )
                return
            if not self._utterance_has_wake_word(utterance, transcript):
                LOGGER.debug("Ignoring interrupt candidate without wake word from %s: %r", utterance.member, transcript[:160])
                await self._send_voice_diagnostic(
                    _format_voice_diagnostic_message(
                        member=utterance.member,
                        duration_seconds=utterance.duration_seconds,
                        voiced_ms=utterance.voiced_ms,
                        max_rms=utterance.max_rms,
                        outcome="interrupt candidate ignored: wake word not detected",
                        preprocess=voice_input.diagnostics,
                        asr_seconds=asr_seconds,
                        transcript=transcript,
                        **self._utterance_local_wake_diag_kwargs(utterance),
                    )
                )
                return
            LOGGER.info("Wake-word steering received from %s: %r", utterance.member, transcript[:160])
            llm_transcript = _normalize_voice_transcript_wake_words(transcript)
            steering_applied = await self._steer_active_voice_turn(llm_transcript)
            await self._send_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=utterance.member,
                    duration_seconds=utterance.duration_seconds,
                    voiced_ms=utterance.voiced_ms,
                    max_rms=utterance.max_rms,
                    outcome="steering applied" if steering_applied else "steering unavailable: cut over to next voice turn",
                    preprocess=voice_input.diagnostics,
                    asr_seconds=asr_seconds,
                    **self._utterance_local_wake_diag_kwargs(utterance),
                )
            )
            if steering_applied:
                metadata = getattr(self._active_turn_context, "metadata", None)
                suppress_status = bool(
                    isinstance(metadata, dict) and metadata.pop("suppress_next_steering_status_message", False)
                )
                if not suppress_status:
                    await self._send_status_message(_format_voice_steering_message(llm_transcript))
            else:
                await self._queue_transcribed_utterance_after_current_turn(
                    utterance,
                    transcript=transcript,
                    input_seconds=input_seconds,
                    asr_seconds=asr_seconds,
                    preprocess=voice_input.diagnostics,
                )
        finally:
            _delete_temporary_paths([wav_path])

    async def _steer_active_voice_turn(self, transcript: str) -> bool:
        steering_callback = self.manager.steering_callback
        if steering_callback is None:
            return False
        llm_transcript = _normalize_voice_transcript_wake_words(transcript)
        try:
            steered = bool(await asyncio.to_thread(steering_callback, self._active_turn_context, llm_transcript))
        except Exception:
            LOGGER.warning("Failed to steer active voice Pi task", exc_info=True)
            return False
        if steered:
            self._mark_steering_tts_boundary()
        return steered

    def _current_steering_tts_generation(self) -> int:
        return self._steering_tts_generation

    def _mark_steering_tts_boundary(self) -> None:
        self._steering_tts_generation += 1
        self._steering_tts_resume_at = time.monotonic() + DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            try:
                self.voice_client.stop()
            except Exception:
                LOGGER.debug("Failed to stop stale Discord voice playback after steering", exc_info=True)

    async def _queue_transcribed_utterance_after_current_turn(
        self,
        utterance: _VoiceUtterance,
        *,
        transcript: str,
        input_seconds: float,
        asr_seconds: float,
        preprocess: _VoicePreprocessDiagnostics,
    ) -> None:
        queued_utterance = replace(
            utterance,
            queued_at=time.monotonic(),
            transcript=transcript,
            input_seconds=input_seconds,
            asr_seconds=asr_seconds,
            preprocess=preprocess,
            is_steering_fallback=True,
        )
        try:
            self._queue.put_nowait(queued_utterance)
        except asyncio.QueueFull:
            LOGGER.warning("Dropping voice steering utterance from %s because the processing queue is full", utterance.member)
            await self._send_status_message("⚠️ I heard you, but I couldn't steer or queue that voice turn because the voice queue is full.")
            return
        LOGGER.debug(
            "Queued no-longer-steerable wake-word utterance from %s as a fresh voice turn; cutting over playback after %.2fs pause",
            utterance.member,
            DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS,
        )
        self._interrupt_requested = True
        self._mark_steering_tts_boundary()
        self._queued_turn_cutover_generation = self._steering_tts_generation

    async def cancel_active_turn(self) -> bool:
        has_active_turn = self._processing_utterance or (
            self._active_pipeline_task is not None and not self._active_pipeline_task.done()
        )
        has_playback = self.voice_client.is_playing() or self.voice_client.is_paused()
        if not has_active_turn and not has_playback:
            return False

        self._interrupt_requested = True
        self._steering_tts_generation += 1
        self._steering_tts_resume_at = 0.0
        self._queued_turn_cutover_generation = max(
            self._queued_turn_cutover_generation,
            self._steering_tts_generation,
        )
        cancel_sent = False
        cancel_callback = self.manager.cancel_callback
        if cancel_callback is not None and self._active_turn_context is not None:
            try:
                cancel_sent = bool(cancel_callback(self._active_turn_context))
            except Exception:
                LOGGER.warning("Failed to cancel active voice Pi task", exc_info=True)
        if has_playback:
            try:
                self.voice_client.stop()
            except Exception:
                LOGGER.debug("Failed to stop Discord voice playback during slash cancel", exc_info=True)
        LOGGER.debug(
            "Discord voice turn cancel requested: active_turn=%s playback=%s rpc_cancel_sent=%s generation=%s",
            has_active_turn,
            has_playback,
            cancel_sent,
            self._steering_tts_generation,
        )
        return has_active_turn or has_playback or cancel_sent

    async def _interrupt_active_voice_turn(self, stop_notice_paths: list[Path]) -> None:
        if self._interrupt_in_progress:
            return
        self._interrupt_in_progress = True
        self._interrupt_requested = True
        try:
            cancel_callback = self.manager.cancel_callback
            if cancel_callback is not None:
                try:
                    cancel_callback(self._active_turn_context)
                except Exception:
                    LOGGER.warning("Failed to cancel active voice Pi task", exc_info=True)
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                try:
                    self.voice_client.stop()
                except Exception:
                    LOGGER.debug("Failed to stop Discord voice playback during interrupt", exc_info=True)
            await self._send_status_message(_format_voice_response_message("Stopping my task, sir."))
            await self._play_stop_notice(stop_notice_paths)
        finally:
            self._interrupt_in_progress = False

    async def _process_utterances(self) -> None:
        try:
            while not self._stopped:
                utterance = await self._queue.get()
                try:
                    self._processing_utterance = True
                    await self._handle_utterance(utterance)
                except Exception:
                    LOGGER.exception("Failed to process Discord voice utterance from %s", utterance.member)
                    await self._send_status_message("⚠️ JARVIS voice request failed; see logs for details.")
                finally:
                    self._processing_utterance = False
                    self._queue.task_done()
        except asyncio.CancelledError:
            return

    async def _handle_utterance(self, utterance: _VoiceUtterance) -> None:
        self._interrupt_requested = False
        turn_started_at = time.monotonic()
        voice_input = await asyncio.to_thread(_write_voice_input_wav_tempfile, utterance.pcm)
        wav_path = voice_input.path
        wav_finished_at = time.monotonic()
        audio_paths: list[Path] = []
        try:
            await self._wait_for_warmup_if_needed()
            preprocess = utterance.preprocess or voice_input.diagnostics
            if utterance.transcript is not None:
                transcript = utterance.transcript.strip()
                input_seconds = utterance.input_seconds if utterance.input_seconds is not None else _audio_duration_seconds(wav_path)
                asr_seconds = utterance.asr_seconds if utterance.asr_seconds is not None else 0.0
                if not transcript:
                    LOGGER.debug("Cached voice transcript was empty for utterance from %s", utterance.member)
                    await self._send_voice_diagnostic(
                        _format_voice_diagnostic_message(
                            member=utterance.member,
                            duration_seconds=utterance.duration_seconds,
                            voiced_ms=utterance.voiced_ms,
                            max_rms=utterance.max_rms,
                            outcome="ASR returned no transcript",
                            preprocess=preprocess,
                            **self._utterance_local_wake_diag_kwargs(utterance),
                        )
                    )
                    return
            else:
                try:
                    transcript, input_seconds, asr_seconds = await asyncio.to_thread(
                        self.manager.pipeline.transcribe_audio,
                        wav_path,
                    )
                except VoicePipelineNoOutputError:
                    LOGGER.debug("Voice ASR produced no transcript for utterance from %s", utterance.member)
                    await self._send_voice_diagnostic(
                        _format_voice_diagnostic_message(
                            member=utterance.member,
                            duration_seconds=utterance.duration_seconds,
                            voiced_ms=utterance.voiced_ms,
                            max_rms=utterance.max_rms,
                            outcome="ASR returned no transcript",
                            preprocess=preprocess,
                            **self._utterance_local_wake_diag_kwargs(utterance),
                        )
                    )
                    return

            if not self._utterance_has_wake_word(utterance, transcript):
                LOGGER.debug("Ignoring voice utterance without wake word from %s: %r", utterance.member, transcript[:160])
                await self._send_voice_diagnostic(
                    _format_voice_diagnostic_message(
                        member=utterance.member,
                        duration_seconds=utterance.duration_seconds,
                        voiced_ms=utterance.voiced_ms,
                        max_rms=utterance.max_rms,
                        outcome="ignored: wake word not detected",
                        preprocess=preprocess,
                        asr_seconds=asr_seconds,
                        transcript=transcript,
                        **self._utterance_local_wake_diag_kwargs(utterance),
                    )
                )
                return

            llm_transcript = _normalize_voice_transcript_wake_words(transcript)
            await self._send_voice_diagnostic(
                _format_voice_diagnostic_message(
                    member=utterance.member,
                    duration_seconds=utterance.duration_seconds,
                    voiced_ms=utterance.voiced_ms,
                    max_rms=utterance.max_rms,
                    outcome="accepted queued steering fallback" if utterance.is_steering_fallback else "accepted",
                    preprocess=preprocess,
                    asr_seconds=asr_seconds,
                    **self._utterance_local_wake_diag_kwargs(utterance),
                )
            )
            turn_generation = self._steering_tts_generation
            status_message = (
                _format_voice_steering_message(llm_transcript)
                if utterance.is_steering_fallback
                else _format_voice_transcript_message(llm_transcript)
            )
            await self._send_status_message(status_message)
            await self._play_processing_ack(audio_paths, steering_generation=turn_generation)
            if self._interrupt_requested:
                LOGGER.debug("Voice turn from %s was cancelled before its Pi task started", utterance.member)
                return
            if self._queued_turn_cutover_generation > turn_generation:
                LOGGER.debug("Voice turn from %s was superseded before its Pi task started", utterance.member)
                return
            pipeline_started_at = time.monotonic()
            use_streaming_playback = self.manager.pipeline.streams_tts_while_llm_generates
            playback_started_at: float | None = None
            playback_finished_at = pipeline_started_at
            streamed_audio_queue: asyncio.Queue[_StreamedAudioPath] = asyncio.Queue()

            def _on_streamed_audio_path(path: Path, steering_generation: int) -> None:
                audio_paths.append(path)
                if not self.loop.is_closed():
                    streamed_audio = _StreamedAudioPath(path=path, steering_generation=steering_generation)
                    self.loop.call_soon_threadsafe(streamed_audio_queue.put_nowait, streamed_audio)

            turn_context = VoiceTurnContext(
                guild=self.guild,
                voice_channel=self.voice_channel,
                member=utterance.member,
                status_channel=self._status_channel,
                steering_generation_provider=self._current_steering_tts_generation,
                steering_tts_delay_seconds=DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS,
            )
            self._active_turn_context = turn_context
            self._interrupt_requested = False

            try:
                if use_streaming_playback:
                    pipeline_task = asyncio.create_task(
                        asyncio.to_thread(
                            self.manager.pipeline.synthesize_turn,
                            wav_path,
                            _on_streamed_audio_path,
                            turn_context,
                            transcript=transcript,
                            input_seconds=input_seconds,
                            asr_seconds=asr_seconds,
                            started_at=turn_started_at,
                        )
                    )
                    self._observe_pipeline_task(pipeline_task)
                    playback_started_at = await self._play_streamed_audio_until_pipeline_done(
                        pipeline_task,
                        streamed_audio_queue,
                    )
                    result = await pipeline_task
                else:
                    pipeline_task = asyncio.create_task(
                        asyncio.to_thread(
                            self.manager.pipeline.synthesize_turn,
                            wav_path,
                            None,
                            turn_context,
                            transcript=transcript,
                            input_seconds=input_seconds,
                            asr_seconds=asr_seconds,
                            started_at=turn_started_at,
                        )
                    )
                    self._observe_pipeline_task(pipeline_task)
                    result = await pipeline_task
            except VoicePipelineNoOutputError:
                if self._interrupt_requested:
                    LOGGER.debug("Voice pipeline stopped after wake-word interrupt from %s", utterance.member)
                    return
                LOGGER.debug("Voice pipeline produced no playable speech for voice utterance from %s", utterance.member)
                raw_clip_percent = _pcm_clip_percent(_truncate_pcm_to_frame_boundary(utterance.pcm, DISCORD_PCM_CHANNELS))
                if raw_clip_percent >= 0.2:
                    await self._send_status_message(
                        "🎙️ I heard audio, but it looks clipped/distorted before voice processing. "
                        "Try lowering Discord/input mic volume, then try again."
                    )
                else:
                    await self._send_status_message("🎙️ I heard audio, but the voice pipeline did not produce a spoken reply. Try again.")
                return
            except Exception as exc:
                if self._interrupt_requested or self._stopped or self._is_expected_pipeline_cancellation(exc):
                    LOGGER.debug("Voice pipeline interrupted for utterance from %s", utterance.member, exc_info=True)
                    return
                raise
            finally:
                self._active_pipeline_task = None
                self._active_turn_context = None
            pipeline_finished_at = time.monotonic()

            if not use_streaming_playback:
                audio_paths.extend(result.audio_paths)
            metadata = getattr(turn_context, "metadata", None)
            response_streamed_to_text = bool(isinstance(metadata, dict) and metadata.get("text_response_streamed"))
            turn_cutover = self._queued_turn_cutover_generation > turn_generation
            if turn_cutover:
                LOGGER.debug("Skipping superseded voice response from %s after queued steering fallback", utterance.member)
            elif result.reply_text and not response_streamed_to_text:
                asyncio.create_task(self._send_status_message(_format_voice_response_message(result.reply_text)))

            if use_streaming_playback:
                playback_finished_at = time.monotonic()
                if playback_started_at is None:
                    playback_started_at = playback_finished_at
            else:
                playback_started_at = time.monotonic()
                if not turn_cutover:
                    for audio_path in result.audio_paths:
                        if self._queued_turn_cutover_generation > turn_generation:
                            LOGGER.debug("Stopping superseded non-streaming voice playback from %s", utterance.member)
                            break
                        await self._play_audio_file(audio_path, steering_generation=turn_generation)
                playback_finished_at = time.monotonic()
            LOGGER.debug(
                "Discord voice pipeline turn timing: speech_end_to_playback=%.2fs queue_wait=%.2fs wav=%.2fs pipeline=%.2fs asr=%.2fs llm=%.2fs tts=%.2fs playback=%.2fs total=%.2fs input=%.2fs output=%.2fs",
                playback_started_at - utterance.last_voice_at,
                turn_started_at - utterance.queued_at,
                wav_finished_at - turn_started_at,
                pipeline_finished_at - pipeline_started_at,
                result.asr_seconds,
                result.llm_seconds,
                result.tts_seconds,
                playback_finished_at - playback_started_at,
                playback_finished_at - turn_started_at,
                result.input_seconds,
                result.output_seconds,
            )
        finally:
            _delete_temporary_paths([wav_path, *audio_paths])

    @staticmethod
    def _wake_word_gate_enabled() -> bool:
        return bool(DISCORD_VOICE_WAKE_WORDS)

    @staticmethod
    def _transcript_has_wake_word(transcript: str) -> bool:
        wake_words = DISCORD_VOICE_WAKE_WORDS
        if not wake_words:
            return True
        return any(
            re.search(rf"(?<!\w){re.escape(wake_word)}(?!\w)", transcript or "", re.IGNORECASE) is not None
            for wake_word in wake_words
        )

    @staticmethod
    def _utterance_has_wake_word(utterance: _VoiceUtterance, transcript: str) -> bool:
        if _JarvisVoiceConversation._transcript_has_wake_word(transcript):
            return True
        return bool(
            DISCORD_VOICE_TRUST_LOCAL_WAKE_WORD
            and utterance.local_wake_gate_active
            and utterance.local_wake_accepted
        )

    async def _play_stop_notice(self, audio_paths: list[Path]) -> None:
        try:
            stop_path = await asyncio.to_thread(
                self.manager.pipeline.synthesize_notice,
                "Stopping my task, sir.",
            )
            audio_paths.append(stop_path)
            await self._play_audio_file(stop_path)
        except Exception:
            LOGGER.warning("Failed to play Discord voice stop acknowledgement", exc_info=True)

    async def _play_processing_ack(self, audio_paths: list[Path], *, steering_generation: int | None = None) -> None:
        if not DISCORD_VOICE_PROCESSING_ACK_ENABLED or not DISCORD_VOICE_PROCESSING_ACK_TEXT:
            return
        try:
            ack_path = await asyncio.to_thread(
                self.manager.pipeline.synthesize_notice,
                DISCORD_VOICE_PROCESSING_ACK_TEXT,
            )
            audio_paths.append(ack_path)
            await self._play_audio_file(ack_path, steering_generation=steering_generation)
        except Exception:
            LOGGER.warning("Failed to play Discord voice processing acknowledgement", exc_info=True)

    def _is_busy_with_voice_turn(self) -> bool:
        return (
            self._processing_utterance
            or not self._queue.empty()
            or self.voice_client.is_playing()
            or self.voice_client.is_paused()
        )

    async def _play_streamed_audio_until_pipeline_done(
        self,
        pipeline_task: asyncio.Task[VoicePipelineResult],
        audio_queue: asyncio.Queue[_StreamedAudioPath],
    ) -> float | None:
        playback_started_at: float | None = None
        while True:
            if self._interrupt_requested:
                while not audio_queue.empty():
                    try:
                        audio_queue.get_nowait()
                        audio_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                return playback_started_at
            if pipeline_task.done() and audio_queue.empty():
                # Let any final call_soon_threadsafe queue handoff run before we stop draining.
                await asyncio.sleep(0)
                if audio_queue.empty():
                    return playback_started_at

            get_task = asyncio.create_task(audio_queue.get())
            done, _pending = await asyncio.wait(
                {pipeline_task, get_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                if self._interrupt_requested:
                    get_task.result()
                    audio_queue.task_done()
                    return playback_started_at
                streamed_audio = get_task.result()
                if streamed_audio.steering_generation < self._steering_tts_generation:
                    audio_queue.task_done()
                    continue
                remaining_delay = self._steering_tts_resume_at - time.monotonic()
                if remaining_delay > 0:
                    await asyncio.sleep(remaining_delay)
                if streamed_audio.steering_generation < self._steering_tts_generation:
                    audio_queue.task_done()
                    continue
                if playback_started_at is None:
                    playback_started_at = time.monotonic()
                await self._play_audio_file(streamed_audio.path, steering_generation=streamed_audio.steering_generation)
                audio_queue.task_done()
                continue

            get_task.cancel()
            await asyncio.gather(get_task, return_exceptions=True)
            if pipeline_task.done() and audio_queue.empty():
                await asyncio.sleep(0)
                if audio_queue.empty():
                    return playback_started_at

    @staticmethod
    def _is_expected_pipeline_cancellation(exc: BaseException) -> bool:
        return exc.__class__.__name__ == "PiRpcCancelledError"

    def _observe_pipeline_task(self, task: asyncio.Task[VoicePipelineResult]) -> None:
        task.add_done_callback(self._drain_pipeline_task_exception)
        self._active_pipeline_task = task

    def _drain_pipeline_task_exception(self, task: asyncio.Task[VoicePipelineResult]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            LOGGER.debug("Failed to inspect completed voice pipeline task", exc_info=True)
            return
        if exc is None:
            return
        if self._stopped or self._interrupt_requested or self._is_expected_pipeline_cancellation(exc):
            LOGGER.debug("Voice pipeline task ended after cancellation/stop: %s", exc)
            return
        LOGGER.debug(
            "Voice pipeline task ended with an exception before it was awaited",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _is_stale_steering_generation(self, steering_generation: int | None) -> bool:
        return steering_generation is not None and steering_generation < self._steering_tts_generation

    async def _wait_for_steering_tts_resume(self) -> None:
        while True:
            remaining_delay = self._steering_tts_resume_at - time.monotonic()
            if remaining_delay <= 0:
                return
            await asyncio.sleep(remaining_delay)

    async def _play_audio_file(self, path: Path, *, steering_generation: int | None = None) -> bool:
        if self._is_stale_steering_generation(steering_generation):
            return False
        await self._wait_for_steering_tts_resume()
        if self._is_stale_steering_generation(steering_generation):
            return False
        async with self._playback_lock:
            if self._is_stale_steering_generation(steering_generation):
                return False
            while self.voice_client.is_playing() or self.voice_client.is_paused():
                await asyncio.sleep(0.1)
                if self._is_stale_steering_generation(steering_generation):
                    return False
            if self._is_stale_steering_generation(steering_generation):
                return False
            playback_done = asyncio.Event()

            def _after_playback(error: Exception | None) -> None:
                if error is not None:
                    LOGGER.error("Discord voice playback failed: %s", error)
                if not self.loop.is_closed():
                    self.loop.call_soon_threadsafe(playback_done.set)

            # discord.py expects stderr to be either None or a file-like object.
            # subprocess.DEVNULL is an int fd, which makes discord.py try to call
            # .write() on an int in its stderr-forwarding thread. Open os.devnull
            # as a real file object so FFmpeg output is discarded safely.
            with open(os.devnull, "wb") as ffmpeg_stderr:
                self.voice_client.play(
                    discord.FFmpegPCMAudio(
                        str(path),
                        before_options="-nostdin -hide_banner -loglevel panic",
                        stderr=ffmpeg_stderr,
                    ),
                    after=_after_playback,
                )
                await playback_done.wait()
                return True

    def _after_listen(self, error: Exception | None) -> None:
        if error is not None:
            LOGGER.error("Discord voice receive failed in %s: %s", self.voice_channel.name, error)

    def _find_status_channel(self) -> discord.abc.Messageable | None:
        if DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME:
            channel = self._find_messageable_channel_by_name(DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME)
            if channel is not None:
                return channel
            LOGGER.warning(
                "Configured Discord voice status channel %r was not found; using voice channel chat instead.",
                DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME,
            )

        # Voice channels have their own text chat in Discord.  Use the active
        # voice channel by default so live voice status messages stay beside
        # the call instead of falling back to jarvis-chat1.
        return self.voice_channel

    def _find_messageable_channel_by_name(self, name: str) -> discord.abc.Messageable | None:
        normalized = name.lower().strip()
        if not normalized:
            return None
        for channel in (*self.guild.text_channels, *self.guild.voice_channels):
            if channel.name.lower() == normalized and isinstance(channel, discord.abc.Messageable):
                return channel
        return None

    def _schedule_voice_diagnostic(self, content: str) -> None:
        if not DISCORD_VOICE_STATUS_DIAGNOSTICS or self._stopped:
            return
        LOGGER.info("%s", content)

    async def _send_voice_diagnostic(self, content: str) -> None:
        if not DISCORD_VOICE_STATUS_DIAGNOSTICS:
            return
        LOGGER.info("%s", content)

    async def _send_status_message(self, content: str) -> None:
        if self._status_channel is None:
            return
        try:
            for chunk in _chunk_text(content):
                await self._status_channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            LOGGER.debug("Failed to send Discord voice status message", exc_info=True)



def _write_voice_input_wav_tempfile(pcm: bytes) -> _VoiceInputWav:
    wav_pcm, channels, sample_rate, diagnostics = _prepare_pcm_for_voice_pipeline(pcm)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix="jarvis_voice_")
    path = Path(handle.name).resolve()
    handle.close()
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(DISCORD_PCM_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(wav_pcm)
    return _VoiceInputWav(path=path, diagnostics=diagnostics)


def _discord_pcm_to_local_wake_pcm(pcm: bytes, *, ratecv_state_holder: object) -> bytes:
    if audioop is None or not pcm:
        return b""
    aligned_pcm = _truncate_pcm_to_frame_boundary(pcm, DISCORD_PCM_CHANNELS)
    if not aligned_pcm:
        return b""
    mono_mode = DISCORD_VOICE_MONO_MODE if DISCORD_VOICE_MONO_MODE in {"left", "right", "average"} else "left"
    if mono_mode == "right":
        mono_pcm = audioop.tomono(aligned_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 0.0, 1.0)
    elif mono_mode == "average":
        mono_pcm = audioop.tomono(aligned_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 0.5, 0.5)
    else:
        mono_pcm = audioop.tomono(aligned_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 1.0, 0.0)
    if DISCORD_PCM_SAMPLE_RATE == _DiscordOpenWakeWordDetector.target_rate:
        return mono_pcm
    state = getattr(ratecv_state_holder, "_ratecv_state", None)
    mono_pcm, state = audioop.ratecv(
        mono_pcm,
        DISCORD_PCM_SAMPLE_WIDTH_BYTES,
        1,
        DISCORD_PCM_SAMPLE_RATE,
        _DiscordOpenWakeWordDetector.target_rate,
        state,
    )
    setattr(ratecv_state_holder, "_ratecv_state", state)
    return mono_pcm


def _pcm_frame_has_voice_energy(pcm: bytes) -> tuple[bool, int]:
    if not pcm:
        return False, 0
    if audioop is None or not DISCORD_VOICE_PREPROCESS_AUDIO or DISCORD_VOICE_SILENCE_RMS_THRESHOLD <= 0:
        return True, 0
    try:
        rms = audioop.rms(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES)
    except Exception:
        return True, 0
    return rms >= DISCORD_VOICE_SILENCE_RMS_THRESHOLD, rms


def _pcm_has_enough_voice_energy(pcm: bytes) -> bool:
    if not pcm:
        return False
    if audioop is None or not DISCORD_VOICE_PREPROCESS_AUDIO or DISCORD_VOICE_SILENCE_RMS_THRESHOLD <= 0:
        return True

    voiced_ms = 0.0
    max_rms = 0
    for frame in _iter_pcm_frames(pcm, frame_ms=20):
        try:
            rms = audioop.rms(frame, DISCORD_PCM_SAMPLE_WIDTH_BYTES)
        except Exception:
            return True
        max_rms = max(max_rms, rms)
        if rms >= DISCORD_VOICE_SILENCE_RMS_THRESHOLD:
            voiced_ms += (len(frame) / DISCORD_PCM_BYTES_PER_SECOND) * 1000.0

    if DISCORD_VOICE_MIN_VOICED_MS <= 0:
        return max_rms >= DISCORD_VOICE_SILENCE_RMS_THRESHOLD
    return voiced_ms >= DISCORD_VOICE_MIN_VOICED_MS


def _pcm_clip_percent(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    sample_count = len(pcm) // DISCORD_PCM_SAMPLE_WIDTH_BYTES
    if sample_count <= 0:
        return 0.0
    usable_pcm = pcm[: sample_count * DISCORD_PCM_SAMPLE_WIDTH_BYTES]
    samples = array.array("h")
    samples.frombytes(usable_pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    clipped = sum(1 for sample in samples if sample <= -32768 or sample >= 32767)
    return (clipped / sample_count) * 100.0


def _prepare_pcm_for_voice_pipeline(pcm: bytes) -> tuple[bytes, int, int, _VoicePreprocessDiagnostics]:
    fallback_diagnostics = _VoicePreprocessDiagnostics(
        input_seconds=len(pcm) / DISCORD_PCM_BYTES_PER_SECOND if pcm else 0.0,
        output_seconds=len(pcm) / DISCORD_PCM_BYTES_PER_SECOND if pcm else 0.0,
        mono_mode="raw",
        selected_rms=audioop.rms(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if audioop is not None and pcm else 0,
        normalized_rms=audioop.rms(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if audioop is not None and pcm else 0,
        selected_peak=audioop.max(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if audioop is not None and pcm else 0,
        normalized_peak=audioop.max(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if audioop is not None and pcm else 0,
        gain=1.0,
        clipped_percent=_pcm_clip_percent(pcm),
    )
    if audioop is None or not DISCORD_VOICE_PREPROCESS_AUDIO or not pcm:
        return pcm, DISCORD_PCM_CHANNELS, DISCORD_PCM_SAMPLE_RATE, fallback_diagnostics

    try:
        aligned_pcm = _truncate_pcm_to_frame_boundary(pcm, DISCORD_PCM_CHANNELS)
        trimmed_pcm = _trim_pcm_silence(aligned_pcm) or aligned_pcm
        left_pcm = audioop.tomono(trimmed_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 1.0, 0.0)
        right_pcm = audioop.tomono(trimmed_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 0.0, 1.0)
        mono_mode = DISCORD_VOICE_MONO_MODE if DISCORD_VOICE_MONO_MODE in {"left", "right", "average"} else "left"
        if mono_mode == "right":
            mono_pcm = right_pcm
        elif mono_mode == "average":
            mono_pcm = audioop.tomono(trimmed_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, 0.5, 0.5)
        else:
            mono_pcm = left_pcm
        LOGGER.debug(
            "Raw Discord voice PCM stats: duration=%.2fs mono=%s left_rms=%s right_rms=%s left_peak=%s right_peak=%s clipped=%.2f%%",
            len(pcm) / DISCORD_PCM_BYTES_PER_SECOND,
            mono_mode,
            audioop.rms(left_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if left_pcm else 0,
            audioop.rms(right_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if right_pcm else 0,
            audioop.max(left_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if left_pcm else 0,
            audioop.max(right_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if right_pcm else 0,
            _pcm_clip_percent(aligned_pcm),
        )
        target_rate = DISCORD_VOICE_INPUT_SAMPLE_RATE
        if target_rate != DISCORD_PCM_SAMPLE_RATE:
            mono_pcm, _ = audioop.ratecv(
                mono_pcm,
                DISCORD_PCM_SAMPLE_WIDTH_BYTES,
                1,
                DISCORD_PCM_SAMPLE_RATE,
                target_rate,
                None,
            )
        selected_rms = audioop.rms(mono_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if mono_pcm else 0
        selected_peak = audioop.max(mono_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if mono_pcm else 0
        normalized_pcm, gain = _normalize_pcm_level(mono_pcm)
        normalized_rms = audioop.rms(normalized_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if normalized_pcm else 0
        normalized_peak = audioop.max(normalized_pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES) if normalized_pcm else 0
        padded_pcm = _pad_pcm_to_min_duration(normalized_pcm, sample_rate=target_rate, channels=1)
        diagnostics = _VoicePreprocessDiagnostics(
            input_seconds=len(pcm) / DISCORD_PCM_BYTES_PER_SECOND,
            output_seconds=len(padded_pcm) / (target_rate * DISCORD_PCM_SAMPLE_WIDTH_BYTES),
            mono_mode=mono_mode,
            selected_rms=selected_rms,
            normalized_rms=normalized_rms,
            selected_peak=selected_peak,
            normalized_peak=normalized_peak,
            gain=gain,
            clipped_percent=_pcm_clip_percent(aligned_pcm),
        )
        LOGGER.debug(
            "Prepared voice audio for oMLX voice pipeline: input=%.2fs output=%.2fs rms=%s->%s peak=%s->%s gain=%.2fx",
            diagnostics.input_seconds,
            diagnostics.output_seconds,
            diagnostics.selected_rms,
            diagnostics.normalized_rms,
            diagnostics.selected_peak,
            diagnostics.normalized_peak,
            diagnostics.gain,
        )
        return padded_pcm, 1, target_rate, diagnostics
    except Exception:
        LOGGER.debug("Failed to preprocess Discord voice PCM; using original audio", exc_info=True)
        return pcm, DISCORD_PCM_CHANNELS, DISCORD_PCM_SAMPLE_RATE, fallback_diagnostics


def _truncate_pcm_to_frame_boundary(pcm: bytes, channels: int) -> bytes:
    frame_bytes = DISCORD_PCM_SAMPLE_WIDTH_BYTES * channels
    if frame_bytes <= 0:
        return pcm
    usable_bytes = len(pcm) - (len(pcm) % frame_bytes)
    return pcm[:usable_bytes]


def _iter_pcm_frames(pcm: bytes, *, frame_ms: int) -> list[bytes]:
    frame_bytes = int(DISCORD_PCM_BYTES_PER_SECOND * (frame_ms / 1000.0))
    frame_bytes -= frame_bytes % (DISCORD_PCM_SAMPLE_WIDTH_BYTES * DISCORD_PCM_CHANNELS)
    if frame_bytes <= 0:
        frame_bytes = DISCORD_PCM_SAMPLE_WIDTH_BYTES * DISCORD_PCM_CHANNELS
    aligned_pcm = _truncate_pcm_to_frame_boundary(pcm, DISCORD_PCM_CHANNELS)
    return [aligned_pcm[index : index + frame_bytes] for index in range(0, len(aligned_pcm), frame_bytes) if aligned_pcm[index : index + frame_bytes]]


def _trim_pcm_silence(pcm: bytes) -> bytes:
    if audioop is None or DISCORD_VOICE_SILENCE_RMS_THRESHOLD <= 0:
        return pcm

    frames = _iter_pcm_frames(pcm, frame_ms=20)
    if not frames:
        return b""

    voiced_ranges: list[tuple[int, int]] = []
    cursor = 0
    for frame in frames:
        frame_start = cursor
        frame_end = frame_start + len(frame)
        cursor = frame_end
        if audioop.rms(frame, DISCORD_PCM_SAMPLE_WIDTH_BYTES) >= DISCORD_VOICE_SILENCE_RMS_THRESHOLD:
            voiced_ranges.append((frame_start, frame_end))

    if not voiced_ranges:
        return b""

    padding_ms = max(DISCORD_VOICE_SILENCE_PADDING_MS, DISCORD_VOICE_PREROLL_MS)
    padding_bytes = int(DISCORD_PCM_BYTES_PER_SECOND * (padding_ms / 1000.0))
    alignment = DISCORD_PCM_SAMPLE_WIDTH_BYTES * DISCORD_PCM_CHANNELS
    padding_bytes -= padding_bytes % alignment
    start = max(0, voiced_ranges[0][0] - padding_bytes)
    end = min(len(pcm), voiced_ranges[-1][1] + padding_bytes)
    start -= start % alignment
    end -= end % alignment
    return pcm[start:end]


def _pad_pcm_to_min_duration(pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
    if not pcm or DISCORD_VOICE_INPUT_MIN_SECONDS <= 0:
        return pcm
    bytes_per_second = sample_rate * channels * DISCORD_PCM_SAMPLE_WIDTH_BYTES
    min_bytes = int(bytes_per_second * DISCORD_VOICE_INPUT_MIN_SECONDS)
    frame_bytes = channels * DISCORD_PCM_SAMPLE_WIDTH_BYTES
    min_bytes += (-min_bytes) % frame_bytes
    if len(pcm) >= min_bytes:
        return pcm
    missing = min_bytes - len(pcm)
    before = (missing // 2) - ((missing // 2) % frame_bytes)
    after = missing - before
    return (b"\x00" * before) + pcm + (b"\x00" * after)


def _normalize_pcm_level(pcm: bytes) -> tuple[bytes, float]:
    if audioop is None or not pcm:
        return pcm, 1.0

    gain_candidates: list[float] = []
    rms = audioop.rms(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES)
    if DISCORD_VOICE_NORMALIZE_TARGET_RMS > 0 and rms > 0:
        gain_candidates.append(DISCORD_VOICE_NORMALIZE_TARGET_RMS / rms)

    peak = audioop.max(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES)
    if DISCORD_VOICE_NORMALIZE_TARGET_PEAK > 0 and peak > 0:
        gain_candidates.append(DISCORD_VOICE_NORMALIZE_TARGET_PEAK / peak)

    if not gain_candidates:
        return pcm, 1.0

    attenuation_candidates = [candidate for candidate in gain_candidates if candidate < 0.99]
    if attenuation_candidates:
        # If Discord/input processing is already too loud, scale down before voice processing.
        # This cannot undo hard clipping, but voice processing is much more likely to
        # reject clipped audio when it is also near full-scale volume.
        gain = max(0.05, min(attenuation_candidates))
        return audioop.mul(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, gain), gain

    # Use the larger gain request for quiet microphones, while capping the boost
    # and clipping ceiling. audioop.mul clips samples rather than wrapping.
    gain = min(DISCORD_VOICE_NORMALIZE_MAX_GAIN, max(gain_candidates))
    if gain <= 1.01:
        return pcm, 1.0
    return audioop.mul(pcm, DISCORD_PCM_SAMPLE_WIDTH_BYTES, gain), gain



@dataclass(frozen=True)
class VoiceTurnContext:
    guild: discord.Guild
    voice_channel: discord.VoiceChannel
    member: discord.Member
    status_channel: discord.abc.Messageable | None = None
    steering_generation_provider: Callable[[], int] | None = None
    steering_tts_delay_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

class JarvisVoiceManager:
    def __init__(
        self,
        client: discord.Client,
        pipeline: OmlxVoicePipeline | None = None,
        *,
        cancel_callback: VoiceCancelCallback | None = None,
        steering_callback: VoiceSteeringCallback | None = None,
        session_start_callback: VoiceSessionLifecycleCallback | None = None,
        session_end_callback: VoiceSessionLifecycleCallback | None = None,
    ) -> None:
        self.client = client
        self.pipeline = pipeline or OmlxVoicePipeline()
        self.cancel_callback = cancel_callback
        self.steering_callback = steering_callback
        self.session_start_callback = session_start_callback
        self.session_end_callback = session_end_callback
        self._voice_conversations: dict[int, _JarvisVoiceConversation] = {}
        self._voice_sync_tasks: dict[int, asyncio.Task[None]] = {}
        self._voice_sync_locks: dict[int, asyncio.Lock] = {}

    async def sync_all_voice_channels(self) -> None:
        if not DISCORD_VOICE_ENABLED:
            return
        if voice_recv is None:
            LOGGER.warning(
                "Discord voice is enabled, but discord-ext-voice-recv is not installed. "
                "Install requirements.txt to enable jarvis listening."
            )
            return
        self._load_discord_opus()
        await asyncio.gather(*(self._sync_guild_voice_channel(guild) for guild in self.client.guilds))

    def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.guild is None:
            return
        if self.voice_state_mentions_target_channel(before, after):
            self.schedule_voice_sync(member.guild)

    def schedule_voice_sync(self, guild: discord.Guild) -> None:
        if not DISCORD_VOICE_ENABLED:
            return
        existing_task = self._voice_sync_tasks.get(guild.id)
        if existing_task is not None and not existing_task.done():
            return

        async def _run() -> None:
            try:
                await self._sync_guild_voice_channel(guild)
            finally:
                if self._voice_sync_tasks.get(guild.id) is task:
                    self._voice_sync_tasks.pop(guild.id, None)

        task = asyncio.create_task(_run())
        self._voice_sync_tasks[guild.id] = task

    async def cancel_voice_channel(self, channel: discord.VoiceChannel) -> bool:
        conversation = self._voice_conversations.get(channel.guild.id)
        if conversation is None or conversation.voice_channel.id != channel.id:
            return False
        return await conversation.cancel_active_turn()

    async def stop_all(self) -> None:
        sync_tasks = list(self._voice_sync_tasks.values())
        self._voice_sync_tasks.clear()
        for task in sync_tasks:
            task.cancel()
        if sync_tasks:
            await asyncio.gather(*sync_tasks, return_exceptions=True)

        voice_conversations = list(self._voice_conversations.values())
        self._voice_conversations.clear()
        if voice_conversations:
            await asyncio.gather(*(conversation.stop() for conversation in voice_conversations), return_exceptions=True)

    async def _sync_guild_voice_channel(self, guild: discord.Guild) -> None:
        lock = self._voice_sync_locks.get(guild.id)
        if lock is None:
            lock = asyncio.Lock()
            self._voice_sync_locks[guild.id] = lock
        async with lock:
            await self._sync_guild_voice_channel_locked(guild)

    async def _wait_for_voice_privacy_ready(self, voice_client: discord.VoiceClient) -> None:
        voice_state = getattr(voice_client, "_connection", None)
        if voice_state is None:
            return
        dave_protocol = getattr(voice_state, "dave_protocol_version", 0)
        dave_session = getattr(voice_state, "dave_session", None)
        if not dave_protocol or dave_session is None:
            return
        for _ in range(20):
            if getattr(dave_session, "ready", False):
                LOGGER.debug(
                    "Discord DAVE voice privacy ready before listening: protocol=%s channel=%s",
                    dave_protocol,
                    getattr(getattr(voice_client, "channel", None), "name", None),
                )
                return
            await asyncio.sleep(0.25)
        LOGGER.warning(
            "Discord DAVE voice privacy was not ready before listening after 5.0s: protocol=%s channel=%s",
            dave_protocol,
            getattr(getattr(voice_client, "channel", None), "name", None),
        )

    async def _sync_guild_voice_channel_locked(self, guild: discord.Guild) -> None:
        if voice_recv is None:
            return
        channel = self._find_voice_channel(guild)
        if channel is None:
            existing = self._voice_conversations.pop(guild.id, None)
            if existing is not None:
                await existing.stop()
            return

        non_bot_members = [member for member in channel.members if not member.bot]
        has_non_bot_member = bool(non_bot_members)
        existing = self._voice_conversations.get(guild.id)
        LOGGER.debug(
            "Discord voice sync: guild=%s target_channel=%s channel_id=%s human_members=%s join_when_empty=%s existing=%s",
            guild.id,
            channel.name,
            channel.id,
            [member.display_name for member in non_bot_members],
            DISCORD_VOICE_JOIN_WHEN_EMPTY,
            existing is not None,
        )
        if not has_non_bot_member and not DISCORD_VOICE_JOIN_WHEN_EMPTY:
            if existing is not None:
                self._voice_conversations.pop(guild.id, None)
                await existing.stop()
            return

        if existing is not None and existing.voice_channel.id == channel.id:
            voice_state = getattr(existing.voice_client, "_connection", None)
            dave_session = getattr(voice_state, "dave_session", None)
            dave_protocol = getattr(voice_state, "dave_protocol_version", 0)
            dave_ready = not dave_protocol or dave_session is None or bool(getattr(dave_session, "ready", False))
            if not has_non_bot_member or dave_ready:
                return
            LOGGER.warning(
                "Reconnecting Discord voice listener because a human joined but DAVE voice privacy is still not ready: guild=%s channel=%s protocol=%s",
                guild.id,
                channel.name,
                dave_protocol,
            )
            self._voice_conversations.pop(guild.id, None)
            await existing.stop()
        elif existing is not None:
            self._voice_conversations.pop(guild.id, None)
            await existing.stop()

        try:
            self._load_discord_opus()
            voice_client = self._existing_voice_client_for_guild(guild)
            if voice_client is not None and voice_client.is_connected():
                connected_channel = getattr(voice_client, "channel", None)
                if not isinstance(connected_channel, discord.VoiceChannel) or connected_channel.id != channel.id:
                    await voice_client.disconnect(force=True)
                    voice_client = None
            if voice_client is None or not voice_client.is_connected():
                voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)  # type: ignore[union-attr]
            await self._wait_for_voice_privacy_ready(voice_client)
            conversation = _JarvisVoiceConversation(
                manager=self,
                guild=guild,
                voice_channel=channel,
                voice_client=voice_client,
            )
            conversation.start()
            self._voice_conversations[guild.id] = conversation
        except discord.ClientException as exc:
            if "Already connected" not in str(exc):
                LOGGER.exception("Failed to join/listen to Discord voice channel %s in guild %s", channel.name, guild.id)
                return
            LOGGER.warning("Discord voice state was already connected; forcing a clean reconnect for guild %s", guild.id)
            voice_client = self._existing_voice_client_for_guild(guild)
            if voice_client is not None:
                try:
                    await voice_client.disconnect(force=True)
                except Exception:
                    LOGGER.debug("Failed to disconnect stale Discord voice client", exc_info=True)
            try:
                voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)  # type: ignore[union-attr]
                await self._wait_for_voice_privacy_ready(voice_client)
                conversation = _JarvisVoiceConversation(
                    manager=self,
                    guild=guild,
                    voice_channel=channel,
                    voice_client=voice_client,
                )
                conversation.start()
                self._voice_conversations[guild.id] = conversation
            except Exception:
                LOGGER.exception("Failed to reconnect/listen to Discord voice channel %s in guild %s", channel.name, guild.id)
        except Exception:
            LOGGER.exception("Failed to join/listen to Discord voice channel %s in guild %s", channel.name, guild.id)

    def _existing_voice_client_for_guild(self, guild: discord.Guild) -> discord.VoiceClient | None:
        guild_voice_client = getattr(guild, "voice_client", None)
        if isinstance(guild_voice_client, discord.VoiceClient):
            return guild_voice_client
        for voice_client in self.client.voice_clients:
            if getattr(voice_client, "guild", None) == guild and isinstance(voice_client, discord.VoiceClient):
                return voice_client
        return None

    def _find_voice_channel(self, guild: discord.Guild) -> discord.VoiceChannel | None:
        for channel in guild.voice_channels:
            if channel.name.lower() == DISCORD_VOICE_CHANNEL_NAME:
                return channel
        return None

    def voice_state_mentions_target_channel(
        self,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> bool:
        before_channel = before.channel
        after_channel = after.channel
        return any(
            isinstance(channel, discord.VoiceChannel) and channel.name.lower() == DISCORD_VOICE_CHANNEL_NAME
            for channel in (before_channel, after_channel)
        )

    def _load_discord_opus(self) -> None:
        try:
            if discord.opus.is_loaded():
                return
            load_default = getattr(discord.opus, "_load_default", None)
            if callable(load_default):
                load_default()
        except Exception:
            LOGGER.debug("Discord opus auto-load failed; voice playback may still work through ffmpeg/opus.", exc_info=True)

