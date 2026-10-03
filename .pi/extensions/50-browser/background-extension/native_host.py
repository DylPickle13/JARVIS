#!/usr/bin/env python3
"""Chrome native-messaging host for background-only connection-tab creation.

No TCP listener, shell commands, browser launching, window creation, or focus APIs.
The private Unix socket is available only while the patched extension is alive.
stdout is exclusively Chrome's length-prefixed native-messaging protocol.
"""
import fcntl
import hmac
import json
import os
from pathlib import Path
import queue
import socket
import stat
import struct
import sys
import threading
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

MODE = 'jarvis-background-native-v1'
EXTENSION = 'mmlmfjhmonkocbjadbfplnigmagldckm'
MAX_MESSAGE = 65536


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError()
        data.extend(chunk)
    return bytes(data)


def read_frame(stream):
    size = struct.unpack('<I', read_exact(stream, 4))[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError('Invalid frame size')
    value = json.loads(read_exact(stream, size))
    if not isinstance(value, dict):
        raise ValueError('Invalid frame')
    return value


def write_frame(stream, value):
    data = json.dumps(value, separators=(',', ':')).encode()
    if not 0 < len(data) <= MAX_MESSAGE:
        raise ValueError('Invalid frame size')
    stream.write(struct.pack('<I', len(data)) + data)
    stream.flush()


def validate_request(request, directory):
    if request.get('command') != 'connect' or request.get('mode') != MODE:
        raise ValueError('Unsupported request')
    window_id = request.get('windowId')
    if type(window_id) is not int or window_id <= 0:
        raise ValueError('Invalid automation window')
    identity = json.loads((directory / 'extension-window.json').read_text())
    if type(identity.get('windowId')) is not int or identity['windowId'] != window_id:
        raise ValueError('Automation window identity mismatch')
    url = request.get('url')
    if not isinstance(url, str) or len(url) > 16384:
        raise ValueError('Invalid connection URL')
    parsed = urlparse(url)
    if (parsed.scheme != 'chrome-extension' or parsed.netloc != EXTENSION
            or parsed.path != '/connect.html' or parsed.fragment != 'jarvis-automation-anchor-v2'):
        raise ValueError('Invalid connection URL')
    params = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(values) != 1 for values in params.values()):
        raise ValueError('Ambiguous connection parameters')
    token = (directory / 'playwright-extension.token').read_text().strip()
    provided = params.get('token', [''])[0]
    if not token or not hmac.compare_digest(token.encode(), provided.encode()):
        raise ValueError('Connection authentication failed')
    relay = urlparse(params.get('mcpRelayUrl', [''])[0])
    if relay.scheme != 'ws' or relay.hostname not in ('127.0.0.1', '::1') or not relay.port or relay.username or relay.password:
        raise ValueError('Non-loopback relay refused')
    if params.get('protocolVersion') != ['2'] or json.loads(params.get('client', ['{}'])[0]).get('name') != 'JARVIS Browser':
        raise ValueError('Unsupported client')
    return {'command': 'connect', 'mode': MODE, 'windowId': window_id, 'url': url}


class Host:
    def __init__(self, directory, stdin, stdout):
        self.directory, self.stdin, self.stdout = directory, stdin, stdout
        self.pending = {}
        self.lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.stopped = threading.Event()

    def send(self, message):
        with self.output_lock:
            write_frame(self.stdout, message)

    def receive(self):
        try:
            while not self.stopped.is_set():
                response = read_frame(self.stdin)
                with self.lock:
                    waiting = self.pending.get(response.get('id'))
                if waiting:
                    waiting.put(response)
        except (EOFError, OSError, ValueError, TypeError):
            pass
        finally:
            self.stopped.set()
            with self.lock:
                for waiting in self.pending.values():
                    waiting.put({'ok': False})

    def handle(self, client):
        # Only one outstanding request is dispatched by serve(). A timeout or
        # lost response is never replayed, and unknown errors expose no URLs.
        request_id = None
        try:
            client.settimeout(22)
            with client.makefile('rwb', buffering=0) as stream:
                try:
                    message = validate_request(read_frame(stream), self.directory)
                    request_id = str(uuid4())
                    waiting = queue.Queue()
                    with self.lock:
                        self.pending[request_id] = waiting
                    self.send({**message, 'id': request_id})
                    response = waiting.get(timeout=18)
                    if response.get('ok') is not True or response.get('mode') != MODE:
                        raise ValueError('Extension rejected connection')
                    if (type(response.get('windowId')) is not int or response['windowId'] != message['windowId']
                            or type(response.get('connectionTabId')) is not int or response['connectionTabId'] <= 0):
                        raise ValueError('Invalid extension response')
                    result = {key: response[key] for key in ('ok', 'mode', 'windowId', 'connectionTabId')}
                except (OSError, ValueError, TypeError, AttributeError, EOFError, queue.Empty):
                    result = {'ok': False, 'error': 'Background connection failed or outcome unknown; no replay'}
                write_frame(stream, result)
        except (OSError, ValueError):
            pass
        finally:
            if request_id:
                with self.lock:
                    self.pending.pop(request_id, None)

    def serve(self):
        # Native host can only be started successfully by the reviewed addon.
        hello = read_frame(self.stdin)
        if hello != {'type': 'hello', 'mode': MODE}:
            raise ValueError('Unexpected native client')
        private = self.directory / 'browser-native'
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = private.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError('Native socket directory must be private')
        # Only one Chrome profile may own this endpoint. Never unlink another
        # live host's socket when a second profile/worker attempts to connect.
        with open(private / 'host.lock', 'a') as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = private / 'control.sock'
            path.unlink(missing_ok=True)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(path))
                os.chmod(path, 0o600)
                server.listen(4)
                server.settimeout(.5)
                threading.Thread(target=self.receive, daemon=True).start()
                try:
                    while not self.stopped.is_set():
                        try:
                            client, _ = server.accept()
                        except socket.timeout:
                            continue
                        with client:
                            if hasattr(client, 'getpeereid') and client.getpeereid()[0] != os.getuid():
                                continue
                            self.handle(client)
                finally:
                    path.unlink(missing_ok=True)


def main():
    try:
        Host(Path.home() / '.jarvis', sys.stdin.buffer, sys.stdout.buffer).serve()
        return 0
    except (OSError, ValueError, TypeError, EOFError):
        # No traceback: malformed input may contain a connection token.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
