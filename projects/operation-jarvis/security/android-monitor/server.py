#!/usr/bin/env python3
"""Read-only, dedicated TLS endpoint for the Android monitor. No device writes."""
import argparse
import hmac
import hashlib
import ipaddress
import signal
import subprocess
import http.client
import json
import math
from pathlib import Path
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'jarvisd'))
from jarvisd_core.local_control import read_token


def sanitize(payload, elapsed=0):
    unknown = {'version': 1, 'state': 'unknown', 'ageSeconds': None}
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        return unknown
    p = payload.get('presence')
    if not isinstance(p, dict) or p.get('zone') != 'basement' or p.get('stale') is not False:
        return unknown
    age = p.get('ageSeconds')
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
        return unknown
    age += elapsed
    if not 0 <= age <= 15 or p.get('state') not in ('nearby', 'away'):
        return unknown
    return {'version': 1, 'state': p['state'], 'ageSeconds': age}


def presence():
    start = time.monotonic()
    conn = http.client.HTTPConnection('127.0.0.1', 8790, timeout=3)
    try:
        conn.request('GET', '/api/v1/presence', headers={'Authorization': 'Bearer ' + read_token()})
        response = conn.getresponse()
        raw = response.read(16385)
        if response.status != 200 or len(raw) > 16384:
            return sanitize(None)
        return sanitize(json.loads(raw), time.monotonic() - start)
    except Exception:
        return sanitize(None)
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log credentials, client addresses or presence history.

    def do_GET(self):
        if self.path != '/v1/presence':
            self.reply(404, {'error': 'not-found'})
            return
        supplied = self.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode('utf-8'), self.server.authorization):
            self.reply(401, {'error': 'unauthorized'})
            return
        self.reply(200, self.server.provider())

    def reply(self, status, value):
        body = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)


def local_peer(address):
    """Only loopback/RFC1918 clients; never accept public/VPN address ranges."""
    ip = ipaddress.ip_address(address)
    return any(ip in ipaddress.ip_network(net) for net in
               ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def advertise(root, port):
    der = ssl.PEM_cert_to_DER_cert((root / 'server.crt').read_text())
    name = 'JARVIS-' + hashlib.sha256(der).hexdigest()[:32]
    # Only a public certificate fingerprint and port; no token or presence in mDNS.
    return subprocess.Popen(['/usr/bin/dns-sd', '-R', name,
                             '_jarvis-monitor._tcp', 'local.', str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, context, token, provider=presence):
        self.context = context
        self.authorization = ('Bearer ' + token).encode()
        self.provider = provider
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def get_request(self):
        sock, addr = super().get_request()
        if not local_peer(addr[0]):
            sock.close()
            raise OSError('Non-LAN peer rejected')
        sock.settimeout(4)
        try:
            return self.context.wrap_socket(sock, server_side=True), addr
        except Exception:
            sock.close()
            raise

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, *args):
        pass  # Disconnects/timeouts are not credential-bearing tracebacks.


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--private-dir', type=Path, required=True)
    args = p.parse_args()
    root = args.private_dir
    config = json.loads((root / 'server.json').read_text())
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(root / 'server.crt', root / 'server.key')
    discovery = config.get('discovery', False) is True
    server = Server(('0.0.0.0' if discovery else config['bind'], config['port']), ctx, config['token'])
    publisher = None
    def terminate(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        if discovery: publisher = advertise(root, config['port'])
        print('Android monitor read-only TLS endpoint ready.', flush=True)
        # A publisher failure restarts this dedicated relay through launchd.
        server.timeout = 0.5
        while publisher is None or publisher.poll() is None:
            server.handle_request()
    finally:
        server.server_close()
        if publisher is not None:
            publisher.terminate()
            try: publisher.wait(timeout=3)
            except subprocess.TimeoutExpired:
                publisher.kill(); publisher.wait()


if __name__ == '__main__':
    main()
