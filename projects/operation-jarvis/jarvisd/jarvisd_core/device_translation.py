"""Legacy-compatible device translation, with no vendor imports or I/O.

The public CLI remains a separate legacy writer until client convergence. Parity
fixtures lock this internal translation to its existing argv/results; this module
never imports or calls that CLI. These are not new capabilities or permissions.
"""
from __future__ import annotations

import argparse
from typing import Any
from .commands import (PURIFIER_SETTINGS, PURIFIER_MODES, PURIFIER_SPEEDS,
                       PURIFIER_AUTO_PREFERENCES)

PURIFIER_ON_OFF_STATES = ("on", "off")

class JarvisError(RuntimeError):
    """Expected vendor-adapter failure; never a reason to replay a write."""

def smart_plug_status_summary(status: dict[str, Any]) -> str:
    name = str(status.get("name") or status.get("alias") or status.get("host") or "smart plug")
    state_value = status.get("is_on")
    state = "on" if state_value is True else "off" if state_value is False else "unknown"
    host = status.get("host")
    alias = status.get("alias")
    label = f"{name} is {state}"
    details = []
    if host:
        details.append(f"host={host}")
    if alias and alias != name:
        details.append(f"alias={alias!r}")
    return f"{label}." + (f" {'; '.join(details)}." if details else "")


def smart_plug_many_summary(plugs: Any, *, verb: str) -> str:
    if not isinstance(plugs, dict) or not plugs:
        return f"No smart plugs {verb}."
    bits: list[str] = []
    for name, value in sorted(plugs.items()):
        if isinstance(value, dict):
            host = value.get("host")
            is_on = value.get("is_on")
            state = "on" if is_on is True else "off" if is_on is False else None
            bits.append(f"{name}={host or '?'}" + (f" ({state})" if state else ""))
        else:
            bits.append(f"{name}={value}")
    return f"Smart plugs {verb}: " + ", ".join(bits) + "."


def purifier_summary(status: dict[str, Any]) -> str:
    name = status.get("name") or "Air purifier"
    power = status.get("power") or ("on" if status.get("is_on") else "off")
    mode = status.get("mode") or "unknown"
    fan = status.get("fan_level")
    pm25 = status.get("pm25")
    filter_life = status.get("filter_life")
    display = status.get("display_status") or status.get("display_set_status")
    bits = [f"{name}: {power}", f"mode {mode}"]
    if fan is not None:
        bits.append(f"fan {fan}")
    if pm25 is not None:
        bits.append(f"PM2.5 {pm25}")
    if filter_life is not None:
        bits.append(f"filter {filter_life}%")
    if display is not None:
        bits.append(f"display {display}")
    supported_modes = status.get("supported_modes")
    if isinstance(supported_modes, list) and supported_modes:
        bits.append("modes " + "/".join(str(mode) for mode in supported_modes))
    supported_fan_levels = status.get("supported_fan_levels")
    if isinstance(supported_fan_levels, list) and supported_fan_levels:
        bits.append("speeds " + "/".join(str(level) for level in supported_fan_levels))
    if status.get("verification_pending"):
        bits.append("write accepted; verification pending")
    return ", ".join(bits) + "."


def _purifier_device_args(args: argparse.Namespace) -> list[str]:
    purifier = (getattr(args, "purifier", None) or "").strip()
    return [purifier] if purifier else []


def _canon_purifier_setting(value: str) -> str:
    setting = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "lock": "child-lock",
        "childlock": "child-lock",
        "child-lock": "child-lock",
        "display-lock": "child-lock",
        "light": "light-detection",
        "light-detect": "light-detection",
        "light-detection": "light-detection",
        "auto": "auto-preference",
        "auto-pref": "auto-preference",
        "auto-preference": "auto-preference",
        "preference": "auto-preference",
        "fan": "speed",
        "fan-speed": "speed",
        "speed": "speed",
        "mode": "mode",
        "power": "power",
        "timer": "timer",
        "display": "display",
    }
    return aliases.get(setting, setting)


def _canon_on_off(value: str, *, allow_toggle: bool = False) -> str:
    clean = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "true": "on",
        "yes": "on",
        "enable": "on",
        "enabled": "on",
        "start": "on",
        "turn-on": "on",
        "false": "off",
        "no": "off",
        "disable": "off",
        "disabled": "off",
        "stop": "off",
        "turn-off": "off",
        "flip": "toggle",
    }
    clean = aliases.get(clean, clean)
    valid = set(PURIFIER_ON_OFF_STATES)
    if allow_toggle:
        valid.add("toggle")
    if clean not in valid:
        raise JarvisError(f"Expected {'on/off/toggle' if allow_toggle else 'on/off'}, got {value!r}")
    return clean


def _value_from_args(args: argparse.Namespace) -> str:
    values = getattr(args, "value", None) or []
    return " ".join(values).strip()


def _purifier_set_cli_args(args: argparse.Namespace) -> list[str]:
    setting = _canon_purifier_setting(args.setting)
    value = _value_from_args(args)
    state = getattr(args, "state", None)
    level = getattr(args, "level", None)
    minutes = getattr(args, "minutes", None)
    purifier = _purifier_device_args(args)

    if setting not in PURIFIER_SETTINGS:
        raise JarvisError(f"Unsupported purifier setting {args.setting!r}; expected one of {', '.join(PURIFIER_SETTINGS)}")

    if setting == "power":
        desired = _canon_on_off(value or state or "", allow_toggle=True)
        return [desired, *purifier]

    if setting == "mode":
        mode = (value or "").strip().lower()
        if mode not in PURIFIER_MODES:
            raise JarvisError(f"Invalid purifier mode {mode!r}; expected one of {', '.join(PURIFIER_MODES)}")
        return ["mode", mode, *purifier]

    if setting == "speed":
        raw_level = level if level is not None else value
        try:
            speed = int(raw_level)
        except (TypeError, ValueError) as exc:
            raise JarvisError("Purifier speed requires level 1-4") from exc
        if speed not in PURIFIER_SPEEDS:
            raise JarvisError("Purifier speed must be 1, 2, 3, or 4")
        return ["speed", str(speed), *purifier]

    if setting == "display":
        desired = _canon_on_off(value or state or "")
        return ["display", desired, *purifier]

    if setting == "child-lock":
        desired = _canon_on_off(value or state or "")
        return ["child-lock", desired, *purifier]

    if setting == "light-detection":
        desired = _canon_on_off(value or state or "")
        return ["light-detection", desired, *purifier]

    if setting == "auto-preference":
        preference = (value or "").strip().lower()
        if preference not in PURIFIER_AUTO_PREFERENCES:
            raise JarvisError(f"Invalid auto preference {preference!r}; expected one of {', '.join(PURIFIER_AUTO_PREFERENCES)}")
        cli_args = ["auto-preference", preference, *purifier]
        room_size = getattr(args, "room_size", None)
        if room_size is not None:
            cli_args.extend(["--room-size", str(room_size)])
        return cli_args

    if setting == "timer":
        if (value or "").strip().lower() in {"clear", "cancel", "off", "none"}:
            return ["clear-timer", *purifier]
        raw_minutes = minutes if minutes is not None else value
        try:
            timer_minutes = int(raw_minutes)
        except (TypeError, ValueError) as exc:
            raise JarvisError("Purifier timer requires minutes, or value='clear'") from exc
        if timer_minutes <= 0 or timer_minutes > 1440:
            raise JarvisError("Purifier timer minutes must be between 1 and 1440")
        return ["timer", str(timer_minutes), *purifier]

    raise JarvisError(f"Unsupported purifier setting {setting!r}")
