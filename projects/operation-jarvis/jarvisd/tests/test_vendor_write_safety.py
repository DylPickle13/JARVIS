"""Failure/identity tests using fake devices only; no SDK or cloud access."""
import asyncio
import contextlib
import io
from pathlib import Path
import types
import unittest
from unittest import mock

from vendor_loader import load_vendor


class AuthenticationError(Exception):
    pass


class PlugWriteSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.m = load_vendor("plug", "kasa_client")
        # SDK-free wrapper tests; the real policy/SDK/transport paths have their
        # own mandatory loopback-only verification gate in tests_sdk/.
        policy = mock.patch.object(self.m, "_single_attempt_write", return_value=contextlib.nullcontext())
        self.policy = policy.start()
        self.addCleanup(policy.stop)
        config = load_vendor("plug", "config")
        self.settings = config.Settings(username=None, password=None,
            credentials=[config.KasaCredential("a", "fixture-a", "fixture-a"),
                         config.KasaCredential("b", "fixture-b", "fixture-b")],
            discovery_target="192.0.2.255", timeout=3, config_path=Path("/synthetic/plugs.json"),
            plugs={"lamp": config.PlugConfig("lamp", "192.0.2.1", ("alias",))})
        self.controller = self.m.SmartPlugController(self.settings)
        self.first, self.second = self.device(), self.device()
        self.controller._connect = mock.AsyncMock(side_effect=[self.first, self.second])

    def device(self):
        device = types.SimpleNamespace(host="192.0.2.1", is_on=False, alias="Fixture", model="Fixture", mac=None, rssi=-50)
        device.update = mock.AsyncMock()
        async def turn_on(): device.is_on = True
        async def turn_off(): device.is_on = False
        device.turn_on = mock.AsyncMock(side_effect=turn_on)
        device.turn_off = mock.AsyncMock(side_effect=turn_off)
        device.disconnect = mock.AsyncMock()
        return device

    async def test_policy_rejection_closes_without_mutation_or_fallback(self):
        self.policy.side_effect = RuntimeError("unaudited SDK stack")
        with self.assertRaisesRegex(RuntimeError, "unaudited"):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_prewrite_authentication_fallback_is_read_only(self):
        self.first.update.side_effect = AuthenticationError("fixture auth failure")
        result = await self.controller.set_power("lamp", True, expected_host="192.0.2.1")
        self.first.turn_on.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()
        self.second.turn_on.assert_awaited_once()
        self.second.disconnect.assert_awaited_once()
        self.assertTrue(result.is_on)
        self.assertEqual(self.controller._connect.await_count, 2)

    async def test_connect_auth_failure_can_try_next_credential_before_write(self):
        self.controller._connect.side_effect = [AuthenticationError("connect"), self.second]
        await self.controller.set_power("lamp", True)
        self.second.turn_on.assert_awaited_once()
        self.assertEqual(self.controller._connect.await_count, 2)

    async def test_auth_failure_after_write_never_uses_next_credential(self):
        self.first.update.side_effect = [None, AuthenticationError("post-send")]
        with self.assertRaises(AuthenticationError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_awaited_once()
        self.controller._connect.assert_awaited_once()
        self.second.turn_on.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()

    async def test_auth_failure_from_mutation_is_ambiguous_not_retryable(self):
        self.first.turn_on.side_effect = AuthenticationError("possibly delivered")
        with self.assertRaises(AuthenticationError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_awaited_once()
        self.controller._connect.assert_awaited_once()
        self.first.disconnect.assert_awaited_once()

    async def test_timeout_after_send_never_replays(self):
        self.first.update.side_effect = [None, TimeoutError("unknown delivery")]
        with self.assertRaises(TimeoutError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_cancel_before_write_closes_connection_without_writing(self):
        self.first.update.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_cancel_during_write_closes_connection_without_replaying(self):
        self.first.turn_on.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_awaited_once()
        self.first.disconnect.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_all_credentials_fail_without_writes(self):
        self.first.update.side_effect = AuthenticationError("first")
        self.second.update.side_effect = AuthenticationError("second")
        with self.assertRaises(AuthenticationError):
            await self.controller.set_power("lamp", True)
        for device in (self.first, self.second):
            device.turn_on.assert_not_awaited()
            device.disconnect.assert_awaited_once()

    async def test_non_auth_prewrite_failure_never_switches_credentials(self):
        self.first.update.side_effect = TimeoutError("pre-write")
        with self.assertRaises(TimeoutError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_not_awaited()
        self.controller._connect.assert_awaited_once()

    async def test_changed_catalogue_rejects_before_connecting(self):
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            await self.controller.set_power("lamp", True, expected_host="192.0.2.2")
        self.controller._connect.assert_not_awaited()

    async def test_wrong_observed_identity_never_writes_or_falls_back(self):
        self.first.host = "192.0.2.2"
        with self.assertRaisesRegex(RuntimeError, "identity"):
            await self.controller.set_power("lamp", True, expected_host="192.0.2.1")
        self.first.turn_on.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_unknown_observed_identity_never_writes(self):
        self.first.host = None
        with self.assertRaises(RuntimeError):
            await self.controller.set_power("lamp", True, expected_host="192.0.2.1")
        self.first.turn_on.assert_not_awaited()

    async def test_alias_uses_canonical_name_and_admitted_host(self):
        result = await self.controller.set_power("alias", True, expected_host=" 192.0.2.1 ")
        self.assertEqual((result.name, result.host), ("lamp", "192.0.2.1"))
        self.first.turn_on.assert_awaited_once()

    async def test_toggle_observes_and_writes_same_connection_once(self):
        self.controller.status = mock.AsyncMock(side_effect=AssertionError("must not reconnect through status"))
        result = await self.controller.toggle("lamp", expected_host="192.0.2.1")
        self.assertTrue(result.is_on)
        self.first.turn_on.assert_awaited_once()
        self.assertEqual(self.first.update.await_count, 2)
        self.controller._connect.assert_awaited_once()
        self.first.disconnect.assert_awaited_once()

    async def test_unknown_toggle_state_never_writes(self):
        self.first.is_on = None
        with self.assertRaises(RuntimeError):
            await self.controller.toggle("lamp")
        self.first.turn_on.assert_not_awaited()
        self.first.turn_off.assert_not_awaited()
        self.first.disconnect.assert_awaited_once()

    async def test_unconfirmed_post_write_state_is_not_reported_as_success(self):
        self.first.turn_on.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_awaited_once()
        self.controller._connect.assert_awaited_once()

    async def test_explicitly_failed_prewrite_read_does_not_write(self):
        self.first.update.return_value = False
        with self.assertRaises(RuntimeError):
            await self.controller.set_power("lamp", True)
        self.first.turn_on.assert_not_awaited()

    async def test_explicitly_failed_verification_cannot_replay(self):
        self.first.update.side_effect = [None, False]
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            await self.controller.set_power("lamp", True)
        self.controller._connect.assert_awaited_once()
        self.first.turn_on.assert_awaited_once()

    async def test_off_and_legacy_direct_host_remain_supported(self):
        self.first.is_on = True
        result = await self.controller.set_power("192.0.2.1", False)
        self.assertFalse(result.is_on)
        self.first.turn_off.assert_awaited_once()


class PurifierIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.m = load_vendor("purifier", "vesync_client")
        self.settings = types.SimpleNamespace(default_device="b", aliases={"a": "b"})
        self.a = types.SimpleNamespace(cid="a", device_name="First", turn_on=mock.AsyncMock(return_value=True))
        self.b = types.SimpleNamespace(cid="b", device_name="a", turn_on=mock.AsyncMock(return_value=True))
        self.controller = self.m.AirPurifierController(self.settings, expected_cid="a")
        self.controller._purifiers = mock.AsyncMock(return_value=[self.a, self.b])

    async def test_admitted_raw_cid_cannot_be_remapped_by_alias_or_default(self):
        result = await self.controller._resolve_device(object(), "a")
        self.assertIs(result, self.a)

    async def test_missing_cid_cannot_fall_back_to_peer_name(self):
        self.controller._purifiers.return_value = [self.b]
        with self.assertRaises(self.m.AirPurifierError):
            await self.controller._resolve_device(object(), "a")

    async def test_duplicate_cid_is_ambiguous(self):
        self.controller._purifiers.return_value = [self.a, self.a]
        with self.assertRaises(self.m.AirPurifierError):
            await self.controller._resolve_device(object(), "a")

    async def test_mismatched_or_default_selector_rejects_before_discovery(self):
        for requested in (None, "b", ""):
            with self.subTest(requested=requested), self.assertRaises(self.m.AirPurifierError):
                await self.controller._resolve_device(object(), requested)
        self.controller._purifiers.assert_not_awaited()

    async def test_legacy_unbound_alias_still_resolves_normally(self):
        self.controller.expected_cid = None
        self.assertIs(await self.controller._resolve_device(object(), "a"), self.b)

    async def test_mismatch_never_reaches_write_method(self):
        @contextlib.asynccontextmanager
        async def session(): yield object()
        self.controller._session = session
        self.controller._purifiers.return_value = [self.b]
        with self.assertRaises(self.m.AirPurifierError):
            await self.controller.set_power(True, "a")
        self.a.turn_on.assert_not_awaited()
        self.b.turn_on.assert_not_awaited()


class VendorCliBindingTests(unittest.TestCase):
    def test_plug_cli_forwards_expected_host_to_write_only(self):
        cli = load_vendor("plug", "cli")
        fake = mock.Mock()
        fake.set_power = mock.AsyncMock(return_value=mock.Mock())
        with mock.patch.object(cli, "load_settings"), mock.patch.object(cli, "SmartPlugController", return_value=fake), \
             mock.patch.object(cli, "_print_status"):
            self.assertEqual(cli.main(["on", "lamp", "--expected-host", "192.0.2.1"]), 0)
        fake.set_power.assert_awaited_once_with("lamp", True, expected_host="192.0.2.1")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["status", "lamp", "--expected-host", "192.0.2.1"])

    def test_purifier_cli_rejects_binding_on_reads_or_different_selector(self):
        cli = load_vendor("purifier", "cli")
        for command in (["status", "a"], ["doctor"], ["on", "b"], ["on"]):
            with self.subTest(command=command), mock.patch.object(cli, "load_settings") as load, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(["--expected-cid", "a", *command])
            load.assert_not_called()

    def test_purifier_cli_passes_exact_cid_to_controller(self):
        cli = load_vendor("purifier", "cli")
        fake = mock.Mock()
        fake.set_power = mock.AsyncMock(return_value=mock.Mock())
        with mock.patch.object(cli, "load_settings", return_value="settings"), \
             mock.patch.object(cli, "AirPurifierController", return_value=fake) as constructor, \
             mock.patch.object(cli, "_print_status"):
            self.assertEqual(cli.main(["--expected-cid", "a", "on", "a"]), 0)
        constructor.assert_called_once_with("settings", retry_cooldown=False, expected_cid="a")
        fake.set_power.assert_awaited_once_with(True, "a")


if __name__ == "__main__":
    unittest.main()
