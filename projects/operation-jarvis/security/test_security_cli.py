"""Consolidated offline security regression suite; synthetic data only."""
from __future__ import annotations
import security_cli


# CAMERAS TESTS
from security_cli import (CameraSettings, CameraTracker, FrameObservation)
"""Offline camera contracts only. Synthetic credentials and metadata, no footage."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch




cameras_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class cameras_CameraSettingsTests(unittest.TestCase):
    def test_missing_configuration(self):
        self.assertEqual(CameraSettings().missing, "missing_host")
        self.assertEqual(CameraSettings(host="192.168.50.2").missing, "missing_credentials")

    def test_env_is_explicit_camera_only_and_credentials_hidden(self):
        with patch.dict("os.environ", {"JARVIS_SECURITY_CAMERA_HOST": "192.168.50.2"}):
            self.assertEqual(CameraSettings.from_env({}).missing, "missing_host")
        settings = CameraSettings.from_env({
            "JARVIS_SECURITY_HUB_HOST": "192.168.50.3",
            "JARVIS_SECURITY_USERNAME": "cloud-test-user",
            "JARVIS_SECURITY_PASSWORD": "cloud-test-secret",
            "JARVIS_SECURITY_CAMERA_HOST": " 192.168.50.2 ",
        })
        self.assertEqual(settings.host, "192.168.50.2")
        self.assertEqual(settings.missing, "missing_credentials")
        settings = CameraSettings.from_env({
            "JARVIS_SECURITY_CAMERA_HOST": "192.168.50.2",
            "JARVIS_SECURITY_CAMERA_USERNAME": "camera-test-user",
            "JARVIS_SECURITY_CAMERA_PASSWORD": "camera-test-secret",
        })
        self.assertIsNone(settings.missing)
        for value in (settings.host, settings.username, settings.password):
            self.assertNotIn(value, repr(settings))

    def test_invalid_hosts_fail_without_echoing_input(self):
        for host in ["8.8.8.8", "127.0.0.1", "0.0.0.0", "224.0.0.1", "169.254.1.2",
                     "localhost", "camera.local", "rtsp://test:fake-secret@192.168.50.2/stream1"]:
            with self.subTest(host=host), self.assertRaises(ValueError) as exc:
                CameraSettings(host=host)
            self.assertNotIn(host, str(exc.exception))

    def test_private_ipv6_supported(self):
        self.assertIsNone(CameraSettings("fd00::10", "fake-user", "fake-password").missing)


class cameras_FrameTests(unittest.TestCase):
    def test_aware_timestamp_and_positive_integer_dimensions_required(self):
        for width, height in [(0, 1080), (1920, -1), (True, 1080), (1920, "1080")]:
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                FrameObservation(cameras_START, width, height)
        with self.assertRaises(ValueError):
            FrameObservation(cameras_START.replace(tzinfo=None), 1920, 1080)

    def test_metadata_only_and_utc_serialization(self):
        reading = FrameObservation(cameras_START.astimezone(timezone(timedelta(hours=-4))), 1920, 1080)
        self.assertEqual(json.loads(json.dumps(reading.as_dict())), {
            "observed_at": cameras_START.isoformat(), "width": 1920, "height": 1080})


class cameras_CameraTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tick = 0
        self.wall = cameras_START
        self.settings = CameraSettings("192.168.50.2", "fake-user", "fake-secret")
        self.tracker = self.make_tracker(self.settings)

    def make_tracker(self, settings):
        return CameraTracker(settings, stale_after=30, clock=lambda: self.tick,
                             wall_clock=lambda: self.wall)

    def frame(self, when=None):
        # These are synthetic dimensions, NOT an assertion of C230 stream resolution.
        return FrameObservation(when or self.wall, 1920, 1080)

    def advance(self, seconds):
        self.tick += seconds
        self.wall += timedelta(seconds=seconds)

    def test_default_and_configured_status_never_access_network(self):
        with patch("socket.socket", side_effect=AssertionError("Network is forbidden")), \
             patch("socket.create_connection", side_effect=AssertionError("Network is forbidden")):
            self.assertEqual(self.make_tracker(CameraSettings()).snapshot()["health"], "not_configured")
            self.assertEqual(self.tracker.snapshot()["health"], "unknown")
            self.tracker.accept_frame(self.frame())
            self.assertEqual(self.tracker.snapshot()["health"], "online")

    def test_unconfigured_cannot_accept_frame_or_claim_network_failure(self):
        tracker = self.make_tracker(CameraSettings())
        with self.assertRaises(ValueError):
            tracker.accept_frame(self.frame())
        tracker.mark_unavailable()
        self.assertEqual(tracker.snapshot()["health"], "not_configured")
        self.assertEqual(tracker.snapshot()["video"], "unknown")

    def test_online_means_frame_not_recording_privacy_or_security(self):
        self.assertTrue(self.tracker.accept_frame(self.frame()))
        snap = self.tracker.snapshot()
        self.assertEqual((snap["health"], snap["video"]), ("online", "available"))
        for key in ["security_assessment", "recording_assessment", "privacy_mode_assessment"]:
            self.assertEqual(snap[key], "not_assessed")
        output = json.dumps(snap)
        for secret in (self.settings.host, self.settings.username, self.settings.password):
            self.assertNotIn(secret, output)

    def test_stale_exact_boundary_and_historical_metadata(self):
        self.tracker.accept_frame(self.frame())
        self.advance(29)
        self.assertEqual(self.tracker.snapshot()["health"], "online")
        self.advance(1)
        snap = self.tracker.snapshot()
        self.assertEqual((snap["health"], snap["video"]), ("stale", "unknown"))
        self.assertEqual(snap["last_frame"]["observed_at"], cameras_START.isoformat())

    def test_duplicate_or_older_frame_does_not_refresh_age(self):
        frame = self.frame()
        self.tracker.accept_frame(frame)
        self.advance(30)
        self.assertFalse(self.tracker.accept_frame(frame))
        self.assertFalse(self.tracker.accept_frame(self.frame(cameras_START - timedelta(seconds=1))))
        self.assertEqual(self.tracker.snapshot()["health"], "stale")

    def test_delayed_frame_cannot_become_fresh_on_ingest(self):
        self.advance(40)
        self.tracker.accept_frame(self.frame(cameras_START))
        self.assertEqual(self.tracker.snapshot()["health"], "stale")
        self.assertEqual(self.tracker.snapshot()["frame_age_seconds"], 40)

    def test_offline_retains_history_not_live_video(self):
        self.tracker.accept_frame(self.frame())
        self.tracker.mark_unavailable()
        snap = self.tracker.snapshot()
        self.assertEqual((snap["health"], snap["video"]), ("offline", "unknown"))
        self.assertIsNotNone(snap["last_frame"])

    def test_auth_stream_and_raw_errors_are_not_misreported_as_offline(self):
        for reason in ["authentication_failed", "stream_unavailable", "read_failed",
                       "rtsp://fake-user:fake-secret@192.168.50.2"]:
            with self.subTest(reason=reason):
                self.tracker.mark_unavailable(reason)
                snap = self.tracker.snapshot()
                self.assertEqual((snap["health"], snap["video"]), ("error", "unknown"))
                self.assertNotIn("fake-secret", json.dumps(snap))

    def test_recovery_requires_new_frame_not_replay(self):
        frame = self.frame()
        self.tracker.accept_frame(frame)
        self.tracker.mark_unavailable()
        self.advance(1)
        self.assertFalse(self.tracker.accept_frame(frame))
        self.assertEqual(self.tracker.snapshot()["health"], "offline")
        self.assertTrue(self.tracker.accept_frame(self.frame()))
        self.assertEqual(self.tracker.snapshot()["health"], "online")

    def test_future_timestamp_invalidates_online_state(self):
        self.tracker.accept_frame(self.frame())
        with self.assertRaises(ValueError):
            self.tracker.accept_frame(self.frame(cameras_START + timedelta(seconds=1)))
        self.assertEqual(self.tracker.snapshot()["health"], "error")
        self.assertEqual(self.tracker.snapshot()["video"], "unknown")

    def test_wall_clock_adjustment_does_not_extend_freshness(self):
        self.tracker.accept_frame(self.frame())
        self.tick = 30
        self.wall -= timedelta(hours=1)
        self.assertEqual(self.tracker.snapshot()["health"], "stale")

    def test_restart_is_unknown(self):
        self.tracker.accept_frame(self.frame())
        self.assertEqual(self.make_tracker(self.settings).snapshot()["health"], "unknown")

    def test_instances_are_independent(self):
        second_stream = self.make_tracker(self.settings)
        self.tracker.accept_frame(self.frame())
        self.assertEqual(second_stream.snapshot()["health"], "unknown")

    def test_invalid_freshness_limits(self):
        for value in [0, -1, True, float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                CameraTracker(self.settings, stale_after=value)






# COMMISSION TESTS
"""Offline tests: no real credentials, network or persistence."""
import io
import unittest
import warnings
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch




class commission_CommissionTests(unittest.TestCase):
    def run_prompt(self, entries, *, tty=True, health="online", reason=None,
                   failure=None):
        output = io.StringIO()
        with patch.object(security_cli.sys.stdin, "isatty", return_value=tty), \
                redirect_stdout(output), \
                patch.object(output, "isatty", return_value=tty), \
                patch.object(security_cli.getpass, "getpass", side_effect=entries) as prompt, \
                patch.object(security_cli, "HubMonitor") as monitor, \
                patch.object(security_cli.logging, "disable"):
            monitor.return_value.probe = AsyncMock(return_value={
                "health": health, "reason": reason,
                "security_assessment": "not_assessed",
                "observation": {"private_metadata": "DO-NOT-PRINT"},
            }, side_effect=failure)
            code = security_cli.commission_main()
        return code, output.getvalue(), prompt, monitor

    def test_refuses_noninteractive_input(self):
        code, _, prompt, monitor = self.run_prompt([], tty=False)
        self.assertEqual(code, 2)
        prompt.assert_not_called()
        monitor.assert_not_called()

    def test_success_is_one_probe_without_secret_or_inventory_output(self):
        code, output, prompt, monitor = self.run_prompt(
            ["192.168.50.8", "synthetic-user", "synthetic-password"])
        self.assertEqual(code, 0)
        self.assertEqual(prompt.call_count, 3)
        monitor.return_value.probe.assert_awaited_once()
        settings = monitor.call_args.args[0]
        self.assertEqual(settings.host, "192.168.50.8")
        self.assertEqual(settings.username, "synthetic-user")
        self.assertEqual(settings.password, "synthetic-password")
        for secret in (settings.host, settings.username, settings.password, "DO-NOT-PRINT"):
            self.assertNotIn(secret, output)
        self.assertIn('"health": "online"', output)
        self.assertIn('"security_assessment": "not_assessed"', output)

    def test_invalid_host_is_not_echoed_and_never_requests_credentials(self):
        code, output, prompt, monitor = self.run_prompt(["invalid-private-input"])
        self.assertEqual(code, 2)
        self.assertEqual(prompt.call_count, 1)
        self.assertNotIn("invalid-private-input", output)
        monitor.assert_not_called()

    def test_empty_entries_do_not_connect(self):
        for entries in ([""], ["192.168.50.8", "", "password"],
                        ["192.168.50.8", "user", ""]):
            with self.subTest(entries=len(entries)):
                code, _, _, monitor = self.run_prompt(entries)
                self.assertEqual(code, 2)
                monitor.assert_not_called()

    def test_input_cancellation_and_eof(self):
        for error in (KeyboardInterrupt(), EOFError()):
            code, _, _, monitor = self.run_prompt(error)
            self.assertEqual(code, 130)
            monitor.assert_not_called()

    def test_hidden_input_warning_aborts_before_echoing_fallback(self):
        def warning(*args):
            warnings.warn("synthetic-terminal-warning", security_cli.getpass.GetPassWarning)
            self.fail("An echoing fallback must not be reached")
        code, output, _, monitor = self.run_prompt(warning)
        self.assertEqual(code, 2)
        self.assertNotIn("synthetic-terminal-warning", output)
        monitor.assert_not_called()

    def test_authentication_failure_is_not_online(self):
        code, output, _, monitor = self.run_prompt(
            ["192.168.50.8", "user", "password"], health="error",
            reason="authentication_failed")
        self.assertEqual(code, 2)
        self.assertIn("authentication_failed", output)
        monitor.return_value.probe.assert_awaited_once()

    def test_unexpected_exception_is_sanitized(self):
        code, output, _, _ = self.run_prompt(
            ["192.168.50.8", "user", "password"],
            failure=RuntimeError("synthetic-sensitive-error"))
        self.assertEqual(code, 2)
        self.assertNotIn("synthetic-sensitive-error", output)






# CONTROL TESTS
from security_cli import (ControlError, WRITES, ACTIONS, clean, device_lock, execute, healthy_feature, inventory, operate, parse_value, registry, validate_request, control_main)
"""Offline CLI/control tests. No real devices or credentials."""
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch






class control_Feature:
    def __init__(self, kind='Switch', value=False):
        self.type = NS(name=kind)
        self.value = value
        self.container = NS(_last_update_error=None, disabled=False)
        self.minimum_value, self.maximum_value = 0, 10
        self.choices = ['Doorbell', 'Alarm']
        self.set_value = AsyncMock(side_effect=self.assign)

    async def assign(self, value):
        self.value = value


def control_device(features=None):
    return NS(features=features or {}, modules={}, update=AsyncMock(),
              protocol=NS(query=AsyncMock()), disconnect=AsyncMock(),
              model='C230', device_type=NS(value='camera'))


class control_ValidationTests(unittest.TestCase):
    def test_all_writes_require_confirmation(self):
        for model in WRITES:
            for command in ('set', 'action', 'privacy', 'move'):
                with self.subTest(model=model, command=command), self.assertRaises(ControlError):
                    validate_request(model, command, 'led', 'on', False, False)

    def test_denied_operations(self):
        for name in ('pair', 'format', 'reboot', 'device_id', 'record', 'raw_rpc'):
            for command in ('set', 'action'):
                with self.subTest(name=name, command=command), self.assertRaises(ControlError):
                    validate_request('H200', command, name, 'on', True, True)

    def test_alarm_double_gate(self):
        with self.assertRaisesRegex(ControlError, 'audible_confirmation'):
            validate_request('H200', 'action', 'test_alarm', None, True, False)
        validate_request('H200', 'action', 'test_alarm', None, True, True)

    def test_movement_bounds(self):
        for value in (0, 31, -1, True, 1.5, '10'):
            with self.assertRaises(ControlError):
                validate_request('C230', 'move', 'left', value, True, False)
        validate_request('C230', 'move', 'left', 30, True, False)

    def test_switch_validation(self):
        self.assertTrue(parse_value(control_Feature(), 'on'))
        self.assertFalse(parse_value(control_Feature(), 'off'))
        with self.assertRaises(ControlError):
            parse_value(control_Feature(), 'toggle')

    def test_number_validation(self):
        f = control_Feature('Number')
        self.assertEqual(parse_value(f, '10'), 10)
        for value in ('11', '-1', 'nan', '1.1', 'secret'):
            with self.assertRaises(ControlError):
                parse_value(f, value)

    def test_choice_validation(self):
        self.assertEqual(parse_value(control_Feature('Choice'), 'Doorbell'), 'Doorbell')
        with self.assertRaises(ControlError):
            parse_value(control_Feature('Choice'), 'unknown')

    def test_inventory_excludes_identity_and_unknown_fields(self):
        d = control_device({'device_id': control_Feature(value='PRIVATE'), 'ssid': control_Feature(value='PRIVATE'),
                    'state': control_Feature(value=True), 'led': control_Feature(value=False)})
        result = inventory(d, 'C230')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertFalse(result['privacy']['value'])

    def test_unavailable_not_false(self):
        f = control_Feature(value=False)
        f.container._last_update_error = Exception('PRIVATE')
        result = inventory(control_device({'state': f}), 'C230')
        self.assertIsNone(result['privacy']['value'])
        self.assertEqual(result['state'], {'status': 'unknown'})

    def test_clean(self):
        for value in ({'password': 'PRIVATE'}, ['PRIVATE'], float('nan'), 'x\nPRIVATE'):
            self.assertIsNone(clean(value))

    def test_registry_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'devices.json'
            for data in ({'../escape': {'model': 'C230', 'host': '192.168.1.1'}},
                         {'cam': {'model': 'C230', 'host': '8.8.8.8'}},
                         {'cam': {'model': 'unknown', 'host': '@hub'}}, {}):
                p.write_text(json.dumps(data))
                with self.assertRaises(ControlError):
                    registry(p)
            p.write_text(json.dumps({'cam': {'model': 'C230', 'host': '192.168.1.1'}}))
            self.assertIn('cam', registry(p))

    def test_lock_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            with device_lock('cam', Path(tmp)):
                with self.assertRaisesRegex(ControlError, 'device_busy'):
                    with device_lock('cam', Path(tmp)):
                        pass

    def test_errors_do_not_echo_arguments(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = control_main(['--json', 'PRIVATE_INVALID_ARGUMENT'])
        self.assertEqual(code, 2)
        self.assertNotIn('PRIVATE', out.getvalue())
        json.loads(out.getvalue())

    def test_exception_redaction(self):
        out = io.StringIO()
        with patch('security_cli.execute', new=AsyncMock(side_effect=RuntimeError('PRIVATE'))):
            with redirect_stdout(out):
                self.assertEqual(control_main(['--json', 'status', 'hub']), 2)
        self.assertNotIn('PRIVATE', out.getvalue())


class control_OperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_never_sets(self):
        f = control_Feature()
        await operate(control_device({'led': f}), 'C230', 'status')
        f.set_value.assert_not_awaited()

    async def test_set_readback(self):
        f = control_Feature()
        d = control_device({'led': f})
        self.assertEqual((await operate(d, 'C230', 'set', 'led', 'on'))['result'], 'verified')
        d.update.assert_awaited_once_with(update_children=False)

    async def test_privacy_inverts_state(self):
        f = control_Feature(value=True)
        result = await operate(control_device({'state': f}), 'C230', 'privacy', value='on')
        f.set_value.assert_awaited_once_with(False)
        self.assertEqual(result['result'], 'verified')

    async def test_readback_mismatch(self):
        f = control_Feature()
        f.set_value = AsyncMock()
        result = await operate(control_device({'led': f}), 'C230', 'set', 'led', 'on')
        self.assertEqual(result['outcome'], 'unknown')

    async def test_movement_single_request(self):
        step, action = control_Feature('Number'), control_Feature('Action')
        result = await operate(control_device({'pan_step': step, 'pan_left': action}),
                               'C230', 'move', 'left', 8)
        step.set_value.assert_awaited_once_with(8)
        action.set_value.assert_awaited_once_with(None)
        self.assertEqual(result['physical_position'], 'not_verified')

    async def test_alarm_duration_gate(self):
        for duration in (0, 61, None, True):
            action = control_Feature('Action')
            with self.assertRaises(ControlError):
                await operate(control_device({'alarm_duration': control_Feature('Number', duration), 'test_alarm': action}),
                              'H200', 'action', 'test_alarm')
            action.set_value.assert_not_awaited()

    async def test_storage_only_get(self):
        d = control_device()
        with patch('security_cli.normalize_status', return_value={}) as normalize:
            await operate(d, 'H200', 'storage')
        d.protocol.query.assert_awaited_once_with({'get': {'harddisk_manage': {'table': ['hd_info']}}})

    async def test_sensor_read_budget_metadata_and_failures(self):
        from contextlib import nullcontext
        for failure in ('success', 'timeout', 'missing', 'feature'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / 'registry.json'
                p.write_text(json.dumps({
                    'hub': {'model': 'H200', 'host': '192.168.1.2'},
                    'door': {'model': 'T110', 'hub': 'hub', 'name': 'Test door'}}))
                feature = control_Feature('Sensor', True)
                child = NS(model='T110', alias='Test door', features={'is_open': feature})
                d = control_device()
                d.model, d.device_type = 'H200', NS(value='hub')
                d.children = [] if failure == 'missing' else [child]
                d.protocol.query.return_value = {'getDeviceInfo': {'device_info': {
                    'basic_info': {'device_model': 'H200'}}}}
                if failure == 'timeout':
                    d.update.side_effect = TimeoutError('PRIVATE')
                if failure == 'feature':
                    feature.container._last_update_error = RuntimeError('PRIVATE')
                with patch('kasa.Discover.discover_single', new=AsyncMock(return_value=d)) as discover, \
                     patch('security_cli.device_lock', return_value=nullcontext()), \
                     patch('security_cli.install_empty_child_lists_compat'), \
                     patch('security_cli.load_settings', return_value=NS(host='', username='u', password='p')), \
                     patch('security_cli.asyncio.timeout', wraps=asyncio.timeout) as budget:
                    if failure in ('timeout', 'missing'):
                        with self.assertRaises((TimeoutError, ControlError)) as caught:
                            await execute('door', 'status', registry_path=p)
                        self.assertEqual(caught.exception.security_stage, 'state_read')
                    else:
                        result = await execute('door', 'status', registry_path=p)
                        self.assertEqual(result['radio_freshness'], 'unknown')
                        self.assertIsNone(result['sensor_updated_at'])
                        self.assertIsNotNone(result['hub_snapshot_at'])
                        if failure == 'feature':
                            self.assertEqual(result['features']['is_open']['status'], 'unknown')
                        else:
                            self.assertTrue(result['features']['is_open']['value'])
                    budget.assert_called_once_with(60)
                    self.assertEqual(discover.call_args.kwargs['timeout'], 10)
                    discover.assert_awaited_once()
                    d.update.assert_awaited_once()
                    d.disconnect.assert_awaited_once()
                    feature.set_value.assert_not_awaited()

    async def test_execute_paths(self):
        try:
            import kasa
        except ImportError:
            self.skipTest('optional SDK unavailable')
        for failure in ('identity', 'write', 'success'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / 'registry.json'
                p.write_text(json.dumps({'cam': {'model': 'C230', 'host': '192.168.1.2'}}))
                f = control_Feature()
                d = control_device({'led': f})
                if failure == 'write':
                    f.set_value.side_effect = TimeoutError('PRIVATE')
                d.protocol.query.return_value = {'getDeviceInfo': {'device_info': {'basic_info': {
                    'device_model': 'H200' if failure == 'identity' else 'C230'}}}}
                original = d.protocol.query
                from contextlib import nullcontext
                with patch('kasa.Discover.discover_single', new=AsyncMock(return_value=d)), \
                     patch('security_cli.device_lock', return_value=nullcontext()), \
                     patch('security_cli.load_settings', return_value=NS(host='', username='u', password='p')):
                    if failure == 'success':
                        result = await execute('cam', 'set', name='led', value='on', confirm=True, registry_path=p)
                        self.assertEqual(result['result'], 'verified')
                    else:
                        with self.assertRaisesRegex(ControlError, 'identity_mismatch' if failure == 'identity' else 'write_outcome_unknown'):
                            await execute('cam', 'set', name='led', value='on', confirm=True, registry_path=p)
                    d.disconnect.assert_awaited_once()
                    self.assertEqual(original.call_args.kwargs['retry_count'], 0)
                    if failure == 'identity':
                        f.set_value.assert_not_awaited()
                    else:
                        self.assertEqual(f.set_value.await_count, 1)






# H200_COMPAT TESTS
from security_cli import (install_empty_child_lists_compat, normalize_empty_child_lists)
import copy
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch






class h200_compat_NormalizeTests(unittest.TestCase):
    def test_exact_zero_entry_shape(self):
        response = {'start_index': 0, 'sum': 0}
        self.assertTrue(normalize_empty_child_lists(response, 'getChildDeviceComponentList'))
        self.assertEqual(response, {'start_index': 0, 'sum': 0, 'child_component_list': []})
        self.assertFalse(normalize_empty_child_lists(response, 'getChildDeviceComponentList'))

    def test_exact_zero_child_device_shape(self):
        response = {'start_index': 0, 'sum': 0}
        self.assertTrue(normalize_empty_child_lists(response, 'getChildDeviceList'))
        self.assertEqual(response, {'start_index': 0, 'sum': 0, 'child_device_list': []})
        self.assertFalse(normalize_empty_child_lists(response, 'getChildDeviceList'))

    def test_other_methods_never_changed(self):
        for method in ('getDeviceInfo', 'getAppComponentList', 'other'):
            response = {'start_index': 0, 'sum': 0}
            self.assertFalse(normalize_empty_child_lists(response, method))
            self.assertEqual(response, {'start_index': 0, 'sum': 0})

    def test_nonempty_uncertain_or_unexpected_shapes_not_changed(self):
        responses = [None, [], {}, {'start_index': 0},
                     {'start_index': 0, 'sum': 1}, {'start_index': 1, 'sum': 0},
                     {'start_index': False, 'sum': 0}, {'start_index': 0, 'sum': False},
                     {'start_index': 0.0, 'sum': 0}, {'start_index': 0, 'sum': '0'},
                     {'start_index': 0, 'sum': 0, 'unexpected': True},
                     {'start_index': 0, 'sum': 0, 'child_component_list': None},
                     {'start_index': 0, 'sum': 0, 'child_component_list': []}]
        for response in responses:
            with self.subTest(shape=type(response).__name__):
                before = copy.deepcopy(response)
                self.assertFalse(normalize_empty_child_lists(response, 'getChildDeviceComponentList'))
                self.assertEqual(response, before)


class h200_compat_InstallationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        class FakeSmartCamProtocol:
            def __init__(self):
                self._handle_response_lists = AsyncMock()
        self.protocol_class = FakeSmartCamProtocol
        module = types.ModuleType('kasa.protocols.smartcamprotocol')
        module.SmartCamProtocol = FakeSmartCamProtocol
        self.modules = patch.dict(sys.modules, {'kasa.protocols.smartcamprotocol': module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.version = patch('security_cli.version', return_value='0.10.2')
        self.version.start()
        self.addCleanup(self.version.stop)

    async def test_wrapper_is_instance_local_and_delegates(self):
        first, second = self.protocol_class(), self.protocol_class()
        original, untouched = first._handle_response_lists, second._handle_response_lists
        self.assertTrue(install_empty_child_lists_compat(first))
        self.assertIs(second._handle_response_lists, untouched)
        response = {'start_index': 0, 'sum': 0}
        await first._handle_response_lists(response, 'getChildDeviceComponentList', None, 0)
        original.assert_awaited_once_with(response, 'getChildDeviceComponentList', None, 0)
        self.assertEqual(response['child_component_list'], [])
        untouched.assert_not_awaited()

    async def test_upstream_errors_not_suppressed(self):
        protocol = self.protocol_class()
        protocol._handle_response_lists.side_effect = RuntimeError('synthetic')
        install_empty_child_lists_compat(protocol)
        with self.assertRaises(RuntimeError):
            await protocol._handle_response_lists({'sum': 1}, 'getChildDeviceComponentList', None, 0)

    async def test_other_versions_and_types_are_untouched(self):
        self.assertFalse(install_empty_child_lists_compat(None))
        self.assertFalse(install_empty_child_lists_compat(object()))
        protocol = self.protocol_class()
        original = protocol._handle_response_lists
        with patch('security_cli.version', return_value='0.10.3'):
            self.assertFalse(install_empty_child_lists_compat(protocol))
        self.assertIs(protocol._handle_response_lists, original)


class h200_compat_InstalledSdkRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_empty_page_regression_without_transport(self):
        try:
            from kasa.protocols.smartcamprotocol import SmartCamProtocol
        except ImportError:
            self.skipTest('Optional SDK is not installed')
        # No transport constructor, sockets, real configuration or credentials.
        protocol = object.__new__(SmartCamProtocol)
        protocol._execute_query = AsyncMock(side_effect=AssertionError('Unexpected query'))
        if not install_empty_child_lists_compat(protocol):
            self.skipTest('Workaround is intentionally pinned to SDK 0.10.2')
        for method, field in (('getChildDeviceList', 'child_device_list'),
                              ('getChildDeviceComponentList', 'child_component_list')):
            response = {'start_index': 0, 'sum': 0}
            await protocol._handle_response_lists(response, method, None, 0)
            self.assertEqual(response[field], [])
        protocol._execute_query.assert_not_awaited()


# HUB TESTS
from security_cli import (HubMonitor, HubReadError, Observation, Settings, read_h200, offline_status_main)


import asyncio
import contextlib
import io
import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch





hub_SETTINGS = Settings(host="192.168.1.20", username="private-user", password="private-secret")
hub_OBSERVATION = Observation("H200", "1.0", "1.3.6", ("alarm",))


class hub_SettingsTests(unittest.TestCase):
    def test_missing_configuration(self):
        self.assertEqual(Settings().missing, "missing_host")
        self.assertEqual(Settings(host="192.168.1.20").missing, "missing_credentials")
        self.assertIsNone(hub_SETTINGS.missing)

    def test_credentials_not_in_repr(self):
        self.assertNotIn("private-user", repr(hub_SETTINGS))
        self.assertNotIn("private-secret", repr(hub_SETTINGS))

    def test_env_is_explicit_and_does_not_reuse_plug_settings(self):
        self.assertEqual(Settings.from_env({"KASA_USERNAME": "x"}), Settings())
        configured = Settings.from_env({"JARVIS_SECURITY_HUB_HOST": " 192.168.1.20 ",
                                       "JARVIS_SECURITY_USERNAME": "CaseSensitive",
                                       "JARVIS_SECURITY_PASSWORD": " secret "})
        self.assertEqual(configured.host, hub_SETTINGS.host)
        self.assertEqual(configured.username, "CaseSensitive")
        self.assertEqual(configured.password, " secret ")

    def test_reject_invalid_or_non_lan_targets(self):
        for host in ["https://example.com", "example.com", "8.8.8.8", "127.0.0.1",
                     "0.0.0.0", "224.0.0.1", "169.254.1.1", "::1"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                Settings(host=host)

    def test_reject_invalid_deadlines(self):
        for key in ["timeout", "stale_after"]:
            for value in [0, -1, float("nan"), float("inf")]:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    Settings(**{key: value})


class hub_MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tick = 100.0
        self.reader = AsyncMock(return_value=hub_OBSERVATION)
        self.monitor = HubMonitor(hub_SETTINGS, reader=self.reader, clock=lambda: self.tick,
                                  wall_clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))

    async def test_missing_config_never_calls_reader(self):
        for settings in [Settings(), Settings(host=hub_SETTINGS.host)]:
            result = await HubMonitor(settings, reader=self.reader).probe()
            self.assertEqual(result["health"], "not_configured")
            self.assertIsNone(result["last_attempt_at"])
        self.reader.assert_not_awaited()

    async def test_snapshot_does_not_probe(self):
        self.assertEqual(self.monitor.snapshot()["health"], "unknown")
        self.reader.assert_not_awaited()

    async def test_success_is_not_security_assessment(self):
        result = await self.monitor.probe()
        self.assertEqual(result["health"], "online")
        self.assertEqual(result["security_assessment"], "not_assessed")
        self.assertEqual(result["observation"]["model"], "H200")
        self.assertIsNotNone(result["last_success_at"])
        self.reader.assert_awaited_once_with(hub_SETTINGS)

    async def test_exact_staleness_boundary(self):
        await self.monitor.probe()
        self.tick += 29.9
        self.assertEqual(self.monitor.snapshot()["health"], "online")
        self.tick = 130
        result = self.monitor.snapshot()
        self.assertEqual(result["health"], "stale")
        self.assertEqual(result["reason"], "reading_expired")

    async def test_failure_keeps_historical_reading_not_live_health(self):
        before = await self.monitor.probe()
        self.tick += 10
        self.reader.side_effect = OSError("private-secret")
        failed = await self.monitor.probe()
        self.assertEqual(failed["health"], "offline")
        self.assertEqual(failed["last_success_at"], before["last_success_at"])
        self.assertEqual(failed["observation"], before["observation"])
        self.assertEqual(failed["observation_age_seconds"], 10)
        self.tick += 60
        self.assertEqual(self.monitor.snapshot()["health"], "offline")
        self.assertNotIn("private-secret", json.dumps(failed))

    async def test_recovery_requires_successful_read(self):
        self.reader.side_effect = OSError()
        self.assertEqual((await self.monitor.probe())["health"], "offline")
        self.reader.side_effect = None
        self.assertEqual((await self.monitor.probe())["health"], "online")

    async def test_safe_error_classification(self):
        cases = [(HubReadError("authentication_failed"), "error", "authentication_failed"),
                 (HubReadError("unsupported_device"), "error", "unsupported_device"),
                 (HubReadError("dependency_unavailable"), "error", "dependency_unavailable"),
                 (HubReadError("unreachable"), "offline", "unreachable"),
                 (TimeoutError("private-secret"), "offline", "unreachable"),
                 (HubReadError("private-secret"), "error", "read_failed"),
                 (RuntimeError("private-secret"), "error", "read_failed")]
        for error, health, reason in cases:
            with self.subTest(reason=reason):
                self.reader.side_effect = error
                result = await self.monitor.probe()
                self.assertEqual((result["health"], result["reason"]), (health, reason))
                self.assertNotIn("private-secret", json.dumps(result))
                self.assertIsNone(result["last_success_at"])

    async def test_deadline(self):
        async def slow_reader(settings):
            await asyncio.sleep(60)
        monitor = HubMonitor(Settings(host=hub_SETTINGS.host, username="u", password="p", timeout=.01),
                             reader=slow_reader)
        result = await monitor.probe()
        self.assertEqual(result["health"], "offline")

    async def test_cancellation_does_not_preserve_online(self):
        await self.monitor.probe()
        self.reader.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.monitor.probe()
        self.assertEqual(self.monitor.snapshot()["health"], "unknown")
        self.assertEqual(self.monitor.snapshot()["reason"], "probe_cancelled")


class hub_TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Fake the optional dependency entirely: these tests cannot reach hardware.
        self.auth_error = type("AuthenticationError", (Exception,), {})
        self.device = types.SimpleNamespace(
            model="H200", device_type=types.SimpleNamespace(value="hub"),
            hw_info={"hw_ver": "1.0", "sw_ver": "1.3.6", "mac": "private-mac"},
            features={"alarm": object(), "volume": object()},
            update=AsyncMock(), disconnect=AsyncMock(),
            turn_on=AsyncMock(), turn_off=AsyncMock(),
        )
        self.discover = AsyncMock(return_value=self.device)
        self.kasa = types.ModuleType("kasa")
        self.kasa.AuthenticationError = self.auth_error
        self.kasa.Discover = types.SimpleNamespace(discover_single=self.discover)
        self.patch = patch.dict(sys.modules, {"kasa": self.kasa})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_single_host_read_only_and_cleanup(self):
        result = await read_h200(hub_SETTINGS)
        self.discover.assert_awaited_once_with(hub_SETTINGS.host, username=hub_SETTINGS.username,
            password=hub_SETTINGS.password, discovery_timeout=5, timeout=10)
        self.device.update.assert_awaited_once()
        self.device.disconnect.assert_awaited_once()
        self.device.turn_on.assert_not_called()
        self.device.turn_off.assert_not_called()
        self.assertEqual(result.capabilities, ("alarm", "volume"))
        self.assertEqual(result.firmware_version, "1.3.6")
        self.assertNotIn("private-mac", repr(result))

    async def test_identity_only_uses_one_read_without_full_update(self):
        self.device.protocol = types.SimpleNamespace(query=AsyncMock(return_value={
            "getDeviceInfo": {"device_info": {"basic_info": {
                "device_model": "H200", "device_type": "SMART.IPCAMERA.HUB",
                "hw_version": "1.0", "sw_version": "test-version",
                "device_id": "private-device-id"}}}}))
        diagnostic = {}
        result = await read_h200(hub_SETTINGS, diagnostics=diagnostic, identity_only=True)
        self.assertEqual(result.model, "H200")
        self.assertEqual(result.capabilities, ())
        self.assertEqual(diagnostic, {"stage": "identity_read"})
        self.assertNotIn("private-device-id", repr(result))
        self.device.update.assert_not_awaited()
        self.device.protocol.query.assert_awaited_once_with({
            "getDeviceInfo": {"device_info": {"name": ["basic_info"]}}})
        self.device.disconnect.assert_awaited_once()

    async def test_identity_only_rejects_wrong_discovery_before_read(self):
        self.device.model = "C230"
        with self.assertRaisesRegex(HubReadError, "unsupported_device"):
            await read_h200(hub_SETTINGS, identity_only=True)
        self.device.update.assert_not_awaited()
        self.device.disconnect.assert_awaited_once()

    async def test_identity_only_rejects_wrong_authenticated_identity(self):
        self.device.protocol = types.SimpleNamespace(query=AsyncMock(return_value={
            "getDeviceInfo": {"device_info": {"basic_info": {
                "device_model": "C230", "device_type": "SMART.IPCAMERA"}}}}))
        with self.assertRaisesRegex(HubReadError, "unsupported_device"):
            await read_h200(hub_SETTINGS, identity_only=True)
        self.device.disconnect.assert_awaited_once()

    async def test_identity_only_malformed_reply_is_not_online(self):
        self.device.protocol = types.SimpleNamespace(query=AsyncMock(return_value={}))
        async def reader(settings):
            return await read_h200(settings, identity_only=True)
        result = await HubMonitor(hub_SETTINGS, reader=reader).probe()
        self.assertEqual(result["health"], "error")
        self.device.disconnect.assert_awaited_once()

    async def test_reject_wrong_model_or_type(self):
        for model, kind in [("HS103", "plug"), ("H100", "hub"), ("H200", "camera")]:
            self.device.model = model
            self.device.device_type.value = kind
            with self.assertRaisesRegex(HubReadError, "unsupported_device"):
                await read_h200(hub_SETTINGS)
        self.assertEqual(self.device.disconnect.await_count, 3)

    async def test_no_device(self):
        self.discover.return_value = None
        with self.assertRaisesRegex(HubReadError, "unreachable"):
            await read_h200(hub_SETTINGS)

    async def test_auth_error_sanitized_and_connection_closed(self):
        self.device.update.side_effect = self.auth_error("private-secret")
        with self.assertRaisesRegex(HubReadError, "^authentication_failed$"):
            await read_h200(hub_SETTINGS)
        self.device.disconnect.assert_awaited_once()

    async def test_update_failure_still_closes_connection(self):
        self.device.update.side_effect = RuntimeError("private-secret")
        result = await HubMonitor(hub_SETTINGS).probe()
        self.assertEqual(result["reason"], "read_failed")
        self.assertNotIn("private-secret", json.dumps(result))
        self.device.disconnect.assert_awaited_once()

    async def test_diagnostics_never_include_exception_text(self):
        for exc, expected in [(KeyError("private-secret"), "KeyError"),
                              (RuntimeError("private-secret"), "RuntimeError"),
                              (type("SensitiveClassName", (Exception,), {})("private-secret"), "other"),
                              (self.auth_error("private-secret"), "AuthenticationError")]:
            self.device.update.side_effect = exc
            diagnostic = {}
            with self.assertRaises(Exception):
                await read_h200(hub_SETTINGS, diagnostics=diagnostic)
            self.assertEqual(diagnostic, {"stage": "update", "error_type": expected})
            self.assertNotIn("private-secret", json.dumps(diagnostic))

    async def test_cleanup_failure_does_not_mask_read(self):
        self.device.disconnect.side_effect = RuntimeError("private-secret")
        self.assertEqual((await read_h200(hub_SETTINGS)).model, "H200")

    async def test_cancellation_closes_connection(self):
        self.device.update.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await read_h200(hub_SETTINGS)
        self.device.disconnect.assert_awaited_once()

    async def test_optional_dependency_missing(self):
        with patch.dict(sys.modules, {"kasa": None}):
            with self.assertRaisesRegex(HubReadError, "dependency_unavailable"):
                await read_h200(hub_SETTINGS)


class hub_CliTests(unittest.TestCase):
    def run_cli(self, args, env):
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["security", *args]), \
                contextlib.redirect_stdout(output):
            code = offline_status_main()
        return code, json.loads(output.getvalue())

    def test_default_status_has_no_network(self):
        with patch.object(HubMonitor, "probe", new_callable=AsyncMock) as probe:
            code, result = self.run_cli(["status"], {})
            self.assertEqual((code, result["health"]), (2, "not_configured"))
            probe.assert_not_awaited()

    def test_configured_status_still_has_no_network(self):
        env = {"JARVIS_SECURITY_HUB_HOST": hub_SETTINGS.host,
               "JARVIS_SECURITY_USERNAME": "private-user", "JARVIS_SECURITY_PASSWORD": "private-secret"}
        with patch.object(HubMonitor, "probe", new_callable=AsyncMock) as probe:
            code, result = self.run_cli(["status"], env)
            self.assertEqual((code, result["health"]), (2, "unknown"))
            self.assertNotIn("private-secret", json.dumps(result))
            probe.assert_not_awaited()

    def test_invalid_config_is_sanitized(self):
        code, result = self.run_cli(["status"], {"JARVIS_SECURITY_HUB_HOST": "private-secret"})
        self.assertEqual((code, result["reason"]), (2, "invalid_config"))
        self.assertNotIn("private-secret", json.dumps(result))

    def test_probe_is_explicit(self):
        with patch.object(HubMonitor, "probe", new_callable=AsyncMock,
                          return_value={"health": "online"}) as probe:
            code, result = self.run_cli(["status", "--probe"], {})
            self.assertEqual(code, 0)
            probe.assert_awaited_once()






# PRIVATE_ENV TESTS
from security_cli import (PrivateEnvError, load_settings)
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch





class private_env_PrivateEnvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '.env'
        self.content = ('JARVIS_SECURITY_HUB_HOST=192.168.50.8\n'
                        'JARVIS_SECURITY_USERNAME=synthetic-email\n'
                        'JARVIS_SECURITY_PASSWORD=synthetic-secret\n')
        self.save(self.content)

    def save(self, text):
        self.path.write_text(text)
        self.path.chmod(0o600)

    def test_literals_and_optional_quotes(self):
        for password in ('literal # $HOME=$(command)=x', '" padded secret "', "'quoted-secret'"):
            self.save(self.content.replace('synthetic-secret', password))
            expected = password[1:-1] if password[0] in '\"\'' else password
            settings = load_settings(self.path)
            self.assertEqual(settings.password, expected)
            self.assertNotIn(expected, repr(settings))

    def test_permissions_required(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(PrivateEnvError, '^private_env_permissions$'):
            load_settings(self.path)

    def test_symlink_rejected(self):
        link = self.path.parent / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(PrivateEnvError):
            load_settings(link)

    def test_malformed_and_incomplete_are_sanitized(self):
        for text in (self.content + 'PRIVATE=synthetic-secret\n',
                     self.content + 'JARVIS_SECURITY_USERNAME=duplicate\n',
                     self.content.replace('192.168.50.8', 'synthetic-secret'),
                     self.content.replace('synthetic-secret', ''),
                     self.content.replace('synthetic-secret', '"unterminated'),
                     'synthetic-secret'):
            with self.subTest(length=len(text)):
                self.save(text)
                with self.assertRaises(PrivateEnvError) as caught:
                    load_settings(self.path)
                self.assertNotIn('synthetic-secret', str(caught.exception))

    def test_no_environment_fallback(self):
        self.save('JARVIS_SECURITY_HUB_HOST=192.168.50.8\n')
        with patch.dict('os.environ', {'JARVIS_SECURITY_USERNAME': 'u',
                                      'JARVIS_SECURITY_PASSWORD': 'p'}):
            with self.assertRaisesRegex(PrivateEnvError, 'incomplete_private_env'):
                load_settings(self.path)

    def test_cli_does_not_print_settings_or_observations(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(security_cli, 'HubMonitor') as monitor, \
                patch.object(security_cli.logging, 'disable'):
            monitor.return_value.probe = AsyncMock(return_value={
                'health': 'online', 'reason': None, 'security_assessment': 'not_assessed',
                'observation': {'private': 'DO-NOT-PRINT'}})
            self.assertEqual(security_cli.check_env_main(['--env-file', str(self.path)]), 0)
        public = json.loads(output.getvalue())
        self.assertEqual(set(public), {'health', 'reason', 'security_assessment'})
        for secret in ('synthetic-secret', 'synthetic-email', '192.168.50.8', 'DO-NOT-PRINT'):
            self.assertNotIn(secret, output.getvalue())
        monitor.return_value.probe.assert_awaited_once()

    def test_invalid_file_never_probes(self):
        self.path.chmod(0o644)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(security_cli, 'HubMonitor') as monitor, \
                patch.object(security_cli.logging, 'disable'):
            self.assertEqual(security_cli.check_env_main(['--env-file', str(self.path)]), 2)
        monitor.assert_not_called()


# SENSORS TESTS
from security_cli import (SensorObservation, SensorTracker)
"""Synthetic observations only. No device API or network dependency is imported."""


import json
import unittest
from datetime import datetime, timedelta, timezone




sensors_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class sensors_ObservationTests(unittest.TestCase):
    def test_supported_states(self):
        for model, states in [("T100", ["motion", "clear", "unknown"]),
                              ("T110", ["open", "closed", "unknown"])]:
            for state in states:
                with self.subTest(model=model, state=state):
                    reading = SensorObservation("test", model, state, sensors_START)
                    self.assertEqual(reading.state, state)
                    self.assertIsNone(reading.battery_percent)
                    self.assertIsNone(reading.low_battery)

    def test_wrong_model_state_and_missing_identity_rejected(self):
        for sensor_id, model, state in [("", "T100", "clear"), (" ", "T110", "closed"),
                ("test", "H200", "closed"), ("test", "T100", "closed"),
                ("test", "T110", "clear"), ("test", "T110", False)]:
            with self.subTest(model=model, state=state), self.assertRaises(ValueError):
                SensorObservation(sensor_id, model, state, sensors_START)

    def test_no_implicit_false_or_string_coercion(self):
        for value in [True, False, "false", "0", 0, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                SensorObservation("test", "T100", value, sensors_START)

    def test_battery_validation(self):
        for battery in [-1, 101, True, "50", 50.5]:
            with self.subTest(battery=battery), self.assertRaises(ValueError):
                SensorObservation("test", "T110", "open", sensors_START, battery_percent=battery)
        for flag in [0, 1, "false"]:
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                SensorObservation("test", "T110", "open", sensors_START, low_battery=flag)

    def test_battery_fields_are_independent_not_inferred(self):
        for battery, low in [(0, None), (100, None), (None, True), (None, False), (50, True)]:
            reading = SensorObservation("test", "T110", "closed", sensors_START, battery, low)
            self.assertEqual((reading.battery_percent, reading.low_battery), (battery, low))

    def test_aware_timestamp_required(self):
        for when in [sensors_START.replace(tzinfo=None), "2026-01-01", None]:
            with self.subTest(when=when), self.assertRaises(ValueError):
                SensorObservation("test", "T100", "motion", when)

    def test_json_timestamp_in_utc(self):
        offset = sensors_START.astimezone(timezone(timedelta(hours=-4)))
        reading = SensorObservation("test", "T100", "motion", offset)
        result = json.loads(json.dumps(reading.as_dict()))
        self.assertEqual(result["observed_at"], sensors_START.isoformat())


class sensors_TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tick = 0.0
        self.wall = sensors_START
        self.door = self.tracker("door-test", "T110")
        self.motion = self.tracker("motion-test", "T100")

    def tracker(self, sensor_id, model):
        # 30 seconds is a synthetic test threshold, not a deployed polling policy.
        return SensorTracker(sensor_id, model, stale_after=30,
                             clock=lambda: self.tick, wall_clock=lambda: self.wall)

    def advance(self, seconds):
        self.tick += seconds
        self.wall += timedelta(seconds=seconds)

    def reading(self, tracker, state, **kwargs):
        when = kwargs.pop("observed_at", self.wall)
        return SensorObservation(tracker.sensor_id, tracker.model, state, when, **kwargs)

    def test_initial_state_is_unknown_not_closed_or_clear(self):
        for tracker in [self.door, self.motion]:
            snap = tracker.snapshot()
            self.assertEqual((snap["health"], snap["state"]), ("unknown", "unknown"))
            self.assertIsNone(snap["last_observation"])
            self.assertIsNone(snap["low_battery"])
            self.assertEqual(snap["security_assessment"], "not_assessed")

    def test_initial_active_reading_is_silent_baseline(self):
        for tracker, state in [(self.door, "open"), (self.motion, "motion")]:
            self.assertIsNone(tracker.accept(self.reading(tracker, state)))
            snap = tracker.snapshot()
            self.assertEqual((snap["health"], snap["state"]), ("online", state))
            self.assertEqual(snap["security_assessment"], "not_assessed")

    def test_consecutive_changes_for_both_models(self):
        for tracker, off, on in [(self.door, "closed", "open"), (self.motion, "clear", "motion")]:
            tracker.accept(self.reading(tracker, off))
            self.advance(1)
            change = tracker.accept(self.reading(tracker, on))
            self.assertEqual((change.previous, change.current), (off, on))
            self.assertEqual(change.sensor_id, tracker.sensor_id)
            self.advance(1)
            change = tracker.accept(self.reading(tracker, off))
            self.assertEqual((change.previous, change.current), (on, off))

    def test_unchanged_new_reading_refreshes_without_duplicate_change(self):
        self.door.accept(self.reading(self.door, "closed"))
        self.advance(20)
        self.assertIsNone(self.door.accept(self.reading(self.door, "closed")))
        self.assertEqual(self.door.snapshot()["observation_age_seconds"], 0)

    def test_repeated_active_samples_do_not_repeat_changes(self):
        self.motion.accept(self.reading(self.motion, "clear"))
        self.advance(1)
        self.assertIsNotNone(self.motion.accept(self.reading(self.motion, "motion")))
        for _ in range(3):
            self.advance(1)
            self.assertIsNone(self.motion.accept(self.reading(self.motion, "motion")))

    def test_duplicate_and_out_of_order_do_not_refresh_or_change_state(self):
        reading = self.reading(self.door, "closed")
        self.door.accept(reading)
        self.advance(5)
        self.assertIsNone(self.door.accept(reading))
        self.assertIsNone(self.door.accept(self.reading(self.door, "open", observed_at=sensors_START)))
        older = self.reading(self.door, "open", observed_at=sensors_START - timedelta(seconds=1))
        self.assertIsNone(self.door.accept(older))
        self.assertEqual(self.door.snapshot()["state"], "closed")
        self.assertEqual(self.door.snapshot()["observation_age_seconds"], 5)

    def test_stale_hides_state_and_battery_but_preserves_labelled_history(self):
        self.door.accept(self.reading(self.door, "closed", battery_percent=80, low_battery=False))
        self.advance(29.9)
        self.assertEqual(self.door.snapshot()["state"], "closed")
        self.advance(.1)
        snap = self.door.snapshot()
        self.assertEqual((snap["health"], snap["state"]), ("stale", "unknown"))
        self.assertIsNone(snap["battery_percent"])
        self.assertIsNone(snap["low_battery"])
        self.assertEqual(snap["last_observation"]["state"], "closed")
        self.assertEqual(snap["last_observation"]["battery_percent"], 80)
        json.dumps(snap)

    def test_recovery_after_expiry_is_silent_even_without_snapshot(self):
        self.door.accept(self.reading(self.door, "closed"))
        self.advance(30)
        self.assertIsNone(self.door.accept(self.reading(self.door, "open")))
        self.advance(1)
        self.assertIsNotNone(self.door.accept(self.reading(self.door, "closed")))

    def test_disconnect_and_error_mask_old_state_and_rebaseline(self):
        for reason in ["offline", "error"]:
            tracker = self.tracker("test", "T110")
            tracker.accept(self.reading(tracker, "closed"))
            tracker.mark_unavailable(reason)
            self.assertEqual(tracker.snapshot()["health"], reason)
            self.assertEqual(tracker.snapshot()["state"], "unknown")
            self.advance(1)
            self.assertIsNone(tracker.accept(self.reading(tracker, "open")))
            self.advance(1)
            self.assertIsNotNone(tracker.accept(self.reading(tracker, "closed")))

    def test_replaying_duplicate_does_not_heal_outage(self):
        reading = self.reading(self.door, "closed")
        self.door.accept(reading)
        self.door.mark_unavailable()
        self.advance(1)
        self.assertIsNone(self.door.accept(reading))
        self.assertEqual(self.door.snapshot()["health"], "offline")
        self.assertEqual(self.door.snapshot()["state"], "unknown")

    def test_unknown_breaks_continuity(self):
        self.motion.accept(self.reading(self.motion, "clear"))
        self.advance(1)
        self.assertIsNone(self.motion.accept(self.reading(self.motion, "unknown")))
        self.assertEqual(self.motion.snapshot()["state"], "unknown")
        self.advance(1)
        self.assertIsNone(self.motion.accept(self.reading(self.motion, "motion")))

    def test_delayed_stale_observation_is_not_fresh_on_arrival(self):
        self.advance(60)
        self.assertIsNone(self.door.accept(self.reading(self.door, "closed", observed_at=sensors_START)))
        snap = self.door.snapshot()
        self.assertEqual((snap["health"], snap["state"]), ("stale", "unknown"))
        self.assertEqual(snap["observation_age_seconds"], 60)

    def test_delayed_newer_sample_cannot_generate_reconstructed_change(self):
        self.door.accept(self.reading(self.door, "closed"))
        self.advance(60)
        replay = self.reading(self.door, "open", observed_at=sensors_START + timedelta(seconds=1))
        self.assertIsNone(self.door.accept(replay))
        self.assertEqual(self.door.snapshot()["state"], "unknown")
        self.assertIsNone(self.door.accept(self.reading(self.door, "closed")))

    def test_clock_adjustment_does_not_rejuvenate_existing_observation(self):
        self.door.accept(self.reading(self.door, "closed"))
        self.tick += 30
        self.wall -= timedelta(hours=1)
        self.assertEqual(self.door.snapshot()["health"], "stale")

    def test_future_timestamp_invalidates_baseline(self):
        self.door.accept(self.reading(self.door, "closed"))
        with self.assertRaises(ValueError):
            self.door.accept(self.reading(self.door, "open", observed_at=sensors_START + timedelta(days=1)))
        self.assertEqual(self.door.snapshot()["state"], "unknown")
        self.assertEqual(self.door.snapshot()["health"], "error")
        self.advance(1)
        self.assertIsNone(self.door.accept(self.reading(self.door, "open")))

    def test_mismatched_sensor_does_not_contaminate_tracker(self):
        with self.assertRaises(ValueError):
            self.door.accept(self.reading(self.motion, "motion"))
        self.assertIsNone(self.door.snapshot()["last_observation"])
        wrong_model = SensorObservation(self.door.sensor_id, "T100", "motion", sensors_START)
        with self.assertRaises(ValueError):
            self.door.accept(wrong_model)

    def test_invalid_tracker_options_and_unavailable_reason(self):
        for limit in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                SensorTracker("test", "T100", stale_after=limit)
        with self.assertRaises(ValueError):
            self.tracker("test", "H200")
        with self.assertRaises(ValueError):
            self.door.mark_unavailable("secret exception text")

    def test_restart_starts_silently_without_replaying_changes(self):
        self.door.accept(self.reading(self.door, "closed"))
        self.advance(1)
        restarted = self.tracker(self.door.sensor_id, self.door.model)
        self.assertIsNone(restarted.accept(self.reading(restarted, "open")))

    def test_low_battery_change_is_not_a_contact_event(self):
        self.door.accept(self.reading(self.door, "closed", low_battery=False))
        self.advance(1)
        self.assertIsNone(self.door.accept(self.reading(self.door, "closed", low_battery=True)))
        self.assertTrue(self.door.snapshot()["low_battery"])






# STORAGE TESTS
from security_cli import (Settings, StorageReadError, storage_probe_main, normalize_status, probe_storage, read_storage)
import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch






storage_SETTINGS = Settings(host='192.168.50.8', username='synthetic-user', password='synthetic-secret')


def storage_reply(**fields):
    return {'get': {'harddisk_manage': {'hd_info': [{'hd_info_1': fields}]}}}


class storage_NormalizeTests(unittest.TestCase):
    def test_no_card_response_is_not_recording_or_physical_absence_proof(self):
        result = normalize_status(storage_reply(status='offline', detect_status='offline'))
        self.assertEqual(result['card_state'], 'offline')
        self.assertEqual(result['health'], 'online')
        for field in ('recording', 'playback', 'download', 'security_assessment'):
            self.assertEqual(result[field], 'not_assessed')

    def test_synthetic_normal_capacity_is_metadata_only(self):
        result = normalize_status(storage_reply(status='normal', detect_status='normal', rw_attr='rw',
                                        total_space='100.00 GB', free_space='90.00 GB'))
        self.assertEqual(result['access_mode'], 'read_write')
        self.assertEqual(result['reported_total_space'], '100.00 GB')
        self.assertEqual(result['reported_free_space'], '90.00 GB')
        self.assertEqual(result['playback'], 'not_assessed')

    def test_offline_masks_retained_capacity_and_access(self):
        result = normalize_status(storage_reply(status='offline', detect_status='offline', rw_attr='rw',
                                        total_space='100 GB', free_space='90 GB'))
        self.assertIsNone(result['reported_total_space'])
        self.assertIsNone(result['reported_free_space'])
        self.assertEqual(result['access_mode'], 'unknown')

    def test_unrecognized_or_missing_values_never_become_normal(self):
        for fields in ({}, {'status': False}, {'status': 'synthetic-secret'}, {'status': []}):
            result = normalize_status(storage_reply(**fields))
            self.assertEqual(result['card_state'], 'unknown')
            self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_invalid_or_sensitive_capacity_is_not_echoed(self):
        result = normalize_status(storage_reply(status='normal', detect_status='normal', rw_attr='synthetic-secret',
                                        total_space='synthetic-secret', free_space='90 GB; hidden'))
        self.assertEqual(result['access_mode'], 'unknown')
        self.assertIsNone(result['reported_total_space'])
        self.assertIsNone(result['reported_free_space'])
        self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_malformed_empty_and_ambiguous_tables_fail_closed(self):
        for response in (None, [], {}, {'get': None},
                         {'get': {'harddisk_manage': {'hd_info': []}}},
                         {'get': {'harddisk_manage': {'hd_info': [{}, {}]}}},
                         {'get': {'harddisk_manage': {'hd_info': [{'private-key': {}}]}}}):
            with self.assertRaisesRegex(StorageReadError, '^invalid_storage_response$'):
                normalize_status(response)

    def test_status_is_offline_only_without_probe(self):
        output = io.StringIO()
        with patch('security_cli.load_settings') as load, \
                patch('security_cli.probe_storage') as probe, \
                contextlib.redirect_stdout(output):
            self.assertEqual(storage_probe_main(['--env-file', 'not-read.env']), 2)
        load.assert_not_called()
        probe.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['card_state'], 'unknown')


class storage_TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.auth_error = type('AuthenticationError', (Exception,), {})
        self.device = types.SimpleNamespace(
            model='H200', device_type=types.SimpleNamespace(value='hub'),
            protocol=types.SimpleNamespace(query=AsyncMock(return_value=storage_reply(status='offline', detect_status='offline'))),
            disconnect=AsyncMock(), update=AsyncMock())
        self.discover = AsyncMock(return_value=self.device)
        module = types.ModuleType('kasa')
        module.AuthenticationError = self.auth_error
        module.Discover = types.SimpleNamespace(discover_single=self.discover)
        replacement = patch.dict(sys.modules, {'kasa': module})
        replacement.start()
        self.addCleanup(replacement.stop)

    async def test_exact_single_getter_no_update_or_retry_and_cleanup(self):
        result = await read_storage(storage_SETTINGS)
        self.discover.assert_awaited_once_with(storage_SETTINGS.host, username=storage_SETTINGS.username,
            password=storage_SETTINGS.password, discovery_timeout=5, timeout=10)
        self.device.protocol.query.assert_awaited_once_with(
            {'get': {'harddisk_manage': {'table': ['hd_info']}}}, retry_count=0)
        self.device.update.assert_not_awaited()
        self.device.disconnect.assert_awaited_once()
        self.assertIsNotNone(result['observed_at'])
        self.assertNotIn(storage_SETTINGS.password, json.dumps(result))

    async def test_rejects_nonhub_before_storage_read(self):
        self.device.model = 'C230'
        result = await probe_storage(storage_SETTINGS)
        self.assertEqual(result['reason'], 'unsupported_device')
        self.device.protocol.query.assert_not_awaited()
        self.device.disconnect.assert_awaited_once()

    async def test_auth_error_is_sanitized_and_cleanup_runs(self):
        self.device.protocol.query.side_effect = self.auth_error('synthetic-secret')
        result = await probe_storage(storage_SETTINGS)
        self.assertEqual(result['reason'], 'authentication_failed')
        self.assertEqual(result['card_state'], 'unknown')
        self.assertNotIn('synthetic-secret', json.dumps(result))
        self.device.disconnect.assert_awaited_once()

    async def test_network_and_unexpected_failures_do_not_imply_no_card(self):
        for exc, health in ((TimeoutError('synthetic-secret'), 'offline'),
                            (RuntimeError('synthetic-secret'), 'error'),
                            (StorageReadError('synthetic-secret'), 'error')):
            result = await probe_storage(storage_SETTINGS, reader=AsyncMock(side_effect=exc))
            self.assertEqual(result['health'], health)
            self.assertEqual(result['card_state'], 'unknown')
            self.assertIsNone(result['observed_at'])
            self.assertNotIn('synthetic-secret', json.dumps(result))

    async def test_missing_config_never_contacts_network(self):
        result = await probe_storage(Settings())
        self.assertEqual(result['health'], 'not_configured')
        self.discover.assert_not_awaited()

    async def test_no_device(self):
        self.discover.return_value = None
        self.assertEqual((await probe_storage(storage_SETTINGS))['reason'], 'unreachable')

    async def test_cleanup_failure_does_not_mask_read(self):
        self.device.disconnect.side_effect = RuntimeError('synthetic-secret')
        self.assertEqual((await probe_storage(storage_SETTINGS))['card_state'], 'offline')

    async def test_optional_dependency_missing(self):
        with patch.dict(sys.modules, {'kasa': None}):
            result = await probe_storage(storage_SETTINGS)
        self.assertEqual(result['reason'], 'dependency_unavailable')


class PairedSensorTests(unittest.TestCase):
    def test_registered_sensors(self):
        import security_cli as cli
        devices = cli.registry()
        self.assertEqual(devices['motion-sensor']['model'], 'T100')
        self.assertEqual(devices['door-sensor']['model'], 'T110')

    def test_sensor_writes_rejected(self):
        import security_cli as cli
        for model in cli.SENSOR_MODELS:
            for command in ('set', 'action', 'privacy', 'move', 'storage'):
                with self.assertRaises(cli.ControlError):
                    cli.validate_request(model, command, 'reboot', 'on', True, True)

    def test_selection_fails_closed(self):
        from types import SimpleNamespace
        import security_cli as cli
        entry = {'model': 'T100', 'name': 'Motion Sensor'}
        child = SimpleNamespace(model='T100', alias='Motion Sensor')
        self.assertIs(cli.select_sensor(SimpleNamespace(children=[child]), entry), child)
        for children in ([], [child, child], [SimpleNamespace(model='T110', alias='Motion Sensor')]):
            with self.assertRaises(cli.ControlError):
                cli.select_sensor(SimpleNamespace(children=children), entry)

    def test_missing_features_unknown(self):
        from types import SimpleNamespace
        import security_cli as cli
        result = cli.sensor_inventory(SimpleNamespace(features={}), 'T110')
        self.assertEqual(result['is_open']['status'], 'unknown')
        self.assertEqual(result['battery_low']['status'], 'unknown')
        self.assertTrue(all(not row['writable'] for row in result.values()))


if __name__ == '__main__':
    unittest.main()
