"""SDK-free wrapper routing and verification policy. Real SDK gate is separate."""
import contextlib
import types
import unittest
from unittest import mock
from vendor_loader import load_vendor


class PurifierWriteBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.m = load_vendor("purifier", "vesync_client")
        self.target = types.SimpleNamespace(cid="fixture-private-cid", is_on=False,
                                            device_name="Fixture", state=types.SimpleNamespace())
        self.controller = self.m.AirPurifierController(types.SimpleNamespace(write_wait_seconds=0),
                                                      expected_cid=self.target.cid)
        @contextlib.asynccontextmanager
        async def session():
            yield object()
        self.controller._session = session
        self.controller._resolve_device = mock.AsyncMock(return_value=self.target)
        self.controller._wait_for_status = mock.AsyncMock(return_value="verified")
        for name in ("execute_write", "observe"):
            patch = mock.patch.object(self.m, name, new_callable=mock.AsyncMock)
            setattr(self, name, patch.start())
            self.addCleanup(patch.stop)
        self.execute_write.return_value = True

    async def test_existing_settings_use_guard_and_admitted_cid(self):
        cases = [("set_power", [True], "turn_on", (), {}),
                 ("set_power", [False], "turn_off", (), {}),
                 ("set_mode", ["auto"], "set_mode", ("auto",), {}),
                 ("set_speed", [3], "set_fan_speed", (3,), {}),
                 ("set_display", [False], "turn_off_display", (), {}),
                 ("set_child_lock", [True], "turn_on_child_lock", (), {}),
                 ("set_light_detection", [True], "turn_on_light_detection", (), {}),
                 ("set_auto_preference", ["quiet", 600], "set_auto_preference", ("quiet",), {"room_size": 600}),
                 ("set_timer", [5], "set_timer", (300,), {}),
                 ("clear_timer", [], "clear_timer", (), {})]
        for method, args, operation, expected_args, kwargs in cases:
            with self.subTest(method=method):
                self.execute_write.reset_mock()
                self.assertEqual(await getattr(self.controller, method)(*args, device=self.target.cid), "verified")
                self.execute_write.assert_awaited_once_with(self.target, operation, *expected_args,
                                                            expected_cid=self.target.cid, **kwargs)

    async def test_guard_failure_never_starts_verification_or_retries(self):
        self.execute_write.side_effect = RuntimeError("possibly delivered")
        with self.assertRaises(RuntimeError):
            await self.controller.set_power(True, self.target.cid)
        self.execute_write.assert_awaited_once()
        self.controller._wait_for_status.assert_not_awaited()

    async def test_toggle_observes_once_before_one_mutation_and_pins_expectation(self):
        await self.controller.toggle(self.target.cid)
        self.observe.assert_awaited_once_with(self.target, expected_cid=self.target.cid)
        self.execute_write.assert_awaited_once_with(self.target, "toggle_switch", None, expected_cid=self.target.cid)
        predicate = self.controller._wait_for_status.call_args.args[1]
        self.assertTrue(predicate(types.SimpleNamespace(is_on=True)))
        self.assertFalse(predicate(types.SimpleNamespace(is_on=False)))

    async def test_failed_toggle_observation_prevents_write(self):
        self.observe.side_effect = RuntimeError("malformed status")
        with self.assertRaises(RuntimeError):
            await self.controller.toggle(self.target.cid)
        self.execute_write.assert_not_awaited()

    async def test_clear_timer_does_not_swallow_preparation_failure(self):
        self.observe.side_effect = RuntimeError("malformed timer list")
        with self.assertRaises(RuntimeError):
            await self.controller.clear_timer(self.target.cid)
        self.execute_write.assert_not_awaited()

    async def test_wait_rejects_invalid_observation_not_optimistic_state(self):
        del self.controller._wait_for_status
        self.observe.side_effect = RuntimeError("incomplete observation")
        with self.assertRaises(RuntimeError):
            await self.controller._wait_for_status(self.target, lambda _: True, "power on")
        self.execute_write.assert_not_awaited()

    async def test_valid_observation_mismatch_remains_pending_without_replay(self):
        del self.controller._wait_for_status
        result = await self.controller._wait_for_status(self.target, lambda _: False, "power on")
        self.assertTrue(result.write_accepted)
        self.assertTrue(result.verification_pending)
        self.execute_write.assert_not_awaited()

    async def test_valid_matching_observation_confirms_without_replay(self):
        del self.controller._wait_for_status
        result = await self.controller._wait_for_status(self.target, lambda _: True, "power on")
        self.assertFalse(result.verification_pending)
        self.observe.assert_awaited_once_with(self.target, expected_cid=self.target.cid)
        self.execute_write.assert_not_awaited()

    async def test_cancellation_does_not_start_verification(self):
        import asyncio
        self.execute_write.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.set_power(True, self.target.cid)
        self.controller._wait_for_status.assert_not_awaited()
