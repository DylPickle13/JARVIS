"""Sensor read health in backend summaries/history; fixtures only, no device I/O."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from jarvisd_core import system_health as health, system_history as history
from test_jarvisd import jarvisd as daemon
from test_system_history import BASE, snapshot

ALIASES = ('door-fixture', 'motion-fixture')


def evidence(available=True, age=0, reason=None):
    return {key: {'availability': 'available' if available else 'unavailable',
        'lastAttemptAt': health.stamp(BASE-age), 'ageSeconds': age,
        'reason': reason if reason else (None if available else 'read_failed'),
        'is_open': True, 'raw_error': 'PRIVATE'} for key in ALIASES}


def sensor(rows, *, enabled=True, aliases=ALIASES, now=BASE):
    return health.security_reads(rows, aliases, enabled=enabled, ttl=120, now=now)


class SensorProjectionTests(unittest.TestCase):
    def test_success_and_failure_affect_devices_and_overall(self):
        for available, state in ((True, 'healthy'), (False, 'unavailable')):
            rows = health.project(snapshot(), BASE, security=sensor(evidence(available)))
            for name in ('security', 'devices', 'overall'):
                self.assertEqual(rows[name]['state'], state)
            self.assertNotIn('PRIVATE', json.dumps(rows))
            self.assertNotIn('is_open', json.dumps(rows))
            self.assertNotIn('door-fixture', json.dumps(rows))

    def test_one_failed_sensor_cannot_be_hidden_by_the_other_success(self):
        value = evidence()
        value[ALIASES[1]] = evidence(False)[ALIASES[1]]
        self.assertEqual(sensor(value)['state'], 'unavailable')

    def test_disabled_or_unconfigured_monitoring_is_inactive(self):
        for row in (sensor({}, enabled=False), sensor({}, aliases=())):
            self.assertEqual(row['state'], 'inactive')
            self.assertEqual(health.project(snapshot(), BASE, security=row)['overall']['state'], 'healthy')

    def test_unchecked_or_expired_evidence_is_unknown_never_healthy(self):
        for value, reason in (({}, 'not_checked'), (evidence(age=121), 'observation_expired'),
                              (evidence(False, reason='observation_expired'), 'observation_expired')):
            row = sensor(value)
            self.assertEqual((row['state'], row['reason']), ('unknown', reason))
            self.assertEqual(health.project(snapshot(), BASE, security=row)['overall']['state'], 'unknown')

    def test_clock_and_shape_validation_fail_closed(self):
        for delta in ({'lastAttemptAt': None}, {'lastAttemptAt': health.stamp(BASE+1)},
                      {'ageSeconds': -1}, {'ageSeconds': True}, {'ageSeconds': float('nan')},
                      {'availability': 'other'}, {'reason': 'PRIVATE'}):
            value = evidence()
            value[ALIASES[0]].update(delta)
            self.assertEqual(sensor(value)['state'], 'unknown')
        for value in (None, [], 'PRIVATE'):
            self.assertEqual(sensor(value)['state'], 'unknown')
        self.assertEqual(sensor(evidence(), aliases=tuple(str(i) for i in range(9)))['state'], 'unknown')

    def test_freshness_uses_oldest_sensor_and_does_not_rejuvenate_old_source(self):
        value = evidence(age=20)
        value[ALIASES[0]].update(ageSeconds=0)  # New response cannot revive old evidence.
        row = sensor(value)
        self.assertEqual(row['validUntil'], BASE+100)
        self.assertEqual(row['sourceObservedAt'], BASE-20)
        self.assertEqual(sensor(evidence(age=120))['state'], 'healthy')
        self.assertEqual(sensor(evidence(age=120.001))['state'], 'unknown')

    def test_extra_component_preserves_inventory_bound(self):
        value = snapshot()
        value['subsystems']['services']['services'] = {f's{i}': {'ok': True, 'running': True} for i in range(100)}
        rows = health.project(value, BASE, security=sensor(evidence()))
        self.assertEqual(len(rows), health.MAX_COMPONENTS)
        self.assertEqual(rows['services']['reason'], 'inventory_limit')

    def test_recorder_includes_security_without_backfilling_previous_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = history.HistoryStore(Path(tmp).resolve()/'chart'/'history.sqlite3')
            current = [evidence(False)]
            recorder = history.HistoryRecorder(store, snapshot, clock=lambda: BASE,
                monotonic=lambda: 0, projector=lambda data, now: health.project(data, now, security=sensor(current[0])))
            try:
                recorder.tick()
                self.assertTrue(recorder.storage_available)
                result = store.read(window='1h', component='security', now=BASE+60, run_id=recorder.run_id)
                self.assertEqual(result['series'][0]['buckets'][-1]['state'], 'unavailable')
                self.assertEqual(result['series'][0]['buckets'][0]['coverageSeconds'], 0)
                self.assertNotIn('PRIVATE', json.dumps(result))
            finally:
                recorder.close()


class SensorHealthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = Mock()
        self.coordinator.snapshot.return_value = snapshot()
        self.tracker = Mock(ttl=120)
        self.tracker.snapshot.return_value = evidence(False)
        self.reader = Mock(side_effect=AssertionError('health must not read hardware'))
        for target, name, value in ((daemon, 'AUTH_MODE', 'token'), (daemon, 'API_TOKEN', 'fixture-token'),
                (daemon, 'ALLOWED_ORIGINS', set()), (daemon, 'MONITORING_ENABLED', True),
                (daemon, 'SECURITY_POLL_ALIASES', ALIASES), (daemon, 'STATE_COORDINATOR', self.coordinator),
                (daemon.read_health, 'SECURITY_HEALTH', self.tracker),
                (daemon.security_status, 'read_status', self.reader), (daemon.time, 'time', lambda: BASE)):
            item = patch.object(target, name, value)
            item.start()
            self.addCleanup(item.stop)
        from http.server import ThreadingHTTPServer
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), daemon.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, token='fixture-token'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            conn.request('GET', path, headers={'x-jarvis-token': token})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_current_health_reports_failure_and_recovery_without_hardware_reads(self):
        for path in ('/api/v1/health', '/api/v1/state?mode=cached'):
            for available, state in ((False, 'unavailable'), (True, 'healthy')):
                self.tracker.snapshot.return_value = evidence(available)
                code, body = self.request(path)
                self.assertEqual(code, 200)  # Query success is distinct from health.
                self.assertEqual(body['health']['components']['security']['state'], state)
                self.assertEqual(body['health']['components']['overall']['state'], state)
                self.assertEqual(body['health']['healthy'], available)
                self.assertNotIn('PRIVATE', json.dumps(body))
        for call in self.coordinator.snapshot.call_args_list:
            self.assertEqual(call.kwargs, {'client_active': False, 'start_collectors': False})
        self.reader.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()

    def test_authentication_precedes_cache_access(self):
        for path in ('/api/v1/health', '/api/v1/state?mode=cached'):
            self.assertEqual(self.request(path, token='')[0], 401)
        self.coordinator.snapshot.assert_not_called()
        self.tracker.snapshot.assert_not_called()
        self.reader.assert_not_called()

    def test_liveness_and_security_diagnostics_remain_separate(self):
        self.assertEqual(self.request('/health')[0], 200)
        code, body = self.request('/api/v1/security/health')
        self.assertEqual(code, 200)
        self.assertNotIn('health', body)
        self.coordinator.snapshot.assert_not_called()
        self.reader.assert_not_called()

    def test_query_rejection_does_not_refresh_any_cache(self):
        self.assertEqual(self.request('/api/v1/health?refresh=true')[0], 400)
        self.assertEqual(self.request('/api/v1/state?mode=cached&refresh=purifier')[0], 400)
        self.coordinator.snapshot.assert_not_called()
        self.reader.assert_not_called()
