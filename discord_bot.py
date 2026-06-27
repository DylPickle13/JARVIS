from __future__ import annotations

import asyncio
import importlib.util
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import discord
import requests
import config
from discord_support.attachments import (
    build_rpc_image_attachments as _build_rpc_image_attachments,
    compose_user_message as _compose_user_message,
    delete_temporary_paths as _delete_temporary_paths,
    format_voice_transcription_status as _format_voice_transcription_status,
    is_voice_message_attachment as _is_voice_message_attachment,
    save_message_attachments as _save_message_attachments,
    transcribe_voice_message_paths as _transcribe_voice_message_paths,
)
from discord_support.formatting import (
    format_voice_steering_marker as _format_voice_steering_marker,
    truncate_discord_label as _truncate_discord_label,
    truncate_discord_value as _truncate_discord_value,
)
from discord_support.instance_lock import acquire_single_instance_lock as _acquire_single_instance_lock
from discord_support.streaming import _StreamingResponse
from discord_support.tool_labels import _tool_voice_narration

PROJECT_ROOT = config.PROJECT_ROOT
DOTENV_PATH = config.DOTENV_PATH
config.load_project_env(DOTENV_PATH)
LOGGER = config.get_logger("jarvis.discord_bot")


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
            os.getenv("DISCORD_TARGET_CHANNEL_NAME", "jarvis-chat"),
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
QWEN35_9B_COMPAT_MODEL_RE = re.compile(r"(?:^|/)Qwen3\.5-9B(-oQ[56]-mtp|-4bit)$", re.IGNORECASE)
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
# Discord views allow at most 25 components. Reserve one slot for the quota button.
MAX_MODEL_BUTTONS = 24
# Keep each config panel active until a newer /jarvis model panel replaces it.
CONFIG_MENU_TIMEOUT_SECONDS: float | None = None
QUOTAS_SCRIPT_PATH = PROJECT_ROOT / "projects" / "quotas" / "quotas.py"
QUOTAS_LATEST_PATH = PROJECT_ROOT / "projects" / "quotas" / "data" / "latest.json"
QUOTA_CHECK_TIMEOUT_SECONDS = config.get_int_env(
    "DISCORD_QUOTA_CHECK_TIMEOUT_SECONDS",
    90,
    minimum=10,
)
def _channel_lock_key(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, discord.VoiceChannel):
        return f"voice:{channel.id}"
    return str(channel.id)


def _is_voice_channel_context(channel_key: str, channel: object | None = None) -> bool:
    return isinstance(channel, discord.VoiceChannel) or channel_key.startswith("voice:")


def _is_qwen35_9b_model(model: str) -> bool:
    """Detect Qwen3.5 9B session selections for consistent routing.

    Matches the current secondary 16GB oMLX model (Qwen3.5-9B-4bit) and
    older Qwen3.5 9B IDs (oQ5/oQ6-mtp) so all are coerced to the
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


def _model_display_name(model: str) -> str:
    return model.rsplit("/", 1)[-1].strip() or model.strip() or "model"


def _model_button_label(index: int, model: str) -> str:
    return _truncate_discord_label(f"{index}. {_model_display_name(model)}")


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
        reset_credits = usage.get("rate_limit_reset_credits") if isinstance(usage, dict) and isinstance(usage.get("rate_limit_reset_credits"), dict) else {}
        codex_bits = [str(usage.get("plan_type") or "unknown plan") if isinstance(usage, dict) else "unknown plan"]
        if primary:
            codex_bits.append(f"5h {_format_quota_percent(primary.get('used_percent'))} used")
        if secondary:
            codex_bits.append(f"weekly {_format_quota_percent(secondary.get('used_percent'))} used")
        if credits and credits.get("balance") is not None:
            codex_bits.append(f"credits {_format_quota_number(credits.get('balance'))}")
        if reset_credits and reset_credits.get("available_count") is not None:
            codex_bits.append(f"banked resets {_format_quota_number(reset_credits.get('available_count'))}")
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
        if not self.bot._is_active_config_view(self.channel_key, self):
            await interaction.response.send_message(
                f"This config panel has been replaced. Use `{SLASH_CONFIG_COMMAND}` for the active panel.",
                ephemeral=True,
            )
            return
        await self.bot._handle_quota_check(interaction, self.channel_key)

    async def select_model(self, interaction: discord.Interaction, model: str) -> None:
        if not self.bot._is_active_config_view(self.channel_key, self):
            await interaction.response.send_message(
                f"This config panel has been replaced. Use `{SLASH_CONFIG_COMMAND}` for the active panel.",
                ephemeral=True,
            )
            return
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
        self._active_config_views: dict[str, _ConfigView] = {}
        self._active_config_messages: dict[str, object | None] = {}
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

    def _is_active_config_view(self, channel_key: str, view: _ConfigView) -> bool:
        return self._active_config_views.get(channel_key) is view

    async def _retire_config_panel(self, message: object | None, view: _ConfigView | None) -> None:
        if view is None:
            return
        if message is not None:
            try:
                await message.edit(view=None)  # type: ignore[attr-defined]
            except discord.NotFound:
                view.stop()
                return
            except Exception:
                LOGGER.debug("Failed to remove stale Discord config panel buttons", exc_info=True)
                return
        view.stop()

    async def _activate_config_panel(
        self,
        channel_key: str,
        message: object | None,
        view: _ConfigView,
        *,
        retire_previous: bool,
    ) -> None:
        previous_view = self._active_config_views.get(channel_key)
        previous_message = self._active_config_messages.get(channel_key)
        self._active_config_views[channel_key] = view
        self._active_config_messages[channel_key] = message
        if previous_view is None or previous_view is view:
            return
        if retire_previous:
            await self._retire_config_panel(previous_message, previous_view)
        else:
            previous_view.stop()

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
                message = await interaction.message.edit(embed=embed, view=view)
                await self._activate_config_panel(channel_key, message, view, retire_previous=False)
            await interaction.followup.send("Quota refreshed.", ephemeral=True)
        except Exception as exc:
            LOGGER.exception("Failed to refresh quota from Discord config panel")
            embed = self._build_config_embed(channel_key, channel, quota_error=str(exc))
            if interaction.message is not None:
                view = _ConfigView(bot=self, channel_key=channel_key, channel=channel)
                message = await interaction.message.edit(embed=embed, view=view)
                await self._activate_config_panel(channel_key, message, view, retire_previous=False)
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
                message = await interaction.message.edit(embed=embed, view=view)
                await self._activate_config_panel(channel_key, message, view, retire_previous=False)
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
        view = _ConfigView(bot=self, channel_key=channel_key, channel=channel)
        message = await interaction.followup.send(
            embed=self._build_config_embed(channel_key, channel),
            view=view,
            wait=True,
        )
        await self._activate_config_panel(channel_key, message, view, retire_previous=True)

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
