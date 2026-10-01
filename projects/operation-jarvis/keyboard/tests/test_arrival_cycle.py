import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

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

    def absence(self):
        for at in range(0, 34, 3): self.step(at)

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

    def test_save_failure_blocks_dispatch(self):
        self.absence()
        self.store.save = Mock(side_effect=OSError())
        self.step(36, 'nearby')
        self.send.assert_not_called()
