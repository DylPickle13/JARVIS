"""Owner read scheduling against real ledger/state; no SDK or hardware IO."""
import json
import unittest
from unittest import mock
import test_device_host as fixture
from jarvisd_core import control_protocol as v, client_policy as p
from jarvisd_core.control_readback import ReadbackQueue

C, P, ACCESS, DEVICE = fixture.C, fixture.P, fixture.ACCESS, fixture.DEVICE


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.HostTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.now = 0.0
        self.queue = ReadbackQueue(host=self.f.host, state=self.f.state, monotonic=lambda: self.now)
        self.addCleanup(self.queue.close)
        self.api = v.ControlProtocol(self.f.store, self.f.host, after_dispatch=self.queue.submit)
        self.f.complete(C); self.f.complete(P)

    def submit(self, request=None):
        request = request or self.f.request()
        return self.api.handle(method='POST', path=v.COMMAND_PATH, content_type=v.CONTENT_TYPE,
                               body=json.dumps(request).encode(), access=ACCESS)

    def warm(self, cohort=C):
        self.f.complete(cohort)  # Existing due/pre-ticket aggregate cannot be used as proof.

    def matching(self, cohort=C):
        if cohort is C:
            self.f.plugs['lamp']['isOn'] = True
        else:
            self.f.purifiers['devices'][DEVICE]['isOn'] = False
        self.f.complete(cohort)

    def test_post_callback_queue_then_new_read_clears_only_uncertainty(self):
        request = self.f.request()
        self.assertEqual(self.submit(request).status, 200)
        self.assertEqual(self.f.store.active_count(), 0)
        self.assertEqual(self.queue.snapshot()['waiting'], 1)
        self.queue.tick()  # Existing post-write refresh is still due, not stolen.
        self.assertEqual(self.queue.snapshot()['reading'], 0)
        self.warm(); self.queue.tick()
        self.assertEqual(self.queue.snapshot()['reading'], 1)
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.matching(); self.queue.tick()
        self.assertFalse(self.f.rows()[0]['unresolved'])
        self.assertEqual(self.queue.snapshot()['reconciled'], 1)
        self.assertEqual(json.loads(self.submit(request).body)['code'], 'duplicate-intent')
        self.f.runner.assert_called_once()

    def test_purifier_respects_sixty_second_spacing_without_forcing_cooldown(self):
        self.f.state._records['purifier']['lastRequestedAt'] = self.f.now
        self.submit(self.f.purifier_request())
        self.queue.tick()
        self.assertEqual(self.queue.snapshot()['waiting'], 1)
        self.assertEqual(self.f.store._observations, {})
        self.f.now += 59
        self.queue.tick(); self.assertEqual(self.queue.snapshot()['reading'], 0)
        self.f.now += 1
        self.queue.tick(); self.assertEqual(self.queue.snapshot()['reading'], 1)
        self.assertIs(self.f.state._records['purifier']['retryCooldown'], False)
        self.matching(P); self.queue.tick()
        self.assertFalse(self.f.rows()[0]['unresolved'])

    def test_failed_read_does_not_automatically_poll_or_replay(self):
        self.submit(); self.warm(); self.queue.tick()
        self.f.complete(C, {'ok': False, 'error': 'synthetic failure'})
        self.now = 26
        self.queue.tick()
        self.assertEqual(self.queue.snapshot()['unresolved'], 1)
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.assertFalse(self.f.store._observations)
        for _ in range(5):
            self.queue.tick()
        self.assertEqual(self.queue.snapshot()['reading'], 0)
        self.f.runner.assert_called_once()

    def test_mismatched_read_consumes_ticket_without_refunding(self):
        self.submit(); self.warm(); self.queue.tick()
        self.f.complete(C)  # Lamp remains off.
        self.queue.tick()
        self.assertEqual(self.queue.snapshot()['unresolved'], 1)
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.assertFalse(self.f.store._observations)

    def test_unknown_receipt_remains_unknown_after_genuine_reconciliation(self):
        self.f.runner.side_effect = RuntimeError('synthetic reply loss')
        reply = self.submit()
        self.assertEqual(json.loads(reply.body)['disposition'], p.Outcome.UNKNOWN.value)
        self.warm(); self.queue.tick(); self.matching(); self.queue.tick()
        self.assertFalse(self.f.rows()[0]['unresolved'])
        self.assertEqual(self.f.rows()[0]['outcome'], p.Outcome.UNKNOWN.value)
        self.f.runner.assert_called_once()

    def test_no_queue_for_unauthorized_stale_or_duplicate_requests(self):
        self.f.allow = False
        self.submit()
        self.assertEqual(self.queue.snapshot()['waiting'], 0)
        self.f.allow = True
        request = self.f.request()
        self.submit(request); self.submit(request)
        self.assertEqual(self.queue.snapshot()['waiting'], 1)
        self.assertEqual(len(self.f.rows()), 1)

    def test_unmodeled_toggle_retains_explicit_recovery_requirement(self):
        self.submit(self.f.request(action='plug-toggle'))
        self.assertEqual(self.queue.snapshot()['unsupported'], 1)
        self.assertEqual(self.queue.snapshot()['waiting'], 0)
        self.assertTrue(self.f.rows()[0]['unresolved'])

    def test_queue_capacity_refuses_without_eviction_or_clearing(self):
        queue = ReadbackQueue(host=self.f.host, state=self.f.state, limit=1)
        self.addCleanup(queue.close)
        first = self.f.host.prepare(v._command('plug-on', {'plug': 'lamp'}), ACCESS)
        second = self.f.host.prepare(v._command('plug-on', {'plug': 'tv'}), ACCESS)
        self.assertTrue(queue.submit(first))
        self.assertFalse(queue.submit(second))
        self.assertFalse(queue.submit(first))
        self.assertEqual(queue.snapshot()['waiting'], 1)
        self.assertEqual(queue.snapshot()['capacity'], 1)

    def test_refresh_race_discards_ticket_before_later_ordinary_attempt(self):
        self.submit(); self.warm()
        with mock.patch.object(self.f.state, 'schedule_control_read', return_value=False):
            self.queue.tick()
        self.assertFalse(self.f.store._observations)
        self.assertEqual(self.queue.snapshot()['waiting'], 1)
        self.queue.tick()
        self.assertEqual(self.queue.snapshot()['reading'], 1)
        self.matching(); self.queue.tick()
        self.assertFalse(self.f.rows()[0]['unresolved'])

    def test_close_discards_only_tickets_and_never_requests_another_read(self):
        self.submit(); self.warm(); self.queue.tick()
        self.queue.close(); self.queue.tick()
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.assertFalse(self.f.store._observations)
        self.assertTrue(self.queue.snapshot()['closed'])

    def test_revocation_before_read_does_not_schedule_or_reconcile(self):
        self.submit(); self.warm(); self.f.allow = False
        self.queue.tick()
        self.assertEqual(self.queue.snapshot()['unresolved'], 1)
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.assertFalse(self.f.store._observations)

    def test_scheduler_failure_cannot_change_receipt_or_replay_command(self):
        self.api = v.ControlProtocol(self.f.store, self.f.host,
                                     after_dispatch=mock.Mock(side_effect=RuntimeError('synthetic')))
        self.assertEqual(json.loads(self.submit().body)['disposition'], p.Outcome.ACKNOWLEDGED.value)
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.f.runner.assert_called_once()

    def test_state_probe_is_read_only_and_rejects_foreign_fence(self):
        self.warm()
        with mock.patch.object(self.f.state, 'start', side_effect=AssertionError('probe started IO')):
            self.assertTrue(self.f.state.control_read_ready('plugs'))
        self.assertFalse(self.f.state.schedule_control_read(object()))
        self.assertFalse(self.f.state.control_read_completed(object()))
        self.assertFalse(self.f.state.control_read_ready('services'))
