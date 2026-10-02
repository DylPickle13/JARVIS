import unittest
from unittest.mock import patch
import numpy as np
from spectral_sync import align_features, FEATURE_RATE


class CoverageTests(unittest.TestCase):
    def run_windows(self, bad=(), duration=47, conflicting=False):
        data = np.zeros((8, int(duration*FEATURE_RATE)), dtype=np.float32)
        count = 0
        def fake(reference, target, start, seconds, max_offset):
            nonlocal count
            i = count
            count += 1
            return {'accepted':i not in bad,'target_seconds':start+seconds/2,
                    'offset_seconds':.5+(.1 if conflicting and i==4 else 0)}
        with patch('spectral_sync.match', side_effect=fake):
            return align_features(data, data)

    def test_weak_opening_allowed(self):
        r = self.run_windows(bad=(0,))
        self.assertTrue(r['accepted'], r)
        self.assertEqual(r['accepted_windows'], 8)
        self.assertEqual(r['required_windows'], 7)

    def test_weak_ending_allowed(self):
        self.assertTrue(self.run_windows(bad=(8,))['accepted'])

    def test_seven_of_nine_distributed_allowed(self):
        self.assertTrue(self.run_windows(bad=(0,8))['accepted'])

    def test_six_of_nine_rejected(self):
        self.assertFalse(self.run_windows(bad=(0,4,8))['accepted'])

    def test_percentage_alone_cannot_replace_coverage(self):
        r = self.run_windows(bad=(0,1))
        self.assertGreater(r['matched_fraction'], .75)
        self.assertFalse(r['accepted'])
        self.assertIn('cover', r['reason'])

    def test_conflicting_accepted_match_not_discarded(self):
        r = self.run_windows(bad=(0,), conflicting=True)
        self.assertFalse(r['accepted'])
        self.assertIn('inconsistent', r['reason'])

    def test_exactly_seventy_five_percent_rejected(self):
        # 12 windows at 1440 seconds; 9/12 is exactly 75%, not >75%.
        r = self.run_windows(bad=(2,5,8), duration=1440)
        self.assertEqual(r['matched_fraction'], .75)
        self.assertEqual(r['required_windows'], 10)
        self.assertFalse(r['accepted'])
