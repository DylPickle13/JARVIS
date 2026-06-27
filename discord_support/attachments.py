from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Callable

import discord
import requests

import config
from discord_support.formatting import format_bytes, format_discord_block_quote

PROJECT_ROOT = config.PROJECT_ROOT
config.load_project_env(config.DOTENV_PATH)
LOGGER = config.get_logger("jarvis.discord_bot")

ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"
DISCORD_IMAGE_ATTACHMENT_MAX_BYTES = config.get_int_env(
    "DISCORD_IMAGE_ATTACHMENT_MAX_BYTES",
    20 * 1024 * 1024,
    minimum=1,
)
DEFAULT_VOICE_MESSAGE_ASR_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_VOICE_MESSAGE_ASR_MODEL = "mlx-community/whisper-large-v3-turbo-asr-4bit"
DISCORD_VOICE_MESSAGE_ASR_ENABLED = config.get_str_env("DISCORD_VOICE_MESSAGE_ASR_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_MESSAGE_ASR_BASE_URL = config.get_str_env(
    "DISCORD_VOICE_MESSAGE_ASR_BASE_URL",
    config.get_str_env("DISCORD_VOICE_BASE_URL", config.get_str_env("OMLX_BASE_URL", DEFAULT_VOICE_MESSAGE_ASR_BASE_URL)),
).rstrip("/")
DISCORD_VOICE_MESSAGE_ASR_API_KEY = config.get_str_env(
    "DISCORD_VOICE_MESSAGE_ASR_API_KEY",
    config.get_str_env("DISCORD_VOICE_API_KEY", config.get_str_env("OMLX_API_KEY", "")),
)
DISCORD_VOICE_MESSAGE_ASR_MODEL = config.get_str_env(
    "DISCORD_VOICE_MESSAGE_ASR_MODEL",
    config.get_str_env("DISCORD_VOICE_ASR_MODEL", DEFAULT_VOICE_MESSAGE_ASR_MODEL),
)
DISCORD_VOICE_MESSAGE_ASR_LANGUAGE = config.get_str_env("DISCORD_VOICE_MESSAGE_ASR_LANGUAGE", "en")
DISCORD_VOICE_MESSAGE_ASR_TIMEOUT_SECONDS = config.get_float_env(
    "DISCORD_VOICE_MESSAGE_ASR_TIMEOUT_SECONDS",
    120.0,
    minimum=1.0,
)
DISCORD_VOICE_MESSAGE_ASR_RETRIES = config.get_int_env(
    "DISCORD_VOICE_MESSAGE_ASR_RETRIES",
    2,
    minimum=0,
)
DISCORD_VOICE_MESSAGE_ASR_RETRY_BACKOFF_SECONDS = config.get_float_env(
    "DISCORD_VOICE_MESSAGE_ASR_RETRY_BACKOFF_SECONDS",
    0.75,
    minimum=0.0,
)
DISCORD_VOICE_MESSAGE_MAX_BYTES = config.get_int_env(
    "DISCORD_VOICE_MESSAGE_MAX_BYTES",
    25 * 1024 * 1024,
    minimum=1,
)
IMAGE_MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ico": "image/x-icon",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
VOICE_MESSAGE_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "application/ogg",
}
VOICE_MESSAGE_EXTENSIONS = {
    ".ogg",
    ".oga",
    ".opus",
}
VOICE_MESSAGE_FILE_MIME_BY_EXTENSION = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
}


def sanitize_attachment_filename(filename: str) -> str:
    safe_name = Path(filename).name.strip()
    return safe_name or "attachment"


async def save_message_attachments(
    message: discord.Message,
    *,
    include: Callable[[discord.Attachment], bool] | None = None,
) -> list[Path]:
    """Save selected Discord attachments under ATTACHMENTS_DIR and return their paths."""
    if not message.attachments:
        return []

    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    for index, attachment in enumerate(message.attachments, start=1):
        if include is not None and not include(attachment):
            continue
        safe_filename = sanitize_attachment_filename(attachment.filename)
        try:
            data = await attachment.read()
            target_path = ATTACHMENTS_DIR / f"{message.id}_{index}_{safe_filename}"
            target_path.write_bytes(data)
            saved_paths.append(target_path.resolve())
        except Exception:
            LOGGER.exception(
                "Failed to save attachment %r from message %s in channel %s",
                attachment.filename,
                message.id,
                getattr(message.channel, "id", "unknown"),
            )

    return saved_paths


def delete_temporary_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            LOGGER.exception("Failed to delete temporary file %s", path)


def is_voice_message_attachment(attachment: discord.Attachment) -> bool:
    try:
        if attachment.is_voice_message():
            return True
    except Exception:
        LOGGER.debug("Failed to inspect Discord attachment voice-message flag", exc_info=True)

    content_type = (attachment.content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(attachment.filename or "").suffix.lower()
    return content_type in VOICE_MESSAGE_MIME_TYPES or extension in VOICE_MESSAGE_EXTENSIONS


def _voice_attachment_mime_type(path: Path) -> str:
    return VOICE_MESSAGE_FILE_MIME_BY_EXTENSION.get(path.suffix.lower(), "audio/ogg")


def _omlx_asr_headers() -> dict[str, str]:
    headers = {"Connection": "close"}
    if DISCORD_VOICE_MESSAGE_ASR_API_KEY:
        headers["Authorization"] = f"Bearer {DISCORD_VOICE_MESSAGE_ASR_API_KEY}"
    return headers


def _json_or_text(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


def _sleep_before_asr_retry(attempt: int, attempts: int, error: BaseException) -> None:
    delay = DISCORD_VOICE_MESSAGE_ASR_RETRY_BACKOFF_SECONDS * attempt
    LOGGER.warning(
        "oMLX voice-message ASR failed on attempt %d/%d: %s; retrying in %.2fs",
        attempt,
        attempts,
        error,
        delay,
    )
    if delay > 0:
        time.sleep(delay)


def transcribe_voice_message_path(audio_path: Path) -> str:
    if not DISCORD_VOICE_MESSAGE_ASR_ENABLED:
        raise RuntimeError("Discord voice-message transcription is disabled.")
    if not DISCORD_VOICE_MESSAGE_ASR_BASE_URL:
        raise RuntimeError("DISCORD_VOICE_MESSAGE_ASR_BASE_URL is not configured.")
    if not DISCORD_VOICE_MESSAGE_ASR_MODEL:
        raise RuntimeError("DISCORD_VOICE_MESSAGE_ASR_MODEL is not configured.")

    audio_size = audio_path.stat().st_size
    if audio_size > DISCORD_VOICE_MESSAGE_MAX_BYTES:
        raise RuntimeError(
            f"Voice message is too large to transcribe ({format_bytes(audio_size)} > "
            f"{format_bytes(DISCORD_VOICE_MESSAGE_MAX_BYTES)})."
        )

    url = f"{DISCORD_VOICE_MESSAGE_ASR_BASE_URL}/audio/transcriptions"
    form: dict[str, str] = {
        "model": DISCORD_VOICE_MESSAGE_ASR_MODEL,
        "response_format": "json",
        "temperature": "0",
    }
    if DISCORD_VOICE_MESSAGE_ASR_LANGUAGE:
        form["language"] = DISCORD_VOICE_MESSAGE_ASR_LANGUAGE

    attempts = max(1, DISCORD_VOICE_MESSAGE_ASR_RETRIES + 1)
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    last_error: BaseException | None = None

    with audio_path.open("rb") as file_obj:
        for attempt in range(1, attempts + 1):
            try:
                file_obj.seek(0)
            except Exception:
                LOGGER.debug("Failed to rewind voice message before ASR attempt", exc_info=True)
            try:
                response = requests.post(
                    url,
                    headers=_omlx_asr_headers(),
                    data=form,
                    files={"file": (audio_path.name, file_obj, _voice_attachment_mime_type(audio_path))},
                    timeout=DISCORD_VOICE_MESSAGE_ASR_TIMEOUT_SECONDS,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                _sleep_before_asr_retry(attempt, attempts, exc)
                continue

            if response.status_code in retry_statuses and attempt < attempts:
                last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.close()
                _sleep_before_asr_retry(attempt, attempts, last_error)
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(f"oMLX voice-message ASR failed: {_json_or_text(response)}") from exc

            payload = response.json()
            text = payload.get("text", "") if isinstance(payload, dict) else ""
            return " ".join(str(text).split()).strip()

    raise RuntimeError(f"oMLX voice-message ASR failed after {attempts} attempt(s): {last_error}") from last_error


def transcribe_voice_message_paths(paths: list[Path]) -> list[str]:
    transcripts: list[str] = []
    for path in paths:
        transcript = transcribe_voice_message_path(path)
        if transcript:
            transcripts.append(transcript)
        else:
            LOGGER.warning("oMLX ASR returned an empty transcript for %s", path)
    return transcripts


def build_voice_transcript_block(transcripts: list[str]) -> str:
    cleaned = [" ".join(transcript.split()).strip() for transcript in transcripts if transcript.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"Voice message transcript:\n{cleaned[0]}"

    lines = ["Voice message transcripts:"]
    lines.extend(f"{index}. {transcript}" for index, transcript in enumerate(cleaned, start=1))
    return "\n".join(lines)


def format_voice_transcription_status(transcripts: list[str]) -> str:
    cleaned = [" ".join(transcript.split()).strip() for transcript in transcripts if transcript.strip()]
    if not cleaned:
        quote_text = "*(empty transcript)*"
    elif len(cleaned) == 1:
        quote_text = cleaned[0]
    else:
        quote_text = "\n".join(f"{index}. {transcript}" for index, transcript in enumerate(cleaned, start=1))
    return f"User said:\n{format_discord_block_quote(quote_text)}"


def detect_image_mime_type(path: Path, data: bytes) -> str | None:
    extension = path.suffix.lower()
    if extension in IMAGE_MIME_BY_EXTENSION:
        return IMAGE_MIME_BY_EXTENSION[extension]

    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 6 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 2 and data[:2] == b"BM":
        return "image/bmp"
    if len(data) >= 4 and data[:4] in {b"II*\x00", b"MM\x00*"}:
        return "image/tiff"

    return None


def build_rpc_image_attachments(saved_paths: list[Path]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for path in saved_paths:
        try:
            data = path.read_bytes()
        except Exception:
            LOGGER.exception("Failed to read image attachment candidate %s", path)
            continue

        mime_type = detect_image_mime_type(path, data)
        if mime_type is None:
            continue
        if not data:
            LOGGER.warning("Skipping empty image attachment: %s", path)
            continue
        if len(data) > DISCORD_IMAGE_ATTACHMENT_MAX_BYTES:
            LOGGER.warning(
                "Skipping image attachment larger than DISCORD_IMAGE_ATTACHMENT_MAX_BYTES (%s bytes): %s",
                len(data),
                path,
            )
            continue

        images.append(
            {
                "type": "image",
                "data": base64.b64encode(data).decode("ascii"),
                "mimeType": mime_type,
            }
        )

    return images


def build_attachment_reference_block(saved_paths: list[Path]) -> str:
    if not saved_paths:
        return ""

    lines = ["Attachment paths saved locally:"]
    lines.extend(f"- {path}" for path in saved_paths)
    return "\n".join(lines)


def compose_user_message(
    user_text: str,
    saved_paths: list[Path],
    *,
    voice_transcripts: list[str] | None = None,
) -> str:
    blocks: list[str] = []
    message_text = user_text.strip()
    voice_transcript_block = build_voice_transcript_block(voice_transcripts or [])
    attachment_block = build_attachment_reference_block(saved_paths)

    if message_text:
        blocks.append(message_text)
    if voice_transcript_block:
        blocks.append(voice_transcript_block)
    if attachment_block:
        blocks.append(attachment_block)

    return "\n\n".join(blocks)
