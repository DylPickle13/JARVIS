"""Offline departure commissioning tests; no household reads or speech."""
import asyncio
import base64
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import departure
import security_cli as cli

START = datetime(2026, 9, 29, 16, tzinfo=timezone.utc)  # Toronto noon.


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = departure.DepartureDetector()

    def sample(self, tick, motion=False, opened=False, **kwargs):
        return departure.Sample(tick, kwargs.pop('observed_at', START + timedelta(seconds=tick)),
                                motion, opened, **kwargs)

    def feed(self, tick, motion=False, opened=False, **kwargs):
        return self.detector.accept(self.sample(tick, motion, opened, **kwargs))

    def arm(self):
        self.feed(0)
        self.feed(2, True)

    def test_departure_is_silent_candidate_not_verified(self):
        self.arm()
        result = self.feed(4, True, True)
        self.assertEqual(result['decision'], 'candidate')
        self.assertEqual(result['delivery'], 'disabled')
        self.assertFalse(result['departure_verified'])

    def test_initial_motion_or_open_door_never_arms(self):
        for motion, opened in ((True, False), (False, True), (True, True)):
            self.detector = departure.DepartureDetector()
            self.assertEqual(self.feed(0, motion, opened)['reason'], 'baseline')
            self.assertEqual(self.feed(2, True, True)['decision'], 'suppressed')

    def test_arrival_is_never_candidate(self):
        self.feed(0)
        self.feed(2, False, True)
        self.assertEqual(self.feed(4, True, True)['decision'], 'suppressed')
        self.feed(6, True, False)
        self.assertEqual(self.feed(8, True, True)['decision'], 'suppressed')

    def test_opening_without_motion_is_suppressed(self):
        self.feed(0)
        self.assertEqual(self.feed(2, False, True)['reason'], 'no_recent_indoor_motion_edge')

    def test_simultaneous_edges_are_ambiguous_and_consumed(self):
        self.arm()
        self.feed(3, False)
        self.assertEqual(self.feed(4, True, True)['reason'], 'simultaneous_changes')
        self.feed(6, True, False)
        self.assertEqual(self.feed(8, True, True)['decision'], 'suppressed')

    def test_opted_in_same_sample_edges_and_cooldown(self):
        self.detector = departure.DepartureDetector(allow_simultaneous=True)
        self.feed(0)
        result = self.feed(2, True, True)
        self.assertEqual(result['reason'], 'same_sample_motion_and_opening')
        self.assertEqual(result['decision'], 'candidate')
        self.assertEqual(self.feed(4, True, True)['decision'], 'suppressed')
        self.feed(6)
        self.assertEqual(self.feed(8, True, True)['reason'], 'cooldown')

    def test_same_sample_mode_preserves_baselines_gaps_and_separate_arrivals(self):
        for mode in ('initial', 'reset', 'gap', 'arrival'):
            self.detector = departure.DepartureDetector(allow_simultaneous=True)
            if mode != 'initial': self.feed(0)
            if mode == 'reset': self.detector.reset()
            if mode == 'arrival': self.feed(1, False, True)
            self.assertEqual(self.feed(10 if mode == 'gap' else 2, True, True)['decision'], 'suppressed')

    def test_close_mode_waits_indefinitely_with_continuous_samples(self):
        self.detector = departure.DepartureDetector(allow_simultaneous=True, require_close=True)
        self.feed(0)
        self.assertEqual(self.feed(2, True, True)['reason'], 'qualified_opening_waiting_for_close')
        for tick in range(4, 604, 2):
            self.assertEqual(self.feed(tick, False, True)['decision'], 'suppressed')
        self.assertEqual(self.feed(604, False, False)['reason'], 'qualified_opening_then_close')
        self.assertEqual(self.feed(606, False, False)['decision'], 'suppressed')
        self.feed(608, True, True)
        self.assertEqual(self.feed(610, False, False)['reason'], 'cooldown')

    def test_close_mode_drops_interrupted_opening_and_unqualified_arrivals(self):
        for interrupt in ('reset', 'gap', 'unknown', 'slow', 'arrival', 'initial'):
            self.detector = departure.DepartureDetector(allow_simultaneous=True, require_close=True)
            if interrupt != 'initial': self.feed(0)
            self.feed(2, interrupt != 'arrival', True)
            if interrupt == 'reset': self.detector.reset()
            if interrupt == 'unknown': self.feed(3, None, True)
            if interrupt == 'slow': self.feed(3, True, True, read_seconds=3)
            result = self.feed(20 if interrupt == 'gap' else 4, False, False)
            self.assertEqual(result['decision'], 'suppressed', interrupt)
            self.assertEqual(self.feed(22 if interrupt == 'gap' else 6)['decision'], 'suppressed')

    def test_close_mode_accepts_ordered_opening_and_closing_once(self):
        self.detector = departure.DepartureDetector(require_close=True)
        self.arm()
        self.assertEqual(self.feed(4, True, True)['decision'], 'suppressed')
        self.assertEqual(self.feed(6, False, False)['decision'], 'candidate')
        self.assertEqual(self.feed(8, False, False)['decision'], 'suppressed')

    def test_too_short_motion_lead_is_suppressed(self):
        self.arm()
        self.assertEqual(self.feed(2.1, True, True)['decision'], 'suppressed')

    def test_motion_expires_despite_repeated_active_readings(self):
        self.arm()
        for tick in range(4, 25, 2):
            self.feed(tick, True)
        self.assertEqual(self.feed(26, True, True)['decision'], 'suppressed')

    def test_window_boundary(self):
        self.arm()
        for tick in (8, 14, 20):
            self.feed(tick, True)
        self.assertEqual(self.feed(22, True, True)['decision'], 'candidate')

    def test_group_has_only_one_candidate(self):
        self.arm()
        self.feed(4, True, True)
        for tick in (6, 8, 10):
            self.assertEqual(self.feed(tick, True, True)['decision'], 'suppressed')

    def test_cooldown_blocks_reopening_and_new_motion(self):
        self.arm()
        self.feed(4, True, True)
        self.feed(6, False, False)
        self.feed(8, True)
        self.assertEqual(self.feed(10, True, True)['reason'], 'cooldown')
        # Suppressed opening consumed the arm too.
        self.feed(12, True, False)
        self.assertEqual(self.feed(14, True, True)['decision'], 'suppressed')

    def test_cooldown_allows_later_new_session(self):
        self.arm()
        self.feed(4, True, True)
        for tick in range(6, 123, 2):
            self.feed(tick)
        self.feed(124, True)
        self.assertEqual(self.feed(126, True, True)['decision'], 'candidate')

    def test_cooldown_survives_reset(self):
        self.arm()
        self.feed(4, True, True)
        self.detector.reset()
        self.feed(6)
        self.feed(8, True)
        self.assertEqual(self.feed(10, True, True)['reason'], 'cooldown')

    def test_unknown_breaks_sequence_and_recovery_is_baseline(self):
        for values in ((None, False), (True, None)):
            self.detector = departure.DepartureDetector()
            self.arm()
            self.assertEqual(self.feed(3, *values)['reason'], 'unknown_sensor_state')
            self.assertEqual(self.feed(4, True, True)['reason'], 'baseline')

    def test_slow_read_breaks_continuity(self):
        self.arm()
        self.assertEqual(self.feed(4, True, True, read_seconds=2.01)['reason'], 'slow_read')
        self.assertEqual(self.feed(6, True, True)['reason'], 'baseline')

    def test_gaps_duplicates_reordering_break_sequence(self):
        for tick in (2, 1, 11):
            self.detector = departure.DepartureDetector()
            self.arm()
            self.assertEqual(self.feed(tick, True, True)['reason'], 'observation_discontinuity')
            self.assertEqual(self.feed(tick + 2, True, True)['reason'], 'baseline')

    def test_wall_clock_jump_breaks_sequence(self):
        self.arm()
        self.assertEqual(self.feed(4, True, True, observed_at=START + timedelta(hours=1))['reason'],
                         'observation_discontinuity')

    def test_24_hour_eligibility_in_summer_and_winter(self):
        for at in (datetime(2026, 9, 29, hour, tzinfo=timezone.utc) for hour in range(24)):
            self.detector = departure.DepartureDetector()
            self.feed(0, observed_at=at - timedelta(seconds=4))
            self.feed(2, True, observed_at=at - timedelta(seconds=2))
            self.assertEqual(self.feed(4, True, True, observed_at=at)['decision'], 'candidate')
        for at in (datetime(2026, 12, 1, hour, tzinfo=timezone.utc) for hour in range(24)):
            self.detector = departure.DepartureDetector()
            self.feed(0, observed_at=at - timedelta(seconds=4))
            self.feed(2, True, observed_at=at - timedelta(seconds=2))
            self.assertEqual(self.feed(4, True, True, observed_at=at)['decision'], 'candidate')

    def test_invalid_samples(self):
        for kwargs in ({'tick': True}, {'tick': float('nan')}, {'tick': -1},
                       {'motion': 1}, {'opened': 'false'}, {'read_seconds': float('inf')},
                       {'read_seconds': -1}, {'observed_at': datetime(2026, 1, 1)}):
            args = {'tick': 0, **kwargs}
            with self.assertRaises(ValueError):
                self.sample(**args)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = patch('runtime.ROOT', Path(self.directory.name))
        self.override.start()
        self.addCleanup(self.override.stop)

    def args(self, *extra):
        return departure.parser().parse_args(list(extra))

    def entries(self):
        return {'hub': {'model': 'H200', 'host': '@hub'},
                'motion-sensor': {'model': 'T100', 'hub': 'hub', 'name': 'Fixture motion'},
                'door-sensor': {'model': 'T110', 'hub': 'hub', 'name': 'Fixture door'}}

    def test_status_offline_no_registry_or_audio(self):
        with patch.object(cli, 'registry') as registry, patch('security_audio.execute_audio') as audio:
            result = departure.execute_departure(self.args())
        registry.assert_not_called()
        audio.assert_not_called()
        self.assertFalse(result['delivery_enabled'])
        self.assertFalse(result['arrival_enabled'])
        self.assertFalse(result['background_listener'])
        self.assertEqual(result['active_hours'], '24/7')
        self.assertIsNone(result['quiet_hours'])
        self.assertFalse(result['quiet_hours_active'])

    def test_cli_dispatch(self):
        out = io.StringIO()
        with patch('sys.stdout', out), patch.object(cli, 'registry') as registry:
            self.assertEqual(departure.main(['--json', 'status']), 0)
        self.assertEqual(json.loads(out.getvalue())['mode'], 'silent')
        registry.assert_not_called()

    def test_invalid_window_before_registry(self):
        for flags in (('--seconds', '9'), ('--seconds', '301'), ('--interval', '1'), ('--interval', '6')):
            with patch.object(cli, 'registry') as registry, self.assertRaises(cli.ControlError):
                departure.execute_departure(self.args('observe', *flags))
            registry.assert_not_called()

    def test_no_speech_enable_flag(self):
        with self.assertRaises(cli.ControlError):
            self.args('observe', '--enable-speech')

    def test_registry_pair_validation(self):
        for mutation in ('missing', 'model', 'hub', 'hub_model'):
            entries = self.entries()
            if mutation == 'missing':
                del entries['door-sensor']
            elif mutation == 'model':
                entries['door-sensor']['model'] = 'C230'
            elif mutation == 'hub':
                entries['door-sensor']['hub'] = 'different'
            else:
                entries['hub']['model'] = 'C230'
            with patch.object(cli, 'registry', return_value=entries), self.assertRaises(cli.ControlError):
                departure.validate_devices(self.args('observe'), cli)

    def test_validated_pair(self):
        entries = self.entries()
        with patch.object(cli, 'registry', return_value=entries):
            result = departure.validate_devices(self.args('observe'), cli)
        self.assertEqual(result[0], 'hub')

    def response(self, motion=False, opened=False):
        return {'getChildDeviceList': {'child_device_list': [
            {'device_id': 'private-motion', 'model': 'T100', 'detected': motion,
             'nickname': base64.b64encode(b'Fixture motion').decode()},
            {'device_id': 'private-door', 'model': 'T110', 'open': opened,
             'nickname': base64.b64encode(b'Fixture door').decode()}]}}

    def states(self, response):
        return departure.paired_states(response, 'private-motion', 'private-door', cli)

    def test_select_child_ids_uses_exact_name_model_and_identity(self):
        entries = self.entries()
        self.assertEqual(departure.select_child_ids(self.response(), entries['motion-sensor'],
            entries['door-sensor'], cli), ('private-motion', 'private-door'))

    def test_select_child_ids_rejects_ambiguity_bad_names_and_identity(self):
        entries = self.entries()
        for kind in ('duplicate', 'nickname', 'identity', 'model'):
            response = self.response()
            rows = response['getChildDeviceList']['child_device_list']
            if kind == 'duplicate': rows.append(rows[0])
            elif kind == 'nickname': rows[0]['nickname'] = 'not-base64!'
            elif kind == 'identity': rows[0]['device_id'] = ''
            else: rows[0]['model'] = 'T110'
            with self.assertRaises(cli.ControlError):
                departure.select_child_ids(response, entries['motion-sensor'], entries['door-sensor'], cli)

    def test_raw_device_model_supported_without_conflicting_identity(self):
        response = self.response()
        for row in response['getChildDeviceList']['child_device_list']:
            row['device_model'] = row.pop('model') + '(US)'
        self.assertEqual(self.states(response), (False, False))
        response['getChildDeviceList']['child_device_list'][0]['model'] = 'C230'
        with self.assertRaises(cli.ControlError): self.states(response)

    def test_paired_states_strict_booleans(self):
        self.assertEqual(self.states(self.response(True, False)), (True, False))
        self.assertEqual(self.states(self.response(1, 'false')), (None, None))

    def test_paired_states_reject_missing_duplicate_or_changed_identity(self):
        for change in ('missing', 'duplicate', 'model'):
            response = self.response()
            rows = response['getChildDeviceList']['child_device_list']
            if change == 'missing':
                rows.pop()
            elif change == 'duplicate':
                rows.append(rows[0])
            else:
                rows[0]['model'] = 'C230'
            with self.assertRaises(cli.ControlError):
                self.states(response)

    def test_paired_states_reject_bad_schema(self):
        for response in ({}, None, {'getChildDeviceList': None},
                         {'getChildDeviceList': {'child_device_list': [None]}},
                         {'getChildDeviceList': {'child_device_list': [{}] * 129}}):
            with self.assertRaises(cli.ControlError):
                self.states(response)

    def observer(self, failure=None, identity='H200'):
        tick = [0.0]
        count = [0]
        async def query(request, **kwargs):
            tick[0] += 0.2
            if 'getDeviceInfo' in request:
                return {'getDeviceInfo': {'device_info': {'basic_info': {'device_model': identity}}}}
            count[0] += 1
            if failure:
                raise failure
            return self.response(count[0] >= 3, count[0] >= 4)
        async def sleep(seconds):
            tick[0] += seconds
        device = NS(model='H200', device_type=NS(value='hub'), config=NS(http_client=None),
                    protocol=NS(query=AsyncMock(side_effect=query)),
                    update=AsyncMock(), disconnect=AsyncMock())
        original = device.protocol.query
        adapter = NS(ControlError=cli.ControlError,
            load_settings=Mock(return_value=NS(host='192.0.2.1', username='fixture', password='fixture', missing=None)),
            device_lock=Mock(return_value=nullcontext()),
            install_empty_child_lists_compat=Mock(),
            select_sensor=Mock(side_effect=[NS(device_id='private-motion'), NS(device_id='private-door')]))
        entries = self.entries()
        pair = ('hub', entries['hub'], entries['motion-sensor'], entries['door-sensor'])
        with patch('kasa.Discover.discover_single', new_callable=AsyncMock, return_value=device):
            result = asyncio.run(departure.observe(self.args('observe', '--seconds', '10'),
                adapter, pair, clock=lambda: tick[0],
                wall_clock=lambda: START + timedelta(seconds=tick[0]), sleep=sleep))
        return result, device, original, adapter

    def test_observer_paired_reads_identity_locks_bounds_and_cleanup(self):
        result, device, query, adapter = self.observer()
        adapter.device_lock.assert_called_once_with('hub')
        device.update.assert_not_awaited()
        device.disconnect.assert_awaited_once()
        self.assertFalse(result['delivery_enabled'])
        self.assertEqual(sum(row['decision'] == 'candidate' for row in result['observations']), 1)
        self.assertLessEqual(len(result['observations']), 5)
        self.assertNotIn('private-', json.dumps(result))
        for call in query.await_args_list:
            self.assertEqual(call.kwargs['retry_count'], 0)
            self.assertTrue(set(call.args[0]) <= {'getDeviceInfo', 'getChildDeviceList'})

    def test_timeout_stops_no_retry_and_disconnects(self):
        result, device, query, _ = self.observer(TimeoutError())
        self.assertEqual(result['end_reason'], 'read_timeout')
        self.assertEqual(result['observations'], [])
        self.assertEqual(query.await_count, 2)
        device.disconnect.assert_awaited_once()

    def test_failure_disconnects_without_retry(self):
        with self.assertRaises(cli.ControlError):
            self.observer(cli.ControlError('fixture_failure'))

    def test_identity_failure_prevents_observation(self):
        with self.assertRaisesRegex(cli.ControlError, 'device_identity_mismatch'):
            self.observer(identity='C230')


if __name__ == '__main__':
    unittest.main()
