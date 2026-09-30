"""Opt-in oMLX admin sessions for the two configured private servers.

No I/O at import. API keys stay in owner-only files; cookies stay in memory.
Only the documented login endpoint is written; no settings/inference requests.
"""
import http.client
from http.cookies import SimpleCookie
import ipaddress
import json
import os
import stat
import threading
import time


class AdminSessions:
    def __init__(self, now=time.monotonic):
        self.now = now
        self.lock = threading.Lock()
        self.sessions = {}
        self.retry_at = {}
        self.busy = set()

    def invalidate(self, host, path):
        with self.lock:
            self.sessions.pop((host, path), None)

    def cookie(self, host, path):
        address = ipaddress.ip_address(host)
        if not (address.is_private or address.is_loopback) or address.is_unspecified or address.is_multicast:
            raise ValueError('Invalid oMLX host')
        identity = (host, path)
        with self.lock:
            cached = self.sessions.get(identity)
            if cached and cached[1] > self.now():
                return cached[0]
            if identity in self.busy or self.retry_at.get(identity, 0) > self.now():
                raise ValueError('oMLX authentication pending')
            self.busy.add(identity)
            self.retry_at[identity] = self.now() + 30
        try:
            key = self._key(path)
            cookie = self._login(host, key)
            with self.lock:
                # Ordinary sessions last 24h. Renew well before expiry.
                self.sessions[identity] = (cookie, self.now() + 12 * 3600)
            return cookie
        finally:
            with self.lock:
                self.busy.discard(identity)

    @staticmethod
    def _key(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Insecure oMLX key file')
            key = stream.read(4097).decode('ascii').strip()
        if not 4 <= len(key) <= 4096 or not key.isprintable() or any(c.isspace() for c in key):
            raise ValueError('Invalid oMLX key file')
        return key

    @staticmethod
    def _login(host, key):
        connection = http.client.HTTPConnection(host, 8000, timeout=3)
        response = None
        guard = None
        try:
            connection.connect()
            transport = connection.sock
            def expire():
                try:
                    transport.shutdown(2)
                except OSError:
                    pass
            guard = threading.Timer(3, expire)
            guard.daemon = True
            guard.start()
            connection.request('POST', '/admin/api/login',
                body=json.dumps({'api_key': key, 'remember': False}),
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError('oMLX login unavailable')
            body = response.read(8193)
            if len(body) > 8192 or json.loads(body).get('success') is not True:
                raise ValueError('Invalid oMLX login response')
            raw = response.getheader('Set-Cookie', '')
            if len(raw) > 8192:
                raise ValueError('Invalid oMLX session')
            cookies = SimpleCookie()
            cookies.load(raw)
            value = cookies.get('omlx_admin_session')
            if value is None or not value.value or len(value.value) > 4096:
                raise ValueError('Missing oMLX session')
            token = value.value
            if not token.isascii() or any(c.isspace() or c in ';,\r\n' for c in token):
                raise ValueError('Invalid oMLX session')
            return 'omlx_admin_session=' + token
        finally:
            if guard is not None:
                guard.cancel()
            if response is not None:
                response.close()
            connection.close()


ADMIN_SESSIONS = AdminSessions()
