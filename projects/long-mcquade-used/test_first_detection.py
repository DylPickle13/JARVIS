import unittest

import used_scraper as watcher


class FirstDetectionTests(unittest.TestCase):
    def test_opt_in_alerts_only_for_future_discoveries_without_faking_baseline(self):
        state = watcher.fresh_state()
        state['initial_output_enabled'] = False
        watcher.record_units(state, [{'id': 'existing'}])
        self.assertEqual(state['pending_alerts'], [])
        first_seen = state['known_units']['existing']['first_seen']
        state['alert_on_first_detection'] = True
        watcher.record_units(state, [{'id': 'existing'}, {'id': 'new'}])
        self.assertEqual(state['pending_alerts'], [{'id': 'new', 'initial_inventory': False}])
        self.assertFalse(state['baseline_complete'])
        self.assertFalse(state['initial_output_enabled'])
        self.assertEqual(state['known_units']['existing']['first_seen'], first_seen)
        watcher.record_units(state, [{'id': 'new'}])
        self.assertEqual(len(state['pending_alerts']), 1)

    def test_default_still_seeds_silently(self):
        state = watcher.fresh_state()
        state['initial_output_enabled'] = False
        watcher.record_units(state, [{'id': 'new'}])
        self.assertEqual(state['pending_alerts'], [])


if __name__ == '__main__':
    unittest.main()
