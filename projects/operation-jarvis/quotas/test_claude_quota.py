"""Offline subscription usage/auth contracts; never touch real credentials."""
import argparse
import contextlib
import datetime as dt
import urllib.error
import io
import json
import os
import threading
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import quotas


class ClaudeQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'auth.json'
        self.creds = {'type': 'oauth', 'access': 'fake-access', 'refresh': 'fake-refresh',
                      'expires': time.time() * 1000 + 3600_000, 'custom': 'retained'}
        self.path.write_text(json.dumps({'anthropic': self.creds, 'other': {'untouched': True}}))
        self.auth = quotas.AuthStore(self.path)
        self.raw = {'five_hour': {'utilization': 20, 'resets_at': '2026-10-17T23:00:00.204Z'},
                    'seven_day': {'utilization': 2, 'resets_at': '2026-10-19T16:00:00Z'},
                    'seven_day_opus': {'utilization': 99}, 'extra_usage': {'is_enabled': False},
                    'secret': 'must-not-leak'}

    def test_read_only_usage_whitelist(self):
        before = self.path.read_bytes()
        with mock.patch.object(quotas, 'request_json', return_value=(self.raw, {})) as request:
            usage = quotas.fetch_claude_usage(self.auth)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args, ('GET', quotas.ANTHROPIC_USAGE_URL))
        self.assertNotIn('body', request.call_args.kwargs)
        self.assertEqual(usage['weekly']['remaining_percent'], 98)
        self.assertEqual(usage['five_hour']['remaining_percent'], 80)
        self.assertTrue(usage['primary_limit']['enforced'])
        self.assertFalse(usage['effective_limit_reached'])
        for private in ('secret', 'extra_usage', 'opus', 'fake-access'):
            self.assertNotIn(private, json.dumps(usage))
        self.assertEqual(self.path.read_bytes(), before)

    def test_partial_missing_and_invalid_windows(self):
        for value in (None, [], {}, {'utilization': True}, {'utilization': -1},
                      {'utilization': float('nan')}, {'utilization': float('inf')},
                      {'utilization': 101}, {'utilization': '2'}):
            self.assertIsNone(quotas.normalize_claude_window(value))
        for reset in ('bad', '2026-10-17', '#{unsafe}', None):
            window = quotas.normalize_claude_window({'utilization': 0, 'resets_at': reset})
            self.assertEqual(window['remaining_percent'], 100)
            self.assertIsNone(window['reset_at'])
        with mock.patch.object(quotas, 'request_json', return_value=({'five_hour': {'utilization': 100}}, {})):
            usage = quotas.fetch_claude_usage(self.auth)
            self.assertIsNone(usage['weekly'])
            self.assertTrue(usage['effective_limit_reached'])
        with mock.patch.object(quotas, 'request_json', return_value=({}, {})):
            with self.assertRaises(quotas.QuotaError):
                quotas.fetch_claude_usage(self.auth)

    def test_no_refresh_never_writes_or_posts(self):
        self.creds['expires'] = 1
        self.path.write_text(json.dumps({'anthropic': self.creds}))
        before = self.path.read_bytes()
        with mock.patch.object(quotas, 'request_json', return_value=(self.raw, {})) as request:
            quotas.fetch_claude_usage(self.auth, refresh=False)
        self.assertEqual([call.args[0] for call in request.call_args_list], ['GET'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_refresh_rotates_under_pi_lock_preserving_other_credentials(self):
        self.creds['expires'] = 1
        self.path.write_text(json.dumps({'anthropic': self.creds, 'other': {'untouched': True}}))
        def refresh(method, url, **kwargs):
            self.assertTrue(Path(str(self.path) + '.lock').is_dir())
            self.assertEqual((method, url), ('POST', quotas.ANTHROPIC_TOKEN_URL))
            self.assertEqual(kwargs['body']['refresh_token'], 'fake-refresh')
            return {'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 3600}, {}
        with mock.patch.object(quotas, 'request_json', side_effect=refresh) as request:
            first = self.auth.ensure_anthropic()
            second = self.auth.ensure_anthropic()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first, second)
        data = json.loads(self.path.read_text())
        self.assertEqual(data['anthropic']['refresh'], 'rotated')
        self.assertEqual(data['anthropic']['custom'], 'retained')
        self.assertEqual(data['other'], {'untouched': True})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_failed_refresh_never_overwrites_credentials_or_leaks_body(self):
        self.creds['expires'] = 1
        self.path.write_text(json.dumps({'anthropic': self.creds}))
        before = self.path.read_bytes()
        with mock.patch.object(quotas, 'request_json', side_effect=RuntimeError('fake-access secret')):
            report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=False))
        self.assertFalse(report['ok'])
        self.assertNotIn('fake-access', json.dumps(report))
        self.assertEqual(self.path.read_bytes(), before)

    def test_lock_heartbeat_and_lost_ownership_guard(self):
        lock = Path(str(self.path) + '.lock')
        updated = threading.Event()
        original = os.utime
        def observed(path, value):
            original(path, value)
            updated.set()
        with mock.patch.object(quotas.os, 'utime', side_effect=observed):
            with quotas.auth_file_lock(self.path) as check:
                self.assertTrue(updated.wait(4), 'Heartbeat must precede Pi\'s 10s stale lease')
                check()
        self.assertFalse(lock.exists())
        # A replaced lease must block credential writes and survive our cleanup.
        with self.assertRaises(quotas.QuotaError):
            with quotas.auth_file_lock(self.path) as check:
                lock.rename(Path(self.tmp.name) / 'old-lock')
                lock.mkdir()
                check()
        self.assertTrue(lock.exists())

    def test_refresh_without_rotated_token_keeps_previous(self):
        with mock.patch.object(quotas, 'request_json', return_value=({'access_token': 'new', 'expires_in': 3600}, {})):
            self.assertEqual(quotas.refresh_anthropic('old')['refresh'], 'old')

    def test_usage_errors_are_generic(self):
        with mock.patch.object(quotas, 'request_json', side_effect=RuntimeError('fake-access secret')):
            report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
        self.assertFalse(report['ok'])
        self.assertNotIn('fake-access', json.dumps(report))

    def test_retry_after_seconds_and_http_dates_are_bounded(self):
        now = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)
        cases = [('0', 0), ('600', 600), ('999999999', 86400),
                 ('Sun, 18 Oct 2026 00:10:00 GMT', 600),
                 ('Sat, 17 Oct 2026 23:00:00 GMT', 0),
                 (None, None), ('secret', None), ('-1', None),
                 ('NaN', None), ('Infinity', None), ('1.5', None),
                 ('9' * 129, None)]
        with mock.patch.object(quotas, 'now_utc', return_value=now):
            for raw, expected in cases:
                with self.subTest(raw=raw):
                    self.assertEqual(quotas.claude_retry_after_seconds(raw), expected)

    def test_429_cli_is_sanitized_structured_and_never_retried(self):
        error = urllib.error.HTTPError(quotas.ANTHROPIC_USAGE_URL, 429, 'private',
            {'Retry-After': '900', 'private': 'secret'}, io.BytesIO(b'fake-access secret'))
        before = self.path.read_bytes()
        with mock.patch.object(quotas.urllib.request, 'urlopen', side_effect=error) as request:
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = quotas.main(['claude', '--auth-path', str(self.path), '--no-refresh', '--json'])
        self.assertEqual(code, 2)
        self.assertEqual(request.call_count, 1)
        report = json.loads(stream.getvalue())
        self.assertTrue(report['rate_limited'])
        self.assertEqual(report['retry_after_seconds'], 900)
        for secret in ('fake-access', 'secret', 'private', 'headers'):
            self.assertNotIn(secret, stream.getvalue())
        self.assertEqual(self.path.read_bytes(), before)

    def test_other_http_failures_do_not_claim_rate_limit(self):
        for status in (401, 403, 500, 503):
            error = quotas.HttpRequestError('GET', quotas.ANTHROPIC_USAGE_URL, status, 'secret')
            with mock.patch.object(quotas, 'request_json', side_effect=error):
                report = quotas.build_claude_report(argparse.Namespace(auth_path=str(self.path), no_refresh=True))
            self.assertFalse(report['ok'])
            self.assertNotIn('rate_limited', report)
            self.assertNotIn('secret', json.dumps(report))

    def test_cli_and_combined_report(self):
        with mock.patch.object(quotas, 'request_json', return_value=(self.raw, {})):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = quotas.main(['claude', '--auth-path', str(self.path), '--no-refresh', '--json'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stream.getvalue())['provider'], 'anthropic')
            args = quotas.build_parser().parse_args(['check', '--auth-path', str(self.path)])
            with mock.patch.object(quotas, 'build_codex_report', return_value={'ok': True}), \
                 mock.patch.object(quotas, 'build_copilot_report', return_value={'ok': True}):
                report = quotas.build_combined_report(args)
            self.assertTrue(report['ok'])
            self.assertIn('anthropic', report['providers'])


if __name__ == '__main__':
    unittest.main()
