import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arrival_cycle as arrival


class Store:
    def __init__(self):
        self.data = {'arrival-config.json': {'enabled': True}}
    def load(self, name, default):
        return self.data.get(name, default)
    def save(self, name, value):
        self.data[name] = dict(value)


class ArrivalTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.send = Mock()

    def step(self, at, mode='away', age=0):
        payload = {'ok': True, 'zones': [{'zone': 'basement', 'subject': 'dylan',
            'state': mode, 'stale': False, 'ageSeconds': age}]}
        arrival.run_once(self.store, now=lambda: at, get_presence=lambda: payload, apply=self.send)

    def absence(self, start=0):
        for at in range(start, start + 34, 3): self.step(at)

    def test_once_after_absence(self):
        self.absence()
        self.step(36, 'nearby')
        self.step(39, 'nearby')
        self.send.assert_called_once()
        self.assertEqual(self.store.data['arrival-state.json']['lastAttempt'], 36)

    def test_startup_and_short_absence(self):
        self.step(0, 'nearby')
        self.step(3)
        self.step(6, 'nearby')
        self.send.assert_not_called()

    def test_unknown_breaks_absence(self):
        self.absence()
        self.step(36, 'unknown')
        self.step(39, 'nearby')
        self.send.assert_not_called()

    def test_gap_and_stale_and_negative_age(self):
        for age in (16, -1):
            self.absence()
            self.step(36, 'away', age)
            self.step(39, 'nearby')
        self.absence()
        self.step(100, 'nearby')
        self.send.assert_not_called()

    def test_restart_does_not_greet(self):
        self.absence()
        self.store.data['arrival-state.json']['boot'] = 'old'
        self.step(36, 'nearby')
        self.send.assert_not_called()

    def test_failure_consumed_before_dispatch(self):
        self.absence()
        self.send.side_effect = RuntimeError('uncertain')
        self.step(36, 'nearby')
        self.step(39, 'nearby')
        self.send.assert_called_once()

    def test_disabled(self):
        self.store.data.clear()
        self.absence()
        self.step(36, 'nearby')
        self.send.assert_not_called()

    def test_cooldown_suppresses_bouncing_and_never_greets_late(self):
        self.absence()
        self.step(36, 'nearby')
        self.absence(60)
        self.step(96, 'nearby')
        self.assertEqual(self.store.data['arrival-state.json']['lastAttempt'], 36)
        for at in range(99, 220, 3):
            self.step(at, 'nearby')
        self.send.assert_called_once()
        self.absence(222)
        self.step(258, 'nearby')
        self.assertEqual(self.send.call_count, 2)

    def test_exact_three_minute_boundary(self):
        for second_return, calls in ((215, 1), (216, 2)):
            with self.subTest(second_return=second_return):
                self.store = Store()
                self.send = Mock()
                self.absence()
                self.step(36, 'nearby')
                self.absence(second_return - 36)
                self.step(second_return, 'nearby')
                self.assertEqual(self.send.call_count, calls)

    def test_restart_preserves_cooldown_but_resets_absence(self):
        self.absence()
        self.step(36, 'nearby')
        self.store.data['arrival-state.json']['boot'] = 'old'
        self.step(39, 'nearby')
        self.assertEqual(self.store.data['arrival-state.json']['lastAttempt'], 36)
        self.absence(60)
        self.step(96, 'nearby')
        self.send.assert_called_once()

    def test_uncertain_dispatch_still_starts_cooldown(self):
        self.send.side_effect = RuntimeError('uncertain')
        self.absence()
        self.step(36, 'nearby')
        self.absence(60)
        self.step(96, 'nearby')
        self.send.assert_called_once()
        self.assertEqual(self.store.data['arrival-state.json']['lastAttempt'], 36)

    def test_invalid_or_future_attempt_timestamp_never_bypasses_cooldown(self):
        for timestamp in ('bad', float('nan'), True, -1, 500):
            with self.subTest(timestamp=timestamp):
                self.store = Store()
                self.send = Mock()
                self.store.data['arrival-state.json'] = {'boot': 'old', 'lastAttempt': timestamp}
                self.absence()
                self.step(36, 'nearby')
                self.send.assert_not_called()

    def test_invalid_clock_never_dispatches(self):
        self.absence()
        for at in (float('nan'), -1, True):
            self.step(at, 'nearby')
        self.send.assert_not_called()

    def test_master_off_discards_absence_without_erasing_cooldown(self):
        self.absence()
        state = self.store.data['arrival-state.json']
        state['lastAttempt'] = 10
        with patch.object(arrival.automatic_voice, 'current', return_value=arrival.automatic_voice.Policy(False, 'b'*32)):
            self.step(36, 'nearby')
        self.assertEqual(state['lastAttempt'], 10)
        self.assertIsNone(state['awaySince'])
        self.send.assert_not_called()

    def test_off_on_generation_cannot_backfill_old_absence(self):
        self.absence()
        with patch.object(arrival.automatic_voice, 'current', return_value=arrival.automatic_voice.Policy(True, 'b'*32)):
            self.step(36, 'nearby')
        self.send.assert_not_called()
        self.assertIsNone(self.store.data['arrival-state.json']['awaySince'])

    def test_policy_change_before_dispatch_consumes_without_speech(self):
        self.absence()
        with patch.object(arrival.automatic_voice, 'admitted', return_value=False):
            self.step(36, 'nearby')
        self.send.assert_not_called()
        self.assertEqual(self.store.data['arrival-state.json']['lastAttempt'], 36)

    def test_save_failure_blocks_dispatch(self):
        self.absence()
        self.store.save = Mock(side_effect=OSError())
        self.step(36, 'nearby')
        self.send.assert_not_called()
