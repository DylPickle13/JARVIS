"""Offline convergence contract. No live clients, transports, queues or fences."""
import concurrent.futures
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest

# Use the test loader's synthetic roots/path setup, not host configuration.
from test_jarvisd import jarvisd as d
from jarvisd_core import client_policy as p


class HandoffPolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = p.Ownership(p.Cohort.PLUGS, 7, p.Mode.MIXED)
        self.draining = p.request_drain(self.state)
        self.proof = p.HandoffEvidence(p.Cohort.PLUGS, self.draining.epoch, 0,
            local_workers_quiescent=True, legacy_writers_fenced=True, uncertainty_preserved=True,
            catalogue_validated=True, clients_compatible=True, client_transports_checked=True)

    def test_initial_state_closed_not_implicit_legacy_fallback(self):
        self.assertEqual(p.Ownership(p.Cohort.PLUGS, 0).mode, p.Mode.CLOSED)

    def test_drain_advances_epoch_and_repeated_drain_is_idempotent(self):
        self.assertEqual(self.draining.epoch, 8)
        self.assertEqual(self.draining.mode, p.Mode.DRAINING)
        self.assertEqual(p.request_drain(self.draining), self.draining)

    def test_full_handoff_requires_two_epoch_boundaries(self):
        maintenance = p.enter_maintenance(self.draining, self.proof)
        self.assertEqual(maintenance.epoch, 8)
        active = p.activate_api(maintenance, self.proof)
        self.assertEqual(active, p.Ownership(p.Cohort.PLUGS, 9, p.Mode.API))

    def test_no_direct_mixed_to_api_or_maintenance_transition(self):
        for function in (p.enter_maintenance, p.activate_api):
            with self.assertRaises(p.PolicyError):
                function(self.state, self.proof)

    def test_active_unknown_or_boolean_write_counts_do_not_prove_drained(self):
        for count in (None, 1, -1, False, True, 0.0, "0"):
            with self.subTest(count=count), self.assertRaises(p.PolicyError):
                p.enter_maintenance(self.draining, replace(self.proof, active_writes=count))

    def test_process_exit_alone_does_not_prove_cloud_cancellation(self):
        with self.assertRaises(p.PolicyError):
            p.enter_maintenance(self.draining, replace(self.proof, uncertainty_preserved=False))

    def test_unfenced_legacy_writer_blocks_handoff(self):
        with self.assertRaises(p.PolicyError):
            p.enter_maintenance(self.draining, replace(self.proof, legacy_writers_fenced=False))

    def test_workers_must_be_quiescent_not_merely_zero_daemon_slots(self):
        with self.assertRaises(p.PolicyError):
            p.enter_maintenance(self.draining, replace(self.proof, local_workers_quiescent=False))

    def test_stale_and_other_cohort_evidence_is_rejected(self):
        for proof in (replace(self.proof, epoch=7), replace(self.proof, epoch=8.0),
                      replace(self.proof, cohort=p.Cohort.PURIFIER)):
            with self.assertRaises(p.PolicyError):
                p.enter_maintenance(self.draining, proof)

    def test_activation_requires_catalogue_client_and_transport_checks(self):
        maintenance = p.enter_maintenance(self.draining, self.proof)
        for field in ("catalogue_validated", "clients_compatible", "client_transports_checked",
                      "local_workers_quiescent", "legacy_writers_fenced", "uncertainty_preserved"):
            for value in (False, None, 1, "yes"):
                with self.subTest(field=field, value=value), self.assertRaises(p.PolicyError):
                    p.activate_api(maintenance, replace(self.proof, **{field: value}))

    def test_restart_and_rollback_never_restore_api_ownership_or_old_epoch(self):
        active = p.activate_api(p.enter_maintenance(self.draining, self.proof), self.proof)
        recovered = p.restart_closed(active)
        self.assertEqual(recovered.mode, p.Mode.CLOSED)
        self.assertGreater(recovered.epoch, active.epoch)
        with self.assertRaises(p.PolicyError):
            p.activate_api(recovered, self.proof)

    def test_bad_modes_epochs_and_overflow_fail_closed(self):
        for value in (-1, True, "7", 7.0, p.MAX_EPOCH + 1):
            with self.assertRaises(p.PolicyError):
                p.Ownership(p.Cohort.PLUGS, value)
        with self.assertRaises(p.PolicyError):
            p.Ownership(p.Cohort.PLUGS, 7, "api-owned")
        with self.assertRaises(p.PolicyError):
            p.Ownership("plugs", 7)
        for epoch in (0, p.MAX_EPOCH):
            with self.assertRaises(p.PolicyError):
                p.Ownership(p.Cohort.PLUGS, epoch, p.Mode.API)
        last_active = p.Ownership(p.Cohort.PLUGS, p.MAX_EPOCH - 1, p.Mode.API)
        self.assertEqual(p.request_drain(last_active).mode, p.Mode.DRAINING)
        self.assertEqual(p.restart_closed(last_active).mode, p.Mode.CLOSED)
        with self.assertRaises(p.PolicyError):
            p.request_drain(p.Ownership(p.Cohort.PLUGS, p.MAX_EPOCH))


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = p.Ownership(p.Cohort.PLUGS, 9, p.Mode.API)
        self.ready = p.Readiness(9, 9, endpoint_available=True, protocol_verified=True,
            transport_guarded=True, authorized=True, target_known=True, observation_fresh=True,
            target_uncertain=False)

    def plan(self, state=None, ready=None, action="plug-on"):
        return p.plan_write(action, state or self.state, ready or self.ready)

    def test_ready_route_is_api_only(self):
        plan = self.plan()
        self.assertEqual(plan.route, p.Route.API)
        self.assertFalse(plan.automatic_retry)
        self.assertFalse(plan.fallback)
        self.assertFalse(plan.queue)
        self.assertEqual(set(p.Route), {p.Route.BLOCK, p.Route.API})

    def test_all_nonactive_modes_block(self):
        for mode in p.Mode:
            if mode is not p.Mode.API:
                self.assertEqual(self.plan(state=replace(self.state, mode=mode)).route, p.Route.BLOCK)

    def test_every_missing_readiness_fact_blocks_without_fallback(self):
        for field in ("endpoint_available", "protocol_verified", "transport_guarded", "authorized",
                      "target_known", "observation_fresh"):
            for value in (False, None, 1, "true"):
                with self.subTest(field=field, value=value):
                    plan = self.plan(ready=replace(self.ready, **{field: value}))
                    self.assertEqual(plan.route, p.Route.BLOCK)
                    self.assertFalse(plan.fallback)

    def test_missing_or_stale_request_and_observation_epochs_block(self):
        for field in ("request_epoch", "observation_epoch"):
            for value in (None, 8, 10, "9", 9.0, True):
                self.assertEqual(self.plan(ready=replace(self.ready, **{field: value})).route, p.Route.BLOCK)

    def test_unknown_pending_or_uncertain_targets_block(self):
        for value in (True, None, 0, "false"):
            self.assertEqual(self.plan(ready=replace(self.ready, target_uncertain=value)).route, p.Route.BLOCK)

    def test_unlisted_read_and_wrong_cohort_actions_never_route_as_writes(self):
        for action in ("status", "plug-status", "purifier-status", "purifier-set", "plug-save-discovery",
                       "cast-volume", "service-restart", "arbitrary-shell", None, []):
            self.assertEqual(self.plan(action=action).route, p.Route.BLOCK)

    def test_existing_compatibility_toggle_also_has_no_replay_or_fallback(self):
        self.assertEqual(self.plan(action="plug-toggle").route, p.Route.API)
        self.assertFalse(self.plan(action="plug-toggle").automatic_retry)

    def test_purifier_cohort_requires_its_own_ownership(self):
        state = replace(self.state, cohort=p.Cohort.PURIFIER)
        self.assertEqual(self.plan(state=state, action="purifier-set").route, p.Route.API)
        self.assertEqual(self.plan(state=state, action="plug-on").route, p.Route.BLOCK)

    def test_current_v1_readiness_without_epoch_is_not_enough(self):
        self.assertEqual(self.plan(ready=p.Readiness(endpoint_available=True)).route, p.Route.BLOCK)

    def test_claim_is_consumed_before_any_transport_attempt(self):
        attempt = p.WriteAttempt(self.plan())
        self.assertTrue(attempt.claim(self.state))
        # A subsequent timeout/cancellation/parse failure cannot refund the claim.
        for _ in range(3):
            with self.assertRaises(p.PolicyError):
                attempt.claim(self.state)

    def test_rejected_preflight_intent_cannot_be_reused_after_recovery(self):
        attempt = p.WriteAttempt(self.plan(ready=replace(self.ready, endpoint_available=False)))
        self.assertFalse(attempt.claim(self.state))
        with self.assertRaises(p.PolicyError):
            attempt.claim(self.state)

    def test_maintenance_between_plan_and_claim_blocks(self):
        attempt = p.WriteAttempt(self.plan())
        self.assertFalse(attempt.claim(p.request_drain(self.state)))
        with self.assertRaises(p.PolicyError):
            attempt.claim(self.state)

    def test_other_cohort_cannot_consume_a_plan_as_permission(self):
        self.assertFalse(p.WriteAttempt(self.plan()).claim(replace(self.state, cohort=p.Cohort.PURIFIER)))

    def test_concurrent_claims_allow_only_one_local_submission(self):
        attempt = p.WriteAttempt(self.plan())
        def claim(_):
            try:
                return attempt.claim(self.state)
            except p.PolicyError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(claim, range(64))), 1)

    def test_cloud_recovery_never_requests_cooldown_bypass(self):
        self.assertEqual(p.recovery_for(p.Cohort.PLUGS), p.Recovery.STATE_READ)
        self.assertEqual(p.recovery_for(p.Cohort.PURIFIER), p.Recovery.FOREGROUND_READ)
        with self.assertRaises(p.PolicyError):
            p.recovery_for("security")


class OutcomePolicyTests(unittest.TestCase):
    def reply(self, status, body, **kwargs):
        return p.classify_reply("plug-on", status, body, authoritative=True, expected_plug="lamp", **kwargs)

    def test_only_unstarted_intent_is_locally_not_submitted(self):
        self.assertEqual(self.reply(None, None, submitted=False), p.Outcome.NOT_SUBMITTED)
        self.assertEqual(self.reply(200, {}, submitted=False), p.Outcome.UNKNOWN)
        self.assertEqual(self.reply(None, None), p.Outcome.UNKNOWN)

    def test_known_authoritative_predispatch_rejections(self):
        for code in (400, 401, 403, 409, 411, 413):
            self.assertEqual(self.reply(code, {"ok": False, "error": "rejected"}), p.Outcome.REJECTED)
            self.assertEqual(self.reply(code, {"ok": False, "action": "plug-on", "error": "rejected"}), p.Outcome.REJECTED)

    def test_arbitrary_proxy_json_is_not_proof_of_rejection(self):
        self.assertEqual(p.classify_reply("plug-on", 409, {"ok": False, "error": "rejected"}), p.Outcome.UNKNOWN)

    def test_adapter_failure_inside_http200_is_ambiguous(self):
        self.assertEqual(self.reply(200, {"ok": False, "action": "plug-on", "error": "write failed"}), p.Outcome.UNKNOWN)

    def test_redirect_rate_limit_and_server_errors_are_never_rejection_proof(self):
        for code in (301, 302, 303, 307, 308, 404, 429, 500, 502, 503, 504):
            self.assertEqual(self.reply(code, {"ok": False, "action": "plug-on", "error": "nothing sent"}), p.Outcome.UNKNOWN)

    def test_wrong_action_bad_body_and_nonboolean_success_are_unknown(self):
        for body in (None, [], "ok", {"ok": 1, "action": "plug-on"},
                     {"ok": False, "action": "purifier-set", "error": "rejected"},
                     {"ok": False, "error": ""}):
            self.assertEqual(self.reply(409, body), p.Outcome.UNKNOWN)

    def test_matching_plug_ack_is_not_a_fresh_observation_or_execution_proof(self):
        body = {"ok": True, "action": "plug-on", "plug": {"name": "lamp", "is_on": True}}
        self.assertEqual(self.reply(200, body), p.Outcome.ACKNOWLEDGED)
        self.assertEqual(self.reply(200.0, body), p.Outcome.UNKNOWN)
        self.assertEqual(self.reply(200, {**body, "error": "contradictory failure"}), p.Outcome.UNKNOWN)
        for plug in ({"name": "other", "is_on": True}, {"name": "lamp", "is_on": False},
                     {"name": "lamp", "is_on": 1}, {}):
            self.assertEqual(self.reply(200, {**body, "plug": plug}), p.Outcome.UNKNOWN)

    def test_purifier_acceptance_and_pending_keep_existing_shape(self):
        for pending, expected in ((False, p.Outcome.ACKNOWLEDGED), (True, p.Outcome.PENDING)):
            body = {"ok": True, "action": "purifier-set", "airPurifier": {"ok": True, "data": {
                "is_on": True, "write_accepted": True, "verification_pending": pending}}}
            self.assertEqual(p.classify_reply("purifier-set", 200, body, authoritative=True), expected)
            for field, value in (("is_on", None), ("write_accepted", False), ("verification_pending", None)):
                bad = {**body, "airPurifier": {"ok": True, "data": {**body["airPurifier"]["data"], field: value}}}
                self.assertEqual(p.classify_reply("purifier-set", 200, bad, authoritative=True), p.Outcome.UNKNOWN)

    def test_classification_matches_real_public_projection_without_changing_schema(self):
        body = d._public_command_result("plug-on", {"ok": True, "plug": {
            "name": "lamp", "is_on": True}, "command": ["private-worker", "private-arguments"]})
        self.assertEqual(self.reply(200, body), p.Outcome.ACKNOWLEDGED)
        self.assertNotIn("command", body)
        body = d._public_command_result("purifier-set", {"ok": True, "airPurifier": {"ok": True,
            "data": {"is_on": True, "write_accepted": True, "verification_pending": True,
                     "cid": "private-cid"}}})
        self.assertEqual(p.classify_reply("purifier-set", 200, body, authoritative=True), p.Outcome.PENDING)
        self.assertNotIn("cid", body["airPurifier"]["data"])
        failure = d._public_command_result("plug-on", {"ok": False, "error": "response lost"})
        self.assertEqual(self.reply(200, failure), p.Outcome.UNKNOWN)

    def test_unknown_action_cannot_be_certified_by_an_ok_payload(self):
        self.assertEqual(p.classify_reply("arbitrary-shell", 200, {"ok": True}, authoritative=True), p.Outcome.UNKNOWN)


class ReferenceBoundaryTests(unittest.TestCase):
    def test_module_is_not_wired_into_live_entry_dispatch_or_admission(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("jarvisd.py", "jarvisd_core/control.py", "jarvisd_core/admission.py", "jarvisd_core/__init__.py"):
            self.assertNotIn("client_policy", (root / name).read_text())
        self.assertEqual(len(d.COMMANDS), 8)

    def test_import_has_no_network_config_persistence_or_execution(self):
        root = Path(__file__).resolve().parents[1]
        code = '''
import sys, socket, subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
def forbidden(*args, **kwargs): raise AssertionError("Import-time I/O")
with patch('builtins.open', forbidden), patch.object(Path, 'read_text', forbidden), \\
     patch.object(Path, 'read_bytes', forbidden), patch.object(Path, 'write_text', forbidden), \\
     patch.object(socket, 'socket', forbidden), patch.object(subprocess, 'Popen', forbidden):
    from jarvisd_core import client_policy
    assert client_policy.Ownership(client_policy.Cohort.PLUGS, 0).mode is client_policy.Mode.CLOSED
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
