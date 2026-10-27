import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from listener import Presence, load_devices
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'jarvisd'))
from jarvisd_core.presence import read_status


class Tests(unittest.TestCase):
    def test_dual_device_timeout(self):
        devices = {s: {'uuid': s.upper(), 'enterRssi': -65, 'exitRssi': -75} for s in ('watch', 'iphone')}
        p = Presence(devices, started=0)
        self.assertEqual(p.snapshot(0)['state'], 'unknown')
        p.observe('other', -30, 1)
        self.assertEqual(p.snapshot(1)['state'], 'unknown')
        p.observe('watch', -60, 0)
        p.observe('watch', -60, 2)
        self.assertEqual(p.snapshot(2)['state'], 'unknown')  # Not yet confirmed.
        p.observe('watch', -60, 3)
        p.observe('iphone', -60, 6)
        p.observe('iphone', -60, 9)
        self.assertEqual(p.snapshot(11)['sources'], ['iphone', 'watch'])
        self.assertEqual(p.snapshot(13)['sources'], ['iphone'])
        self.assertEqual(p.snapshot(18.9)['state'], 'nearby')
        self.assertEqual(p.snapshot(19)['state'], 'away')

    def test_single_strong_spike_never_reports_nearby(self):
        p = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -70}}, started=0)
        p.observe('watch', -50, 20)
        p.observe('watch', -50, 21)  # Still under three seconds.
        p.observe('watch', -90, 22)
        p.observe('watch', -90, 22.5)
        for now in (21, 22, 25, 31):
            self.assertEqual(p.snapshot(now)['state'], 'away')
        self.assertEqual([e['kind'] for e in p.events], ['rejected-spike'])

    def test_weak_reading_or_gap_restarts_confirmation(self):
        p = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -70}}, started=0)
        p.observe('watch', -50, 20)
        p.observe('watch', -100, 21)
        p.observe('watch', -40, 22)
        self.assertEqual(p.snapshot(24)['state'], 'away')
        p.observe('watch', -40, 40)  # Gap beyond CONFIRM_GAP restarts.
        self.assertEqual(p.snapshot(41)['state'], 'away')
        p.observe('watch', -40, 43)
        self.assertEqual(p.snapshot(43)['state'], 'nearby')

    def test_confirmed_device_keeps_exit_hysteresis_and_hold(self):
        p = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -70}}, started=0)
        for t in (20, 23):
            p.observe('watch', -60, t)
        p.observe('watch', -68, 30)  # Between thresholds: stays qualifying once confirmed.
        self.assertEqual(p.snapshot(39.9)['state'], 'nearby')
        self.assertEqual(p.snapshot(40)['state'], 'away')

    def test_transition_log_is_private_bounded_and_rssi_local_only(self):
        import listener
        p = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -70}}, started=0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'transitions.jsonl'
            for t in (20, 23):
                p.observe('watch', -60, t)
            key = listener.log_changes(p, p.snapshot(23), None, path)
            self.assertEqual(listener.log_changes(p, p.snapshot(24), key, path), key)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r['kind'] for r in rows], ['confirmed', 'state'])
            self.assertEqual(rows[1]['sources'], ['watch'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('WATCH', path.read_text())
            self.assertNotIn('rssi', p.snapshot(24))

    def test_no_enrollment_never_away(self):
        self.assertEqual(Presence({}, started=0).snapshot(999)['state'], 'unknown')

    def test_weak_and_invalid(self):
        p = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -75}}, started=0)
        for rssi in (0, 127, float('nan'), -100):
            p.observe('watch', rssi, 130)
        self.assertEqual(p.snapshot(130)['state'], 'away')

    def test_freshness_and_sanitization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            self.assertEqual(read_status(path, 10)['state'], 'unknown')
            path.write_text(json.dumps({'state': 'nearby', 'updatedAt': 10, 'sources': ['watch'], 'uuid': 'secret'}))
            self.assertEqual(read_status(path, 11)['state'], 'nearby')
            self.assertNotIn('uuid', read_status(path, 11))
            for now in (9, 26):
                self.assertEqual(read_status(path, now)['state'], 'unknown')
            path.write_text('[]')
            self.assertEqual(read_status(path, 11)['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
