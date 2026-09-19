"""STAGED wrappers + real SDKs against inherited synthetic loopback peers only.

Uses actual callback-bound issuer and temporary ledger, NOT snapshot grant minting.
Run explicitly with 'kasa' or 'vesync' and JARVIS_TEST_VENDOR_ROOT staged packages.
No production source/config/credential or accepted certificate is modified.
"""
import asyncio
import concurrent.futures
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core import control_delegation as d, vendor_fence as f
from jarvisd_core.device_host import CatalogueEntry
from jarvisd_core.devices import _purifier_id

KIND = sys.argv.pop(1)
assert KIND in ('kasa', 'vesync')
spec = importlib.util.spec_from_file_location('_synthetic_original_sdk_fixture',
    BACKEND / 'tests_sdk' / ('test_kasa_no_replay.py' if KIND == 'kasa' else 'test_vesync_no_replay.py'))
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)


class Broker:
    """A real callback remains active while the synthetic async SDK call runs."""
    def __init__(self, testcase, params=None, *, action='plug-on'):
        self.temp = tempfile.TemporaryDirectory()
        testcase.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'owner'; self.root.mkdir(mode=0o700)
        (self.root / 'grants').mkdir(mode=0o700)
        g.ControlLedger.initialize(self.root / 'ledger')
        self.store = g.ControlLedger.open(self.root / 'ledger')
        testcase.addCleanup(self.store.close)
        cohort = p.Cohort.PLUGS if action.startswith('plug-') else p.Cohort.PURIFIER
        if cohort is p.Cohort.PLUGS:
            entry = CatalogueEntry(cohort, 'lamp', '127.0.0.1')
            params = {'plug': 'lamp'}
        else:
            cid = testcase.target.cid
            identity = _purifier_id(cid)
            entry = CatalogueEntry(cohort, identity, identity, cid)
            params = {'deviceID': identity, **params}
        # TEST-ONLY synthetic handoff; never usable as live transition evidence.
        state = self.store.transition(cohort, p.Mode.DRAINING)
        evidence = p.HandoffEvidence(cohort, state.epoch, 0, True, True, True, True, True, True)
        self.store.transition(cohort, p.Mode.MAINTENANCE, evidence)
        self.store.transition(cohort, p.Mode.API, evidence)
        self.bound = v.BoundWrite(v._command(action, params), (cohort.value, entry.identity), 'c' * 64)
        self.call = d.call_for(self.bound, entry)
        self.entry = entry
        window = self.store.issue_window(cohort, 'a' * 64)
        self.intent = g.Intent(cohort, window.incarnation, window.epoch, 'a' * 64, '1' * 32,
            self.bound.resource, self.bound.fingerprint, action, window.token)
        self.runner = d.DelegatingRunner(store=self.store, runner=None, root=self.root)

    @contextlib.contextmanager
    def permit(self, sdk_fence):
        messages = queue.Queue(); finish = threading.Event()
        def callback():
            try:
                with self.runner.scope(self.bound, self.entry):
                    messages.put((True, self.runner._local.frame['token']))
                    if not finish.wait(8):
                        raise TimeoutError('Synthetic fixture did not release callback')
                return g.DispatchResult(p.Outcome.UNKNOWN)
            except BaseException as error:
                messages.put((False, error)); raise
        ready = p.Readiness(self.intent.epoch, self.intent.epoch, True, True, True, True, True, True, False)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.store.execute_once, self.intent, lambda: ready, callback)
            try:
                ok, token = messages.get(timeout=8)
                if not ok:
                    raise token
                with mock.patch.object(sdk_fence, 'root_directory', return_value=self.root), \
                        mock.patch.object(f, 'root_directory', return_value=self.root), \
                        mock.patch.dict(os.environ, {f.TOKEN_ENV: token}), \
                        f.permission(self.call, phase='worker'):
                    yield token
            finally:
                finish.set()
                future.result(timeout=8)


def isolated_root(testcase, sdk_fence):
    temp = tempfile.TemporaryDirectory()
    testcase.addCleanup(temp.cleanup)
    patch = mock.patch.object(sdk_fence, 'root_directory', return_value=Path(temp.name) / 'absent')
    patch.start(); testcase.addCleanup(patch.stop)
    patch = mock.patch.dict(os.environ, {f.TOKEN_ENV: ''})
    patch.start(); testcase.addCleanup(patch.stop)


if KIND == 'kasa':
    class FencedTests(original.NoReplayTests):
        async def asyncSetUp(self):
            await super().asyncSetUp()
            self.fence = original.wrapper._ownership  # Missing staged hook is a failure.
            isolated_root(self, self.fence)

        async def asyncTearDown(self):
            # Release synthetic XOR responders BEFORE protocol-close cleanups;
            # this is fixture shutdown, not mutation retry or remote cancellation.
            self.release.set()

        async def write(self, dev, on=True, *, intent=None):
            controller = object.__new__(original.wrapper.SmartPlugController)
            # Synthetic post-write observation only. Actual setter/protocol/HTTP
            # remain the installed SDK against the loopback peer, never mocked.
            with mock.patch.object(dev, 'update', new_callable=mock.AsyncMock, return_value=True), \
                    mock.patch.object(original.wrapper, '_status_from_device', return_value=types.SimpleNamespace(is_on=on)):
                return await controller._write_connected(dev, 'lamp', '127.0.0.1', on, '127.0.0.1', intent=intent)

        async def test_missing_grant_denies_before_sdk_submission(self):
            dev = await self.xor_device()
            with self.assertRaises(self.fence.FenceError):
                await self.write(dev)
            self.assertEqual(self.received, [])

        async def test_real_issuer_one_sdk_submission_and_no_reuse(self):
            dev = await self.xor_device()
            broker = Broker(self)
            with broker.permit(self.fence):
                await self.write(dev)
                with self.assertRaises(self.fence.FenceError):
                    await self.write(dev)
            self.assertEqual(len(self.received), 1)
            self.assertTrue(broker.store.pending_resources(p.Cohort.PLUGS))

        async def test_wrong_effect_and_toggle_intent_are_distinct(self):
            dev = await self.xor_device()
            broker = Broker(self, action='plug-toggle')
            with broker.permit(self.fence):
                with self.assertRaises(self.fence.FenceError):
                    await self.write(dev)
                await self.write(dev, intent='plug-toggle')
            self.assertEqual(len(self.received), 1)

        async def test_lost_reply_cannot_replay_or_refund(self):
            dev = await self.xor_device(); self.mode = 'drop'
            broker = Broker(self)
            with broker.permit(self.fence):
                with self.assertRaises(Exception):
                    await self.write(dev)
                with self.assertRaises(self.fence.FenceError):
                    await self.write(dev)
            self.assertEqual(len(self.received), 1)
            self.assertTrue(broker.store.pending_resources(p.Cohort.PLUGS))

        async def test_cancellation_preserves_consumption_and_sdk_restoration(self):
            dev = await self.xor_device(); self.mode = 'wait'
            broker = Broker(self)
            with broker.permit(self.fence):
                task = asyncio.create_task(self.write(dev))
                await asyncio.wait_for(self.received_event.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(self.fence.FenceError):
                    await self.write(dev)
            self.assertEqual(len(self.received), 1)
            self.assert_restored(dev)

        async def test_smart_http_path_is_still_single_attempt(self):
            dev = await self.http_device(original.SmartProtocol, original.AesTransport)
            broker = Broker(self)
            with broker.permit(self.fence):
                await self.write(dev)
            self.assertEqual(len(self.received), 1)
            self.assert_restored(dev)

        async def test_save_discovery_is_closed_without_discovery_or_config_io(self):
            controller = object.__new__(original.wrapper.SmartPlugController)
            with mock.patch.object(controller, 'discover', new_callable=mock.AsyncMock) as discover:
                with self.assertRaises(self.fence.FenceError):
                    await controller.save_discovery()
                discover.assert_not_awaited()
else:
    class FencedTests(original.VeSyncGuardTests):
        async def asyncSetUp(self):
            await super().asyncSetUp()
            self.fence = original.policy._ownership
            isolated_root(self, self.fence)

        async def test_missing_grant_denies_before_sdk_submission(self):
            with self.assertRaises(self.fence.FenceError):
                await self.write()
            self.assertEqual(self.calls, [])
            self.restored()

        async def test_real_issuer_one_sdk_submission_and_no_reuse(self):
            broker = Broker(self, {'setting': 'power', 'value': 'on'}, action='purifier-set')
            with broker.permit(self.fence):
                self.assertTrue(await self.write())
                with self.assertRaises(self.fence.FenceError):
                    await self.write()
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(broker.store.pending_resources(p.Cohort.PURIFIER))
            self.restored()

        async def test_wrong_setting_and_argument_types_cannot_borrow_grant(self):
            broker = Broker(self, {'setting': 'speed', 'level': 1}, action='purifier-set')
            with broker.permit(self.fence):
                with self.assertRaises(self.fence.FenceError):
                    await self.write('turn_on')
                with self.assertRaises(Exception):
                    await self.write('set_fan_speed', True)
                self.assertTrue(await self.write('set_fan_speed', 1))
            self.assertEqual(len(self.calls), 1)

        async def test_lost_reply_cannot_replay_or_refund(self):
            broker = Broker(self, {'setting': 'power', 'value': 'on'}, action='purifier-set')
            self.mode = 'drop'
            with broker.permit(self.fence):
                try:
                    await self.write()
                except Exception:
                    pass  # SDK can report False or raise; neither refunds.
                with self.assertRaises(self.fence.FenceError):
                    await self.write()
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(broker.store.pending_resources(p.Cohort.PURIFIER))
            self.restored()

        async def test_cancellation_preserves_consumption_and_sdk_restoration(self):
            broker = Broker(self, {'setting': 'power', 'value': 'on'}, action='purifier-set')
            self.mode = 'wait'
            with broker.permit(self.fence):
                task = asyncio.create_task(self.write())
                await asyncio.wait_for(self.reached.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(self.fence.FenceError):
                    await self.write()
            self.assertEqual(len(self.calls), 1)
            self.restored()

        async def test_existing_settings_match_sdk_methods_and_mutation_payloads(self):
            cases = [({'setting': 'power', 'value': 'on'}, 'turn_on', [], {}, 'setSwitch'),
                ({'setting': 'power', 'value': 'off'}, 'turn_off', [], {}, 'setSwitch'),
                ({'setting': 'power', 'value': 'toggle'}, 'toggle_switch', [None], {}, 'setSwitch'),
                ({'setting': 'timer', 'value': 'clear'}, 'clear_timer', [], {}, 'delTimerV2')]
            for setting, suffix, payload in [('display', 'display', 'setDisplay'),
                    ('child-lock', 'child_lock', 'setChildLock'), ('light-detection', 'light_detection', 'setLightDetection')]:
                for value in ('on', 'off'):
                    cases.append(({'setting': setting, 'value': value}, 'turn_' + value + '_' + suffix, [], {}, payload))
            for mode in ('auto', 'manual', 'sleep', 'pet'):
                cases.append(({'setting': 'mode', 'value': mode}, 'set_mode', [mode], {},
                              'setLevel' if mode == 'manual' else 'setPurifierMode'))
            for level in range(1, 5):
                cases.append(({'setting': 'speed', 'level': level}, 'set_fan_speed', [level], {}, 'setLevel'))
            for preference in ('default', 'quiet', 'efficient'):
                cases.append(({'setting': 'auto-preference', 'value': preference, 'roomSize': 123},
                              'set_auto_preference', [preference], {'room_size': 123}, 'setAutoPreference'))
            for params, method, args, kwargs, payload in cases:
                with self.subTest(params=params):
                    self.target.state.device_status = original.DeviceStatus.ON if method == 'turn_off' else original.DeviceStatus.OFF
                    self.target.state.display_set_status = original.DeviceStatus.ON if method == 'turn_off_display' else original.DeviceStatus.OFF
                    self.target.state.light_detection_status = original.DeviceStatus.ON if method == 'turn_off_light_detection' else original.DeviceStatus.OFF
                    self.target.state.light_detection_switch = self.target.state.light_detection_status
                    self.target.state.timer = original.Timer(300, 'off', id=7)
                    broker = Broker(self, params, action='purifier-set')
                    before = len(self.calls)
                    with broker.permit(self.fence):
                        self.assertTrue(await self.write(method, *args, **kwargs))
                    self.assertEqual(len(self.calls), before + 1)
                    self.assertEqual(self.calls[-1][1]['payload']['method'], payload)
                    self.restored()

        async def test_timer_seconds_and_room_size_match_reviewed_translation(self):
            cases = [({'setting': 'timer', 'minutes': 2}, 'set_timer', [120], {}),
                     ({'setting': 'auto-preference', 'value': 'quiet'}, 'set_auto_preference', ['quiet'], {'room_size': 600})]
            for params, method, args, kwargs in cases:
                broker = Broker(self, params, action='purifier-set')
                with broker.permit(self.fence):
                    self.assertTrue(await self.write(method, *args, **kwargs))
            self.assertEqual(len(self.calls), 2)
            self.restored()


def load_tests(loader, tests, pattern):
    # Inherit synthetic peer setup/helpers, not the original unfenced test cases.
    return unittest.TestSuite(FencedTests(name) for name in sorted(FencedTests.__dict__) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
