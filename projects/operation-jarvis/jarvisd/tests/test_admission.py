"""Deterministic fake-device concurrency tests; no real adapters or services."""
import concurrent.futures
from contextlib import contextmanager
from pathlib import Path
import threading
import unittest
from unittest import mock

from test_jarvisd import jarvisd as d
from jarvisd_core.admission import AdmissionError, WriteAdmission
from jarvisd_core.control import DeviceCommandDispatcher, UNCERTAIN
from jarvisd_core.devices import _purifier_id
from jarvisd_core.state import StateCoordinator


class GateTests(unittest.TestCase):
    def test_conflict_is_rejected_without_queue_and_slot_releases(self):
        gate = WriteAdmission()
        key = ("plugs", "fake-private-resource")
        with gate.hold(key):
            with self.assertRaises(AdmissionError) as error:
                with gate.hold(key):
                    self.fail("conflicting writer admitted")
            self.assertNotIn(key[1], str(error.exception))
        with gate.hold(key):
            pass
        self.assertEqual(gate._active, set())

    def test_capacity_is_bounded_and_distinct_resources_do_not_conflict(self):
        gate = WriteAdmission(max_active=2)
        with gate.hold(("plugs", "a")), gate.hold(("purifier", "a")):
            with self.assertRaises(AdmissionError):
                with gate.hold(("plugs", "b")):
                    self.fail("capacity exceeded")
        self.assertEqual(gate._active, set())
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                WriteAdmission(value)

    def test_exception_always_releases_slot(self):
        gate = WriteAdmission()
        with self.assertRaises(RuntimeError):
            with gate.hold(("plugs", "a")):
                raise RuntimeError("test")
        with gate.hold(("plugs", "a")):
            pass


class DeviceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.state = StateCoordinator(
            {"plugs": lambda: {}, "purifier": lambda: {}}, version="test", started_at=0,
            now=lambda: self.now,
        )
        self.state.start = mock.Mock()  # All collections are explicitly completed by the test.
        self.gate = WriteAdmission()
        self.ids = {"a": _purifier_id("test-cid-a"), "b": _purifier_id("test-cid-b")}
        self.selectors = {value: "test-cid-" + key for key, value in self.ids.items()}
        self.plugs = {
            "lamp": {"ok": True, "isOn": False, "host": "192.0.2.1"},
            "pedalboard": {"ok": True, "isOn": False, "host": "192.0.2.2"},
        }
        self.purifiers = {"ok": True, "defaultDeviceID": self.ids["a"], "devices": {
            key: {"ok": True, "deviceID": key, "isOn": True, "mode": "auto"}
            for key in self.ids.values()
        }}
        self.complete("plugs", self.plug_batch())
        self.complete("purifier", self.purifiers)
        self.run = mock.Mock()
        self.dispatch = DeviceCommandDispatcher(
            state=self.state, admission=self.gate, cli=Path("/fixed/jarvis-cli"), run=self.run,
            selected_purifier=lambda device_id: self.selectors[device_id], purifier_wait_seconds=15,
        )

    def complete(self, subsystem, result, revision=None):
        if revision is None:
            revision = self.state.capture_revision(subsystem)
        future = concurrent.futures.Future()
        future.set_result(result)
        self.state._complete(subsystem, future, revision)

    def plug_batch(self, **changes):
        return {"ok": True, "plugs": {**self.plugs, **changes}}

    def plug_result(self, name="lamp", is_on=True):
        return {"ok": True, "plug": {"name": name, "host": self.plugs[name]["host"], "is_on": is_on}}

    def purifier_result(self, which="a", is_on=False, pending=False):
        return {"ok": True, "purifier": {"cid": "test-cid-" + which, "is_on": is_on,
                "mode": "auto", "verification_pending": pending}}

    def snapshot(self):
        return self.state.snapshot()["subsystems"]

    def purifier_write(self, which=None):
        params = {"setting": "power", "value": "off"}
        if which:
            params["deviceID"] = self.ids[which]
        return self.dispatch.execute("purifier-set", params)

    def pool(self):
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.addCleanup(lambda: pool.shutdown(wait=True))
        return pool

    def test_client_cannot_override_the_admitted_host_binding(self):
        self.run.return_value = self.plug_result()
        self.dispatch.execute("plug-on", {"plug": "lamp", "expectedHost": "192.0.2.9"})
        argv = self.run.call_args.args[0]
        self.assertEqual(argv[-2:], ["--expected-host", "192.0.2.1"])
        self.assertNotIn("192.0.2.9", argv)

    def test_inconsistent_private_selector_is_rejected_before_dispatch(self):
        self.selectors[self.ids["a"]] = "test-cid-b"
        with self.assertRaises(AdmissionError):
            self.purifier_write()
        self.run.assert_not_called()
        self.assertFalse(self.snapshot()["purifier"]["stale"])
        self.assertFalse(self.gate._active)

    def test_admitted_cid_binding_is_derived_from_private_selector(self):
        self.run.return_value = self.purifier_result(is_on=False)
        result = self.dispatch.execute("purifier-set", {"setting": "power", "value": "off", "expectedCID": "other"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.run.call_args.args[0][-2:], ["--expected-cid", "test-cid-a"])
        self.assertNotIn("other", self.run.call_args.args[0])

    def test_cache_runtime_identity_and_collectors_are_explicit(self):
        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["version"], "test")
        self.assertEqual(set(snapshot["subsystems"]), {"plugs", "purifier"})
        self.assertEqual(self.state._retry_collectors, {})

    def test_explicit_recovery_callback_is_debounced_and_consumed_once(self):
        recovery = mock.Mock(return_value={"ok": True})
        ordinary = mock.Mock(return_value={"ok": True})
        state = StateCoordinator({"purifier": ordinary}, version="test", started_at=0,
                                 retry_collectors={"purifier": recovery}, now=lambda: self.now)
        state.start = mock.Mock()
        state.request_refresh("purifier", retry_cooldown=True)
        state._collect_one("purifier")
        state._collect_one("purifier")
        self.assertEqual(recovery.call_args_list, [mock.call(True), mock.call(False)])
        ordinary.assert_not_called()

    def test_success_applies_verified_result_and_preserves_unrelated_device(self):
        self.run.return_value = self.plug_result()
        result = self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.assertTrue(result["ok"])
        state = self.snapshot()["plugs"]["plugs"]
        self.assertTrue(state["lamp"]["isOn"])
        self.assertFalse(state["lamp"]["stale"])
        self.assertFalse(state["pedalboard"]["stale"])
        self.assertFalse(state["pedalboard"]["isOn"])
        self.assertEqual(self.gate._active, set())
        self.run.assert_called_once_with(["/fixed/jarvis-cli", "--json", "plug-on", "lamp",
                                          "--expected-host", "192.0.2.1"], timeout=30.0, env=None)

    def test_same_device_conflict_is_immediate_and_not_replayed(self):
        entered, release = threading.Event(), threading.Event()
        pool = self.pool()
        self.addCleanup(release.set)
        def run(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return self.plug_result()
        self.run.side_effect = run
        future = pool.submit(self.dispatch.execute, "plug-on", {"plug": "lamp"})
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])
        self.assertFalse(self.snapshot()["plugs"]["plugs"]["pedalboard"]["stale"])
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-off", {"plug": "lamp"})
        release.set()
        self.assertTrue(future.result(2)["ok"])
        self.assertEqual(self.run.call_count, 1)

    def test_two_different_devices_can_execute_concurrently(self):
        entered = {name: threading.Event() for name in self.plugs}
        release = threading.Event()
        pool = self.pool()
        self.addCleanup(release.set)
        def run(argv, **kwargs):
            name = argv[3]
            entered[name].set()
            self.assertTrue(release.wait(3))
            return self.plug_result(name)
        self.run.side_effect = run
        futures = [pool.submit(self.dispatch.execute, "plug-on", {"plug": name}) for name in self.plugs]
        self.assertTrue(all(event.wait(1) for event in entered.values()))
        release.set()
        self.assertTrue(all(f.result(2)["ok"] for f in futures))
        self.assertEqual(self.run.call_count, 2)

    def test_duplicate_plug_host_names_share_one_resource_gate(self):
        self.plugs["lamp-alias"] = dict(self.plugs["lamp"])
        self.complete("plugs", self.plug_batch())
        with self.gate.hold(("plugs", "192.0.2.1")):
            with self.assertRaises(AdmissionError):
                self.dispatch.execute("plug-on", {"plug": "lamp-alias"})
        self.run.assert_not_called()

    def test_failed_write_stales_all_same_host_aliases_not_peers(self):
        self.plugs["lamp-alias"] = dict(self.plugs["lamp"])
        self.complete("plugs", self.plug_batch())
        self.run.return_value = {"ok": False, "error": "timeout"}
        self.dispatch.execute("plug-on", {"plug": "lamp"})
        items = self.snapshot()["plugs"]["plugs"]
        self.assertTrue(items["lamp"]["stale"])
        self.assertIn("uncertain", items["lamp"]["error"])
        self.assertNotIn("lastError", items["lamp"])
        self.assertTrue(items["lamp-alias"]["stale"])
        self.assertFalse(items["pedalboard"]["stale"])
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp-alias"})
        self.assertEqual(self.run.call_count, 1)

    def test_default_and_explicit_purifier_share_identity_and_selector(self):
        with self.gate.hold(("purifier", self.ids["a"])):
            with self.assertRaises(AdmissionError):
                self.purifier_write()
            with self.assertRaises(AdmissionError):
                self.purifier_write("a")
        self.run.assert_not_called()
        self.run.return_value = self.purifier_result()
        self.assertTrue(self.purifier_write()["ok"])
        argv = self.run.call_args.args[0]
        self.assertEqual(argv[argv.index("--purifier") + 1], "test-cid-a")
        self.assertFalse(self.snapshot()["purifier"]["devices"][self.ids["a"]]["isOn"])
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["b"]]["isOn"])

    def test_default_is_pinned_even_if_default_changes_after_resolution(self):
        gate = self.gate
        @contextmanager
        def changing(resource):
            with gate.hold(resource):
                self.complete("purifier", {**self.purifiers, "defaultDeviceID": self.ids["b"]})
                yield
        self.dispatch.admission = mock.Mock(hold=changing)
        self.run.return_value = self.purifier_result("a")
        self.assertTrue(self.purifier_write()["ok"])
        self.assertIn("test-cid-a", self.run.call_args.args[0])
        self.assertNotIn("test-cid-b", self.run.call_args.args[0])

    def test_other_purifier_is_not_blocked_by_peer_gate(self):
        self.run.return_value = self.purifier_result("b")
        with self.gate.hold(("purifier", self.ids["a"])):
            self.assertTrue(self.purifier_write("b")["ok"])

    def test_unknown_devices_and_missing_default_never_reach_adapter(self):
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "203.0.113.123"})
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("purifier-set", {"deviceID": "missing", "setting": "power", "value": "off"})
        self.complete("purifier", {**self.purifiers, "defaultDeviceID": None})
        with self.assertRaises(AdmissionError):
            self.purifier_write()
        self.run.assert_not_called()

    def test_stale_plug_and_purifier_state_rejects_without_refresh_or_write(self):
        self.now += 91
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp"})
        with self.assertRaises(AdmissionError):
            self.purifier_write()
        self.run.assert_not_called()

    def test_freshness_is_rechecked_inside_admission_not_only_on_entry(self):
        gate = self.gate
        @contextmanager
        def age_after_resolve(resource):
            with gate.hold(resource):
                self.now += 31
                yield
        self.dispatch.admission = mock.Mock(hold=age_after_resolve)
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.run.assert_not_called()
        self.assertEqual(self.gate._active, set())

    def test_host_identity_change_after_resolution_rejects_instead_of_switching_locks(self):
        gate = self.gate
        @contextmanager
        def changed(resource):
            with gate.hold(resource):
                self.complete("plugs", self.plug_batch(lamp={"ok": True, "isOn": False, "host": "192.0.2.9"}))
                yield
        self.dispatch.admission = mock.Mock(hold=changed)
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.run.assert_not_called()

    def test_failed_write_fences_prewrite_and_during_write_reads_then_recovers(self):
        before = self.state.capture_revision("plugs")
        during = []
        def fail(*args, **kwargs):
            during.append(self.state.capture_revision("plugs"))
            self.complete("plugs", self.plug_batch(lamp={**self.plugs["lamp"], "isOn": True}))
            self.assertFalse(self.snapshot()["plugs"]["plugs"]["lamp"]["isOn"])
            return {"ok": False, "error": "timeout"}
        self.run.side_effect = fail
        self.assertFalse(self.dispatch.execute("plug-on", {"plug": "lamp"})["ok"])
        for revision in (before, during[0]):
            self.complete("plugs", self.plug_batch(), revision)
            self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.assertEqual(self.run.call_count, 1)
        self.complete("plugs", self.plug_batch(lamp={**self.plugs["lamp"], "isOn": True}))
        self.assertFalse(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])
        self.run.side_effect = None
        self.run.return_value = self.plug_result(is_on=False)
        self.assertTrue(self.dispatch.execute("plug-off", {"plug": "lamp"})["ok"])

    def test_failed_postwrite_read_does_not_clear_uncertainty_via_last_good_grace(self):
        self.run.return_value = {"ok": False}
        self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.complete("plugs", self.plug_batch(lamp={"ok": False, "error": "offline"}))
        self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])
        self.assertFalse(self.snapshot()["plugs"]["plugs"]["pedalboard"]["stale"])

    def test_late_read_cannot_revert_confirmed_write(self):
        old_revision = self.state.capture_revision("plugs")
        self.run.return_value = self.plug_result()
        self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.complete("plugs", self.plug_batch(), old_revision)
        self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["isOn"])

    def test_exception_or_malformed_result_is_uncertain_and_never_retried(self):
        self.run.side_effect = RuntimeError("private-provider-secret")
        result = self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.assertEqual(result, {"ok": False, "error": UNCERTAIN})
        self.assertNotIn("private-provider-secret", str(result))
        self.assertEqual(self.gate._active, set())
        self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])
        self.run.assert_called_once()

    def test_mismatched_identity_or_desired_state_cannot_report_success(self):
        cases = [self.plug_result("pedalboard"), self.plug_result(is_on=False),
                 {"ok": True, "plug": {"name": "lamp", "is_on": True, "host": "192.0.2.9"}},
                 {"ok": True}, []]
        for result in cases:
            with self.subTest(result=result):
                self.complete("plugs", self.plug_batch())
                self.run.return_value = result
                self.assertFalse(self.dispatch.execute("plug-on", {"plug": "lamp"})["ok"])
                self.assertTrue(self.snapshot()["plugs"]["plugs"]["lamp"]["stale"])

    def test_purifier_wrong_identity_or_unconfirmed_nonpending_result_fails_closed(self):
        for raw in (self.purifier_result("b"), self.purifier_result("a", is_on=True),
                    {"ok": True, "purifier": {"cid": "test-cid-a"}}):
            with self.subTest(raw=raw):
                self.complete("purifier", self.purifiers)
                self.run.return_value = raw
                self.assertFalse(self.purifier_write("a")["ok"])
                self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])
                self.assertFalse(self.snapshot()["purifier"]["devices"][self.ids["b"]]["stale"])
                self.assertEqual(self.state._records["purifier"]["nextDue"], float("inf"))

    def test_pending_purifier_result_stays_pending_until_reconciled_batch(self):
        self.run.return_value = self.purifier_result(is_on=True, pending=True)
        self.assertTrue(self.purifier_write()["ok"])
        item = self.snapshot()["purifier"]["devices"][self.ids["a"]]
        self.assertTrue(item["verificationPending"])
        self.assertTrue(item["stale"])
        with self.assertRaises(AdmissionError):
            self.purifier_write()
        # A plain HTTP status read must not clear expected-state verification.
        self.run.return_value = self.purifier_result(is_on=True)
        self.dispatch.execute("purifier-status", {})
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["verificationPending"])
        self.complete("purifier", self.purifiers)
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])
        devices = {**self.purifiers["devices"], self.ids["a"]: {**self.purifiers["devices"][self.ids["a"]], "isOn": False}}
        self.complete("purifier", {**self.purifiers, "devices": devices})
        self.assertFalse(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])

    def test_pending_setting_without_reconciliation_contract_remains_uncertain(self):
        self.run.return_value = self.purifier_result(is_on=True, pending=True)
        result = self.dispatch.execute("purifier-set", {"setting": "display", "value": "off"})
        self.assertFalse(result["ok"])
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])
        revision = self.state.capture_revision("purifier")
        self.assertFalse(self.state.apply_purifier_result(self.purifier_result(pending=True)["purifier"],
                                                        read_revision=revision))
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])

    def test_removed_device_barriers_are_pruned_without_enabling_unknown_writes(self):
        self.run.return_value = {"ok": False}
        self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.complete("plugs", {"ok": True, "plugs": {"pedalboard": self.plugs["pedalboard"]}})
        self.assertEqual(self.state._records["plugs"]["writeBarriers"], {})
        with self.assertRaises(AdmissionError):
            self.dispatch.execute("plug-on", {"plug": "lamp"})
        self.assertEqual(self.run.call_count, 1)

    def test_late_direct_purifier_status_cannot_overwrite_newer_command(self):
        entered, release = threading.Event(), threading.Event()
        pool = self.pool()
        self.addCleanup(release.set)
        def run(argv, **kwargs):
            if argv[-1] == "purifier-status":
                entered.set()
                self.assertTrue(release.wait(3))
                return self.purifier_result(is_on=True)
            return self.purifier_result(is_on=False)
        self.run.side_effect = run
        future = pool.submit(self.dispatch.execute, "purifier-status", {})
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.purifier_write()["ok"])
        release.set()
        self.assertTrue(future.result(2)["ok"])
        self.assertFalse(self.snapshot()["purifier"]["devices"][self.ids["a"]]["isOn"])

    def test_postfailure_direct_purifier_status_can_supply_fresh_observation(self):
        self.run.return_value = {"ok": False, "error": "timeout"}
        self.purifier_write()
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])
        self.run.return_value = self.purifier_result(is_on=True)
        self.dispatch.execute("purifier-status", {})
        self.assertFalse(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])

    def test_direct_read_during_write_cannot_clear_inflight_barrier(self):
        observation, affected = self.state.begin_device_write("purifier", self.ids["a"])
        revision = self.state.capture_revision("purifier")
        self.assertFalse(self.state.apply_purifier_result(self.purifier_result()["purifier"], read_revision=revision))
        self.state.finish_device_write("purifier", affected, applied_to=None)
        self.assertTrue(self.snapshot()["purifier"]["devices"][self.ids["a"]]["stale"])

    def test_read_actions_do_not_acquire_write_gate_or_change_catalog(self):
        self.run.return_value = {"ok": True, "plugs": {}}
        with mock.patch.object(self.gate, "hold", side_effect=AssertionError("unexpected write gate")):
            self.assertTrue(self.dispatch.execute("plug-list", {})["ok"])
        self.run.assert_called_once_with(["/fixed/jarvis-cli", "--json", "plug-list"], timeout=30.0, env=None)

    def test_invalid_command_syntax_does_not_consult_state_or_execute(self):
        with mock.patch.object(self.state, "snapshot", side_effect=AssertionError("unexpected state read")):
            with self.assertRaises(d.CommandError):
                self.dispatch.execute("plug-on", {"plug": "lamp; shell"})
        self.run.assert_not_called()

    def test_http_conflict_uses_existing_error_shape_and_never_calls_adapter(self):
        handler = object.__new__(d.Handler)
        handler.server = mock.Mock(control_endpoint=None)
        handler.path = "/api/v1/command"
        handler._auth_or_respond = mock.Mock(return_value=True)
        handler._read_json = mock.Mock(return_value={"action": "plug-on", "params": {"plug": "lamp"}})
        handler._send = mock.Mock()
        with mock.patch.object(d, "STATE_COORDINATOR", self.state), \
             mock.patch.object(d, "WRITE_ADMISSION", self.gate), \
             mock.patch.object(d, "run_cli_json", self.run), \
             self.gate.hold(("plugs", "192.0.2.1")):
            handler.do_POST()
        code, body = handler._send.call_args.args
        self.assertEqual(code, 409)
        self.assertEqual(set(body), {"ok", "error", "action"})
        self.assertFalse(body["ok"])
        self.assertNotIn("192.0.2.1", str(body))
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
