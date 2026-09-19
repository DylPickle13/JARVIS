"""Opt-in raw v2 HTTP boundary, shared-port legacy dispatch and write fence.

The server must be explicitly composed with a ControlEndpoint. Production main
currently supplies none. No listener/store/identity is created by this module.
"""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import socket
import threading
import time

from . import control_protocol as protocol, control_identity as identity

MAX_HEADER = 16_384
MAX_LINE = 4096
WRITES = frozenset({'plug-on', 'plug-off', 'plug-toggle', 'purifier-set'})


class FramingError(ValueError):
    def __init__(self, status=400):
        self.status = status


class _Input:
    def __init__(self, stream, connection, deadline):
        self.stream, self.connection, self.deadline = stream, connection, deadline
        self.header_bytes = 0

    def read(self, maximum):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise FramingError(408)
        self.connection.settimeout(left)
        # read(n)/readline(n) can internally repeat recv with a renewed relative
        # timeout. read1 performs at most one raw read; recheck total time each time.
        chunk = self.stream.read1(maximum)
        if not chunk:
            raise FramingError()
        return chunk

    def line(self):
        line = bytearray()
        while not line.endswith(b'\r\n'):
            chunk = self.read(1)
            line.extend(chunk)
            self.header_bytes += len(chunk)
            if self.header_bytes > MAX_HEADER or len(line) > MAX_LINE:
                raise FramingError(413)
            if chunk == b'\n' and not line.endswith(b'\r\n'):
                raise FramingError()
        return bytes(line)

    def body(self, length):
        result = bytearray()
        while len(result) < length:
            result.extend(self.read(min(4096, length - len(result))))
        return bytes(result)


class ControlEndpoint:
    def __init__(self, *, registry, api, max_connections=32, input_timeout=5.0):
        if (type(registry) is not identity.IdentityRegistry or type(api) is not protocol.ControlProtocol
                or type(max_connections) is not int or not 1 <= max_connections <= 32
                or type(input_timeout) not in (int, float) or not 0 < input_timeout <= 5):
            raise ValueError('invalid-control-endpoint')
        self.registry, self.api = registry, api
        self.input_timeout = input_timeout
        self._slots = threading.BoundedSemaphore(max_connections)

    def install(self, server):
        """Trusted composition only. Retire v1 writes BEFORE exposing the endpoint.

        This process-local latch is not the required persistent/vendor fence.
        Removing/failing the endpoint cannot reopen v1 on the same server.
        """
        if (getattr(server, '_control_ever_installed', False)
                or getattr(server, 'control_endpoint', None) is not None):
            raise ValueError('control-endpoint-already-installed')
        server.legacy_device_writes_closed = True
        server._control_ever_installed = True
        server.control_endpoint = self

    @contextmanager
    def slot(self):
        acquired = self._slots.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._slots.release()

    def read_request(self, reader, first):
        parts = first[:-2].split(b' ')
        if (len(parts) != 3 or parts[0] != b'POST' or parts[2] != b'HTTP/1.1'
                or parts[1] not in {p.encode('ascii') for p in identity.PATHS}):
            raise FramingError(404)
        headers = []
        while (line := reader.line()) != b'\r\n':
            if len(headers) >= len(identity.HEADER_NAMES):
                raise FramingError()
            key, separator, value = line[:-2].partition(b': ')
            if (not separator or not key or key.lower() not in {n.encode('ascii') for n in identity.HEADER_NAMES}
                    or any(c < 32 or c > 126 for c in key + value)
                    or any(k.lower() == key.decode('ascii').lower() for k, _ in headers)):
                raise FramingError()
            headers.append((key.decode('ascii'), value.decode('ascii')))
        normalized = {key.lower(): value for key, value in headers}
        if (set(normalized) != identity.HEADER_NAMES or normalized['content-type'] != protocol.CONTENT_TYPE
                or normalized['connection'] != 'close'):
            raise FramingError()
        length = normalized['content-length']
        if not length.isascii() or not length.isdigit() or len(length) > 5 or str(int(length)) != length:
            raise FramingError()
        length = int(length)
        if not 0 < length <= protocol.MAX_BODY:
            raise FramingError(413)
        return parts[1].decode('ascii'), headers, reader.body(length)

    @staticmethod
    def send(handler, reply, headers=None):
        if headers is None:
            headers = (*reply.headers, ('Content-Length', str(len(reply.body))), ('Connection', 'close'))
        wire = f'HTTP/1.1 {reply.status} Control\r\n'.encode('ascii')
        wire += b''.join(f'{key}: {value}\r\n'.encode('ascii') for key, value in headers)
        handler.connection.settimeout(5.0)
        handler.wfile.write(wire + b'\r\n' + reply.body)
        handler.wfile.flush()

    def handle(self, handler, reader, first):
        handler.close_connection = True  # No pipeline, outbox or connection reuse.
        try:
            path, headers, body = self.read_request(reader, first)
            context = self.registry.authenticate(peer=handler.client_address[0], method='POST',
                path=path, headers=headers, body=body)
        except FramingError as exc:
            self.send(handler, protocol._error(exc.status, 'invalid-control-framing'))
            return
        except identity.IdentityError:
            self.send(handler, protocol._error(401, 'control-authentication-failed'))
            return
        except (TimeoutError, socket.timeout):
            self.send(handler, protocol._error(408, 'control-input-expired'))
            return
        # Framing/auth errors cannot be confused with faults AFTER admission.
        try:
            reply = self.api.handle(method='POST', path=path, content_type=protocol.CONTENT_TYPE,
                                    body=body, access=context.access)
        except Exception:
            reply = protocol._error(503, 'control-unavailable')
        self.send(handler, reply, self.registry.response_headers(context, reply))


class ControlHTTPServer(ThreadingHTTPServer):
    """Opt-in server with bounded threads/connections BEFORE thread creation.

    Starts with v1 device writes closed even without a usable endpoint. It does
    not construct credentials/ledger/host or grant ownership. Existing main uses
    the old server until the full persistent/vendor-fenced composition is ready.
    """
    daemon_threads = True

    def __init__(self, address, handler, *, max_connections=64):
        if type(max_connections) is not int or not 1 <= max_connections <= 64:
            raise ValueError('invalid-control-connection-limit')
        self._connections = threading.BoundedSemaphore(max_connections)
        self.legacy_device_writes_closed = True
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self._connections.acquire(blocking=False):
            # No queue and no new thread; a bounded best-effort rejection cannot
            # acknowledge original command delivery or advise a retry.
            try:
                request.settimeout(.1)
                request.sendall(b'HTTP/1.1 503 Control busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self._connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._connections.release()


class ControlHTTPMixin:
    """No endpoint: exactly the existing BaseHTTPRequestHandler implementation.

    Opted-in server: bound the first line before choosing v2 versus legacy. Raw v2
    never enters the old JSON handler; invalid v2 aliases cannot become v1 commands.
    Non-v2 requests continue through the same parser/methods. Only their request
    line has a tighter size/deadline limit when this boundary is installed.
    """
    def handle_one_request(self):
        endpoint = getattr(self.server, 'control_endpoint', None)
        if endpoint is None:
            return super().handle_one_request()
        self.close_connection = True
        try:
            with endpoint.slot() as admitted:
                if not admitted:
                    endpoint.send(self, protocol._error(503, 'control-busy'))
                    return
                reader = _Input(self.rfile, self.connection, time.monotonic() + endpoint.input_timeout)
                first = reader.line()
                # Conservative classification catches malformed spacing and absolute
                # URI attempts as v2 failures, rather than handing them to old routes.
                if b'/api/v2/' in first:
                    endpoint.handle(self, reader, first)
                    return
            self.connection.settimeout(30)
            self.raw_requestline = first
            if not self.parse_request():
                return
            method = 'do_' + self.command
            if not hasattr(self, method):
                self.send_error(501, 'Unsupported method')
                return
            getattr(self, method)()
            self.wfile.flush()
        except FramingError as exc:
            self.close_connection = True
            endpoint.send(self, protocol._error(exc.status, 'invalid-control-framing'))
        except (OSError, TimeoutError):
            self.close_connection = True
