"""Bounded read-only Unix HTTP; no retries or import-time I/O."""
import http.client
import json
import socket
import threading
import time


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def read_json(path, resource, *, timeout=3.0, maximum=65536):
    deadline = time.monotonic() + timeout
    connection = UnixHTTPConnection(path, timeout)
    timer = None
    try:
        connection.connect()
        transport = connection.sock

        def expire():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # A socket timeout alone is not a total deadline against slow headers.
        timer = threading.Timer(max(.001, deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()
        connection.request('GET', resource)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Local status unavailable')
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Local status deadline')
            transport.settimeout(remaining)
            chunk = response.read1(min(4096, maximum + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > maximum:
                raise ValueError('Local status output limit')
        if time.monotonic() >= deadline:
            raise TimeoutError('Local status deadline')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('Invalid local status')
        return value
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()
