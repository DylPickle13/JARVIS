"""Genuine coordinator read fences + temporary ledger; all device IO is fake."""
import concurrent.futures
from dataclasses import replace
import json
import threading
import unittest
from unittest import mock

import test_device_host as fixture
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core.device_host import HostError

C, P, ACCESS, DEVICE = fixture.C, fixture.P, fixture.ACCESS, fixture.DEVICE


class ReadbackTests(unittest.TestCase):
    setUp = fixture.HostTests.setUp
    make_host = fixture.HostTests.make_host
    complete = fixture.HostTests.complete
    fake_run = fixture.HostTests.fake_run
    request = fixture.HostTests.request
    call = fixture.HostTests.call
    purifier_request = fixture.HostTests.purifier_request
    outcome = fixture.HostTests.outcome
    rows = fixture.HostTests.rows

    def write(self, request=None):
        request = request or self.request()
        parsed = v.parse_request(json.dumps(request).encode())
        self.complete(parsed.command.cohort)
        bound = self.host.prepare(parsed.command, ACCESS)
        self.assertEqual(self.call(request).status, 200)
        return bound, request

    def matching_read(self, cohort=C):
        if cohort is C:
            self.plugs["lamp"]["isOn"] = True
        else:
            self.purifiers["devices"][DEVICE]["isOn"] = False
        self.complete(cohort)

    def test_matching_new_read_clears_barrier_without_refunding_or_replaying(self):
        bound, request = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.host.finish_reconciliation(readback)
        row = self.rows()[0]
        self.assertFalse(row["unresolved"])
        self.assertEqual(row["outcome"], p.Outcome.ACKNOWLEDGED.value)
        self.assertEqual(json.loads(self.call(request).body)["code"], "duplicate-intent")
        self.runner.assert_called_once()

    def test_unknown_outcome_remains_unknown_in_history_after_matching_read(self):
        self.runner.side_effect = RuntimeError("synthetic response loss")
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.host.finish_reconciliation(readback)
        self.assertFalse(self.rows()[0]["unresolved"])
        self.assertEqual(self.rows()[0]["outcome"], p.Outcome.UNKNOWN.value)
        self.runner.assert_called_once()

    def test_no_read_and_command_readback_cannot_clear_quarantine(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])
        self.runner.assert_called_once()

    def test_previous_successful_collection_cannot_be_reused(self):
        bound, _ = self.write()
        self.matching_read()
        readback = self.host.begin_reconciliation(bound)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_collection_started_before_ticket_is_discarded(self):
        bound, _ = self.write()
        revision = self.state.capture_revision("plugs")
        readback = self.host.begin_reconciliation(bound)
        self.plugs["lamp"]["isOn"] = True
        self.complete(C, revision=revision)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_direct_status_application_is_not_aggregate_read_evidence(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.state.apply_plug_result({"name": "lamp", "host": "192.0.2.1", "is_on": True})
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_failed_or_mismatched_read_does_not_clear_and_ticket_is_consumed(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.complete(C)  # Still off, not the requested on.
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.matching_read()
        with self.assertRaises(g.LedgerError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])
        replacement = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.host.finish_reconciliation(replacement)
        self.assertFalse(self.rows()[0]["unresolved"])

    def test_retained_cache_on_read_failure_cannot_clear(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.complete(C, {"ok": False, "plugs": {"lamp": {"ok": False, "error": "read failed"}}})
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_changed_identity_or_aged_read_cannot_clear(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.now += 31
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.complete(C)
        readback = self.host.begin_reconciliation(bound)
        self.plugs["lamp"]["host"] = "192.0.2.9"
        self.complete(C)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_different_goal_cannot_clear_original_command_even_if_read_matches(self):
        _, _ = self.write()
        parsed = v.parse_request(json.dumps(self.request(2, action="plug-off")).encode())
        different = self.host.prepare(parsed.command, ACCESS)
        readback = self.host.begin_reconciliation(different)
        self.complete(C)  # Matches off but original command was on.
        with self.assertRaises(g.LedgerError) as error:
            self.host.finish_reconciliation(readback)
        self.assertEqual(error.exception.code, "command-proof-mismatch")
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_purifier_requires_matching_new_observation_even_after_pending_deadline(self):
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "purifier": {"cid": fixture.CID, "is_on": True,
            "write_accepted": True, "verification_pending": True}}
        bound, _ = self.write(self.purifier_request())
        readback = self.host.begin_reconciliation(bound)
        self.now += 100  # Existing pending UI deadline does not weaken requested-goal matching.
        self.complete(P)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        readback = self.host.begin_reconciliation(bound)
        self.matching_read(P)
        self.host.finish_reconciliation(readback)
        self.assertFalse(self.rows()[0]["unresolved"])
        self.assertEqual(self.rows()[0]["outcome"], p.Outcome.PENDING.value)

    def test_toggle_and_unmodeled_setting_require_explicit_recovery(self):
        for request in (self.request(action="plug-toggle"), self.request(action="purifier-set",
                params={"deviceID": DEVICE, "setting": "timer", "value": "clear"})):
            bound = self.host.prepare(v.parse_request(json.dumps(request).encode()).command, ACCESS)
            with self.assertRaises(HostError):
                self.host.begin_reconciliation(bound)
        self.assertEqual(self.store._observations, {})
        self.runner.assert_not_called()

    def test_authorization_revocation_prevents_reconciliation(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.allow = False
        with self.assertRaises(HostError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_maintenance_epoch_change_invalidates_readback(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        self.store.transition(C, p.Mode.DRAINING)
        with self.assertRaises(g.LedgerError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_expired_ticket_cannot_clear(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        mono, wall = self.store._mono(), self.store._wall()
        with mock.patch.object(self.store, "_mono", return_value=mono + g.TTL_NS), \
             mock.patch.object(self.store, "_wall", return_value=wall + g.TTL_NS):
            with self.assertRaises(g.LedgerError):
                self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_intervening_state_write_fences_the_observation(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        admitted = self.state.begin_device_write("plugs", "lamp", identity="192.0.2.1")
        self.assertIsNotNone(admitted)
        self.state.finish_device_write("plugs", admitted[1], applied_to=None)
        with self.assertRaises(ValueError):
            self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_write_still_active_cannot_begin_readback(self):
        bound, _ = self.write()
        self.matching_read()
        admitted = self.state.begin_device_write("plugs", "tv", identity="192.0.2.2")
        try:
            with self.assertRaises(ValueError):
                self.host.begin_reconciliation(bound)
            self.assertEqual(self.store._observations, {})
        finally:
            self.state.finish_device_write("plugs", admitted[1], applied_to=None)

    def test_readback_does_not_start_or_bypass_collector_scheduling(self):
        bound, _ = self.write(self.purifier_request())
        self.state.start.reset_mock()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read(P)
        self.host.finish_reconciliation(readback)
        self.state.start.assert_not_called()
        self.collect.assert_not_called()
        self.assertEqual(self.state._records["purifier"]["nextDue"], float("inf"))

    def test_context_owner_and_ticket_identity_cannot_be_replaced(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        with self.assertRaises(HostError):
            self.host.finish_reconciliation(replace(readback, owner=object()))
        with self.assertRaises(g.LedgerError):
            self.host.finish_reconciliation(replace(readback, ticket=replace(readback.ticket)))
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_failed_durability_retains_uncertainty_without_retry(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        with mock.patch.object(self.store, "_write", side_effect=OSError("synthetic IO failure")):
            with self.assertRaises(g.LedgerError):
                self.host.finish_reconciliation(readback)
        self.assertTrue(self.rows()[0]["unresolved"])
        self.runner.assert_called_once()

    def test_state_lock_is_held_through_ledger_commit_without_inverse_lock_order(self):
        bound, _ = self.write()
        readback = self.host.begin_reconciliation(bound)
        self.matching_read()
        entered, release, attempted, finished = (threading.Event() for _ in range(4))
        original = self.store._commit
        def commit(data):
            entered.set()
            self.assertTrue(release.wait(5))
            original(data)
        def state_change():
            attempted.set()
            self.state.apply_plug_result({"name": "lamp", "host": "192.0.2.1", "is_on": False})
            finished.set()
        with mock.patch.object(self.store, "_commit", side_effect=commit), concurrent.futures.ThreadPoolExecutor() as pool:
            reconcile = pool.submit(self.host.finish_reconciliation, readback)
            change = None
            try:
                self.assertTrue(entered.wait(5))
                change = pool.submit(state_change)
                self.assertTrue(attempted.wait(5))
                self.assertFalse(finished.wait(.05))
            finally:
                release.set()
            reconcile.result(5)
            change.result(5)
        self.assertFalse(self.rows()[0]["unresolved"])
        self.runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
