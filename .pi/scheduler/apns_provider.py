#!/usr/bin/env python3
"""Fail-closed APNs provider for private JARVIS scheduled-result alerts.

The module has no import-time credential or network side effects. Callers must
explicitly enable and validate a configuration before any signing or transport.
Device registration, durable outbox state, retry policy, and activation remain
scheduler-owned.
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
import unicodedata
from typing import Callable, Mapping, Protocol

IPHONE_APNS_TOPIC = "com.operation-jarvis.jarvis"
WATCH_APNS_TOPIC = "com.operation-jarvis.jarvis.watchkitapp"
APNS_TOPICS = frozenset({IPHONE_APNS_TOPIC, WATCH_APNS_TOPIC})
APNS_PRODUCTION_HOST = "api.push.apple.com"
APNS_SANDBOX_HOST = "api.sandbox.push.apple.com"
APNS_ENVIRONMENTS = frozenset({"development", "production"})
FALLBACK_ALERT_TITLE = "JARVIS Jobs"
FALLBACK_ALERT_BODY = "Result details are ready in Jobs."
ROUTE_NAME = "scheduled-job-result"
ROUTE_VERSION = 1
MAX_PROVIDER_TOKEN_AGE_SECONDS = 50 * 60
DEFAULT_EXPIRATION_SECONDS = 5 * 60
MAX_PAYLOAD_BYTES = 1024
MAX_ALERT_TITLE_BYTES = 120
MAX_ALERT_PREVIEW_CHARACTERS = 240
MAX_ALERT_BODY_BYTES = 640
MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]{1,160})\]\([^)\s]+\)")
URL_RE = re.compile(r"\b(?:[a-z][a-z0-9+.-]{1,15}://|www\.)[^\s<>()]+", re.IGNORECASE)
BARE_NETWORK_LOCATION_RE = re.compile(
    r"(?<![@\w])(?:(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?|"
    r"(?:[a-z0-9-]+\.)+(?:com|org|net|ca|io|dev|app|ai|co|local|internal))"
    r"(?:/[^\s<>()]*)?",
    re.IGNORECASE,
)
LOCAL_PATH_RE = re.compile(
    r"(?i)(?:(?<![a-z0-9])(?:~?/|\.\.?/)[^\s,;]+|"
    r"(?<![a-z0-9])[a-z]:\\[^\s,;]+|(?<!\S)(?:[a-z0-9._~-]+/)+[^\s,;]+)"
)
SENSITIVE_CONTEXT_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?:prompts?|models?|credentials?|tokens?|secrets?|passwords?|passwd|"
    r"authorization|auth|api[_ -]?key|private[_ -]?key|access[_ -]?key|cookies?|"
    r"session[_ -]?id)(?![a-z0-9])|<local-path>"
)
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:token|secret|password|passwd|authorization|api[_ -]?key|private[_ -]?key|"
    r"access[_ -]?key|cookie|session[_ -]?id)\b\s*[:=]"
)
OPAQUE_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:eyJ[A-Za-z0-9_-]{20,}|[A-Fa-f0-9]{32,}|"
    r"(?:sk|pk|gh[opusr]|xox[abprs])[-_][A-Za-z0-9_-]{16,}|[A-Za-z0-9_+/=-]{40,})(?![A-Za-z0-9])"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
DEVICE_TOKEN_RE = re.compile(r"^[0-9A-Fa-f]{64,200}$")
APPLE_IDENTIFIER_RE = re.compile(r"^[A-Z0-9]{10}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
APNS_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
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
    environment: str = "development"

    @property
    def host(self) -> str:
        return APNS_PRODUCTION_HOST if self.environment == "production" else APNS_SANDBOX_HOST

    def validate_for_send(self) -> None:
        if not self.enabled:
            raise APNsConfigurationError("APNs delivery is disabled")
        if not APPLE_IDENTIFIER_RE.fullmatch(self.team_id):
            raise APNsConfigurationError("APNs Team ID is invalid")
        if not APPLE_IDENTIFIER_RE.fullmatch(self.key_id):
            raise APNsConfigurationError("APNs Key ID is invalid")
        if self.environment not in APNS_ENVIRONMENTS:
            raise APNsConfigurationError("APNs environment is invalid")
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
    invalidation_timestamp: int | None = None

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
    header = _b64url(
        json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    claims = _b64url(
        json.dumps({"iat": issued_at, "iss": team_id}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
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
            lines.extend(
                f"header = {_curl_config_quote(f'{name}: {value}')}" for name, value in request.headers.items()
            )
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


def _response_payload(response: APNsResponse) -> dict:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _retry_after(headers: Mapping[str, str], default: int) -> int:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(1, min(3600, int(raw))) if raw is not None else default
    except (TypeError, ValueError):
        return default


def classify_response(response: APNsResponse) -> APNsSendResult:
    payload = _response_payload(response)
    raw_reason = payload.get("reason")
    reason = raw_reason if isinstance(raw_reason, str) and raw_reason in KNOWN_REASONS else "unknown"
    raw_timestamp = payload.get("timestamp")
    timestamp = None
    if isinstance(raw_timestamp, int) and not isinstance(raw_timestamp, bool) and raw_timestamp >= 0:
        # APNs documents token-invalidation timestamps in milliseconds since
        # the Unix epoch. Normalize once so scheduler comparisons use seconds.
        timestamp = raw_timestamp // 1_000 if raw_timestamp >= 10_000_000_000 else raw_timestamp
    if response.status_code == 200:
        return APNsSendResult("accepted", 200, "accepted")
    if response.status_code == 410 or reason in TOKEN_INVALIDATION_REASONS:
        return APNsSendResult(
            "failed",
            response.status_code,
            reason,
            invalidate_token=True,
            invalidation_timestamp=timestamp,
        )
    if response.status_code in RETRYABLE_STATUS_CODES:
        return APNsSendResult(
            "retry",
            response.status_code,
            reason,
            retry_after_seconds=_retry_after(response.headers, 30),
        )
    return APNsSendResult("failed", response.status_code, reason)


def _truncate_utf8(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value
    suffix = "…"
    allowance = max(0, maximum - len(suffix.encode("utf-8")))
    prefix = encoded[:allowance]
    while prefix:
        try:
            return prefix.decode("utf-8").rstrip() + suffix
        except UnicodeDecodeError as exc:
            prefix = prefix[: exc.start]
    return suffix if maximum >= len(suffix.encode("utf-8")) else ""


def _truncate_characters(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    if maximum <= 0:
        return ""
    if maximum == 1:
        return "…"
    return value[: maximum - 1].rstrip() + "…"


def _plain_notification_text(value: str, *, replace_links: bool) -> str:
    text = unicodedata.normalize(
        "NFC",
        str(value or "").replace("\r\n", "\n").replace("\r", "\n"),
    )
    text = "".join(
        character
        for character in text
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
    )
    if replace_links:
        text = MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)
        text = URL_RE.sub("link available in Jobs", text)
        text = BARE_NETWORK_LOCATION_RE.sub("link available in Jobs", text)
    # Result summaries are sanitized before persistence. This second, stricter
    # boundary deliberately falls back to generic text whenever a summary still
    # resembles private metadata, a credential, a token, or any local path.
    # Partial redaction is not sufficient for Lock Screen content because paths
    # and prompts may contain spaces or otherwise ambiguous boundaries.
    if (
        SENSITIVE_CONTEXT_RE.search(text)
        or BEARER_RE.search(text)
        or SECRET_ASSIGNMENT_RE.search(text)
        or OPAQUE_SECRET_RE.search(text)
        or PRIVATE_KEY_RE.search(text)
        or LOCAL_PATH_RE.search(text)
    ):
        return ""
    return " ".join(text.split()).strip()


def _display_job_name(value: str) -> str:
    clean = _plain_notification_text(value, replace_links=True)
    words = clean.replace("-", " ").replace("_", " ").split()
    display = " ".join(word[:1].upper() + word[1:] for word in words)
    return _truncate_utf8(display or FALLBACK_ALERT_TITLE, MAX_ALERT_TITLE_BYTES)


def build_alert_payload(
    result_sequence: int,
    *,
    job_name: str,
    status: str,
    summary: str,
) -> bytes:
    if isinstance(result_sequence, bool) or not 0 < result_sequence <= 9_223_372_036_854_775_807:
        raise APNsConfigurationError("APNs result sequence is invalid")
    if status not in {"success", "error"}:
        raise APNsConfigurationError("APNs result status is invalid")
    title = _display_job_name(job_name)
    preview = _plain_notification_text(summary, replace_links=True) or FALLBACK_ALERT_BODY
    preview = _truncate_characters(preview, MAX_ALERT_PREVIEW_CHARACTERS)
    status_label = "Failed" if status == "error" else "Completed"
    body = _truncate_utf8(f"{status_label} — {preview}", MAX_ALERT_BODY_BYTES)
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "thread-id": "jarvis-jobs",
        },
        "resultSequence": str(result_sequence),
        "route": ROUTE_NAME,
        "routeVersion": ROUTE_VERSION,
    }
    def encode() -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    encoded = encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        # JSON escaping can make quote- or backslash-heavy text larger than its
        # UTF-8 representation. Fit only the visible body, preserving the fixed
        # routing metadata, status prefix, and already-bounded title.
        full_body = body
        minimum = len(status_label) + len(" — …")
        low, high = minimum, len(full_body)
        best: bytes | None = None
        while low <= high:
            midpoint = (low + high) // 2
            payload["aps"]["alert"]["body"] = _truncate_characters(full_body, midpoint)
            candidate = encode()
            if len(candidate) <= MAX_PAYLOAD_BYTES:
                best = candidate
                low = midpoint + 1
            else:
                high = midpoint - 1
        if best is None:
            payload["aps"]["alert"] = {
                "title": FALLBACK_ALERT_TITLE,
                "body": f"{status_label} — {FALLBACK_ALERT_BODY}",
            }
            best = encode()
        encoded = best
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise APNsConfigurationError("APNs payload exceeds the private JARVIS limit")
    return encoded


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

    def send_alert(
        self,
        *,
        topic: str,
        device_token: str,
        result_sequence: int,
        job_id: str,
        job_name: str,
        status: str,
        summary: str,
        apns_id: str,
        expiration: int | None = None,
    ) -> APNsSendResult:
        self.configuration.validate_for_send()
        if topic not in APNS_TOPICS:
            raise APNsConfigurationError("APNs topic is not an allowed JARVIS app topic")
        if not DEVICE_TOKEN_RE.fullmatch(device_token):
            raise APNsConfigurationError("APNs device token is invalid")
        if not JOB_ID_RE.fullmatch(job_id):
            raise APNsConfigurationError("APNs job identifier is invalid")
        if not APNS_ID_RE.fullmatch(apns_id):
            raise APNsConfigurationError("APNs request identifier is invalid")

        now = int(self.now())
        resolved_expiration = expiration if expiration is not None else now + DEFAULT_EXPIRATION_SECONDS
        if isinstance(resolved_expiration, bool) or not now < resolved_expiration <= now + DEFAULT_EXPIRATION_SECONDS:
            raise APNsConfigurationError("APNs expiration is invalid")
        payload = build_alert_payload(
            result_sequence,
            job_name=job_name,
            status=status,
            summary=summary,
        )
        provider_token = self._token(now)
        collapse_id = "jarvis-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:32]
        request = APNsRequest(
            host=self.configuration.host,
            path=f"/3/device/{device_token}",
            headers={
                "authorization": f"bearer {provider_token}",
                "apns-topic": topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-expiration": str(resolved_expiration),
                "apns-collapse-id": collapse_id,
                "apns-id": apns_id.lower(),
                "content-type": "application/json",
            },
            body=payload,
        )
        try:
            response = self.transport.send(request)
        except APNsTransportError:
            return APNsSendResult("ambiguous", None, "transport-error")
        return classify_response(response)
