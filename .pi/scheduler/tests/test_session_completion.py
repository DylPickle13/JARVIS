from __future__ import annotations
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
import uuid

spec = importlib.util.spec_from_file_location("session_completion", Path(__file__).parents[1] / "session_completion.py")
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
        self.provider = types.SimpleNamespace(configuration=types.SimpleNamespace(environment="development"), send_session_completion=self.send)
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
        completion.deliver(event_id=self.event, slot=2, store=self.store, registry=self.registry,
                           provider=self.provider, gate=gate, invalidate=lambda *args:self.invalidations.append(args),
                           now=lambda: 1000, sleep=lambda _: None)

    def testIndependentDeliveryDeduplicatesAndDoesNotStoreTokens(self):
        self.deliver()
        self.deliver()
        self.assertEqual(len(self.calls), 2)
        self.assertNotEqual(self.calls[0]["apns_id"], self.calls[1]["apns_id"])
        self.assertNotIn("synthetic-fixture-only", " ".join(self.store.iterdump()))
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

    def testInvalidSlotRejected(self):
        with self.assertRaises(ValueError):
            completion.deliver(event_id=self.event, slot=True, store=self.store, registry=self.registry,
                               provider=self.provider, gate=lambda:True, invalidate=lambda *a:None)
