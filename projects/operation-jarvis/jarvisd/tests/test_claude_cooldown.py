"""Offline shared scheduler admission tests; no provider calls or real threads."""
import concurrent.futures
import unittest
from unittest import mock

from jarvisd_core.state import StateCoordinator


class ClaudeCooldownTests(unittest.TestCase):
    def setUp(self):
        self.wall = 1000.0
        self.mono = 100.0
        self.c = StateCoordinator(
            {'claudeQuota': mock.Mock(), 'codexQuota': mock.Mock()},
            now=lambda: self.wall, quota_now=lambda: self.mono,
            version='test', started_at=0)
        self.start = mock.patch.object(self.c, 'start')
        self.start.start()
        self.addCleanup(self.start.stop)

    @property
    def record(self):
        return self.c._records['claudeQuota']

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds

    def complete(self, result):
        future = concurrent.futures.Future()
        future.set_result(result)
        self.c._complete('claudeQuota', future, self.record['revision'])

    def assert_remaining(self, seconds):
        self.assertEqual(self.c._claude_remaining_locked(self.record), seconds)

    def dispatch_once(self):
        # Drive the actual final dispatch gate, but never execute a collector.
        self.c._stop.clear()
        executor = mock.Mock()
        executor.submit.side_effect = lambda *args: concurrent.futures.Future()
        self.c._executor = executor
        with mock.patch.object(self.c._condition, 'wait', side_effect=lambda **kw: self.c._stop.set()):
            self.c._run_scheduler()
        return [call.args[1] for call in executor.submit.call_args_list]

    def test_explicit_refresh_bursts_share_success_and_failure_spacing(self):
        for result in ({'ok': True}, {'ok': False, 'error': 'unavailable'}):
            with self.subTest(result=result):
                self.complete(result)
                self.advance(10)
                for _ in range(100):
                    self.c.request_refresh('claudeQuota')
                self.assert_remaining(110)
                self.assertEqual(self.record['nextDue'], self.wall + 110)
                self.c.request_refresh('codexQuota')
                self.assertEqual(self.c._records['codexQuota']['nextDue'], 0)

    def test_idle_activation_and_recovery_flag_cannot_bypass_backoff(self):
        self.complete({'ok': False, 'rateLimited': True})
        self.advance(10)
        self.c._active_until = 0
        self.c.activate_client()
        self.assertEqual(self.record['nextDue'], self.wall + 290)
        self.c.request_refresh('claudeQuota', retry_cooldown=True)
        self.assert_remaining(290)
        self.assertEqual(self.record['nextDue'], self.wall + 290)

    def test_inflight_requests_coalesce_without_queued_second_collection(self):
        self.record.update(refreshing=True, nextDue=1500)
        for _ in range(100):
            self.c.request_refresh('claudeQuota')
        self.assertEqual(self.record['nextDue'], 1500)
        self.complete({'ok': True})
        self.assertFalse(self.record['refreshing'])
        self.assertEqual(self.record['nextDue'], self.wall + 120)

    def test_exponential_backoff_cap_retry_after_and_success_reset(self):
        for delay in (300, 600, 1200, 1800, 1800):
            self.complete({'ok': False, 'rateLimited': True, 'retryAfterSeconds': 0})
            self.assert_remaining(delay)
            self.assertGreaterEqual(self.record['nextDue'], self.wall + delay)
            self.advance(delay)
        self.complete({'ok': False, 'rateLimited': True, 'retryAfterSeconds': 3600})
        self.assert_remaining(3600)
        self.advance(3600)
        self.complete({'ok': True})
        self.assert_remaining(120)
        self.assertEqual(self.record['quotaRateLimits'], 0)
        self.advance(120)
        self.complete({'ok': False, 'rateLimited': True})
        self.assert_remaining(300)

    def test_malformed_retry_and_non_boolean_rate_limit_are_not_trusted(self):
        for retry in (True, -1, 86401, '5000', float('nan'), float('inf')):
            self.record['quotaRateLimits'] = 0
            self.complete({'ok': False, 'rateLimited': True, 'retryAfterSeconds': retry})
            self.assert_remaining(300)
        self.complete({'ok': False, 'rateLimited': 'true'})
        self.assert_remaining(120)

    def test_actual_scheduler_gate_blocks_wall_jump_and_reset_next_due(self):
        self.complete({'ok': False, 'rateLimited': True})
        self.wall += 10000  # Wall-clock change cannot shorten a monotonic cooldown.
        self.record['nextDue'] = 0  # Simulate another wake/revision path.
        self.assertNotIn('claudeQuota', self.dispatch_once())
        self.advance(299)
        self.assertNotIn('claudeQuota', self.dispatch_once())
        self.advance(1)
        self.assertIn('claudeQuota', self.dispatch_once())

    def test_last_good_error_and_freshness_are_not_hidden(self):
        self.complete({'ok': True, 'available': True, 'checkedAt': 'original'})
        original = self.record['lastGoodAt']
        self.advance(120)
        self.complete({'ok': False, 'rateLimited': True, 'error': 'rate limited'})
        state = self.c.snapshot(start_collectors=False)['subsystems']['claudeQuota']
        self.assertEqual(state['checkedAt'], 'original')
        self.assertEqual(state['lastError'], 'rate limited')
        self.assertEqual(self.record['lastGoodAt'], original)
        self.advance(901)
        self.assertTrue(self.c.snapshot(start_collectors=False)['subsystems']['claudeQuota']['stale'])
        self.complete({'ok': True, 'available': True, 'checkedAt': 'new'})
        state = self.c.snapshot(start_collectors=False)['subsystems']['claudeQuota']
        self.assertNotIn('lastError', state)
        self.assertFalse(state['stale'])

    def test_superseded_result_still_enforces_provider_cooldown(self):
        future = concurrent.futures.Future()
        future.set_result({'ok': False, 'rateLimited': True})
        self.c._complete('claudeQuota', future, self.record['revision'] - 1)
        self.assert_remaining(300)
        self.assertNotIn('claudeQuota', self.dispatch_once())

    def test_concurrent_clients_coalesce_on_one_deadline(self):
        self.complete({'ok': False, 'rateLimited': True})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.c.request_refresh('claudeQuota'), range(100)))
        self.assertEqual(self.record['nextDue'], self.wall + 300)
        self.assertNotIn('claudeQuota', self.dispatch_once())

    def test_idle_interval_and_initial_admission_remain_unchanged(self):
        self.assertIn('claudeQuota', self.dispatch_once())
        self.c._active_until = 0
        self.complete({'ok': True})
        self.assertEqual(self.record['nextDue'], self.wall + 300)
        self.assert_remaining(120)
        self.assertEqual(self.c.intervals['codexQuota'], 60)
        self.assertEqual(self.c.idle_intervals['codexQuota'], 300)


if __name__ == '__main__':
    unittest.main()
