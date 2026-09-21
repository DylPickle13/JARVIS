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
        p.observe('watch', -60, 2)
        p.observe('iphone', -60, 9)
        self.assertEqual(p.snapshot(11)['sources'], ['iphone', 'watch'])
        self.assertEqual(p.snapshot(12)['sources'], ['iphone'])
        self.assertEqual(p.snapshot(18.9)['state'], 'nearby')
        self.assertEqual(p.snapshot(19)['state'], 'away')

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
