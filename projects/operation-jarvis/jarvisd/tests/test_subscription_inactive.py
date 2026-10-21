"""An inactive Codex/Claude subscription is reported state, never a backend fault."""
import concurrent.futures
import json
import time
from pathlib import Path
import unittest
from unittest import mock

from daemon_loader import load_daemon
from jarvisd_core import system_health as health
from jarvisd_core.state import StateCoordinator
from test_system_history import BASE, snapshot

jarvisd = load_daemon('jarvisd_subscription_test', Path(__file__).resolve().parents[1] / 'jarvisd.py')


class PublicProjectionTests(unittest.TestCase):
    def test_codex_inactive_is_successful_without_percentages(self):
        result = jarvisd._public_codex_quota({
            'ok': True, 'checked_at': '2026-10-20T20:00:00Z',
            'usage': {'subscription': 'inactive', 'plan_type': 'free', 'weekly': None,
                      'secret': 'private'}})
        self.assertTrue(result['ok'])
        self.assertFalse(result['available'])
        self.assertEqual(result['subscription'], 'inactive')
        self.assertEqual(result['planType'], 'free')
        self.assertIsNone(result['weekly'])
        self.assertIsNone(result['error'])
        self.assertNotIn('private', json.dumps(result))

    def test_claude_inactive_is_successful_without_percentages(self):
        result = jarvisd._public_claude_quota({
            'ok': True, 'checked_at': '2026-10-20T20:00:00Z',
            'usage': {'subscription': 'inactive', 'weekly': None, 'five_hour': None}})
        self.assertTrue(result['ok'])
        self.assertFalse(result['available'])
        self.assertEqual(result['subscription'], 'inactive')
        self.assertEqual(result['checkedAt'], '2026-10-20T20:00:00Z')
        self.assertIsNone(result['weekly'])
        self.assertIsNone(result['error'])

    def test_active_projections_declare_subscription(self):
        window = {'remaining_percent': 50}
        codex = jarvisd._public_codex_quota({'ok': True, 'usage': {'weekly': window}})
        claude = jarvisd._public_claude_quota({'ok': True, 'usage': {'weekly': window}})
        self.assertEqual(codex['subscription'], 'active')
        self.assertEqual(claude['subscription'], 'active')
        self.assertTrue(codex['available'] and claude['available'])

    def test_failures_remain_failures(self):
        # Without an explicit inactive marker, missing windows are still errors.
        self.assertFalse(jarvisd._public_codex_quota({'ok': True, 'usage': {'weekly': None}})['ok'])
        self.assertFalse(jarvisd._public_claude_quota({'ok': True, 'usage': {}})['ok'])
        self.assertFalse(jarvisd._public_codex_quota({'ok': False, 'usage': {'subscription': 'inactive'}})['ok'])


class HealthProjectionTests(unittest.TestCase):
    def inactive_snapshot(self, *names):
        value = snapshot()
        for name in names:
            value['subsystems'][name] = jarvisd._inactive_subscription_quota('2026-10-20T20:00:00Z')
        return value

    def test_inactive_subscriptions_do_not_fail_overall(self):
        rows = health.project(self.inactive_snapshot('codexQuota', 'claudeQuota'), BASE)
        for name in ('codexQuota', 'claudeQuota'):
            self.assertEqual(rows[name]['state'], 'inactive')
            self.assertEqual(rows[name]['reason'], 'optional_inactive')
            self.assertEqual(rows[name]['validUntil'], BASE + health.LIMITS[name])
        self.assertEqual(rows['overall']['state'], 'healthy')
        self.assertEqual(rows['overall']['reason'], 'current')

    def test_stale_inactive_reading_is_unknown_not_inactive(self):
        value = self.inactive_snapshot('codexQuota')
        value['subsystemsMeta']['codexQuota']['stale'] = True
        self.assertEqual(health.project(value, BASE)['codexQuota']['state'], 'unknown')

    def test_failed_collection_still_fails_overall(self):
        value = self.inactive_snapshot('claudeQuota')
        value['subsystemsMeta']['codexQuota'].update(ok=False, error='Codex quota unavailable')
        rows = health.project(value, BASE)
        self.assertEqual(rows['claudeQuota']['state'], 'inactive')
        self.assertEqual(rows['codexQuota']['state'], 'unavailable')
        self.assertEqual(rows['overall']['state'], 'unavailable')

    def test_marker_only_applies_to_subscription_components(self):
        value = snapshot()
        value['subsystems']['network'] = {'subscription': 'inactive'}
        self.assertEqual(health.project(value, BASE)['network']['state'], 'healthy')


class MainWindowAndSignedOutTests(unittest.TestCase):
    def test_free_monthly_window_becomes_main_gauge(self):
        result = jarvisd._public_codex_quota({'ok': True, 'checked_at': '2026-10-21T01:00:00Z', 'usage': {
            'subscription': 'active', 'plan_type': 'free', 'weekly': None, 'five_hour': None,
            'primary': {'remaining_percent': 100.0, 'used_percent': 0, 'window_seconds': 2592000,
                        'reset_after_seconds': 2592000, 'reset_at': 1795136754},
            'secondary': None, 'credits': {'balance': '1887.2380505000'},
            'primary_limit': {'status': 'unavailable', 'enforced': None}}})
        self.assertTrue(result['ok'] and result['available'])
        self.assertIsNone(result['weekly'])
        self.assertEqual(result['mainWindowLabel'], 'monthly')
        self.assertEqual(result['mainWindow']['remainingPercent'], 100.0)
        self.assertEqual(result['fiveHourStatus'], 'none')
        self.assertEqual(result['creditBalance'], 1887.24)

    def test_weekly_plans_keep_weekly_as_main_and_five_hour_status(self):
        result = jarvisd._public_codex_quota({'ok': True, 'usage': {
            'weekly': {'remaining_percent': 60}, 'five_hour': {'remaining_percent': 90},
            'primary': {'remaining_percent': 90, 'window_seconds': 18000},
            'secondary': {'remaining_percent': 60, 'window_seconds': 604800},
            'primary_limit': {'status': 'temporarily_suspended', 'enforced': False}}})
        self.assertEqual(result['mainWindowLabel'], 'weekly')
        self.assertEqual(result['mainWindow'], result['weekly'])
        self.assertEqual(result['fiveHourStatus'], 'temporarily_suspended')

    def test_only_a_five_hour_window_is_not_a_main_gauge(self):
        result = jarvisd._public_codex_quota({'ok': True, 'usage': {
            'weekly': None, 'primary': {'remaining_percent': 90, 'window_seconds': 18000}}})
        self.assertFalse(result['ok'])

    def test_window_labels(self):
        day = 86400
        for seconds, label in ((18000, '5h'), (7 * day, 'weekly'), (30 * day, 'monthly'),
                               (2 * day, '2d'), (7200, '2h'), (1234, None), (True, None), (-1, None)):
            self.assertEqual(jarvisd._window_label(seconds), label)

    def test_signed_out_projects_and_is_not_a_fault(self):
        for project in (jarvisd._public_codex_quota, jarvisd._public_claude_quota):
            result = project({'ok': True, 'checked_at': '2026-10-21T01:00:00Z',
                              'usage': {'subscription': 'signed_out'}})
            self.assertTrue(result['ok'])
            self.assertEqual(result['subscription'], 'signed_out')
        value = snapshot()
        value['subsystems']['codexQuota'] = jarvisd._inactive_subscription_quota(None, None, 'signed_out')
        rows = health.project(value, BASE)
        self.assertEqual(rows['codexQuota']['state'], 'inactive')
        self.assertEqual(rows['overall']['state'], 'healthy')
        self.assertEqual(jarvisd._inactive_subscription_quota(None, None, 'bogus')['subscription'], 'inactive')


class RateLimitedFreshReadingTests(unittest.TestCase):
    def setUp(self):
        self.wall, self.mono = 1000.0, 100.0
        self.c = StateCoordinator({'claudeQuota': mock.Mock(), 'codexQuota': mock.Mock()},
                                  now=lambda: self.wall, quota_now=lambda: self.mono,
                                  version='test', started_at=0)
        patcher = mock.patch.object(self.c, 'start'); patcher.start(); self.addCleanup(patcher.stop)

    def complete(self, result):
        future = concurrent.futures.Future(); future.set_result(result)
        self.c._complete('claudeQuota', future, self.c._records['claudeQuota']['revision'])

    def advance(self, seconds):
        self.wall += seconds; self.mono += seconds

    def health_row(self):
        snap = self.c.snapshot(start_collectors=False)
        # Timestamps are real wall time; ages come from the fake clock.
        return snap, health.project(snap, time.time())['claudeQuota']

    def test_fresh_rate_limited_reading_is_current_then_expires(self):
        self.complete({'ok': True, 'available': True, 'checkedAt': 'x', 'weekly': {'remainingPercent': 97}})
        self.advance(120)
        self.complete({'ok': False, 'rateLimited': True, 'error': 'Claude usage rate limited'})
        snap, row = self.health_row()
        self.assertTrue(snap['subsystems']['claudeQuota']['rateLimited'])
        self.assertTrue(snap['subsystemsMeta']['claudeQuota']['rateLimited'])
        self.assertEqual(snap['subsystems']['claudeQuota']['lastError'], 'Claude usage rate limited')
        self.assertEqual(row['state'], 'healthy')
        self.advance(901)
        _, row = self.health_row()
        self.assertEqual(row['state'], 'unknown')

    def test_other_failures_and_no_last_good_still_fail(self):
        self.complete({'ok': False, 'rateLimited': True, 'error': 'rate limited'})
        _, row = self.health_row()
        self.assertEqual(row['state'], 'unavailable')   # nothing good to show yet
        self.complete({'ok': True, 'available': True, 'checkedAt': 'x'})
        self.advance(120)
        self.complete({'ok': False, 'error': 'Claude usage failed (http_error)'})
        snap, row = self.health_row()
        self.assertNotIn('rateLimited', snap['subsystems']['claudeQuota'])
        self.assertEqual(row['state'], 'unavailable')
        self.advance(120)
        self.complete({'ok': True, 'available': True, 'checkedAt': 'y'})
        snap, row = self.health_row()
        self.assertNotIn('rateLimited', snap['subsystems']['claudeQuota'])
        self.assertEqual(row['state'], 'healthy')


if __name__ == '__main__':
    unittest.main()
