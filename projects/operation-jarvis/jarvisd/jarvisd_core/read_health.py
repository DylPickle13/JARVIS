"""Bounded, process-local observations. No I/O, device state, or background probes.

Availability describes data access, never physical device reachability. HTTP
validation/auth failures are not integration failures. Re-reading diagnostics
cannot refresh an observation. Raw error strings are never retained.
"""
from datetime import datetime, timezone
import threading
import time


class ReadHealth:
    def __init__(self, *, ttl=120.0, capacity=256, clock=time.monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._rows = {}
        self._lock = threading.Lock()

    def record(self, key, success, *, reason=None):
        now = self.clock()
        stamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if key not in self._rows and len(self._rows) >= self.capacity:
                del self._rows[min(self._rows, key=lambda k: self._rows[k]['time'])]
            old = self._rows.get(key, {})
            failures = 0 if success else old.get('consecutiveFailures', 0) + 1
            self._rows[key] = {
                'time': now, 'success': bool(success), 'lastAttemptAt': stamp,
                'lastSuccessAt': stamp if success else old.get('lastSuccessAt'),
                'consecutiveFailures': failures,
                'reason': None if success else 'read_failed',
            }

    def snapshot(self):
        now = self.clock()
        with self._lock:
            result = {}
            for key, row in self._rows.items():
                expired = now - row['time'] > self.ttl
                result[key] = {
                    'availability': 'available' if row['success'] and not expired else 'unavailable',
                    'lastAttemptAt': row['lastAttemptAt'], 'lastSuccessAt': row['lastSuccessAt'],
                    'ageSeconds': round(max(0, now - row['time']), 1),
                    'consecutiveFailures': row['consecutiveFailures'],
                    'reason': 'observation_expired' if expired else row['reason'],
                }
            return result


# Fixed templates: never retain arbitrary paths, selectors, query strings or bodies.
READ_ROUTES = {
    '/api/v1/presence': 'read', '/api/v1/security/status': 'read',
    '/api/v1/omlx': 'read', '/api/v1/room-audio': 'read',
    '/api/v1/room-audio/pi': 'read', '/api/v1/room-audio/mac': 'read',
    '/api/v1/state': 'read', '/api/v1/events': 'query',
    '/api/v1/services': 'query', '/api/v1/services/{name}': 'read',
    '/api/v1/scheduled-jobs': 'query', '/api/v1/scheduled-job-results': 'query',
    '/api/v1/notification-status': 'read', '/api/v1/signing/status': 'read',
    '/api/v1/local-control': 'readiness', '/health': 'liveness',
}
WRITE_ROUTES = frozenset({
    '/api/v1/local-control', '/api/v1/device-command', '/api/v1/command',
    '/api/v1/services/{name}', '/api/v1/room-audio/stop',
    '/api/v1/room-audio/pi/stop', '/api/v1/room-audio/mac/stop',
    '/api/jarvis/events', '/api/v1/signing/renew',
})


def route(path):
    if path.startswith('/api/v1/services/') and '/' not in path[len('/api/v1/services/'):]:
        return '/api/v1/services/{name}'
    return path


def fresh(value):
    return (isinstance(value, dict) and value.get('ok') is True
            and value.get('stale') is not True and not value.get('error')
            and value.get('verificationPending') is not True)


def successful(path, code, body):
    if not 200 <= code < 300 or not isinstance(body, dict):
        return False
    if not fresh(body):
        return False
    if path == '/api/v1/presence':
        zones = body.get('zones', [])
        return bool(zones) and all(isinstance(z, dict) and z.get('stale') is False
                                   and z.get('state') not in (None, 'unknown') for z in zones)
    if path == '/api/v1/omlx':
        servers = body.get('servers', [])
        return bool(servers) and all(fresh(s) for s in servers)
    if path == '/api/v1/state':
        meta = body.get('subsystemsMeta', {})
        return bool(meta) and all(isinstance(m, dict) and m.get('stale') is False
                                  and not m.get('error') for m in meta.values())
    return True


def response_status(method, path, code, body):
    path = route(path)
    if method == 'POST' and path in WRITE_ROUTES:
        # A 202 acknowledges admission, not completion. No synthetic success label.
        if code == 202:
            return None
        return 'succeeded' if successful(path, code, body) else 'failed'
    kind = READ_ROUTES.get(path) if method == 'GET' else None
    labels = {'read': ('available', 'unavailable'), 'query': ('succeeded', 'failed'),
              'readiness': ('ready', 'not_ready'), 'liveness': ('healthy', 'unhealthy')}
    if kind is None:
        return None
    return labels[kind][0 if successful(path, code, body) else 1]


ENDPOINT_HEALTH = ReadHealth()
SECURITY_HEALTH = ReadHealth()


def observe(method, path, code, body):
    """Only completed GET checks; auth/input rejection and writes cannot poison health."""
    key = route(path)
    if method == 'GET' and key in READ_ROUTES and (200 <= code < 300 or code >= 500):
        ENDPOINT_HEALTH.record(key, successful(key, code, body))


def endpoint_snapshot():
    rows = ENDPOINT_HEALTH.snapshot()
    return {path: rows.get(path, {'availability': 'unavailable', 'reason': 'not_checked',
            'lastAttemptAt': None, 'lastSuccessAt': None, 'ageSeconds': None,
            'consecutiveFailures': 0}) for path in READ_ROUTES}
