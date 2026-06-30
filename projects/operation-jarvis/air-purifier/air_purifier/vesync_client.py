from __future__ import annotations

import asyncio
import importlib.metadata
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any, Iterable

from .config import Settings, normalize_name

SUPPORTED_VITAL_200S_MODELS = {
    "LAP-V201S-AASR",
    "LAP-V201S-AEUR",
    "LAP-V201S-AUSR",
    "LAP-V201S-WEU",
    "LAP-V201S-WJP",
    "LAP-V201S-WUS",
    "LAP-V201-AUSR",
}
SUPPORTED_MODES = {"manual", "auto", "sleep", "pet"}
SUPPORTED_AUTO_PREFERENCES = {"default", "efficient", "quiet"}


class AirPurifierError(RuntimeError):
    """Expected air-purifier subsystem failure."""


@dataclass(frozen=True)
class DependencyStatus:
    python_version: str
    python_ok: bool
    pyvesync_installed: bool
    pyvesync_version: str | None
    pyvesync_error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "python_version": self.python_version,
            "python_ok": self.python_ok,
            "pyvesync_installed": self.pyvesync_installed,
            "pyvesync_version": self.pyvesync_version,
            "pyvesync_error": self.pyvesync_error,
        }


@dataclass(frozen=True)
class PurifierStatus:
    name: str
    model: str | None
    cid: str | None
    device_region: str | None
    product_type: str | None
    is_on: bool | None
    power: Any
    mode: Any
    fan_level: Any
    fan_set_level: Any
    filter_life: Any
    pm25: Any
    pm1: Any
    pm10: Any
    air_quality_level: Any
    aq_percent: Any
    display_status: Any
    display_set_status: Any
    child_lock: Any
    light_detection_switch: Any
    light_detection_status: Any
    auto_preference_type: Any
    auto_room_size: Any
    timer: Any
    supported_modes: tuple[str, ...]
    supported_fan_levels: tuple[int, ...]
    supported_auto_preferences: tuple[str, ...]
    write_accepted: bool = False
    verification_pending: bool = False
    verification_description: str | None = None
    verification_warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "cid": self.cid,
            "device_region": self.device_region,
            "product_type": self.product_type,
            "is_on": self.is_on,
            "power": _clean_value(self.power),
            "mode": _clean_value(self.mode),
            "fan_level": _clean_value(self.fan_level),
            "fan_set_level": _clean_value(self.fan_set_level),
            "filter_life": _clean_value(self.filter_life),
            "pm25": _clean_value(self.pm25),
            "pm1": _clean_value(self.pm1),
            "pm10": _clean_value(self.pm10),
            "air_quality_level": _clean_value(self.air_quality_level),
            "aq_percent": _clean_value(self.aq_percent),
            "display_status": _clean_value(self.display_status),
            "display_set_status": _clean_value(self.display_set_status),
            "child_lock": _clean_value(self.child_lock),
            "light_detection_switch": _clean_value(self.light_detection_switch),
            "light_detection_status": _clean_value(self.light_detection_status),
            "auto_preference_type": _clean_value(self.auto_preference_type),
            "auto_room_size": _clean_value(self.auto_room_size),
            "timer": _clean_value(self.timer),
            "supported_modes": list(self.supported_modes),
            "supported_fan_levels": list(self.supported_fan_levels),
            "supported_auto_preferences": list(self.supported_auto_preferences),
            "write_accepted": self.write_accepted,
            "verification_pending": self.verification_pending,
            "verification_description": self.verification_description,
            "verification_warning": self.verification_warning,
        }


class AirPurifierController:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def list(self) -> dict[str, PurifierStatus]:
        async with self._session() as manager:
            purifiers = await self._purifiers(manager)
            return {status.name: status for status in map(_status_from_device, purifiers)}

    async def status(self, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            await target.update()
            return _status_from_device(target)

    async def set_power(self, on: bool, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.turn_on() if on else await target.turn_off()
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm power {'on' if on else 'off'} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: status.is_on is on,
                f"power {'on' if on else 'off'}",
            )

    async def toggle(self, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.toggle_switch(None)
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm power toggle for {target.device_name!r}")
            # Toggle may legitimately end either on or off. Poll once so the returned status is fresh.
            await asyncio.sleep(min(5.0, self.settings.write_wait_seconds))
            await target.update()
            return replace(
                _status_from_device(target),
                write_accepted=True,
                verification_pending=False,
                verification_description="power toggle",
            )

    async def set_mode(self, mode: str, device: str | None = None) -> PurifierStatus:
        mode = mode.lower().strip()
        if mode not in SUPPORTED_MODES:
            raise AirPurifierError(f"Invalid mode {mode!r}; expected one of {sorted(SUPPORTED_MODES)}")
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.set_mode(mode)
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm mode {mode!r} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: _clean_value(status.mode) == mode,
                f"mode {mode}",
            )

    async def set_speed(self, level: int, device: str | None = None) -> PurifierStatus:
        if level < 1 or level > 4:
            raise AirPurifierError("Vital 200S fan speed must be between 1 and 4")
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.set_fan_speed(level)
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm fan speed {level} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: (
                    _clean_value(status.mode) == "manual"
                    and (
                        _clean_value(status.fan_set_level) == level
                        or _clean_value(status.fan_level) == level
                    )
                ),
                f"manual fan speed {level}",
            )

    async def set_display(self, on: bool, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.turn_on_display() if on else await target.turn_off_display()
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm display {'on' if on else 'off'} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: _matches_bool(status.display_set_status, on) or _matches_bool(status.display_status, on),
                f"display {'on' if on else 'off'}",
            )

    async def set_child_lock(self, on: bool, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.turn_on_child_lock() if on else await target.turn_off_child_lock()
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm child lock {'on' if on else 'off'} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: bool(status.child_lock) is on,
                f"child lock {'on' if on else 'off'}",
            )

    async def set_light_detection(self, on: bool, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.turn_on_light_detection() if on else await target.turn_off_light_detection()
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm light detection {'on' if on else 'off'} for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: _matches_bool(status.light_detection_switch, on),
                f"light detection {'on' if on else 'off'}",
            )

    async def set_auto_preference(
        self,
        preference: str,
        room_size: int,
        device: str | None = None,
    ) -> PurifierStatus:
        preference = preference.lower().strip()
        if preference not in SUPPORTED_AUTO_PREFERENCES:
            raise AirPurifierError(
                f"Invalid auto preference {preference!r}; expected one of {sorted(SUPPORTED_AUTO_PREFERENCES)}"
            )
        if room_size <= 0:
            raise AirPurifierError("room_size must be greater than 0")
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.set_auto_preference(preference, room_size=room_size)
            if not ok:
                raise AirPurifierError(
                    f"VeSync did not confirm auto preference {preference!r} for {target.device_name!r}"
                )
            return await self._wait_for_status(
                target,
                lambda status: _clean_value(status.auto_preference_type) == preference,
                f"auto preference {preference}",
            )

    async def set_timer(self, minutes: int, device: str | None = None) -> PurifierStatus:
        if minutes <= 0 or minutes > 24 * 60:
            raise AirPurifierError("timer minutes must be between 1 and 1440")
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            ok = await target.set_timer(minutes * 60)
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm timer for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: status.timer is not None,
                f"timer {minutes} minutes",
            )

    async def clear_timer(self, device: str | None = None) -> PurifierStatus:
        async with self._session() as manager:
            target = await self._resolve_device(manager, device)
            try:
                await target.get_timer()
            except Exception:
                pass
            ok = await target.clear_timer()
            if not ok:
                raise AirPurifierError(f"VeSync did not confirm timer clear for {target.device_name!r}")
            return await self._wait_for_status(
                target,
                lambda status: status.timer is None,
                "timer clear",
            )


    async def _wait_for_status(self, target: Any, predicate: Any, description: str) -> PurifierStatus:
        deadline = asyncio.get_running_loop().time() + max(0.0, self.settings.write_wait_seconds)
        last_status: PurifierStatus | None = None
        # Poll fairly quickly at first, then settle into a five-second cadence.
        delay = min(3.0, max(0.0, self.settings.write_wait_seconds))
        while True:
            await asyncio.sleep(delay)
            await target.update()
            last_status = _status_from_device(target)
            if predicate(last_status):
                return replace(
                    last_status,
                    write_accepted=True,
                    verification_pending=False,
                    verification_description=description,
                )

            now = asyncio.get_running_loop().time()
            if now >= deadline:
                warning = (
                    f"VeSync accepted {description}, but the purifier did not report the expected state "
                    f"within {self.settings.write_wait_seconds:.0f}s. Last status may still be stale."
                )
                return replace(
                    last_status,
                    write_accepted=True,
                    verification_pending=True,
                    verification_description=description,
                    verification_warning=warning,
                )
            delay = min(5.0, max(0.25, deadline - now))

    async def _resolve_device(self, manager: Any, requested: str | None = None) -> Any:
        purifiers = await self._purifiers(manager)
        if not purifiers:
            raise AirPurifierError("No VeSync air purifiers were discovered. Pair the purifier in the VeSync app first.")

        selector = requested or self.settings.default_device
        if not selector:
            if len(purifiers) == 1:
                return purifiers[0]
            names = ", ".join(getattr(device, "device_name", "<unknown>") for device in purifiers)
            raise AirPurifierError(f"Multiple air purifiers found; pass a device name/CID. Found: {names}")

        clean_selector = normalize_name(selector)
        for device in purifiers:
            candidates = {
                normalize_name(getattr(device, "device_name", None)),
                normalize_name(getattr(device, "cid", None)),
                normalize_name(getattr(device, "device_type", None)),
                normalize_name(getattr(device, "model", None)),
            }
            if clean_selector in candidates:
                return device
        names = ", ".join(getattr(device, "device_name", "<unknown>") for device in purifiers)
        raise AirPurifierError(f"Could not find air purifier {selector!r}. Found: {names or 'none'}")

    async def _purifiers(self, manager: Any) -> list[Any]:
        await manager.get_devices()
        try:
            await manager.update()
        except Exception:
            # Keep discovery failures visible through individual update/status calls.
            pass
        devices = getattr(manager, "devices", None)
        purifiers = list(getattr(devices, "air_purifiers", []) or [])
        return purifiers

    @asynccontextmanager
    async def _session(self):
        manager = self._manager()
        async with manager as active_manager:
            await active_manager.login()
            if not getattr(active_manager, "enabled", False):
                raise AirPurifierError("VeSync login failed. Check VESYNC_EMAIL/VESYNC_PASSWORD and region settings.")
            yield active_manager

    def _manager(self) -> Any:
        if not self.settings.has_credentials:
            raise AirPurifierError(
                "VeSync credentials are not configured. Set VESYNC_EMAIL and VESYNC_PASSWORD in air-purifier/.env."
            )
        try:
            from pyvesync import VeSync
        except ModuleNotFoundError as exc:
            raise AirPurifierError(
                "pyvesync is not installed. Run: cd projects/operation-jarvis/air-purifier && "
                "/opt/homebrew/bin/python3.13 -m venv .venv && source .venv/bin/activate && "
                "pip install -r requirements.txt -e ."
            ) from exc
        return VeSync(
            username=self.settings.username or "",
            password=self.settings.password or "",
            country_code=self.settings.country_code,
            time_zone=self.settings.time_zone,
            redact=True,
        )


def dependency_status() -> DependencyStatus:
    pyvesync_version: str | None = None
    pyvesync_error: str | None = None
    pyvesync_installed = False
    try:
        pyvesync_version = importlib.metadata.version("pyvesync")
        pyvesync_installed = True
    except Exception as exc:
        pyvesync_error = str(exc)
    return DependencyStatus(
        python_version=sys.version.split()[0],
        python_ok=sys.version_info >= (3, 11),
        pyvesync_installed=pyvesync_installed,
        pyvesync_version=pyvesync_version,
        pyvesync_error=pyvesync_error,
    )


def _status_from_device(device: Any) -> PurifierStatus:
    state = getattr(device, "state", None)
    modes = tuple(str(value) for value in (getattr(device, "modes", []) or []))
    fan_levels = tuple(int(value) for value in (getattr(device, "fan_levels", []) or []))
    auto_preferences = tuple(str(value) for value in (getattr(device, "auto_preferences", []) or []))
    return PurifierStatus(
        name=str(getattr(device, "device_name", "")),
        model=_maybe_str(getattr(device, "device_type", None)),
        cid=_maybe_str(getattr(device, "cid", None)),
        device_region=_maybe_str(getattr(device, "device_region", None)),
        product_type=_maybe_str(getattr(device, "product_type", None)),
        is_on=bool(getattr(device, "is_on")) if hasattr(device, "is_on") else None,
        power=_state_attr(state, "device_status"),
        mode=_state_attr(state, "mode"),
        fan_level=_state_attr(state, "fan_level"),
        fan_set_level=_state_attr(state, "fan_set_level"),
        filter_life=_state_attr(state, "filter_life"),
        pm25=_state_attr(state, "pm25"),
        pm1=_state_attr(state, "pm1"),
        pm10=_state_attr(state, "pm10"),
        air_quality_level=_state_attr(state, "air_quality_level"),
        aq_percent=_state_attr(state, "aq_percent"),
        display_status=_state_attr(state, "display_status"),
        display_set_status=_state_attr(state, "display_set_status"),
        child_lock=_state_attr(state, "child_lock"),
        light_detection_switch=_state_attr(state, "light_detection_switch"),
        light_detection_status=_state_attr(state, "light_detection_status"),
        auto_preference_type=_state_attr(state, "auto_preference_type"),
        auto_room_size=_state_attr(state, "auto_room_size"),
        timer=_state_attr(state, "timer"),
        supported_modes=modes,
        supported_fan_levels=fan_levels,
        supported_auto_preferences=auto_preferences,
    )



def _matches_bool(value: Any, expected: bool) -> bool:
    clean = _clean_value(value)
    if isinstance(clean, bool):
        return clean is expected
    if isinstance(clean, int):
        return bool(clean) is expected
    if isinstance(clean, str):
        return (clean.lower() in {"on", "true", "1", "yes"}) is expected
    return False

def _state_attr(state: Any, name: str) -> Any:
    if state is None:
        return None
    try:
        return getattr(state, name)
    except Exception:
        return None


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _clean_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "value"):
        return _clean_value(getattr(value, "value"))
    if hasattr(value, "to_dict"):
        try:
            return _clean_value(value.to_dict())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean_value(v) for v in value]
    if hasattr(value, "__dict__"):
        try:
            return {str(k): _clean_value(v) for k, v in vars(value).items() if not str(k).startswith("_")}
        except Exception:
            pass
    return str(value)


def statuses_to_dict(statuses: Iterable[PurifierStatus] | dict[str, PurifierStatus]) -> dict[str, Any]:
    if isinstance(statuses, dict):
        return {key: status.as_dict() for key, status in statuses.items()}
    return {status.name: status.as_dict() for status in statuses}


def run(coro: Any) -> Any:
    return asyncio.run(coro)
