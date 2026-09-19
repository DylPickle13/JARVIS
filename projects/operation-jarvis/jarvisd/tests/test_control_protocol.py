"""Dormant boundary tests: temp stores, synthetic hosts/loopback; no real devices."""
from dataclasses import replace
import concurrent.futures
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from test_control_ledger import Clock, handoff
from jarvisd_core import client_policy as p
from jarvisd_core import control_ledger as g
from jarvisd_core import control_protocol as v
from jarvisd_core import commands, device_worker, device_translation

C = p.Cohort.PLUGS
ACCESS = v.Access("a" * 64, frozenset(p.Cohort), True)
DEVICE = "d" * 24


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


class Host:
    def __init__(self):
        self.effects = []
        self.preparations = []
        self.catalogue = "c" * 64
        self.target = "192.0.2.1"
        self.fresh = True
        self.authorized = True
        self.outcome = p.Outcome.ACKNOWLEDGED

    def prepare(self, command, access):
        bound = v.BoundWrite(command, (command.cohort.value,
            self.target if command.cohort is C else DEVICE), self.catalogue)
        self.preparations.append(bound)
        return bound

    def readiness(self, bound, access, epoch):
        return p.Readiness(epoch, epoch, endpoint_available=True, protocol_verified=True,
            transport_guarded=True, authorized=self.authorized, target_known=True,
            observation_fresh=self.fresh and bound.catalogue == self.catalogue, target_uncertain=False)

    def execute(self, bound):
        # Synthetic equivalent of the required second identity/catalogue check in
        # the existing dispatcher. The protocol does not replace that admission.
        if bound.catalogue != self.catalogue:
            raise RuntimeError("catalogue changed")
        self.effects.append(bound)
        return g.DispatchResult(self.outcome, {"private-selector": "must-not-leak"})


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "store"
        self.clock = Clock()
        g.ControlLedger.initialize(self.path)
        self.store = self.open()
        self.addCleanup(lambda: self.store.close())
        self.host = Host()
        self.api = v.ControlProtocol(self.store, self.host)
        handoff(self.store)
        handoff(self.store, p.Cohort.PURIFIER)

    def open(self):
        return g.ControlLedger.open(self.path, monotonic_ns=lambda: self.clock.mono,
                                    wall_ns=lambda: self.clock.wall)

    def call(self, data, *, path=v.COMMAND_PATH, access=ACCESS, **kwargs):
        return self.api.handle(method=kwargs.get("method", "POST"), path=path,
            content_type=kwargs.get("content_type", v.CONTENT_TYPE),
            body=data if type(data) is bytes else encode(data), access=access)

    def window(self, cohort=C, access=ACCESS):
        reply = self.call({"protocol": v.PROTOCOL, "cohort": cohort.value}, path=v.WINDOW_PATH, access=access)
        self.assertEqual(reply.status, 200, reply.body)
        return json.loads(reply.body)

    def request(self, number=1, action="plug-on", params=None, access=ACCESS):
        cohort = p.Cohort(commands.COMMANDS[action].integration)
        window = self.window(cohort, access)
        return {"protocol": v.PROTOCOL, "requestID": f"{number:032x}",
            "incarnation": window["incarnation"], "epoch": window["epoch"], "window": window["window"],
            "operation": {"action": action, "params": params if params is not None else {"plug": "lamp"}}}

    def operation(self, request, **changes):
        return {**request, "operation": {**request["operation"], **changes}}

    def assert_error(self, reply, code, status=None):
        if status is not None:
            self.assertEqual(reply.status, status, reply.body)
        data = json.loads(reply.body)
        self.assertEqual(data["code"], code)
        self.assertEqual(data["kind"], "error")
        self.assertEqual(data["disposition"], p.Outcome.UNKNOWN.value)
        self.assertEqual(dict(reply.headers), {"Content-Type": v.CONTENT_TYPE, "Cache-Control": "no-store"})
        return data

    def classify(self, request, reply, **kwargs):
        options = dict(status=reply.status, content_type=v.CONTENT_TYPE, body=reply.body,
                       intended_peer=True, single_submission=True)
        options.update(kwargs)
        return v.classify_receipt(v.parse_request(encode(request)), **options)

    def test_explicit_paths_methods_media_and_no_v1_aliases(self):
        request = self.request()
        for path in ("/api/v1/command", "/api/v2/control/command/", v.COMMAND_PATH + "?refresh=1",
                     "/api/v2/control/%63ommand", "/api/v2/control/maintenance"):
            with self.subTest(path=path):
                self.assert_error(self.call(request, path=path), "unsupported-route", 404)
        for method in ("GET", "PUT", "PATCH", "post"):
            self.assert_error(self.call(request, method=method), "unsupported-method", 405)
        for media in ("application/json", "", v.CONTENT_TYPE + ";charset=utf-8"):
            self.assert_error(self.call(request, content_type=media), "unsupported-media-type", 415)
        self.assertEqual(self.host.effects, [])

    def test_authentication_transport_and_scope_before_prepare(self):
        request = self.request()
        for access, code in ((None, "authentication-required"),
                ({"principal": ACCESS.principal}, "authentication-required"),
                (replace(ACCESS, transport_verified=False), "transport-not-certified"),
                (replace(ACCESS, cohorts=frozenset()), "scope-denied")):
            self.assert_error(self.call(request, access=access), code)
        self.assertEqual(self.host.preparations, [])

    def test_access_is_strict_host_only_input(self):
        for kwargs in ({"principal": "raw-token"}, {"cohorts": {C}},
                       {"cohorts": frozenset({"plugs"})}, {"transport_verified": 1}):
            with self.assertRaises(v.ProtocolError):
                replace(ACCESS, **kwargs)

    def test_body_cannot_supply_authority_or_identity_binding(self):
        request = self.request()
        for field in ("client", "principal", "resource", "command", "ready", "authorized", "epochOverride",
                      "legacy_writers_fenced", "catalogue", "retry", "expectedHost", "expectedCID", "action", "params"):
            self.assert_error(self.call({**request, field: True}), "invalid-body", 400)
        self.assertEqual(self.host.effects, [])

    def test_strict_json_duplicate_keys_constants_encoding_depth_size(self):
        request = encode(self.request())
        bad = [b"", b"[]", b"null", b"\xff", b"\xef\xbb\xbf" + request,
            request.replace(b'"epoch":3', b'"epoch":NaN'),
            request[:-1] + b',"protocol":"jarvis-control/2"}',
            request.replace(b'"lamp"', b'"lamp","plug":"lamp"'),
            b'{"protocol":"jarvis-control/2","x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}']
        for body in bad:
            with self.subTest(body=body[:80]):
                self.assert_error(self.call(body), "invalid-body", 400)
        self.assert_error(self.call(b"x" * (v.MAX_BODY + 1)), "body-too-large", 413)
        self.assertEqual(self.host.effects, [])

    def test_closed_envelope_exact_types_and_epoch_limits(self):
        request = self.request()
        changes = {"protocol": [None, "jarvis-control/1", True], "epoch": [True, 0, -1, 3.0, p.MAX_EPOCH],
            "requestID": ["A" * 32, "x", None, 1], "incarnation": ["", [], "a" * 33],
            "window": ["", True], "action": ["status", "purifier-status-all", [], "plug-On"],
            "params": [None, [], True]}
        for field, values in changes.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    changed = self.operation(request, **{field: value}) if field in ("action", "params") else {**request, field: value}
                    self.assert_error(self.call(changed), "invalid-body", 400)
        for field in request:
            copy = dict(request); del copy[field]
            self.assert_error(self.call(copy), "invalid-body", 400)
        self.assertEqual(self.host.effects, [])

    def test_operation_envelope_is_closed_not_legacy_compatible(self):
        request = self.request()
        for operation in (None, [], {}, {"action": "plug-on"}, {"params": {"plug": "lamp"}},
                          {**request["operation"], "authorized": True}):
            self.assert_error(self.call({**request, "operation": operation}), "invalid-body", 400)
        self.assertEqual(self.host.effects, [])

    def test_old_daemon_routes_and_misrouted_body_cannot_execute_v2_operation(self):
        request = self.request()
        handler = object.__new__(daemon.Handler)
        handler.server = mock.Mock(control_endpoint=None)
        handler._send = mock.Mock()
        handler._read_json = mock.Mock(return_value=request)
        handler._auth_or_respond = mock.Mock(return_value=True)
        # Exercise the actual unchanged v1 handler with a pure command-validation
        # seam. It must never obtain an executable action, even if misrouted to v1.
        validated = []
        def validate_only(action, params):
            argv = commands.build_command(action, params, cli=Path("unused"), selected_purifier=lambda x: x)
            validated.append(argv)
            raise AssertionError("old handler accepted a v2 operation")
        with mock.patch.object(daemon, "dispatch_command", side_effect=validate_only) as dispatch:
            for path in (v.COMMAND_PATH, v.WINDOW_PATH):
                handler.path = path
                handler.do_POST()
                self.assertEqual(handler._send.call_args.args[0], 404)
                dispatch.assert_not_called()
            handler.path = "/api/v1/command"
            handler.do_POST()
            self.assertEqual(handler._send.call_args.args[0], 400)
            self.assertIsNone(dispatch.call_args.args[0])
        self.assertEqual(validated, [])

    def test_plug_names_and_no_ignored_options(self):
        request = self.request()
        for params in ({"plug": " Lamp "}, {"plug": "Lamp"}, {"plug": "../lamp"},
                       {"plug": "a" * 129}, {"plug": "lamp", "value": "off"}, {"plug": True}):
            self.assert_error(self.call(self.operation(request, params=params)), "invalid-body", 400)
        self.assertEqual(self.host.effects, [])

    def test_canonical_purifier_forms_match_existing_private_translation(self):
        cases = [({"setting": "power", "value": "toggle"}, ["toggle", DEVICE]),
            ({"setting": "display", "value": "off"}, ["display", "off", DEVICE]),
            ({"setting": "child-lock", "value": "on"}, ["child-lock", "on", DEVICE]),
            ({"setting": "light-detection", "value": "off"}, ["light-detection", "off", DEVICE]),
            ({"setting": "mode", "value": "pet"}, ["mode", "pet", DEVICE]),
            ({"setting": "speed", "level": 4}, ["speed", "4", DEVICE]),
            ({"setting": "auto-preference", "value": "efficient", "roomSize": 100},
             ["auto-preference", "efficient", DEVICE, "--room-size", "100"]),
            ({"setting": "timer", "minutes": 1440}, ["timer", "1440", DEVICE]),
            ({"setting": "timer", "value": "clear"}, ["clear-timer", DEVICE])]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                request = self.request(action="purifier-set", params={"deviceID": DEVICE, **fields})
                command = v.parse_request(encode(request)).command
                argv = commands.build_command(command.action, dict(command.params), cli=Path("unused"),
                                               selected_purifier=lambda value: value)
                args = device_worker.build_parser().parse_args(["--operation-root", self.temp.name,
                    "--project-root", self.temp.name, *argv[1:], "--expected-cid", DEVICE])
                self.assertEqual(device_translation._purifier_set_cli_args(args), expected)

    def test_purifier_defaults_aliases_ambiguities_and_irrelevant_fields_rejected(self):
        request = self.request(action="purifier-set", params={})
        cases = [{"setting": "power", "state": "on"}, {"setting": "power", "value": "yes"},
            {"setting": "display", "value": "toggle"}, {"setting": "mode", "value": "auto", "level": 2},
            {"setting": "speed", "value": "2"}, {"setting": "speed", "level": True},
            {"setting": "speed", "level": 5}, {"setting": "timer", "minutes": 0},
            {"setting": "timer", "minutes": 1441}, {"setting": "timer", "value": "cancel"},
            {"setting": "timer", "value": "clear", "minutes": 4},
            {"setting": "auto-preference", "value": "quiet", "roomSize": None},
            {"setting": "auto-preference", "value": "quiet", "roomSize": True},
            {"setting": "mode", "value": "AUTO"}, {"setting": ["mode"]},
            {"setting": "power", "value": "on", "retryCooldown": True}]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assert_error(self.call(self.operation(request, params={"deviceID": DEVICE, **fields})), "invalid-body")
        for device in (None, "Air Purifier", "default", "a" * 32, "D" * 24):
            self.assert_error(self.call(self.operation(request, params={"deviceID": device, "setting": "power", "value": "on"})), "invalid-body")
        self.assert_error(self.call(self.operation(request, params={"setting": "power", "value": "on"})), "invalid-body")

    def test_success_binds_exact_immutable_command_and_hides_vendor_values(self):
        request = self.request()
        reply = self.call(request)
        self.assertEqual(reply.status, 200)
        self.assertIs(self.host.preparations[0], self.host.effects[0])
        self.assertEqual(self.host.effects[0].command.params, (("plug", "lamp"),))
        self.assertNotIn(b"private-selector", reply.body)
        self.assertNotIn(b"192.0.2.1", reply.body)
        self.assertEqual(self.classify(request, reply), p.Outcome.ACKNOWLEDGED)
        row = json.loads((self.path / "record.json").read_text())["records"][0]
        bound = self.host.effects[0]
        self.assertEqual((row["client"], row["resource"], row["command"]),
                         (ACCESS.principal, bound.resource, bound.fingerprint))
        self.assertNotIn("lamp", (self.path / "record.json").read_text())

    def test_duplicate_preserves_prior_disposition_and_never_replays(self):
        request = self.request()
        self.call(request)
        reply = self.call(request)
        data = self.assert_error(reply, "duplicate-intent", 409)
        self.assertEqual(data["priorDisposition"], p.Outcome.ACKNOWLEDGED.value)
        self.assertEqual(self.classify(request, reply), p.Outcome.UNKNOWN)
        self.assertEqual(len(self.host.effects), 1)

    def test_duplicate_changed_action_payload_target_and_cohort_cannot_escape(self):
        request = self.request()
        self.call(request)
        self.host.target = "192.0.2.2"
        for changed in (self.operation(request, action="plug-off"),
                        self.operation(request, params={"plug": "tv"}),
                        self.request(action="purifier-set", params={"deviceID": DEVICE, "setting": "power", "value": "on"})):
            self.assert_error(self.call(changed), "duplicate-intent")
        self.assertEqual(len(self.host.effects), 1)

    def test_aliases_catalogue_and_epoch_changes_do_not_escape_resource_barrier(self):
        self.call(self.request())
        old = self.host.effects[0]
        self.host.catalogue = "e" * 64
        handoff(self.store)
        self.assert_error(self.call(self.request(2, params={"plug": "alias"})), "resource-unresolved")
        new = self.host.preparations[-1]
        self.assertEqual(old.resource, new.resource)
        self.assertNotEqual(old.fingerprint, new.fingerprint)

    def test_bound_target_validation_and_fingerprint_domains(self):
        command = v.parse_request(encode(self.request())).command
        bound = v.BoundWrite(command, (C.value, "192.0.2.1"), "c" * 64)
        for changes in ({"target": [C.value, "192.0.2.1"]}, {"target": ("purifier", DEVICE)},
                        {"target": (C.value, "")}, {"target": (C.value, "host with space")},
                        {"target": (C.value, "x" * 257)}, {"catalogue": "raw-catalogue"}):
            with self.assertRaises(v.ProtocolError):
                replace(bound, **changes)
        changed = replace(bound, catalogue="e" * 64)
        self.assertEqual(bound.resource, changed.resource)
        self.assertNotEqual(bound.fingerprint, changed.fingerprint)
        self.assertNotEqual(bound.resource, bound.fingerprint)
        self.assertNotEqual(bound.resource, replace(bound, target=(C.value, "192.0.2.2")).resource)

    def test_window_scope_cannot_be_transferred_to_other_principal(self):
        request = self.request()
        other = replace(ACCESS, principal="b" * 64)
        self.assert_error(self.call(request, access=other), "window-scope-mismatch")
        self.assertEqual(self.host.effects, [])

    def test_window_scope_cannot_be_transferred_between_cohorts(self):
        request = self.request()
        request = self.operation(request, action="purifier-set", params={"deviceID": DEVICE, "setting": "power", "value": "on"})
        self.assert_error(self.call(request), "window-scope-mismatch")
        self.assertEqual(self.host.effects, [])

    def test_expired_window_and_restarted_store_refuse_stale_request(self):
        request = self.request()
        self.clock.advance(g.TTL_NS)
        self.assert_error(self.call(request), "window-expired-or-unknown")
        self.store.close()
        self.store = self.open()
        self.api = v.ControlProtocol(self.store, self.host)
        self.assert_error(self.call({"protocol": v.PROTOCOL, "cohort": C.value}, path=v.WINDOW_PATH), "window-unavailable")
        handoff(self.store)
        self.assert_error(self.call(request), "window-expired-or-unknown")
        self.assertEqual(self.host.effects, [])

    def test_restart_duplicate_stays_consumed(self):
        request = self.request()
        self.call(request)
        self.store.close()
        self.store = self.open()
        self.api = v.ControlProtocol(self.store, self.host)
        handoff(self.store)
        self.assert_error(self.call(self.request()), "duplicate-intent")
        self.assertEqual(len(self.host.effects), 1)

    def test_revoked_authority_stale_observation_and_catalogue_block(self):
        request = self.request()
        self.host.authorized = False
        self.assert_error(self.call(request), "write-not-admitted")
        self.host.authorized = True
        self.host.fresh = False
        self.assert_error(self.call(request), "write-not-admitted")
        self.host.fresh = True
        original = self.host.prepare
        def prepare(*args):
            bound = original(*args)
            self.host.catalogue = "e" * 64
            return bound
        with mock.patch.object(self.host, "prepare", side_effect=prepare):
            self.assert_error(self.call(request), "write-not-admitted")
        self.assertEqual(self.host.effects, [])

    def test_host_cannot_swap_command_during_binding(self):
        request = self.request()
        def prepare(command, access):
            return v.BoundWrite(replace(command, action="plug-off"), (C.value, "192.0.2.1"), "c" * 64)
        with mock.patch.object(self.host, "prepare", side_effect=prepare):
            self.assert_error(self.call(request), "control-unavailable", 503)
        self.assertEqual(self.host.effects, [])

    def test_callback_failure_after_effect_is_unknown_and_consumed(self):
        request = self.request()
        original = self.host.execute
        def execute(bound):
            original(bound)
            raise RuntimeError("private-cid credential local-path")
        with mock.patch.object(self.host, "execute", side_effect=execute):
            reply = self.call(request)
        self.assert_error(reply, "control-unavailable", 503)
        self.assertNotIn(b"private", reply.body)
        data = self.assert_error(self.call(request), "duplicate-intent")
        self.assertEqual(data["priorDisposition"], p.Outcome.UNKNOWN.value)
        self.assertEqual(len(self.host.effects), 1)

    def test_host_protocol_errors_after_effect_are_not_mislabeled_bad_request(self):
        request = self.request()
        original = self.host.execute
        def execute(bound):
            original(bound)
            raise v.ProtocolError("private-binding-detail")
        with mock.patch.object(self.host, "execute", side_effect=execute):
            self.assert_error(self.call(request), "control-unavailable", 503)
        self.assert_error(self.call(request), "duplicate-intent")
        self.assertEqual(len(self.host.effects), 1)

    def test_callback_cancellation_propagates_but_never_refunds(self):
        request = self.request()
        with mock.patch.object(self.host, "execute", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.call(request)
        data = self.assert_error(self.call(request), "duplicate-intent")
        self.assertEqual(data["priorDisposition"], p.Outcome.UNKNOWN.value)

    def test_invalid_dispatch_result_is_unknown_and_reserved(self):
        request = self.request()
        with mock.patch.object(self.host, "execute", return_value={"ok": True}):
            self.assert_error(self.call(request), "control-unavailable", 503)
        data = self.assert_error(self.call(request), "duplicate-intent")
        self.assertEqual(data["priorDisposition"], p.Outcome.UNKNOWN.value)

    def test_store_fault_does_not_fallback(self):
        request = self.request()
        (self.path / "record.json").write_bytes(b"corrupt")
        self.assert_error(self.call(request), "control-unavailable", 503)
        self.assertEqual(self.host.effects, [])

    def test_full_store_refuses_submission_without_pruning_or_fallback(self):
        self.call(self.request())
        resource = self.host.effects[0].resource
        self.store.reconcile(self.store.begin_observation(C, resource), reconciled=True)
        request = self.request(2)
        with mock.patch.object(g, "MAX_RECORDS", 1):
            self.assert_error(self.call(request), "store-capacity", 409)
        self.assertEqual(len(self.host.effects), 1)

    def test_completion_failure_after_effect_preserves_duplicate_on_reopen(self):
        request = self.request()
        original = self.store._commit
        def commit(data):
            if data["records"] and data["records"][-1]["outcome"] != "reserved":
                raise g.LedgerError("store-unavailable")
            return original(data)
        with mock.patch.object(self.store, "_commit", side_effect=commit):
            self.assert_error(self.call(request), "control-unavailable", 503)
        self.store.close()
        self.store = self.open()
        self.api = v.ControlProtocol(self.store, self.host)
        handoff(self.store)
        data = self.assert_error(self.call(self.request()), "duplicate-intent")
        self.assertEqual(data["priorDisposition"], p.Outcome.UNKNOWN.value)
        self.assertEqual(len(self.host.effects), 1)

    def test_admission_contention_is_unknown_without_waiting_or_dispatch(self):
        request = self.request()
        self.store._mutex.acquire()
        try:
            self.assert_error(self.call(request), "admission-busy", 409)
        finally:
            self.store._mutex.release()
        self.assertEqual(self.host.effects, [])

    def test_failed_reservation_sync_does_not_dispatch(self):
        request = self.request()
        with mock.patch.object(g.os, "fsync", side_effect=OSError("private-path")):
            self.assert_error(self.call(request), "control-unavailable", 503)
        self.assertEqual(self.host.effects, [])

    def test_ack_pending_and_unknown_stay_quarantined_until_host_observation(self):
        for index, outcome in enumerate((p.Outcome.ACKNOWLEDGED, p.Outcome.PENDING, p.Outcome.UNKNOWN), 1):
            self.host.outcome = outcome
            request = self.request(index)
            reply = self.call(request)
            self.assertEqual(self.classify(request, reply), outcome)
            resource = self.host.effects[-1].resource
            self.assertIn(resource, self.store.pending_resources(C))
            self.assert_error(self.call(self.request(100 + index)), "resource-unresolved")
            ticket = self.store.begin_observation(C, resource)
            self.store.reconcile(ticket, reconciled=True)  # Synthetic NEW host read, never response receipt.

    def test_receipt_classification_requires_peer_and_single_submission_evidence(self):
        request = self.request()
        reply = self.call(request)
        for options in ({"intended_peer": False}, {"single_submission": False},
                        {"single_submission": 1}, {"status": 201}, {"content_type": "application/json"}):
            self.assertEqual(self.classify(request, reply, **options), p.Outcome.UNKNOWN)

    def test_portable_request_digest_vectors(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/control-protocol-v2.json").read_text())
        self.assertEqual(fixture["protocol"], v.PROTOCOL)
        for vector in fixture["vectors"]:
            request = v.parse_request(encode(vector["request"]))
            self.assertEqual(request.fingerprint, vector["requestDigest"])

    def test_receipt_digest_covers_payload_and_window_not_private_binding(self):
        request = self.request()
        reply = self.call(request)
        changed = self.operation(request, params={"plug": "other-alias"})
        self.assertEqual(self.classify(changed, reply), p.Outcome.UNKNOWN)
        changed = {**request, "window": "f" * 32}
        self.assertEqual(self.classify(changed, reply), p.Outcome.UNKNOWN)
        reversed_json = dict(reversed(list(request.items())))
        self.assertEqual(self.classify(reversed_json, reply), p.Outcome.ACKNOWLEDGED)
        public_digest = json.loads(reply.body)["requestDigest"]
        self.assertEqual(public_digest, v.parse_request(encode(request)).fingerprint)
        self.assertNotEqual(public_digest, self.host.effects[0].fingerprint)

    def test_receipts_reject_wrong_identity_envelope_and_v1_responses(self):
        request = self.request()
        reply = self.call(request)
        data = json.loads(reply.body)
        for field, value in (("protocol", "jarvis-control/1"), ("kind", "error"), ("requestID", "b" * 32),
            ("incarnation", "c" * 32), ("epoch", True), ("epoch", request["epoch"] + 1),
            ("action", "plug-off"), ("requestDigest", "a" * 64), ("disposition", "rejected-before-adapter"), ("disposition", []), ("extra", True)):
            self.assertEqual(self.classify(request, reply, body=encode({**data, field: value})), p.Outcome.UNKNOWN)
        for body in (b'{"ok":true,"action":"plug-on"}', reply.body[:-1], b"[]"):
            self.assertEqual(self.classify(request, reply, body=body), p.Outcome.UNKNOWN)

    def test_concurrent_duplicate_and_maintenance_never_repeat_callback(self):
        request = self.request()
        entered, release = threading.Event(), threading.Event()
        original = self.host.execute
        def execute(bound):
            result = original(bound)
            entered.set()
            self.assertTrue(release.wait(5))
            return result
        with mock.patch.object(self.host, "execute", side_effect=execute), concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.call, request)
            try:
                self.assertTrue(entered.wait(5))
                duplicate = self.assert_error(self.call(request), "duplicate-intent")
                self.assertEqual(duplicate["priorDisposition"], p.Outcome.UNKNOWN.value)
                state = self.store.transition(C, p.Mode.DRAINING)
                with self.assertRaises(g.LedgerError) as exc:
                    self.store.transition(C, p.Mode.MAINTENANCE, p.HandoffEvidence(C, state.epoch, 0))
                self.assertEqual(exc.exception.code, "writes-active")
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5).status, 200)
        self.assertEqual(len(self.host.effects), 1)

    def test_ownership_change_during_prepare_prevents_callback(self):
        request = self.request()
        original = self.host.prepare
        def prepare(*args):
            bound = original(*args)
            self.store.transition(C, p.Mode.DRAINING)
            return bound
        with mock.patch.object(self.host, "prepare", side_effect=prepare):
            self.assert_error(self.call(request), "write-not-admitted")
        self.assertEqual(self.host.effects, [])

    def test_window_endpoint_never_calls_dispatch_and_has_no_maintenance_controls(self):
        for data in ({"protocol": v.PROTOCOL, "cohort": "system"},
                     {"protocol": v.PROTOCOL, "cohort": "plugs", "activate": True},
                     {"protocol": v.PROTOCOL, "cohort": ["plugs"]}):
            self.assert_error(self.call(data, path=v.WINDOW_PATH), "invalid-body")
        window = self.window()
        self.assertEqual(window["maxAgeMs"], 25000)
        self.assertEqual(self.host.preparations, [])
        self.assertEqual(self.host.effects, [])

    def test_loopback_response_loss_then_duplicate_does_not_resubmit_effect(self):
        api = self.api
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                reply = api.handle(method="POST", path=self.path,
                    content_type=self.headers.get("Content-Type"), body=body, access=ACCESS)
                if json.loads(reply.body).get("kind") == "receipt":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_response(reply.status)
                for key, value in reply.headers:
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = self.request()
        try:
            def submit():
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                try:
                    connection.request("POST", v.COMMAND_PATH, encode(request), {"Content-Type": v.CONTENT_TYPE})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            with self.assertRaises(http.client.RemoteDisconnected):
                submit()
            # Deliberate adversarial duplicate, NOT an automatic client retry.
            status, data = submit()
            self.assertEqual(status, 409)
            self.assertEqual(data["code"], "duplicate-intent")
            self.assertEqual(data["disposition"], p.Outcome.UNKNOWN.value)
            self.assertEqual(len(self.host.effects), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(5)

    def test_no_live_wiring_or_import_time_io(self):
        import importlib
        with mock.patch("builtins.open", side_effect=AssertionError("import IO")), \
             mock.patch("pathlib.Path.open", side_effect=AssertionError("import IO")), \
             mock.patch("os.open", side_effect=AssertionError("import IO")), \
             mock.patch("socket.socket", side_effect=AssertionError("import network")):
            # Load under a distinct module name so the dataclass identities used by
            # the rest of the suite are not replaced by a reload.
            spec = importlib.util.spec_from_file_location("jarvisd_core.protocol_import_probe", v.__file__)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        root = Path(v.__file__).resolve().parents[1]
        for path in (root / "jarvisd.py", root / "device-worker.py",
                     root / "jarvisd_core/control.py", root / "jarvisd_core/__init__.py",
                     root.parent / "jarvis.py", root.parents[2] / ".pi/extensions/45-jarvis.ts"):
            self.assertNotIn("control_protocol", path.read_text())
        self.assertEqual(len(commands.COMMANDS), 8)


if __name__ == "__main__":
    unittest.main()
