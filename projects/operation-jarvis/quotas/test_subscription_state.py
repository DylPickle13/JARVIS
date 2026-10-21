"""Inactive Codex/Claude subscriptions are a reported state, not a check failure."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import quotas


def http_error(url, status, body):
    return quotas.HttpRequestError('GET', url, status, body)


class SubscriptionStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'auth.json'
        cred = {'type': 'oauth', 'access': 'fake-access', 'refresh': 'fake-refresh',
                'expires': time.time() * 1000 + 3600_000, 'accountId': 'acct'}
        self.path.write_text(json.dumps({'anthropic': dict(cred), 'openai-codex': dict(cred)}))
        self.auth = quotas.AuthStore(self.path)

    def codex_args(self, **extra):
        values = dict(auth_path=str(self.path), no_refresh=True, codex_client_version='1.0.0',
                      require_model=None, probe=None, probe_timeout=90)
        values.update(extra)
        return argparse.Namespace(**values)

    # Claude ---------------------------------------------------------------

    def test_claude_explicit_null_windows_is_inactive(self):
        raw = {'five_hour': None, 'seven_day': None, 'seven_day_opus': None,
               'extra_usage': {'is_enabled': False}}
        with mock.patch.object(quotas, 'request_json', return_value=(raw, {})):
            report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
        self.assertTrue(report['ok'])
        self.assertEqual(report['usage']['subscription'], 'inactive')
        self.assertIsNone(report['usage']['weekly'])
        self.assertIsNone(report['usage']['five_hour'])
        self.assertFalse(report['usage']['effective_limit_reached'])

    def test_claude_active_reports_subscription(self):
        raw = {'five_hour': {'utilization': 10}, 'seven_day': {'utilization': 50}}
        with mock.patch.object(quotas, 'request_json', return_value=(raw, {})):
            usage = quotas.fetch_claude_usage(self.auth, refresh=False)
        self.assertEqual(usage['subscription'], 'active')

    def test_claude_missing_or_malformed_windows_remain_failures(self):
        for raw in ({}, {'five_hour': None}, {'five_hour': {'utilization': 'x'}, 'seven_day': None}):
            with self.subTest(raw=raw), mock.patch.object(quotas, 'request_json', return_value=(raw, {})):
                report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
                self.assertFalse(report['ok'])

    def test_claude_explicit_plan_refusals_are_inactive(self):
        for status, body in ((402, ''), (403, '{"error":{"message":"This feature requires a Pro or Max subscription"}}')):
            error = http_error(quotas.ANTHROPIC_USAGE_URL, status, body)
            with self.subTest(status=status), mock.patch.object(quotas, 'request_json', side_effect=error):
                report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
                self.assertTrue(report['ok'])
                self.assertEqual(report['usage']['subscription'], 'inactive')
                self.assertNotIn('Max subscription', json.dumps(report))

    def test_claude_auth_and_generic_forbidden_remain_failures(self):
        for status, body in ((401, 'token expired'), (403, 'error code: 1010'), (403, ''), (500, 'subscription')):
            error = http_error(quotas.ANTHROPIC_USAGE_URL, status, body)
            with self.subTest(status=status, body=body), mock.patch.object(quotas, 'request_json', side_effect=error):
                report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
                self.assertFalse(report['ok'])

    def test_claude_inactive_cli_exits_zero(self):
        with mock.patch.object(quotas, 'request_json', return_value=({'five_hour': None, 'seven_day': None}, {})):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = quotas.main(['claude', '--auth-path', str(self.path), '--no-refresh', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())['usage']['subscription'], 'inactive')

    # Codex ----------------------------------------------------------------

    def codex_responses(self, usage, models=None, models_error=None):
        def respond(method, url, **_):
            if url.endswith('/wham/usage'):
                if isinstance(usage, Exception):
                    raise usage
                return usage, {}
            if 'rate-limit-reset-credits' in url:
                raise http_error(url, 404, 'n/a')
            if '/codex/models' in url:
                if models_error is not None:
                    raise models_error
                return models or {'models': [{'slug': 'gpt-5.5'}]}, {}
            raise AssertionError(url)
        return respond

    def test_codex_no_windows_is_inactive_even_if_models_refused(self):
        usage = {'plan_type': 'free', 'rate_limit': None, 'credits': None}
        refused = http_error('https://chatgpt.com/backend-api/codex/models', 403, 'forbidden')
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(usage, models_error=refused)):
            report = quotas.build_codex_report(self.codex_args())
        self.assertTrue(report['ok'])
        self.assertEqual(report['usage']['subscription'], 'inactive')
        self.assertEqual(report['usage']['plan_type'], 'free')
        self.assertIsNone(report['usage']['weekly'])
        self.assertIsNotNone(report['models_error'])

    def test_codex_free_plan_with_windows_is_active(self):
        usage = {'plan_type': 'free', 'rate_limit': {
            'allowed': True, 'limit_reached': False,
            'primary_window': {'used_percent': 40, 'limit_window_seconds': 604800, 'reset_at': 2_000_000_000}}}
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(usage)):
            report = quotas.build_codex_report(self.codex_args())
        self.assertTrue(report['ok'])
        self.assertEqual(report['usage']['subscription'], 'active')
        self.assertEqual(report['usage']['weekly']['remaining_percent'], 60)

    def test_codex_402_is_inactive_but_401_is_failure(self):
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(
                http_error('https://chatgpt.com/backend-api/wham/usage', 402, ''))):
            report = quotas.build_codex_report(self.codex_args())
        self.assertTrue(report['ok'])
        self.assertEqual(report['usage']['subscription'], 'inactive')
        expired = http_error('https://chatgpt.com/backend-api/wham/usage', 401, '{"code":"token_expired"}')
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(expired)):
            report = quotas.build_codex_report(self.codex_args())
        self.assertFalse(report['ok'])

    # Signed out -------------------------------------------------------------

    def test_absent_logins_are_signed_out_state_without_requests(self):
        self.path.write_text(json.dumps({'other': {'untouched': True}}))
        before = self.path.read_bytes()
        with mock.patch.object(quotas, 'request_json', side_effect=AssertionError('no request')):
            claude = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=False))
            codex = quotas.build_codex_report(self.codex_args(no_refresh=False))
        self.assertTrue(claude['ok'])
        self.assertEqual(claude['usage']['subscription'], 'signed_out')
        self.assertTrue(codex['ok'])
        self.assertEqual(codex['usage']['subscription'], 'signed_out')
        self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_or_non_oauth_logins_remain_failures(self):
        for value in ({'type': 'api_key', 'key': 'x'}, 'garbage', {'type': 'oauth'}):
            self.path.write_text(json.dumps({'anthropic': value, 'openai-codex': value}))
            with self.subTest(value=value), mock.patch.object(quotas, 'request_json', side_effect=AssertionError('no request')):
                self.assertFalse(quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))['ok'])
                self.assertFalse(quotas.build_codex_report(self.codex_args())['ok'])

    def test_free_monthly_window_is_active_and_kept(self):
        usage = {'plan_type': 'free', 'rate_limit': {'allowed': True, 'limit_reached': False,
                 'primary_window': {'used_percent': 0, 'limit_window_seconds': 2592000, 'reset_at': 2_000_000_000}}}
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(usage)):
            report = quotas.build_codex_report(self.codex_args())
        self.assertEqual(report['usage']['subscription'], 'active')
        self.assertIsNone(report['usage']['weekly'])
        self.assertEqual(report['usage']['primary']['window_seconds'], 2592000)

    def test_required_models_still_gate_ok(self):
        usage = {'plan_type': 'plus', 'rate_limit': {
            'primary_window': {'used_percent': 1, 'limit_window_seconds': 604800}}}
        refused = http_error('https://chatgpt.com/backend-api/codex/models', 500, 'x')
        with mock.patch.object(quotas, 'request_json', side_effect=self.codex_responses(usage, models_error=refused)):
            self.assertTrue(quotas.build_codex_report(self.codex_args())['ok'])
            self.assertFalse(quotas.build_codex_report(self.codex_args(require_model=['gpt-5.5']))['ok'])


if __name__ == '__main__':
    unittest.main()
