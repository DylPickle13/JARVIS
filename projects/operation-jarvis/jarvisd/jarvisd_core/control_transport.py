"""Local CLI candidate transport: one connection, one submission, no fallback.

Numeric IPv4 loopback only. Ignores proxies/DNS, does not redirect, recover keys,
reconnect, enqueue, or retry. Request and response MACs authenticate the intended
peer without revealing the dedicated client key to a process occupying the port.
Not an HTTP listener, CLI integration, TLS substitute or ownership activation.
"""
from dataclasses import dataclass, field
import hmac
import math
import re
import secrets
import socket
import threading
import time

from . import client_policy as policy
from . import control_protocol as protocol
from .control_ledger import TTL_NS
from . import control_identity as identity

MAX_HEADER = 16_384
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_STATUS = re.compile(rb"HTTP/1\.[01] ([2-5][0-9]{2})(?: [\x20-\x7e]*)?\Z")


class TransportError(ValueError):
    """No automatic replay is permitted, regardless of when failure happened."""


@dataclass(frozen=True)
class VerifiedReply:
    status: int
    body: bytes


class LoopbackTransport:
    def __init__(self, credential, *, port=8790, timeout=60.0):
        if (type(credential) is not identity.Credential or not identity.valid_port(port)
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 120):
            raise TransportError("invalid-control-transport")
        self._credential, self._port, self._timeout = credential, port, timeout

    def exchange(self, path, body, *, deadline=None):
        started = time.monotonic()
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise TransportError("invalid-control-deadline")
        limit = started + self._timeout
        deadline = limit if deadline is None else min(deadline, limit)
        if deadline <= started:
            raise TransportError("control-deadline-exceeded; never replay automatically")
        if path not in identity.PATHS or type(body) is not bytes or not 0 < len(body) <= protocol.MAX_BODY:
            raise TransportError("invalid-control-request")
        nonce = secrets.token_hex(32)
        credential = self._credential
        proof = identity.request_proof(credential.key, port=self._port,
            client=credential.client_id, nonce=nonce, path=path, body=body)
        headers = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self._port}\r\n"
            f"Content-Type: {protocol.CONTENT_TYPE}\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\nX-Jarvis-Control-Client: {credential.client_id}\r\n"
            f"X-Jarvis-Control-Nonce: {nonce}\r\nX-Jarvis-Control-Proof: {proof}\r\n\r\n").encode("ascii")
        def remaining(sock):
            duration = deadline - time.monotonic()
            if duration <= 0:
                raise TransportError("control-deadline-exceeded; never replay automatically")
            sock.settimeout(duration)

        try:
            # No create_connection/getaddrinfo, HTTP pool, credentials delegate,
            # redirect handler or retry machinery; no second socket on any error.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                remaining(sock)
                sock.connect(("127.0.0.1", self._port))
                remaining(sock)
                sock.sendall(headers + body)

                def receive(maximum):
                    remaining(sock)
                    return sock.recv(maximum)

                raw = bytearray()
                while b"\r\n\r\n" not in raw:
                    chunk = receive(min(4096, MAX_HEADER + 1 - len(raw)))
                    if not chunk:
                        raise TransportError("incomplete-control-reply")
                    raw.extend(chunk)
                    if b"\r\n\r\n" not in raw and len(raw) > MAX_HEADER:
                        raise TransportError("oversized-control-header")
                start = raw.index(b"\r\n\r\n")
                if start + 4 > MAX_HEADER:
                    raise TransportError("oversized-control-header")
                lines = bytes(raw[:start]).split(b"\r\n")
                status_line = _STATUS.fullmatch(lines[0])
                if status_line is None or len(lines) > 33:
                    raise TransportError("invalid-control-framing")
                status = int(status_line[1])
                fields = {}
                for line in lines[1:]:
                    name, separator, value = line.partition(b":")
                    if not separator or not _HEADER_NAME.fullmatch(name):
                        raise TransportError("invalid-control-framing")
                    name = name.lower()
                    if name in fields or any(c < 32 or c > 126 for c in value):
                        raise TransportError("invalid-control-framing")
                    fields[name] = value.strip(b" ")
                length = fields.get(b"content-length", b"")
                if (not re.fullmatch(rb"0|[1-9][0-9]{0,4}", length)
                        or not 0 < int(length) <= protocol.MAX_BODY
                        or b"transfer-encoding" in fields
                        or fields.get(b"content-type") != protocol.CONTENT_TYPE.encode("ascii")
                        or fields.get(b"cache-control") != b"no-store"
                        or fields.get(b"connection") != b"close"):
                    raise TransportError("invalid-control-framing")
                length = int(length)
                payload = bytearray(raw[start + 4:])
                while len(payload) <= length:
                    chunk = receive(min(4096, length + 1 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                if len(payload) != length:
                    raise TransportError("incomplete-or-oversized-control-reply")
                payload = bytes(payload)
                proof = fields.get(b"x-jarvis-control-proof", b"").decode("ascii")
                expected = identity.reply_proof(credential.key, port=self._port,
                    client=credential.client_id, nonce=nonce, path=path,
                    request_digest=identity.digest(body), status=status, body=payload)
                if not identity.hexadecimal(proof, identity.HEX64) or not hmac.compare_digest(proof, expected):
                    raise TransportError("control-peer-not-authenticated")
                # An authentic redirect is STILL not followed or accepted.
                if 300 <= status < 400:
                    raise TransportError("control-redirect-forbidden")
                return VerifiedReply(status, payload)
        except (OSError, UnicodeError):
            raise TransportError("control-transport-failed; delivery unknown; never replay automatically") from None
        # Cancellation/BaseException closes the socket and propagates. The intent
        # budget below was consumed BEFORE entering this method and stays consumed.


@dataclass(frozen=True)
class Window:
    owner: object = field(repr=False)
    cohort: policy.Cohort
    incarnation: str
    epoch: int
    token: str = field(repr=False)
    received: float = field(repr=False)


class Intent:
    """Process-local intent budget, not durable deduplication or an offline outbox."""
    __slots__ = ('_owner', '_request', '_body', '_lock', '_consumed')

    def __init__(self, owner, request, body):
        self._owner, self._request, self._body = owner, request, body
        self._lock = threading.Lock()
        self._consumed = False

    @property
    def request(self):
        return self._request

    def _claim(self, owner):
        with self._lock:
            if self._consumed:
                raise TransportError("intent-already-consumed; never replay")
            self._consumed = True
            if self._owner is not owner:
                raise TransportError("intent-client-mismatch; never replay")
            return self._body


class ControlClient:
    def __init__(self, credential, *, port=8790, timeout=60.0, deadline=None):
        started = time.monotonic()
        self._transport = LoopbackTransport(credential, port=port, timeout=timeout)
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise TransportError("invalid-control-deadline")
        # A CLI client represents one bounded invocation, not an immortal session.
        # Metadata and construction must never renew the caller's earlier budget.
        self._deadline = min(started + timeout, deadline) if deadline is not None else started + timeout
        self._owner = object()

    def window(self, cohort):
        if type(cohort) is not policy.Cohort:
            raise TransportError("invalid-control-cohort")
        reply = self._transport.exchange(protocol.WINDOW_PATH,
            protocol._encode({"protocol": protocol.PROTOCOL, "cohort": cohort.value}), deadline=self._deadline)
        try:
            data = protocol._decode(reply.body)
            if (reply.status != 200 or set(data) != {"protocol", "kind", "cohort", "incarnation", "epoch", "window", "maxAgeMs"}
                    or data["kind"] != "window" or data["cohort"] != cohort.value
                    or not protocol._hex(data["incarnation"], protocol._HEX32)
                    or not protocol._hex(data["window"], protocol._HEX32) or not protocol._epoch(data["epoch"])
                    or type(data["maxAgeMs"]) is not int or data["maxAgeMs"] != TTL_NS // 1_000_000):
                raise TransportError("invalid-control-window")
            return Window(self._owner, cohort, data["incarnation"], data["epoch"], data["window"], time.monotonic())
        except protocol.ProtocolError:
            raise TransportError("invalid-control-window") from None

    def intent(self, window, action, params):
        if (type(window) is not Window or window.owner is not self._owner
                or not 0 <= time.monotonic() - window.received < TTL_NS / 1_000_000_000):
            raise TransportError("expired-or-foreign-control-window")
        body = protocol._encode({"protocol": protocol.PROTOCOL, "requestID": secrets.token_hex(16),
            "incarnation": window.incarnation, "epoch": window.epoch, "window": window.token,
            "operation": {"action": action, "params": params}})
        request = protocol.parse_request(body)
        if request.command.cohort is not window.cohort:
            raise TransportError("control-window-cohort-mismatch")
        return Intent(self._owner, request, body)

    def submit(self, intent):
        if type(intent) is not Intent:
            raise TransportError("invalid-control-intent")
        body = intent._claim(self._owner)
        try:
            reply = self._transport.exchange(protocol.COMMAND_PATH, body, deadline=self._deadline)
        except TransportError:
            return policy.Outcome.UNKNOWN
        return protocol.classify_receipt(intent.request, status=reply.status,
            content_type=protocol.CONTENT_TYPE, body=reply.body,
            intended_peer=True, single_submission=True)
