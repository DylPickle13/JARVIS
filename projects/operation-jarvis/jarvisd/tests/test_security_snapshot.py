import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from jarvisd_core import security_snapshot as snapshot, security_status


class SharedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'snapshot.json'
        self.value = {'version': 1, 'observed_at': '2026-09-30T18:00:00+00:00', 'tick': 100.,
                      'sensors': {'motion-sensor': {'model': 'T100', 'state': True},
                                  'door-sensor': {'model': 'T110', 'state': False}}}
        from datetime import datetime
        self.now = datetime.fromisoformat(self.value['observed_at']).timestamp()
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o600)

    def read(self, **kwargs):
        return snapshot.read(str(self.path), 'motion-sensor', now=self.now + 1, tick=101., **kwargs)

    def test_fresh_preserves_observation_time_and_unknown_radio(self):
        code, body = self.read()
        self.assertEqual(code, 200)
        self.assertEqual(body['observedAt'], self.value['observed_at'])
        self.assertTrue(body['data']['motionDetected'])
        self.assertEqual(body['data']['radioFreshness'], 'unknown')
        self.assertIsNone(body['data']['batteryLow'])

    def test_stale_future_and_clock_discontinuity_rejected(self):
        for now, tick in ((self.now + 9, 109), (self.now - 1, 101),
                          (self.now + 1, 109), (self.now + 1, 90)):
            self.assertEqual(snapshot.read(str(self.path), 'motion-sensor', now=now, tick=tick)[0], 503)

    def test_missing_corrupt_and_untrusted_files(self):
        self.path.unlink()
        self.assertEqual(self.read()[0], 503)
        self.path.write_text('broken')
        self.assertEqual(self.read()[0], 503)
        self.save()
        self.path.chmod(0o644)
        self.assertEqual(self.read()[0], 503)
        self.path.unlink()
        self.path.symlink_to(Path(self.tmp.name) / 'missing')
        self.assertEqual(self.read()[0], 503)

    def test_schema_and_identity(self):
        for key, bad in (('tick', float('nan')), ('version', True), ('sensors', {}),
                         ('observed_at', '2026-09-30T18:00:00')):
            old = self.value[key]
            self.value[key] = bad
            self.save()
            self.assertEqual(self.read()[0], 503)
            self.value[key] = old
        self.value['sensors']['motion-sensor']['state'] = 1
        self.save()
        self.assertEqual(self.read()[0], 503)

    def test_opt_in_never_falls_back_to_cli(self):
        runner = Mock(side_effect=AssertionError('must not read hub'))
        with patch.dict(os.environ, {'JARVISD_SECURITY_SHARED_SNAPSHOT': str(self.path)}):
            for alias in ('motion-sensor', 'door-sensor'):
                with patch.object(snapshot.time, 'time', return_value=self.now + 1), \
                     patch.object(snapshot.time, 'monotonic', return_value=101.):
                    self.assertEqual(security_status._read_status('/fixture/security', alias, runner=runner)[0], 200)
                self.assertEqual(security_status._read_status('/fixture/security', alias, runner=runner)[0], 503)
        runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
