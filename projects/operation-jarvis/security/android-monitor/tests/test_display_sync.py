import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import display_presence, unknown_display


class DisplaySync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.put('cycle.lock', {})
        self.put('watcher.lock', {})
        self.watcher_lock = (self.root / 'watcher.lock').open()
        fcntl.flock(self.watcher_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.put('display-config.json', {'enabled': True})
        self.state = dict(version=2, mode='nearby', away_since=None, away_checks=0,
                          last_tick=100, pending=False, fault=False, completed_at=90)
        self.put('display-state.json', self.state)
        self.put('watcher.json', dict(version=1, heartbeat=100, alerts=[]))
        self.sample = dict(version=1, state='nearby', ageSeconds=1)

    def tearDown(self):
        self.watcher_lock.close()
        self.tmp.cleanup()

    def put(self, name, value):
        p = self.root / name
        p.write_text(json.dumps(value))
        p.chmod(0o600)

    def get(self, now=101):
        return display_presence(self.root, provider=lambda: self.sample, now=lambda: now)

    def test_full_controller_to_relay_sequence_without_hardware(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent / 'keyboard'))
        import display_cycle
        owner = self
        class Store:
            def load(self, name, default):
                p = owner.root / name
                return json.loads(p.read_text()) if p.exists() else default
            def save(self, name, value):
                owner.put(name, value)
        self.put('display-state.json', display_cycle.initial())
        actions = []
        def tick(t, state):
            self.sample = dict(version=1, state=state, ageSeconds=0)
            payload = {'ok': True, 'zones': [{'zone': 'basement', 'subject': 'dylan',
                       'stale': False, 'ageSeconds': 0, 'state': state}]}
            display_cycle.run_once(Store(), now=lambda: t, get_presence=lambda: payload,
                                   apply=actions.append)
            self.put('watcher.json', dict(version=1, heartbeat=t, alerts=[]))
            return self.get(now=t)['state']
        self.assertEqual(tick(100, 'nearby'), 'unknown')  # No startup wake.
        self.assertEqual(tick(103, 'away'), 'unknown')
        self.assertEqual(tick(106, 'away'), 'unknown')
        self.assertEqual(actions, [])
        self.assertEqual(tick(109, 'away'), 'away')
        self.assertEqual(actions, ['lock-sleep'])
        self.assertEqual(tick(112, 'nearby'), 'nearby')
        self.assertEqual(actions, ['lock-sleep', 'wake'])
        self.assertEqual(tick(115, 'nearby'), 'nearby')
        self.assertEqual(actions, ['lock-sleep', 'wake'])

    def test_good_only_completed_matching_action(self):
        r = self.get()
        self.assertEqual(r['version'], 2)
        self.assertEqual(r['source'], 'computer-display')
        self.assertEqual(r['state'], 'nearby')
        self.assertEqual(set(r), {'version', 'source', 'state', 'ageSeconds'})

    def test_initial_nearby_never_wakes_phone(self):
        self.state['completed_at'] = None
        self.put('display-state.json', self.state)
        self.assertEqual(self.get(), unknown_display('awaiting-transition'))

    def test_first_two_away_checks_do_not_sleep_phone(self):
        self.sample['state'] = 'away'
        for count in (1, 2):
            self.state.update(away_checks=count, away_since=99)
            self.put('display-state.json', self.state)
            self.assertEqual(self.get()['state'], 'unknown')
        self.state.update(mode='away', completed_at=100, away_checks=0, away_since=None)
        self.put('display-state.json', self.state)
        self.assertEqual(self.get()['state'], 'away')

    def test_return_does_not_wake_before_mac_completion(self):
        self.state.update(mode='away', completed_at=90)
        self.put('display-state.json', self.state)
        self.assertEqual(self.get()['state'], 'unknown')
        self.state.update(mode='nearby', completed_at=100)
        self.put('display-state.json', self.state)
        self.assertEqual(self.get()['state'], 'nearby')

    def test_pending_or_fault_blocks_both_actions(self):
        for field in ('pending', 'fault'):
            for mode in ('nearby', 'away'):
                with self.subTest(field=field, mode=mode):
                    s = self.state | {field: True, 'mode': mode}
                    self.sample['state'] = mode
                    self.put('display-state.json', s)
                    self.assertEqual(self.get()['state'], 'unknown')

    def test_disabled_invalid_or_missing_files_fail_closed(self):
        for cfg in ({'enabled': False}, {'enabled': 1}, {'enabled': True, 'extra': 1}):
            self.put('display-config.json', cfg)
            self.assertEqual(self.get()['state'], 'unknown')
        self.put('display-config.json', {'enabled': True})
        for name in ('display-state.json', 'watcher.json', 'cycle.lock'):
            value = (self.root / name).read_bytes()
            (self.root / name).unlink()
            self.assertEqual(self.get()['state'], 'unknown')
            (self.root / name).write_bytes(value)
            (self.root / name).chmod(0o600)

    def test_stale_future_clock_and_bad_types_fail_closed(self):
        for now in (99, 116, float('nan'), True):
            self.assertEqual(self.get(now)['state'], 'unknown')
        for patch_state in ({'version': 1}, {'version': True}, {'last_tick': True},
                            {'completed_at': 102}, {'completed_at': True},
                            {'pending': 0}, {'fault': 0}, {'away_checks': True}):
            self.put('display-state.json', self.state | patch_state)
            self.assertEqual(self.get()['state'], 'unknown')

    def test_presence_unknown_stale_malformed_and_latency(self):
        for sample in (None, {}, {'state': 'unknown', 'ageSeconds': 1},
                       {'state': 'nearby', 'ageSeconds': 16},
                       {'state': 'nearby', 'ageSeconds': -1},
                       {'state': 'nearby', 'ageSeconds': True},
                       {'state': 'nearby', 'ageSeconds': float('inf')}):
            self.sample = sample
            self.assertEqual(self.get()['state'], 'unknown')
        self.sample = dict(version=1, state='nearby', ageSeconds=14)
        with patch('server.time.monotonic', side_effect=[0, 2]):
            self.assertEqual(self.get()['state'], 'unknown')

    def test_fetch_error_does_not_change_any_state(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        def fail():
            raise TimeoutError()
        self.assertEqual(display_presence(self.root, provider=fail)['state'], 'unknown')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_stopped_watcher_blocks_even_with_recent_heartbeat(self):
        self.watcher_lock.close()
        self.assertEqual(self.get()['state'], 'unknown')

    def test_busy_controller_lock_does_not_block_or_publish(self):
        with (self.root / 'cycle.lock').open() as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.get()['state'], 'unknown')

    def test_backend_fetch_is_outside_controller_lock(self):
        def provider():
            with (self.root / 'cycle.lock').open() as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.sample
        self.assertEqual(display_presence(self.root, provider=provider, now=lambda: 101)['state'], 'nearby')

    def test_unsafe_modes_and_symlinks_rejected(self):
        for mode in (0o644, 0o666):
            (self.root / 'display-state.json').chmod(mode)
            self.assertEqual(self.get()['state'], 'unknown')
        (self.root / 'display-state.json').chmod(0o600)
        p = self.root / 'watcher.json'
        p.rename(self.root / 'other.json')
        p.symlink_to('other.json')
        self.assertEqual(self.get()['state'], 'unknown')
        p.unlink(); (self.root / 'other.json').rename(p)
        self.root.chmod(0o755)
        self.assertEqual(self.get()['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
