"""Explicit local-client identity and request/reply MACs. Not wired into HTTP yet.

No default credentials, credential recovery, file provisioning or import-time IO.
An owner must enroll clients and an independently reviewed transport certificate.
Legacy API/event tokens and caller claims never confer this authority.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import stat
import re
import secrets
import socket
import sys
import sysconfig
import threading
import weakref
import _socket
import _hashlib
from types import MappingProxyType

from . import client_policy as policy
from . import control_protocol as protocol

PROFILE = "jarvis-local-cli/socket-hmac-v1"
REQUEST_DOMAIN = "jarvis-control-request/1"
REPLY_DOMAIN = "jarvis-control-reply/1"
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PATHS = frozenset({protocol.WINDOW_PATH, protocol.COMMAND_PATH})
HEADER_NAMES = frozenset({"host", "content-type", "content-length", "connection",
    "x-jarvis-control-client", "x-jarvis-control-nonce", "x-jarvis-control-proof"})


class IdentityError(ValueError):
    pass


def hexadecimal(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def valid_port(value):
    return type(value) is int and 1 <= value <= 65535


def digest(body):
    return hashlib.sha256(body).hexdigest()


def source_digest(path):
    """Bounded regular-file source check, never an unbounded read or FIFO wait."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        limit = 128 * 1024 * 1024
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
            raise IdentityError('unsupported-control-source')
        result = hashlib.sha256()
        total = 0
        while chunk := source.read(min(1024 * 1024, limit + 1 - total)):
            total += len(chunk)
            if total > limit:
                raise IdentityError('oversized-control-source')
            result.update(chunk)
        after = os.fstat(source.fileno())
        if total != metadata.st_size or (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise IdentityError('changed-control-source')
        return result.hexdigest()


def _mac(key, parts):
    encoded = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.new(bytes.fromhex(key), encoded, hashlib.sha256).hexdigest()


def request_proof(key, *, port, client, nonce, path, body):
    return _mac(key, [REQUEST_DOMAIN, port, client, nonce, "POST", path, digest(body)])


def reply_proof(key, *, port, client, nonce, path, request_digest, status, body):
    return _mac(key, [REPLY_DOMAIN, port, client, nonce, path, request_digest, status, digest(body)])


@dataclass(frozen=True)
class Credential:
    client_id: str
    key: str = field(repr=False)  # Dedicated 256-bit key, never transmitted.

    def __post_init__(self):
        if not hexadecimal(self.client_id, HEX32) or not hexadecimal(self.key, HEX64):
            raise IdentityError("invalid-control-credential")


@dataclass(frozen=True)
class Enrollment:
    credential: Credential = field(repr=False)
    principal: str = field(repr=False)  # Stable across key rotation, not derived from key.
    cohorts: frozenset
    profile: str = PROFILE

    def __post_init__(self):
        if (type(self.credential) is not Credential or not hexadecimal(self.principal, HEX64)
                or type(self.cohorts) is not frozenset or not self.cohorts
                or any(type(c) is not policy.Cohort for c in self.cohorts) or self.profile != PROFILE):
            raise IdentityError("invalid-control-enrollment")


def certificate_sources():
    """Explicit source inventory for the local transport's reviewed runtime.

    Computing these hashes does NOT constitute review/certification. The server
    must receive hashes retained from successful independent tests/owner approval,
    never auto-accept current bytes after a failed check.
    """
    from . import control_transport, control_ledger, commands, control_credentials, control_cli, control_http
    modules = (sys.modules[__name__], control_transport, control_credentials, control_cli, control_http,
               protocol, policy, control_ledger,
               commands, socket, hmac, hashlib, _socket, _hashlib, json, json.decoder,
               json.encoder, secrets, threading, weakref, sysconfig)
    if sys.implementation.name != 'cpython':
        raise IdentityError('unsupported-control-runtime')
    operation = Path(__file__).resolve().parents[2]
    paths = {Path(sys.executable).resolve(), operation / 'jarvis.py', operation / 'control-cli.py',
             operation / 'jarvisd/jarvisd.py'}
    for module in modules:
        source = getattr(module, '__file__', None)
        if source is not None:
            paths.add(Path(source).resolve())
        elif getattr(module.__spec__, 'origin', None) != 'built-in':
            raise IdentityError('unsupported-control-runtime')
    # uv's reviewed CPython statically links _socket/_hashlib into libpython;
    # hashing only the small executable launcher would not pin their bytes.
    if sysconfig.get_config_var('Py_ENABLE_SHARED'):
        library = Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')
        if not library.is_file():
            raise IdentityError('unsupported-control-runtime')
        paths.add(library.resolve())
    return tuple(sorted(paths))


@dataclass(frozen=True)
class TransportCertificate:
    profile: str
    python_version: tuple
    sources: tuple  # Exact absolute (path, sha256) pairs from a reviewed test artifact.

    def valid(self):
        if (type(self.profile) is not str or self.profile != PROFILE
                or type(self.python_version) is not tuple or len(self.python_version) != 3
                or any(type(n) is not int for n in self.python_version)
                or self.python_version != tuple(sys.version_info[:3])):
            return False
        try:
            required = certificate_sources()
            if (type(self.sources) is not tuple or len(self.sources) != len(required)
                    or len({name for name, _ in self.sources}) != len(required)
                    or {name for name, _ in self.sources} != {str(p) for p in required}):
                return False
            for name, expected in self.sources:
                if not hexadecimal(expected, HEX64) or source_digest(name) != expected:
                    return False
            return True
        except (OSError, ValueError, TypeError):
            return False


@dataclass(frozen=True)
class AuthenticatedRequest:
    owner: object = field(repr=False)
    enrollment: Enrollment = field(repr=False)
    nonce: str = field(repr=False)
    path: str
    request_digest: str
    port: int
    access: protocol.Access = field(repr=False)


class IdentityRegistry:
    """Trusted enrolled local CLI only; no network enrollment or caller flags.

    Authentication returns a scoped request object ONLY after verifying the
    reviewed transport/runtime hashes and request integrity. This is an approved
    cooperating-client profile, not cryptographic process attestation against a
    malicious same-user process that has obtained the dedicated key.
    """
    def __init__(self, *, enrollments, certificate, port=8790):
        if (type(enrollments) is not tuple or not 0 < len(enrollments) <= 16
                or any(type(e) is not Enrollment for e in enrollments)
                or len({e.credential.client_id for e in enrollments}) != len(enrollments)
                or type(certificate) is not TransportCertificate or not valid_port(port)):
            raise IdentityError("invalid-control-registry")
        self._enrollments = MappingProxyType({e.credential.client_id: e for e in enrollments})
        self._certificate, self._port = certificate, port
        self._owner = object()
        self._lock = threading.RLock()
        self._revoked = set()
        self._issued = {}

    def revoke(self, client_id):
        with self._lock:
            if client_id not in self._enrollments:
                raise IdentityError("unknown-control-client")
            self._revoked.add(client_id)

    def authorize(self, access, command):
        """Fast host check: exact issued object + current revocation and scope.

        No file IO under the ledger/coordinator locks. Source certification was
        checked at authentication, before admitting this particular request.
        """
        with self._lock:
            entry = self._issued.get(id(access))
            if (entry is None or entry[0]() is not access or entry[1] in self._revoked
                    or type(command) is not protocol.Command):
                return False
            try:
                return command.cohort in access.cohorts
            except (KeyError, ValueError):
                return False

    def _forget(self, key):
        with self._lock:
            self._issued.pop(key, None)

    def authenticate(self, *, peer, method, path, headers, body):
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            raise IdentityError("control-authentication-failed") from None
        # Numeric IPv4 loopback only. No forwarded identity, LAN/Tailscale, DNS,
        # mapped IPv6, proxy, cookies, Origin or legacy/event credential fallback.
        if (str(address) != "127.0.0.1" or type(peer) is not str or method != "POST"
                or path not in PATHS or type(body) is not bytes or not 0 < len(body) <= protocol.MAX_BODY
                or type(headers) not in (tuple, list) or len(headers) != len(HEADER_NAMES)):
            raise IdentityError("control-authentication-failed")
        normalized = {}
        for pair in headers:
            if (type(pair) not in (tuple, list) or len(pair) != 2
                    or any(type(x) is not str or len(x) > 256 or not x.isascii()
                           or any(ord(c) < 32 or ord(c) == 127 for c in x) for x in pair)):
                raise IdentityError("control-authentication-failed")
            key, value = pair
            if key.lower() in normalized:
                raise IdentityError("control-authentication-failed")
            normalized[key.lower()] = value
        if (set(normalized) != HEADER_NAMES or normalized['host'] != f'127.0.0.1:{self._port}'
                or normalized['content-type'] != protocol.CONTENT_TYPE
                or normalized['content-length'] != str(len(body)) or normalized['connection'] != 'close'):
            raise IdentityError("control-authentication-failed")
        client = normalized['x-jarvis-control-client']
        nonce, proof = normalized['x-jarvis-control-nonce'], normalized['x-jarvis-control-proof']
        enrollment = self._enrollments.get(client)
        if (enrollment is None or not hexadecimal(nonce, HEX64) or not hexadecimal(proof, HEX64)
                or not hmac.compare_digest(proof, request_proof(enrollment.credential.key,
                    port=self._port, client=client, nonce=nonce, path=path, body=body))
                or not self._certificate.valid()):
            raise IdentityError("control-authentication-failed")
        with self._lock:
            if client in self._revoked or len(self._issued) >= 2048:
                raise IdentityError("control-authentication-failed")
            access = protocol.Access(enrollment.principal, enrollment.cohorts, True)
            access_id = id(access)
            self._issued[access_id] = (weakref.ref(access, lambda _: self._forget(access_id)), client)
            return AuthenticatedRequest(self._owner, enrollment, nonce, path, digest(body), self._port, access)

    def response_headers(self, request, reply):
        if (type(request) is not AuthenticatedRequest or request.owner is not self._owner
                or self._enrollments.get(request.enrollment.credential.client_id) is not request.enrollment
                or type(reply) is not protocol.Reply or type(reply.status) is not int
                or not 200 <= reply.status <= 599 or type(reply.body) is not bytes
                or len(reply.body) > protocol.MAX_BODY):
            raise IdentityError("invalid-control-reply")
        proof = reply_proof(request.enrollment.credential.key, port=request.port,
            client=request.enrollment.credential.client_id, nonce=request.nonce, path=request.path,
            request_digest=request.request_digest, status=reply.status, body=reply.body)
        return (*reply.headers, ('Content-Length', str(len(reply.body))), ('Connection', 'close'),
                ('X-Jarvis-Control-Proof', proof))
