from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from kasa import Discover

from .config import PlugConfig, Settings, normalize_name, write_plug_config


@dataclass(frozen=True)
class PlugStatus:
    name: str
    host: str
    alias: str | None
    model: str | None
    mac: str | None
    is_on: bool | None
    rssi: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "alias": self.alias,
            "model": self.model,
            "mac": self.mac,
            "is_on": self.is_on,
            "rssi": self.rssi,
        }


class SmartPlugController:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def discover(self) -> dict[str, PlugStatus]:
        kwargs = self._primary_auth_kwargs()
        devices = await Discover.discover(
            target=self.settings.discovery_target,
            discovery_timeout=min(self.settings.timeout, 10),
            timeout=self.settings.timeout,
            **kwargs,
        )

        statuses: dict[str, PlugStatus] = {}
        for host, dev in sorted(devices.items()):
            try:
                try:
                    await dev.update()
                except Exception:
                    # Keep partially discovered devices visible; commands can surface errors later.
                    pass
                alias = _safe_get(dev, "alias")
                name = normalize_name(alias or host)
                statuses[name] = _status_from_device(name, host, dev)
            finally:
                await _close_device(dev)
        return statuses

    async def save_discovery(self) -> dict[str, PlugStatus]:
        statuses = await self.discover()
        plugs = {
            name: PlugConfig(name=name, host=status.host)
            for name, status in statuses.items()
        }
        write_plug_config(plugs, self.settings.config_path)
        return statuses

    async def status(self, name_or_host: str) -> PlugStatus:
        name, host = self._resolve(name_or_host)
        last_auth_error: Exception | None = None
        auth_kwargs = self._auth_kwargs_list()
        for index, kwargs in enumerate(auth_kwargs):
            dev = await self._connect(host, kwargs)
            try:
                await dev.update()
                return _status_from_device(name, host, dev)
            except Exception as exc:
                if _is_auth_error(exc) and index < len(auth_kwargs) - 1:
                    last_auth_error = exc
                    continue
                raise
            finally:
                await _close_device(dev)
        if last_auth_error:
            raise last_auth_error
        raise RuntimeError(f"No Kasa device found at {host}")

    async def set_power(self, name_or_host: str, on: bool) -> PlugStatus:
        name, host = self._resolve(name_or_host)
        last_auth_error: Exception | None = None
        auth_kwargs = self._auth_kwargs_list()
        for index, kwargs in enumerate(auth_kwargs):
            dev = await self._connect(host, kwargs)
            try:
                if on:
                    await dev.turn_on()
                else:
                    await dev.turn_off()
                await dev.update()
                return _status_from_device(name, host, dev)
            except Exception as exc:
                if _is_auth_error(exc) and index < len(auth_kwargs) - 1:
                    last_auth_error = exc
                    continue
                raise
            finally:
                await _close_device(dev)
        if last_auth_error:
            raise last_auth_error
        raise RuntimeError(f"No Kasa device found at {host}")

    async def toggle(self, name_or_host: str) -> PlugStatus:
        current = await self.status(name_or_host)
        if current.is_on is None:
            raise RuntimeError(f"Could not read current state for {name_or_host!r}")
        return await self.set_power(name_or_host, not current.is_on)

    async def _connect(self, host: str, auth_kwargs: dict[str, str] | None = None):
        dev = await Discover.discover_single(
            host,
            discovery_timeout=min(self.settings.timeout, 10),
            timeout=self.settings.timeout,
            **(auth_kwargs or self._primary_auth_kwargs()),
        )
        if dev is None:
            raise RuntimeError(f"No Kasa device found at {host}")
        return dev

    def _auth_kwargs_list(self) -> list[dict[str, str]]:
        if self.settings.credentials:
            return [
                {"username": credential.username, "password": credential.password}
                for credential in self.settings.credentials
            ]
        return [self._primary_auth_kwargs()]

    def _primary_auth_kwargs(self) -> dict[str, str]:
        kwargs: dict[str, str] = {}
        if self.settings.username:
            kwargs["username"] = self.settings.username
        if self.settings.password:
            kwargs["password"] = self.settings.password
        return kwargs

    def _resolve(self, name_or_host: str) -> tuple[str, str]:
        key = normalize_name(name_or_host)
        if key in self.settings.plugs:
            plug = self.settings.plugs[key]
            return plug.name, plug.host
        for plug in self.settings.plugs.values():
            if key in plug.aliases:
                return plug.name, plug.host
        # Treat unknown values as direct hosts/IPs.
        return key, name_or_host


async def _close_device(dev: Any) -> None:
    disconnect = getattr(dev, "disconnect", None)
    if disconnect is None:
        return
    try:
        result = disconnect()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        pass


def _is_auth_error(exc: Exception) -> bool:
    if exc.__class__.__name__ == "AuthenticationError":
        return True
    return "Device response did not match our challenge" in str(exc)


def _safe_get(dev: Any, attr: str) -> Any:
    try:
        return getattr(dev, attr)
    except Exception:
        return None


def _status_from_device(name: str, host: str, dev: Any) -> PlugStatus:
    return PlugStatus(
        name=name,
        host=str(_safe_get(dev, "host") or host),
        alias=_safe_get(dev, "alias"),
        model=_safe_get(dev, "model"),
        mac=_safe_get(dev, "mac"),
        is_on=_safe_get(dev, "is_on"),
        rssi=_safe_get(dev, "rssi"),
    )


def run(coro):
    return asyncio.run(coro)
