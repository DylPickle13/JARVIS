"""Private temporary files and synthetic callbacks ONLY; no device/SDK calls."""
import concurrent.futures
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

# Reuse the existing isolated test loader; imports never start collectors.
from test_jarvisd import jarvisd as daemon
from jarvisd_core import client_policy as p
from jarvisd_core import control_ledger as g

C = p.Cohort.PLUGS
CLIENT = "a" * 64
RESOURCE = "b" * 64
COMMAND = "c" * 64


def handoff(store, cohort=C):
    state = store.transition(cohort, p.Mode.DRAINING)
    proof = p.HandoffEvidence(cohort, state.epoch, 0, local_workers_quiescent=True,
        legacy_writers_fenced=True, uncertainty_preserved=True, catalogue_validated=True,
        clients_compatible=True, client_transports_checked=True)
    store.transition(cohort, p.Mode.MAINTENANCE, proof)
    return store.transition(cohort, p.Mode.API, proof)


def ready(intent):
    return p.Readiness(intent.epoch, intent.epoch, endpoint_available=True, protocol_verified=True,
        transport_guarded=True, authorized=True, target_known=True, observation_fresh=True,
        target_uncertain=False)


def intent_for(store, number=1, resource=RESOURCE, cohort=C, client=CLIENT):
    window = store.issue_window(cohort, client)
    return g.Intent(cohort, window.incarnation, window.epoch, client, f"{number:032x}", resource,
                    COMMAND, "plug-on" if cohort is C else "purifier-set", window.token)


class Clock:
    def __init__(self):
        self.mono = 1_000_000_000
        self.wall = 1_700_000_000_000_000_000

    def advance(self, ns):
        self.mono += ns
        self.wall += ns


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private-ledger"
        self.clock = Clock()
        g.ControlLedger.initialize(self.path)
        self.store = self.open()
        self.addCleanup(lambda: self.store.close())

    def open(self):
        return g.ControlLedger.open(self.path, monotonic_ns=lambda: self.clock.mono,
                                    wall_ns=lambda: self.clock.wall)

    def activate(self):
        handoff(self.store)
        return intent_for(self.store)

    def execute(self, intent, operation=None, readiness=None):
        return self.store.execute_once(intent, readiness or (lambda: ready(intent)),
            operation or (lambda: g.DispatchResult(p.Outcome.ACKNOWLEDGED, "synthetic-success")))

    def assert_code(self, code, function):
        with self.assertRaises(g.LedgerError) as result:
            function()
        self.assertEqual(result.exception.code, code)
        return result.exception

    def reconcile(self, resource=RESOURCE):
        ticket = self.store.begin_observation(C, resource)
        self.store.reconcile(ticket, reconciled=True)

    def test_creation_is_private_explicit_and_closed(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        for path in self.path.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.snapshot(C).mode, p.Mode.CLOSED)
        self.assert_code("window-unavailable", lambda: self.store.issue_window(C, CLIENT))
        self.assert_code("initialization-refused", lambda: g.ControlLedger.initialize(self.path))

    def test_missing_store_does_not_create_anything(self):
        missing = self.path / "missing"
        self.assert_code("store-open-failed", lambda: g.ControlLedger.open(missing))
        self.assertFalse(missing.exists())

    def test_same_process_second_owner_is_rejected(self):
        self.assert_code("store-busy", self.open)
        self.assertEqual(self.store.snapshot(C).mode, p.Mode.CLOSED)

    def test_restart_advances_epoch_changes_incarnation_and_closes(self):
        intent = self.activate()
        self.store.close()
        self.store = self.open()
        self.assertGreater(self.store.snapshot(C).epoch, intent.epoch)
        self.assertEqual(self.store.snapshot(C).mode, p.Mode.CLOSED)
        handoff(self.store)
        new = intent_for(self.store, 2)
        self.assertNotEqual(new.incarnation, intent.incarnation)
        self.assert_code("window-expired-or-unknown", lambda: self.execute(intent))

    def test_incarnation_reuse_refuses_open_without_resetting_history(self):
        intent = self.activate()
        self.execute(intent)
        self.store.close()
        original = (self.path / "record.json").read_bytes()
        with mock.patch.object(g.uuid, "uuid4", return_value=mock.Mock(hex=intent.incarnation)):
            self.assert_code("incarnation-collision", self.open)
        self.assertEqual((self.path / "record.json").read_bytes(), original)
        self.store = self.open()
        self.assertEqual(self.store.pending_resources(C), {RESOURCE})

    def test_reservation_is_durable_before_callback_and_payload_never_persisted(self):
        intent = self.activate()
        def operation():
            disk = json.loads((self.path / "record.json").read_text())
            self.assertEqual(disk["records"][0]["outcome"], "reserved")
            self.assertTrue(disk["records"][0]["unresolved"])
            return g.DispatchResult(p.Outcome.ACKNOWLEDGED, {"private-selector": "not-for-storage"})
        result = self.execute(intent, operation)
        self.assertIn("private-selector", result.value)
        self.assertNotIn("private-selector", (self.path / "record.json").read_text())
        self.assertEqual(self.store.pending_resources(C), {RESOURCE})

    def test_duplicate_is_not_a_new_before_adapter_rejection(self):
        intent = self.activate()
        self.execute(intent)
        calls = []
        error = self.assert_code("duplicate-intent", lambda: self.execute(intent, lambda: calls.append(1)))
        self.assertEqual(error.prior_outcome, p.Outcome.ACKNOWLEDGED)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.pending_resources(C), {RESOURCE})

    def test_nonce_cannot_be_rebound_to_another_payload_target_or_epoch(self):
        intent = self.activate()
        self.execute(intent)
        for candidate in (replace(intent, command="d" * 64), replace(intent, resource="e" * 64),
                          replace(intent, action="plug-off"), replace(intent, epoch=intent.epoch + 1)):
            self.assert_code("duplicate-intent", lambda: self.execute(candidate))
        self.store.transition(C, p.Mode.DRAINING)
        handoff(self.store)
        self.assert_code("duplicate-intent", lambda: self.execute(intent_for(self.store)))

    def test_second_intent_for_unresolved_target_is_rejected(self):
        intent = self.activate()
        self.execute(intent)
        self.assert_code("resource-unresolved", lambda: self.execute(intent_for(self.store, 2)))
        self.execute(intent_for(self.store, 3, resource="d" * 64))

    def test_callback_exception_preserves_uncertainty_and_no_retry(self):
        intent = self.activate()
        calls = []
        def operation():
            calls.append(1)
            raise TimeoutError("synthetic response loss")
        with self.assertRaises(TimeoutError):
            self.execute(intent, operation)
        error = self.assert_code("duplicate-intent", lambda: self.execute(intent, operation))
        self.assertEqual(error.prior_outcome, p.Outcome.UNKNOWN)
        self.assertEqual(calls, [1])

    def test_baseexception_and_invalid_result_cannot_refund_reservation(self):
        intent = self.activate()
        with self.assertRaises(KeyboardInterrupt):
            self.execute(intent, lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assert_code("duplicate-intent", lambda: self.execute(intent))
        other = intent_for(self.store, 2, resource="d" * 64)
        self.assert_code("invalid-dispatch-result", lambda: self.execute(other, lambda: {"ok": True}))
        self.assertEqual(self.store.pending_resources(C), {RESOURCE, "d" * 64})

    def test_completion_does_not_clear_pending_or_acknowledged_barriers(self):
        intent = self.activate()
        for number, outcome in enumerate((p.Outcome.PENDING, p.Outcome.UNKNOWN, p.Outcome.ACKNOWLEDGED), 1):
            candidate = replace(intent_for(self.store, number), resource=f"{number:064x}")
            self.execute(candidate, lambda: g.DispatchResult(outcome))
            self.assertIn(candidate.resource, self.store.pending_resources(C))

    def test_complete_valid_postwrite_observation_releases_only_resource_barrier(self):
        intent = self.activate()
        self.execute(intent)
        self.reconcile()
        self.assertEqual(self.store.pending_resources(C), set())
        self.assert_code("duplicate-intent", lambda: self.execute(intent))
        self.execute(intent_for(self.store, 2))

    def test_prewrite_observation_cannot_clear_later_reservation(self):
        intent = self.activate()
        ticket = self.store.begin_observation(C, RESOURCE)
        self.execute(intent)
        self.assert_code("stale-observation", lambda: self.store.reconcile(ticket, reconciled=True))
        self.assertEqual(self.store.pending_resources(C), {RESOURCE})

    def test_invalid_forged_reused_and_expired_observations_are_rejected(self):
        self.activate()
        ticket = self.store.begin_observation(C, RESOURCE)
        self.assert_code("invalid-observation", lambda: self.store.reconcile(ticket, reconciled=1))
        self.assert_code("invalid-observation", lambda: self.store.reconcile(ticket, reconciled=True))
        ticket = self.store.begin_observation(C, RESOURCE)
        self.assert_code("invalid-observation", lambda: self.store.reconcile(replace(ticket), reconciled=True))
        ticket = self.store.begin_observation(C, RESOURCE)
        self.clock.advance(g.TTL_NS)
        self.assert_code("invalid-observation", lambda: self.store.reconcile(ticket, reconciled=True))

    def test_observation_from_previous_epoch_cannot_release_quarantine(self):
        intent = self.activate()
        self.execute(intent)
        ticket = self.store.begin_observation(C, RESOURCE)
        self.store.transition(C, p.Mode.DRAINING)
        handoff(self.store)
        self.assert_code("stale-observation", lambda: self.store.reconcile(ticket, reconciled=True))

    def test_expired_window_does_not_dispatch_and_cannot_be_reconstructed(self):
        intent = self.activate()
        calls = []
        self.clock.advance(g.TTL_NS)
        self.assert_code("window-expired-or-unknown", lambda: self.execute(intent, lambda: calls.append(1)))
        self.assert_code("window-expired-or-unknown", lambda: self.execute(replace(intent, window="f" * 32)))
        self.assertEqual(calls, [])

    def test_window_binds_client_cohort_epoch_and_incarnation(self):
        intent = self.activate()
        for field, value in (("client", "e" * 64), ("cohort", p.Cohort.PURIFIER),
                             ("epoch", intent.epoch + 1), ("incarnation", "e" * 32)):
            self.assert_code("window-scope-mismatch", lambda: self.execute(replace(intent, **{field: value})))

    def test_clock_rollback_and_suspend_like_skew_latch_closed(self):
        intent = self.activate()
        self.clock.wall += g.CLOCK_SKEW_NS + 1
        self.assert_code("clock-untrusted", lambda: self.execute(intent))
        self.assert_code("store-unavailable", lambda: self.execute(intent))
        self.store.close()
        self.store = self.open()
        intent = self.activate()
        self.clock.mono -= 1
        self.assert_code("clock-untrusted", lambda: self.execute(intent))

    def test_readiness_delay_and_slow_commit_do_not_extend_window(self):
        intent = self.activate()
        def delayed():
            self.clock.advance(g.TTL_NS)
            return ready(intent)
        self.assert_code("window-expired-or-unknown", lambda: self.execute(intent, readiness=delayed))
        intent = intent_for(self.store, 2)
        original = self.store._commit
        def slow(data):
            original(data)
            self.clock.advance(g.TTL_NS)
        calls = []
        with mock.patch.object(self.store, "_commit", slow):
            self.assert_code("window-expired-or-unknown", lambda: self.execute(intent, lambda: calls.append(1)))
        self.assertEqual(calls, [])
        self.assertIn(RESOURCE, self.store.pending_resources(C))

    def test_closed_wrong_action_stale_unauthorized_and_malformed_intents_do_not_dispatch(self):
        intent = self.activate()
        for candidate in (replace(intent, action="status"), replace(intent, action="arbitrary-shell")):
            self.assert_code("write-not-admitted", lambda: self.execute(candidate))
        for field in ("authorized", "target_known", "observation_fresh", "protocol_verified", "transport_guarded"):
            self.assert_code("write-not-admitted", lambda: self.execute(intent,
                readiness=lambda: replace(ready(intent), **{field: False})))
        for field, value in (("epoch", True), ("resource", "raw-host"), ("client", "caller-name"),
                             ("request_id", "UPPERCASE"), ("command", "raw-private-arguments")):
            self.assert_code("invalid-intent", lambda: self.execute(replace(intent, **{field: value})))
        self.store.transition(C, p.Mode.DRAINING)
        self.assert_code("write-not-admitted", lambda: self.execute(intent))

    def test_reservation_capacity_never_evicts_a_nonce(self):
        intent = self.activate()
        with mock.patch.object(g, "MAX_RECORDS", 1):
            self.execute(intent)
            self.reconcile()
            self.assert_code("store-capacity", lambda: self.execute(intent_for(self.store, 2)))
            self.assert_code("duplicate-intent", lambda: self.execute(intent))
            self.store.transition(C, p.Mode.DRAINING)  # Maintenance is still possible.

    def test_window_and_observation_maps_are_bounded_without_live_eviction(self):
        self.activate()
        with mock.patch.object(g, "MAX_TICKETS", 1):
            self.assert_code("window-capacity", lambda: self.store.issue_window(C, CLIENT))
            self.store.begin_observation(C, RESOURCE)
            self.assert_code("observation-capacity", lambda: self.store.begin_observation(C, RESOURCE))
            self.clock.advance(g.TTL_NS)
            self.store.issue_window(C, CLIENT)
            self.store.begin_observation(C, RESOURCE)

    def test_failed_fsync_prevents_callback_latches_fault_and_preserves_reservation_or_old_record(self):
        intent = self.activate()
        calls = []
        with mock.patch.object(g.os, "fsync", side_effect=OSError("synthetic disk failure")):
            self.assert_code("store-commit-failed", lambda: self.execute(intent, lambda: calls.append(1)))
        self.assert_code("store-unavailable", lambda: self.execute(intent))
        self.assertEqual(calls, [])
        self.store.close()
        self.store = self.open()  # Bounded orphan .next cleanup, old complete record.
        self.assertEqual(self.store.snapshot(C).mode, p.Mode.CLOSED)
        self.assertFalse((self.path / "record.next").exists())

    def test_failure_after_replace_never_grants_callback_and_reopens_uncertain(self):
        intent = self.activate()
        original = g.os.fsync
        def sync(fd):
            if fd == self.store._dfd:
                raise OSError("directory sync failed")
            return original(fd)
        calls = []
        with mock.patch.object(g.os, "fsync", sync):
            self.assert_code("store-commit-failed", lambda: self.execute(intent, lambda: calls.append(1)))
        self.assertEqual(calls, [])
        self.store.close()
        self.store = self.open()
        self.assertEqual(self.store.pending_resources(C), {RESOURCE})
        handoff(self.store)
        error = self.assert_code("duplicate-intent", lambda: self.execute(intent_for(self.store)))
        self.assertEqual(error.prior_outcome, p.Outcome.UNKNOWN)

    def test_failed_completion_commit_does_not_erase_completed_effect(self):
        intent = self.activate()
        calls = []
        original = self.store._write
        def write(data, **kwargs):
            if data["records"] and data["records"][-1]["outcome"] != "reserved":
                raise OSError("synthetic completion failure")
            return original(data, **kwargs)
        def operation():
            calls.append(1)
            return g.DispatchResult(p.Outcome.ACKNOWLEDGED)
        with mock.patch.object(self.store, "_write", write):
            self.assert_code("store-commit-failed", lambda: self.execute(intent, operation))
        self.assertEqual(calls, [1])
        self.store.close()
        self.store = self.open()
        handoff(self.store)
        self.assert_code("duplicate-intent", lambda: self.execute(intent_for(self.store), operation))
        self.assertEqual(calls, [1])

    def test_restart_preserves_resolved_history_and_unresolved_targets(self):
        intent = self.activate()
        self.execute(intent)
        self.reconcile()
        self.execute(intent_for(self.store, 2, resource="d" * 64))
        self.store.close()
        self.store = self.open()
        self.assertEqual(self.store.pending_resources(C), {"d" * 64})
        handoff(self.store)
        self.assert_code("duplicate-intent", lambda: self.execute(intent_for(self.store)))
        self.execute(intent_for(self.store, 3))

    def test_concurrent_duplicate_callbacks_run_once_and_drain_waits(self):
        intent = self.activate()
        started, release = threading.Event(), threading.Event()
        calls = []
        def operation():
            calls.append(1)
            started.set()
            if not release.wait(5):
                raise AssertionError("test release timed out")
            return g.DispatchResult(p.Outcome.ACKNOWLEDGED)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            first = pool.submit(self.execute, intent, operation)
            try:
                self.assertTrue(started.wait(3))
                def duplicate(_):
                    with self.assertRaises(g.LedgerError) as error:
                        self.execute(intent, operation)
                    self.assertIn(error.exception.code, ("duplicate-intent", "admission-busy"))
                    return error.exception.prior_outcome
                self.assertEqual(list(pool.map(duplicate, range(24))), [p.Outcome.UNKNOWN] * 24)
                self.assert_code("observation-not-admitted", lambda: self.store.begin_observation(C, RESOURCE))
                self.assert_code("writes-active", self.store.close)
                state = self.store.transition(C, p.Mode.DRAINING)
                proof = p.HandoffEvidence(C, state.epoch, 0, True, True, True, True, True, True)
                self.assert_code("writes-active", lambda: self.store.transition(C, p.Mode.MAINTENANCE, proof))
            finally:
                release.set()
            first.result(timeout=5)
        self.store.transition(C, p.Mode.MAINTENANCE, proof)
        self.assertEqual(calls, [1])

    def test_gate_and_drain_are_atomic_even_while_readiness_is_checked(self):
        intent = self.activate()
        checking, finish_check = threading.Event(), threading.Event()
        def check():
            checking.set()
            self.assertTrue(finish_check.wait(5))
            return ready(intent)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            execution = pool.submit(self.execute, intent, readiness=check)
            self.assertTrue(checking.wait(3))
            drain = pool.submit(self.store.transition, C, p.Mode.DRAINING)
            try:
                self.assertFalse(drain.done())
            finally:
                finish_check.set()
            try:
                execution.result(timeout=5)
            except g.LedgerError as exc:
                self.assertEqual(exc.code, "write-not-admitted")  # Drain won post-commit recheck.
            self.assertEqual(drain.result(timeout=5).mode, p.Mode.DRAINING)
            self.assertIn(RESOURCE, self.store.pending_resources(C))

    def test_busy_admission_rejects_without_waiting_or_claiming_original_not_sent(self):
        intent = self.activate()
        self.store._mutex.acquire()
        try:
            error = self.assert_code("admission-busy", lambda: self.execute(intent))
            self.assertEqual(error.prior_outcome, p.Outcome.UNKNOWN)
        finally:
            self.store._mutex.release()
        self.assertEqual(self.store.pending_resources(C), set())

    def test_expired_tokens_are_not_reissued_even_if_randomness_repeats(self):
        self.activate()
        with mock.patch.object(g.uuid, "uuid4", return_value=mock.Mock(hex="e" * 32)):
            first = self.store.issue_window(C, CLIENT)
            self.clock.advance(g.TTL_NS)
            second = self.store.issue_window(C, CLIENT)
        self.assertNotEqual(first.token, second.token)
        old = g.Intent(C, first.incarnation, first.epoch, CLIENT, "1" * 32, RESOURCE,
                       COMMAND, "plug-on", first.token)
        self.assert_code("window-expired-or-unknown", lambda: self.execute(old))
        self.store._ticket_serial = p.MAX_EPOCH
        self.assert_code("ticket-counter-exhausted", lambda: self.store.issue_window(C, CLIENT))
        self.assert_code("store-unavailable", lambda: self.store.snapshot(C))

    def test_directory_symlink_and_insecure_directory_are_rejected(self):
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.path, target_is_directory=True)
        self.assert_code("store-open-failed", lambda: g.ControlLedger.open(alias))
        self.store.close()
        self.path.chmod(0o755)
        self.assert_code("unsafe-directory", self.open)
        self.path.chmod(0o700)

    def test_file_symlink_missing_lock_and_directory_replacement_fail_closed(self):
        self.store.close()
        record = self.path / "record.json"
        external = Path(self.temp.name) / "outside-record"
        record.rename(external)
        record.symlink_to(external)
        self.assert_code("store-open-failed", self.open)
        record.unlink(); external.rename(record)
        lock = self.path / "owner.lock"
        lock.unlink()
        self.assert_code("store-open-failed", self.open)
        lock.touch(mode=0o600)
        self.store = self.open()
        self.path.rename(self.path.with_name("moved"))
        g.ControlLedger.initialize(self.path)
        self.assert_code("store-unavailable", lambda: self.store.snapshot(C))

    def test_active_capacity_is_not_a_queue_and_other_cohort_can_drain(self):
        intent = self.activate()
        handoff(self.store, p.Cohort.PURIFIER)
        started, release = threading.Event(), threading.Event()
        def operation():
            started.set()
            if not release.wait(5): raise AssertionError("release timeout")
            return g.DispatchResult(p.Outcome.ACKNOWLEDGED)
        with mock.patch.object(g, "MAX_ACTIVE", 1), concurrent.futures.ThreadPoolExecutor() as pool:
            first = pool.submit(self.execute, intent, operation)
            try:
                self.assertTrue(started.wait(3))
                other = intent_for(self.store, 2, resource="d" * 64)
                self.assert_code("writes-capacity", lambda: self.execute(other))
                self.assertEqual(self.store.transition(p.Cohort.PURIFIER, p.Mode.DRAINING).mode, p.Mode.DRAINING)
            finally:
                release.set()
            first.result(timeout=5)

    def test_handoff_does_not_accept_missing_or_stale_external_evidence(self):
        state = self.store.transition(C, p.Mode.DRAINING)
        self.assert_code("handoff-evidence-required", lambda: self.store.transition(C, p.Mode.MAINTENANCE))
        proof = p.HandoffEvidence(C, state.epoch, 0)
        with self.assertRaises(p.PolicyError):
            self.store.transition(C, p.Mode.MAINTENANCE, proof)
        proof = replace(proof, epoch=state.epoch - 1, legacy_writers_fenced=True,
                        local_workers_quiescent=True, uncertainty_preserved=True)
        with self.assertRaises(p.PolicyError):
            self.store.transition(C, p.Mode.MAINTENANCE, proof)

    def test_live_record_mutation_latches_closed_instead_of_overwriting(self):
        intent = self.activate()
        original = (self.path / "record.json").read_bytes()
        (self.path / "record.json").write_bytes(original + b" ")
        self.assert_code("store-unavailable", lambda: self.execute(intent))
        (self.path / "record.json").write_bytes(original)
        self.assert_code("store-unavailable", lambda: self.execute(intent))

    def test_lock_and_directory_replacement_are_detected(self):
        self.activate()
        (self.path / "owner.lock").rename(self.path / "old-lock")
        (self.path / "owner.lock").touch(mode=0o600)
        self.assert_code("store-unavailable", lambda: self.store.snapshot(C))

    def test_permissions_symlinks_hardlinks_missing_and_corruption_fail_closed(self):
        self.store.close()
        record = self.path / "record.json"
        original = record.read_bytes()
        for blob in (b"", b"{", b'{"schema":1,"schema":1}', b"null", b"x" * (g.MAX_BYTES + 1)):
            record.write_bytes(blob)
            code = "store-open-failed" if len(blob) <= g.MAX_BYTES else "unsafe-store-file"
            self.assert_code(code, self.open)
        record.write_bytes(original)
        record.chmod(0o644)
        self.assert_code("unsafe-store-file", self.open)
        record.chmod(0o600)
        record.rename(self.path / "other")
        record.symlink_to(self.path / "other")
        self.assert_code("unexpected-store-files", self.open)
        record.unlink()
        (self.path / "other").rename(record)
        external = Path(self.temp.name) / "hardlink"
        os.link(record, external)
        self.assert_code("unsafe-store-file", self.open)
        external.unlink()
        record.unlink()
        self.assert_code("store-open-failed", self.open)
        self.assertFalse(record.exists())

    def test_schema_validation_rejects_extra_fields_types_epochs_and_duplicate_rows(self):
        intent = self.activate()
        self.execute(intent)
        self.store.close()
        file = self.path / "record.json"
        original = json.loads(file.read_text())
        mutations = [lambda d: d.update(schema=True), lambda d: d.update(schema=2),
                     lambda d: d.update(extra="not-allowed"),
                     lambda d: d.update(revision=0, incarnation=None, records=[]),
                     lambda d: d["cohorts"][C.value].update(epoch=True),
                     lambda d: d["records"].append(dict(d["records"][0])),
                     lambda d: d["records"][0].update(outcome="confirmed-exactly-once"),
                     lambda d: d["records"][0].update(resource="raw-host")]
        for mutate in mutations:
            data = json.loads(json.dumps(original)); mutate(data)
            file.write_text(json.dumps(data))
            self.assert_code("store-open-failed", self.open)

    def test_inherited_store_is_rejected_before_lock_and_does_not_unlock_parent(self):
        with mock.patch.object(g.os, "getpid", return_value=self.store._pid + 1):
            self.assert_code("forked-store", lambda: self.store.snapshot(C))
            self.assert_code("forked-store", self.store.close)
        self.assert_code("store-busy", self.open)


class ProcessTests(unittest.TestCase):
    def run_child(self, code, path, *args):
        tests = Path(__file__).resolve().parent
        prefix = "import sys; sys.path.insert(0, sys.argv[1]); from test_control_ledger import *\n"
        result = subprocess.run([sys.executable, "-B", "-c", prefix + code, str(tests), str(path), *args],
                                text=True, capture_output=True, timeout=15)
        return result

    def test_cross_process_owner_lease_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger"
            g.ControlLedger.initialize(path)
            with g.ControlLedger.open(path):
                result = self.run_child('''
try: g.ControlLedger.open(sys.argv[2])
except g.LedgerError as exc:
    assert exc.code == 'store-busy'
else: raise AssertionError('second owner acquired')
''', path)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_fork_child_cannot_deadlock_on_or_unlock_parent_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger"
            g.ControlLedger.initialize(path)
            result = self.run_child('''
import signal
store = g.ControlLedger.open(sys.argv[2])
store._mutex.acquire()
pid = os.fork()
if pid == 0:
    signal.alarm(3)
    for function in (lambda: store.snapshot(C), store.close):
        try: function()
        except g.LedgerError as exc: assert exc.code == 'forked-store'
        else: os._exit(81)
    store._release()  # Close inherited descriptors without LOCK_UN on parent's lease.
    os._exit(0)
_, status = os.waitpid(pid, 0)
store._mutex.release()
assert status == 0, status
try: g.ControlLedger.open(sys.argv[2])
except g.LedgerError as exc: assert exc.code == 'store-busy'
else: raise AssertionError('child unlocked parent')
store.close()
with g.ControlLedger.open(sys.argv[2]): pass
''', path)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_process_death_before_and_after_synthetic_dispatch_never_replays(self):
        for checkpoint in ("before", "after"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "ledger"
                g.ControlLedger.initialize(path)
                result = self.run_child('''
store = g.ControlLedger.open(sys.argv[2]); handoff(store)
intent = intent_for(store)
if sys.argv[3] == 'before':
    original = store._commit
    def commit(data):
        original(data)
        if data['records']: os._exit(71)
    store._commit = commit
def operation():
    with open(Path(sys.argv[2]).parent / 'synthetic-calls', 'ab', buffering=0) as stream:
        stream.write(b'once\\n'); os.fsync(stream.fileno())
    os._exit(72)
store.execute_once(intent, lambda: ready(intent), operation)
''', path, checkpoint)
                self.assertEqual(result.returncode, 71 if checkpoint == "before" else 72, result.stderr)
                calls = Path(temp) / "synthetic-calls"
                self.assertEqual(calls.read_bytes() if calls.exists() else b"", b"" if checkpoint == "before" else b"once\n")
                with g.ControlLedger.open(path) as store:
                    self.assertEqual(store.snapshot(C).mode, p.Mode.CLOSED)
                    self.assertEqual(store.pending_resources(C), {RESOURCE})
                    handoff(store)
                    intent = intent_for(store)
                    with self.assertRaises(g.LedgerError) as error:
                        store.execute_once(intent, lambda: ready(intent), lambda: self.fail("replayed"))
                    self.assertEqual(error.exception.code, "duplicate-intent")
                    self.assertEqual(error.exception.prior_outcome, p.Outcome.UNKNOWN)

    def test_process_death_after_temp_sync_before_replace_cannot_grant_or_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger"
            g.ControlLedger.initialize(path)
            result = self.run_child('''
from dataclasses import asdict
store = g.ControlLedger.open(sys.argv[2]); handoff(store)
intent = intent_for(store)
body = asdict(intent); body['cohort'] = intent.cohort.value
(Path(sys.argv[2]).parent / 'intent.json').write_text(json.dumps(body))
def stop(*args, **kwargs): os._exit(73)
g.os.replace = stop
store.execute_once(intent, lambda: ready(intent), lambda: os._exit(99))
''', path)
            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertTrue((path / "record.next").exists())
            body = json.loads((Path(temp) / "intent.json").read_text())
            body["cohort"] = p.Cohort(body["cohort"])
            old_intent = g.Intent(**body)
            with g.ControlLedger.open(path) as store:
                self.assertFalse((path / "record.next").exists())
                self.assertEqual(store.pending_resources(C), set())
                handoff(store)
                with self.assertRaises(g.LedgerError) as error:
                    store.execute_once(old_intent, lambda: ready(old_intent), lambda: self.fail("replayed"))
                self.assertEqual(error.exception.code, "window-expired-or-unknown")

    def test_import_is_io_free_and_live_entrypoints_remain_unwired(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("jarvisd.py", "device-worker.py", "jarvisd_core/control.py", "jarvisd_core/__init__.py"):
            self.assertNotIn("control_ledger", (root / name).read_text())
        code = '''
import sys, os, socket, subprocess
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
def forbidden(*a, **kw): raise AssertionError('import-time IO')
with patch('builtins.open', forbidden), patch.object(os, 'open', forbidden), \\
     patch.object(socket, 'socket', forbidden), patch.object(subprocess, 'Popen', forbidden):
    from jarvisd_core import control_ledger
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(daemon.COMMANDS), 8)
