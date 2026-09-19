"""Closed command catalog and pure argv validation for existing integrations.

Descriptors are code-owned capabilities, not permission grants. Builders do no
I/O; the selected-purifier resolver is explicitly injected by the composition
root. This module never calls the public CLI or executes a command itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Callable, Literal


PLUG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
PURIFIER_SETTINGS = (
    "power", "mode", "speed", "display", "child-lock", "light-detection", "auto-preference", "timer"
)
PURIFIER_MODES = ("auto", "manual", "sleep", "pet")
PURIFIER_SPEEDS = (1, 2, 3, 4)
PURIFIER_POWER_STATES = ("on", "off", "toggle")
PURIFIER_AUTO_PREFERENCES = ("default", "efficient", "quiet")


class CommandError(ValueError):
    """Raised when a command action or params fail validation."""


def _require_str(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"missing required string param {key!r}")
    return value.strip()


def _plug_name(params: dict) -> str:
    name = _require_str(params, "plug")
    if not PLUG_NAME_RE.fullmatch(name):
        raise CommandError("invalid plug name")
    return name


def _opt_int(params: dict, key: str, lo: int, hi: int) -> int | None:
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"param {key!r} must be an integer")
    if not (lo <= value <= hi):
        raise CommandError(f"param {key!r} must be between {lo} and {hi}")
    return value


def _opt_enum(params: dict, key: str, choices: tuple[str, ...]) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value not in choices:
        raise CommandError(f"param {key!r} must be one of {', '.join(choices)}")
    return value


def purifier_set_args(params: dict, *, selected_purifier: Callable[[str], str]) -> list[str]:
    setting = _require_str(params, "setting")
    if setting not in PURIFIER_SETTINGS:
        raise CommandError(f"unsupported purifier setting {setting!r}")
    args = ["purifier-set", setting]
    if "deviceID" in params:
        device_id = _require_str(params, "deviceID")
        selector = selected_purifier(device_id)
        args += ["--purifier", selector]

    value = params.get("value")
    if value is not None:
        if not isinstance(value, str) or not value.strip():
            raise CommandError("param 'value' must be a non-empty string")
        value = value.strip()
        if setting == "mode" and value not in PURIFIER_MODES:
            raise CommandError(f"invalid mode {value!r}")
        if setting in ("power", "display", "child-lock", "light-detection") and value not in PURIFIER_POWER_STATES:
            raise CommandError(f"invalid state for {setting}")
        if setting == "auto-preference" and value not in PURIFIER_AUTO_PREFERENCES:
            raise CommandError(f"invalid auto-preference {value!r}")
        args.append(value)

    level = _opt_int(params, "level", 1, 4)
    if level is not None:
        args += ["--level", str(level)]
    state = _opt_enum(params, "state", PURIFIER_POWER_STATES)
    if state is not None:
        args += ["--state", state]
    minutes = _opt_int(params, "minutes", 1, 24 * 60)
    if minutes is not None:
        args += ["--minutes", str(minutes)]
    room_size = _opt_int(params, "roomSize", 1, 10000)
    if room_size is not None:
        args += ["--room-size", str(room_size)]
    return args



@dataclass(frozen=True)
class CommandSpec:
    action: str
    integration: str
    effect: Literal["read", "write"]
    build_args: Callable[[dict, Callable[[str], str]], list[str]]
    timeout_seconds: float = 30.0
    replay_allowed: bool = False


# No dynamic plugin loading, shell text, new actions, or broader permissions.
COMMANDS = MappingProxyType({spec.action: spec for spec in (
    CommandSpec("status", "system", "read", lambda p, select: ["status", "--no-cast"]),
    CommandSpec("plug-list", "plugs", "read", lambda p, select: ["plug-list"]),
    CommandSpec("plug-status", "plugs", "read", lambda p, select: ["plug-status", _plug_name(p)]),
    CommandSpec("plug-on", "plugs", "write", lambda p, select: ["plug-on", _plug_name(p)]),
    CommandSpec("plug-off", "plugs", "write", lambda p, select: ["plug-off", _plug_name(p)]),
    # Compatibility only; native controls continue using desired-state on/off.
    CommandSpec("plug-toggle", "plugs", "write", lambda p, select: ["plug-toggle", _plug_name(p)]),
    CommandSpec("purifier-status", "purifier", "read", lambda p, select: ["purifier-status"]),
    CommandSpec("purifier-set", "purifier", "write",
                lambda p, select: purifier_set_args(p, selected_purifier=select)),
)})


def build_command(action: Any, params: Any, *, cli: Path,
                  selected_purifier: Callable[[str], str]) -> list[str]:
    if not isinstance(action, str) or action not in COMMANDS:
        raise CommandError(f"action {action!r} is not allowlisted")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise CommandError("params must be an object")
    argv = COMMANDS[action].build_args(params, selected_purifier)
    return [str(cli), "--json", *argv]
