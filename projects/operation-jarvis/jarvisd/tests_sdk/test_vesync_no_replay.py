"""Actual SDK and synthetic loopback cloud. Never loads private settings/auth."""
import asyncio
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get("JARVIS_TEST_VENDOR_ROOT", str(Path(__file__).resolve().parents[2])))
assert (ROOT / "air-purifier/air_purifier/write_safety.py").is_file(), "Candidate vendor sources required"
sys.path.insert(0, str(ROOT / "air-purifier"))
from air_purifier import write_safety as policy, vesync_client as wrapper
assert Path(policy.__file__).resolve() == (ROOT / "air-purifier/air_purifier/write_safety.py").resolve()
from air_purifier.config import Settings
from air_purifier.cooldown import cloud_request, CooldownError
import aiohttp
from aiohttp import web
from pyvesync import VeSync
from pyvesync.auth import VeSyncAuth
from pyvesync.const import DeviceStatus
from pyvesync.device_map import get_purifier
from pyvesync.devices.vesyncpurifier import VeSyncAirBaseV2
from pyvesync.models.vesync_models import ResponseDeviceDetailsModel
from pyvesync.utils.helpers import Timer
from pyvesync.utils.errors import VeSyncTokenError, VeSyncRateLimitError


class VeSyncGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        original = socket.socket.connect
        original_ex = socket.socket.connect_ex
        def connect(sock, address):
            if sock.type != socket.SOCK_STREAM or not isinstance(address, tuple) or address[0] != "127.0.0.1":
                raise AssertionError("Non-loopback access forbidden")
            return original(sock, address)
        def connect_ex(sock, address):
            if sock.type != socket.SOCK_STREAM or not isinstance(address, tuple) or address[0] != "127.0.0.1":
                raise AssertionError("Non-loopback access forbidden")
            return original_ex(sock, address)
        for patch in (mock.patch.object(socket.socket, "connect", connect),
                      mock.patch.object(socket.socket, "connect_ex", connect_ex),
                      mock.patch.object(socket.socket, "sendto", side_effect=AssertionError("No UDP")),
                      mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")),
                      mock.patch.object(VeSync, "get_devices", side_effect=AssertionError("No discovery")),
                      mock.patch.object(VeSyncAuth, "load_credentials_from_file", side_effect=AssertionError("No credentials")),
                      mock.patch.object(VeSyncAuth, "save_credentials_to_file", side_effect=AssertionError("No credentials")),
                      mock.patch("air_purifier.config.load_settings", side_effect=AssertionError("No private config"))):
            patch.start()
            self.addCleanup(patch.stop)
        self.mode = "ok"
        self.calls = []
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.status = dict(powerSwitch=0, filterLifePercent=99, workMode="auto", manualSpeedLevel=2,
            fanSpeedLevel=2, AQLevel=1, PM25=1, screenState=0, childLockSwitch=0, screenSwitch=0,
            lightDetectionSwitch=0, environmentLightState=0, scheduleCount=0, timerRemain=0,
            efficientModeTimeRemain=0, errorCode=0)
        async def handler(request):
            body = await request.json()
            self.calls.append((request.path, body))
            self.reached.set()
            if self.mode == "drop":
                request.transport.close()
                return web.Response()
            if self.mode == "wait":
                await self.release.wait()
            if self.mode == "token" or (self.mode == "token-once" and len(self.calls) == 1):
                return web.json_response({"code": -11001000})
            if self.mode == "rate":
                return web.json_response({"code": -11003000})
            if self.mode == "server":
                return web.json_response({"code": -11103000})
            if self.mode == "device-error":
                return web.json_response({"code": 0, "result": {"code": 11}})
            if self.mode == "malformed":
                return web.json_response({})
            if isinstance(self.mode, int) and request.path != "/redirect":
                return web.Response(status=self.mode, headers={"Location": "/redirect"})
            method = body["payload"]["method"]
            if method == "getPurifierStatus":
                data = {} if self.mode == "bad-observation" else self.status
                return web.json_response({"code": 0, "result": {"code": 0, "result": data}})
            if method == "getTimer":
                data = {} if self.mode == "bad-observation" else {"timers": []}
                return web.json_response({"code": 0, "result": {"code": 0, "result": data}})
            # Match the installed SDK's acknowledgement/parser contracts.
            return web.json_response({"code": 0, "id": 7})
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app, shutdown_timeout=0.01)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
        patch = mock.patch("pyvesync.vesync.REGION_API_MAP", {"US": self.url})
        patch.start()
        self.addCleanup(patch.stop)
        self.target = await self.device()
        self.manager = self.target.manager

    async def asyncTearDown(self):
        self.release.set()

    async def device(self, cid="fixture-cid"):
        manager = VeSync("fixture@example.invalid", "fixture-password", country_code="CA", redact=True)
        manager.auth.set_credentials("fixture-token", "fixture-account", "CA", "US")
        manager.enabled = True
        manager.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.15))
        manager._close_session = True
        self.addAsyncCleanup(manager.__aexit__)
        details = ResponseDeviceDetailsModel(deviceRegion="US", isOwner=True, deviceName="Fixture", cid=cid,
            connectionType="wifi", deviceType="LAP-V201S-AASR", type="wifi", configModule="fixture-module",
            deviceStatus="off", connectionStatus="online")
        target = VeSyncAirBaseV2(details, manager, get_purifier(details.deviceType))
        # Model a completed observation, not raw discovery's string fields.
        target.state.device_status = DeviceStatus.OFF
        target.state.display_set_status = DeviceStatus.OFF
        target.state.light_detection_status = DeviceStatus.OFF
        target.state.light_detection_switch = DeviceStatus.OFF
        return target

    async def write(self, method="turn_on", *args, **kwargs):
        return await policy.execute_write(self.target, method, *args, expected_cid="fixture-cid", **kwargs)

    def restored(self):
        self.assertIs(self.target.manager, self.manager)
        self.assertNotIn("request", vars(self.manager.session))
        self.assertTrue(self.manager.session._retry_connection)

    def controller(self):
        controller = wrapper.AirPurifierController(Settings(None, None, "CA", "America/Toronto", None,
            0, Path("/synthetic/auth"), {}), expected_cid="fixture-cid")
        @contextlib.asynccontextmanager
        async def session():
            try:
                yield self.manager
            finally:
                await self.manager.__aexit__()
        controller._session = session
        controller._resolve_device = mock.AsyncMock(return_value=self.target)
        return controller

    async def test_reviewed_sources_and_import_locations(self):
        policy.require_reviewed_stack()
        self.assertEqual(self.calls, [])

    async def test_unguarded_token_error_reproduces_mutation_replay(self):
        self.mode = "token-once"
        with mock.patch.object(VeSync, "_reauthenticate", new_callable=mock.AsyncMock, return_value=True) as auth:
            self.assertTrue(await self.target.turn_on())
            auth.assert_awaited_once()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][1], self.calls[1][1])

    async def test_token_error_does_not_reauthenticate_or_replay(self):
        self.mode = "token"
        with mock.patch.object(VeSync, "_reauthenticate", new_callable=mock.AsyncMock) as auth:
            with self.assertRaises(VeSyncTokenError):
                await self.write()
            auth.assert_not_awaited()
        self.assertEqual(len(self.calls), 1)
        self.restored()

    async def test_unguarded_redirect_reproduces_second_post(self):
        self.mode = 307
        self.assertTrue(await self.target.turn_on())
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][0], "/redirect")

    async def test_redirects_blocked_and_restored(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.mode = status
                before = len(self.calls)
                with self.assertRaises(Exception):
                    await self.write()
                self.assertEqual(len(self.calls) - before, 1)
                self.assertNotEqual(self.calls[-1][0], "/redirect")
                self.restored()

    async def test_existing_setters_submit_matching_payload_once(self):
        cases = [("turn_on", (), {}, "setSwitch"), ("turn_off", (), {}, "setSwitch"),
            ("toggle_switch", (None,), {}, "setSwitch"),
            ("set_mode", ("auto",), {}, "setPurifierMode"), ("set_mode", ("sleep",), {}, "setPurifierMode"),
            ("set_mode", ("pet",), {}, "setPurifierMode"), ("set_mode", ("manual",), {}, "setLevel"),
            ("set_fan_speed", (4,), {}, "setLevel"), ("turn_on_display", (), {}, "setDisplay"),
            ("turn_off_display", (), {}, "setDisplay"), ("turn_on_child_lock", (), {}, "setChildLock"),
            ("turn_off_child_lock", (), {}, "setChildLock"), ("turn_on_light_detection", (), {}, "setLightDetection"),
            ("turn_off_light_detection", (), {}, "setLightDetection"),
            ("set_auto_preference", ("quiet",), {"room_size": 600}, "setAutoPreference"),
            ("set_timer", (300,), {}, "addTimerV2"), ("clear_timer", (), {}, "delTimerV2")]
        for method, args, kwargs, payload_method in cases:
            with self.subTest(method=method, args=args):
                self.target.state.device_status = DeviceStatus.ON if method == "turn_off" else DeviceStatus.OFF
                self.target.state.display_set_status = DeviceStatus.ON if method == "turn_off_display" else DeviceStatus.OFF
                self.target.state.light_detection_status = DeviceStatus.ON if method == "turn_off_light_detection" else DeviceStatus.OFF
                self.target.state.light_detection_switch = self.target.state.light_detection_status
                self.target.state.timer = Timer(300, "off", id=7)
                before = len(self.calls)
                self.assertTrue(await self.write(method, *args, **kwargs))
                self.assertEqual(len(self.calls) - before, 1)
                self.assertEqual(self.calls[-1][1]["payload"]["method"], payload_method)
                self.assertEqual(self.calls[-1][1]["cid"], "fixture-cid")
                self.restored()

    async def test_recognized_noop_does_not_claim_a_sent_request(self):
        self.target.state.device_status = DeviceStatus.ON
        self.assertTrue(await self.write())
        self.assertEqual(self.calls, [])
        self.restored()

    async def test_ambient_light_skip_cannot_confirm_wrong_switch(self):
        self.target.state.light_detection_status = DeviceStatus.ON
        self.target.state.light_detection_switch = DeviceStatus.OFF
        with self.assertRaises(policy.WriteSafetyError):
            await self.write("turn_on_light_detection")
        self.assertEqual(self.calls, [])
        self.restored()

    async def test_loss_and_timeout_never_resend(self):
        for mode in ("drop", "wait"):
            with self.subTest(mode=mode):
                self.mode = mode
                before = len(self.calls)
                with self.assertRaises(Exception):
                    await self.write()
                self.assertEqual(len(self.calls) - before, 1)
                self.restored()

    async def test_cancel_after_send_restores_without_replay(self):
        self.mode = "wait"
        task = asyncio.create_task(self.write())
        await asyncio.wait_for(self.reached.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.calls), 1)
        self.restored()

    async def test_rate_limit_preserves_existing_account_backoff(self):
        self.mode = "rate"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth"
            with self.assertRaises(VeSyncRateLimitError):
                with cloud_request(path):
                    await self.write()
            self.assertTrue((path.parent / ".vesync_cooldown").is_file())
            with self.assertRaises(CooldownError):
                with cloud_request(path):
                    self.fail("Cloud operation must not start during cooldown")
        self.assertEqual(len(self.calls), 1)
        self.restored()

    async def test_http_429_preserves_account_backoff(self):
        self.mode = 429
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth"
            with self.assertRaises(VeSyncRateLimitError):
                with cloud_request(path):
                    await self.write()
            self.assertTrue((path.parent / ".vesync_cooldown").is_file())
        self.assertEqual(len(self.calls), 1)
        self.restored()

    async def test_server_device_and_malformed_errors_never_replay_or_confirm(self):
        for mode in ("server", "device-error", "malformed"):
            self.mode = mode
            before = len(self.calls)
            with self.subTest(mode=mode), self.assertRaises(Exception):
                await self.write()
            self.assertEqual(len(self.calls) - before, 1)
            self.restored()

    async def test_version_or_source_drift_fail_closed(self):
        for patch in (mock.patch.object(importlib.metadata, "version", return_value="changed"),
                      mock.patch.object(Path, "read_bytes", return_value=b"changed"),
                      mock.patch.object(Path, "read_bytes", side_effect=OSError())):
            with patch, self.assertRaises(policy.WriteSafetyError):
                await self.write()
        self.assertEqual(self.calls, [])
        self.restored()

    async def test_identity_mismatch_before_mutation(self):
        with self.assertRaises(policy.WriteSafetyError):
            await policy.execute_write(self.target, "turn_on", expected_cid="different")
        self.assertEqual(self.calls, [])

    async def test_unknown_model_and_operation_fail_closed(self):
        with self.assertRaises(policy.WriteSafetyError):
            await self.write("reset_filter")
        self.target.device_type = "unreviewed"
        with self.assertRaises(policy.WriteSafetyError):
            await self.write()
        self.assertEqual(self.calls, [])

    async def test_external_session_or_middleware_rejects(self):
        self.manager._close_session = False
        with self.assertRaises(policy.WriteSafetyError):
            await self.write()
        self.manager._close_session = True
        self.manager.session._middlewares = (object(),)
        try:
            with self.assertRaises(policy.WriteSafetyError):
                await self.write()
        finally:
            self.manager.session._middlewares = ()
        self.assertEqual(self.calls, [])

    async def test_other_manager_is_not_patched(self):
        other = await self.device("other-cid")
        original = VeSyncAirBaseV2.turn_on
        async def inspect(target):
            self.assertNotIn("request", vars(other.manager.session))
            self.assertTrue(other.manager.session._retry_connection)
            return await original(target)
        with mock.patch.object(VeSyncAirBaseV2, "turn_on", inspect):
            self.assertTrue(await self.write())
        self.restored()

    async def test_read_token_recovery_is_unchanged(self):
        self.mode = "token-once"
        with mock.patch.object(VeSync, "_reauthenticate", new_callable=mock.AsyncMock, return_value=True) as auth:
            await policy.observe(self.target)
            auth.assert_awaited_once()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(body["payload"]["method"] == "getPurifierStatus" for _, body in self.calls))
        self.restored()

    async def test_optimistic_sdk_state_is_not_confirmation(self):
        await self.write()
        self.assertTrue(self.target.is_on)  # SDK optimistically changes local state.
        self.mode = "bad-observation"
        with self.assertRaises(policy.WriteSafetyError):
            await policy.observe(self.target)
        self.assertEqual(len(self.calls), 2)
        self.restored()

    async def test_complete_observation_clears_optimistic_timer(self):
        self.target.state.timer = Timer(300, "off")
        await policy.observe(self.target)
        self.assertIsNone(self.target.state.timer)
        self.assertFalse(self.target.is_on)
        self.restored()

    async def test_timer_read_rejects_missing_list(self):
        self.mode = "bad-observation"
        with self.assertRaises(policy.WriteSafetyError):
            await policy.observe(self.target, timer=True)
        self.restored()

    async def test_controller_acceptance_waits_for_valid_matching_observation(self):
        self.status["workMode"] = "sleep"
        result = await self.controller().set_mode("sleep", "fixture-cid")
        self.assertFalse(result.verification_pending)
        self.assertTrue(result.write_accepted)
        self.assertEqual([body["payload"]["method"] for _, body in self.calls], ["setPurifierMode", "getPurifierStatus"])
        self.assertTrue(self.manager.session.closed)
        self.restored()

    async def test_controller_valid_mismatch_stays_pending_without_second_write(self):
        result = await self.controller().set_mode("sleep", "fixture-cid")
        self.assertTrue(result.verification_pending)
        self.assertEqual([body["payload"]["method"] for _, body in self.calls], ["setPurifierMode", "getPurifierStatus"])
        self.assertTrue(self.manager.session.closed)

    async def test_controller_malformed_observation_raises_and_closes(self):
        self.mode = "bad-observation"
        with self.assertRaises(policy.WriteSafetyError):
            await self.controller().set_mode("sleep", "fixture-cid")
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.manager.session.closed)
        self.restored()

    async def test_controller_token_failure_closes_without_verification(self):
        self.mode = "token"
        with self.assertRaises(VeSyncTokenError):
            await self.controller().set_mode("sleep", "fixture-cid")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.manager.session.closed)
        self.restored()

    async def test_extra_api_and_http_attempts_are_blocked(self):
        for layer in ("api", "http"):
            with self.subTest(layer=layer):
                self.target.state.device_status = DeviceStatus.OFF
                before = len(self.calls)
                original = VeSyncAirBaseV2.turn_on
                async def repeat(target):
                    await original(target)
                    if layer == "api":
                        return await target.call_bypassv2_api("setSwitch", {"powerSwitch": 1, "switchIdx": 0})
                    body = self.calls[-1][1]
                    async with target.manager.session.request("post", url=target.manager.url, json=body):
                        pass
                    return True
                with mock.patch.object(VeSyncAirBaseV2, "turn_on", repeat), self.assertRaises(policy.WriteSafetyError):
                    await self.write()
                self.assertEqual(len(self.calls) - before, 1)
                self.restored()

    async def test_wrong_cid_or_action_payload_never_reaches_http(self):
        for method, data in (("setSwitch", {"powerSwitch": 0, "switchIdx": 0}), ("resetFilter", {})):
            async def wrong(target):
                return await target.call_bypassv2_api(method, data)
            with mock.patch.object(VeSyncAirBaseV2, "turn_on", wrong), self.assertRaises(policy.WriteSafetyError):
                await self.write()
        original = VeSyncAirBaseV2.turn_on
        async def changed(target):
            target.cid = "different-private-cid"
            return await original(target)
        with mock.patch.object(VeSyncAirBaseV2, "turn_on", changed), self.assertRaises(policy.WriteSafetyError):
            await self.write()
        self.assertEqual(self.calls, [])
        self.restored()

    async def test_swallowed_failure_cannot_report_success(self):
        self.mode = "drop"
        original = VeSyncAirBaseV2.turn_on
        async def swallow(target):
            try:
                await original(target)
            except Exception:
                pass
            return True
        with mock.patch.object(VeSyncAirBaseV2, "turn_on", swallow), self.assertRaises(policy.WriteSafetyError):
            await self.write()
        self.assertEqual(len(self.calls), 1)
        self.restored()

    async def test_disabled_http_retry_flag_remains_disabled(self):
        self.manager.session._retry_connection = False
        await self.write()
        self.assertFalse(self.manager.session._retry_connection)
        self.assertNotIn("request", vars(self.manager.session))

    async def test_raw_discovery_string_is_not_a_confirmed_noop(self):
        self.target.state.device_status = "off"  # bool('off') is True in SDK skip logic.
        with self.assertRaises(policy.WriteSafetyError):
            await self.write()
        self.assertEqual(self.calls, [])

    async def test_controller_power_preparation_fixes_raw_discovery_skip(self):
        self.target.state.device_status = "off"
        result = await self.controller().set_power(True, "fixture-cid")
        self.assertTrue(result.verification_pending)
        self.assertEqual([body["payload"]["method"] for _, body in self.calls],
                         ["getPurifierStatus", "setSwitch", "getPurifierStatus"])
        self.assertTrue(self.manager.session.closed)

    async def test_failed_timer_preparation_cannot_delete_cached_timer(self):
        self.target.state.timer = Timer(300, "off", id=7)
        self.mode = "bad-observation"
        with self.assertRaises(policy.WriteSafetyError):
            await self.controller().clear_timer("fixture-cid")
        self.assertEqual([body["payload"]["method"] for _, body in self.calls], ["getTimer"])
        self.assertTrue(self.manager.session.closed)

    async def test_normal_status_rejects_sdk_silent_parse_failure(self):
        self.mode = "bad-observation"
        with self.assertRaises(policy.WriteSafetyError):
            await self.controller().status("fixture-cid")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.manager.session.closed)

    async def test_batch_status_marks_malformed_observation_failed(self):
        self.mode = "bad-observation"
        controller = self.controller()
        controller._purifiers = mock.AsyncMock(return_value=[self.target])
        result = await controller.status_all()
        self.assertFalse(result["fixture-cid"]["ok"])
        self.assertEqual(result["fixture-cid"]["error"], "Device status refresh failed")
        self.assertEqual(len(self.calls), 1)

    async def test_normal_status_requires_a_new_response_object(self):
        await self.target.update()
        with mock.patch.object(VeSyncAirBaseV2, "update", new_callable=mock.AsyncMock), self.assertRaises(policy.WriteSafetyError):
            await self.controller().status("fixture-cid")
        self.assertEqual(len(self.calls), 1)

    async def test_normal_status_accepts_valid_observation_without_write_gate(self):
        with mock.patch.object(policy, "require_reviewed_stack", side_effect=AssertionError("Read must not invoke write gate")):
            result = await self.controller().status("fixture-cid")
        self.assertFalse(result.is_on)
        self.assertEqual(len(self.calls), 1)

    async def test_network_tripwires(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            with self.assertRaises(AssertionError):
                sock.connect(("192.0.2.1", 80))
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("fixture.invalid", 443)


if __name__ == "__main__":
    unittest.main(verbosity=2)
