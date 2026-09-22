"""Offline monitoring projections, serial scheduling, and authenticated HTTP."""
import http.client
import json
import threading
import unittest
from unittest.mock import Mock, patch
from jarvisd_core import monitoring, read_health
from jarvisd_core.security_polling import SecurityPoller, aliases_from_config
from test_jarvisd import jarvisd as daemon


class PollTests(unittest.TestCase):
    def test_alias_validation(self):
        self.assertEqual(aliases_from_config('door-sensor, motion-sensor'), ('door-sensor', 'motion-sensor'))
        for raw in ('../private', 'a,a', ','.join('a' + str(i) for i in range(9))):
            with self.assertRaises(ValueError):
                aliases_from_config(raw)
        for interval in (0, 301, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                SecurityPoller('', (), reader=Mock(), interval=interval)

    def test_serial_completion_relative_no_catchup_and_stop(self):
        now = [0.0]
        calls = []
        def reader(cli, alias):
            calls.append(alias)
            now[0] += 10
        poller = SecurityPoller('/fixture', ('door', 'motion'), reader=reader, clock=lambda: now[0])
        self.assertEqual(calls, [])
        poller.tick()
        self.assertEqual(calls, ['door', 'motion'])
        poller.tick()
        self.assertEqual(len(calls), 2)
        now[0] = 1000
        poller.tick()
        self.assertEqual(calls, ['door', 'motion', 'door', 'motion'])
        poller.stop()
        now[0] = 2000
        poller.tick()
        self.assertEqual(len(calls), 4)

    def test_unexpected_exception_invalidates_health_and_continues(self):
        tracker = read_health.ReadHealth()
        reader = Mock(side_effect=[RuntimeError('PRIVATE'), (200, {'ok': True})])
        with patch.object(read_health, 'SECURITY_HEALTH', tracker):
            SecurityPoller('', ('door', 'motion'), reader=reader).tick()
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(tracker.snapshot()['door']['availability'], 'unavailable')
        self.assertNotIn('PRIVATE', json.dumps(tracker.snapshot()))


class ProjectionTests(unittest.TestCase):
    def test_sensor_expiry_failure_recovery_without_reads(self):
        now = [0.0]
        tracker = read_health.ReadHealth(clock=lambda: now[0])
        def check():
            return monitoring.security('door', enabled=True, configured=('door',), observations=tracker.snapshot())
        self.assertEqual(check()[0], 503)
        tracker.record('door', True)
        self.assertEqual(check()[0], 200)
        self.assertEqual(check()[1]['radioFreshness'], 'unknown')
        now[0] = 121
        self.assertEqual(check()[0], 503)
        tracker.record('door', False)
        self.assertEqual(check()[0], 503)
        tracker.record('door', True)
        self.assertEqual(check()[0], 200)
        self.assertNotIn('data', check()[1])

    def test_idle_omlx_health_is_not_six_second_activity_freshness(self):
        meta = {'ok': True, 'stale': True, 'ageSeconds': 45, 'error': None}
        snapshot = {'subsystemsMeta': {'fixture': meta}}
        self.assertEqual(monitoring.integration('fixture', snapshot)[0], 503)
        self.assertEqual(monitoring.integration('fixture', snapshot, observation_limit=120)[0], 200)
        meta['error'] = 'PRIVATE'
        self.assertEqual(monitoring.integration('fixture', snapshot, observation_limit=120)[0], 503)
        meta['error'], meta['ageSeconds'] = None, 121
        self.assertEqual(monitoring.integration('fixture', snapshot, observation_limit=120)[0], 503)

    def test_integration_freshness_and_sanitization(self):
        for meta, code in [({'ok': True, 'stale': False}, 200),
                           ({'ok': True, 'stale': True}, 503),
                           ({'ok': True, 'stale': False, 'error': 'PRIVATE'}, 503),
                           ({'ok': False, 'stale': False}, 503)]:
            result = monitoring.integration('plugs', {'subsystemsMeta': {'plugs': meta}})
            self.assertEqual(result[0], code)
            self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(monitoring.integration('bad', {})[0], 404)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.reader = Mock(side_effect=AssertionError('monitor must not read hardware'))
        self.coordinator = Mock()
        self.coordinator.snapshot.return_value = {'subsystemsMeta': {'plugs': {'ok': True, 'stale': False}}}
        self.tracker = read_health.ReadHealth()
        for target, name, value in [(daemon, 'API_TOKEN', 'fixture-token'), (daemon, 'AUTH_MODE', 'trusted-network'),
                (daemon, 'MONITORING_ENABLED', True), (daemon, 'SECURITY_POLL_ALIASES', ('door',)),
                (daemon, 'STATE_COORDINATOR', self.coordinator), (daemon, 'ALLOWED_ORIGINS', set()),
                (daemon.security_status, 'read_status', self.reader),
                (read_health, 'SECURITY_HEALTH', self.tracker)]:
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
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
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            conn.close()

    def test_dashboard_api_auth_and_private_history(self):
        worker = Mock(storage_available=True)
        worker.store.status.return_value = {'security/door': {'availability': 'unavailable'}}
        worker.store.history.return_value = []
        with patch.object(daemon, 'MONITOR_WORKER', worker):
            self.assertEqual(self.request('/api/v1/monitor/history', token='')[0], 401)
            worker.store.history.assert_not_called()
            self.assertEqual(self.request('/api/v1/monitor/history')[1]['events'], [])
            self.assertEqual(self.request('/api/v1/monitor/status')[0], 200)
            worker.store.history.side_effect = RuntimeError('PRIVATE')
            code, body, _ = self.request('/api/v1/monitor/history')
            self.assertEqual(code, 503)
            self.assertNotIn('PRIVATE', json.dumps(body))
        self.reader.assert_not_called()

    def test_removed_dashboard_routes_return_not_found(self):
        for path in ('/monitoring', '/monitoring.js'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, token='')[0], 404)
                self.assertEqual(self.request(path)[0], 404)
        self.reader.assert_not_called()
        self.coordinator.snapshot.assert_not_called()

    def test_monitor_auth_and_no_hardware_reads(self):
        path = '/api/v1/monitor/security/door'
        self.assertEqual(self.request(path, token='')[0], 401)
        self.assertEqual(self.request(path)[0], 503)
        self.tracker.record('door', True)
        code, body, headers = self.request(path)
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.reader.assert_not_called()
        self.coordinator.snapshot.assert_not_called()
        self.assertEqual(self.request(path + '?refresh=true')[0], 400)

    def test_on_demand_auth_missing_expiry_and_no_polling(self):
        path = '/api/v1/monitor/on-demand/purifier'
        self.assertEqual(self.request(path, token='')[0], 401)
        self.coordinator.snapshot.assert_not_called()
        self.assertEqual(self.request(path)[0], 503)
        self.coordinator.snapshot.assert_called_once_with(client_active=False)
        self.coordinator.snapshot.return_value = {'subsystemsMeta': {
            'purifier': {'ok': True, 'stale': False, 'ageSeconds': 1}}}
        code, body, _ = self.request(path)
        self.assertEqual(code, 200)
        self.assertEqual(body['mode'], 'on_demand')
        self.assertFalse(body['backgroundPolled'])
        self.assertFalse(body['incidentTracking'])
        self.coordinator.snapshot.return_value['subsystemsMeta']['purifier']['stale'] = True
        self.assertEqual(self.request(path)[0], 503)
        self.coordinator.snapshot.reset_mock()
        self.assertEqual(self.request('/api/v1/monitor/on-demand/unknown')[0], 404)
        self.assertEqual(self.request(path + '?refresh=true')[0], 400)
        with patch.object(daemon, 'MONITORING_ENABLED', False):
            self.assertEqual(self.request(path)[0], 503)
        self.coordinator.snapshot.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()
        self.reader.assert_not_called()

    def test_on_demand_read_health_expires_and_recovers(self):
        now = [0.0]
        tracker = read_health.ReadHealth(clock=lambda: now[0])
        with patch.object(read_health, 'ENDPOINT_HEALTH', tracker):
            for name, route in [('presence', '/api/v1/presence'),
                                ('room-audio-pi', '/api/v1/room-audio/pi'),
                                ('room-audio-mac', '/api/v1/room-audio/mac')]:
                path = '/api/v1/monitor/on-demand/' + name
                self.assertEqual(self.request(path)[0], 503)
                tracker.record(route, True)
                self.assertEqual(self.request(path)[0], 200)
                now[0] += 121
                self.assertEqual(self.request(path)[1]['reason'], 'observation_expired')
                tracker.record(route, False)
                self.assertEqual(self.request(path)[0], 503)
                tracker.record(route, True)
                self.assertEqual(self.request(path)[0], 200)
        self.reader.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()

    def test_on_demand_cache_failure_sanitized(self):
        self.coordinator.snapshot.side_effect = RuntimeError('PRIVATE')
        code, body, _ = self.request('/api/v1/monitor/on-demand/purifier')
        self.assertEqual(code, 503)
        self.assertNotIn('PRIVATE', json.dumps(body))

    def test_integrations_cached_only_and_disabled(self):
        path = '/api/v1/monitor/integrations/plugs'
        self.assertEqual(self.request(path)[0], 200)
        self.coordinator.snapshot.assert_called_once_with(client_active=False)
        self.coordinator.request_refresh.assert_not_called()
        with patch.object(daemon, 'MONITORING_ENABLED', False):
            self.assertEqual(self.request(path)[0], 503)
        self.assertEqual(self.coordinator.snapshot.call_count, 1)

    def test_cached_state_does_not_activate_or_refresh(self):
        self.assertEqual(self.request('/api/v1/state?mode=cached')[0], 200)
        self.coordinator.snapshot.assert_called_once_with(client_active=False, start_collectors=False)
        self.coordinator.request_refresh.assert_not_called()
        self.coordinator.snapshot.reset_mock()
        for query in ('mode=cached&refresh=purifier', 'mode=cached&retryCooldown=true',
                      'mode=bad', 'mode=cached&mode=cached', 'mode=', 'mode=cached&refresh='):
            self.assertEqual(self.request('/api/v1/state?' + query)[0], 400)
        self.coordinator.snapshot.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()

    def test_work_diagnostics_are_private_and_cache_only(self):
        self.coordinator.metrics.snapshot.return_value = {}
        self.assertEqual(self.request('/api/v1/diagnostics', token='')[0], 401)
        self.coordinator.metrics.snapshot.assert_not_called()
        self.assertEqual(self.request('/api/v1/diagnostics')[0], 200)
        self.assertEqual(self.request('/api/v1/diagnostics?refresh=true')[0], 400)
        self.coordinator.snapshot.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()
        self.reader.assert_not_called()

    def test_diagnostics_success_does_not_mask_monitor_failure(self):
        self.assertEqual(self.request('/api/v1/security/health')[0], 200)
        self.assertEqual(self.request('/api/v1/monitor/security/door')[0], 503)
        self.assertEqual(self.request('/api/v1/health', token='')[0], 401)
        self.reader.assert_not_called()
