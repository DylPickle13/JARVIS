import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cycle
import led_cycle as led
import watch
from test_cycle import presence


class LEDTests(unittest.TestCase):
    def setUp(self):
        self.state = led.initial()
        self.faults = set()
        self.apply = Mock(return_value=True)
        self.save = Mock()

    def tick(self, now, location='nearby', **extra):
        led.tick(self.state, self.faults, now=now,
                 get_presence=lambda: presence(location, **extra),
                 apply=self.apply, save=self.save)

    def test_transitions(self):
        self.tick(100)
        self.tick(103, 'away')
        self.tick(106)
        self.assertEqual([c.args[0] for c in self.apply.call_args_list], ['on', 'off', 'on'])
        self.assertFalse(self.state['pending'])

    def test_no_repeat_after_restart(self):
        self.tick(100)
        self.state = led.validate_state(dict(self.state))
        self.tick(103)
        self.tick(500)
        self.apply.assert_called_once()

    def test_unknown_stale_wrong_subject_unchanged(self):
        self.tick(100, 'unknown')
        self.tick(103, 'away', stale=True)
        self.tick(106, 'away', ageSeconds=16)
        self.tick(109, 'away', subject='someone_else')
        self.apply.assert_not_called()

    def test_pending_saved_before_write(self):
        snapshots = []
        self.save.side_effect = lambda s: snapshots.append(dict(s))
        def apply(*args):
            self.assertTrue(snapshots[-1]['pending'])
            return True
        self.apply.side_effect = apply
        self.tick(100)
        self.assertFalse(snapshots[-1]['pending'])

    def test_uncertain_blocks_retries_across_restart_and_transitions(self):
        self.apply.side_effect = TimeoutError()
        self.tick(100)
        self.state = led.validate_state(dict(self.state))
        self.tick(200, 'away')
        self.tick(300)
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])
        self.assertIn('led', self.faults)

    def test_expired_before_dispatch_waits_for_fresh_presence(self):
        self.apply.return_value = False
        self.tick(100)
        self.assertFalse(self.state['pending'])
        self.assertIsNone(self.state['last_mode'])
        self.assertIn('presence', self.faults)
        self.apply.return_value = True
        self.tick(103)
        self.assertEqual(self.state['last_mode'], 'on')

    def test_snapshot_ages_during_save(self):
        clock = iter([100, 100, 116])
        led.tick(self.state, self.faults, now=100,
                 get_presence=lambda: presence('nearby'), apply=self.apply,
                 save=self.save, monotonic=lambda: next(clock))
        self.apply.assert_not_called()
        self.assertFalse(self.state['pending'])

    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            store = cycle.Store(Path(d))
            led.run_once(store, get_presence=Mock(side_effect=AssertionError()), apply=self.apply)
            self.apply.assert_not_called()

    def test_fixed_cli_and_strict_readback(self):
        payload = dict(result='verified', device='led-strip', model='L930-5', setting='state', value=True)
        with patch.object(led.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps(payload).encode())) as run:
            self.assertTrue(led.send('on', 123))
            self.assertEqual(run.call_args.args[0][-5:], ['state', 'on', '--confirm', '--presence-deadline', '123'])
            self.assertIn('light-set', run.call_args.args[0])
            self.assertIn('--presence-deadline', run.call_args.args[0])
            payload['value'] = False
            run.return_value.stdout = json.dumps(payload).encode()
            with self.assertRaises(RuntimeError):
                led.send('on', 123)

    def test_probe_read_only_consumed_and_preserves_latch(self):
        with tempfile.TemporaryDirectory() as d:
            store = cycle.Store(Path(d))
            state = {**led.initial(), 'pending': True}
            store.save('led-state.json', state)
            store.save('led-probe-request.json', True)
            def execute(argv, **kwargs):
                self.assertFalse(store.load('led-probe-request.json', True))
                self.assertEqual(argv[-3:], ['--json', 'status', 'led-strip'])
                return Mock(returncode=2, stdout=b'{"reason":"timeout","stage":"connection"}')
            with patch.object(led.subprocess, 'run', side_effect=execute) as run:
                led.probe_once(store)
                led.probe_once(store)
                run.assert_called_once()
            self.assertEqual(store.load('led-state.json', None), state)
            self.assertEqual(store.load('led-probe-result.json', {})['reason'], 'timeout')

    def test_failed_write_diagnostic_persisted_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            store = cycle.Store(Path(d))
            store.save('led-config.json', {'enabled': True})
            apply = Mock(side_effect=led.LightingError({'reason': 'timeout', 'stage': 'connection'}))
            for now in (100, 200):
                led.run_once(store, now=lambda: now, get_presence=lambda: presence('nearby'), apply=apply)
            apply.assert_called_once()
            self.assertTrue(store.load('led-state.json', {})['pending'])
            self.assertEqual(store.load('led-failure.json', {})['reason'], 'timeout')

    def test_probe_timeout_consumed(self):
        with tempfile.TemporaryDirectory() as d:
            store = cycle.Store(Path(d))
            store.save('led-probe-request.json', True)
            with patch.object(led.subprocess, 'run', side_effect=led.subprocess.TimeoutExpired('secret', 29)) as run:
                led.probe_once(store)
                led.probe_once(store)
                run.assert_called_once()
            self.assertEqual(store.load('led-probe-result.json', {})['reason'], 'subprocess_timeout')

    def test_diagnostic_does_not_capture_secrets(self):
        for output in (b'private-secret', b'{"reason":"private-secret","stage":"private-secret"}', b'[]', b'{"reason":{}}'):
            details = led.response_diagnostic(Mock(returncode=2, stdout=output, stderr=b'private-secret'))
            self.assertNotIn('private-secret', json.dumps(details))

    def test_alert_relay_recognizes_led(self):
        self.assertEqual(watch.alert_component('ERROR: ' + led.MESSAGES['led']), 'led')
        with tempfile.TemporaryDirectory() as d:
            store = cycle.Store(Path(d))
            store.save('led-alerts.json', ['led'])
            self.assertIn('owner review', watch.controller_status(store)['led'][0])
