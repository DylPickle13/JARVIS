import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'jarvisd'))
import unittest
from unittest.mock import patch
from pi_bridge import normalize
from pi_export import export
from pi_listener import load_config


class PiTests(unittest.TestCase):
    def test_bridge_ages_at_origin_not_poll_time(self):
        raw = {'state': 'nearby', 'sources': ['watch'], 'reason': 'ble-proximity', 'ageSeconds': 4}
        self.assertEqual(normalize(raw, 2, 100)['updatedAt'], 94)
        for age in (16, -1, float('nan'), True):
            with self.assertRaises(ValueError):
                normalize({**raw, 'ageSeconds': age}, 2, 100)
        with self.assertRaises(ValueError):
            normalize({**raw, 'sources': ['private-id']}, 2, 100)

    def test_configuration_requires_real_key_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            config = {'positioned': False, 'devices': {}}
            path.write_text(json.dumps(config))
            self.assertEqual(load_config(path), config)
            config['devices']['watch'] = {'irk': '00', 'enterRssi': -65, 'exitRssi': -70}
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_enrollment_is_private_and_preserves_placement(self):
        import base64
        from pi_enroll import parse_irk, enroll
        synthetic = bytes(range(16))
        self.assertEqual(parse_irk(synthetic.hex()), synthetic.hex())
        self.assertEqual(parse_irk(base64.b64encode(synthetic).decode()), synthetic.hex())
        for invalid in ('', '1234', 'not a key'):
            with self.assertRaises(ValueError):
                parse_irk(invalid)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/'config.json'
            path.write_text(json.dumps({'positioned': False, 'devices': {}}))
            enroll('watch', synthetic.hex(), root)
            config = load_config(path)
            self.assertFalse(config['positioned'])
            self.assertEqual(config['devices']['watch']['exitRssi'], -70)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                enroll('iphone', synthetic.hex(), root)
            with self.assertRaises(ValueError):
                enroll('watch', bytes(reversed(synthetic)).hex(), root)

    def test_export_rejects_old_boot_or_stale_monotonic_sample(self):
        import math
        good = {'state': 'nearby', 'sources': ['watch'], 'reason': 'ble-proximity',
                'bootId': 'boot-a', 'updatedMonotonic': 98}
        def read_fixture(path):
            if str(path) == '/proc/sys/kernel/random/boot_id':
                return 'boot-a'
            return json.dumps(good)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'state.json').write_text('{}')
            with patch.object(Path, 'read_text', read_fixture), patch('pi_export.time.monotonic', return_value=100):
                self.assertEqual(export(root)['state'], 'nearby')
                good['bootId'] = 'old-boot'
                self.assertEqual(export(root)['state'], 'unknown')
                good['bootId'] = 'boot-a'
                for stamp in (80, 101, float('nan')):
                    good['updatedMonotonic'] = stamp
                    self.assertEqual(export(root)['state'], 'unknown')

    def test_calibration_is_bounded_and_alias_only(self):
        from policy import Presence
        from pi_listener import summarize_observations
        policy = Presence({'watch': {'uuid': 'WATCH', 'enterRssi': -65, 'exitRssi': -70}})
        policy.observe('watch', -68, 99)
        result = summarize_observations({'watch': [(30, -90), (98, -70), (99, -68)], 'iphone': []}, policy, 100)
        self.assertEqual(result['devices']['watch'], {
            'matchedPacketsLast60Seconds': 2, 'lastSeenAgeSeconds': 1,
            'smoothedRssi': -68, 'minRssi': -70, 'medianRssi': -69,
            'maxRssi': -68})
        self.assertIsNone(result['devices']['iphone']['lastSeenAgeSeconds'])
        self.assertEqual(result['devices']['iphone']['matchedPacketsLast60Seconds'], 0)
        self.assertNotIn('uuid', json.dumps(result))
        self.assertNotIn('irk', json.dumps(result))

    def test_missing_export_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(export(Path(tmp))['state'], 'unknown')

    def test_second_zone_stale_and_sanitized(self):
        from jarvisd_core.presence import read_status
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            path.write_text(json.dumps({'updatedAt': 100, 'state': 'unknown', 'sources': [], 'reason': 'awaiting-placement', 'irk': 'secret'}))
            result = read_status(path, now=101, zone='living room')
            self.assertEqual(result['zone'], 'living room')
            self.assertEqual(result['reason'], 'awaiting-placement')
            self.assertNotIn('irk', result)
            self.assertEqual(read_status(path, now=116, zone='living room')['reason'], 'listener-stale')
