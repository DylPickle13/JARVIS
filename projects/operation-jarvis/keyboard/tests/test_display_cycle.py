import copy
import subprocess
import unittest
from unittest.mock import patch

import cycle
import display_cycle as display
import display_session


class Store:
    def __init__(self):
        self.data = {'display-config.json': {'enabled': True}}

    def load(self, name, default):
        return copy.deepcopy(self.data.get(name, default))

    def save(self, name, value):
        self.data[name] = copy.deepcopy(value)


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.actions = []

    def tick(self, t, state='away', stale=False, apply=None):
        payload = {'ok': True, 'zones': [{'zone': 'basement', 'subject': 'dylan',
                   'stale': stale, 'ageSeconds': 0, 'state': state}]}
        return display.run_once(self.store, now=lambda: t,
                                get_presence=lambda: payload,
                                apply=apply or self.actions.append)

    def away(self):
        for t in range(0, 121, 10):
            self.tick(t)

    def test_disabled(self):
        self.store.data.clear()
        self.away()
        self.assertEqual(self.actions, [])

    def test_two_away_checks_once_and_return_once(self):
        self.tick(0, 'nearby')
        self.tick(3)
        self.assertEqual(self.actions, [])
        self.tick(6)
        self.assertEqual(self.actions, ['lock-sleep'])
        self.tick(120)
        self.tick(130)
        self.tick(140, 'nearby')
        self.tick(150, 'nearby')
        self.assertEqual(self.actions, ['lock-sleep', 'wake'])

    def test_no_startup_wake(self):
        self.tick(0, 'nearby')
        self.assertEqual(self.actions, [])

    def test_unknown_and_stale_do_not_act(self):
        self.tick(0, 'nearby')
        self.tick(3, 'unknown')
        self.tick(6, stale=True)
        self.assertEqual(self.actions, [])
        self.tick(9)
        self.assertEqual(self.actions, [])
        self.tick(12)
        self.assertEqual(self.actions, ['lock-sleep'])

    def test_gap_and_clock_reversal_reset_confirmation(self):
        self.tick(0)
        self.tick(100)
        self.tick(90)
        self.assertEqual(self.actions, [])
        self.tick(93)
        self.assertEqual(self.actions, ['lock-sleep'])

    def test_single_false_away_does_not_sleep(self):
        self.tick(0, 'nearby')
        self.tick(3)
        self.tick(6, 'nearby')
        self.tick(9)
        self.assertEqual(self.actions, [])
        self.tick(12)
        self.assertEqual(self.actions, ['lock-sleep'])

    def test_unknown_or_stale_breaks_confirmation(self):
        for state, stale in [('unknown', False), ('away', True)]:
            with self.subTest(state=state, stale=stale):
                self.store = Store()
                self.actions = []
                self.tick(0)
                self.tick(3, state, stale=stale)
                self.tick(6)
                self.assertEqual(self.actions, [])
                self.tick(9)
                self.assertEqual(self.actions, ['lock-sleep'])

    def test_same_timestamp_does_not_confirm(self):
        self.tick(0)
        self.tick(0)
        self.assertEqual(self.actions, [])

    def test_persisted_away_does_not_repeat(self):
        self.away()
        self.tick(1000)
        self.assertEqual(self.actions, ['lock-sleep'])

    def test_failure_blocks_even_return(self):
        self.tick(0, 'nearby')
        def fail(action):
            raise subprocess.TimeoutExpired('helper', 8)
        self.tick(117)
        output, code = self.tick(120, apply=fail)
        self.assertEqual(code, 1)
        self.assertTrue(output.startswith('ERROR:'))
        self.tick(130, 'nearby')
        self.assertEqual(self.actions, [])
        self.assertTrue(self.store.data['display-state.json']['pending'])

    def test_corrupt_state_blocks(self):
        self.store.data['display-state.json'] = {'pending': False}
        with self.assertRaises(cycle.CycleError):
            self.tick(0)

    def test_sleep_only_after_verified_lock(self):
        with patch.object(display_session, 'locked', return_value=True), \
                patch.object(display_session.subprocess, 'run') as run:
            display_session.perform('lock-sleep')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/pmset', 'displaysleepnow'])

    def test_no_sleep_if_lock_unconfirmed(self):
        with patch.object(display_session, 'locked', return_value=False), \
                patch.object(display_session.C, 'CDLL'), \
                patch.object(display_session.time, 'sleep'), \
                patch.object(display_session.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                display_session.perform('lock-sleep')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
