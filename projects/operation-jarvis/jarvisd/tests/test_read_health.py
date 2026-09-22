"""Offline health classification and bounded room-read recovery."""
import json
import unittest
from unittest.mock import Mock
from jarvisd_core import read_health as health
from jarvisd_core.room_audio_read import read_status


class HealthTests(unittest.TestCase):
    def test_success_failure_expiry_and_reset(self):
        now = [0.0]
        tracker = health.ReadHealth(ttl=10, clock=lambda: now[0])
        tracker.record('fixture', True)
        self.assertEqual(tracker.snapshot()['fixture']['availability'], 'available')
        now[0] = 11
        self.assertEqual(tracker.snapshot()['fixture']['reason'], 'observation_expired')
        tracker.record('fixture', False, reason='PRIVATE')
        tracker.record('fixture', False)
        self.assertEqual(tracker.snapshot()['fixture']['consecutiveFailures'], 2)
        self.assertNotIn('PRIVATE', json.dumps(tracker.snapshot()))
        tracker.record('fixture', True)
        self.assertEqual(tracker.snapshot()['fixture']['consecutiveFailures'], 0)

    def test_bounded_storage(self):
        tracker = health.ReadHealth(capacity=2)
        for key in ('a', 'b', 'c'):
            tracker.record(key, True)
        self.assertEqual(set(tracker.snapshot()), {'b', 'c'})

    def test_fixed_route_templates(self):
        self.assertEqual(health.route('/api/v1/services/private'), '/api/v1/services/{name}')
        self.assertIsNone(health.response_status('GET', '/not-a-route', 404, {'ok': False}))

    def test_endpoint_specific_terminology_and_staleness(self):
        cases = [('/health', {'ok': True}, 'healthy'),
                 ('/api/v1/local-control', {'ok': False}, 'not_ready'),
                 ('/api/v1/events', {'ok': True, 'events': []}, 'succeeded'),
                 ('/api/v1/security/status', {'ok': True}, 'available'),
                 ('/api/v1/omlx', {'ok': True, 'servers': [{'ok': True, 'stale': True}]}, 'unavailable'),
                 ('/api/v1/presence', {'ok': True, 'zones': [{'state': 'unknown', 'stale': True}]}, 'unavailable'),
                 ('/api/v1/state', {'ok': True, 'subsystemsMeta': {'plugs': {'ok': True, 'stale': False, 'error': None}}}, 'available')]
        for path, body, label in cases:
            self.assertEqual(health.response_status('GET', path, 200, body), label)
        self.assertEqual(health.response_status('POST', '/api/v1/device-command', 503, {'ok': False}), 'failed')
        self.assertIsNone(health.response_status('POST', '/api/v1/signing/renew', 202, {'ok': True}))

    def test_no_auth_input_write_or_diagnostic_health_poisoning(self):
        from unittest.mock import patch
        tracker = health.ReadHealth()
        with patch.object(health, 'ENDPOINT_HEALTH', tracker):
            for method, path, code in [('GET', '/api/v1/state', 401), ('GET', '/api/v1/state', 400),
                                       ('POST', '/api/v1/command', 503), ('GET', '/api/v1/health', 200)]:
                health.observe(method, path, code, {'ok': False})
        self.assertEqual(tracker.snapshot(), {})


class RoomRecoveryTests(unittest.TestCase):
    def connection(self, status=200, body=None):
        conn = Mock()
        conn.getresponse.return_value.status = status
        conn.getresponse.return_value.read.return_value = json.dumps(body or {'ok': True, 'phase': 'idle'}).encode()
        return conn

    def test_transient_recovery_and_get_only(self):
        first, second = self.connection(), self.connection()
        first.request.side_effect = ConnectionRefusedError()
        factory = Mock(side_effect=[first, second])
        result = read_status(8791, connection_factory=factory, sleep=lambda _: None)
        self.assertTrue(result['ok'])
        self.assertEqual(factory.call_count, 2)
        for conn in (first, second):
            conn.request.assert_called_once_with('GET', '/control/status')
            conn.close.assert_called_once()

    def test_auth_and_malformed_are_not_retried(self):
        for status in (401, 403, 200):
            conn = self.connection(status, {'ok': True, 'phase': 'PRIVATE'})
            factory = Mock(return_value=conn)
            with self.assertRaises(ValueError):
                read_status(8793, connection_factory=factory)
            self.assertEqual(factory.call_count, 1)

    def test_exhaustion_is_three_attempts(self):
        factory = Mock(side_effect=[self.connection(503) for _ in range(3)])
        with self.assertRaises(ConnectionError):
            read_status(8791, connection_factory=factory, sleep=lambda _: None)
        self.assertEqual(factory.call_count, 3)
