#!/usr/bin/env python3
"""Read-only USB iPhone discovery and Blackmagic candidate-port reachability.
No pairing secrets, installation, local listener, recording, or media access.
A reachable port is NOT an authenticated API/control validation.
"""
import json
import plistlib
import socket
import struct


def exact(sock, size):
    if size < 0 or size > 1024 * 1024:
        raise ValueError('Invalid response length')
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError('Connection closed')
        data += part
    return data


def connect():
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(5)
    sock.connect('/var/run/usbmuxd')
    return sock


def mux(sock, request):
    body = plistlib.dumps({'ClientVersionString': 'phone-recording', 'ProgName': 'phone-recording', 'kLibUSBMuxVersion': 3, **request})
    sock.sendall(struct.pack('<IIII', len(body) + 16, 1, 8, 1) + body)
    length, version, message, tag = struct.unpack('<IIII', exact(sock, 16))
    if (version, message, tag) != (1, 8, 1):
        raise ValueError('Unexpected usbmux response')
    return plistlib.loads(exact(sock, length - 16))


def inspect():
    with connect() as sock:
        devices = mux(sock, {'MessageType': 'ListDevices'}).get('DeviceList', [])
    devices = [d for d in devices if d.get('Properties', {}).get('ConnectionType') == 'USB']
    if len(devices) != 1:
        return {'ok': False, 'error': 'Expected exactly one USB Apple device', 'count': len(devices)}
    device = devices[0]['DeviceID']
    result = {'usb_connected': True}
    with connect() as sock:
        code = mux(sock, {'MessageType': 'Connect', 'DeviceID': device, 'PortNumber': socket.htons(62078)}).get('Number')
        if code != 0:
            return {'ok': False, 'error': 'Device information connection unavailable'}
        for key in ['ProductType', 'ProductVersion']:
            body = plistlib.dumps({'Label': 'phone-recording', 'Request': 'GetValue', 'Key': key})
            sock.sendall(struct.pack('>I', len(body)) + body)
            response = plistlib.loads(exact(sock, struct.unpack('>I', exact(sock, 4))[0]))
            result[key] = response.get('Value', response.get('Error', 'unavailable'))
    # Community integration reports Camera App 3.4 HTTPS API on port 4444.
    # TCP reachability only: no TLS bypass, credentials, or guessed API calls.
    with connect() as sock:
        code = mux(sock, {'MessageType': 'Connect', 'DeviceID': device, 'PortNumber': socket.htons(4444)}).get('Number')
        result['candidate_api_usb_port_4444_reachable'] = code == 0
        result['api_authenticated_or_recording_tested'] = False
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(inspect(), indent=2))
    except (OSError, EOFError, ValueError, KeyError, plistlib.InvalidFileException):
        print(json.dumps({'ok': False, 'error': 'USB discovery failed; check connected/unlocked iPhone'}))
        raise SystemExit(1)
