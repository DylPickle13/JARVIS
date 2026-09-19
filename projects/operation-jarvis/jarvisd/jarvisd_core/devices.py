"""Pure existing device projections and opaque identities; no vendor SDKs or I/O."""
from __future__ import annotations

import hashlib
from typing import Any

from .commands import PURIFIER_MODES, PURIFIER_SPEEDS


def _purifier_command_data(result: dict) -> dict | None:
    air_purifier = result.get("airPurifier")
    if isinstance(air_purifier, dict) and isinstance(air_purifier.get("data"), dict):
        return air_purifier["data"]
    purifier = result.get("purifier")
    return purifier if isinstance(purifier, dict) else None



def _purifier_expectation(params: Any) -> dict | None:
    if not isinstance(params, dict):
        return None
    setting = params.get("setting")
    value = params.get("value")
    if setting == "power" and value in {"on", "off"}:
        return {"isOn": value == "on"}
    if setting == "mode" and value in PURIFIER_MODES:
        return {"mode": value}
    if setting == "speed":
        level = params.get("level", value)
        if isinstance(level, float) and level.is_integer():
            level = int(level)
        if isinstance(level, int) and level in PURIFIER_SPEEDS:
            return {"mode": "manual", "fanLevel": level}
    return None



def _purifier_matches(state: dict, expected: dict) -> bool:
    for key, value in expected.items():
        if key == "fanLevel":
            if state.get("fanSetLevel") != value and state.get("fanLevel") != value:
                return False
        elif state.get(key) != value:
            return False
    return True



def _purifier_pending_command(expected: Any) -> dict | None:
    """Return only the structured desired state needed for native progress UI."""
    if not isinstance(expected, dict):
        return None
    level = expected.get("fanLevel")
    if isinstance(level, int) and level in PURIFIER_SPEEDS:
        return {"setting": "speed", "level": level}
    is_on = expected.get("isOn")
    if isinstance(is_on, bool):
        return {"setting": "power", "value": "on" if is_on else "off"}
    mode = expected.get("mode")
    if mode in PURIFIER_MODES:
        return {"setting": "mode", "value": mode}
    return None



def _purifier_state(data: dict) -> dict:
    return {
        "ok": True,
        "verificationPending": data.get("verification_pending") is True,
        "isOn": data.get("is_on"),
        "power": data.get("power"),
        "mode": data.get("mode"),
        "fanLevel": data.get("fan_level"),
        "fanSetLevel": data.get("fan_set_level"),
        "pm25": data.get("pm25"),
        "airQualityLevel": data.get("air_quality_level"),
        "filterLife": data.get("filter_life"),
        "childLock": data.get("child_lock"),
        "display": data.get("display_status"),
        "timer": data.get("timer"),
        "name": data.get("name"),
        "model": data.get("model"),
    }



def _purifier_id(cid: str) -> str:
    # Public app identity is stable, but never exposes the raw VeSync CID.
    return hashlib.sha256(("jarvis-purifier-v1:" + cid).encode()).hexdigest()[:24]
