from __future__ import annotations

import asyncio
from contextlib import contextmanager, ExitStack
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

    async def _prepare_write(self, host: str, expected_host: str | None):
        """Credential fallback is allowed ONLY while performing pre-write reads."""
        auth_kwargs = self._auth_kwargs_list()
        for index, kwargs in enumerate(auth_kwargs):
            dev = None
            try:
                dev = await self._connect(host, kwargs)
                if await dev.update() is False:
                    raise RuntimeError("Plug pre-write refresh was not confirmed")
                self._check_observed_host(dev, expected_host)
                return dev
            except BaseException as exc:
                if dev is not None:
                    await _close_device(dev)
                if isinstance(exc, Exception) and _is_auth_error(exc) and index < len(auth_kwargs) - 1:
                    continue
                raise
        raise RuntimeError("No credentials available for plug control")

    def _write_target(self, name_or_host: str, expected_host: str | None) -> tuple[str, str]:
        name, host = self._resolve(name_or_host)
        if expected_host is not None and (
            not expected_host.strip() or host.strip().lower() != expected_host.strip().lower()
        ):
            raise RuntimeError("Plug identity changed before dispatch; refresh before another change")
        return name, host

    @staticmethod
    def _check_observed_host(dev: Any, expected_host: str | None) -> None:
        if expected_host is None:
            return  # Legacy CLI has no admitted cache identity to bind.
        observed = _safe_get(dev, "host")
        if not isinstance(observed, str) or observed.strip().lower() != expected_host.strip().lower():
            raise RuntimeError("Observed plug identity does not match the admitted target")

    async def _write_connected(self, dev: Any, name: str, host: str, on: bool,
                               expected_host: str | None) -> PlugStatus:
        # Never catch an error here to retry credentials or the mutation. Even
        # an auth-classified failure after this point may follow delivery.
        with _single_attempt_write(dev, on):
            if on:
                await dev.turn_on()
            else:
                await dev.turn_off()
        if await dev.update() is False:
            raise RuntimeError("Plug write verification was not confirmed; outcome is uncertain")
        self._check_observed_host(dev, expected_host)
        result = _status_from_device(name, host, dev)
        if result.is_on is not on:
            raise RuntimeError("Plug did not report the requested state; outcome is uncertain")
        return result

    async def set_power(self, name_or_host: str, on: bool, *, expected_host: str | None = None) -> PlugStatus:
        name, host = self._write_target(name_or_host, expected_host)
        dev = await self._prepare_write(host, expected_host)
        try:
            return await self._write_connected(dev, name, host, on, expected_host)
        finally:
            await _close_device(dev)

    async def toggle(self, name_or_host: str, *, expected_host: str | None = None) -> PlugStatus:
        # Resolve, observe and mutate the same connection, not status() followed
        # by a second resolution/connection. Other controllers can still race us.
        name, host = self._write_target(name_or_host, expected_host)
        dev = await self._prepare_write(host, expected_host)
        try:
            current = _safe_get(dev, "is_on")
            if not isinstance(current, bool):
                raise RuntimeError("Could not read a definite plug state before toggle")
            return await self._write_connected(dev, name, host, not current, expected_host)
        finally:
            await _close_device(dev)

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


# Audited installed PR build, not merely its reused 0.10.2 version string.
# Re-audit and run the offline SDK gate before accepting a dependency change.
_AUDITED_SOURCE_SHA256 = {'aiohttp/client.py': 'a5467752c13ae51bf5731a8e3997d5f8b44ab1c0c54b11a906e878ff3cc31701',
 'aiohttp/client_reqrep.py': '456c97cee222d0d11335eb8d00331b58f19dfa6c5ca552ec550334379f36a54f',
 'kasa/httpclient.py': 'b5bf3266306d06e6ef7ceb55d85fc6afcaaf1e415c5ec01cf23e66cada226f64',
 'kasa/iot/iotdevice.py': '605f92e7c6a853e04c2e9a82a6286f92fe7988e3c13731691507f73ae63cc160',
 'kasa/iot/iotplug.py': 'ac027ee415d4b1c0daaf6e8542656aaf3a17f81a93621c4220baa5b142c9bf3c',
 'kasa/protocols/iotprotocol.py': '5b8abc4a7593712b0655b6412ca1836846757018066c8cb974e16673b9b1358e',
 'kasa/protocols/smartprotocol.py': '373a4a62462699ed7da76890009b82076a976d36f00d6be30c1c992ee211f122',
 'kasa/smart/smartdevice.py': '50e399c85a5a53b8976ebe55496ecf5212f389d83619bfc248bdc14c68397d6c',
 'kasa/transports/aestransport.py': 'a959961b82538b455ac38f22c45060195bca0d37e0eec0cfd258d9e7c5ab0f65',
 'kasa/transports/klaptransport.py': '25a3f4592d60ea2f0b587ecb9d9e3a4ea51b1c0519512a84e9cd77036ef83784',
 'kasa/transports/xortransport.py': 'b762263dc648336315f44133792dd19c9c6271d100bf4d3d1cfd0a377937a11c'}


def _require_reviewed_kasa_stack() -> None:
    import hashlib
    import importlib.metadata
    from pathlib import Path
    import aiohttp
    import kasa

    if (importlib.metadata.version("python-kasa"), aiohttp.__version__) != ("0.10.2", "3.14.3"):
        raise RuntimeError("Unaudited plug SDK stack; writes disabled pending review")
    roots = {"kasa": Path(kasa.__file__).parent, "aiohttp": Path(aiohttp.__file__).parent}
    for name, expected in _AUDITED_SOURCE_SHA256.items():
        package, relative = name.split("/", 1)
        try:
            actual = hashlib.sha256((roots[package] / relative).read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError("Plug SDK source audit unavailable; writes disabled") from exc
        if actual != expected:
            raise RuntimeError("Plug SDK source changed; writes disabled pending review")


@contextmanager
def _temporary_attribute(obj: Any, name: str, value: Any):
    absent = object()
    previous = vars(obj).get(name, absent)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if previous is absent:
            delattr(obj, name)
        else:
            setattr(obj, name, previous)


@contextmanager
def _single_attempt_write(dev: Any, on: bool):
    """Connection-local guards around the mutation only, never global patches.

    A failed attempt is consumed even when delivery is unknown. Reads before/
    after this context retain their existing retry policy. This is not a claim
    about device execution, other writers, or lower-level packet retransmission.
    """
    _require_reviewed_kasa_stack()
    import aiohttp
    from kasa.httpclient import HttpClient
    from kasa.iot import IotPlug
    from kasa.smart import SmartDevice
    from kasa.protocols import IotProtocol, SmartProtocol
    from kasa.transports import AesTransport, KlapTransport, KlapTransportV2, XorTransport
    from kasa.transports.aestransport import TransportState

    protocol = getattr(dev, "protocol", None)
    transport = getattr(protocol, "_transport", None)
    allowed = {IotProtocol: (XorTransport, KlapTransport, KlapTransportV2),
               SmartProtocol: (AesTransport, KlapTransport, KlapTransportV2)}
    device_types = {IotProtocol: IotPlug, SmartProtocol: SmartDevice}
    if (type(on) is not bool or type(transport) not in allowed.get(type(protocol), ())
            or type(dev) is not device_types.get(type(protocol))):
        raise RuntimeError("Unsupported plug write device/protocol/transport; no write attempted")
    # Reject nested guards/custom protocol methods, including child wrappers.
    for obj, name in ((dev, "turn_on" if on else "turn_off"),
                      (protocol, "query"), (transport, "send")):
        if getattr(getattr(obj, name), "__func__", None) is not getattr(type(obj), name):
            raise RuntimeError("Nonstandard plug write connection; no write attempted")
    expected = ({"system": {"set_relay_state": {"state": int(on)}}}
                if type(protocol) is IotProtocol else {"set_device_info": {"device_on": on}})
    query, send = protocol.query, transport.send
    attempts = {"query": 0, "send": 0}
    query_completed = False

    def consume(kind):
        attempts[kind] += 1  # Before awaiting: failures/cancellation cannot refund it.
        if attempts[kind] != 1:
            raise RuntimeError("Additional plug write attempt blocked; outcome is uncertain")

    async def query_once(request, retry_count=3):
        nonlocal query_completed
        if request != expected:
            raise RuntimeError("Unexpected plug mutation payload blocked; outcome may be uncertain")
        consume("query")
        result = await query(request, retry_count=0)
        query_completed = True
        return result

    async def send_once(request):
        consume("send")
        return await send(request)

    with ExitStack() as stack:
        if type(transport) is not XorTransport:
            http = transport._http_client
            if type(http) is not HttpClient or http._config.http_client is not None:
                raise RuntimeError("Nonstandard plug HTTP client; no write attempted")
            if type(transport) is AesTransport:
                ready = transport._state is TransportState.ESTABLISHED
                endpoint = transport._token_url or transport._app_url
            else:
                ready = transport._handshake_done
                endpoint = transport._request_url
            if not ready or transport._handshake_session_expired() or transport._encryption_session is None:
                raise RuntimeError("Plug session expired before write; refresh before another change")
            session = http.client
            if (type(session) is not aiohttp.ClientSession or session.closed
                    or session._middlewares or session._trace_configs
                    or type(getattr(session, "_retry_connection", None)) is not bool
                    or getattr(session.post, "__func__", None) is not aiohttp.ClientSession.post):
                raise RuntimeError("Nonstandard plug HTTP session; no write attempted")
            post = session.post
            attempts["post"] = 0

            def post_once(url, **kwargs):
                if url != endpoint:
                    raise RuntimeError("Plug write endpoint change blocked; outcome may be uncertain")
                consume("post")
                kwargs["allow_redirects"] = False
                return post(url, **kwargs)

            stack.enter_context(_temporary_attribute(session, "post", post_once))
            stack.enter_context(_temporary_attribute(session, "_retry_connection", False))
        stack.enter_context(_temporary_attribute(protocol, "query", query_once))
        stack.enter_context(_temporary_attribute(transport, "send", send_once))
        yield
        if any(count != 1 for count in attempts.values()):
            raise RuntimeError("Plug mutation was not submitted through the guarded path")
        if not query_completed:
            raise RuntimeError("Plug mutation result was not confirmed; outcome is uncertain")


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
