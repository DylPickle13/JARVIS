#!/usr/bin/env python3
"""Dormant, fail-closed APNs provider for future direct Watch alerts.

This module has no import-time side effects and does not register devices,
request notification permission, read credentials, or contact Apple unless an
explicitly enabled ``APNsProvider.send_alert`` call is made. The scheduler does
not import it before paid Apple Developer Program activation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from typing import Callable, Mapping, Protocol

WATCH_APNS_TOPIC = "com.operation-jarvis.jarvis.watchkitapp"
APNS_PRODUCTION_HOST = "api.push.apple.com"
APNS_SANDBOX_HOST = "api.sandbox.push.apple.com"
GENERIC_ALERT_TITLE = "JARVIS Jobs"
GENERIC_ALERT_BODY = "A scheduled job result is ready."
MAX_PROVIDER_TOKEN_AGE_SECONDS = 50 * 60
DEFAULT_EXPIRATION_SECONDS = 5 * 60
DEVICE_TOKEN_RE = re.compile(r"^[0-9A-Fa-f]{64,200}$")
APPLE_IDENTIFIER_RE = re.compile(r"^[A-Z0-9]{10}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
KNOWN_REASONS = {
    "BadCollapseId",
    "BadDeviceToken",
    "BadExpirationDate",
    "BadMessageId",
    "BadPriority",
    "BadTopic",
    "DeviceTokenNotForTopic",
    "DuplicateHeaders",
    "ExpiredProviderToken",
    "Forbidden",
    "IdleTimeout",
    "InvalidProviderToken",
    "MethodNotAllowed",
    "MissingDeviceToken",
    "MissingTopic",
    "PayloadEmpty",
    "PayloadTooLarge",
    "Shutdown",
    "TooManyProviderTokenUpdates",
    "TooManyRequests",
    "TopicDisallowed",
    "Unregistered",
}
TOKEN_INVALIDATION_REASONS = {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}
RETRYABLE_STATUS_CODES = {429, 500, 503}


class APNsConfigurationError(RuntimeError):
    """Raised before transport when APNs is disabled or configured unsafely."""


class APNsTransportError(RuntimeError):
    """Raised when transport completion is unknown; messages never include tokens."""


class APNsSigner(Protocol):
    def sign(self, message: bytes) -> bytes:
        """Return a raw 64-byte ES256 signature (r || s)."""


@dataclass(frozen=True)
class APNsConfiguration:
    team_id: str
    key_id: str
    key_path: Path
    enabled: bool = False
    production: bool = False
    topic: str = WATCH_APNS_TOPIC

    @property
    def host(self) -> str:
        return APNS_PRODUCTION_HOST if self.production else APNS_SANDBOX_HOST

    def validate_for_send(self) -> None:
        if not self.enabled:
            raise APNsConfigurationError("APNs delivery is disabled")
        if not APPLE_IDENTIFIER_RE.fullmatch(self.team_id):
            raise APNsConfigurationError("APNs Team ID is invalid")
        if not APPLE_IDENTIFIER_RE.fullmatch(self.key_id):
            raise APNsConfigurationError("APNs Key ID is invalid")
        if self.topic != WATCH_APNS_TOPIC:
            raise APNsConfigurationError("Only the JARVIS Watch APNs topic is permitted")
        _validate_private_key_path(self.key_path)


@dataclass(frozen=True)
class APNsRequest:
    host: str
    path: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class APNsResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class APNsSendResult:
    outcome: str
    status_code: int | None
    reason: str
    retry_after_seconds: int | None = None
    invalidate_token: bool = False

    @property
    def accepted(self) -> bool:
        return self.outcome == "accepted"


class APNsTransport(Protocol):
    def send(self, request: APNsRequest) -> APNsResponse:
        """Perform one HTTP/2 APNs request."""


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_private_key_path(path: Path) -> None:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise APNsConfigurationError("APNs private key is unavailable")
    resolved = candidate.resolve()
    key_stat = resolved.stat()
    parent_stat = resolved.parent.stat()
    if key_stat.st_uid != os.getuid() or parent_stat.st_uid != os.getuid():
        raise APNsConfigurationError("APNs private key ownership is invalid")
    if stat.S_IMODE(key_stat.st_mode) & 0o077:
        raise APNsConfigurationError("APNs private key must use owner-only permissions")
    if stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise APNsConfigurationError("APNs private key directory must use owner-only permissions")
    with resolved.open("rb") as handle:
        first_line = handle.readline(80).strip()
    if first_line != b"-----BEGIN PRIVATE KEY-----":
        raise APNsConfigurationError("APNs private key format is invalid")


def _read_der_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    if count < 1 or count > 2 or offset + count > len(data):
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    return int.from_bytes(data[offset : offset + count], "big"), offset + count


def _der_integer(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset >= len(data) or data[offset] != 0x02:
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    length, start = _read_der_length(data, offset + 1)
    end = start + length
    if length < 1 or end > len(data):
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    value = data[start:end]
    if value[0] & 0x80:
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    while len(value) > 1 and value[0] == 0:
        value = value[1:]
    if len(value) > 32:
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    return value.rjust(32, b"\0"), end


def der_es256_to_raw(signature: bytes) -> bytes:
    if not signature or signature[0] != 0x30:
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    sequence_length, offset = _read_der_length(signature, 1)
    if offset + sequence_length != len(signature):
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    r_value, offset = _der_integer(signature, offset)
    s_value, offset = _der_integer(signature, offset)
    if offset != len(signature):
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    return r_value + s_value


class OpenSSLES256Signer:
    """ES256 signer that keeps private-key material outside the Python process."""

    def __init__(self, key_path: Path, openssl_path: str | None = None) -> None:
        self.key_path = key_path.expanduser().resolve()
        self.openssl_path = openssl_path or shutil.which("openssl") or ""

    def sign(self, message: bytes) -> bytes:
        if not self.openssl_path:
            raise APNsConfigurationError("OpenSSL is unavailable for APNs signing")
        try:
            completed = subprocess.run(
                [self.openssl_path, "dgst", "-sha256", "-sign", str(self.key_path)],
                input=message,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise APNsConfigurationError("APNs provider-token signing failed") from exc
        if completed.returncode != 0:
            raise APNsConfigurationError("APNs provider-token signing failed")
        return der_es256_to_raw(completed.stdout)


def build_provider_token(
    *,
    team_id: str,
    key_id: str,
    issued_at: int,
    signer: APNsSigner,
) -> str:
    header = _b64url(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    claims = _b64url(json.dumps({"iat": issued_at, "iss": team_id}, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header}.{claims}".encode("ascii")
    signature = signer.sign(signing_input)
    if len(signature) != 64:
        raise APNsConfigurationError("APNs signer returned an invalid signature")
    return f"{header}.{claims}.{_b64url(signature)}"


def _curl_config_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise APNsTransportError("APNs request contains an invalid value")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class CurlHTTP2Transport:
    """Minimal HTTP/2 transport that passes sensitive headers over stdin, not argv."""

    def __init__(self, curl_path: str | None = None, timeout_seconds: int = 15) -> None:
        self.curl_path = curl_path or shutil.which("curl") or ""
        self.timeout_seconds = max(1, min(60, int(timeout_seconds)))

    def send(self, request: APNsRequest) -> APNsResponse:
        if not self.curl_path:
            raise APNsTransportError("APNs HTTP/2 transport is unavailable")
        with tempfile.TemporaryDirectory(prefix="jarvis-apns-") as raw_temp:
            temp = Path(raw_temp)
            temp.chmod(0o700)
            payload_path = temp / "payload.json"
            headers_path = temp / "response.headers"
            response_path = temp / "response.body"
            payload_path.write_bytes(request.body)
            payload_path.chmod(0o600)
            lines = [
                "silent",
                "show-error",
                "http2",
                'request = "POST"',
                f"url = {_curl_config_quote(f'https://{request.host}{request.path}')}",
                f"connect-timeout = {min(10, self.timeout_seconds)}",
                f"max-time = {self.timeout_seconds}",
                f"data-binary = {_curl_config_quote('@' + str(payload_path))}",
                f"dump-header = {_curl_config_quote(str(headers_path))}",
                f"output = {_curl_config_quote(str(response_path))}",
                'write-out = "%{http_code}"',
            ]
            lines.extend(f"header = {_curl_config_quote(f'{name}: {value}')}" for name, value in request.headers.items())
            try:
                completed = subprocess.run(
                    [self.curl_path, "--config", "-"],
                    input="\n".join(lines) + "\n",
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds + 5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise APNsTransportError("APNs transport completion is unknown") from exc
            if completed.returncode != 0:
                raise APNsTransportError("APNs transport completion is unknown")
            try:
                status_code = int(completed.stdout.strip()[-3:])
            except (TypeError, ValueError) as exc:
                raise APNsTransportError("APNs transport returned an invalid status") from exc
            response_headers: dict[str, str] = {}
            try:
                for line in headers_path.read_text(encoding="iso-8859-1").splitlines():
                    if ":" not in line:
                        continue
                    name, value = line.split(":", 1)
                    response_headers[name.strip().lower()] = value.strip()
                body = response_path.read_bytes()[:16 * 1024]
            except OSError as exc:
                raise APNsTransportError("APNs transport response is unavailable") from exc
            return APNsResponse(status_code=status_code, headers=response_headers, body=body)


def _response_reason(response: APNsResponse) -> str:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return reason if isinstance(reason, str) and reason in KNOWN_REASONS else "unknown"


def _retry_after(headers: Mapping[str, str], default: int) -> int:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(1, min(3600, int(raw))) if raw is not None else default
    except (TypeError, ValueError):
        return default


def classify_response(response: APNsResponse) -> APNsSendResult:
    reason = _response_reason(response)
    if response.status_code == 200:
        return APNsSendResult("accepted", 200, "accepted")
    if response.status_code == 410 or reason in TOKEN_INVALIDATION_REASONS:
        return APNsSendResult("failed", response.status_code, reason, invalidate_token=True)
    if response.status_code in RETRYABLE_STATUS_CODES:
        return APNsSendResult(
            "retry",
            response.status_code,
            reason,
            retry_after_seconds=_retry_after(response.headers, 30),
        )
    return APNsSendResult("failed", response.status_code, reason)


class APNsProvider:
    """One-shot provider. Retry policy and outbox state remain scheduler-owned."""

    def __init__(
        self,
        configuration: APNsConfiguration,
        *,
        signer: APNsSigner | None = None,
        transport: APNsTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.configuration = configuration
        self.signer = signer or OpenSSLES256Signer(configuration.key_path)
        self.transport = transport or CurlHTTP2Transport()
        self.now = now
        self._token_lock = threading.Lock()
        self._provider_token = ""
        self._provider_token_issued_at = 0

    def _token(self, now: int) -> str:
        with self._token_lock:
            if self._provider_token and 0 <= now - self._provider_token_issued_at < MAX_PROVIDER_TOKEN_AGE_SECONDS:
                return self._provider_token
            token = build_provider_token(
                team_id=self.configuration.team_id,
                key_id=self.configuration.key_id,
                issued_at=now,
                signer=self.signer,
            )
            self._provider_token = token
            self._provider_token_issued_at = now
            return token

    def send_alert(self, *, device_token: str, result_sequence: int, job_id: str) -> APNsSendResult:
        self.configuration.validate_for_send()
        if not DEVICE_TOKEN_RE.fullmatch(device_token):
            raise APNsConfigurationError("APNs device token is invalid")
        if isinstance(result_sequence, bool) or not 0 < result_sequence <= 9_223_372_036_854_775_807:
            raise APNsConfigurationError("APNs result sequence is invalid")
        if not JOB_ID_RE.fullmatch(job_id):
            raise APNsConfigurationError("APNs job identifier is invalid")

        now = int(self.now())
        token = self._token(now)
        payload = {
            "aps": {
                "alert": {"title": GENERIC_ALERT_TITLE, "body": GENERIC_ALERT_BODY},
                "sound": "default",
                "thread-id": "jarvis-jobs",
            },
            "resultSequence": str(result_sequence),
        }
        collapse_id = "jarvis-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:32]
        request = APNsRequest(
            host=self.configuration.host,
            path=f"/3/device/{device_token}",
            headers={
                "authorization": f"bearer {token}",
                "apns-topic": self.configuration.topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-expiration": str(now + DEFAULT_EXPIRATION_SECONDS),
                "apns-collapse-id": collapse_id,
                "content-type": "application/json",
            },
            body=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        )
        try:
            response = self.transport.send(request)
        except APNsTransportError:
            return APNsSendResult("ambiguous", None, "transport-error", retry_after_seconds=30)
        return classify_response(response)
