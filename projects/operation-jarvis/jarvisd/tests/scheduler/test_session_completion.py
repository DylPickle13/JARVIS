from __future__ import annotations
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

spec = importlib.util.spec_from_file_location("session_completion", Path(__file__).parents[2] / "jarvisd_core/scheduler/session_completion.py")
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = completion.receipts(Path(self.temp.name) / "private/receipts.sqlite")
        self.registry = sqlite3.connect(":memory:")
        self.registry.execute("CREATE TABLE notification_devices (platform,installation_id,active,topic,device_token,environment)")
        for platform in ["iphone", "watch"]:
            self.registry.execute("INSERT INTO notification_devices VALUES(?,?,1,?,?,?)", (platform, platform, platform, "synthetic-fixture-only", "development"))
        self.calls = []
        self.responses = []
        self.invalidations = []
        self.provider = types.SimpleNamespace(configuration=types.SimpleNamespace(environment="development"), send_session_notification=self.send)
        self.event = str(uuid.uuid4())

    def tearDown(self):
        self.store.close()
        self.registry.close()
        self.temp.cleanup()

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0) if self.responses else self.result("accepted", 200)

    def result(self, outcome, status):
        return types.SimpleNamespace(outcome=outcome, status_code=status, invalidate_token=False, retry_after_seconds=1)

    def deliver(self, gate=lambda: True):
        return completion.deliver(event_id=self.event, slot=2, title="Build ready", message="The checks passed, sir.",
                           store=self.store, registry=self.registry,
                           provider=self.provider, gate=gate, invalidate=lambda *args:self.invalidations.append(args),
                           now=lambda: 1000, sleep=lambda _: None)

    def testIndependentDeliveryDeduplicatesAndDoesNotStoreTokens(self):
        self.deliver()
        self.deliver()
        self.assertEqual(len(self.calls), 2)
        self.assertNotEqual(self.calls[0]["apns_id"], self.calls[1]["apns_id"])
        dumped = " ".join(self.store.iterdump())
        self.assertNotIn("synthetic-fixture-only", dumped)
        self.assertNotIn("Build ready", dumped)
        self.assertNotIn("The checks passed, sir.", dumped)
        self.assertEqual(self.calls[0]["title"], "Build ready")
        self.assertEqual(self.calls[0]["message"], "The checks passed, sir.")
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM receipts WHERE state='accepted'").fetchone()[0], 2)

    def testGateOffNeverSendsOrEnqueues(self):
        self.deliver(gate=lambda: False)
        self.assertFalse(self.calls)
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 0)

    def testAmbiguousIsNotRetried(self):
        self.responses = [self.result("ambiguous", None)]
        self.deliver()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.execute("SELECT state FROM receipts WHERE platform='iphone'").fetchone()[0], "ambiguous")

    def testDefiniteTransientRetryIsBoundedAndUsesSameRequestIdentity(self):
        self.responses = [self.result("retry", 503)] * 4
        self.deliver()
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(len({x['apns_id'] for x in self.calls[:4]}), 1)

    def testAuthenticationFailureStopsBeforeOtherTopic(self):
        self.responses = [self.result("failed", 403)]
        self.deliver()
        self.assertEqual(len(self.calls), 1)

    def testCrashClaimIsNeverReplayed(self):
        self.store.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?)", (self.event, "iphone", 2, "ambiguous", str(uuid.uuid4()), 1000))
        self.store.commit()
        self.deliver()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['topic'], 'watch')

    def testOutcomeReportsAcceptanceNotScreenDelivery(self):
        result = self.deliver()
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["sessionID"], 2)
        again = self.deliver()
        self.assertTrue(all(device["deduplicated"] for device in again["devices"]))
        self.assertEqual(len(self.calls), 2)

    def testPartialAndUnknownOutcomesDoNotClaimSuccess(self):
        self.responses = [self.result("ambiguous", None)]
        result = self.deliver()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")
        self.assertNotIn("synthetic-fixture-only", json.dumps(result))

    def testNoActiveDevicesIsNotSuccess(self):
        self.registry.execute("UPDATE notification_devices SET active=0")
        result = self.deliver()
        self.assertEqual(result["outcome"], "unavailable")
        self.assertFalse(self.calls)

    def testGateAndEnvironmentChangesSuppressDelivery(self):
        result = self.deliver(gate=lambda: False)
        self.assertEqual(result["outcome"], "disabled")
        self.registry.execute("UPDATE notification_devices SET environment='production'")
        result = self.deliver()
        self.assertFalse(result["ok"])
        self.assertTrue(all(device["outcome"] == "suppressed" for device in result["devices"]))
        self.assertFalse(self.calls)

    def testUnexpectedTransportExceptionStaysAmbiguousAndIsNotReplayed(self):
        def fail(**kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("private transport diagnostic")
        self.provider.send_session_notification = fail
        result = self.deliver()
        self.assertEqual(result["outcome"], "ambiguous")
        self.deliver()
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("private", json.dumps(result))

    def testLegacyLifecycleCLIIsInertEvenWithoutExtensionReload(self):
        result = subprocess.run([sys.executable, str(Path(completion.__file__)), "%1", "123", self.event],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"ok": False, "outcome": "retired", "devices": []})
        self.assertFalse(result.stderr)

    def testStdinEnvelopeIsStrictBoundedAndRequiresExplicitText(self):
        request = {"version": 1, "pane": "%1", "pid": 123, "eventID": self.event,
                   "title": "Ready", "message": "Done"}
        self.assertEqual(completion.decode_request(json.dumps(request).encode()), request)
        invalid = [dict(request, version=True), dict(request, pid=True), dict(request, pane="%1; touch nope"),
                   dict(request, eventID="not-a-uuid"), dict(request, title=" "),
                   dict(request, message="x" * 2049), dict(request, extra="ignored")]
        del invalid[-1]["title"]
        for item in invalid:
            with self.assertRaises((ValueError, TypeError)):
                completion.decode_request(json.dumps(item).encode())
        with self.assertRaises(ValueError):
            completion.decode_request(b" " * (completion.MAX_REQUEST_BYTES + 1))
        with self.assertRaises(ValueError):
            completion.decode_request(json.dumps(request).replace('"version": 1', '"version": 1, "version": 1').encode())

    def testSessionIdentityMustMatchAnAliveApprovedPane(self):
        for slot in range(1, 10):
            name = "jarvis-ios" if slot == 1 else f"jarvis-ios-{slot}"
            with patch.object(completion.subprocess, "run", return_value=types.SimpleNamespace(
                returncode=0, stdout=f"{name}\t123\t0\n")):
                self.assertEqual(completion.resolve_slot("%1", 123), slot)
                self.assertIsNone(completion.resolve_slot("%1", 124))
        for stdout in ("other\t123\t0", "jarvis-ios\t123\t1", "broken"):
            with patch.object(completion.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=stdout)):
                self.assertIsNone(completion.resolve_slot("%1", 123))

    def mainFixture(self, enabled=True, configuration_ok=True, raw=None):
        directory = Path(self.temp.name) / "main-notifications"
        directory.mkdir(exist_ok=True)
        if enabled:
            (directory / "enabled").touch()
        target = Path(self.temp.name) / "registry.sqlite"
        self.registry.commit()
        disk = sqlite3.connect(target)
        try:
            self.registry.backup(disk)
        finally:
            disk.close()
        def validate():
            if not configuration_ok:
                raise RuntimeError("private configuration diagnostic")
        self.provider.configuration.validate_for_send = validate
        runner = types.SimpleNamespace(
            SESSION_NOTIFICATIONS_DIR=directory, DB_PATH=target,
            notification_dispatch_enabled=lambda registry: True,
            _provider_configuration=lambda: self.provider.configuration,
        )
        apns = types.SimpleNamespace(
            APNsConfigurationError=RuntimeError, APNsProvider=lambda configuration: self.provider,
            build_session_notification_payload=lambda slot, title, message: json.dumps({
                "aps": {"alert": {"title": title.strip(), "body": message.strip()}}}).encode(),
        )
        request = {"version": 1, "pane": "%1", "pid": 123, "eventID": self.event,
                   "title": "Build ready", "message": "Checks passed"}
        old_umask = os.umask(0o077)
        try:
            with patch.dict(sys.modules, {"runner": runner, "apns_provider": apns}), \
                 patch.object(sys, "argv", [completion.__file__, "--notify"]), \
                 patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(
                     json.dumps(request).encode() if raw is None else raw))), \
                 patch.object(completion, "resolve_slot", return_value=2):
                return completion.main()
        finally:
            os.umask(old_umask)

    def testExplicitStdinMainUsesExistingGatesRegistryAndPrivateReceipts(self):
        result = self.mainFixture()
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["textAdjusted"], False)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]["message"], "Checks passed")
        receipt_file = Path(self.temp.name) / "main-notifications/receipts.sqlite"
        self.assertEqual(receipt_file.stat().st_mode & 0o777, 0o600)

    def testMainDisabledOrInvalidConfigurationCannotTransmitOrCreateReceipts(self):
        result = self.mainFixture(enabled=False)
        self.assertEqual(result["outcome"], "disabled")
        result = self.mainFixture(configuration_ok=False)
        self.assertEqual(result["outcome"], "unavailable")
        self.assertFalse(self.calls)
        self.assertFalse((Path(self.temp.name) / "main-notifications/receipts.sqlite").exists())
        self.assertNotIn("private configuration", json.dumps(result))

    def testMainInvalidEnvelopeFailsBeforeSessionResolution(self):
        with patch.object(completion, "resolve_slot", side_effect=AssertionError("No lookup on invalid envelope")):
            # mainFixture supplies its own identity stub; exercise main directly.
            with patch.object(sys, "argv", [completion.__file__, "--notify"]), \
                 patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"{}"))):
                old_umask = os.umask(0o077)
                try:
                    self.assertEqual(completion.main()["outcome"], "invalid")
                finally:
                    os.umask(old_umask)

    def testInvalidSlotRejected(self):
        with self.assertRaises(ValueError):
            completion.deliver(event_id=self.event, slot=True, title="Ready", message="Done",
                               store=self.store, registry=self.registry,
                               provider=self.provider, gate=lambda:True, invalidate=lambda *a:None)
