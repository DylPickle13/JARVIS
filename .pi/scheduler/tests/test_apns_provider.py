from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[3]
PROVIDER_PATH = ROOT / ".pi" / "scheduler" / "apns_provider.py"


def load_provider():
    name = f"jarvis_apns_provider_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, PROVIDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve postponed annotations through the module registry.
    __import__("sys").modules[name] = module
    spec.loader.exec_module(module)
    return module


def decode_part(value: str) -> dict:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


class FakeSigner:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    def sign(self, message: bytes) -> bytes:
        self.messages.append(message)
        return bytes(range(64))


class FakeTransport:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class APNsProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.apns = load_provider()
        self.temp_dir = tempfile.TemporaryDirectory()
        key_dir = Path(self.temp_dir.name) / "credentials"
        key_dir.mkdir(mode=0o700)
        key_dir.chmod(0o700)
        self.key_path = key_dir / "AuthKey_TEST.p8"
        self.key_path.write_text("-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n", encoding="utf-8")
        self.key_path.chmod(0o600)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def configuration(self, *, enabled: bool = True, environment: str = "development"):
        return self.apns.APNsConfiguration(
            team_id="TEAMID1234",
            key_id="KEYID12345",
            key_path=self.key_path,
            enabled=enabled,
            environment=environment,
        )

    def send(self, provider, *, topic=None, sequence=1, token="ab" * 32, job_id="job_fixture"):
        return provider.send_alert(
            topic=topic or self.apns.IPHONE_APNS_TOPIC,
            device_token=token,
            result_sequence=sequence,
            job_id=job_id,
            apns_id="123e4567-e89b-42d3-a456-426614174000",
        )

    def test_provider_token_contains_only_required_claims_and_raw_signature(self) -> None:
        signer = FakeSigner()
        token = self.apns.build_provider_token(
            team_id="TEAMID1234",
            key_id="KEYID12345",
            issued_at=1_800_000_000,
            signer=signer,
        )
        header, claims, signature = token.split(".")
        self.assertEqual(decode_part(header), {"alg": "ES256", "kid": "KEYID12345"})
        self.assertEqual(decode_part(claims), {"iat": 1_800_000_000, "iss": "TEAMID1234"})
        self.assertEqual(len(base64.urlsafe_b64decode(signature + "==")), 64)
        self.assertEqual(signer.messages, [f"{header}.{claims}".encode("ascii")])

    def test_disabled_provider_fails_before_signing_or_transport(self) -> None:
        signer = FakeSigner()
        transport = FakeTransport()
        provider = self.apns.APNsProvider(
            self.configuration(enabled=False), signer=signer, transport=transport
        )
        with self.assertRaisesRegex(self.apns.APNsConfigurationError, "disabled"):
            self.send(provider)
        self.assertEqual(signer.messages, [])
        self.assertEqual(transport.requests, [])

    def test_alert_is_generic_for_both_exact_topics_and_accepted(self) -> None:
        response = self.apns.APNsResponse(200, {"apns-id": "opaque"}, b"")
        transport = FakeTransport(response=response)
        signer = FakeSigner()
        provider = self.apns.APNsProvider(
            self.configuration(environment="production"),
            signer=signer,
            transport=transport,
            now=lambda: 1_800_000_000,
        )

        for topic in (self.apns.IPHONE_APNS_TOPIC, self.apns.WATCH_APNS_TOPIC):
            result = self.send(provider, topic=topic, sequence=41, job_id="private-job-id")
            self.assertTrue(result.accepted)

        self.assertEqual(len(transport.requests), 2)
        for request, topic in zip(
            transport.requests,
            (self.apns.IPHONE_APNS_TOPIC, self.apns.WATCH_APNS_TOPIC),
            strict=True,
        ):
            self.assertEqual(request.host, self.apns.APNS_PRODUCTION_HOST)
            self.assertEqual(request.headers["apns-topic"], topic)
            self.assertEqual(request.headers["apns-id"], "123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(request.headers["apns-push-type"], "alert")
            self.assertEqual(request.headers["apns-expiration"], "1800000300")
            payload = json.loads(request.body)
            self.assertEqual(payload["route"], "scheduled-job-result")
            self.assertEqual(payload["routeVersion"], 1)
            self.assertEqual(payload["resultSequence"], "41")
            self.assertEqual(payload["aps"]["alert"]["body"], self.apns.GENERIC_ALERT_BODY)
            serialized = request.body.decode("utf-8")
            self.assertNotIn("private-job-id", serialized)
            self.assertNotIn("output", serialized.lower())
            self.assertNotIn("prompt", serialized.lower())
            self.assertTrue(request.headers["apns-collapse-id"].startswith("jarvis-"))

    def test_unknown_topic_fails_before_signing_or_transport(self) -> None:
        signer = FakeSigner()
        transport = FakeTransport()
        provider = self.apns.APNsProvider(self.configuration(), signer=signer, transport=transport)
        with self.assertRaisesRegex(self.apns.APNsConfigurationError, "topic"):
            self.send(provider, topic="com.operation-jarvis.jarvis.widget")
        self.assertEqual(signer.messages, [])
        self.assertEqual(transport.requests, [])

    def test_provider_token_is_reused_only_within_bounded_age(self) -> None:
        now = [1_800_000_000]
        signer = FakeSigner()
        transport = FakeTransport(response=self.apns.APNsResponse(200, {}, b""))
        provider = self.apns.APNsProvider(
            self.configuration(), signer=signer, transport=transport, now=lambda: now[0]
        )
        for sequence in (1, 2):
            self.send(provider, sequence=sequence, token="cd" * 32)
        self.assertEqual(len(signer.messages), 1)
        now[0] += self.apns.MAX_PROVIDER_TOKEN_AGE_SECONDS
        self.send(provider, sequence=3, token="cd" * 32)
        self.assertEqual(len(signer.messages), 2)

    def test_unregistered_response_invalidates_without_exposing_token(self) -> None:
        transport = FakeTransport(
            response=self.apns.APNsResponse(410, {}, b'{"reason":"Unregistered","timestamp":1800000000000}')
        )
        provider = self.apns.APNsProvider(
            self.configuration(), signer=FakeSigner(), transport=transport
        )
        result = self.send(provider, sequence=9, token="ef" * 32)
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.reason, "Unregistered")
        self.assertTrue(result.invalidate_token)
        self.assertEqual(result.invalidation_timestamp, 1_800_000_000)

    def test_retry_and_ambiguous_transport_are_classified_without_network(self) -> None:
        retry = self.apns.classify_response(
            self.apns.APNsResponse(429, {"retry-after": "12"}, b'{"reason":"TooManyRequests"}')
        )
        self.assertEqual(retry.outcome, "retry")
        self.assertEqual(retry.retry_after_seconds, 12)

        transport = FakeTransport(error=self.apns.APNsTransportError("fixture"))
        provider = self.apns.APNsProvider(
            self.configuration(), signer=FakeSigner(), transport=transport
        )
        ambiguous = self.send(provider, sequence=10, token="12" * 32)
        self.assertEqual(ambiguous.outcome, "ambiguous")
        self.assertEqual(ambiguous.reason, "transport-error")

    def test_private_key_permissions_are_fail_closed(self) -> None:
        self.key_path.chmod(0o644)
        transport = FakeTransport()
        provider = self.apns.APNsProvider(
            self.configuration(), signer=FakeSigner(), transport=transport
        )
        with self.assertRaisesRegex(self.apns.APNsConfigurationError, "owner-only"):
            self.send(provider, token="34" * 32)
        self.assertEqual(transport.requests, [])

    def test_der_es256_signature_is_converted_to_fixed_width_raw_values(self) -> None:
        der = bytes.fromhex("300702010102020080")
        raw = self.apns.der_es256_to_raw(der)
        self.assertEqual(len(raw), 64)
        self.assertEqual(raw[:32], b"\0" * 31 + b"\x01")
        self.assertEqual(raw[32:], b"\0" * 31 + b"\x80")


if __name__ == "__main__":
    unittest.main()
