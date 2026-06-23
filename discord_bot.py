from __future__ import annotations

import asyncio
import base64
import importlib.util
import datetime as dt
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import discord
import requests
import config

PROJECT_ROOT = config.PROJECT_ROOT
DOTENV_PATH = config.DOTENV_PATH
config.load_project_env(DOTENV_PATH)
LOGGER = config.get_logger("jarvis.discord_bot")
_DISCORD_BOT_INSTANCE_LOCK: object | None = None


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _falsy_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).lower() in {"0", "false", "no", "off"}


def _parse_pid(raw_pid: str) -> int | None:
    try:
        pid = int(raw_pid.strip())
    except ValueError:
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    return pid


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_command(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return " ".join(completed.stdout.split())


def _pid_looks_like_discord_bot(pid: int) -> bool:
    command = _pid_command(pid)
    if not command:
        return False
    return "discord_bot.py" in command


def _terminate_existing_discord_bot(pid: int) -> bool:
    if not _pid_looks_like_discord_bot(pid):
        LOGGER.error(
            "Discord bot lock is held by pid %s, but its command does not look like this JARVIS discord_bot.py; "
            "refusing to terminate it automatically. Command: %s",
            pid,
            _pid_command(pid) or "unknown",
        )
        return False

    LOGGER.warning("Replacing existing JARVIS Discord bot process pid %s before starting this instance.", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        LOGGER.error("Cannot terminate existing Discord bot pid %s: permission denied.", pid)
        return False
    except OSError as exc:
        LOGGER.error("Cannot terminate existing Discord bot pid %s: %s", pid, exc)
        return False

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.2)

    LOGGER.warning("Existing Discord bot pid %s did not exit after SIGTERM; sending SIGKILL.", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        LOGGER.error("Cannot SIGKILL existing Discord bot pid %s: permission denied.", pid)
        return False
    except OSError as exc:
        LOGGER.error("Cannot SIGKILL existing Discord bot pid %s: %s", pid, exc)
        return False

    # If the process briefly remains visible as a zombie, its advisory lock should
    # still be released. Let the caller decide success by reacquiring the lock.
    time.sleep(0.5)
    return True


def _write_instance_lock_pid(lock_file: object) -> None:
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()


def _acquire_single_instance_lock() -> bool:
    """Run only one local bot process, replacing an older local instance by default.

    Discord voice state is especially sensitive to duplicate clients: a second
    local process can invalidate the first process's voice websocket/session and
    produce 4006 reconnect loops. The lock is advisory and automatically
    released by the OS if the process exits.
    """
    if _truthy_env("DISCORD_BOT_DISABLE_INSTANCE_LOCK"):
        return True
    if os.name != "posix":
        return True
    try:
        import fcntl
    except Exception:
        LOGGER.warning("fcntl is unavailable; Discord bot single-instance lock is disabled.")
        return True

    lock_path = PROJECT_ROOT / ".pi" / "discord_bot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.seek(0)
        existing_pid_text = lock_file.read().strip()
        existing_pid = _parse_pid(existing_pid_text)
        detail = f" by pid {existing_pid_text}" if existing_pid_text else ""
        if _falsy_env("DISCORD_BOT_REPLACE_EXISTING", "1"):
            LOGGER.error(
                "Another local JARVIS Discord bot instance is already running%s; refusing to start a duplicate. "
                "Remove DISCORD_BOT_REPLACE_EXISTING=0 to restore automatic replacement.",
                detail,
            )
            lock_file.close()
            return False
        if existing_pid is None:
            LOGGER.error(
                "Another local JARVIS Discord bot instance is already running%s, but the lock file does not contain "
                "a usable pid; refusing to guess which process to terminate.",
                detail,
            )
            lock_file.close()
            return False
        if not _terminate_existing_discord_bot(existing_pid):
            lock_file.close()
            return False

        deadline = time.monotonic() + 8.0
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    LOGGER.error("Timed out waiting for Discord bot lock held%s to be released.", detail)
                    lock_file.close()
                    return False
                time.sleep(0.2)

    _write_instance_lock_pid(lock_file)
    global _DISCORD_BOT_INSTANCE_LOCK
    _DISCORD_BOT_INSTANCE_LOCK = lock_file
    return True


import llm


def _load_project_script(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


WORKOUT_TRACKER_SCRIPT_PATH = PROJECT_ROOT / "projects" / "workout-tracker" / "discord_workout_tracker.py"
if WORKOUT_TRACKER_SCRIPT_PATH.exists():
    discord_workout_tracker = _load_project_script("discord_workout_tracker", WORKOUT_TRACKER_SCRIPT_PATH)
else:
    LOGGER.warning("Workout tracker project script not found at %s; Discord workout UI is disabled.", WORKOUT_TRACKER_SCRIPT_PATH)
    discord_workout_tracker = None

VOICE_CONTROL_SCRIPT_PATH = PROJECT_ROOT / "projects" / "operation-jarvis" / "voice" / "discord_voice.py"

if VOICE_CONTROL_SCRIPT_PATH.exists():
    try:
        # Load Operation JARVIS live voice into the main bot so the same Discord
        # token can handle text channels, voice-channel text chat, and #jarvis voice.
        discord_voice = _load_project_script("operation_jarvis_voice_discord_voice", VOICE_CONTROL_SCRIPT_PATH)
    except Exception:
        LOGGER.exception("Operation JARVIS voice script failed to load from %s; Discord voice is disabled.", VOICE_CONTROL_SCRIPT_PATH)
        discord_voice = None
else:
    LOGGER.warning("Operation JARVIS voice script not found at %s; Discord voice is disabled.", VOICE_CONTROL_SCRIPT_PATH)
    discord_voice = None

MAX_DISCORD_MESSAGE_LENGTH = 2000
ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()
SLASH_COMMAND_GROUP = "jarvis"
SLASH_NEW_COMMAND = f"/{SLASH_COMMAND_GROUP} new"
SLASH_DELETE_COMMAND = f"/{SLASH_COMMAND_GROUP} delete"
SLASH_CANCEL_COMMAND = f"/{SLASH_COMMAND_GROUP} cancel"
SLASH_CONFIG_COMMAND = f"/{SLASH_COMMAND_GROUP} model"
SLASH_RESTART_COMMAND = f"/{SLASH_COMMAND_GROUP} restart"
SLASH_COMPACT_COMMAND = f"/{SLASH_COMMAND_GROUP} compact"
SLASH_THINKING_COMMAND = f"/{SLASH_COMMAND_GROUP} thinking"
THINKING_LEVEL_OPTIONS = ("off", "minimal", "low", "medium", "high", "xhigh")
DISCORD_TARGET_CHANNEL_NAMES = tuple(
    dict.fromkeys(
        channel_name.strip().lower()
        for channel_name in os.getenv(
            "DISCORD_TARGET_CHANNEL_NAMES",
            os.getenv("DISCORD_TARGET_CHANNEL_NAME", "jarvis-chat1,jarvis-chat2,jarvis-chat3"),
        ).split(",")
        if channel_name.strip()
    )
)
DISCORD_VOICE_CHANNEL_NAME = (
    str(getattr(discord_voice, "DISCORD_VOICE_CHANNEL_NAME", ""))
    if discord_voice is not None
    else os.getenv("DISCORD_VOICE_CHANNEL_NAME", "jarvis")
).strip().lower()
QWEN35_9B_PROVIDER = "omlx"
QWEN35_9B_MODEL_ID = "Qwen3.5-9B-4bit"
QWEN35_9B_COMPAT_MODEL_RE = re.compile(r"(?:^|/)Qwen3\.5-9B(-oQ[456]-mtp|-4bit)$", re.IGNORECASE)
DISCORD_TEXT_QWEN35_9B_MODEL = config.get_str_env(
    "DISCORD_TEXT_QWEN35_9B_MODEL",
    f"{QWEN35_9B_PROVIDER}/{QWEN35_9B_MODEL_ID}",
)
DISCORD_VOICE_QWEN35_9B_MODEL = config.get_str_env(
    "DISCORD_VOICE_QWEN35_9B_MODEL",
    f"{QWEN35_9B_PROVIDER}/{QWEN35_9B_MODEL_ID}",
)
DISCORD_EXTRA_PI_MODEL_OPTIONS = tuple(
    dict.fromkeys(
        model
        for model in (
            f"{QWEN35_9B_PROVIDER}/{QWEN35_9B_MODEL_ID}",
            DISCORD_TEXT_QWEN35_9B_MODEL,
            DISCORD_VOICE_QWEN35_9B_MODEL,
        )
        if model
    )
)
DEFAULT_DISCORD_VOICE_PI_MODEL = "omlx-64/Qwen3.6-35B-A3B-6bit"
DISCORD_VOICE_PI_MODEL = config.get_str_env("DISCORD_VOICE_PI_MODEL", DEFAULT_DISCORD_VOICE_PI_MODEL)


def _split_env_csv(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))


DISCORD_AUTO_THREAD_MEMBER_IDS = _split_env_csv(os.getenv("DISCORD_AUTO_THREAD_MEMBER_IDS", ""))
DISCORD_AUTO_THREAD_MEMBER_QUERY = os.getenv("DISCORD_AUTO_THREAD_MEMBER_QUERY", "dyl pickle").strip()
DISCORD_API_BASE = "https://discord.com/api/v10"


DISCORD_STREAM_EDIT_INTERVAL_SECONDS = config.get_int_env(
    "DISCORD_STREAM_EDIT_INTERVAL_SECONDS",
    2,
    minimum=1,
)
DISCORD_TOOL_HEARTBEAT_SECONDS = config.get_int_env(
    "DISCORD_TOOL_HEARTBEAT_SECONDS",
    45,
    minimum=10,
)
DISCORD_VOICE_SPEAK_PI_THINKING = config.get_str_env("DISCORD_VOICE_SPEAK_PI_THINKING", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_SPEAK_TOOL_CALLS = config.get_str_env("DISCORD_VOICE_SPEAK_TOOL_CALLS", "0").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DISCORD_VOICE_PI_IDLE_NEW_SESSION_SECONDS = config.get_float_env(
    "DISCORD_VOICE_PI_IDLE_NEW_SESSION_SECONDS",
    15 * 60.0,
    minimum=0.0,
)
PI_APPEND_SYSTEM_PROMPT_PATH = PROJECT_ROOT / ".pi" / "APPEND_SYSTEM.md"
DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT_PATH = (
    PROJECT_ROOT / "projects" / "operation-jarvis" / "voice" / "APPEND_SYSTEM.md"
)


def _load_markdown_prompt(path: Path, *, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        LOGGER.warning("%s prompt file not found at %s", description, path)
    except Exception:
        LOGGER.exception("Failed to read %s prompt from %s", description, path)
    return ""


def _load_pi_append_system_prompt() -> str:
    return _load_markdown_prompt(PI_APPEND_SYSTEM_PROMPT_PATH, description="Pi append-system")


def _load_voice_pi_append_system_prompt() -> str:
    return _load_markdown_prompt(
        DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT_PATH,
        description="Discord voice Pi append-system",
    )


DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT = "\n\n".join(
    part
    for part in (
        _load_voice_pi_append_system_prompt(),
        _load_pi_append_system_prompt(),
    )
    if part
)
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
# Discord views allow at most 25 components. Reserve one slot for the quota button.
MAX_MODEL_BUTTONS = 24
CONFIG_MENU_TIMEOUT_SECONDS = 600
QUOTAS_SCRIPT_PATH = PROJECT_ROOT / "projects" / "quotas" / "quotas.py"
QUOTAS_LATEST_PATH = PROJECT_ROOT / "projects" / "quotas" / "data" / "latest.json"
QUOTA_CHECK_TIMEOUT_SECONDS = config.get_int_env(
    "DISCORD_QUOTA_CHECK_TIMEOUT_SECONDS",
    90,
    minimum=10,
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


def _channel_lock_key(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, discord.VoiceChannel):
        return f"voice:{channel.id}"
    return str(channel.id)


def _is_voice_channel_context(channel_key: str, channel: object | None = None) -> bool:
    return isinstance(channel, discord.VoiceChannel) or channel_key.startswith("voice:")


def _is_qwen35_9b_model(model: str) -> bool:
    """Detect Qwen3.5 9B session selections for consistent routing.

    Matches the current secondary 16GB oMLX model (Qwen3.5-9B-4bit) and
    older Qwen3.5 9B IDs (oQ4/oQ5/oQ6-mtp) so all are coerced to the
    configured replacement model for this channel.
    """
    return bool(QWEN35_9B_COMPAT_MODEL_RE.search(model.strip()))


def _preferred_qwen35_9b_model(channel_key: str, channel: object | None = None) -> str:
    if _is_voice_channel_context(channel_key, channel):
        return DISCORD_VOICE_QWEN35_9B_MODEL
    return DISCORD_TEXT_QWEN35_9B_MODEL


def _coerce_model_for_channel(model: str, channel_key: str, channel: object | None = None) -> str:
    selected_model = model.strip()
    if _is_qwen35_9b_model(selected_model):
        return _preferred_qwen35_9b_model(channel_key, channel)
    return selected_model


def _default_model_for_channel(channel_key: str, channel: object | None = None) -> str:
    if _is_voice_channel_context(channel_key, channel) and DISCORD_VOICE_PI_MODEL:
        return _coerce_model_for_channel(DISCORD_VOICE_PI_MODEL, channel_key, channel)
    return _coerce_model_for_channel(llm.DISCORD_PI_MODEL, channel_key, channel)


def _enabled_command_channel_names() -> tuple[str, ...]:
    names = list(DISCORD_TARGET_CHANNEL_NAMES)
    if DISCORD_VOICE_CHANNEL_NAME and DISCORD_VOICE_CHANNEL_NAME not in names:
        names.append(DISCORD_VOICE_CHANNEL_NAME)
    return tuple(names)


def _is_enabled_jarvis_command_channel(channel: object) -> bool:
    if isinstance(channel, discord.TextChannel):
        return channel.name.lower() in DISCORD_TARGET_CHANNEL_NAMES
    if isinstance(channel, discord.VoiceChannel):
        return bool(DISCORD_VOICE_CHANNEL_NAME) and channel.name.lower() == DISCORD_VOICE_CHANNEL_NAME
    return False


def _truncate_discord_label(text: str, *, max_length: int = 80) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}…"


def _truncate_discord_value(text: str, *, max_length: int = 1000) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}…"


def _format_steering_marker(text: str) -> str:
    steering_text = _truncate_discord_value(" ".join(text.split()), max_length=1500)
    if not steering_text:
        return "🕹️ Steering applied."
    return f"🕹️ Steering applied:\n{_format_discord_block_quote(steering_text)}"


def _format_voice_steering_marker(text: str) -> str:
    steering_text = _truncate_discord_value(" ".join(text.split()), max_length=1500)
    if not steering_text:
        return "Steering said."
    return f"Steering said:\n{_format_discord_block_quote(steering_text)}"


def _model_display_name(model: str) -> str:
    return model.rsplit("/", 1)[-1].strip() or model.strip() or "model"


def _model_button_label(index: int, model: str) -> str:
    return _truncate_discord_label(f"{index}. {_model_display_name(model)}")


def _format_bytes(byte_count: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    value = float(byte_count)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{byte_count} {unit}"
        value /= 1024
    return f"{byte_count} B"


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:g}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:g}m"
    return f"{minutes / 60:g}h"


def _format_quota_number(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _format_quota_percent(value: object) -> str:
    formatted = _format_quota_number(value)
    return f"{formatted}%" if formatted != "?" else "?"


def _format_compaction_result(data: dict[str, object]) -> str:
    tokens_before = data.get("tokensBefore")
    token_text = ""
    if isinstance(tokens_before, (int, float)):
        token_text = f" Context before compaction was about {int(tokens_before):,} tokens."
    return f"Compacted the current JARVIS session.{token_text}"


def _format_delete_session_result(data: dict[str, object]) -> str:
    if data.get("busy"):
        return (
            "I'm still working on the current JARVIS session. "
            f"Send `{SLASH_CANCEL_COMMAND}` to abort it before deleting."
        )

    reason = str(data.get("reason") or "")
    if reason in {"no_session", "no_live_session"}:
        return "There is no active JARVIS Pi session to delete in this channel."

    method = str(data.get("method") or "")
    if data.get("deleted"):
        action = "moved it to trash" if method == "trash" else "deleted its session file"
        return f"Deleted the current JARVIS Pi session and {action}. Future messages will start fresh."

    if reason in {"missing", "missing_session_file"} or method == "missing":
        return "Reset the current JARVIS Pi session. No saved session file existed yet."

    return "Reset the current JARVIS Pi session. Future messages will start fresh."


def _session_stats_context_tokens(stats: dict[str, object]) -> int | float | None:
    context_usage = stats.get("contextUsage")
    if not isinstance(context_usage, dict):
        return None
    tokens = context_usage.get("tokens")
    return tokens if isinstance(tokens, (int, float)) else None


def _parse_quota_timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def _discord_timestamp(value: object) -> str:
    timestamp = _parse_quota_timestamp(value)
    if timestamp is None:
        return "unknown"
    return f"<t:{timestamp}:R>"


def _load_latest_quota_report() -> dict[str, object] | None:
    try:
        with QUOTAS_LATEST_PATH.open("r", encoding="utf-8") as quota_file:
            payload = json.load(quota_file)
    except FileNotFoundError:
        return None
    except Exception:
        LOGGER.exception("Failed to read latest quota report from %s", QUOTAS_LATEST_PATH)
        return None
    return payload if isinstance(payload, dict) else None


def _format_quota_summary(report: dict[str, object] | None, *, error: str | None = None) -> str:
    if error:
        return _truncate_discord_value(f"Check failed: {error}")
    if not report:
        return "No saved quota check yet. Click **Check quota** to refresh it."

    checked_at = _discord_timestamp(report.get("checked_at"))
    providers = report.get("providers") if isinstance(report.get("providers"), dict) else {}
    codex = providers.get("openai-codex") if isinstance(providers, dict) else None
    copilot = providers.get("github-copilot") if isinstance(providers, dict) else None
    lines = [f"Last checked: {checked_at}"]

    if isinstance(codex, dict):
        usage = codex.get("usage") if isinstance(codex.get("usage"), dict) else {}
        primary = usage.get("primary") if isinstance(usage, dict) and isinstance(usage.get("primary"), dict) else {}
        secondary = usage.get("secondary") if isinstance(usage, dict) and isinstance(usage.get("secondary"), dict) else {}
        credits = usage.get("credits") if isinstance(usage, dict) and isinstance(usage.get("credits"), dict) else {}
        codex_bits = [str(usage.get("plan_type") or "unknown plan") if isinstance(usage, dict) else "unknown plan"]
        if primary:
            codex_bits.append(f"5h {_format_quota_percent(primary.get('used_percent'))} used")
        if secondary:
            codex_bits.append(f"weekly {_format_quota_percent(secondary.get('used_percent'))} used")
        if credits and credits.get("balance") is not None:
            codex_bits.append(f"credits {_format_quota_number(credits.get('balance'))}")
        lines.append(f"Codex: {'; '.join(codex_bits)}")
    else:
        lines.append("Codex: no saved data")

    if isinstance(copilot, dict):
        usage = copilot.get("usage") if isinstance(copilot.get("usage"), dict) else {}
        ai_credits = usage.get("ai_credits") if isinstance(usage, dict) and isinstance(usage.get("ai_credits"), dict) else {}
        premium = (
            usage.get("legacy_premium_interactions")
            if isinstance(usage, dict) and isinstance(usage.get("legacy_premium_interactions"), dict)
            else usage.get("premium_interactions") if isinstance(usage, dict) and isinstance(usage.get("premium_interactions"), dict) else {}
        )
        plan = "unknown plan"
        if isinstance(usage, dict):
            allowance = usage.get("plan_allowance") if isinstance(usage.get("plan_allowance"), dict) else {}
            plan = allowance.get("label") or usage.get("plan") or usage.get("access_type_sku") or "unknown plan"
        if ai_credits:
            used = ai_credits.get("used")
            entitlement = ai_credits.get("entitlement")
            remaining = ai_credits.get("remaining")
            if used is not None and entitlement is not None:
                lines.append(
                    "Copilot: "
                    f"{plan}; AI credits {_format_quota_number(used)}/"
                    f"{_format_quota_number(entitlement)} used, "
                    f"{_format_quota_number(remaining)} left"
                )
            elif used is not None:
                lines.append(f"Copilot: {plan}; AI credits {_format_quota_number(used)} used")
            elif ai_credits.get("entitlement_per_user") is not None:
                lines.append(
                    "Copilot: "
                    f"{plan}; AI credits {_format_quota_number(ai_credits.get('entitlement_per_user'))}/user/mo pooled"
                )
            else:
                lines.append(f"Copilot: {plan}; AI credits unavailable")
        elif isinstance(usage, dict) and usage.get("billing_model") == "ai_credits":
            lines.append(f"Copilot: {plan}; token billing active, AI credits unavailable")
        elif premium:
            lines.append(
                "Copilot: "
                f"{plan}; premium {_format_quota_number(premium.get('used'))}/"
                f"{_format_quota_number(premium.get('entitlement'))} used, "
                f"{_format_quota_number(premium.get('remaining'))} left"
            )
        else:
            lines.append(f"Copilot: {plan}")
    else:
        lines.append("Copilot: no saved data")

    return _truncate_discord_value("\n".join(lines))


def _sanitize_attachment_filename(filename: str) -> str:
    safe_name = Path(filename).name.strip()
    return safe_name or "attachment"


async def _save_message_attachments(
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
        safe_filename = _sanitize_attachment_filename(attachment.filename)
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


def _delete_temporary_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            LOGGER.exception("Failed to delete temporary file %s", path)


def _is_voice_message_attachment(attachment: discord.Attachment) -> bool:
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


def _transcribe_voice_message_path(audio_path: Path) -> str:
    if not DISCORD_VOICE_MESSAGE_ASR_ENABLED:
        raise RuntimeError("Discord voice-message transcription is disabled.")
    if not DISCORD_VOICE_MESSAGE_ASR_BASE_URL:
        raise RuntimeError("DISCORD_VOICE_MESSAGE_ASR_BASE_URL is not configured.")
    if not DISCORD_VOICE_MESSAGE_ASR_MODEL:
        raise RuntimeError("DISCORD_VOICE_MESSAGE_ASR_MODEL is not configured.")

    audio_size = audio_path.stat().st_size
    if audio_size > DISCORD_VOICE_MESSAGE_MAX_BYTES:
        raise RuntimeError(
            f"Voice message is too large to transcribe ({_format_bytes(audio_size)} > "
            f"{_format_bytes(DISCORD_VOICE_MESSAGE_MAX_BYTES)})."
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


def _transcribe_voice_message_paths(paths: list[Path]) -> list[str]:
    transcripts: list[str] = []
    for path in paths:
        transcript = _transcribe_voice_message_path(path)
        if transcript:
            transcripts.append(transcript)
        else:
            LOGGER.warning("oMLX ASR returned an empty transcript for %s", path)
    return transcripts


def _build_voice_transcript_block(transcripts: list[str]) -> str:
    cleaned = [" ".join(transcript.split()).strip() for transcript in transcripts if transcript.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"Voice message transcript:\n{cleaned[0]}"

    lines = ["Voice message transcripts:"]
    lines.extend(f"{index}. {transcript}" for index, transcript in enumerate(cleaned, start=1))
    return "\n".join(lines)


def _format_discord_block_quote(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "> *(empty transcript)*"
    return "\n".join(f"> {line}" if line else ">" for line in normalized.split("\n"))


def _format_voice_transcription_status(transcripts: list[str]) -> str:
    cleaned = [" ".join(transcript.split()).strip() for transcript in transcripts if transcript.strip()]
    if not cleaned:
        quote_text = "*(empty transcript)*"
    elif len(cleaned) == 1:
        quote_text = cleaned[0]
    else:
        quote_text = "\n".join(f"{index}. {transcript}" for index, transcript in enumerate(cleaned, start=1))
    return f"User said:\n{_format_discord_block_quote(quote_text)}"


def _detect_image_mime_type(path: Path, data: bytes) -> str | None:
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


def _build_rpc_image_attachments(saved_paths: list[Path]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for path in saved_paths:
        try:
            data = path.read_bytes()
        except Exception:
            LOGGER.exception("Failed to read image attachment candidate %s", path)
            continue

        mime_type = _detect_image_mime_type(path, data)
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


def _build_attachment_reference_block(saved_paths: list[Path]) -> str:
    if not saved_paths:
        return ""

    lines = ["Attachment paths saved locally:"]
    lines.extend(f"- {path}" for path in saved_paths)
    return "\n".join(lines)


def _compose_user_message(
    user_text: str,
    saved_paths: list[Path],
    *,
    voice_transcripts: list[str] | None = None,
) -> str:
    blocks: list[str] = []
    message_text = user_text.strip()
    voice_transcript_block = _build_voice_transcript_block(voice_transcripts or [])
    attachment_block = _build_attachment_reference_block(saved_paths)

    if message_text:
        blocks.append(message_text)
    if voice_transcript_block:
        blocks.append(voice_transcript_block)
    if attachment_block:
        blocks.append(attachment_block)

    return "\n\n".join(blocks)


def _starts_inside_block_quote(text: str, offset: int) -> bool:
    if offset <= 0 or offset >= len(text) or text[offset] == "\n":
        return False

    line_start = text.rfind("\n", 0, offset) + 1
    return offset > line_start and text.startswith(">", line_start)


def _chunk_text(text: str) -> list[str]:
    if not text:
        return ["I did not receive response text from the model."]

    chunks: list[str] = []
    offset = 0
    while offset < len(text):
        prefix = "> " if _starts_inside_block_quote(text, offset) else ""
        available_length = MAX_DISCORD_MESSAGE_LENGTH - len(prefix)
        chunks.append(f"{prefix}{text[offset : offset + available_length]}")
        offset += available_length

    return chunks or ["I did not receive response text from the model."]


def _clean_tool_parameter(value: object, *, max_length: int = 120) -> str:
    if value is None:
        return ""

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) > max_length:
        return f"{text[: max_length - 1].rstrip()}…"
    return text


def _tool_key(tool_name: str) -> str:
    return (tool_name.strip() or "tool").rsplit(".", 1)[-1]


def _is_discord_send_file_tool(tool_name: str) -> bool:
    return _tool_key(tool_name) == "discord_send_file"


DISCORD_BOT_TOOL_KEYS = {
    # Always-on Pi tools.
    "bash",
    "code_search",
    "edit",
    "fetch_content",
    "find",
    "get_search_content",
    "grep",
    "load_tools",
    "ls",
    "memory",
    "minecraft_jarvis",
    "read",
    "ssh",
    "web_search",
    "write",
    # Lazy/optional Pi tools surfaced through load_tools.
    "discord_cron",
    "discord_ping",
    "google_workspace",
    "jarvis",
    "session_search",
    "smart_plug",
    "youtube_api",
    # Discord-specific helper tools.
    "discord_send_file",
    "memory_forget",
    "memory_lessons",
    "memory_remember",
    "memory_search",
    "memory_stats",
    "parallel",
}

TOOL_EMOJIS = {
    "bash": "🖥️",
    "code_search": "💻",
    "discord_cron": "🗓️",
    "discord_ping": "📣",
    "discord_send_file": "📎",
    "edit": "✏️",
    "fetch_content": "📄",
    "find": "🗂️",
    "get_search_content": "📥",
    "google_workspace": "🏢",
    "grep": "🧶",
    "jarvis": "🤖",
    "load_tools": "🧰",
    "ls": "📁",
    "memory": "🧠",
    "memory_forget": "🗑️",
    "memory_lessons": "📚",
    "memory_remember": "💾",
    "memory_search": "🔍",
    "memory_stats": "📊",
    "minecraft_jarvis": "⛏️",
    "parallel": "🔀",
    "read": "📖",
    "session_search": "🧭",
    "smart_plug": "🔌",
    "ssh": "🔗",
    "web_search": "🔎",
    "write": "📝",
    "youtube_api": "📺",
    "fallback": "🛠️",
}


_FALLBACK_TOOL_EMOJI_PALETTE = [
    "🧪",
    "🧬",
    "🔧",
    "⚙️",
    "🧲",
    "🛰️",
    "📡",
    "🔭",
    "🕯️",
    "🧯",
    "🚦",
    "🧷",
    "🪛",
    "🪚",
    "🧮",
    "🧿",
]
_DYNAMIC_TOOL_EMOJIS: dict[str, str] = {}
_KEYCAP_DIGIT_EMOJIS = {
    "0": "0️⃣",
    "1": "1️⃣",
    "2": "2️⃣",
    "3": "3️⃣",
    "4": "4️⃣",
    "5": "5️⃣",
    "6": "6️⃣",
    "7": "7️⃣",
    "8": "8️⃣",
    "9": "9️⃣",
}


def _keycap_number_emoji(number: int) -> str:
    return "".join(_KEYCAP_DIGIT_EMOJIS[digit] for digit in str(max(0, number)))


def _validate_tool_emojis() -> None:
    missing = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_EMOJIS))
    if missing:
        raise RuntimeError(f"Missing tool emoji mapping(s): {', '.join(missing)}")

    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for tool_key, emoji in TOOL_EMOJIS.items():
        other_tool_key = seen.get(emoji)
        if other_tool_key:
            duplicates.append(f"{other_tool_key}/{tool_key} share {emoji}")
        else:
            seen[emoji] = tool_key
    if duplicates:
        raise RuntimeError(f"Duplicate tool emoji mapping(s): {', '.join(duplicates)}")


def _tool_emoji(tool_key: str) -> str:
    key = _tool_key(tool_key)
    emoji = TOOL_EMOJIS.get(key)
    if emoji:
        return emoji

    dynamic_emoji = _DYNAMIC_TOOL_EMOJIS.get(key)
    if dynamic_emoji:
        return dynamic_emoji

    used = set(TOOL_EMOJIS.values()).union(_DYNAMIC_TOOL_EMOJIS.values())
    for candidate in _FALLBACK_TOOL_EMOJI_PALETTE:
        if candidate not in used:
            _DYNAMIC_TOOL_EMOJIS[key] = candidate
            return candidate

    # If new tool surfaces exceed the named palette, keep the visible emoji unique
    # by appending keycap digits rather than reusing the bare fallback emoji.
    index = len(_DYNAMIC_TOOL_EMOJIS) + 1
    while True:
        candidate = f"{TOOL_EMOJIS['fallback']}{_keycap_number_emoji(index)}"
        if candidate not in used:
            _DYNAMIC_TOOL_EMOJIS[key] = candidate
            return candidate
        index += 1


_validate_tool_emojis()



TOOL_VOICE_START_NARRATIONS = {
    "bash": "I’ll run that in the terminal, sir.",
    "code_search": "I’ll search the code references, sir.",
    "discord_cron": "I’ll adjust the scheduled jobs, sir.",
    "discord_ping": "I’ll send the Discord ping, sir.",
    "discord_send_file": "I’ll send the file to Discord, sir.",
    "edit": "I’ll make the edit, sir.",
    "fetch_content": "I’ll fetch the source content, sir.",
    "find": "I’ll find matching files, sir.",
    "get_search_content": "I’ll open the retrieved content, sir.",
    "google_workspace": "I’ll work in Google Workspace, sir.",
    "grep": "I’ll search the files, sir.",
    "jarvis": "I’ll consult the JARVIS subsystem, sir.",
    "load_tools": "I’ll bring the required systems online, sir.",
    "ls": "I’ll list the directory, sir.",
    "memory": "I’ll check my memory, sir.",
    "memory_forget": "I’ll remove that from memory, sir.",
    "memory_lessons": "I’ll review the saved lessons, sir.",
    "memory_remember": "I’ll store that in memory, sir.",
    "memory_search": "I’ll search my memory, sir.",
    "memory_stats": "I’ll check the memory status, sir.",
    "minecraft_jarvis": "I’ll contact the Minecraft JARVIS bot, sir.",
    "parallel": "I’ll run those in parallel, sir.",
    "ssh": "I’ll connect over SSH, sir.",
    "read": "I’ll inspect the file, sir.",
    "session_search": "I’ll search the previous sessions, sir.",
    "smart_plug": "I’ll adjust the smart plug, sir.",
    "web_search": "I’ll search the web, sir.",
    "write": "I’ll write the file, sir.",
    "youtube_api": "I’ll check YouTube, sir.",
}

TOOL_VOICE_FAILURE_NARRATIONS = {
    "bash": "The terminal command failed, sir.",
    "code_search": "The code search failed, sir.",
    "discord_cron": "I couldn’t update the scheduled jobs, sir.",
    "discord_ping": "I couldn’t send the Discord ping, sir.",
    "discord_send_file": "I couldn’t send the file, sir.",
    "edit": "The edit failed, sir.",
    "fetch_content": "I couldn’t fetch that content, sir.",
    "find": "The file lookup failed, sir.",
    "get_search_content": "I couldn’t retrieve that content, sir.",
    "google_workspace": "The Google Workspace action failed, sir.",
    "grep": "The file search failed, sir.",
    "jarvis": "The JARVIS subsystem call failed, sir.",
    "load_tools": "I couldn’t load those systems, sir.",
    "ls": "The directory listing failed, sir.",
    "memory": "The memory action failed, sir.",
    "memory_forget": "I couldn’t remove that memory, sir.",
    "memory_lessons": "I couldn’t review the saved lessons, sir.",
    "memory_remember": "I couldn’t store that memory, sir.",
    "memory_search": "The memory search failed, sir.",
    "memory_stats": "I couldn’t check memory status, sir.",
    "minecraft_jarvis": "The Minecraft JARVIS call failed, sir.",
    "parallel": "The parallel tools failed, sir.",
    "ssh": "The SSH command failed, sir.",
    "read": "I couldn’t read the file, sir.",
    "session_search": "The session search failed, sir.",
    "smart_plug": "The smart plug action failed, sir.",
    "web_search": "The web search failed, sir.",
    "write": "I couldn’t write the file, sir.",
    "youtube_api": "The YouTube lookup failed, sir.",
}


def _validate_tool_voice_narrations() -> None:
    missing_start = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_VOICE_START_NARRATIONS))
    missing_failure = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_VOICE_FAILURE_NARRATIONS))
    problems = []
    if missing_start:
        problems.append(f"missing start narration(s): {', '.join(missing_start)}")
    if missing_failure:
        problems.append(f"missing failure narration(s): {', '.join(missing_failure)}")
    if problems:
        raise RuntimeError("Invalid tool voice narration mapping: " + "; ".join(problems))


def _voice_tool_key(tool_name: object) -> str:
    raw_name = str(tool_name or "tool")
    key = _tool_key(raw_name)
    if raw_name in {"multi_tool_use.parallel", "parallel"} or key == "parallel":
        return "parallel"
    return key


def _tool_voice_narration(tool_name: object, *, failed: bool = False) -> str:
    key = _voice_tool_key(tool_name)
    narrations = TOOL_VOICE_FAILURE_NARRATIONS if failed else TOOL_VOICE_START_NARRATIONS
    narration = narrations.get(key)
    if narration:
        return narration
    spoken_name = re.sub(r"[_-]+", " ", key).strip() or "tool"
    if failed:
        return f"The {spoken_name} action failed, sir."
    return f"I’ll use {spoken_name}, sir."


_validate_tool_voice_narrations()


def _first_tool_arg(tool_args: dict[str, object], *keys: str, max_length: int = 120) -> str:
    for key in keys:
        value = _clean_tool_parameter(tool_args.get(key), max_length=max_length)
        if value:
            return value
    return ""


def _coordinate_label(tool_args: dict[str, object]) -> str:
    x = _first_tool_arg(tool_args, "x", "clientX", "screenX", max_length=24)
    y = _first_tool_arg(tool_args, "y", "clientY", "screenY", max_length=24)
    if x and y:
        return f"{x}, {y}"
    return ""


def _list_arg_label(value: object, *, max_length: int = 120) -> str:
    if isinstance(value, (list, tuple)):
        return _clean_tool_parameter(", ".join(str(item) for item in value if str(item).strip()), max_length=max_length)
    return _clean_tool_parameter(value, max_length=max_length)


def _tool_action_label(tool_name: str, args: object) -> str:
    tool_args = args if isinstance(args, dict) else {}
    name = tool_name.strip() or "tool"
    tool_key = _tool_key(name)

    if tool_key == "web_search":
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("queries", ""))
        emoji = _tool_emoji("web_search")
        return f"{emoji} Searched the web for \"{query}\"" if query else f"{emoji} Searched the web"

    if tool_key == "code_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("code_search")
        return f"{emoji} Searched code references for \"{query}\"" if query else f"{emoji} Searched code references"

    if tool_key == "fetch_content":
        url = _clean_tool_parameter(tool_args.get("url") or tool_args.get("urls", ""))
        emoji = _tool_emoji("fetch_content")
        return f"{emoji} Fetched source content from \"{url}\"" if url else f"{emoji} Fetched source content"

    if tool_key == "get_search_content":
        response_id = _clean_tool_parameter(tool_args.get("responseId"))
        emoji = _tool_emoji("get_search_content")
        return f"{emoji} Opened fetched result \"{response_id}\"" if response_id else f"{emoji} Opened fetched result"

    if tool_key == "youtube_api":
        action = _first_tool_arg(tool_args, "action", "resource", max_length=40)
        query = _first_tool_arg(tool_args, "query", "id", max_length=120)
        emoji = _tool_emoji("youtube_api")
        if action and query:
            return f"{emoji} Checked YouTube {action} for \"{query}\""
        return f"{emoji} Checked YouTube {action}" if action else f"{emoji} Checked YouTube"

    if tool_key == "discord_cron":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        target = _first_tool_arg(tool_args, "name", "id", "channel", "query", max_length=100)
        emoji = _tool_emoji("discord_cron")
        if action and target:
            return f"{emoji} Updated scheduled job {action}: {target}"
        return f"{emoji} Updated scheduled jobs: {action}" if action else f"{emoji} Updated scheduled jobs"

    if tool_key == "discord_ping":
        message = _first_tool_arg(tool_args, "message", max_length=140)
        emoji = _tool_emoji("discord_ping")
        return f"{emoji} Sent Discord ping: \"{message}\"" if message else f"{emoji} Sent Discord ping"

    if tool_key == "session_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("session_search")
        return f"{emoji} Searched prior sessions for \"{query}\"" if query else f"{emoji} Searched prior sessions"

    if tool_key == "memory":
        action = _clean_tool_parameter(tool_args.get("action"), max_length=40)
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("text") or tool_args.get("id"), max_length=140)
        emoji = _tool_emoji("memory")
        if action == "search":
            return f"{emoji} Searched memory for \"{query}\"" if query else f"{emoji} Searched memory"
        if action == "remember":
            return f"{emoji} Saved memory: \"{query}\"" if query else f"{emoji} Saved memory"
        if action == "forget":
            return f"{emoji} Removed memory {query}" if query else f"{emoji} Removed memory"
        if action == "update":
            return f"{emoji} Updated memory {query}" if query else f"{emoji} Updated memory"
        if action == "list":
            return f"{emoji} Listed memory"
        if action == "status":
            return f"{emoji} Checked memory status"
        return f"{emoji} Managed memory: {action}" if action else f"{emoji} Managed memory"

    if tool_key == "memory_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("memory_search")
        return f"{emoji} Searched memory for \"{query}\"" if query else f"{emoji} Searched memory"

    if tool_key == "memory_remember":
        detail = _first_tool_arg(tool_args, "key", "type", "text", max_length=140)
        emoji = _tool_emoji("memory_remember")
        return f"{emoji} Saved memory: {detail}" if detail else f"{emoji} Saved memory"

    if tool_key == "memory_forget":
        key = _clean_tool_parameter(tool_args.get("key") or tool_args.get("id"))
        emoji = _tool_emoji("memory_forget")
        return f"{emoji} Removed memory {key}" if key else f"{emoji} Removed memory"

    if tool_key == "memory_lessons":
        category = _clean_tool_parameter(tool_args.get("category"))
        emoji = _tool_emoji("memory_lessons")
        return f"{emoji} Reviewed saved lessons for {category}" if category else f"{emoji} Reviewed saved lessons"

    if tool_key == "memory_stats":
        return f"{_tool_emoji('memory_stats')} Checked memory statistics"

    if tool_key == "discord_send_file":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("discord_send_file")
        return f"{emoji} Attached file \"{path}\"" if path else f"{emoji} Attached file to Discord"

    if tool_key == "bash":
        command = _clean_tool_parameter(tool_args.get("command"))
        emoji = _tool_emoji("bash")
        return f"{emoji} Executed terminal command: \"{command}\"" if command else f"{emoji} Executed terminal command"

    if tool_key == "read":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("read")
        return f"{emoji} Inspected file \"{path}\"" if path else f"{emoji} Inspected file"

    if tool_key == "grep":
        pattern = _clean_tool_parameter(tool_args.get("pattern"))
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("grep")
        target = f" in {path}" if path else ""
        return f"{emoji} Searched files for \"{pattern}\"{target}" if pattern else f"{emoji} Searched files"

    if tool_key == "find":
        pattern = _clean_tool_parameter(tool_args.get("pattern"))
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("find")
        target = f" in {path}" if path else ""
        return f"{emoji} Found files matching \"{pattern}\"{target}" if pattern else f"{emoji} Found matching files"

    if tool_key == "ls":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("ls")
        return f"{emoji} Listed directory \"{path}\"" if path else f"{emoji} Listed directory"

    if tool_key == "write":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("write")
        return f"{emoji} Wrote file \"{path}\"" if path else f"{emoji} Wrote file"

    if tool_key == "edit":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("edit")
        return f"{emoji} Patched file \"{path}\"" if path else f"{emoji} Patched file"

    if tool_key == "load_tools":
        groups = _list_arg_label(tool_args.get("groups"), max_length=120)
        emoji = _tool_emoji("load_tools")
        return f"{emoji} Loaded tool group{'s' if ',' in groups else ''}: {groups}" if groups else f"{emoji} Loaded optional tools"

    if tool_key == "jarvis":
        action = _first_tool_arg(tool_args, "action", "workflow", "prompt", max_length=120)
        emoji = _tool_emoji("jarvis")
        return f"{emoji} Queried JARVIS subsystem: {action}" if action else f"{emoji} Queried JARVIS subsystem"

    if tool_key == "smart_plug":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        plug = _first_tool_arg(tool_args, "plug", "name", "alias", max_length=100)
        emoji = _tool_emoji("smart_plug")
        if action and plug:
            return f"{emoji} Updated smart plug {plug}: {action}"
        return f"{emoji} Updated smart plug: {action}" if action else f"{emoji} Updated smart plug"

    if tool_key == "google_workspace":
        action = _first_tool_arg(tool_args, "action", "resource", "query", max_length=120)
        emoji = _tool_emoji("google_workspace")
        return f"{emoji} Updated Google Workspace: {action}" if action else f"{emoji} Updated Google Workspace"

    if name in {"multi_tool_use.parallel", "parallel"} or tool_key == "parallel":
        return f"{_tool_emoji('parallel')} Executed multiple tools in parallel"

    readable_name = re.sub(r"[_-]+", " ", tool_key).strip() or name
    return f"{_tool_emoji(tool_key)} Completed {readable_name} action"


def _tool_failure_label(tool_name: str, args: object) -> str:
    tool_args = args if isinstance(args, dict) else {}
    name = tool_name.strip() or "tool"
    tool_key = _tool_key(name)
    emoji = _tool_emoji(tool_key)

    if tool_key == "bash":
        command = _clean_tool_parameter(tool_args.get("command"))
        return f"❌ {emoji} Terminal command failed: \"{command}\"" if command else f"❌ {emoji} Terminal command failed"
    if tool_key == "read":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not inspect file \"{path}\"" if path else f"❌ {emoji} Could not inspect file"
    if tool_key == "write":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not write file \"{path}\"" if path else f"❌ {emoji} Could not write file"
    if tool_key == "edit":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not patch file \"{path}\"" if path else f"❌ {emoji} Could not patch file"
    if tool_key in {"web_search", "code_search", "session_search", "memory_search", "grep", "find"}:
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("pattern"))
        readable = {
            "web_search": "web search",
            "code_search": "code reference search",
            "session_search": "prior session search",
            "memory_search": "memory search",
            "grep": "file search",
            "find": "file lookup",
        }[tool_key]
        return f"❌ {emoji} Failed {readable} for \"{query}\"" if query else f"❌ {emoji} Failed {readable}"
    if tool_key == "ls":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not list directory \"{path}\"" if path else f"❌ {emoji} Could not list directory"
    if tool_key == "fetch_content":
        url = _clean_tool_parameter(tool_args.get("url") or tool_args.get("urls", ""))
        return f"❌ {emoji} Could not fetch source content from \"{url}\"" if url else f"❌ {emoji} Could not fetch source content"
    if tool_key == "get_search_content":
        response_id = _clean_tool_parameter(tool_args.get("responseId"))
        return f"❌ {emoji} Could not open fetched result \"{response_id}\"" if response_id else f"❌ {emoji} Could not open fetched result"
    if tool_key == "youtube_api":
        query = _first_tool_arg(tool_args, "query", "id", max_length=120)
        return f"❌ {emoji} YouTube lookup failed for \"{query}\"" if query else f"❌ {emoji} YouTube lookup failed"
    if tool_key == "discord_ping":
        message = _first_tool_arg(tool_args, "message", max_length=140)
        return f"❌ {emoji} Could not send Discord ping: \"{message}\"" if message else f"❌ {emoji} Could not send Discord ping"
    if tool_key == "discord_send_file":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not attach file \"{path}\"" if path else f"❌ {emoji} Could not attach file"
    if tool_key == "load_tools":
        groups = _list_arg_label(tool_args.get("groups"), max_length=120)
        return f"❌ {emoji} Could not load tool group: {groups}" if groups else f"❌ {emoji} Could not load optional tools"
    if tool_key == "memory":
        action = _clean_tool_parameter(tool_args.get("action"), max_length=40)
        return f"❌ {emoji} Memory action failed: {action}" if action else f"❌ {emoji} Memory action failed"
    if tool_key == "smart_plug":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        plug = _first_tool_arg(tool_args, "plug", "name", "alias", max_length=100)
        detail = f" {plug}: {action}" if action and plug else f": {action}" if action else ""
        return f"❌ {emoji} Smart plug action failed{detail}"
    if tool_key == "parallel" or name in {"multi_tool_use.parallel", "parallel"}:
        return f"❌ {_tool_emoji('parallel')} Parallel tool execution failed"

    readable_name = re.sub(r"[_-]+", " ", _voice_tool_key(name)).strip() or name
    return f"❌ {emoji} {readable_name.capitalize()} action failed"


class _StreamingResponse:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        channel: discord.abc.Messageable,
        update_interval_seconds: float,
    ) -> None:
        self._loop = loop
        self._channel = channel
        self._update_interval_seconds = update_interval_seconds
        self._buffer = ""
        self._lock = threading.Lock()
        self._pending_task: asyncio.Task[None] | None = None
        self._last_edit_at = 0.0
        self._closed = False
        self._update_lock = asyncio.Lock()
        self._live_messages: list[discord.Message] = []
        self._sent_chunks: list[str] = []
        self._current_tool_name = ""
        self._current_tool_args = ""
        self._shown_tool_call_ids: set[str] = set()
        self._tool_args_by_call_id: dict[str, object] = {}
        self._tool_label_spans_by_call_id: dict[str, tuple[int, int]] = {}
        self._active_tool_call_id = ""
        self._active_tool_label = ""
        self._active_tool_started_at = 0.0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._in_thinking = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._needs_text_separator = False
        self._pause_updates = False
        self._file_tool_call_ids: set[str] = set()
        self._file_tool_labels: dict[str, str] = {}
        self._file_split_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_steering_markers: list[str] = []
        self._seen_turn_start = False
        self._has_output = False

    @property
    def has_output(self) -> bool:
        return self._has_output

    def append(self, delta: str) -> None:
        if not delta:
            return
        with self._lock:
            if self._closed:
                return
            self._buffer += delta
        self._has_output = True
        self._schedule_update()

    def current_text(self) -> str:
        with self._lock:
            return self._buffer

    def queue_marker(self, marker: str) -> str | None:
        marker = (marker or "").strip()
        if not marker:
            return None
        with self._lock:
            if self._closed:
                return None
            self._pending_steering_markers.append(marker)
        return marker

    def queue_steering_marker(self, text: str) -> str | None:
        return self.queue_marker(_format_steering_marker(text))

    def discard_steering_marker(self, marker: str | None) -> None:
        if not marker:
            return
        with self._lock:
            try:
                self._pending_steering_markers.remove(marker)
            except ValueError:
                pass

    async def finalize(self, text: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._buffer = text
        await self._update_message()

    async def wait_pending(self) -> None:
        """Wait for any pending update tasks to complete."""
        if self._pending_task and not self._pending_task.done():
            await self._pending_task

    async def close(self) -> None:
        self._closed = True
        self._stop_tool_heartbeat()
        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        heartbeat_task = self._heartbeat_task
        if heartbeat_task is not None and not heartbeat_task.done():
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        self._pending_task = None
        self._heartbeat_task = None

    def on_rpc_event(self, event: dict) -> None:
        """Process a Pi RPC event and stream it to Discord."""
        event_type = event.get("type", "")

        if event_type == "turn_start":
            self._handle_turn_start()
        elif event_type == "message_update":
            self._handle_message_update(event)
        elif event_type == "tool_execution_start":
            self._handle_tool_start(event)
        elif event_type == "tool_execution_update":
            self._handle_tool_update(event)
        elif event_type == "tool_execution_end":
            self._handle_tool_end(event)
        elif event_type == "compaction_start":
            self.append("Compacting context...\n")
        elif event_type == "compaction_end":
            self.append("Context compacted.\n")

    def _handle_turn_start(self) -> None:
        with self._lock:
            if not self._seen_turn_start:
                self._seen_turn_start = True
                return
            marker = self._pending_steering_markers.pop(0) if self._pending_steering_markers else ""
        if marker:
            self._request_steering_boundary(marker)

    def _request_steering_boundary(self, marker: str) -> None:
        if self._loop.is_closed():
            return

        with self._lock:
            if self._closed:
                return
            content_before_marker = self._buffer
            self._buffer = ""
            self._pause_updates = True
            self._has_output = True
            self._needs_text_separator = False
            self._thinking_has_content = False
            self._thinking_line_needs_prefix = True
            self._in_thinking = False

        def _schedule() -> None:
            if self._closed:
                return
            asyncio.create_task(self._split_for_steering_marker(marker, content_before_marker))

        self._loop.call_soon_threadsafe(_schedule)

    async def _split_for_steering_marker(self, marker: str, content_before_marker: str) -> None:
        if self._closed:
            return

        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        self._pending_task = None

        if content_before_marker:
            async with self._update_lock:
                await _sync_live_messages(
                    self._channel,
                    self._live_messages,
                    self._sent_chunks,
                    _chunk_text(content_before_marker),
                )
            self._last_edit_at = time.monotonic()

        await self._channel.send(marker)

        self._live_messages = []
        self._sent_chunks = []
        self._tool_label_spans_by_call_id.clear()
        self._needs_text_separator = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._in_thinking = False
        self._pause_updates = False
        self._schedule_update()

    def _format_thinking_delta(self, delta: str) -> str:
        """Format thinking text as a Discord block quote without dangling quote markers."""
        formatted_parts: list[str] = []
        normalized_delta = delta.replace("\r\n", "\n").replace("\r", "\n")

        for char in normalized_delta:
            if char == "\n":
                if self._thinking_has_content:
                    formatted_parts.append("\n")
                    self._thinking_line_needs_prefix = True
                continue

            if self._thinking_line_needs_prefix:
                formatted_parts.append("> ")
                self._thinking_line_needs_prefix = False

            self._thinking_has_content = True
            formatted_parts.append(char)

        return "".join(formatted_parts)

    def _handle_message_update(self, event: dict) -> None:
        """Handle text/thinking deltas from message_update events."""
        msg_event = event.get("assistantMessageEvent", {})
        event_type = msg_event.get("type", "")
        
        if event_type == "thinking_start":
            with self._lock:
                if self._buffer and not self._buffer.endswith(("\n", "\r")):
                    self._buffer += "\n"
            self._in_thinking = True
            self._thinking_has_content = False
            self._thinking_line_needs_prefix = True
        elif event_type == "thinking_delta":
            delta = msg_event.get("delta", "")
            if delta and self._in_thinking:
                formatted_delta = self._format_thinking_delta(delta)
                if formatted_delta:
                    self.append(formatted_delta)
        elif event_type == "thinking_end":
            self._in_thinking = False
            self._thinking_line_needs_prefix = True
            with self._lock:
                if self._thinking_has_content:
                    self._buffer = self._buffer.rstrip("\r\n")
                    self._needs_text_separator = bool(self._buffer)
            self._schedule_update()
        elif event_type == "text_start":
            pass
        elif event_type == "text_delta":
            delta = msg_event.get("delta", "")
            if delta:
                if self._needs_text_separator:
                    delta = "\n" + delta.lstrip("\r\n")
                    self._needs_text_separator = False
                self.append(delta)
        elif event_type == "text_end":
            pass
        elif event_type == "toolcall_start":
            self._current_tool_name = msg_event.get("toolCall", {}).get("name", "unknown")
        elif event_type == "toolcall_delta":
            pass
        elif event_type == "toolcall_end":
            pass

    def _handle_tool_start(self, event: dict) -> None:
        """Handle tool execution start."""
        tool_name = event.get("toolName", "unknown")
        tool_call_id = str(event.get("toolCallId", ""))
        self._current_tool_name = tool_name

        if tool_call_id and tool_call_id in self._shown_tool_call_ids:
            return
        if tool_call_id:
            self._shown_tool_call_ids.add(tool_call_id)

        args = event.get("args", {})
        if tool_call_id:
            self._tool_args_by_call_id[tool_call_id] = args

        label = _tool_action_label(str(tool_name), args)
        if _is_discord_send_file_tool(str(tool_name)):
            self._request_file_stream_split(tool_call_id, label)
            return

        self._append_tool_label(tool_call_id, label)
        self._start_tool_heartbeat(tool_call_id, label)

    def _handle_tool_update(self, event: dict) -> None:
        """Handle tool execution progress without dumping raw tool output."""
        pass

    def _append_tool_label(self, tool_call_id: str, label: str) -> None:
        line = f"\n{label}\n"
        with self._lock:
            if self._closed:
                return
            start = len(self._buffer) + 1
            self._buffer += line
            if tool_call_id:
                self._tool_label_spans_by_call_id[tool_call_id] = (start, start + len(label))
        self._has_output = True
        self._schedule_update()

    def _shift_tool_label_spans(self, from_index: int, delta: int, *, skip_tool_call_id: str = "") -> None:
        if delta == 0:
            return
        for call_id, (start, end) in list(self._tool_label_spans_by_call_id.items()):
            if skip_tool_call_id and call_id == skip_tool_call_id:
                continue
            if start >= from_index:
                self._tool_label_spans_by_call_id[call_id] = (start + delta, end + delta)

    def _prefix_failed_tool_label(self, tool_call_id: str, label: str, failed_label: str | None = None) -> bool:
        failed_label = failed_label or (label if label.startswith("❌ ") else f"❌ {label}")
        with self._lock:
            if self._closed:
                return False

            buffer = self._buffer
            start = -1
            end = -1
            span = self._tool_label_spans_by_call_id.get(tool_call_id) if tool_call_id else None
            if span is not None:
                span_start, span_end = span
                if 0 <= span_start <= span_end <= len(buffer) and buffer[span_start:span_end] == label:
                    start, end = span_start, span_end

            if start < 0:
                needle = f"\n{label}\n"
                idx = buffer.rfind(needle)
                if idx < 0:
                    return False
                start = idx + 1
                end = start + len(label)

            self._buffer = buffer[:start] + failed_label + buffer[end:]
            delta = len(failed_label) - (end - start)
            if tool_call_id:
                self._tool_label_spans_by_call_id[tool_call_id] = (start, start + len(failed_label))
            self._shift_tool_label_spans(end, delta, skip_tool_call_id=tool_call_id)

        self._has_output = True
        self._schedule_update()
        return True

    def _handle_tool_end(self, event: dict) -> None:
        """Handle tool execution completion."""
        tool_name = str(event.get("toolName", ""))
        is_error = event.get("isError", False)

        tool_call_id = str(event.get("toolCallId", ""))
        args = event.get("args", self._tool_args_by_call_id.get(tool_call_id, {}))

        label = _tool_action_label(tool_name, args)
        if _is_discord_send_file_tool(tool_name):
            self._request_file_stream_resume(tool_call_id, label, is_error)
            if tool_call_id:
                self._tool_args_by_call_id.pop(tool_call_id, None)
            self._stop_tool_heartbeat(tool_call_id)
            self._current_tool_name = ""
            self._current_tool_args = ""
            return

        if is_error:
            failed_label = _tool_failure_label(tool_name, args)
            if not self._prefix_failed_tool_label(tool_call_id, label, failed_label):
                self.append(f"\n{failed_label}\n")
        if tool_call_id:
            self._tool_args_by_call_id.pop(tool_call_id, None)
            self._tool_label_spans_by_call_id.pop(tool_call_id, None)
        self._stop_tool_heartbeat(tool_call_id)
        self._current_tool_name = ""
        self._current_tool_args = ""

    def _start_tool_heartbeat(self, tool_call_id: str, label: str) -> None:
        self._active_tool_call_id = tool_call_id
        self._active_tool_label = label
        self._active_tool_started_at = time.monotonic()

        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            if self._heartbeat_task is not None and not self._heartbeat_task.done():
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(
                self._run_tool_heartbeat(tool_call_id, label, self._active_tool_started_at)
            )

        self._loop.call_soon_threadsafe(_schedule)

    def _stop_tool_heartbeat(self, tool_call_id: str = "") -> None:
        if tool_call_id and self._active_tool_call_id and tool_call_id != self._active_tool_call_id:
            return
        self._active_tool_call_id = ""
        self._active_tool_label = ""
        self._active_tool_started_at = 0.0

        def _cancel() -> None:
            heartbeat_task = self._heartbeat_task
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()

        try:
            if asyncio.get_running_loop() is self._loop:
                _cancel()
            elif not self._loop.is_closed():
                self._loop.call_soon_threadsafe(_cancel)
        except RuntimeError:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(_cancel)

    def _request_file_stream_split(self, tool_call_id: str, label: str) -> None:
        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            task = asyncio.create_task(self._split_for_file_send(tool_call_id, label))
            task_key = tool_call_id or "_no_tool_call_id"
            self._file_split_tasks[task_key] = task

        self._loop.call_soon_threadsafe(_schedule)

    async def _split_for_file_send(self, tool_call_id: str, label: str) -> None:
        if self._closed:
            return
        if tool_call_id:
            if tool_call_id in self._file_tool_call_ids:
                return
            self._file_tool_call_ids.add(tool_call_id)
            self._file_tool_labels[tool_call_id] = label

        self._pause_updates = True
        self._has_output = True

        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        self._pending_task = None

        with self._lock:
            content = self._buffer
            self._buffer = ""

        if content:
            async with self._update_lock:
                await _sync_live_messages(
                    self._channel,
                    self._live_messages,
                    self._sent_chunks,
                    _chunk_text(content),
                )
            self._last_edit_at = time.monotonic()

        self._live_messages = []
        self._sent_chunks = []
        self._tool_label_spans_by_call_id.clear()
        self._needs_text_separator = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._in_thinking = False

    def _request_file_stream_resume(self, tool_call_id: str, label: str, is_error: bool) -> None:
        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            asyncio.create_task(self._resume_after_file_send(tool_call_id, label, is_error))

        self._loop.call_soon_threadsafe(_schedule)

    async def _resume_after_file_send(self, tool_call_id: str, label: str, is_error: bool) -> None:
        if self._closed:
            return

        task_key = tool_call_id or "_no_tool_call_id"
        split_task = self._file_split_tasks.pop(task_key, None)
        if split_task is not None and not split_task.done():
            await asyncio.gather(split_task, return_exceptions=True)

        if tool_call_id and tool_call_id in self._file_tool_call_ids:
            self._file_tool_call_ids.discard(tool_call_id)
            label = self._file_tool_labels.pop(tool_call_id, label)

        self._pause_updates = False

        message = f"❌ {label}" if is_error else label
        if message:
            prefix = "\n" if self._buffer else ""
            self.append(f"{prefix}{message}\n")
        else:
            self._schedule_update()

    async def _run_tool_heartbeat(self, tool_call_id: str, label: str, started_at: float) -> None:
        heartbeat_count = 0
        try:
            while not self._closed:
                await asyncio.sleep(DISCORD_TOOL_HEARTBEAT_SECONDS)
                if self._closed or self._active_tool_call_id != tool_call_id:
                    return
                heartbeat_count += 1
                elapsed_seconds = max(1, int(time.monotonic() - started_at))
                elapsed_minutes = max(1, round(elapsed_seconds / 60))
                self.append(
                    f"\n⏳ Still working: {label} ({elapsed_minutes} min elapsed). "
                    f"Send another message to steer, or `{SLASH_CANCEL_COMMAND}` to abort.\n"
                )
                if heartbeat_count >= 20:
                    return
        except asyncio.CancelledError:
            return

    def _schedule_update(self) -> None:
        if self._loop.is_closed() or self._pause_updates:
            return

        def _schedule() -> None:
            if self._closed:
                return
            now = time.monotonic()
            elapsed = now - self._last_edit_at
            delay = max(0.0, self._update_interval_seconds - elapsed)
            if self._pending_task is None or self._pending_task.done():
                self._pending_task = asyncio.create_task(self._run_update_after(delay))

        self._loop.call_soon_threadsafe(_schedule)

    async def _run_update_after(self, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        if self._closed:
            return
        await self._update_message()

    async def _update_message(self) -> None:
        if self._closed or self._pause_updates:
            return
        with self._lock:
            if self._pause_updates:
                return
            content = self._buffer
        async with self._update_lock:
            await _sync_live_messages(
                self._channel,
                self._live_messages,
                self._sent_chunks,
                _chunk_text(content),
            )
        self._last_edit_at = time.monotonic()


async def _sync_live_messages(
    channel: discord.TextChannel,
    live_messages: list[discord.Message],
    sent_chunks: list[str],
    chunks: list[str],
) -> None:
    for idx, chunk in enumerate(chunks):
        if idx >= len(live_messages):
            live_messages.append(await channel.send(chunk))
            sent_chunks.append(chunk)
            continue

        if sent_chunks[idx] != chunk:
            await live_messages[idx].edit(content=chunk)
            sent_chunks[idx] = chunk

    while len(live_messages) > len(chunks):
        stale_message = live_messages.pop()
        sent_chunks.pop()
        try:
            await stale_message.delete()
        except Exception:
            LOGGER.debug("Failed to delete stale Discord response message %s", stale_message.id, exc_info=True)


class _ModelSelectButton(discord.ui.Button):
    def __init__(self, *, index: int, model: str, current_model: str, row: int | None = None) -> None:
        is_current = model == current_model
        super().__init__(
            label=_model_button_label(index, model),
            style=discord.ButtonStyle.success if is_current else discord.ButtonStyle.secondary,
            disabled=is_current,
            row=(index - 1) // 5 if row is None else row,
        )
        self.model = model

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, _ConfigView):
            await interaction.response.send_message("This config panel is no longer available.", ephemeral=True)
            return
        await view.select_model(interaction, self.model)



class _QuotaCheckButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Check quota", style=discord.ButtonStyle.primary, emoji="🔄", row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, _ConfigView):
            await interaction.response.send_message("This config panel is no longer available.", ephemeral=True)
            return
        await view.check_quota(interaction)


class _ConfigView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: "JarvisDiscordBot",
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> None:
        super().__init__(timeout=CONFIG_MENU_TIMEOUT_SECONDS)
        self.bot = bot
        self.channel_key = channel_key
        self.add_item(_QuotaCheckButton())
        models, _, current_model = bot._model_options_for_channel(channel_key, channel)
        for index, model in enumerate(models, start=1):
            # Reserve component slot 0 for the quota button. This packs four model
            # buttons on row 0, then five per row through row 4.
            self.add_item(
                _ModelSelectButton(index=index, model=model, current_model=current_model, row=index // 5)
            )

    async def check_quota(self, interaction: discord.Interaction) -> None:
        await self.bot._handle_quota_check(interaction, self.channel_key)

    async def select_model(self, interaction: discord.Interaction, model: str) -> None:
        await self.bot._handle_model_selection(interaction, self.channel_key, model)




class JarvisDiscordBot:
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        self.client = discord.Client(intents=intents)
        self.tree = discord.app_commands.CommandTree(self.client)
        self._slash_command_guild: discord.Object | None = (
            discord.Object(id=int(DISCORD_GUILD_ID)) if DISCORD_GUILD_ID.isdigit() else None
        )
        self._slash_commands_synced = False
        self._channel_locks: dict[str, asyncio.Lock] = {}
        self._rpc_sessions: dict[str, llm.PiRpcSession] = {}
        self._active_channel_tasks: dict[str, asyncio.Task[object]] = {}
        self._active_stream_responses: dict[str, _StreamingResponse] = {}
        self._workout_tracker = (
            discord_workout_tracker.WorkoutTrackerDiscordIntegration(self.client)
            if discord_workout_tracker is not None
            else None
        )
        self._voice_manager = None
        if discord_voice is not None:
            voice_pipeline = discord_voice.OmlxVoicePipeline(response_callback=self._run_voice_pi_response)
            self._voice_manager = discord_voice.JarvisVoiceManager(
                self.client,
                pipeline=voice_pipeline,
                cancel_callback=self._cancel_voice_pi_response,
                steering_callback=self._steer_voice_pi_response,
                session_start_callback=self._start_voice_pi_session,
                session_end_callback=self._end_voice_pi_session,
            )
        self._restart_in_progress = False
        self._auto_thread_member_ids_by_guild: dict[int, tuple[str, ...]] = {}
        if self._workout_tracker is not None:
            self._workout_tracker.register_persistent_views()
        self._register_slash_commands()
        self._register_events()

    async def _discord_api_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_payload: dict[str, object] | None = None,
        expect_json: bool = True,
    ) -> object | None:
        if not DISCORD_BOT_TOKEN:
            raise RuntimeError("Missing DISCORD_BOT_TOKEN")

        def _request() -> object | None:
            resp = requests.request(
                method,
                f"{DISCORD_API_BASE}{path}",
                headers={
                    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json_payload,
                timeout=15,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Discord API {method} {path} failed: HTTP {resp.status_code}: {resp.text[:300]}")
            if not expect_json or not resp.text.strip():
                return None
            return resp.json()

        return await asyncio.to_thread(_request)

    @staticmethod
    def _thread_member_names(member_payload: dict[str, object]) -> tuple[str, ...]:
        user_payload = member_payload.get("user") if isinstance(member_payload, dict) else None
        user = user_payload if isinstance(user_payload, dict) else {}
        names = [
            member_payload.get("nick") if isinstance(member_payload, dict) else None,
            user.get("global_name"),
            user.get("username"),
        ]
        return tuple(str(name).strip() for name in names if isinstance(name, str) and name.strip())

    async def _resolve_auto_thread_member_ids(self, guild_id: int) -> tuple[str, ...]:
        cached = self._auto_thread_member_ids_by_guild.get(guild_id)
        if cached is not None:
            return cached

        resolved = list(DISCORD_AUTO_THREAD_MEMBER_IDS)
        query = DISCORD_AUTO_THREAD_MEMBER_QUERY.strip()
        if query:
            try:
                payload = await self._discord_api_request(
                    "GET",
                    f"/guilds/{guild_id}/members/search",
                    params={"query": query, "limit": 25},
                    expect_json=True,
                )
                members = payload if isinstance(payload, list) else []
                needle = query.casefold()
                exact_match_id: str | None = None
                fallback_match_id: str | None = None
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    names = self._thread_member_names(member)
                    if not names:
                        continue
                    user_payload = member.get("user")
                    user = user_payload if isinstance(user_payload, dict) else {}
                    user_id = str(user.get("id") or "").strip()
                    if not user_id:
                        continue
                    if exact_match_id is None and any(name.casefold() == needle for name in names):
                        exact_match_id = user_id
                        break
                    if fallback_match_id is None and any(needle in name.casefold() for name in names):
                        fallback_match_id = user_id
                chosen = exact_match_id or fallback_match_id
                if chosen:
                    resolved.append(chosen)
            except Exception:
                LOGGER.debug("Failed to resolve auto thread member by query '%s' in guild %s", query, guild_id, exc_info=True)

        deduped = tuple(dict.fromkeys(member_id for member_id in resolved if str(member_id).strip()))
        self._auto_thread_member_ids_by_guild[guild_id] = deduped
        return deduped

    async def _add_auto_members_to_thread(self, thread: discord.Thread) -> None:
        if thread.guild is None:
            return
        member_ids = await self._resolve_auto_thread_member_ids(thread.guild.id)
        if not member_ids:
            return

        for member_id in member_ids:
            try:
                await self._discord_api_request(
                    "PUT",
                    f"/channels/{thread.id}/thread-members/{member_id}",
                    expect_json=False,
                )
            except Exception:
                LOGGER.debug(
                    "Failed to auto-add member %s to thread %s (%s)",
                    member_id,
                    thread.id,
                    thread.name,
                    exc_info=True,
                )

    @staticmethod
    def _voice_turn_metadata(turn_context: object | None) -> dict[str, object] | None:
        metadata = getattr(turn_context, "metadata", None)
        return metadata if isinstance(metadata, dict) else None

    def _create_voice_text_stream_response(
        self,
        channel_key: str,
        turn_context: object | None,
    ) -> _StreamingResponse | None:
        status_channel = getattr(turn_context, "status_channel", None)
        if not isinstance(status_channel, discord.abc.Messageable):
            return None

        stream_response = _StreamingResponse(
            loop=self.client.loop,
            channel=status_channel,
            update_interval_seconds=DISCORD_STREAM_EDIT_INTERVAL_SECONDS,
        )
        self._active_stream_responses[channel_key] = stream_response
        metadata = self._voice_turn_metadata(turn_context)
        if metadata is not None:
            metadata["text_response_streamed"] = True
        return stream_response

    def _finish_voice_text_stream_response(
        self,
        stream_response: _StreamingResponse,
        *,
        fallback_text: str = "",
    ) -> None:
        if self.client.loop.is_closed():
            return

        async def _finish() -> None:
            try:
                final_text = stream_response.current_text()
                if not final_text and not stream_response.has_output:
                    final_text = fallback_text
                if final_text:
                    await stream_response.finalize(final_text)
                await stream_response.wait_pending()
            finally:
                await stream_response.close()

        future = asyncio.run_coroutine_threadsafe(_finish(), self.client.loop)
        try:
            future.result(timeout=max(10.0, float(DISCORD_STREAM_EDIT_INTERVAL_SECONDS) + 10.0))
        except Exception:
            LOGGER.debug("Failed to finalize Discord voice text stream", exc_info=True)

    @staticmethod
    def _voice_steering_generation(turn_context: object | None) -> int:
        provider = getattr(turn_context, "steering_generation_provider", None)
        if not callable(provider):
            return 0
        try:
            return max(0, int(provider()))
        except Exception:
            LOGGER.debug("Failed to read voice steering generation in Discord Pi response bridge", exc_info=True)
            return 0

    def _start_new_voice_rpc_session_if_idle(
        self,
        session: llm.PiRpcSession,
        channel_key: str,
        voice_channel: discord.abc.GuildChannel,
    ) -> None:
        if DISCORD_VOICE_PI_IDLE_NEW_SESSION_SECONDS <= 0:
            return
        idle_for = session.seconds_since_last_activity()
        idle_detail = f"{idle_for:.0f}s" if idle_for is not None else "unknown"
        try:
            started = session.start_new_session_if_idle(DISCORD_VOICE_PI_IDLE_NEW_SESSION_SECONDS)
        except Exception:
            LOGGER.warning(
                "Failed to start fresh voice Pi session for channel_key=%s channel=%s after %s idle; restarting Pi RPC process",
                channel_key,
                getattr(voice_channel, "name", "-"),
                idle_detail,
                exc_info=True,
            )
            session.stop()
            return
        if started:
            LOGGER.info(
                "Started fresh voice Pi session for channel_key=%s channel=%s after %s idle",
                channel_key,
                getattr(voice_channel, "name", "-"),
                idle_detail,
            )

    def _run_voice_pi_response(
        self,
        transcript: str,
        on_delta: Callable[[str], None] | None,
        turn_context: object | None,
    ) -> str:
        """Send a Discord voice transcript through a real Pi RPC session."""
        voice_channel = getattr(turn_context, "voice_channel", None)
        if not isinstance(voice_channel, discord.abc.GuildChannel):
            raise RuntimeError("Voice Pi response requires a Discord voice channel context.")

        channel_key = f"voice:{voice_channel.id}"
        prompt = transcript.strip()
        stream_response = self._create_voice_text_stream_response(channel_key, turn_context)

        text_parts: list[str] = []
        spoken_tool_call_ids: set[str] = set()
        spoken_failed_tool_call_ids: set[str] = set()
        voice_tool_names_by_call_id: dict[str, object] = {}
        initial_steering_generation = self._voice_steering_generation(turn_context)
        active_steering_generation = initial_steering_generation
        suppress_voice_until_post_steer_assistant = False
        saw_post_steer_user_message = False

        def _speak_voice_delta(delta: str) -> None:
            if delta and on_delta is not None:
                on_delta(delta)

        def _handle_voice_pi_event(event: dict[str, object]) -> None:
            nonlocal active_steering_generation, suppress_voice_until_post_steer_assistant, saw_post_steer_user_message
            if stream_response is not None:
                try:
                    stream_response.on_rpc_event(event)
                except Exception:
                    LOGGER.debug("Failed to stream Discord voice Pi event to text chat", exc_info=True)
            event_type = event.get("type")
            current_steering_generation = self._voice_steering_generation(turn_context)
            if current_steering_generation > active_steering_generation:
                active_steering_generation = current_steering_generation
                suppress_voice_until_post_steer_assistant = True
                saw_post_steer_user_message = False
                text_parts.clear()
                spoken_tool_call_ids.clear()
                spoken_failed_tool_call_ids.clear()
                voice_tool_names_by_call_id.clear()
                LOGGER.debug(
                    "Voice Pi stream suppressing pre-steer output until queued steering message is processed: generation=%s",
                    active_steering_generation,
                )

            if suppress_voice_until_post_steer_assistant and event_type in {"message_start", "message_end"}:
                message = event.get("message")
                role = message.get("role") if isinstance(message, dict) else None
                if role == "user":
                    saw_post_steer_user_message = True
                elif role == "assistant" and saw_post_steer_user_message and event_type == "message_start":
                    suppress_voice_until_post_steer_assistant = False
                    LOGGER.debug("Voice Pi stream reached post-steer assistant response; resuming spoken deltas.")

            if event_type == "tool_execution_start":
                if suppress_voice_until_post_steer_assistant or not DISCORD_VOICE_SPEAK_TOOL_CALLS:
                    return
                tool_name = event.get("toolName", "tool")
                tool_call_id = str(event.get("toolCallId") or "")
                dedupe_key = tool_call_id or f"{tool_name}:{len(spoken_tool_call_ids)}"
                if tool_call_id:
                    voice_tool_names_by_call_id[tool_call_id] = tool_name
                if dedupe_key in spoken_tool_call_ids:
                    return
                spoken_tool_call_ids.add(dedupe_key)
                _speak_voice_delta(f"{_tool_voice_narration(tool_name)} ")
                return

            if event_type == "tool_execution_end":
                tool_call_id = str(event.get("toolCallId") or "")
                tool_name = event.get("toolName") or voice_tool_names_by_call_id.get(tool_call_id) or "tool"
                if tool_call_id:
                    voice_tool_names_by_call_id.pop(tool_call_id, None)
                if suppress_voice_until_post_steer_assistant or not DISCORD_VOICE_SPEAK_TOOL_CALLS:
                    return
                if not event.get("isError", False):
                    return
                dedupe_key = tool_call_id or f"{tool_name}:{len(spoken_failed_tool_call_ids)}"
                if dedupe_key in spoken_failed_tool_call_ids:
                    return
                spoken_failed_tool_call_ids.add(dedupe_key)
                _speak_voice_delta(f"{_tool_voice_narration(tool_name, failed=True)} ")
                return

            if event_type != "message_update":
                return
            if suppress_voice_until_post_steer_assistant:
                return
            message_event = event.get("assistantMessageEvent")
            if not isinstance(message_event, dict):
                return
            message_event_type = message_event.get("type")
            delta = str(message_event.get("delta") or "")
            if not delta:
                return
            if message_event_type == "text_delta":
                text_parts.append(delta)
                _speak_voice_delta(delta)
            elif message_event_type == "thinking_delta" and DISCORD_VOICE_SPEAK_PI_THINKING:
                _speak_voice_delta(delta)

        rpc_session = self._get_rpc_session(
            channel_key,
            voice_channel,
            append_system_prompt=DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT,
        )
        self._start_new_voice_rpc_session_if_idle(rpc_session, channel_key, voice_channel)
        reply_text = ""
        try:
            rpc_session.run_prompt(prompt, on_event=_handle_voice_pi_event)
            reply_text = "".join(text_parts).strip()
            return reply_text
        finally:
            if stream_response is not None:
                self._finish_voice_text_stream_response(stream_response, fallback_text=reply_text)
                if self._active_stream_responses.get(channel_key) is stream_response:
                    self._active_stream_responses.pop(channel_key, None)

    def _cancel_voice_pi_response(self, turn_context: object | None) -> bool:
        voice_channel = getattr(turn_context, "voice_channel", None)
        if not isinstance(voice_channel, discord.abc.GuildChannel):
            return False
        return self._cancel_rpc_session(f"voice:{voice_channel.id}")

    def _steer_voice_pi_response(self, turn_context: object | None, transcript: str) -> bool:
        voice_channel = getattr(turn_context, "voice_channel", None)
        if not isinstance(voice_channel, discord.abc.GuildChannel):
            return False
        prompt = (transcript or "").strip()
        if not prompt:
            return False
        channel_key = f"voice:{voice_channel.id}"
        stream_response = self._active_stream_responses.get(channel_key)
        queued_marker = (
            stream_response.queue_marker(_format_voice_steering_marker(prompt))
            if stream_response is not None
            else None
        )
        rpc_session = self._get_rpc_session(
            channel_key,
            voice_channel,
            append_system_prompt=DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT,
        )
        try:
            steered = rpc_session.steer_prompt(prompt)
        except Exception:
            if stream_response is not None:
                stream_response.discard_steering_marker(queued_marker)
            raise
        if steered and queued_marker:
            metadata = self._voice_turn_metadata(turn_context)
            if metadata is not None:
                metadata["suppress_next_steering_status_message"] = True
        elif stream_response is not None:
            stream_response.discard_steering_marker(queued_marker)
        return steered

    def _start_voice_pi_session(self, voice_channel: discord.abc.GuildChannel) -> None:
        """Mark a fresh Pi session boundary when the bot joins a voice channel."""
        channel_key = f"voice:{voice_channel.id}"
        old_session = self._rpc_sessions.pop(channel_key, None)
        selected_model = getattr(old_session, "model", None)
        if isinstance(selected_model, str) and selected_model.strip():
            selected_model = _coerce_model_for_channel(selected_model, channel_key, voice_channel)
        else:
            selected_model = _default_model_for_channel(channel_key, voice_channel)
        selected_thinking = getattr(old_session, "thinking", None)
        if old_session is not None:
            old_session.stop()
        self._rpc_sessions[channel_key] = llm.PiRpcSession(
            discord_channel_id=channel_key,
            discord_channel_name=voice_channel.name,
            discord_guild_id=str(voice_channel.guild.id) if voice_channel.guild is not None else None,
            model=selected_model,
            thinking=selected_thinking,
            append_system_prompt=DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT,
        )
        LOGGER.info("Started fresh voice Pi session for channel_key=%s channel=%s", channel_key, voice_channel.name)

    def _end_voice_pi_session(self, voice_channel: discord.abc.GuildChannel) -> None:
        """End the Pi session when the bot leaves a voice channel."""
        channel_key = f"voice:{voice_channel.id}"
        session = self._rpc_sessions.pop(channel_key, None)
        if session is not None:
            session.stop()
        LOGGER.info("Ended voice Pi session for channel_key=%s channel=%s", channel_key, voice_channel.name)

    def _get_channel_lock(self, channel_key: str) -> asyncio.Lock:
        lock = self._channel_locks.get(channel_key)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[channel_key] = lock
        return lock

    def _get_rpc_session(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
        *,
        model: str | None = None,
        thinking: str | None = None,
        append_system_prompt: str | None = None,
    ) -> llm.PiRpcSession:
        session = self._rpc_sessions.get(channel_key)
        selected_model = model.strip() if isinstance(model, str) and model.strip() else None
        if selected_model:
            selected_model = _coerce_model_for_channel(selected_model, channel_key, channel)
        selected_thinking = thinking.strip().lower() if isinstance(thinking, str) and thinking.strip() else None
        selected_append_system_prompt = append_system_prompt.strip() if isinstance(append_system_prompt, str) else ""
        if session is None:
            session = llm.PiRpcSession(
                discord_channel_id=channel_key,
                model=selected_model or _default_model_for_channel(channel_key, channel),
                thinking=selected_thinking,
                append_system_prompt=selected_append_system_prompt,
            )
            self._rpc_sessions[channel_key] = session
        elif selected_model and session.model != selected_model:
            session.set_model(selected_model)
        else:
            channel_model = _coerce_model_for_channel(session.model, channel_key, channel)
            if channel_model != session.model:
                session.set_model(channel_model)
        if selected_thinking and getattr(session, "thinking", None) != selected_thinking:
            session.set_thinking(selected_thinking)
        if selected_append_system_prompt != getattr(session, "append_system_prompt", ""):
            session.append_system_prompt = selected_append_system_prompt
            session.stop()
        if channel is not None:
            session.set_discord_channel_context(
                discord_channel_id=str(channel.id),
                discord_channel_name=channel.name,
                discord_guild_id=str(channel.guild.id) if channel.guild is not None else None,
            )
        return session

    def _all_model_options_for_channel(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> tuple[list[str], str]:
        current_model = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        ).model
        models: list[str] = []
        for model in (*llm.DISCORD_PI_MODEL_OPTIONS, *DISCORD_EXTRA_PI_MODEL_OPTIONS, current_model):
            model = _coerce_model_for_channel(model, channel_key, channel)
            if model and model not in models:
                models.append(model)
        return models, current_model

    def _model_options_for_channel(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> tuple[list[str], int, str]:
        models, current_model = self._all_model_options_for_channel(channel_key, channel)
        total_model_count = len(models)
        return models[:MAX_MODEL_BUTTONS], total_model_count, current_model

    def _build_config_embed(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
        *,
        quota_report: dict[str, object] | None = None,
        quota_error: str | None = None,
    ) -> discord.Embed:
        all_models, current_model = self._all_model_options_for_channel(channel_key, channel)
        models = all_models[:MAX_MODEL_BUTTONS]
        total_model_count = len(all_models)
        model_options = "\n".join(f"- `{model}`" for model in all_models) or f"- `{current_model}`"
        if quota_report is None and quota_error is None:
            quota_report = _load_latest_quota_report()
        embed = discord.Embed(
            title="JARVIS configuration",
            description=(
                "Runtime settings for this Discord bot. Secrets are intentionally hidden. "
                "Use the model buttons below to switch this channel's model; in the voice channel text chat, "
                "this targets the LLM used by the voice pipeline."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Current model", value=f"`{current_model}`", inline=False)
        embed.add_field(name="Configured model options", value=f"`{model_options}`", inline=False)
        if total_model_count > len(models):
            embed.add_field(
                name="Model buttons",
                value=f"Showing the first {len(models)} of {total_model_count} configured models.",
                inline=False,
            )
        embed.add_field(name="Quota", value=_format_quota_summary(quota_report, error=quota_error), inline=False)
        embed.set_footer(
            text=(
                f"Commands: {SLASH_NEW_COMMAND}, {SLASH_DELETE_COMMAND}, "
                f"{SLASH_CANCEL_COMMAND}, {SLASH_CONFIG_COMMAND}, {SLASH_THINKING_COMMAND}, "
                f"{SLASH_RESTART_COMMAND}, {SLASH_COMPACT_COMMAND}"
            )
        )
        return embed

    def _run_quota_check(self) -> dict[str, object]:
        if not QUOTAS_SCRIPT_PATH.exists():
            raise FileNotFoundError(f"Quota checker not found: {QUOTAS_SCRIPT_PATH}")
        completed = subprocess.run(
            [sys.executable, str(QUOTAS_SCRIPT_PATH), "check", "--json", "--save"],
            cwd=str(QUOTAS_SCRIPT_PATH.parent),
            capture_output=True,
            text=True,
            timeout=QUOTA_CHECK_TIMEOUT_SECONDS,
        )
        output = completed.stdout.strip()
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            stderr = completed.stderr.strip()
            detail = stderr or output or f"quota checker exited with {completed.returncode}"
            raise RuntimeError(detail[:1000]) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Quota checker returned unexpected data.")
        if completed.returncode == 1 and payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload

    async def _handle_quota_check(self, interaction: discord.Interaction, channel_key: str) -> None:
        channel = interaction.channel if isinstance(interaction.channel, discord.abc.GuildChannel) else None
        await interaction.response.defer()
        try:
            quota_report = await asyncio.to_thread(self._run_quota_check)
            embed = self._build_config_embed(channel_key, channel, quota_report=quota_report)
            view = _ConfigView(bot=self, channel_key=channel_key, channel=channel)
            if interaction.message is not None:
                await interaction.message.edit(embed=embed, view=view)
            await interaction.followup.send("Quota refreshed.", ephemeral=True)
        except Exception as exc:
            LOGGER.exception("Failed to refresh quota from Discord config panel")
            embed = self._build_config_embed(channel_key, channel, quota_error=str(exc))
            if interaction.message is not None:
                await interaction.message.edit(embed=embed, view=_ConfigView(bot=self, channel_key=channel_key, channel=channel))
            await interaction.followup.send(f"Failed to refresh quota: {exc}", ephemeral=True)

    @staticmethod
    def _append_system_prompt_for_channel(channel: discord.abc.GuildChannel | None) -> str | None:
        return DISCORD_VOICE_PI_APPEND_SYSTEM_PROMPT if isinstance(channel, discord.VoiceChannel) else None

    def _set_rpc_session_model(
        self,
        channel_key: str,
        model: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> bool:
        model = _coerce_model_for_channel(model, channel_key, channel)
        session = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        return session.set_model(model)

    def _set_rpc_session_thinking(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None,
        level: str,
    ) -> tuple[bool, str]:
        session = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        changed = session.set_thinking(level)
        return changed, session.thinking

    async def _handle_model_selection(self, interaction: discord.Interaction, channel_key: str, model: str) -> None:
        channel = interaction.channel if isinstance(interaction.channel, discord.abc.GuildChannel) else None
        model = _coerce_model_for_channel(model, channel_key, channel)
        channel_lock = self._get_channel_lock(channel_key)
        if channel_lock.locked():
            await interaction.response.send_message(
                "I'm still working on the previous request in this channel. "
                f"Send `{SLASH_CANCEL_COMMAND}` to abort it, then pick a model.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            changed = await asyncio.to_thread(self._set_rpc_session_model, channel_key, model, channel)
        except Exception as exc:
            await interaction.followup.send(f"Failed to switch model: {exc}", ephemeral=True)
            return

        embed = self._build_config_embed(channel_key, channel)
        view = _ConfigView(bot=self, channel_key=channel_key, channel=channel)
        if interaction.message is not None:
            try:
                await interaction.message.edit(embed=embed, view=view)
            except Exception:
                LOGGER.exception("Failed to update config panel for channel %s", channel_key)

        if changed:
            target = "voice pipeline" if isinstance(channel, discord.VoiceChannel) else "channel"
            await interaction.followup.send(f"JARVIS {target} model set to `{model}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"`{model}` is already selected for this channel.", ephemeral=True)

    def _start_new_rpc_session(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        session = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        return session.new_session(on_event=on_event)

    def _get_rpc_session_stats(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> dict[str, object]:
        session = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        return session.get_session_stats()

    def _compact_rpc_session(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
        *,
        custom_instructions: str | None = None,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        session = self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        return session.compact(custom_instructions=custom_instructions, on_event=on_event)

    def _delete_rpc_session(
        self,
        channel_key: str,
        channel: discord.abc.GuildChannel | None = None,
    ) -> dict[str, object]:
        session = self._rpc_sessions.get(channel_key)
        if session is None:
            return {"deleted": False, "reason": "no_session"}

        selected_model = getattr(session, "model", None)
        if not isinstance(selected_model, str) or not selected_model.strip():
            selected_model = None
        selected_thinking = getattr(session, "thinking", None)
        if not isinstance(selected_thinking, str) or not selected_thinking.strip():
            selected_thinking = None
        selected_append_system_prompt = self._append_system_prompt_for_channel(channel)
        if selected_append_system_prompt is None:
            selected_append_system_prompt = getattr(session, "append_system_prompt", "")

        result = session.delete_current_session_file()
        if result.get("busy"):
            return result

        if self._rpc_sessions.get(channel_key) is session:
            self._rpc_sessions.pop(channel_key, None)
            self._get_rpc_session(
                channel_key,
                channel,
                model=selected_model,
                thinking=selected_thinking,
                append_system_prompt=selected_append_system_prompt,
            )
        return result

    def _cancel_rpc_session(self, channel_key: str) -> bool:
        session = self._rpc_sessions.get(channel_key)
        if session is None:
            return False
        return session.abort_active()

    def _stop_rpc_session(self, channel_key: str) -> None:
        session = self._rpc_sessions.get(channel_key)
        if session is not None:
            session.stop()

    def _has_active_channel_work(self) -> bool:
        return any(lock.locked() for lock in self._channel_locks.values()) or any(
            task is not None and not task.done() for task in self._active_channel_tasks.values()
        )

    def _stop_all_rpc_sessions(self) -> None:
        sessions = list(self._rpc_sessions.values())
        self._rpc_sessions.clear()
        for session in sessions:
            try:
                session.stop()
            except Exception:
                LOGGER.exception("Failed to stop Pi RPC session during restart")


    async def _restart_process(self, channel: discord.abc.Messageable) -> None:
        try:
            await asyncio.to_thread(self._stop_all_rpc_sessions)
            await channel.send("Restarting JARVIS now…")
            await asyncio.sleep(1)

            script_path = Path(__file__).resolve()
            os.execv(sys.executable, [sys.executable, str(script_path), *sys.argv[1:]])
        except Exception as exc:
            self._restart_in_progress = False
            LOGGER.exception("Failed to restart JARVIS process")
            try:
                await channel.send(f"Failed to restart JARVIS: {exc}")
            except Exception:
                LOGGER.debug("Failed to send restart failure message to Discord", exc_info=True)

    async def _sync_slash_commands_once(self) -> None:
        if self._slash_commands_synced:
            return
        self._slash_commands_synced = True
        try:
            if self._slash_command_guild is not None:
                await self.tree.sync(guild=self._slash_command_guild)
            else:
                await self.tree.sync()
        except Exception:
            self._slash_commands_synced = False
            LOGGER.exception("Failed to sync JARVIS slash commands")

    async def _require_slash_text_channel(self, interaction: discord.Interaction) -> discord.abc.GuildChannel | None:
        channel = interaction.channel
        if not isinstance(channel, discord.abc.GuildChannel) or not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "JARVIS slash commands can only be used in server text channels or the configured voice channel text chat.",
                ephemeral=True,
            )
            return None
        if not _is_enabled_jarvis_command_channel(channel):
            allowed_channels = ", ".join(f"#{name}" for name in _enabled_command_channel_names())
            await interaction.response.send_message(
                f"JARVIS commands are only enabled in: {allowed_channels}.",
                ephemeral=True,
            )
            return None
        return channel

    async def _handle_slash_config(self, interaction: discord.Interaction) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        await interaction.response.defer()
        channel_key = _channel_lock_key(channel)
        self._get_rpc_session(
            channel_key,
            channel,
            append_system_prompt=self._append_system_prompt_for_channel(channel),
        )
        await interaction.followup.send(
            embed=self._build_config_embed(channel_key, channel),
            view=_ConfigView(bot=self, channel_key=channel_key, channel=channel),
        )

    async def _handle_slash_thinking(self, interaction: discord.Interaction, level: str | None = None) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        channel_key = _channel_lock_key(channel)
        channel_lock = self._get_channel_lock(channel_key)
        if channel_lock.locked():
            await interaction.response.send_message(
                "I'm still working on the previous request in this channel. "
                f"Send `{SLASH_CANCEL_COMMAND}` to abort it before changing thinking level.",
                ephemeral=True,
            )
            return

        selected_level = level.strip().lower() if isinstance(level, str) and level.strip() else None
        if selected_level is None:
            current_level = self._get_rpc_session(
                channel_key,
                channel,
                append_system_prompt=self._append_system_prompt_for_channel(channel),
            ).thinking
            options = ", ".join(f"`{option}`" for option in THINKING_LEVEL_OPTIONS)
            await interaction.response.send_message(
                f"Current JARVIS thinking level is `{current_level}`. Options: {options}.",
                ephemeral=True,
            )
            return
        if selected_level not in llm.VALID_THINKING_LEVELS:
            options = ", ".join(f"`{option}`" for option in THINKING_LEVEL_OPTIONS)
            await interaction.response.send_message(
                f"Unknown thinking level `{selected_level}`. Choose one of: {options}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            changed, current_level = await asyncio.to_thread(
                self._set_rpc_session_thinking,
                channel_key,
                channel,
                selected_level,
            )
        except Exception as exc:
            LOGGER.exception("Failed to set thinking level for channel %s", channel_key)
            await interaction.followup.send(f"Failed to set thinking level: {exc}", ephemeral=True)
            return

        if changed:
            await interaction.followup.send(f"JARVIS thinking level set to `{current_level}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"JARVIS thinking level is already `{current_level}`.", ephemeral=True)

    async def _handle_slash_cancel(self, interaction: discord.Interaction) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        channel_key = _channel_lock_key(channel)
        channel_lock = self._get_channel_lock(channel_key)
        if isinstance(channel, discord.VoiceChannel):
            voice_stopped = False
            if self._voice_manager is not None:
                voice_stopped = await self._voice_manager.cancel_voice_channel(channel)
            abort_sent = await asyncio.to_thread(self._cancel_rpc_session, channel_key)
            await interaction.response.send_message(
                "Stopped the active JARVIS voice turn and sent a cancel request. The current voice Pi session will be preserved."
                if voice_stopped or abort_sent
                else "There is no running JARVIS voice process to cancel in this channel."
            )
        elif channel_lock.locked():
            abort_sent = await asyncio.to_thread(self._cancel_rpc_session, channel_key)
            await interaction.response.send_message(
                "Sent a cancel request for the active JARVIS job. The current JARVIS session will be preserved."
                if abort_sent
                else "There is no running JARVIS process to cancel in this channel."
            )
        else:
            await interaction.response.send_message("There is no active JARVIS job to cancel in this channel.")

    async def _handle_slash_delete(self, interaction: discord.Interaction) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        channel_key = _channel_lock_key(channel)
        channel_lock = self._get_channel_lock(channel_key)
        if channel_lock.locked():
            await interaction.response.send_message(
                "I'm still working on the previous request in this channel. "
                f"Send `{SLASH_CANCEL_COMMAND}` to abort it before deleting the session."
            )
            return

        await interaction.response.defer(thinking=True)
        async with channel_lock:
            try:
                result = await asyncio.to_thread(self._delete_rpc_session, channel_key, channel)
            except Exception as exc:
                LOGGER.exception("Failed to delete JARVIS session for channel %s", channel_key)
                await interaction.followup.send(f"Failed to delete the current JARVIS session: {exc}")
                return

        await interaction.followup.send(_format_delete_session_result(result))

    async def _handle_slash_new(self, interaction: discord.Interaction) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        channel_key = _channel_lock_key(channel)
        channel_lock = self._get_channel_lock(channel_key)
        if channel_lock.locked():
            await interaction.response.send_message(
                "I'm still working on the previous request in this channel. "
                f"Long research jobs can take several minutes. Send `{SLASH_CANCEL_COMMAND}` to abort it."
            )
            return

        await interaction.response.defer(thinking=True)

        async def _edit_original_response(content: str, *, fallback_to_channel: bool = False) -> None:
            try:
                await interaction.edit_original_response(content=content)
            except Exception:
                LOGGER.exception("Failed to update /jarvis new response")
                if fallback_to_channel:
                    try:
                        await channel.send(content)
                    except Exception:
                        LOGGER.debug("Failed to send fallback /jarvis new channel message", exc_info=True)

        async with channel_lock:
            loop = asyncio.get_running_loop()
            status_message_lock = threading.Lock()
            status_update_requested = False
            status_update_future = None

            def _request_consolidation_status_message() -> None:
                nonlocal status_update_requested, status_update_future
                with status_message_lock:
                    if status_update_requested:
                        return
                    status_update_requested = True
                    status_update_future = asyncio.run_coroutine_threadsafe(
                        _edit_original_response("Consolidating memory..."),
                        loop,
                    )

            def _handle_new_session_event(event: dict[str, object]) -> None:
                if event.get("type") != "extension_ui_request":
                    return
                if event.get("method") != "setStatus":
                    return
                if event.get("statusKey") != "pi-memory":
                    return

                status_text = str(event.get("statusText") or "")
                if "consolidating memory" in status_text.lower():
                    _request_consolidation_status_message()

            async def _wait_for_status_update() -> None:
                with status_message_lock:
                    future = status_update_future
                if future is None:
                    return
                try:
                    await asyncio.wrap_future(future)
                except Exception:
                    LOGGER.debug("Failed to await /jarvis new status update", exc_info=True)

            try:
                data = await asyncio.to_thread(
                    self._start_new_rpc_session,
                    channel_key,
                    channel,
                    _handle_new_session_event,
                )
                await _wait_for_status_update()
                if data.get("cancelled"):
                    await _edit_original_response("JARVIS session switch was cancelled.", fallback_to_channel=True)
                else:
                    await _edit_original_response("Started a new JARVIS session.", fallback_to_channel=True)
            except Exception as exc:
                await _wait_for_status_update()
                LOGGER.exception("Failed to start a new JARVIS session for channel %s", channel_key)
                await _edit_original_response(
                    f"Failed to start a new JARVIS session: {exc}",
                    fallback_to_channel=True,
                )

    async def _handle_slash_compact(self, interaction: discord.Interaction, instructions: str | None = None) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        channel_key = _channel_lock_key(channel)
        channel_lock = self._get_channel_lock(channel_key)
        if channel_lock.locked():
            await interaction.response.send_message(
                "I'm still working on the previous request in this channel. "
                f"Send `{SLASH_CANCEL_COMMAND}` to abort it before compacting."
            )
            return

        custom_instructions = instructions.strip() if isinstance(instructions, str) and instructions.strip() else None
        await interaction.response.defer(thinking=True)

        async def _edit_original_response(content: str, *, fallback_to_channel: bool = False) -> None:
            try:
                await interaction.edit_original_response(content=content)
            except Exception:
                LOGGER.exception("Failed to update /compact response")
                if fallback_to_channel:
                    try:
                        await channel.send(content)
                    except Exception:
                        LOGGER.debug("Failed to send fallback /compact channel message", exc_info=True)

        async with channel_lock:
            loop = asyncio.get_running_loop()
            status_message_lock = threading.Lock()
            status_update_requested = False
            status_update_future = None

            def _request_compaction_status_message(text: str) -> None:
                nonlocal status_update_requested, status_update_future
                with status_message_lock:
                    if status_update_requested:
                        return
                    status_update_requested = True
                    status_update_future = asyncio.run_coroutine_threadsafe(
                        _edit_original_response(text),
                        loop,
                    )

            def _handle_compaction_event(event: dict[str, object]) -> None:
                event_type = event.get("type")
                if event_type == "compaction_start":
                    _request_compaction_status_message("Compacting the current JARVIS session…")
                elif event_type == "extension_ui_request" and event.get("method") == "setStatus":
                    status_text = str(event.get("statusText") or "")
                    if "compact" in status_text.lower():
                        _request_compaction_status_message(status_text or "Compacting the current JARVIS session…")

            async def _wait_for_status_update() -> None:
                with status_message_lock:
                    future = status_update_future
                if future is None:
                    return
                try:
                    await asyncio.wrap_future(future)
                except Exception:
                    LOGGER.debug("Failed to await /compact status update", exc_info=True)

            try:
                stats = await asyncio.to_thread(self._get_rpc_session_stats, channel_key, channel)
                context_tokens = _session_stats_context_tokens(stats)
                total_messages = stats.get("totalMessages")
                if context_tokens == 0 or (context_tokens is None and total_messages == 0):
                    await _edit_original_response(
                        "There is no conversation history to compact.",
                        fallback_to_channel=True,
                    )
                    return

                data = await asyncio.to_thread(
                    self._compact_rpc_session,
                    channel_key,
                    channel,
                    custom_instructions=custom_instructions,
                    on_event=_handle_compaction_event,
                )
                await _wait_for_status_update()
                await _edit_original_response(_format_compaction_result(data), fallback_to_channel=True)
            except Exception as exc:
                await _wait_for_status_update()
                LOGGER.exception("Failed to compact JARVIS session for channel %s", channel_key)
                await _edit_original_response(
                    f"Failed to compact the current JARVIS session: {exc}",
                    fallback_to_channel=True,
                )

    async def _handle_slash_restart(self, interaction: discord.Interaction) -> None:
        channel = await self._require_slash_text_channel(interaction)
        if channel is None:
            return
        if self._restart_in_progress:
            await interaction.response.send_message("A JARVIS restart is already in progress.")
            return

        if self._has_active_channel_work():
            await interaction.response.send_message(
                "I won't restart while a JARVIS job is active because restarting stops the "
                f"bot-managed Pi process. Send `{SLASH_CANCEL_COMMAND}` in the busy channel first, "
                f"then retry `{SLASH_RESTART_COMMAND}`."
            )
            return

        self._restart_in_progress = True
        await interaction.response.send_message("Restart requested. Stopping bot-managed Pi sessions safely…")
        asyncio.create_task(self._restart_process(channel))

    async def _prepare_message_for_rpc(
        self,
        message: discord.Message,
    ) -> tuple[str, list[dict[str, str]], list[Path], discord.Message | None]:
        """Save/transcribe Discord inputs and build the text/images sent to Pi RPC."""
        transcription_status_message: discord.Message | None = None
        voice_attachment_paths: list[Path] = []
        try:
            voice_attachments = [
                attachment for attachment in message.attachments if _is_voice_message_attachment(attachment)
            ]
            voice_transcripts: list[str] = []
            if voice_attachments:
                transcription_status_message = await message.channel.send("Transcribing voice message…")
                voice_attachment_paths = await _save_message_attachments(
                    message,
                    include=_is_voice_message_attachment,
                )
                if not voice_attachment_paths:
                    raise RuntimeError("Voice message attachment could not be saved for transcription.")
                voice_transcripts = await asyncio.to_thread(
                    _transcribe_voice_message_paths,
                    voice_attachment_paths,
                )
                if not voice_transcripts:
                    raise RuntimeError("Voice message ASR produced no transcript.")
                if transcription_status_message is not None:
                    try:
                        await transcription_status_message.edit(
                            content=_format_voice_transcription_status(voice_transcripts)
                        )
                        transcription_status_message = None
                    except Exception:
                        LOGGER.debug("Failed to edit transcription status message", exc_info=True)

            saved_attachment_paths = await _save_message_attachments(
                message,
                include=lambda attachment: not _is_voice_message_attachment(attachment),
            )

            rpc_images = _build_rpc_image_attachments(saved_attachment_paths)
            effective_user_text = _compose_user_message(
                message.content.strip(),
                saved_attachment_paths,
                voice_transcripts=voice_transcripts,
            )
            if not effective_user_text.strip():
                raise RuntimeError("No message text was provided and no attachments were saved successfully.")

            return effective_user_text, rpc_images, voice_attachment_paths, transcription_status_message
        except Exception as exc:
            if transcription_status_message is not None:
                try:
                    await transcription_status_message.edit(content=f"Voice message transcription failed: {exc}")
                    transcription_status_message = None
                except Exception:
                    LOGGER.debug("Failed to edit failed transcription status message", exc_info=True)
            if voice_attachment_paths:
                await asyncio.to_thread(_delete_temporary_paths, voice_attachment_paths)
            raise

    async def _queue_steering_message(self, message: discord.Message, channel_key: str) -> None:
        """Queue a Discord message as Pi steering input for the active stream."""
        transcription_status_message: discord.Message | None = None
        voice_attachment_paths: list[Path] = []
        queued_stream_response: _StreamingResponse | None = None
        queued_marker: str | None = None
        try:
            async with message.channel.typing():
                effective_user_text, rpc_images, voice_attachment_paths, transcription_status_message = (
                    await self._prepare_message_for_rpc(message)
                )
                stream_response = self._active_stream_responses.get(channel_key)
                if stream_response is not None:
                    # Queue the display marker before sending the RPC steer command
                    # so a very fast next turn cannot race ahead of the marker.
                    queued_stream_response = stream_response
                    queued_marker = stream_response.queue_steering_marker(effective_user_text)
                rpc_session = self._get_rpc_session(channel_key, message.channel)
                await asyncio.to_thread(
                    rpc_session.steer_prompt,
                    effective_user_text,
                    images=rpc_images,
                )
            try:
                await message.add_reaction("🕹️")
            except Exception:
                LOGGER.debug("Failed to add steering reaction", exc_info=True)
                await message.channel.send("🕹️ Steering queued.")
        except Exception as exc:
            if queued_stream_response is not None:
                queued_stream_response.discard_steering_marker(queued_marker)
            LOGGER.exception("Failed to queue Discord steering message %s", message.id)
            await message.channel.send(
                "I couldn't steer the active JARVIS job with that message: "
                f"{exc}. Send `{SLASH_CANCEL_COMMAND}` to abort it if needed."
            )
        finally:
            if transcription_status_message is not None:
                try:
                    await transcription_status_message.delete()
                except Exception:
                    LOGGER.debug("Failed to delete transcription status message", exc_info=True)
            if voice_attachment_paths:
                await asyncio.to_thread(_delete_temporary_paths, voice_attachment_paths)

    def _register_slash_commands(self) -> None:
        jarvis_group = discord.app_commands.Group(
            name=SLASH_COMMAND_GROUP,
            description="Control JARVIS in this Discord server.",
        )

        @jarvis_group.command(name="new", description="Start a fresh JARVIS session in this channel.")
        async def new_command(interaction: discord.Interaction) -> None:
            await self._handle_slash_new(interaction)

        @jarvis_group.command(name="delete", description="Delete this channel's current saved JARVIS Pi session.")
        async def delete_command(interaction: discord.Interaction) -> None:
            await self._handle_slash_delete(interaction)

        @jarvis_group.command(name="cancel", description="Cancel the active JARVIS job in this channel.")
        async def cancel_command(interaction: discord.Interaction) -> None:
            await self._handle_slash_cancel(interaction)

        @jarvis_group.command(name="model", description="Show JARVIS model controls.")
        async def model_command(interaction: discord.Interaction) -> None:
            await self._handle_slash_config(interaction)

        @jarvis_group.command(name="thinking", description="Show or change this channel's JARVIS thinking level.")
        @discord.app_commands.describe(level="Thinking level to use for future JARVIS replies.")
        @discord.app_commands.choices(
            level=[discord.app_commands.Choice(name=level, value=level) for level in THINKING_LEVEL_OPTIONS]
        )
        async def thinking_command(interaction: discord.Interaction, level: str | None = None) -> None:
            await self._handle_slash_thinking(interaction, level)

        @jarvis_group.command(name="restart", description="Safely restart the JARVIS Discord bot process.")
        async def restart_command(interaction: discord.Interaction) -> None:
            await self._handle_slash_restart(interaction)

        @jarvis_group.command(name="compact", description="Compact this channel's current JARVIS Pi session.")
        @discord.app_commands.describe(instructions="Optional custom instructions for the compaction summary.")
        async def compact_group_command(interaction: discord.Interaction, instructions: str | None = None) -> None:
            await self._handle_slash_compact(interaction, instructions)

        if self._slash_command_guild is not None:
            self.tree.add_command(jarvis_group, guild=self._slash_command_guild)
        else:
            self.tree.add_command(jarvis_group)

    def _register_events(self) -> None:
        @self.client.event
        async def on_ready() -> None:
            await self._sync_slash_commands_once()
            if self._workout_tracker is not None:
                await self._workout_tracker.sync_thread()
            if self._voice_manager is not None:
                await self._voice_manager.sync_all_voice_channels()

        @self.client.event
        async def on_voice_state_update(
            member: discord.Member,
            before: discord.VoiceState,
            after: discord.VoiceState,
        ) -> None:
            if self._voice_manager is not None:
                self._voice_manager.handle_voice_state_update(member, before, after)

        @self.client.event
        async def on_thread_create(thread: discord.Thread) -> None:
            # Auto-invite configured helper users only to threads created by this bot/JARVIS.
            owner_id = getattr(thread, "owner_id", None)
            bot_user = self.client.user
            if owner_id is not None and bot_user is not None and int(owner_id) != int(bot_user.id):
                return
            await self._add_auto_members_to_thread(thread)

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return

            if not isinstance(message.channel, discord.TextChannel):
                return
            if message.channel.name.lower() not in DISCORD_TARGET_CHANNEL_NAMES:
                return

            user_text = message.content.strip()
            attachments = list(message.attachments)
            if not user_text and not attachments:
                return

            channel_key = _channel_lock_key(message.channel)
            channel_lock = self._get_channel_lock(channel_key)
            if channel_lock.locked():
                await self._queue_steering_message(message, channel_key)
                return

            stream_response: _StreamingResponse | None = None
            transcription_status_message: discord.Message | None = None
            voice_attachment_paths: list[Path] = []

            async with channel_lock:
                active_task = asyncio.current_task()
                if active_task is not None:
                    self._active_channel_tasks[channel_key] = active_task

                try:
                    async with message.channel.typing():
                        effective_user_text, rpc_images, voice_attachment_paths, transcription_status_message = (
                            await self._prepare_message_for_rpc(message)
                        )

                        stream_response = _StreamingResponse(
                            loop=self.client.loop,
                            channel=message.channel,
                            update_interval_seconds=DISCORD_STREAM_EDIT_INTERVAL_SECONDS,
                        )
                        self._active_stream_responses[channel_key] = stream_response

                        rpc_session = self._get_rpc_session(channel_key, message.channel)
                        await asyncio.to_thread(
                            rpc_session.run_prompt,
                            effective_user_text,
                            images=rpc_images,
                            on_event=stream_response.on_rpc_event,
                        )

                    # Stop refreshing Discord's typing indicator before sending the final update.
                    final_text = stream_response._buffer
                    if not final_text and not stream_response.has_output:
                        final_text = "No response received from the agent."
                    if final_text:
                        await stream_response.finalize(final_text)

                    # Wait for any pending updates after the typing context has exited.
                    await stream_response.wait_pending()
                except (asyncio.CancelledError, llm.PiRpcCancelledError):
                    cancel_text = "JARVIS job cancelled."
                    if stream_response is None:
                        await message.channel.send(cancel_text)
                    else:
                        existing_text = stream_response._buffer.strip()
                        await stream_response.finalize(
                            f"{existing_text}\n\n{cancel_text}" if existing_text else cancel_text
                        )
                except Exception as exc:
                    LOGGER.exception(
                        "Failed to process Discord message %s in channel %s",
                        message.id,
                        message.channel.id,
                    )
                    if transcription_status_message is not None:
                        try:
                            await transcription_status_message.edit(content=f"Voice message transcription failed: {exc}")
                            transcription_status_message = None
                        except Exception:
                            LOGGER.debug("Failed to edit failed transcription status message", exc_info=True)
                    error_text = f"JARVIS request failed: {exc}"
                    if stream_response is None:
                        await message.channel.send(error_text)
                    else:
                        await stream_response.finalize(error_text)
                finally:
                    if self._active_stream_responses.get(channel_key) is stream_response:
                        self._active_stream_responses.pop(channel_key, None)
                    if stream_response is not None:
                        await stream_response.close()
                    if transcription_status_message is not None:
                        try:
                            await transcription_status_message.delete()
                        except Exception:
                            LOGGER.debug("Failed to delete transcription status message", exc_info=True)
                    if voice_attachment_paths:
                        await asyncio.to_thread(_delete_temporary_paths, voice_attachment_paths)
                    if active_task is not None and self._active_channel_tasks.get(channel_key) is active_task:
                        self._active_channel_tasks.pop(channel_key, None)

    def run(self) -> None:
        self.client.run(DISCORD_BOT_TOKEN, log_level=logging.WARNING)


def main() -> int:
    if not _acquire_single_instance_lock():
        return 1
    if not DISCORD_BOT_TOKEN:
        LOGGER.error("Missing DISCORD_BOT_TOKEN environment variable.")
        return 1
    if not DISCORD_TARGET_CHANNEL_NAMES:
        LOGGER.error("Missing DISCORD_TARGET_CHANNEL_NAMES environment variable.")
        return 1

    bot = JarvisDiscordBot()
    bot.run()
    return 0


if __name__ == "__main__":
    LOGGER.info("Starting JARVIS...")
    raise SystemExit(main())
