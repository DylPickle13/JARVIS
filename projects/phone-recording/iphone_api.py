#!/usr/bin/env python3
"""USB iPhone API with allowlisted format and explicit start/stop requests.
Certificate pinned on first observation at the user's supplied LAN address.
This pins continuity, not independently verified device identity.
No system trust changes, redirects, authentication, or live video requests.
"""
import hashlib
import json
from pathlib import Path
import http.client
import ssl
import sys
import socket
from iphone_usb import connect, mux

HOST = '192.168.21.158'
PORT = 4444
CERT_SHA256 = '230539b272e99d9d46dfaebeef02f6dafcc06f8c7fa53b63ae0ae8805124ca59'


def request(path, method='GET', payload=None):
    allowed_write = (method == 'PUT' and path == '/control/api/v1/system/videoFormat' and payload == {'name': '3840x2160p30'}) or (method == 'POST' and path in ('/control/api/v1/transports/0/record', '/control/api/v1/transports/0/stop') and payload is None)
    allowed_write = allowed_write or (method == 'PUT' and path == '/control/api/v1/transports/0/proxyRecording' and payload == {'enabled': False})
    if method != 'GET' and not allowed_write:
        raise ValueError('API mutation not allowlisted')
    if not path.startswith('/control/') or any(c in path for c in '\r\n'):
        raise ValueError('Only camera control discovery paths allowed')
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Replaced with exact certificate pin below.
    # USB only: tunnel TLS directly over usbmuxd, without a LAN connection
    # or a TCP forwarding listener. HOST is merely the TLS server-name hint.
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    raw = None
    try:
        with connect() as discovery:
            devices = [d for d in mux(discovery, {'MessageType': 'ListDevices'}).get('DeviceList', []) if d.get('Properties', {}).get('ConnectionType') == 'USB']
        if len(devices) != 1:
            raise RuntimeError('Expected exactly one USB Apple device')
        raw = connect()
        result = mux(raw, {'MessageType': 'Connect', 'DeviceID': devices[0]['DeviceID'], 'PortNumber': socket.htons(PORT)})
        if result.get('Number') != 0:
            raise ConnectionError('iPhone USB API unavailable; no LAN fallback')
        conn.sock = ctx.wrap_socket(raw, server_hostname=HOST)
        if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != CERT_SHA256:
            raise ssl.SSLError('Camera certificate changed; inspect before updating pin')
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {'Content-Type': 'application/json'} if body is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('Response exceeds discovery limit')
        return response.status, body.decode('utf-8')
    finally:
        conn.close()
        if raw is not None:
            raw.close()


def get(path):
    return request(path)


def read_json(path):
    status, body = get('/control/api/v1/' + path)
    if status != 200:
        raise RuntimeError(f'GET {path}: HTTP {status}')
    return json.loads(body)


def setup_4k30():
    if read_json('transports/0/record').get('recording') is not False:
        raise RuntimeError('iPhone not verified idle; no settings changed')
    before = read_json('system/format')
    if before.get('offSpeedEnabled') is not False:
        raise RuntimeError('Off-speed mode enabled/unknown; inspect before changing format')
    if '3840x2160p30' not in read_json('system/supportedVideoFormats').get('videoFormats', []):
        raise RuntimeError('Native 4K/30 not advertised; no settings changed')
    root = Path(__file__).resolve().parent
    # Preserve first pre-change settings; do not overwrite a previous backup.
    backup = root / 'iphone-before-4k30.json'
    if not backup.exists():
        with backup.open('x') as f:
            json.dump(before, f, indent=2)
    if read_json('transports/0/record').get('recording') is not False:
        raise RuntimeError('Recording state changed; no settings changed')
    status, body = request('/control/api/v1/system/videoFormat', 'PUT', {'name': '3840x2160p30'})
    # Never retry a mutation after an ambiguous response.
    if status != 204:
        raise RuntimeError(f'Format update HTTP {status}: {body}; inspect, do not blindly retry')
    after = read_json('system/format')
    ok = (after.get('recordResolution') == {'width': 3840, 'height': 2160}
          and after.get('sensorResolution') == {'width': 3840, 'height': 2160}
          and after.get('frameRate') in ('30', '30.00')
          and after.get('offSpeedEnabled') is False
          and after.get('codec') == before.get('codec')
          and read_json('transports/0/record').get('recording') is False)
    result = {'ok': ok, 'before': before, 'after': after, 'clip_recorded': False}
    (root / 'iphone-4k30-setup-result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    if sys.argv[1:] == ['setup-4k30']:
        result = setup_4k30()
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['ok'] else 1)
    for path in sys.argv[1:] or ['/control/documentation.html']:
        status, body = get(path)
        print(f'{path}: HTTP {status}\n{body}')
