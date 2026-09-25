import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cycle
import watch
from test_cycle import presence, prefs


class ResponsiveTests(unittest.TestCase):
    def setUp(self):
        self.state = cycle.initial()
        self.faults = set()
        self.apply = Mock()

    def tick(self, now, location='nearby', **extra):
        cycle.tick(self.state, self.faults, now=now,
                   get_presence=lambda: presence(location, **extra),
                   get_preferences=prefs, apply=self.apply, save=Mock(),
                   choose=lambda choices: choices[0], responsive=True)

    def test_first_fresh_nearby_applies_immediately_then_rotates_only_each_minute(self):
        self.tick(100)
        self.apply.assert_called_once()
        first = self.apply.call_args.args[0]['effect']
        for now in range(103, 160, 3):
            self.tick(now)
        self.apply.assert_called_once()
        self.tick(160)
        self.assertEqual(self.apply.call_count, 2)
        self.assertNotEqual(first, self.apply.call_args.args[0]['effect'])

    def test_away_and_return_bypass_minute_timer_without_extra_debounce(self):
        self.tick(100)
        self.tick(103, 'away')
        self.assertEqual(self.apply.call_args.args[0], cycle.AWAY)
        self.assertEqual(self.apply.call_count, 2)
        self.tick(106, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.tick(109)
        self.assertEqual(self.apply.call_count, 3)
        self.assertNotEqual(self.apply.call_args.args[0]['effect'], 'ripples')
        self.assertFalse(self.state['away_applied'])
        for now in range(112, 169, 3):
            self.tick(now)
        self.assertEqual(self.apply.call_count, 3)
        self.tick(169)
        self.assertEqual(self.apply.call_count, 4)

    def test_no_catchup_or_sub_three_second_transition_writes(self):
        self.tick(100)
        self.tick(101, 'away'); self.tick(102, 'away')
        self.apply.assert_called_once()
        self.tick(103, 'away')
        self.assertEqual(self.apply.call_count, 2)

    def test_known_failure_cooldown_survives_presence_flips(self):
        self.apply.side_effect = cycle.CycleError('keyboard')
        self.tick(100, 'away')
        for now in range(103, 160, 3):
            self.tick(now, 'away' if now % 2 else 'nearby')
        self.apply.assert_called_once()
        self.apply.side_effect = None
        self.tick(160, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertFalse(self.faults)

    def test_uncertain_write_stays_blocked_through_restart_and_presence_flips(self):
        self.apply.side_effect = cycle.CycleError('keyboard', uncertain=True)
        self.tick(100)
        self.state = cycle.validate_state(dict(self.state))
        for now in (103, 160, 220):
            self.tick(now, 'away')
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])

    def test_unknown_never_changes_lighting_then_first_fresh_away_applies(self):
        self.tick(100)
        self.tick(103, 'unknown', stale=True, ageSeconds=None)
        self.apply.assert_called_once()
        self.tick(106, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.apply.call_args.args[0], cycle.AWAY)

    def test_stale_at_final_deadline_sends_nothing(self):
        with patch.object(cycle.time, 'monotonic', side_effect=[0, 1, 16]):
            self.tick(100, 'away')
        self.apply.assert_not_called()
        self.assertFalse(self.state['pending'])
        self.assertIn('presence', self.faults)

    def test_black_v2_migrates_without_claiming_purple_ripples_already_applied(self):
        old = cycle.initial()
        old.pop('away_applied')
        old.update(version=2, lighting_dark=True, mode='dark', pending=True, last_effect='scan')
        new = cycle.validate_state(old)
        self.assertEqual(new['version'], 3)
        self.assertFalse(new['away_applied'])
        self.assertTrue(new['pending'])
        self.assertEqual(new['last_effect'], 'scan')
        self.assertNotIn('lighting_dark', new)

    def test_away_profile_persists_without_repeated_write_after_restart(self):
        self.tick(100, 'away')
        self.state = cycle.validate_state(dict(self.state))
        self.tick(500, 'away')
        self.apply.assert_called_once_with(cycle.AWAY)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = cycle.Store(Path(self.temp.name) / 'runtime')

    def relay(self, now):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = watch.relay(self.store, now=lambda: now)
        return output.getvalue(), code

    def test_healthy_steps_and_relay_are_silent(self):
        sender = Mock()
        watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=sender)
        sender.assert_called_once()
        self.assertEqual(self.relay(103), ('', 0))

    def test_durable_error_once_and_successful_recovery_once(self):
        sender = Mock(side_effect=cycle.CycleError('keyboard'))
        for now in (100, 103, 106):
            watch.step(self.store, now=lambda: now, get_presence=lambda: presence('away'), apply=sender)
        sender.assert_called_once()
        result = self.relay(109)
        self.assertEqual(result[0].count('ERROR:'), 1)
        self.assertEqual(result[1], 1)
        self.assertEqual(self.relay(110), ('', 0))
        sender.side_effect = None
        watch.step(cycle.Store(self.store.directory), now=lambda: 160,
                   get_presence=lambda: presence('away'), apply=sender)
        result = self.relay(163)
        self.assertEqual(result[0].count('RECOVERED:'), 1)
        self.assertIn('Purple ripples', result[0])
        self.assertEqual(result[1], 0)
        self.assertEqual(self.relay(164), ('', 0))

    def test_missing_watcher_reports_once_then_recovers_without_hid_from_relay(self):
        self.assertEqual(self.relay(100)[1], 1)
        self.assertEqual(self.relay(160), ('', 0))
        watch.step(self.store, now=lambda: 163, get_presence=lambda: presence(), apply=Mock())
        with patch.object(cycle, 'send', side_effect=AssertionError('No relay HID')):
            result = self.relay(166)
        self.assertIn('RECOVERED:', result[0])
        self.assertIn('not lighting readback', result[0])
        self.assertEqual(self.relay(169), ('', 0))

    def test_stale_heartbeat_alert_is_latched(self):
        watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=Mock())
        self.assertEqual(self.relay(131)[1], 1)
        self.assertEqual(self.relay(200), ('', 0))

    def test_corrupt_outbox_blocks_step_before_any_hid(self):
        self.store.save('watcher.json', {'alerts': []})
        sender = Mock()
        with self.assertRaises(cycle.CycleError):
            watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=sender)
        sender.assert_not_called()

    def test_single_watcher_and_shared_cycle_lock(self):
        with watch.locked(self.store, 'watcher.lock'):
            with self.assertRaises(BlockingIOError):
                with watch.locked(self.store, 'watcher.lock'):
                    self.fail('second watcher acquired singleton lock')
        with watch.locked(self.store, 'cycle.lock'):
            with self.assertRaises(BlockingIOError):
                with watch.locked(self.store, 'cycle.lock'):
                    self.fail('overlapping step acquired cycle lock')


if __name__ == '__main__':
    unittest.main()
