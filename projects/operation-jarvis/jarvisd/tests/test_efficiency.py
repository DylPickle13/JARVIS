"""Offline audit regressions: no device/configuration/service access."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from jarvisd_core.local_http import read_json
from jarvisd_core.monitoring import integration
from jarvisd_core.state import StateCoordinator
from jarvisd_core.work_metrics import WorkMetrics


class FreshnessTests(unittest.TestCase):
    def test_every_incident_integration_expires_without_another_collection(self):
        now = [100.0]
        for name in ('pi', 'services', 'network', 'codexQuota'):
            c = StateCoordinator({name: Mock()}, now=lambda: now[0], version='test', started_at=0)
            c._records[name].update(data={'ok': True}, lastGoodAt=100.0, stale=False)
            c.start = Mock(side_effect=AssertionError('passive read started workers'))
            now[0] = 100
            self.assertEqual(integration(name, c.snapshot(start_collectors=False))[0], 200)
            now[0] += c.DEFAULT_FRESHNESS_LIMITS[name] + 1
            self.assertEqual(integration(name, c.snapshot(start_collectors=False))[0], 503)
            c.collectors[name].assert_not_called()
            c.start.assert_not_called()


class MetricsTests(unittest.TestCase):
    def test_counts_latencies_failures_busy_and_sanitization(self):
        now = [0.0]
        m = WorkMetrics(['read'], clock=lambda: now[0])
        def success():
            self.assertEqual(m.snapshot()['read']['inFlight'], 1)
            now[0] += 2
            return {'ok': True, 'private': 'SECRET'}
        m.run('read', success)
        m.run('read', lambda: (409, {'errorCode': 'device_busy'}))
        with self.assertRaises(RuntimeError):
            m.run('read', Mock(side_effect=RuntimeError('SECRET')))
        row = m.snapshot()['read']
        self.assertEqual((row['started'], row['completed'], row['failed'], row['busy']), (3, 3, 1, 1))
        self.assertEqual(row['maxSeconds'], 2)
        self.assertEqual(row['inFlight'], 0)
        self.assertNotIn('SECRET', json.dumps(row))
        with self.assertRaises(KeyError):
            m.run('arbitrary-path', success)

    def test_collection_instrumented_once_not_on_snapshot(self):
        c = StateCoordinator({'pi': lambda: {'ok': True}}, version='test', started_at=0)
        c._collect_one('pi')
        for _ in range(5):
            c.snapshot(start_collectors=False)
        self.assertEqual(c.metrics.snapshot()['pi']['started'], 1)


class UnixHTTPTests(unittest.TestCase):
    def server(self, responder):
        directory = tempfile.TemporaryDirectory(prefix='jh-', dir='/tmp')
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / 's')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(2)
        def serve():
            try:
                with listener.accept()[0] as connection:
                    connection.recv(4096)
                    try:
                        responder(connection)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            finally:
                listener.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(2))
        return path

    def test_bounded_success_and_body_limit(self):
        def response(data):
            return lambda s: s.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(data)).encode() + b'\r\n\r\n' + data)
        self.assertEqual(read_json(self.server(response(b'{"ok":true}')), '/status'), {'ok': True})
        with self.assertRaisesRegex(ValueError, 'output limit'):
            read_json(self.server(response(b'x' * 128)), '/status', maximum=32)

    def test_slow_headers_have_total_deadline(self):
        def dribble(s):
            for char in b'HTTP/1.1 200 OK\r\n':
                s.sendall(bytes([char]))
                time.sleep(.015)
        started = time.monotonic()
        with self.assertRaises(Exception):
            read_json(self.server(dribble), '/status', timeout=.06)
        self.assertLess(time.monotonic() - started, .5)


class WatchdogTests(unittest.TestCase):
    def test_sustained_threshold_recovery_and_failed_attempt_backoff(self):
        script = Path(__file__).resolve().parents[1] / 'resurrector.sh'
        body = '''source "$1"
log() { :; }
calls=0
healthy=0
is_healthy() { (( healthy )); }
launchctl() { calls=$((calls + 1)); return 1; }
check_once 0
check_once 10
[[ $calls == 0 ]] || exit 11
check_once 20
[[ $calls == 2 ]] || exit 12
check_once 30
check_once 40
[[ $calls == 2 ]] || exit 13
healthy=1; check_once 45
healthy=0; check_once 46; check_once 56
[[ $calls == 2 ]] || exit 14
check_once 66
[[ $calls == 4 ]] || exit 15
'''
        result = subprocess.run(['bash', '-c', body, 'test', str(script)], capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
