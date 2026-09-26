from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cycle
import mouse_cycle as mouse
import razer_bridge
import watch
from test_cycle import presence


class MouseTests(unittest.TestCase):
    def setUp(self):
        self.state = mouse.initial()
        self.faults = set()
        self.apply = Mock()
        self.save = Mock()

    def tick(self, now, location='nearby', **extra):
        mouse.tick(self.state, self.faults, now=now, get_presence=lambda: presence(location, **extra),
                   apply=self.apply, save=self.save)

    def test_nearby_steady_away_off_never_breathing(self):
        self.tick(100)
        self.tick(103, 'away')
        self.tick(106)
        self.assertEqual([c.args[0] for c in self.apply.call_args_list], ['steady', 'off', 'steady'])
        self.assertFalse(self.state['pending'])

    def test_unchanged_presence_and_restart_do_not_repeat(self):
        self.tick(100)
        self.state = mouse.validate_state(dict(self.state))
        for t in [103, 160, 500]:
            self.tick(t)
        self.apply.assert_called_once_with('steady')

    def test_unknown_stale_and_wrong_subject_do_not_change_light(self):
        self.tick(100)
        self.tick(103, 'unknown')
        self.tick(106, 'away', stale=True)
        self.tick(109, 'away', ageSeconds=16)
        self.tick(112, 'away', subject='someone_else')
        self.apply.assert_called_once_with('steady')
        self.tick(115, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertFalse(self.faults)

    def test_pending_persisted_before_send(self):
        snapshots = []
        self.save.side_effect = lambda s: snapshots.append(dict(s))
        self.apply.side_effect = lambda _: self.assertTrue(snapshots[-1]['pending'])
        self.tick(100)
        self.assertFalse(snapshots[-1]['pending'])

    def test_uncertain_survives_restart_and_presence_changes(self):
        self.apply.side_effect = razer_bridge.RazerBridgeError('lost reply', uncertain=True)
        self.tick(100)
        self.state = mouse.validate_state(dict(self.state))
        for t in [103, 160, 1000]:
            self.tick(t, 'away')
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])

    def test_unknown_exception_is_uncertain(self):
        self.apply.side_effect = RuntimeError('unknown')
        self.tick(100)
        self.assertTrue(self.state['pending'])
        self.tick(200)
        self.apply.assert_called_once()

    def test_prewrite_failure_cools_down_full_minute(self):
        self.apply.side_effect = razer_bridge.RazerBridgeError('unavailable', uncertain=False)
        self.tick(100)
        for t in [103, 106, 157]:
            self.tick(t, 'away')
        self.apply.assert_called_once()
        self.assertFalse(self.state['pending'])
        self.apply.side_effect = None
        self.tick(160, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertFalse(self.faults)

    def test_no_sub_three_second_transition(self):
        self.tick(100)
        self.tick(101, 'away')
        self.tick(102, 'away')
        self.apply.assert_called_once()
        self.tick(103, 'away')
        self.assertEqual(self.apply.call_count, 2)

    def test_expired_before_submission_clears_reservation_without_sending(self):
        monotonic = Mock(side_effect=[0, 1, 2, 20])
        mouse.tick(self.state, self.faults, now=100, get_presence=lambda: presence(),
                   apply=self.apply, save=self.save, monotonic=monotonic)
        self.apply.assert_not_called()
        self.assertFalse(self.state['pending'])
        self.assertIn('presence', self.faults)

    def test_sender_allowlist_excludes_breathing(self):
        with patch.object(razer_bridge, 'request') as request:
            mouse.send('steady')
            mouse.send('off')
            with self.assertRaises(ValueError):
                mouse.send('breathing')
            self.assertEqual([c.args[1]['value'] for c in request.call_args_list], [1, 0])

    def test_keyboard_white_migration_preserves_pending_and_breath_preference(self):
        old = cycle.initial() | dict(version=3, away_applied=True, pending=True, last_effect='breath')
        new = cycle.validate_state(old)
        self.assertEqual(new['version'], 4)
        self.assertTrue(new['pending'])
        self.assertFalse(new['away_applied'])
        self.assertEqual(new['last_effect'], 'breath')
        effects, values = cycle.preferences((cycle.ROOT / 'liked-effects.md').read_text())
        self.assertIn('breath', effects)
        self.assertEqual(values['color'], '#FFFFFF')
        self.assertEqual(cycle.AWAY['color'], '#FFFFFF')


class SharedWatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = cycle.Store(Path(self.temp.name) / 'runtime')

    def test_one_presence_fetch_for_two_devices_and_mouse_ignores_keyboard_fault(self):
        fetch = Mock(return_value=presence())
        keyboard = Mock(side_effect=cycle.CycleError('keyboard', uncertain=True))
        mouse_sender = Mock()
        watch.step(self.store, now=lambda: 100, get_presence=fetch, apply=keyboard, mouse_apply=mouse_sender)
        fetch.assert_called_once()
        mouse_sender.assert_called_once_with('steady')
        self.assertTrue(self.store.load('state.json', {})['pending'])
        self.assertFalse(self.store.load('mouse-state.json', {})['pending'])

    def test_shared_presence_failure_sends_nothing(self):
        fetch = Mock(side_effect=cycle.CycleError('presence'))
        keyboard, mouse_sender = Mock(), Mock()
        watch.step(self.store, now=lambda: 100, get_presence=fetch, apply=keyboard, mouse_apply=mouse_sender)
        fetch.assert_called_once()
        keyboard.assert_not_called()
        mouse_sender.assert_not_called()

    def test_mouse_ages_snapshot_after_slow_keyboard_operation(self):
        clock = [0]
        def keyboard(_):
            clock[0] = 16
        mouse_sender = Mock()
        with patch('time.monotonic', side_effect=lambda: clock[0]):
            watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(),
                       apply=keyboard, mouse_apply=mouse_sender)
        mouse_sender.assert_not_called()
        self.assertIn('presence', self.store.load('mouse-alerts.json', []))

    def test_mouse_error_and_recovery_are_latched(self):
        mouse_sender = Mock(side_effect=razer_bridge.RazerBridgeError('offline', uncertain=False))
        for now in (100, 103, 106):
            watch.step(self.store, now=lambda: now, get_presence=lambda: presence(),
                       apply=Mock(), mouse_apply=mouse_sender)
        self.assertEqual(len(self.store.load('watcher.json', {})['alerts']), 1)
        mouse_sender.side_effect = None
        watch.step(self.store, now=lambda: 160, get_presence=lambda: presence(),
                   apply=Mock(), mouse_apply=mouse_sender)
        alerts = self.store.load('watcher.json', {})['alerts']
        self.assertEqual(len(alerts), 2)
        self.assertTrue(alerts[-1]['message'].startswith('RECOVERED: Mouse'))

    def test_corrupt_mouse_state_blocks_mouse_only(self):
        self.store.save('mouse-state.json', {'bad': True})
        keyboard, mouse_sender = Mock(), Mock()
        watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(),
                   apply=keyboard, mouse_apply=mouse_sender)
        keyboard.assert_called_once()
        mouse_sender.assert_not_called()


if __name__ == '__main__':
    unittest.main()
