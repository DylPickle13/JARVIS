"""Unidentified sale listings must not block or create invented unit alerts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import used_scraper as watcher
from test_used_scraper import TASK, FakeClient, details


def contact_only():
    page = watcher.soup(details(serial='0', condition='Demo, Return'))
    page.select_one('a').replace_with('Please contact store for details')
    return str(page)


class UnidentifiedTests(unittest.TestCase):
    def state(self):
        state = watcher.fresh_state()
        state.update(stage='inventory', store_queue=[deepcopy(TASK)],
                     initial_output_enabled=False)
        return state

    def test_checkpoint_resumes_past_unidentified_without_alerts(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            watcher.run_batch(state, path, FakeClient([contact_only()], limit=1))
            resumed = watcher.load_state(path)
        self.assertFalse(resumed['store_queue'])
        self.assertFalse(resumed['known_units'])
        self.assertFalse(resumed['pending_alerts'])
        self.assertEqual(watcher.status(resumed)['unidentified_listings'], 1)

    def test_mixed_response_records_identified_units_only(self):
        page = watcher.soup(contact_only())
        page.select_one('div.fw-normal.fs-7').append(
            watcher.soup(details()).select_one('div.mb-3.p-2.bg-light-grey'))
        state = self.state()
        watcher.step(state, FakeClient([str(page)]))
        self.assertEqual(len(state['known_units']), 1)
        self.assertFalse(state['pending_alerts'])
        self.assertEqual(watcher.status(state)['unidentified_listings'], 1)

    def test_repeat_replaces_observations_and_resolved_response_clears(self):
        state = self.state()
        for _ in range(2):
            state['store_queue'] = [deepcopy(TASK)]
            watcher.step(state, FakeClient([contact_only()]))
        self.assertEqual(watcher.status(state)['unidentified_listings'], 1)
        state['store_queue'] = [deepcopy(TASK)]
        watcher.step(state, FakeClient([details()]))
        self.assertEqual(watcher.status(state)['unidentified_listings'], 0)

    def test_malformed_response_preserves_checkpoint(self):
        state = self.state()
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            watcher.step(state, FakeClient([contact_only().replace('$75.00', 'bad')]))
        self.assertEqual(state, before)

    def test_strict_parser_callers_still_fail(self):
        with self.assertRaisesRegex(ValueError, 'neither a serial'):
            watcher.parse_units(contact_only(), TASK)


if __name__ == '__main__':
    unittest.main()
