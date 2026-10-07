"""Offline status-only frame integration; fake workers, no LAN/photo/config access."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jarvisd_core import device_health as health
from jarvisd_core import frame_health as frame


def entry(**extra):
    return dict(id='picture-frame', name='Picture frame', kind='frame', expectation='always', **extra)


def registry(*rows):
    return health.validate({'version': 1, 'devices': list(rows)})


class ConfigurationTests(unittest.TestCase):
    def test_fixed_one_frame_and_no_target_arguments(self):
        self.assertEqual(registry(entry())[0]['kind'], 'frame')
        for extra in ({'host': '192.168.1.2', 'port': 5555}, {'selector': 'other'},
                      {'path': '/private/source'}, {'command': 'shell'}, {'python': '/bin/python'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                registry(entry(**extra))
        with self.assertRaises(ValueError):
            registry(entry(), dict(entry(), id='another-frame'))

    def test_no_default_monitor_and_explicit_paths_required(self):
        self.assertIsNone(frame.configure((), {}))
        for env in ({}, {'JARVISD_FRAME_HEALTH_WORKER': '/source/health_worker.py'},
                    {'JARVISD_FRAME_HEALTH_WORKER': 'health_worker.py', 'JARVISD_FRAME_HEALTH_PYTHON': '/python'},
                    {'JARVISD_FRAME_HEALTH_WORKER': '/source/other.py', 'JARVISD_FRAME_HEALTH_PYTHON': '/python'},
                    {'JARVISD_FRAME_HEALTH_WORKER': '/source/health_worker.py', 'JARVISD_FRAME_HEALTH_PYTHON': 'python'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                frame.configure(registry(entry()), env)

    def test_import_and_configuration_never_perform_io(self):
        with patch.object(frame.subprocess, 'Popen', side_effect=AssertionError), \
             patch.object(Path, 'lstat', side_effect=AssertionError), \
             patch('builtins.open', side_effect=AssertionError):
            importlib.reload(frame)
            probe = frame.configure(registry(entry()), {'JARVISD_FRAME_HEALTH_WORKER': '/source/health_worker.py',
                'JARVISD_FRAME_HEALTH_PYTHON': '/approved/python'})
            self.assertEqual(probe.python, '/approved/python')
            health.ProbeWorker(registry(entry()), frame=probe)

    def test_adapter_uses_fixed_owner_paths_only(self):
        calls = []
        probe = frame.FrameProbe('/source/health_worker.py', '/approved/python',
            collector=lambda *args: (calls.append(args) or (True, None)))
        self.assertEqual(probe(entry()), (True, None))
        self.assertEqual(calls, [('/source/health_worker.py', '/approved/python')])
        self.assertEqual(probe({'kind': 'tcp'}), (None, 'configuration_unavailable'))
        self.assertEqual(len(calls), 1)


class SubprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worker = Path(self.tmp.name) / 'health_worker.py'

    def script(self, body):
        self.worker.write_text(body)
        self.worker.chmod(0o600)

    def collect(self):
        return frame.collect(str(self.worker), sys.executable)

    def test_success_fixed_arguments_and_no_environment_secrets(self):
        self.script("import json, os, sys\nassert sys.argv[1:] == ['--check']\n"
                    "assert 'PRIVATE_PHOTO_PATH' not in os.environ\n"
                    "print(json.dumps({'ok':True,'reason':None}))\n")
        with patch.dict(os.environ, {'PRIVATE_PHOTO_PATH': '/private/photo.jpg'}):
            self.assertEqual(self.collect(), (True, None))

    def test_single_failure_never_retries(self):
        count = Path(self.tmp.name) / 'attempts'
        self.script(f"import json\nwith open({str(count)!r}, 'a') as f:f.write('1')\n"
                    "print(json.dumps({'ok':False,'reason':'read_failed'}))\n")
        self.assertEqual(self.collect(), (False, 'read_failed'))
        self.assertEqual(count.read_text(), '1')

    def test_strict_bounded_sanitized_protocol(self):
        for value in ({'ok': True, 'reason': None, 'endpoint': 'private'},
                      {'ok': 1, 'reason': None}, {'ok': False, 'reason': 'raw-private-error'},
                      {'ok': None, 'reason': []}, {'ok': True}, ['wrong'],
                      {'ok': True, 'reason': 'current'}):
            with self.subTest(value=value):
                self.script('print(' + repr(json.dumps(value)) + ')\n')
                self.assertEqual(self.collect(), (None, 'invalid_output'))
        self.script("print('invalid secret text')\n")
        self.assertEqual(self.collect(), (None, 'worker_failed'))
        self.script("print('x' * 5000)\n")
        self.assertEqual(self.collect(), (None, 'invalid_output'))

    def test_unknown_failure_is_not_unreachable(self):
        self.script("print('{\"ok\": null, \"reason\": \"device_busy\"}')\n")
        self.assertEqual(self.collect(), (None, 'device_busy'))
        self.script('raise RuntimeError("private endpoint")\n')
        self.assertEqual(self.collect(), (None, 'worker_failed'))

    def test_deadline_kills_the_worker_and_does_not_retry(self):
        count = Path(self.tmp.name) / 'attempts'
        self.script(f"import time\nwith open({str(count)!r}, 'a') as f:f.write('1')\n"
                    "time.sleep(30)\n")
        with patch.object(frame, 'TIMEOUT', 0.3):
            self.assertEqual(self.collect(), (None, 'worker_timeout'))
        self.assertEqual(count.read_text(), '1')

    def test_shared_missing_or_symlink_code_rejected_before_spawn(self):
        self.assertEqual(self.collect(), (None, 'worker_failed'))
        self.script("print('{}')\n")
        self.worker.chmod(0o666)
        with patch.object(frame.subprocess, 'Popen', side_effect=AssertionError):
            self.assertEqual(self.collect(), (None, 'configuration_unavailable'))
        other = self.worker.with_name('other.py')
        self.worker.rename(other)
        self.worker.symlink_to(other)
        with patch.object(frame.subprocess, 'Popen', side_effect=AssertionError):
            self.assertEqual(self.collect(), (None, 'configuration_unavailable'))


class HealthProjectionTests(unittest.TestCase):
    def setUp(self):
        self.reg = registry(entry())
        self.tick = 0
        self.outcome = (True, None)
        self.calls = []
        def read(row):
            self.calls.append(row['id'])
            return self.outcome
        self.worker = health.ProbeWorker(self.reg, frame=read,
            clock=lambda: self.tick, wall=lambda: 100 + self.tick)

    def project(self):
        return health.project(self.reg, {}, {}, {}, self.worker.snapshot())

    def test_up_unreachable_unknown_and_last_attempt(self):
        self.assertEqual(self.project()['devices'][0]['state'], 'unknown')
        self.worker.tick()
        row = self.project()['devices'][0]
        self.assertEqual(row['scope'], 'frame_network_reachability')
        self.assertEqual(row['state'], 'available')
        self.assertIsNotNone(row['lastAttemptAt'])
        success = row['lastSuccessAt']
        self.tick = 60; self.outcome = (False, 'read_failed'); self.worker.tick()
        row = self.project()['devices'][0]
        self.assertEqual(row['state'], 'unavailable')
        self.assertEqual(row['consecutiveFailures'], 1)
        self.assertEqual(row['lastSuccessAt'], success)
        self.tick = 120; self.outcome = (None, 'device_busy'); self.worker.tick()
        row = self.project()['devices'][0]
        self.assertEqual(row['state'], 'unknown')
        self.assertEqual(row['reason'], 'device_busy')
        self.assertEqual(row['lastSuccessAt'], success)
        self.assertEqual(row['consecutiveFailures'], 1)
        self.assertEqual(health.incident_observations(self.project()), {'devices/picture-frame': None})
        self.tick = 180; self.outcome = (True, None); self.worker.tick()
        self.assertEqual(self.project()['devices'][0]['consecutiveFailures'], 0)
        self.assertEqual(self.calls, ['picture-frame'] * 4)

    def test_expiry_never_substitutes_last_good(self):
        self.worker.tick(); self.tick = 151
        row = self.project()['devices'][0]
        self.assertEqual(row['state'], 'unknown')
        self.assertEqual(row['reason'], 'observation_expired')
        self.assertIsNotNone(row['lastSuccessAt'])
        self.assertEqual(health.incident_observations(self.project()), {'devices/picture-frame': None})

    def test_missing_worker_and_exceptions_are_unknown_not_green_or_outage(self):
        worker = health.ProbeWorker(self.reg)
        worker.tick()
        row = health.project(self.reg, {}, {}, {}, worker.snapshot())['devices'][0]
        self.assertEqual((row['state'], row['reason']), ('unknown', 'configuration_unavailable'))
        def explode(row): raise RuntimeError('private photo path')
        worker = health.ProbeWorker(self.reg, frame=explode); worker.tick()
        body = health.project(self.reg, {}, {}, {}, worker.snapshot())
        self.assertEqual(body['devices'][0]['state'], 'unknown')
        self.assertNotIn('private photo path', json.dumps(body))
        self.assertEqual(worker.snapshot()['picture-frame']['consecutiveFailures'], 0)

    def test_malicious_reason_sanitized(self):
        self.outcome = (None, 'private endpoint'); self.worker.tick()
        self.assertEqual(self.project()['devices'][0]['reason'], 'check_failed')
        self.assertNotIn('private endpoint', json.dumps(self.project()))

    def test_no_frame_read_in_http_projection_or_disabled_monitoring(self):
        self.project(); self.project()
        body = health.project(self.reg, {}, {}, {}, {}, enabled=False)
        self.assertEqual(body['devices'][0]['coverage'], 'unmonitored')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
