import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvisd_core import network_speed as speed


class SpeedTests(unittest.TestCase):
    def test_parse_units_and_reject_invalid(self):
        fixture = dict(dl_throughput=125000000, ul_throughput=22000000, base_rtt=12.5)
        self.assertEqual(speed.parse_result(json.dumps(fixture)),
                         dict(downloadMbps=125, uploadMbps=22, idleLatencyMs=12.5))
        for key in fixture:
            for invalid in (None, True, -1, '12', float('nan'), float('inf')):
                with self.assertRaises(ValueError):
                    speed.parse_result(json.dumps({**fixture, key: invalid}))
        with self.assertRaises(ValueError):
            speed.parse_result('{}')

    def wait_done(self, test):
        for _ in range(100):
            if test.snapshot()['status'] != 'running':
                return
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_single_flight_cooldown_and_cached_result(self):
        gate = threading.Event()
        now = [1000]
        collector = mock.Mock(side_effect=lambda: (gate.wait(2), {'downloadMbps': 42})[1])
        test = speed.SpeedTest(collector, lambda: now[0])
        self.assertEqual(test.snapshot()['status'], 'idle')
        collector.assert_not_called()
        self.assertEqual(test.start()[0], 202)
        self.assertEqual(test.start()[0], 409)
        gate.set()
        self.wait_done(test)
        self.assertEqual(test.snapshot()['status'], 'completed')
        self.assertEqual(test.start()[0], 429)
        cached = test.snapshot()
        cached['result']['downloadMbps'] = 0
        self.assertEqual(test.snapshot()['result']['downloadMbps'], 42)
        now[0] += 301
        self.assertEqual(test.start()[0], 202)
        self.wait_done(test)

    def test_failure_sanitized(self):
        test = speed.SpeedTest(mock.Mock(side_effect=RuntimeError('private output')))
        test.start()
        self.wait_done(test)
        self.assertEqual(test.snapshot()['status'], 'failed')
        self.assertNotIn('private output', str(test.snapshot()))
        self.assertEqual(test.start()[0], 429)

    def test_subprocess_bounds(self):
        scripts = ["print('x' * 70000)", "import time; time.sleep(5)", "raise SystemExit(1)"]
        for script in scripts:
            with mock.patch.object(speed, 'COMMAND', [sys.executable, '-c', script]), \
                 mock.patch.object(speed, 'TIMEOUT', .2):
                with self.assertRaises((ValueError, TimeoutError)):
                    speed.collect()


if __name__ == '__main__':
    unittest.main()
