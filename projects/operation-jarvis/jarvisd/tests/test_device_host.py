"""Real ledger/protocol/dispatcher/coordinator with fake runners and observations."""
import concurrent.futures
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from test_control_ledger import handoff
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core.admission import WriteAdmission
from jarvisd_core.control import DeviceCommandDispatcher
from jarvisd_core.device_host import Catalogue, CatalogueEntry, DeviceControlHost, HostError
from jarvisd_core.devices import _purifier_id
from jarvisd_core.state import StateCoordinator

C = p.Cohort.PLUGS
P = p.Cohort.PURIFIER
ACCESS = v.Access("a" * 64, frozenset({C, P}), True)
CID = "synthetic-private-cid"
DEVICE = _purifier_id(CID)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger"
        g.ControlLedger.initialize(self.path)
        self.store = g.ControlLedger.open(self.path)
        self.addCleanup(lambda: self.store.close())
        handoff(self.store, C); handoff(self.store, P)
        self.now = 1000.0
        self.collect = mock.Mock(side_effect=AssertionError("unexpected collection"))
        self.state = StateCoordinator({"plugs": self.collect, "purifier": self.collect},
                                      version="fake", started_at=0, now=lambda: self.now)
        self.state.start = mock.Mock()  # No scheduler/SDK/physical hardware in these tests.
        self.admission = WriteAdmission()
        self.plugs = {name: {"ok": True, "isOn": False, "host": host} for name, host in
                      (("lamp", "192.0.2.1"), ("alias", "192.0.2.1"), ("tv", "192.0.2.2"))}
        self.purifiers = {"ok": True, "defaultDeviceID": DEVICE, "devices": {
            DEVICE: {"ok": True, "deviceID": DEVICE, "isOn": True, "mode": "auto"}}}
        self.catalogue = Catalogue("c" * 64, tuple(
            [CatalogueEntry(C, name, item["host"]) for name, item in self.plugs.items()]
            + [CatalogueEntry(P, DEVICE, DEVICE, CID)]))
        self.allow = True
        self.authorize = mock.Mock(side_effect=lambda access, command: self.allow)
        self.runner = mock.Mock(side_effect=self.fake_run)
        self.complete(C); self.complete(P)  # Warm cache BEFORE activating host must not suffice.
        self.host = self.make_host()
        self.api = v.ControlProtocol(self.store, self.host)

    def make_host(self, **kwargs):
        options = dict(store=self.store, state=self.state, admission=self.admission, runner=self.runner,
                       cli=Path("/synthetic/private-worker"), catalogue=self.catalogue, authorize=self.authorize,
                       purifier_wait_seconds=15)
        options.update(kwargs)
        return DeviceControlHost(**options)

    def complete(self, cohort, result=None, revision=None):
        if result is None:
            result = {"ok": True, "plugs": self.plugs} if cohort is C else self.purifiers
        future = concurrent.futures.Future(); future.set_result(result)
        self.state._complete(cohort.value, future,
            self.state.capture_revision(cohort.value) if revision is None else revision)

    def fake_run(self, argv, **kwargs):
        if argv[2].startswith("plug-"):
            name = argv[3]
            return {"ok": True, "plug": {"name": name, "host": self.plugs[name]["host"],
                    "is_on": argv[2] != "plug-off"}}
        return {"ok": True, "purifier": {"cid": CID, "is_on": False, "mode": "auto",
                                        "verification_pending": False}}

    def request(self, number=1, action="plug-on", params=None):
        cohort = P if action == "purifier-set" else C
        window = self.store.issue_window(cohort, ACCESS.principal)
        return {"protocol": v.PROTOCOL, "requestID": f"{number:032x}", "incarnation": window.incarnation,
                "epoch": window.epoch, "window": window.token,
                "operation": {"action": action, "params": params if params is not None else {"plug": "lamp"}}}

    def call(self, request):
        return self.api.handle(method="POST", path=v.COMMAND_PATH, content_type=v.CONTENT_TYPE,
                               body=json.dumps(request).encode(), access=ACCESS)

    def purifier_request(self, number=1):
        return self.request(number, "purifier-set", {"deviceID": DEVICE, "setting": "power", "value": "off"})

    def outcome(self, reply):
        return json.loads(reply.body)["disposition"]

    def rows(self):
        return json.loads((self.path / "record.json").read_text())["records"]

    def test_construction_prepare_and_readiness_do_not_start_collectors(self):
        request = v.parse_request(json.dumps(self.request()).encode())
        bound = self.host.prepare(request.command, ACCESS)
        ready = self.host.readiness(bound, ACCESS, request.epoch)
        self.assertTrue(ready.observation_fresh)  # Cache is warm but wrong epoch.
        self.assertIsNone(ready.observation_epoch)
        self.assertTrue(ready.target_uncertain)
        self.state.start.assert_not_called(); self.collect.assert_not_called(); self.runner.assert_not_called()

    def test_warm_pre_activation_cache_cannot_dispatch(self):
        reply = self.call(self.request())
        self.assertEqual(json.loads(reply.body)["code"], "write-not-admitted")
        self.runner.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_new_epoch_observation_runs_existing_dispatcher_once_after_reservation(self):
        self.complete(C)
        original = self.fake_run
        def run(argv, **kwargs):
            row = self.rows()[0]
            self.assertEqual(row["outcome"], "reserved")
            self.assertEqual(self.state._records["plugs"]["writeBarriers"]["lamp"], "inflight")
            self.assertEqual(argv[-2:], ["--expected-host", "192.0.2.1"])
            self.assertEqual(kwargs["timeout"], 30.0)
            return original(argv, **kwargs)
        self.runner.side_effect = run
        reply = self.call(self.request())
        self.assertEqual(self.outcome(reply), p.Outcome.ACKNOWLEDGED.value)
        self.runner.assert_called_once()
        self.assertEqual(self.rows()[0]["unresolved"], True)
        self.assertEqual(self.admission._active, set())
        self.assertTrue(self.state._records["plugs"]["data"]["plugs"]["lamp"]["isOn"])
        self.assertEqual(self.state._records["plugs"]["controlObserved"], {"tv": "192.0.2.2"})

    def test_purifier_uses_frozen_explicit_selector_and_cid_binding(self):
        self.complete(P)
        reply = self.call(self.purifier_request())
        self.assertEqual(self.outcome(reply), p.Outcome.ACKNOWLEDGED.value)
        argv = self.runner.call_args.args[0]
        self.assertEqual(argv[argv.index("--purifier") + 1], CID)
        self.assertEqual(argv[-2:], ["--expected-cid", CID])
        self.state.start.assert_not_called()  # No new purifier background polling.
        self.assertNotIn(CID.encode(), reply.body)
        self.assertNotIn(CID, (self.path / "record.json").read_text())

    def test_purifier_pending_stays_pending_and_quarantined(self):
        self.complete(P)
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "purifier": {"cid": CID, "is_on": True, "mode": "auto",
            "write_accepted": True, "verification_pending": True}}
        reply = self.call(self.purifier_request())
        self.assertEqual(self.outcome(reply), p.Outcome.PENDING.value)
        self.assertTrue(self.rows()[0]["unresolved"])
        self.assertTrue(self.state._records["purifier"]["data"]["devices"][DEVICE]["verificationPending"])

    def test_purifier_pending_without_acceptance_is_unknown(self):
        self.complete(P)
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "purifier": {"cid": CID, "is_on": True,
            "verification_pending": True}}
        self.assertEqual(self.outcome(self.call(self.purifier_request())), p.Outcome.UNKNOWN.value)

    def test_malformed_pending_flag_is_not_acknowledgement(self):
        self.complete(P)
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "purifier": {"cid": CID, "is_on": False,
            "verification_pending": 0}}
        self.assertEqual(self.outcome(self.call(self.purifier_request())), p.Outcome.UNKNOWN.value)

    def test_failed_runner_does_not_retry_and_keeps_both_barriers(self):
        self.complete(C)
        self.runner.side_effect = RuntimeError("private vendor detail")
        request = self.request()
        reply = self.call(request)
        self.assertEqual(self.outcome(reply), p.Outcome.UNKNOWN.value)
        self.assertNotIn(b"private", reply.body)
        self.assertEqual(self.state._records["plugs"]["writeBarriers"]["lamp"], "uncertain")
        self.assertTrue(self.rows()[0]["unresolved"])
        self.assertEqual(json.loads(self.call(request).body)["code"], "duplicate-intent")
        self.runner.assert_called_once()

    def test_cancellation_finishes_state_and_ledger_barriers(self):
        self.complete(C)
        self.runner.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.call(self.request())
        self.assertEqual(self.rows()[0]["outcome"], p.Outcome.UNKNOWN.value)
        self.assertTrue(self.rows()[0]["unresolved"])
        self.assertEqual(self.state._records["plugs"]["writeBarriers"]["lamp"], "uncertain")
        self.assertEqual(self.admission._active, set())

    def test_wrong_plug_result_host_is_uncertain(self):
        self.complete(C)
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "plug": {"name": "lamp", "host": "192.0.2.9", "is_on": True}}
        self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.assertEqual(self.state._records["plugs"]["writeBarriers"]["lamp"], "uncertain")

    def test_wrong_purifier_result_cid_is_uncertain(self):
        self.complete(P)
        self.runner.side_effect = None
        self.runner.return_value = {"ok": True, "purifier": {"cid": "other-cid", "is_on": False}}
        self.assertEqual(self.outcome(self.call(self.purifier_request())), p.Outcome.UNKNOWN.value)

    def test_cached_alias_cannot_redirect_frozen_catalogue_target(self):
        self.plugs["lamp"] = {"ok": True, "isOn": False, "host": "192.0.2.9"}
        self.complete(C)
        self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_identity_change_at_atomic_begin_is_rejected_after_reservation(self):
        self.complete(C)
        original = self.state.begin_device_write
        def begin(*args, **kwargs):
            self.plugs["lamp"] = {"ok": True, "isOn": False, "host": "192.0.2.9"}
            self.complete(C)
            return original(*args, **kwargs)
        with mock.patch.object(self.state, "begin_device_write", side_effect=begin):
            self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_staleness_at_atomic_begin_is_rejected(self):
        self.complete(C)
        original = self.state.begin_device_write
        def begin(*args, **kwargs):
            self.now += 31
            return original(*args, **kwargs)
        with mock.patch.object(self.state, "begin_device_write", side_effect=begin):
            self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()

    def test_revocation_after_reservation_blocks_actual_runner(self):
        self.complete(C)
        original = self.store._commit
        def commit(data):
            original(data)
            if data["records"]:
                self.allow = False
        with mock.patch.object(self.store, "_commit", side_effect=commit):
            self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_authorizer_exact_true_and_scope_checks(self):
        self.complete(C)
        for value in (False, None, 1, "true"):
            self.authorize.side_effect = None; self.authorize.return_value = value
            self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()
        self.assertEqual(self.rows(), [])
        command = v.parse_request(json.dumps(self.request()).encode()).command
        with self.assertRaises(HostError):
            self.host.prepare(command, replace(ACCESS, cohorts=frozenset()))

    def test_unknown_catalogue_target_is_not_discovered_or_defaulted(self):
        self.complete(C); self.complete(P)
        self.assertEqual(self.outcome(self.call(self.request(params={"plug": "unknown"}))), p.Outcome.UNKNOWN.value)
        request = self.purifier_request()
        request["operation"]["params"]["deviceID"] = _purifier_id("unknown-cid")
        self.assertEqual(self.outcome(self.call(request)), p.Outcome.UNKNOWN.value)
        self.collect.assert_not_called(); self.runner.assert_not_called()

    def test_alias_and_resource_admission_are_shared_with_legacy_dispatcher(self):
        self.complete(C)
        with self.admission.hold(("plugs", "192.0.2.1")):
            self.assertEqual(self.outcome(self.call(self.request(params={"plug": "alias"}))), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()
        self.assertTrue(self.rows()[0]["unresolved"])

    def test_acknowledgement_or_later_cache_read_cannot_clear_ledger_uncertainty(self):
        self.complete(C)
        self.call(self.request())
        self.complete(C)  # New collector evidence refreshes cache, NOT persistent intent outcome.
        reply = self.call(self.request(2, params={"plug": "alias"}))
        self.assertEqual(json.loads(reply.body)["code"], "resource-unresolved")
        self.runner.assert_called_once()

    def test_old_pre_activation_collection_is_discarded(self):
        self.complete(C)
        old_revision = self.state.capture_revision("plugs")
        handoff(self.store, C); handoff(self.store, P)
        self.host = self.make_host(); self.api = v.ControlProtocol(self.store, self.host)
        self.complete(C, revision=old_revision)
        self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()
        self.complete(C)
        self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.ACKNOWLEDGED.value)

    def test_failed_partial_and_malformed_reads_cannot_manufacture_epoch_evidence(self):
        bad = [{"ok": False, "error": "failed"}, {"ok": True, "plugs": {
            "lamp": {"ok": False, "error": "retained fresh cache"}}},
            {"ok": True, "plugs": {"lamp": {"ok": True, "host": "192.0.2.1", "isOn": "on"}}}]
        for result in bad:
            self.complete(C, result)
            self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_failed_refresh_clears_previous_epoch_evidence_even_with_fresh_grace(self):
        self.complete(C)
        self.complete(C, {"ok": False, "error": "temporary read failure"})
        self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_purifier_failed_and_invalid_reads_do_not_certify_epoch(self):
        for result in ({"ok": False, "error": "read rejected"},
            {"ok": False, "defaultDeviceID": DEVICE, "devices": {DEVICE: {"ok": False}}},
            {"ok": True, "defaultDeviceID": DEVICE, "devices": {DEVICE: {"ok": True, "isOn": "on"}}}):
            self.complete(P, result)
            self.assertEqual(json.loads(self.call(self.purifier_request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_one_cohort_observation_does_not_authorize_the_other(self):
        self.complete(C)
        self.assertEqual(json.loads(self.call(self.purifier_request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_partial_collection_certifies_only_successful_devices(self):
        self.complete(C, {"ok": False, "plugs": {"lamp": self.plugs["lamp"], "tv": {"ok": False}}})
        self.assertEqual(json.loads(self.call(self.request(2, params={"plug": "tv"})).body)["code"], "write-not-admitted")
        self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.ACKNOWLEDGED.value)

    def test_direct_result_cannot_replace_activated_epoch_collection(self):
        self.state.apply_plug_result({"name": "lamp", "host": "192.0.2.1", "is_on": False})
        self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.state.apply_purifier_result({"cid": CID, "is_on": True, "mode": "auto"})
        self.assertEqual(json.loads(self.call(self.purifier_request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_all_writes_invalidate_epoch_proof_including_legacy_entry(self):
        self.complete(C)
        legacy = DeviceCommandDispatcher(state=self.state, admission=self.admission,
            cli=Path("/fake"), run=self.runner, selected_purifier=lambda _: CID, purifier_wait_seconds=3)
        legacy.execute("plug-on", {"plug": "lamp"})
        self.runner.reset_mock()
        self.assertEqual(json.loads(self.call(self.request()).body)["code"], "write-not-admitted")
        self.runner.assert_not_called()

    def test_during_write_collections_do_not_supply_post_write_epoch_proof(self):
        self.complete(C)
        def run(argv, **kwargs):
            self.complete(C)
            return self.fake_run(argv, **kwargs)
        self.runner.side_effect = run
        self.call(self.request())
        epoch = self.host._epochs[C]
        self.assertFalse(self.state.inspect_device("plugs", "lamp", control_epoch=epoch)["epochObserved"])

    def test_epoch_rearming_is_idempotent_but_catalogue_change_requires_handoff(self):
        self.complete(C)
        revision = self.state.capture_revision("plugs")
        self.make_host()
        self.assertEqual(self.state.capture_revision("plugs"), revision)
        with self.assertRaises(ValueError):
            self.make_host(catalogue=replace(self.catalogue, generation="d" * 64))
        handoff(self.store, C); handoff(self.store, P)
        host = self.make_host(catalogue=replace(self.catalogue, generation="d" * 64))
        self.assertNotEqual(host._catalogue, self.host._catalogue)
        self.assertFalse(self.state.inspect_device("plugs", "lamp", control_epoch=host._epochs[C])["epochObserved"])

    def test_old_host_cannot_use_new_epoch_observations(self):
        self.complete(C)
        command = v.parse_request(json.dumps(self.request()).encode()).command
        bound = self.host.prepare(command, ACCESS)
        old_host = self.host
        handoff(self.store, C); handoff(self.store, P)
        new_host = self.make_host()
        self.complete(C)
        with self.assertRaises(ValueError):
            old_host.execute(bound)
        with self.assertRaises(HostError):
            new_host.execute(bound)
        self.runner.assert_not_called()

    def test_state_refuses_epoch_rollback_and_malformed_epochs(self):
        epoch = self.host._epochs[C]
        for candidate in ((epoch[0], epoch[1] - 1), ("f" * 32, epoch[1]),
                          (epoch[0], True), (epoch[0], 3.0), [*epoch], ("x", 7)):
            with self.assertRaises(ValueError):
                self.state.arm_control_epoch("plugs", candidate, catalogue=self.host._catalogue)

    def test_host_requires_api_ownership_and_has_no_activation_path(self):
        self.store.transition(C, p.Mode.DRAINING)
        with self.assertRaises(HostError):
            self.make_host()
        self.assertEqual(self.store.snapshot(C).mode, p.Mode.DRAINING)

    def test_context_cannot_be_swapped_across_commands_hosts_or_principals(self):
        command = v.parse_request(json.dumps(self.request()).encode()).command
        bound = self.host.prepare(command, ACCESS)
        for changed in (replace(bound, context=None), replace(bound, catalogue="f" * 64),
                        replace(bound, target=("plugs", "192.0.2.2")),
                        replace(bound, command=replace(command, action="plug-off"))):
            with self.assertRaises(HostError):
                self.host.execute(changed)
        with self.assertRaises(HostError):
            self.make_host().execute(bound)
        ready = self.host.readiness(bound, replace(ACCESS, principal="b" * 64), 3)
        self.assertFalse(ready.authorized)
        self.runner.assert_not_called()

    def test_catalogue_is_closed_immutable_and_selector_identity_checked(self):
        for construct in (lambda: Catalogue("x", self.catalogue.entries),
            lambda: Catalogue("c" * 64, list(self.catalogue.entries)),
            lambda: Catalogue("c" * 64, self.catalogue.entries * 2),
            lambda: CatalogueEntry(C, "Lamp", "192.0.2.1"),
            lambda: CatalogueEntry(C, "lamp", "HOST"),
            lambda: CatalogueEntry(C, "lamp", "192.0.2.1", CID),
            lambda: CatalogueEntry(P, DEVICE, DEVICE, "wrong-cid")):
            with self.assertRaises(HostError):
                construct()
        self.assertEqual(self.catalogue.fingerprint,
                         replace(self.catalogue, entries=tuple(reversed(self.catalogue.entries))).fingerprint)
        self.assertNotIn(CID, repr(self.catalogue))

    def test_state_snapshot_contract_does_not_expose_control_bookkeeping(self):
        self.complete(C); self.complete(P)
        text = json.dumps(self.state.snapshot())
        for field in ("controlEpoch", "controlObserved", "controlCatalogue", self.host._epochs[C][0]):
            self.assertNotIn(field, text)

    def test_active_runner_blocks_maintenance_and_duplicate_never_runs_again(self):
        self.complete(C)
        entered, release = threading.Event(), threading.Event()
        def run(argv, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return self.fake_run(argv, **kwargs)
        self.runner.side_effect = run
        request = self.request()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.call, request)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(json.loads(self.call(request).body)["code"], "duplicate-intent")
                state = self.store.transition(C, p.Mode.DRAINING)
                with self.assertRaises(g.LedgerError) as error:
                    self.store.transition(C, p.Mode.MAINTENANCE, p.HandoffEvidence(C, state.epoch, 0))
                self.assertEqual(error.exception.code, "writes-active")
            finally:
                release.set()
            self.assertEqual(self.outcome(future.result(5)), p.Outcome.ACKNOWLEDGED.value)
        self.runner.assert_called_once()

    def test_uncertain_store_refuses_existing_dispatcher_without_fallback(self):
        self.complete(C)
        request = self.request()
        (self.path / "record.json").write_bytes(b"corrupt")
        self.assertEqual(self.outcome(self.call(request)), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()
        self.assertEqual(self.admission._active, set())

    def test_epoch_change_between_dispatch_inspection_and_atomic_begin_blocks(self):
        self.complete(C)
        original = self.state.begin_device_write
        def begin(*args, **kwargs):
            old = self.host._epochs[C]
            self.state.arm_control_epoch("plugs", (old[0], old[1] + 1), catalogue=self.host._catalogue)
            return original(*args, **kwargs)
        with mock.patch.object(self.state, "begin_device_write", side_effect=begin):
            self.assertEqual(self.outcome(self.call(self.request())), p.Outcome.UNKNOWN.value)
        self.runner.assert_not_called()

    def test_import_purity_and_no_live_host_wiring(self):
        import jarvisd_core.device_host as module
        with mock.patch("builtins.open", side_effect=AssertionError("IO")), \
             mock.patch("pathlib.Path.open", side_effect=AssertionError("IO")), \
             mock.patch("os.open", side_effect=AssertionError("IO")), \
             mock.patch("socket.socket", side_effect=AssertionError("network")):
            spec = importlib.util.spec_from_file_location("jarvisd_core.host_import_probe", module.__file__)
            probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        root = Path(module.__file__).resolve().parents[1]
        for path in (root / "jarvisd.py", root / "device-worker.py", root / "jarvisd_core/__init__.py",
                     root.parent / "jarvis.py", root.parents[2] / ".pi/extensions/45-jarvis.ts"):
            self.assertNotIn("device_host", path.read_text())


if __name__ == "__main__":
    unittest.main()
