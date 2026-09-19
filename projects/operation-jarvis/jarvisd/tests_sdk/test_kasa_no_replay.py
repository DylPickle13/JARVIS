"""Real SDK policy tests. Only synthetic loopback peers; no vendor configuration.

Run via ../verify-kasa-sdk.sh using the installed smart-plug interpreter. Crypto
sessions are synthetic; protocol/transport/HTTP retry paths are the actual SDK.
"""
import asyncio
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
import types
import unittest
from unittest import mock

ROOT = Path(os.environ.get("JARVIS_TEST_VENDOR_ROOT", str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(ROOT / "smart-plug"))
import smart_plug.kasa_client as wrapper
import aiohttp
from aiohttp import web
from kasa import Discover
from kasa.deviceconfig import DeviceConfig
from kasa.exceptions import KasaException
from kasa.iot import IotPlug
from kasa.protocols import IotProtocol, SmartProtocol
from kasa.protocols.smartprotocol import SMART_RETRYABLE_ERRORS, SMART_AUTHENTICATION_ERRORS
from kasa.smart import SmartDevice
from kasa.transports import XorTransport, XorEncryption, KlapTransport, KlapTransportV2, AesTransport
from kasa.transports.aestransport import TransportState


class NoReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Numeric loopback TCP only. A bug must not become a device/cloud probe.
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        def guard_connect(sock, address):
            if sock.type != socket.SOCK_STREAM or not isinstance(address, tuple) or address[0] != "127.0.0.1":
                raise AssertionError("Non-loopback network access forbidden in SDK tests")
            return original_connect(sock, address)
        def guard_connect_ex(sock, address):
            if sock.type != socket.SOCK_STREAM or not isinstance(address, tuple) or address[0] != "127.0.0.1":
                raise AssertionError("Non-loopback network access forbidden in SDK tests")
            return original_connect_ex(sock, address)
        for patch in (mock.patch.object(socket.socket, "connect", guard_connect),
                      mock.patch.object(socket.socket, "connect_ex", guard_connect_ex),
                      mock.patch.object(socket.socket, "sendto", side_effect=AssertionError("No UDP/discovery")),
                      mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
                      mock.patch.object(Discover, "discover", side_effect=AssertionError("No discovery")),
                      mock.patch.object(Discover, "discover_single", side_effect=AssertionError("No discovery")),
                      mock.patch("smart_plug.config.load_settings", side_effect=AssertionError("No private config"))):
            patch.start()
            self.addCleanup(patch.stop)
        self.received = []
        self.mode = "ok"
        self.received_event = asyncio.Event()
        self.release = asyncio.Event()
        self.addAsyncCleanup(self.unblock)

    async def unblock(self):
        self.release.set()

    async def http_device(self, protocol=IotProtocol, transport=KlapTransportV2):
        async def handler(request):
            payload = await request.read()
            self.received.append((request.method, request.path, payload))
            self.received_event.set()
            if self.mode == "drop":
                request.transport.close()
                return web.Response()
            if self.mode == "wait":
                await self.release.wait()
            if isinstance(self.mode, int):
                return web.Response(status=self.mode, headers={"Location": "/redirect-target"})
            body = ({"system": {"set_relay_state": {"err_code": 0}}}
                    if protocol is IotProtocol else {"error_code": 0})
            if self.mode == "retryable":
                body = {"error_code": int(next(iter(SMART_RETRYABLE_ERRORS)))}
            elif self.mode == "auth":
                body = {"error_code": int(next(iter(SMART_AUTHENTICATION_ERRORS)))}
            elif self.mode == "pagination":
                body = {"error_code": 0, "result": {"start_index": 0, "sum": 2, "items": [1]}}
            if transport is AesTransport:
                body = {"error_code": 0, "result": {"response": json.dumps(body)}}
            return web.Response(body=json.dumps(body).encode())
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app, shutdown_timeout=0.01)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        config = DeviceConfig(host="127.0.0.1", port_override=port, timeout=0.2)
        link = transport(config=config)
        # The installed AES transport uses wall time; KLAP uses monotonic time.
        link._session_expire_at = (time.time() if transport is AesTransport else time.monotonic()) + 3600
        if transport is AesTransport:
            link._state = TransportState.ESTABLISHED
            link._encryption_session = types.SimpleNamespace(encrypt=lambda data: data, decrypt=lambda data: data.decode())
        else:
            link._handshake_done = True
            link._encryption_session = types.SimpleNamespace(encrypt=lambda data: (data, 42), decrypt=lambda data: data.decode())
        connection = protocol(transport=link)
        self.addAsyncCleanup(connection.close)
        return (IotPlug if protocol is IotProtocol else SmartDevice)("127.0.0.1", config=config, protocol=connection)

    async def xor_device(self):
        async def handler(reader, writer):
            try:
                length = struct.unpack(">I", await reader.readexactly(4))[0]
                payload = await reader.readexactly(length)
                self.received.append(json.loads(XorEncryption.decrypt(payload)))
                self.received_event.set()
                if self.mode == "wait":
                    await self.release.wait()
                if self.mode != "drop":
                    writer.write(XorEncryption.encrypt(json.dumps({"system": {"set_relay_state": {"err_code": 0}}})))
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        async def close():
            server.close()
            await server.wait_closed()
        self.addAsyncCleanup(close)
        config = DeviceConfig(host="127.0.0.1", port_override=server.sockets[0].getsockname()[1], timeout=0.2)
        protocol = IotProtocol(transport=XorTransport(config=config))
        self.addAsyncCleanup(protocol.close)
        return IotPlug("127.0.0.1", config=config, protocol=protocol)

    async def mutate(self, dev, on=True):
        with wrapper._single_attempt_write(dev, on):
            await (dev.turn_on() if on else dev.turn_off())

    def assert_restored(self, dev):
        self.assertNotIn("query", vars(dev.protocol))
        self.assertNotIn("send", vars(dev.protocol._transport))
        if not isinstance(dev.protocol._transport, XorTransport):
            session = dev.protocol._transport._http_client.client
            self.assertNotIn("post", vars(session))
            self.assertTrue(session._retry_connection)

    async def test_audited_stack_matches_and_guard_is_read_time_only(self):
        wrapper._require_reviewed_kasa_stack()
        self.assertEqual(len(self.received), 0)

    async def test_changed_source_rejects_before_mutation(self):
        dev = await self.xor_device()
        with mock.patch.object(Path, "read_bytes", return_value=b"changed"), self.assertRaisesRegex(RuntimeError, "source changed"):
            await self.mutate(dev)
        self.assertEqual(self.received, [])
        self.assert_restored(dev)

    async def test_changed_version_rejects_before_mutation(self):
        dev = await self.xor_device()
        with mock.patch.object(importlib.metadata, "version", return_value="unreviewed"), self.assertRaisesRegex(RuntimeError, "Unaudited"):
            await self.mutate(dev)
        self.assertEqual(self.received, [])

    async def test_missing_audit_source_rejects_before_mutation(self):
        dev = await self.xor_device()
        with mock.patch.object(Path, "read_bytes", side_effect=OSError()), self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.mutate(dev)
        self.assertEqual(self.received, [])

    async def test_all_supported_pairs_on_off_and_restoration(self):
        for protocol, transport in ((IotProtocol, XorTransport), (IotProtocol, KlapTransport),
                (IotProtocol, KlapTransportV2), (SmartProtocol, KlapTransport),
                (SmartProtocol, KlapTransportV2), (SmartProtocol, AesTransport)):
            for on in (True, False):
                with self.subTest(protocol=protocol.__name__, transport=transport.__name__, on=on):
                    dev = await (self.xor_device() if transport is XorTransport else self.http_device(protocol, transport))
                    before = len(self.received)
                    await self.mutate(dev, on)
                    self.assertEqual(len(self.received) - before, 1)
                    self.assert_restored(dev)
                    await dev.disconnect()

    async def test_response_loss_never_resends_xor_or_http(self):
        self.mode = "drop"
        for protocol, transport in ((IotProtocol, XorTransport), (IotProtocol, KlapTransportV2),
                                    (SmartProtocol, AesTransport), (SmartProtocol, KlapTransport)):
            with self.subTest(protocol=protocol.__name__, transport=transport.__name__):
                dev = await (self.xor_device() if transport is XorTransport else self.http_device(protocol, transport))
                before = len(self.received)
                with self.assertRaises(KasaException):
                    await self.mutate(dev)
                self.assertEqual(len(self.received) - before, 1)
                self.assert_restored(dev)
                await dev.disconnect()

    async def test_http_redirects_are_not_followed(self):
        for status in (301, 302, 303, 307, 308):
            for protocol, transport in ((IotProtocol, KlapTransportV2), (SmartProtocol, AesTransport)):
                with self.subTest(status=status, transport=transport.__name__):
                    self.mode = status
                    dev = await self.http_device(protocol, transport)
                    before = len(self.received)
                    with self.assertRaises(KasaException):
                        await self.mutate(dev)
                    self.assertEqual(len(self.received) - before, 1)
                    self.assertNotEqual(self.received[-1][1], "/redirect-target")
                    self.assert_restored(dev)
                    await dev.disconnect()

    async def test_retryable_and_auth_failures_do_not_replay_smart(self):
        for mode in ("retryable", "auth"):
            for transport in (KlapTransport, AesTransport):
                with self.subTest(mode=mode, transport=transport.__name__):
                    self.mode = mode
                    dev = await self.http_device(SmartProtocol, transport)
                    before = len(self.received)
                    with self.assertRaises(KasaException):
                        await self.mutate(dev)
                    self.assertEqual(len(self.received) - before, 1)
                    self.assert_restored(dev)
                    await dev.disconnect()

    async def test_klap_security_response_cannot_rehandshake_and_replay(self):
        self.mode = 403
        dev = await self.http_device()
        with self.assertRaises(KasaException):
            await self.mutate(dev)
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_smart_pagination_cannot_resend_mutation(self):
        self.mode = "pagination"
        dev = await self.http_device(SmartProtocol)
        with self.assertRaisesRegex(RuntimeError, "Additional"):
            await self.mutate(dev)
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_timeout_after_delivery_never_replays(self):
        for factory in (self.xor_device, self.http_device):
            self.mode = "wait"
            dev = await factory()
            before = len(self.received)
            with self.assertRaises(KasaException):
                await self.mutate(dev)
            self.assertEqual(len(self.received) - before, 1)
            self.assert_restored(dev)
        self.release.set()

    async def test_cancel_after_delivery_restores_guard_without_replay(self):
        self.mode = "wait"
        dev = await self.http_device()
        task = asyncio.create_task(self.mutate(dev))
        await asyncio.wait_for(self.received_event.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)
        self.release.set()

    async def test_second_device_is_not_patched(self):
        first, second = await self.http_device(), await self.http_device()
        with wrapper._single_attempt_write(first, True):
            self.assertNotIn("query", vars(second.protocol))
            self.assertNotIn("send", vars(second.protocol._transport))
            self.assertNotIn("post", vars(second.protocol._transport._http_client.client))
            await first.turn_on()
        self.assert_restored(first)

    async def test_nested_guards_reject_and_restore_outer(self):
        dev = await self.http_device()
        with wrapper._single_attempt_write(dev, True):
            with self.assertRaisesRegex(RuntimeError, "Nonstandard"):
                with wrapper._single_attempt_write(dev, True):
                    pass
            await dev.turn_on()
        self.assert_restored(dev)

    async def test_additional_sdk_query_is_blocked(self):
        dev = await self.http_device()
        with self.assertRaises(KasaException):
            with wrapper._single_attempt_write(dev, True):
                await dev.turn_on()
                await dev.turn_on()
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_noop_device_method_cannot_claim_submission(self):
        dev = await self.http_device()
        with self.assertRaisesRegex(RuntimeError, "not submitted"):
            with wrapper._single_attempt_write(dev, True):
                pass
        self.assertEqual(self.received, [])
        self.assert_restored(dev)

    async def test_unexpected_payload_fails_before_send(self):
        dev = await self.http_device()
        with self.assertRaises(KasaException):
            with wrapper._single_attempt_write(dev, True):
                await dev.turn_off()
        self.assertEqual(self.received, [])
        self.assert_restored(dev)

    async def test_unsupported_protocol_and_transport_reject(self):
        dev = await self.http_device()
        original = dev.protocol
        for protocol in (types.SimpleNamespace(_transport=original._transport),
                         IotProtocol(transport=types.SimpleNamespace(_host="127.0.0.1"))):
            dev.protocol = protocol
            with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                await self.mutate(dev)
        dev.protocol = original
        self.assertEqual(self.received, [])

    async def test_custom_device_or_power_method_rejected_before_invocation(self):
        dev = await self.http_device()
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            await self.mutate(types.SimpleNamespace(protocol=dev.protocol))
        with mock.patch.object(dev, "turn_on", new_callable=mock.AsyncMock) as mutation:
            with self.assertRaisesRegex(RuntimeError, "Nonstandard"):
                await self.mutate(dev)
            mutation.assert_not_awaited()
        self.assertEqual(self.received, [])
        self.assert_restored(dev)

    async def test_expired_session_never_authenticates_during_write(self):
        dev = await self.http_device()
        dev.protocol._transport._session_expire_at = 0
        with self.assertRaisesRegex(RuntimeError, "expired"):
            await self.mutate(dev)
        self.assertEqual(self.received, [])

    async def test_shared_http_session_rejected(self):
        dev = await self.http_device()
        transport = dev.protocol._transport
        transport._config.http_client = transport._http_client.client
        try:
            with self.assertRaisesRegex(RuntimeError, "HTTP client"):
                await self.mutate(dev)
        finally:
            transport._config.http_client = None
        self.assertEqual(self.received, [])

    async def test_http_middleware_rejected(self):
        dev = await self.http_device()
        session = dev.protocol._transport._http_client.client
        session._middlewares = (object(),)
        try:
            with self.assertRaisesRegex(RuntimeError, "HTTP session"):
                await self.mutate(dev)
        finally:
            session._middlewares = ()
        self.assertEqual(self.received, [])

    async def test_unguarded_sdk_reproduces_four_attempts_on_synthetic_peer(self):
        self.mode = "drop"
        dev = await self.xor_device()
        with self.assertRaises(KasaException):
            await dev.turn_on()  # Deliberately unguarded, loopback-only regression baseline.
        self.assertEqual(len(self.received), 4)

    async def test_explicit_retry_argument_cannot_override_policy(self):
        self.mode = "drop"
        dev = await self.http_device()
        with self.assertRaises(KasaException):
            with wrapper._single_attempt_write(dev, True):
                await dev.protocol.query({"system": {"set_relay_state": {"state": 1}}}, retry_count=99)
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_endpoint_change_cannot_start_authentication_or_redirect(self):
        dev = await self.http_device()
        transport = dev.protocol._transport
        with self.assertRaises(KasaException):
            with wrapper._single_attempt_write(dev, True):
                transport._request_url = transport._app_url / "handshake1"
                await dev.turn_on()
        self.assertEqual(self.received, [])
        self.assert_restored(dev)

    async def test_original_disabled_http_retry_flag_is_preserved(self):
        dev = await self.http_device()
        session = dev.protocol._transport._http_client.client
        session._retry_connection = False
        await self.mutate(dev)
        self.assertFalse(session._retry_connection)
        self.assertNotIn("post", vars(session))

    async def test_network_tripwires_reject_nonloopback_and_dns(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            with self.assertRaisesRegex(AssertionError, "Non-loopback"):
                sock.connect(("192.0.2.1", 9999))
        with self.assertRaisesRegex(AssertionError, "No DNS"):
            socket.getaddrinfo("fixture.invalid", 80)

    async def test_swallowed_sdk_failure_cannot_report_success(self):
        self.mode = "drop"
        dev = await self.http_device()
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            with wrapper._single_attempt_write(dev, True):
                try:
                    await dev.turn_on()
                except KasaException:
                    pass
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_http_budget_blocks_extra_post_without_protocol_resubmission(self):
        dev = await self.http_device()
        transport = dev.protocol._transport
        # Exercise the lower HTTP budget even if a transport tries extra POSTs
        # without re-entering protocol.query/transport.send.
        with self.assertRaises(KasaException):
            with wrapper._single_attempt_write(dev, True):
                await transport._http_client.post(transport._request_url, data=b"synthetic")
                await transport._http_client.post(transport._request_url, data=b"synthetic")
        self.assertEqual(len(self.received), 1)
        self.assert_restored(dev)

    async def test_controller_and_real_sdk_use_guard_and_close_on_response_loss(self):
        from smart_plug.config import Settings, PlugConfig, KasaCredential
        settings = Settings(username=None, password=None,
            credentials=[KasaCredential("a", "fixture-a", "fixture-a"), KasaCredential("b", "fixture-b", "fixture-b")],
            discovery_target="192.0.2.255", timeout=1, config_path=Path("/synthetic/config.json"),
            plugs={"lamp": PlugConfig("lamp", "127.0.0.1")})
        controller = wrapper.SmartPlugController(settings)
        for action in ("on", "off", "toggle"):
            with self.subTest(action=action):
                self.mode = "drop"
                dev = await self.http_device()
                dev._last_update = {"system": {"get_sysinfo": {"relay_state": 0}}}
                dev._sys_info = {"relay_state": 0}
                dev.update = mock.AsyncMock()
                controller._connect = mock.AsyncMock(return_value=dev)
                before = len(self.received)
                with mock.patch.object(dev, "disconnect", wraps=dev.disconnect) as close:
                    with self.assertRaises(KasaException):
                        if action == "toggle":
                            await controller.toggle("lamp", expected_host="127.0.0.1")
                        else:
                            await controller.set_power("lamp", action == "on", expected_host="127.0.0.1")
                    close.assert_awaited_once()
                self.assertEqual(len(self.received) - before, 1)
                controller._connect.assert_awaited_once()
                dev.update.assert_awaited_once()
                self.assertIsNone(dev.protocol._transport._http_client._client_session)
                self.assertNotIn("query", vars(dev.protocol))

    async def test_controller_restores_policy_before_successful_verification(self):
        from smart_plug.config import Settings, PlugConfig
        settings = Settings(username=None, password=None, credentials=[],
            discovery_target="192.0.2.255", timeout=1, config_path=Path("/synthetic/config.json"),
            plugs={"lamp": PlugConfig("lamp", "127.0.0.1")})
        dev = await self.http_device()
        dev._last_update = {"system": {"get_sysinfo": {"relay_state": 0}}}
        dev._sys_info = {"relay_state": 0}
        reads = 0
        async def update():
            nonlocal reads
            self.assert_restored(dev)
            reads += 1
            if reads == 2:
                dev._sys_info["relay_state"] = 1
        dev.update = mock.AsyncMock(side_effect=update)
        controller = wrapper.SmartPlugController(settings)
        controller._connect = mock.AsyncMock(return_value=dev)
        result = await controller.set_power("lamp", True, expected_host="127.0.0.1")
        self.assertTrue(result.is_on)
        self.assertEqual(reads, 2)
        self.assertEqual(len(self.received), 1)
        self.assertIsNone(dev.protocol._transport._http_client._client_session)

    async def test_read_retry_policy_is_restored_after_mutation(self):
        dev = await self.http_device()
        await self.mutate(dev)
        original = dev.protocol._query
        retries = []
        async def record(request, retry_count):
            retries.append(retry_count)
            return {}
        with mock.patch.object(dev.protocol, "_query", record):
            await dev.protocol.query({"system": {"get_sysinfo": {}}})
        self.assertEqual(retries, [3])
        self.assertEqual(dev.protocol._query, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
