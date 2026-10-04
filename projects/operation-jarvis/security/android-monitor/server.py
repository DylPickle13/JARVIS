#!/usr/bin/env python3
"""Read-only, dedicated TLS endpoint for the Android monitor. No device writes."""
import argparse
import hmac
import hashlib
import ipaddress
import fcntl
import os
import stat
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


DISPLAY_RUNTIME = Path.home() / 'Library/Application Support/JARVIS/ajazz-keyboard'


def unknown_display(reason='controller-unavailable'):
    return {'version': 2, 'source': 'computer-display', 'state': 'unknown',
            'ageSeconds': None, 'reason': reason}


def private_json(root, name):
    """Read bounded owner-only regular files; never create or repair watcher state."""
    fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('private-state')
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('state-size')
    return json.loads(raw)


def watcher_running(root):
    fd = os.open(root / 'watcher.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            return False
        try:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return False  # Singleton unlocked: disabled/stopped, even with a recent heartbeat.
        except BlockingIOError:
            return True


def display_presence(root=DISPLAY_RUNTIME, *, provider=presence, now=time.time):
    """Only relay completed Mac actions, with fresh matching presence and heartbeat.

    Fetch before taking the nonblocking shared cycle lock, so slow backend reads
    never delay computer control. Locked, disabled, pending, faulty, initial,
    stale or inconsistent state produces unknown; no actions/state repairs here.
    """
    started = time.monotonic()
    try:
        sample = provider()
        current = now()
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            return unknown_display()
        if not watcher_running(root):
            return unknown_display()
        fd = os.open(root / 'cycle.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as lock:
            info = os.fstat(lock.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                return unknown_display()
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            config = private_json(root, 'display-config.json')
            state = private_json(root, 'display-state.json')
            watcher = private_json(root, 'watcher.json')
        if config != {'enabled': True} or type(config.get('enabled')) is not bool:
            return unknown_display()
        fields = {'version', 'mode', 'away_since', 'away_checks', 'last_tick',
                  'pending', 'fault', 'completed_at'}
        if (type(state) is not dict or set(state) != fields
                or type(state['version']) is not int or state['version'] != 2
                or state['mode'] not in ('nearby', 'away')
                or state['pending'] is not False or state['fault'] is not False
                or type(state['away_checks']) is not int or not 0 <= state['away_checks'] <= 3):
            return unknown_display()
        finite = lambda v: type(v) in (int, float) and math.isfinite(v) and v >= 0
        if (not finite(current) or not finite(state['last_tick'])
                or not 0 <= current - state['last_tick'] <= 15
                or type(watcher) is not dict or type(watcher.get('version')) is not int
                or watcher['version'] != 1 or not finite(watcher.get('heartbeat'))
                or not 0 <= current - watcher['heartbeat'] <= 15):
            return unknown_display()
        age = sample.get('ageSeconds') if type(sample) is dict else None
        if (not finite(age) or sample.get('state') not in ('nearby', 'away')
                or type(sample.get('version')) is not int or sample['version'] != 1
                or age + time.monotonic() - started > 15):
            return unknown_display('presence-unavailable')
        if state['completed_at'] is None:
            return unknown_display('awaiting-transition')
        if (not finite(state['completed_at']) or state['completed_at'] > current
                or state['completed_at'] > state['last_tick']):
            # Successful actions persist completion and last_tick together;
            # future/reversed/incoherent timestamps are never eligible.
            return unknown_display()
        if state['mode'] != sample['state']:
            return unknown_display('transition-pending')
        if not watcher_running(root):
            return unknown_display()
        return {'version': 2, 'source': 'computer-display', 'state': state['mode'],
                'ageSeconds': age + time.monotonic() - started}
    except Exception:
        return unknown_display()


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

    def __init__(self, address, context, token, provider=display_presence):
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
