import concurrent.futures
import json
from pathlib import Path
import unittest
from unittest import mock

from daemon_loader import load_daemon

jarvisd = load_daemon('jarvisd_claude_test', Path(__file__).resolve().parents[1] / 'jarvisd.py')


class ClaudeQuotaTests(unittest.TestCase):
    def payload(self):
        return {'ok': True, 'checked_at': '2026-10-17T20:00:00Z', 'secret': 'private',
                'usage': {'weekly': {'remaining_percent': 98, 'private': 'secret'},
                          'five_hour': {'used_percent': 20, 'reset_at': 1792279800},
                          'seven_day_opus': {'used_percent': 99}, 'plan_type': 'private'}}

    def test_public_projection_is_bounded_and_whitelisted(self):
        result = jarvisd._public_claude_quota(self.payload())
        self.assertTrue(result['ok'])
        self.assertEqual(result['weekly']['remainingPercent'], 98)
        self.assertEqual(result['fiveHour']['remainingPercent'], 80)
        self.assertTrue(result['fiveHourEnforced'])
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('opus', json.dumps(result))
        self.assertNotIn('planType', result)
        self.assertEqual(result['checkedAt'], '2026-10-17T20:00:00Z')

    def test_sanitized_failure_stage_survives_projection(self):
        payload = {'ok': False, 'usage_error': 'secret', 'diagnostic': {
            'stage': 'refresh', 'code': 'http_error', 'http_status': 403, 'body': 'secret'}}
        result = jarvisd._public_claude_quota(payload)
        self.assertEqual(result['diagnostic'], {'stage': 'refresh', 'code': 'http_error', 'http_status': 403})
        self.assertNotIn('secret', json.dumps(result))
        for field in ('stage', 'code'):
            bad = {**payload, 'diagnostic': {**payload['diagnostic'], field: 'secret'}}
            self.assertNotIn('diagnostic', jarvisd._public_claude_quota(bad))
        for status in (True, 399, 600, 'secret'):
            bad = {**payload, 'diagnostic': {**payload['diagnostic'], 'http_status': status}}
            self.assertNotIn('http_status', jarvisd._public_claude_quota(bad)['diagnostic'])

    def test_invalid_and_partial_payloads(self):
        for value in (None, [], {}, {'ok': False}, {'ok': True, 'usage': {}},
                      {'ok': True, 'usage': {'weekly': {'remaining_percent': float('nan')}}}):
            self.assertFalse(jarvisd._public_claude_quota(value)['available'])
        payload = self.payload()
        payload['usage']['weekly'] = None
        payload['checked_at'] = 'private'
        result = jarvisd._public_claude_quota(payload)
        self.assertTrue(result['available'])
        self.assertIsNone(result['checkedAt'])
        self.assertIsNone(result['weekly'])
        payload['usage']['five_hour']['used_percent'] = 100
        self.assertTrue(jarvisd._public_claude_quota(payload)['limitReached'])

    def test_fixed_usage_command_bounded_failures(self):
        completed = mock.Mock(returncode=0, stdout=json.dumps(self.payload()), stderr='private')
        with mock.patch.object(jarvisd, 'CLAUDE_QUOTAS_SCRIPT', Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, 'run', return_value=completed) as run:
            self.assertTrue(jarvisd._claude_quota()['available'])
        self.assertEqual(run.call_args.args[0][-2:], ['claude', '--json'])
        self.assertNotIn('--probe', run.call_args.args[0])
        self.assertNotIn('--save', run.call_args.args[0])
        for code, output in ((2, 'private'), (0, 'invalid JSON'),
                             (0, 'x' * (jarvisd.MAX_CLAUDE_QUOTA_OUTPUT_BYTES + 1))):
            completed.returncode, completed.stdout = code, output
            with mock.patch.object(jarvisd, 'CLAUDE_QUOTAS_SCRIPT', Path(__file__)), \
                 mock.patch.object(jarvisd.subprocess, 'run', return_value=completed):
                result = jarvisd._claude_quota()
            self.assertFalse(result['available'])
            self.assertNotIn('private', json.dumps(result))

    def test_periodic_completion_uses_two_minutes_only_for_active_claude(self):
        coordinator = jarvisd.StateCoordinator(collectors={
            'claudeQuota': lambda: {'ok': True},
            'codexQuota': lambda: {'ok': True}}, now=lambda: 100)
        for active, expected in ((True, {'claudeQuota': 220, 'codexQuota': 160}),
                                 (False, {'claudeQuota': 400, 'codexQuota': 400})):
            coordinator._active_until = 200 if active else 0
            for ok in (True, False):
                for name, next_due in expected.items():
                    with self.subTest(active=active, ok=ok, name=name):
                        future = concurrent.futures.Future()
                        future.set_result({'ok': ok, 'error': None if ok else 'unavailable'})
                        coordinator._complete(name, future, coordinator._records[name]['revision'])
                        self.assertEqual(coordinator._records[name]['nextDue'], next_due)

    def test_rate_limit_projection_and_failed_process_report(self):
        payload = {'ok': False, 'rate_limited': True, 'retry_after_seconds': 700,
                   'usage_error': 'secret body', 'headers': {'private': 'secret'}}
        result = jarvisd._public_claude_quota(payload)
        self.assertEqual(result, {'ok': False, 'available': False,
            'error': 'Claude usage rate limited; waiting before another check.',
            'rateLimited': True, 'retryAfterSeconds': 700})
        self.assertNotIn('secret', json.dumps(result))
        for retry in (True, -1, 86401, 1.5, '120', float('inf')):
            self.assertIsNone(jarvisd._public_claude_quota(
                {**payload, 'retry_after_seconds': retry})['retryAfterSeconds'])
        self.assertNotIn('rateLimited', jarvisd._public_claude_quota(
            {**payload, 'rate_limited': 'true'}))
        completed = mock.Mock(returncode=2, stdout=json.dumps(payload))
        with mock.patch.object(jarvisd, 'CLAUDE_QUOTAS_SCRIPT', Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, 'run', return_value=completed) as run:
            self.assertTrue(jarvisd._claude_quota()['rateLimited'])
        self.assertEqual(run.call_count, 1)

    def test_usage_http_429_report_reaches_scheduler_backoff(self):
        import argparse
        import importlib.util
        import io
        import urllib.error
        spec = importlib.util.spec_from_file_location('claude_usage_contract',
            Path(__file__).resolve().parents[2] / 'quotas/quotas.py')
        usage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(usage)
        error = urllib.error.HTTPError(usage.ANTHROPIC_USAGE_URL, 429, 'private',
            {'Retry-After': '700'}, io.BytesIO(b'secret'))
        output = io.StringIO()
        import contextlib
        with mock.patch.object(usage.AuthStore, 'ensure_anthropic', return_value={'access': 'fake'}), \
             mock.patch.object(usage.urllib.request, 'urlopen', side_effect=error) as request, \
             contextlib.redirect_stdout(output):
            code = usage.main(['claude', '--auth-path', '/nonexistent/offline-auth', '--no-refresh', '--json'])
        self.assertEqual(code, 2)
        completed = mock.Mock(returncode=code, stdout=output.getvalue())
        with mock.patch.object(jarvisd, 'CLAUDE_QUOTAS_SCRIPT', Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, 'run', return_value=completed):
            result = jarvisd._claude_quota()
        coordinator = jarvisd.StateCoordinator(
            collectors={'claudeQuota': lambda: result}, now=lambda: 100, quota_now=lambda: 100)
        future = concurrent.futures.Future()
        future.set_result(result)
        coordinator._complete('claudeQuota', future, 0)
        self.assertEqual(coordinator._records['claudeQuota']['nextDue'], 800)
        self.assertEqual(request.call_count, 1)
        self.assertNotIn('secret', json.dumps(result))

    def test_independent_noncritical_freshness(self):
        coordinator = jarvisd.StateCoordinator(collectors={
            'core': lambda: {'ok': True}, 'claudeQuota': jarvisd._claude_quota}, now=lambda: 100)
        self.assertIn('claudeQuota', coordinator.NONCRITICAL_SUBSYSTEMS)
        self.assertEqual(coordinator.intervals['claudeQuota'], 120)
        self.assertEqual(coordinator.intervals['codexQuota'], 60)
        self.assertEqual(coordinator.idle_intervals['codexQuota'], 300)
        self.assertEqual(coordinator.idle_intervals['claudeQuota'], 300)
        self.assertEqual(coordinator.freshness_limits['claudeQuota'], 900)
        coordinator._records['core'].update(data={'ok': True}, updatedAt='2026-10-17T20:00:00Z',
                                            lastGoodAt=100, stale=False)
        with mock.patch.object(coordinator, 'start'):
            snapshot = coordinator.snapshot()
        self.assertFalse(snapshot['stale'])
        self.assertTrue(snapshot['subsystems']['claudeQuota']['stale'])


if __name__ == '__main__':
    unittest.main()
