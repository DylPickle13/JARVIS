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

    def test_independent_noncritical_freshness(self):
        coordinator = jarvisd.StateCoordinator(collectors={
            'core': lambda: {'ok': True}, 'claudeQuota': jarvisd._claude_quota}, now=lambda: 100)
        self.assertIn('claudeQuota', coordinator.NONCRITICAL_SUBSYSTEMS)
        self.assertEqual(coordinator.intervals['claudeQuota'], 60)
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
