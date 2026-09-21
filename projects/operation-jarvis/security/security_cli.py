"""JARVIS security CLI: local devices and explicit cloud Smart Actions. No monitoring."""
from __future__ import annotations


# ========================================================================
# H200_COMPAT
# ========================================================================
"""Narrow local workaround for python-kasa 0.10.2 H200 empty child lists.

No global monkeypatch, installed-package edits, writes or inferred sensor state.
Only the exact observed zero-entry metadata response is normalized.
"""


from importlib.metadata import PackageNotFoundError, version


def normalize_empty_child_lists(response: object, method: str) -> bool:
    """Return whether the exact zero-entry response was normalized in place."""
    fields = {"getChildDeviceComponentList": "child_component_list",
              "getChildDeviceList": "child_device_list"}
    if (method not in fields or type(response) is not dict
            or set(response) != {"start_index", "sum"}
            or type(response["start_index"]) is not int
            or type(response["sum"]) is not int
            or response["start_index"] != 0 or response["sum"] != 0):
        return False
    response[fields[method]] = []
    return True


def install_empty_child_lists_compat(protocol) -> bool:
    """Wrap only this H200 connection's list parser, for the pinned SDK only.

    Caller must first validate the discovery model/type as H200/hub. Other SDK
    versions and transport types are left untouched and require fresh testing.
    """
    if protocol is None:
        return False
    try:
        if version("python-kasa") != "0.10.2":
            return False
        from kasa.protocols.smartcamprotocol import SmartCamProtocol
    except (ImportError, PackageNotFoundError):
        return False
    if type(protocol) is not SmartCamProtocol:
        return False
    original = protocol._handle_response_lists

    async def handle(response_result, method, params, retry_count):
        normalize_empty_child_lists(response_result, method)
        return await original(response_result, method, params, retry_count)

    protocol._handle_response_lists = handle
    return True


# ========================================================================
# HUB
# ========================================================================
"""Read-only H200 observations. No alarm decisions, writes, or background polling."""


import asyncio
import ipaddress
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Mapping


@dataclass(frozen=True)
class Settings:
    host: str = ""
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout: float = 10.0
    stale_after: float = 30.0

    def __post_init__(self) -> None:
        if self.host:
            address = ipaddress.ip_address(self.host)
            if not address.is_private or any((address.is_loopback,
                    address.is_unspecified, address.is_multicast, address.is_link_local)):
                raise ValueError("A private LAN IP address is required")
        for value in (self.timeout, self.stale_after):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Timeouts must be finite and positive")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        return cls(host=env.get("JARVIS_SECURITY_HUB_HOST", "").strip(),
                   username=env.get("JARVIS_SECURITY_USERNAME", ""),
                   password=env.get("JARVIS_SECURITY_PASSWORD", ""))

    @property
    def missing(self) -> str | None:
        if not self.host:
            return "missing_host"
        if not self.username or not self.password:
            return "missing_credentials"
        return None


@dataclass(frozen=True)
class Observation:
    model: str
    hardware_version: str | None
    firmware_version: str | None
    # Capability names only: never read feature values or expose child identities.
    capabilities: tuple[str, ...] = ()


class HubReadError(Exception):
    """Fixed public reason; never include device/library exception text."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def read_h200(settings: Settings, *, diagnostics: dict | None = None,
                    identity_only: bool = False) -> Observation:
    """Single-host read; optional diagnostics contain fixed labels, never raw errors."""
    phase = "dependency"
    if diagnostics is not None:
        diagnostics.clear()
    try:
        from kasa import AuthenticationError, Discover
    except ImportError:
        raise HubReadError("dependency_unavailable") from None

    device = None
    try:
        phase = "discovery"
        if diagnostics is not None:
            diagnostics["stage"] = phase
        device = await Discover.discover_single(
            settings.host, username=settings.username, password=settings.password,
            discovery_timeout=min(5, settings.timeout), timeout=settings.timeout,
        )
        if device is None:
            raise HubReadError("unreachable")
        if device.model != "H200" or device.device_type.value != "hub":
            raise HubReadError("unsupported_device")
        if identity_only:
            phase = "identity_read"
            if diagnostics is not None:
                diagnostics["stage"] = phase
            # Same read getter as SmartCam DeviceModule, without child/list queries.
            response = await device.protocol.query({
                "getDeviceInfo": {"device_info": {"name": ["basic_info"]}}})
            info = response["getDeviceInfo"]["device_info"]["basic_info"]
            if (info.get("device_model") != "H200"
                    or not isinstance(info.get("device_type"), str)
                    or not info["device_type"].endswith("HUB")):
                raise HubReadError("unsupported_device")
            hardware, firmware = info.get("hw_version"), info.get("sw_version")
            if not isinstance(hardware, str) or not isinstance(firmware, str):
                raise HubReadError("read_failed")
            return Observation("H200", hardware, firmware)

        install_empty_child_lists_compat(getattr(device, "protocol", None))
        phase = "update"
        if diagnostics is not None:
            diagnostics["stage"] = phase
        await device.update()
        phase = "metadata"
        if diagnostics is not None:
            diagnostics["stage"] = phase
        if device.model != "H200" or device.device_type.value != "hub":
            raise HubReadError("unsupported_device")
        info = device.hw_info
        return Observation(
            model="H200", hardware_version=info.get("hw_ver"),
            firmware_version=info.get("sw_ver"),
            capabilities=tuple(sorted(device.features)),
        )
    except AuthenticationError:
        if diagnostics is not None:
            diagnostics.update(stage=phase, error_type="AuthenticationError")
        raise HubReadError("authentication_failed") from None
    except Exception as exc:
        if diagnostics is not None:
            allowed = {"HubReadError", "TimeoutError", "OSError", "ConnectionError",
                       "DeviceError", "KasaException", "UnsupportedDeviceError",
                       "KeyError", "ValueError", "TypeError", "AttributeError",
                       "ClientConnectorError", "ClientConnectorCertificateError",
                       "ClientResponseError", "ClientConnectorSSLError", "SSLError",
                       "_ConnectionError", "_RetryableError", "RuntimeError",
                       "ServerDisconnectedError", "ClientConnectionResetError"}
            name = type(exc).__name__
            diagnostics.update(stage=phase, error_type=name if name in allowed else "other")
            # Code locations only: no traceback text, locals, arguments or payloads.
            trace = exc.__traceback__
            while trace is not None:
                module = trace.tb_frame.f_globals.get("__name__", "")
                if module.startswith(("kasa.", "aiohttp.", "cryptography.", "asyncio.")):
                    diagnostics["source_module"] = module
                    diagnostics["source_line"] = trace.tb_lineno
                trace = trace.tb_next
            # Only library-defined enum labels are reportable, never exception text.
            try:
                from kasa.exceptions import SmartErrorCode
                code = getattr(exc, "error_code", None)
                if type(code) is SmartErrorCode:
                    diagnostics["device_error"] = code.name
            except ImportError:
                pass
        raise
    finally:
        if device is not None:
            try:
                await asyncio.wait_for(device.disconnect(), timeout=2)
            except Exception:
                # Cleanup failures must not expose raw protocol data or mask reads.
                pass


Reader = Callable[[Settings], Awaitable[Observation]]


class HubMonitor:
    """In-memory last observation; the caller decides when to probe.

    Offline/error states retain timestamped historical metadata, not a live state.
    Freshness uses a monotonic clock, independently of displayed UTC timestamps.
    No credentials or observations are persisted to disk.
    """

    def __init__(self, settings: Settings, *, reader: Reader = read_h200,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.settings = settings
        self._reader = reader
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = asyncio.Lock()
        self._health = "not_configured" if settings.missing else "unknown"
        self._reason = settings.missing or "not_checked"
        self._observation: Observation | None = None
        self._success_tick: float | None = None
        self._last_attempt: str | None = None
        self._last_success: str | None = None

    def snapshot(self) -> dict:
        age = None if self._success_tick is None else max(0, self._clock() - self._success_tick)
        health, reason = self._health, self._reason
        if health == "online" and age is not None and age >= self.settings.stale_after:
            health, reason = "stale", "reading_expired"
        return {
            "health": health, "reason": reason,
            "security_assessment": "not_assessed",
            "last_attempt_at": self._last_attempt,
            "last_success_at": self._last_success,
            "observation_age_seconds": None if age is None else round(age, 3),
            "observation": asdict(self._observation) if self._observation else None,
        }

    async def probe(self) -> dict:
        async with self._lock:
            if self.settings.missing:
                return self.snapshot()
            self._last_attempt = self._wall_clock().isoformat()
            try:
                observation = await asyncio.wait_for(
                    self._reader(self.settings), timeout=self.settings.timeout)
            except asyncio.CancelledError:
                self._health, self._reason = "unknown", "probe_cancelled"
                raise
            except (TimeoutError, OSError):
                self._health, self._reason = "offline", "unreachable"
            except HubReadError as exc:
                # Allowlist public reasons, even if a future adapter misuses the exception.
                reasons = {"unreachable", "authentication_failed", "unsupported_device",
                           "dependency_unavailable"}
                self._reason = exc.reason if exc.reason in reasons else "read_failed"
                self._health = "offline" if self._reason == "unreachable" else "error"
            except Exception:
                self._health, self._reason = "error", "read_failed"
            else:
                self._observation = observation
                self._success_tick = self._clock()
                self._last_success = self._wall_clock().isoformat()
                self._health, self._reason = "online", None
            return self.snapshot()


# ========================================================================
# PRIVATE_ENV
# ========================================================================
"""Explicit, non-shell loader for the private security settings file."""


import os
import stat
from pathlib import Path



_KEYS = {"JARVIS_SECURITY_HUB_HOST", "JARVIS_SECURITY_USERNAME", "JARVIS_SECURITY_PASSWORD"}


class PrivateEnvError(ValueError):
    """Fixed error text only; no file contents or account details."""


def load_settings(path: str | Path) -> Settings:
    """Read an owner-only regular file. No sourcing, expansion or environment export.

    Values after '=' are literal, including '#' and '$'. One matching pair of
    surrounding single/double quotes is optional. Escapes/interpolation and inline
    comments are deliberately unsupported. Use literal values inside the quotes.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as file:
            info = os.fstat(file.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise PrivateEnvError("private_env_permissions")
            text = file.read(65537)
        if len(text) > 65536:
            raise PrivateEnvError("invalid_private_env")
        values = {}
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in _KEYS or key in values:
                raise PrivateEnvError("invalid_private_env")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise PrivateEnvError("invalid_private_env")
                value = value[1:-1]
            if "\x00" in value:
                raise PrivateEnvError("invalid_private_env")
            values[key] = value
        settings = Settings.from_env(values)
        if settings.missing:
            raise PrivateEnvError("incomplete_private_env")
        return settings
    except PrivateEnvError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise PrivateEnvError("invalid_private_env") from None


# ========================================================================
# CAMERAS
# ========================================================================
"""Offline C230 preparation: no sockets, SDK, decoder, recorder, or device control."""


import ipaddress
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("An aware acquisition timestamp is required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CameraSettings:
    """Dedicated camera credentials; never reuse the TP-Link cloud/hub login.

    No URL generation or automatic environment/file loading. Do not serialize
    this object with asdict: repr protection is not a secret-store mechanism.
    """

    host: str = field(default="", repr=False)
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) for value in (self.host, self.username, self.password)):
            raise ValueError("Camera configuration must contain strings")
        if self.host:
            try:
                address = ipaddress.ip_address(self.host)
            except ValueError:
                raise ValueError("A private camera LAN IP is required") from None
            if not address.is_private or any((address.is_loopback, address.is_unspecified,
                                             address.is_multicast, address.is_link_local)):
                raise ValueError("A private camera LAN IP is required")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> CameraSettings:
        return cls(host=env.get("JARVIS_SECURITY_CAMERA_HOST", "").strip(),
                   username=env.get("JARVIS_SECURITY_CAMERA_USERNAME", ""),
                   password=env.get("JARVIS_SECURITY_CAMERA_PASSWORD", ""))

    @property
    def missing(self) -> str | None:
        if not self.host:
            return "missing_host"
        if not self.username or not self.password:
            return "missing_credentials"
        return None


@dataclass(frozen=True)
class FrameObservation:
    """Metadata for a newly decoded frame, not an image or proof of recording.

    Future adapters must preserve original acquisition time on replay. Merely
    reaching a camera TCP port is not evidence of a decoded video frame.
    """

    observed_at: datetime
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if any(type(value) is not int or value <= 0 for value in (self.width, self.height)):
            raise ValueError("Frame dimensions must be positive integers")

    def as_dict(self) -> dict:
        return {"observed_at": self.observed_at.isoformat(),
                "width": self.width, "height": self.height}


class CameraTracker:
    """Caller-fed video health, in memory only. Never opens a connection.

    One instance represents one configured camera/stream, not overall network
    reachability. Use separate instances for stream1/stream2. Production freshness
    limits and the real transport are intentionally not chosen or implemented.
    """

    def __init__(self, settings: CameraSettings, *, stale_after: float,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if isinstance(stale_after, bool) or not math.isfinite(stale_after) or stale_after <= 0:
            raise ValueError("Freshness limit must be finite and positive")
        self.settings = settings
        self.stale_after = stale_after
        self._clock, self._wall_clock = clock, wall_clock
        self._health = "not_configured" if settings.missing else "unknown"
        self._reason = settings.missing or "not_checked"
        self._last: FrameObservation | None = None
        self._received_tick = 0.0
        self._initial_age = 0.0

    def snapshot(self) -> dict:
        age = None if self._last is None else (
            self._initial_age + max(0.0, self._clock() - self._received_tick))
        health, reason = self._health, self._reason
        if health == "online" and age is not None and age >= self.stale_after:
            health, reason = "stale", "frame_expired"
        return {
            "health": health, "reason": reason,
            "video": "available" if health == "online" else "unknown",
            "security_assessment": "not_assessed",
            "recording_assessment": "not_assessed",
            "privacy_mode_assessment": "not_assessed",
            "frame_age_seconds": None if age is None else round(age, 3),
            "last_frame": self._last.as_dict() if self._last else None,
        }

    def mark_unavailable(self, reason: str = "unreachable") -> None:
        if self.settings.missing:
            return
        # Raw exceptions, URLs, or device payloads must never enter public status.
        allowed = {"unreachable", "authentication_failed", "stream_unavailable", "read_failed"}
        self._reason = reason if reason in allowed else "read_failed"
        self._health = "offline" if self._reason == "unreachable" else "error"

    def accept_frame(self, observation: FrameObservation) -> bool:
        """Accept metadata only; False means duplicate/out-of-order. No emitted events."""
        if self.settings.missing:
            raise ValueError("Camera is not configured")
        age = (_utc(self._wall_clock()) - observation.observed_at).total_seconds()
        if age < 0:
            self.mark_unavailable("read_failed")
            raise ValueError("Frame timestamp is in the future")
        if self._last and observation.observed_at <= self._last.observed_at:
            return False
        self._last = observation
        self._received_tick = self._clock()
        self._initial_age = age
        self._health, self._reason = "online", None
        return True


# ========================================================================
# SENSORS
# ========================================================================
"""Offline T100/T110 state contracts. No transport, polling, storage, or alerts."""


import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal


Model = Literal["T100", "T110"]
State = Literal["motion", "clear", "open", "closed", "unknown"]
_STATES = {"T100": {"motion", "clear", "unknown"},
           "T110": {"open", "closed", "unknown"}}


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("An aware observation timestamp is required")


@dataclass(frozen=True)
class SensorObservation:
    """Normalized sample, NOT a vendor payload or proof of a physical event.

    observed_at is the actual local acquisition time, never the time a cached
    payload was replayed. Missing/unsupported state must be explicitly unknown.
    Battery percentage and low-battery flag are independent, optional facts.
    """

    sensor_id: str
    model: Model
    state: State
    observed_at: datetime
    battery_percent: int | None = None
    low_battery: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sensor_id, str) or not self.sensor_id.strip():
            raise ValueError("A local sensor identifier is required")
        if self.model not in _STATES or self.state not in _STATES[self.model]:
            raise ValueError("Invalid model/state combination")
        _aware(self.observed_at)
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))
        if self.battery_percent is not None and (
                type(self.battery_percent) is not int or not 0 <= self.battery_percent <= 100):
            raise ValueError("Battery percentage must be an integer from 0 to 100 or None")
        if self.low_battery is not None and type(self.low_battery) is not bool:
            raise ValueError("Low-battery flag must be a boolean or None")

    def as_dict(self) -> dict:
        return {
            "sensor_id": self.sensor_id, "model": self.model, "state": self.state,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "battery_percent": self.battery_percent, "low_battery": self.low_battery,
        }


@dataclass(frozen=True)
class ObservedChange:
    """A change between consecutive fresh readings; not an alarm or notification."""

    sensor_id: str
    model: Model
    previous: State
    current: State
    observed_at: datetime


class SensorTracker:
    """One sensor, caller-supplied observations, in-memory only.

    The first known reading establishes a baseline silently. A disconnect,
    unknown state, or freshness gap breaks continuity: the next known reading
    establishes a new baseline, never a reconstructed intrusion/clear event.
    Freshness is required explicitly; no production timing is chosen here.
    """

    def __init__(self, sensor_id: str, model: Model, *, stale_after: float,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if not isinstance(sensor_id, str) or not sensor_id.strip() or model not in _STATES:
            raise ValueError("A supported sensor identity is required")
        if not math.isfinite(stale_after) or stale_after <= 0:
            raise ValueError("Freshness limit must be finite and positive")
        self.sensor_id, self.model = sensor_id, model
        self.stale_after = stale_after
        self._clock, self._wall_clock = clock, wall_clock
        self._last: SensorObservation | None = None
        self._received_tick = 0.0
        self._initial_age = 0.0
        self._health, self._reason = "unknown", "not_observed"

    def _age(self) -> float | None:
        if self._last is None:
            return None
        return self._initial_age + max(0.0, self._clock() - self._received_tick)

    def snapshot(self) -> dict:
        age = self._age()
        health, reason = self._health, self._reason
        if health in {"online", "unknown"} and age is not None and age >= self.stale_after:
            health, reason = "stale", "reading_expired"
        live = self._last if health == "online" else None
        return {
            "sensor_id": self.sensor_id, "model": self.model,
            "health": health, "reason": reason,
            "state": live.state if live else "unknown",
            "battery_percent": live.battery_percent if live else None,
            "low_battery": live.low_battery if live else None,
            "security_assessment": "not_assessed",
            "observation_age_seconds": None if age is None else round(age, 3),
            "last_observation": self._last.as_dict() if self._last else None,
        }

    def mark_unavailable(self, reason: Literal["offline", "error"] = "offline") -> None:
        """Future adapter must call for hub loss, missing child, or read failure."""
        if reason not in {"offline", "error"}:
            raise ValueError("Unsupported unavailable reason")
        self._health, self._reason = reason, "sensor_unavailable"

    def accept(self, observation: SensorObservation) -> ObservedChange | None:
        if observation.sensor_id != self.sensor_id or observation.model != self.model:
            raise ValueError("Observation does not match this sensor")
        now = self._wall_clock()
        _aware(now)
        age = (now.astimezone(timezone.utc) - observation.observed_at).total_seconds()
        if age < 0:
            # Clock skew or an invalid timestamp must not maintain a live baseline.
            self.mark_unavailable("error")
            raise ValueError("Observation timestamp is in the future")
        if self._last and observation.observed_at <= self._last.observed_at:
            # Duplicates/out-of-order samples neither refresh age nor heal an outage.
            return None

        previous = self.snapshot()
        self._last = observation
        self._received_tick = self._clock()
        self._initial_age = age
        if observation.state == "unknown":
            self._health, self._reason = "unknown", "state_unavailable"
        else:
            self._health, self._reason = "online", None
        current = self.snapshot()
        if (previous["health"] == current["health"] == "online"
                and previous["state"] != current["state"]):
            return ObservedChange(self.sensor_id, self.model, previous["state"],
                                  current["state"], observation.observed_at)
        return None


# ========================================================================
# STORAGE
# ========================================================================
"""Explicit H200 SD-status getter. No formatting, recording or media download."""


import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import re





class StorageReadError(Exception):
    """Fixed public error code only."""


def unknown_status(health="unknown", reason="not_checked") -> dict:
    return {
        "health": health, "reason": reason, "observed_at": None,
        "card_state": "unknown", "detection_state": "unknown",
        "access_mode": "unknown", "reported_total_space": None,
        "reported_free_space": None, "recording": "not_assessed",
        "playback": "not_assessed", "download": "not_assessed",
        "security_assessment": "not_assessed",
    }


def normalize_status(response: object) -> dict:
    """Accept one well-shaped card record; expose only allowlisted metadata.

    'offline' is not proof of physical absence. A normal card is not evidence of
    enabled recording or readable saved footage. Unknown fields never imply normal.
    """
    try:
        table = response["get"]["harddisk_manage"]["hd_info"]
        if not isinstance(table, list) or len(table) != 1:
            raise ValueError
        row = table[0]
        if not isinstance(row, dict) or len(row) != 1:
            raise ValueError
        name, info = next(iter(row.items()))
        if not isinstance(name, str) or not re.fullmatch(r"hd_info_[0-9]+", name):
            raise ValueError
        if not isinstance(info, dict):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise StorageReadError("invalid_storage_response") from None
    result = unknown_status("online", None)
    states = {"normal", "offline", "unformatted", "formatting", "abnormal", "error"}
    for source, target in (("status", "card_state"), ("detect_status", "detection_state")):
        value = info.get(source)
        if type(value) is str and value in states:
            result[target] = value
    # Do not present capacities/access retained in an offline/error response as live.
    if result["card_state"] == "normal" and result["detection_state"] == "normal":
        mode = info.get("rw_attr")
        if type(mode) is str:
            result["access_mode"] = {"rw": "read_write", "ro": "read_only", "r": "read_only"}.get(mode, "unknown")
        for source, target in (("total_space", "reported_total_space"),
                               ("free_space", "reported_free_space")):
            value = info.get(source)
            if (type(value) is str and len(value) <= 32
                    and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?\s*(?:B|KB|MB|GB|TB)", value.strip())):
                result[target] = value.strip()
    return result


async def read_storage(settings: Settings) -> dict:
    """Authenticate to one H200; query storage metadata once, with no SDK retries."""
    try:
        from kasa import AuthenticationError, Discover
    except ImportError:
        raise StorageReadError("dependency_unavailable") from None
    device = None
    try:
        device = await Discover.discover_single(
            settings.host, username=settings.username, password=settings.password,
            discovery_timeout=min(5, settings.timeout), timeout=settings.timeout)
        if device is None:
            raise StorageReadError("unreachable")
        if device.model != "H200" or device.device_type.value != "hub":
            raise StorageReadError("unsupported_device")
        # Native read-only getter. Do not substitute formatSdCard or a 'set'/'do'.
        response = await device.protocol.query(
            {"get": {"harddisk_manage": {"table": ["hd_info"]}}}, retry_count=0)
        result = normalize_status(response)
        result["observed_at"] = datetime.now(timezone.utc).isoformat()
        return result
    except AuthenticationError:
        raise StorageReadError("authentication_failed") from None
    finally:
        if device is not None:
            try:
                await asyncio.wait_for(device.disconnect(), timeout=2)
            except Exception:
                pass


async def probe_storage(settings: Settings, *, reader=read_storage) -> dict:
    if settings.missing:
        return unknown_status("not_configured", settings.missing)
    try:
        return await asyncio.wait_for(reader(settings), timeout=settings.timeout)
    except (TimeoutError, OSError):
        return unknown_status("offline", "unreachable")
    except StorageReadError as exc:
        reason = str(exc)
        allowed = {"dependency_unavailable", "unsupported_device", "unreachable",
                   "authentication_failed", "invalid_storage_response"}
        return unknown_status("offline" if reason == "unreachable" else "error",
                              reason if reason in allowed else "storage_read_failed")
    except Exception:
        return unknown_status("error", "storage_read_failed")


def storage_probe_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only H200 SD-card status")
    parser.add_argument("--probe", action="store_true", help="Explicitly read hub storage status once")
    parser.add_argument("--env-file", help="Explicit private hub settings file")
    args = parser.parse_args(argv)
    if not args.probe:
        print(json.dumps(unknown_status(), indent=2))
        return 2
    if not args.env_file:
        parser.error("--probe requires --env-file")
    logging.disable(logging.CRITICAL)
    try:
        settings = load_settings(args.env_file)
        result = asyncio.run(probe_storage(settings))
    except PrivateEnvError as exc:
        result = unknown_status("not_configured", str(exc))
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, indent=2))
    # Exit 0 only when both endpoint and card report normal. Still not recording proof.
    return 0 if (result["health"] == "online" and result["card_state"] == "normal"
                 and result["detection_state"] == "normal") else 2






# ========================================================================
# COMMISSION
# ========================================================================
"""Interactive one-shot H200 check; hidden input, no credential persistence."""


import asyncio
import getpass
import json
import logging
import sys
import warnings




def commission_main() -> int:
    # Refuse pipes/tool consoles. Never allow getpass's echoing fallback.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Run this command directly in a private Terminal window.")
        return 2
    print("JARVIS: one read-only H200 check. No alarms or settings changes.")
    print("All three entries are hidden. Nothing is saved or added to shell history.")
    print("Use your Tapo/TP-Link account login, not a camera account. Ctrl-C cancels.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            host = getpass.getpass("H200 LAN IP (hidden): ").strip()
            # Validate the target before requesting any account credentials.
            Settings(host=host)
            if not host:
                print("Hub IP is required; no connection attempted.")
                return 2
            username = getpass.getpass("Tapo account email (hidden): ").strip()
            password = getpass.getpass("Tapo account password (hidden): ")
        settings = Settings(host=host, username=username, password=password)
        if settings.missing:
            print("Credentials are required; no connection attempted.")
            return 2
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; no connection attempted.")
        return 130
    except getpass.GetPassWarning:
        print("Hidden input unavailable; no connection attempted.")
        return 2
    except ValueError:
        print("Invalid LAN IP; no connection attempted.")
        return 2

    # Library protocol/debug messages must never reach the Terminal or log handlers.
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(HubMonitor(settings).probe())
    except KeyboardInterrupt:
        print("\nCheck cancelled; authenticated access is unconfirmed.")
        return 130
    except Exception:
        print("Check failed; authenticated access is unconfirmed.")
        return 2
    # No raw device payloads, IPs, account names, firmware or capability inventory.
    print(json.dumps({key: result[key] for key in
                      ("health", "reason", "security_assessment")}, indent=2))
    print("One-shot check complete. Credentials were not saved; no monitoring is running.")
    return 0 if result["health"] == "online" else 2






# ========================================================================
# CHECK_ENV
# ========================================================================
"""Explicit one-shot read from a private file; never prints its contents."""


import argparse
import asyncio
from functools import partial
import json
import logging





def check_env_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="One read-only H200 check from a private file")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--identity-only", action="store_true",
                        help="Authenticate and read hub identity only; no feature/child inventory")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        settings = load_settings(args.env_file)
    except PrivateEnvError as exc:
        print(json.dumps({"health": "not_configured", "reason": str(exc),
                          "security_assessment": "not_assessed"}))
        return 2
    diagnostics = {}
    try:
        result = asyncio.run(HubMonitor(settings, reader=partial(
            read_h200, diagnostics=diagnostics, identity_only=args.identity_only)).probe())
    except KeyboardInterrupt:
        print("Check cancelled; authenticated access is unconfirmed.")
        return 130
    except Exception:
        print("Check failed; authenticated access is unconfirmed.")
        return 2
    public = {key: result[key] for key in ("health", "reason", "security_assessment")}
    if args.identity_only:
        public["read_scope"] = "identity_only"
        public["capability_inventory"] = "not_assessed"
    if result["health"] != "online":
        public["diagnostic"] = diagnostics
    print(json.dumps(public, indent=2))
    return 0 if result["health"] == "online" else 2






# ========================================================================
# __MAIN__
# ========================================================================
"""Default status is offline-only. --probe explicitly opts into a network read."""


import argparse
import asyncio
import json
import os




def offline_status_main() -> int:
    parser = argparse.ArgumentParser(description="Read-only JARVIS H200 status")
    parser.add_argument("command", choices=["status"])
    parser.add_argument("--probe", action="store_true", help="Read the configured hub once over LAN")
    args = parser.parse_args()
    try:
        settings = Settings.from_env(os.environ)
    except ValueError:
        print(json.dumps({"health": "error", "reason": "invalid_config",
                          "security_assessment": "not_assessed"}))
        return 2
    monitor = HubMonitor(settings)
    try:
        result = asyncio.run(monitor.probe()) if args.probe else monitor.snapshot()
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, indent=2))
    return 0 if result["health"] == "online" else 2






# ========================================================================
# CONTROL
# ========================================================================
"""Bounded security adapter. No polling, media, arbitrary RPCs or automatic writes."""


import asyncio
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re




ROOT = Path(__file__).resolve().parent
WRITES = {
    'C230': {'state', 'led', 'motion_detection', 'person_detection',
             'pet_detection', 'baby_cry_detection', 'tamper_detection'},
    'H200': {'led', 'alarm_sound', 'alarm_volume', 'alarm_duration'},
    'D235': set(),
}
SENSOR_MODELS = {'T100', 'T110'}
WRITES.update({model: set() for model in SENSOR_MODELS})
ACTIONS = {'T100': set(), 'T110': set(), 'C230': {'pan_left', 'pan_right', 'tilt_up', 'tilt_down'},
           'H200': {'stop_alarm', 'test_alarm'}, 'D235': set()}
READS = set.union(*WRITES.values()) | {'alarm', 'rssi', 'signal_level', 'device_time'}


class ControlError(Exception):
    """Only fixed public reason codes belong here."""


def registry(path=ROOT / 'devices.json'):
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or not data or len(data) > 16:
            raise ValueError
        for alias, entry in data.items():
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', alias):
                raise ValueError
            if entry.get('model') == 'D235':
                if set(entry) not in ({'model', 'hub'}, {'model', 'hub', 'host'}) or entry['hub'] != 'hub':
                    raise ValueError
                if 'host' in entry:
                    Settings(host=entry['host'])
                    if not entry['host'] or entry['host'] == '@hub':
                        raise ValueError
                continue
            if entry.get('model') in SENSOR_MODELS:
                if (set(entry) != {'model', 'hub', 'name'} or entry['hub'] != 'hub'
                        or not isinstance(entry['name'], str) or not entry['name'].strip()):
                    raise ValueError
                continue
            if set(entry) != {'model', 'host'} or entry['model'] not in WRITES:
                raise ValueError
            if entry['host'] != '@hub':
                Settings(host=entry['host'])
                if not entry['host']:
                    raise ValueError
        if any(e['model'] in SENSOR_MODELS | {'D235'} for e in data.values()):
            if data.get('hub', {}).get('model') != 'H200':
                raise ValueError
        return data
    except Exception:
        raise ControlError('invalid_device_registry') from None


@contextmanager
def device_lock(alias, root=ROOT):
    directory = root / '.locks'
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(directory / (alias + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ControlError('device_busy') from None
        yield
    finally:
        os.close(fd)


def clean(value):
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9 _().:+/\-]{1,100}', value):
        return value
    return None


def healthy_feature(device, name):
    feature = device.features.get(name)
    if feature is None:
        raise ControlError('unsupported_feature')
    container = getattr(feature, 'container', None)
    if getattr(container, '_last_update_error', None) is not None or getattr(container, 'disabled', False):
        raise ControlError('feature_unavailable')
    return feature


def inventory(device, model):
    result = {}
    for name in sorted(READS | ACTIONS[model]):
        if name not in device.features:
            continue
        try:
            f = healthy_feature(device, name)
            row = {'type': f.type.name, 'writable': name in WRITES[model],
                   'action': name in ACTIONS[model], 'control_verification': 'not_assessed'}
            if f.type.name != 'Action':
                row['value'] = clean(f.value)
            if f.type.name == 'Choice':
                row['choices'] = [clean(x) for x in (f.choices or [])]
            if f.type.name == 'Number':
                row['minimum'], row['maximum'] = clean(f.minimum_value), clean(f.maximum_value)
            result[name] = row
        except Exception:
            result[name] = {'status': 'unknown'}
    if model == 'C230':
        state = result.get('state', {}).get('value')
        result['privacy'] = {'value': not state if type(state) is bool else None,
                             'meaning': 'privacy_on_is_camera_state_off'}
    return result


def parse_value(feature, text):
    kind = feature.type.name
    if kind == 'Switch':
        if text not in ('on', 'off'):
            raise ControlError('expected_on_or_off')
        return text == 'on'
    if kind == 'Number':
        try:
            if not re.fullmatch(r'-?\d{1,8}', text):
                raise ValueError
            value = int(text)
            if not feature.minimum_value <= value <= feature.maximum_value:
                raise ValueError
            return value
        except Exception:
            raise ControlError('number_out_of_range') from None
    if kind == 'Choice' and text in (feature.choices or []):
        return text
    raise ControlError('invalid_feature_value')


def validate_request(model, command, name, value, confirm, audible):
    if model == 'D235':
        if command in ('recording', 'recordings', 'clip'):
            from security_recording import validate
        else:
            from security_doorbell_direct import validate
        validate(command, name, value, confirm)
        return
    if model in SENSOR_MODELS and command not in ('status', 'capabilities'):
        raise ControlError('unsupported_command')
    if command not in ('status', 'capabilities', 'storage', 'set', 'action', 'privacy', 'move'):
        raise ControlError('unsupported_command')
    if command in ('set', 'action', 'privacy', 'move'):
        if not confirm:
            raise ControlError('confirmation_required')
    if command == 'set' and name not in WRITES[model]:
        raise ControlError('unsupported_setting')
    if command == 'action' and name not in ACTIONS[model]:
        raise ControlError('unsupported_action')
    if command in ('privacy', 'move') and model != 'C230':
        raise ControlError('camera_required')
    if command == 'privacy' and value not in ('on', 'off'):
        raise ControlError('expected_on_or_off')
    if command == 'move' and (name not in ('left', 'right', 'up', 'down') or
                              type(value) is not int or not 1 <= value <= 30):
        raise ControlError('invalid_movement')
    if command == 'action' and name == 'test_alarm' and not audible:
        raise ControlError('audible_confirmation_required')
    if command == 'storage' and model != 'H200':
        raise ControlError('hub_required')


async def operate(device, model, command, name=None, value=None, progress=None):
    progress = progress if progress is not None else {}
    if command in ('status', 'capabilities'):
        return {'result': 'read_succeeded', 'features': inventory(device, model)}
    if command == 'storage':

        response = await device.protocol.query({'get': {'harddisk_manage': {'table': ['hd_info']}}})
        storage = normalize_status(response)
        storage['observed_at'] = datetime.now(timezone.utc).isoformat()
        return {'result': 'read_succeeded', 'storage': storage}
    if command == 'privacy':
        name, value = 'state', 'off' if value == 'on' else 'on'
    if command == 'move':
        direction = {'left': 'pan_left', 'right': 'pan_right', 'up': 'tilt_up', 'down': 'tilt_down'}[name]
        step = 'pan_step' if name in ('left', 'right') else 'tilt_step'
        target = healthy_feature(device, direction)
        # SDK step is in-memory only; apply it within this same command.
        await healthy_feature(device, step).set_value(value)
        progress['write_started'] = True
        await target.set_value(None)
        return {'result': 'acknowledged', 'physical_position': 'not_verified'}
    f = healthy_feature(device, name)
    if command == 'action':
        if name == 'test_alarm':
            duration = healthy_feature(device, 'alarm_duration').value
            if type(duration) is not int or not 1 <= duration <= 60:
                raise ControlError('alarm_requires_duration_1_to_60_seconds')
        progress['write_started'] = True
        await f.set_value(None)
        return {'result': 'acknowledged', 'physical_effect': 'not_verified'}
    desired = parse_value(f, value)
    progress['write_started'] = True
    await f.set_value(desired)
    # Force a current observation rather than accepting module throttling/cached values.
    for module in device.modules.values():
        module._last_update_time = None
    await device.update(update_children=False)
    actual = healthy_feature(device, name).value
    if type(actual) is not type(desired) or actual != desired:
        return {'result': 'readback_mismatch', 'outcome': 'unknown'}
    return {'result': 'verified', 'setting': name, 'value': clean(actual)}


def sensor_inventory(device, model):
    names = {'battery_low', 'rssi', 'signal_level',
             'motion_detected' if model == 'T100' else 'is_open'}
    result = {}
    for name in sorted(names):
        try:
            result[name] = {'value': clean(healthy_feature(device, name).value),
                            'writable': False}
        except Exception:
            result[name] = {'status': 'unknown', 'writable': False}
    return result


def select_sensor(hub, entry):
    matches = [child for child in hub.children
               if child.model == entry['model'] and child.alias == entry['name']]
    if len(matches) != 1:
        raise ControlError('sensor_missing_or_ambiguous')
    return matches[0]


async def execute(alias, command, *, name=None, value=None, confirm=False,
                  audible=False, env_file=ROOT / '.env', registry_path=ROOT / 'devices.json'):
    devices = registry(registry_path)
    if alias not in devices:
        raise ControlError('unknown_device')
    entry = devices[alias]
    model = entry['model']
    if model == 'D235':
        validate_request(model, command, name, value, confirm, audible)
        from security_doorbell import execute as read_doorbell
        if 'host' not in entry and command not in ('status', 'capabilities'):
            raise ControlError('direct_doorbell_required')
        with device_lock(entry['hub']):
            if 'host' in entry:
                result = await read_doorbell(env_file, entry=entry, command=command,
                                           name=name, value=value, confirm=confirm)
            else:
                result = await read_doorbell(env_file)
        return {'device': alias, **result}
    is_sensor = model in SENSOR_MODELS
    connection_entry = devices[entry['hub']] if is_sensor else entry
    connection_model = connection_entry['model']
    validate_request(model, command, name, value, confirm, audible)
    progress = {}
    stage = 'preflight'
    device = None
    from kasa import Discover
    try:
        with device_lock(entry['hub'] if is_sensor else alias):
            settings = load_settings(env_file)
            host = settings.host if connection_entry['host'] == '@hub' else connection_entry['host']
            stage = 'connection'
            # A sensor read includes H200 child initialization; keep writes at
            # their existing budget and never automatically replay a request.
            async with asyncio.timeout(60 if is_sensor else 25):
                device = await Discover.discover_single(host, username=settings.username,
                    password=settings.password, discovery_timeout=5 if is_sensor else 3,
                    timeout=10 if is_sensor else 5)
                expected_type = 'hub' if connection_model == 'H200' else 'camera'
                if device is None:
                    raise ControlError('unreachable')
                if device.model != connection_model or device.device_type.value != expected_type:
                    raise ControlError('device_identity_mismatch')
                original = device.protocol.query
                async def once(request, *args, **kwargs):
                    return await original(request, retry_count=0)
                device.protocol.query = once
                if connection_model == 'H200':

                    install_empty_child_lists_compat(device.protocol)
                # Authenticate identity before inventory or writes.
                response = await device.protocol.query({'getDeviceInfo': {
                    'device_info': {'name': ['basic_info']}}})
                info = response['getDeviceInfo']['device_info']['basic_info']
                if info.get('device_model') != connection_model:
                    raise ControlError('device_identity_mismatch')
                stage = 'state_read'
                if command != 'storage':
                    await device.update()
                if is_sensor:
                    child = select_sensor(device, entry)
                    return {'device': alias, 'model': model, 'name': child.alias,
                            'result': 'read_succeeded',
                            'observation_scope': 'hub_reported_snapshot',
                            'sensor_reachability': 'not_assessed',
                            'hub_snapshot_at': datetime.now(timezone.utc).isoformat(),
                            'radio_freshness': 'unknown',
                            'sensor_updated_at': None,
                            'features': sensor_inventory(child, model)}
                result = await operate(device, model, command, name, value, progress)
                return {'device': alias, 'model': model,
                        'hardware': clean(info.get('hw_version')),
                        'firmware': clean(info.get('sw_version')), **result}
    except BaseException as exc:
        if progress.get('write_started'):
            raise ControlError('write_outcome_unknown') from None
        if isinstance(exc, Exception):
            exc.security_stage = stage
        raise
    finally:
        if device is not None:
            try:
                await asyncio.wait_for(device.disconnect(), 2)
            except Exception:
                pass


# ========================================================================
# CLI
# ========================================================================
"""Standalone CLI; only explicit device commands make network requests."""


import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging




class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ControlError('invalid_arguments')


def parser():
    p = Parser(description='JARVIS security CLI. Smart Actions use TP-Link cloud; no background monitoring.')
    p.add_argument('--json', action='store_true', help='Machine-readable output')
    p.add_argument('--env-file', default=str(ROOT / '.env'))
    p.add_argument('--registry', default=str(ROOT / 'devices.json'))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('devices', help='List configured aliases without network access')
    for command in ('status', 'capabilities', 'storage'):
        s = sub.add_parser(command)
        s.add_argument('device')
    for command in ('set', 'action', 'privacy', 'move'):
        s = sub.add_parser(command)
        s.add_argument('device')
        if command in ('set', 'action'):
            s.add_argument('name', help='Allowlisted SDK feature name; see capabilities')
        if command == 'set':
            s.add_argument('value')
        if command == 'privacy':
            s.add_argument('value', choices=('on', 'off'))
        if command == 'move':
            s.add_argument('name', choices=('left', 'right', 'up', 'down'))
            s.add_argument('--degrees', type=int, default=10, help='One movement request, 1–30 degrees')
        s.add_argument('--confirm', action='store_true', help='Explicit approval for this write')
        if command == 'action':
            s.add_argument('--allow-audible', action='store_true', help='Approve audible alarm test')
    r = sub.add_parser('recording', help='D235 weekly recording plan/status')
    r.add_argument('device')
    r.add_argument('name', choices=('status', 'continuous', 'events', 'schedule'), default='status', nargs='?')
    r.add_argument('--schedule-file', help='JSON object with all seven weekday arrays')
    r.add_argument('--confirm', action='store_true')
    for command in ('recordings', 'clip'):
        r = sub.add_parser(command, help='D235 hub archive index or private bounded clip')
        r.add_argument('device')
        r.add_argument('--start', required=command == 'clip', help='Unix seconds or ISO timestamp with UTC offset')
        r.add_argument('--end', required=command == 'clip', help='Unix seconds or ISO timestamp with UTC offset')
        if command == 'clip':
            r.add_argument('--confirm', action='store_true', help='Approve a private local media download')
    from security_audio import add_parser
    add_parser(sub)
    from security_video import add_parser as add_video_parser
    add_video_parser(sub)
    from security_events import add_parser as add_events_parser
    add_events_parser(sub)
    from security_chime import add_parser as add_chime_parser
    add_chime_parser(sub)
    from security_smart_actions import add_parser as add_smart_parser
    add_smart_parser(sub)
    return p


def control_main(argv=None):
    logging.disable(logging.CRITICAL)
    machine = False
    try:
        args = parser().parse_args(argv)
        machine = args.json
        if args.command == 'devices':
            result = {'result': 'configured', 'devices': {
                k: {'model': v['model']} for k, v in registry(args.registry).items()}}
        elif args.command == 'smart-actions':
            from security_smart_actions import execute_smart_actions
            result = execute_smart_actions(args, adapter=sys.modules[__name__])
        elif args.command == 'chime':
            from security_chime import execute_chime
            result = execute_chime(args, adapter=sys.modules[__name__])
        elif args.command == 'events':
            from security_events import execute_events
            result = execute_events(args, adapter=sys.modules[__name__])
        elif args.command in ('snapshot', 'live'):
            from security_video import execute_video
            result = execute_video(args, adapter=sys.modules[__name__])
        elif args.command == 'audio':
            from security_audio import execute_audio
            result = execute_audio(args, adapter=sys.modules[__name__])
        else:
            value = args.degrees if args.command == 'move' else getattr(args, 'value', None)
            if args.command == 'recording':
                if args.name == 'schedule':
                    if not args.schedule_file:
                        raise ControlError('schedule_file_required')
                    with Path(args.schedule_file).open() as source:
                        text = source.read(16385)
                    if len(text) > 16384:
                        raise ControlError('invalid_weekly_schedule')
                    try:
                        value = json.loads(text)
                    except ValueError:
                        raise ControlError('invalid_weekly_schedule') from None
                elif args.schedule_file:
                    raise ControlError('unexpected_schedule_file')
            elif args.command in ('recordings', 'clip'):
                now = int(time.time())
                value = {'start': args.start if args.start is not None else now - 3600,
                         'end': args.end if args.end is not None else now - 60}
            result = asyncio.run(execute(args.device, args.command,
                name=getattr(args, 'name', None),
                value=value,
                confirm=getattr(args, 'confirm', False),
                audible=getattr(args, 'allow_audible', False),
                env_file=args.env_file, registry_path=args.registry))
        code = 3 if result.get('outcome') == 'unknown' else (2 if result.get('result') == 'error' else 0)
    except ControlError as exc:
        result = {'result': 'error', 'reason': str(exc),
                  'stage': getattr(exc, 'security_stage', 'preflight')}
        code = 3 if str(exc) == 'write_outcome_unknown' else 2
    except KeyboardInterrupt:
        result, code = {'result': 'cancelled'}, 130
    except Exception as exc:
        reason = {'AuthenticationError': 'authentication_failed',
                  'TimeoutError': 'timeout', 'ModuleNotFoundError': 'dependency_unavailable',
                  'PrivateEnvError': 'private_credentials_unavailable',
                  'OSError': 'network_or_local_io_error'}.get(type(exc).__name__, 'operation_failed')
        result, code = {'result': 'error', 'reason': reason,
                        'stage': getattr(exc, 'security_stage', 'unknown')}, 2
    result.update(security_assessment='not_assessed', observed_at=datetime.now(timezone.utc).isoformat())
    if machine or result.get('result') == 'error':
        print(json.dumps(result, indent=2))
    else:
        print('JARVIS security — ' + result['result'])
        print(json.dumps(result, indent=2))
    return code







def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    legacy = {'check-env': check_env_main, 'storage-probe': storage_probe_main}
    if args and args[0] in legacy:
        return legacy[args[0]](args[1:])
    if args and args[0] == 'offline-status':
        previous = sys.argv
        try:
            sys.argv = [previous[0], *args[1:]]
            return offline_status_main()
        finally:
            sys.argv = previous
    if args == ['commission']:
        return commission_main()
    return control_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
