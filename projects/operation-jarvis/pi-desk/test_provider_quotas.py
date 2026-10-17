"""Offline dual-provider projection/layout and isolated tmux integration tests."""
import datetime as dt
import json
import re
import shutil
import unittest
import uuid
from unittest import mock

import codex_quota
import core
import desktop
import install
import provider_quotas
import status_stream
from test_codex_quota import sample, plain_text


class ProviderQuotaTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc)
        self.value = {'codexQuota': sample(self.now), 'claudeQuota': sample(self.now)}
        self.value['claudeQuota']['weekly']['remainingPercent'] = 98
        self.value['claudeQuota']['fiveHour']['remainingPercent'] = 20

    def test_both_windows_and_resets_always_in_every_candidate(self):
        for segments in provider_quotas.label_segments(self.value, self.now):
            label = ''.join(text for text, _ in segments)
            for text in ('W:68%↻2d', '5h:91%↻48m', 'W:98%↻2d', '5h:20%↻48m'):
                self.assertIn(text, label)
            self.assertIn(('20%', codex_quota.CRITICAL), segments)
            self.assertIn(('98%', codex_quota.ACCENT), segments)

    def test_stale_unavailable_and_paused_are_independent(self):
        self.value['claudeQuota']['checkedAt'] = (self.now - dt.timedelta(seconds=901)).isoformat()
        label = ''.join(text for text, _ in provider_quotas.label_segments(self.value, self.now)[0])
        self.assertIn('Claude stale', label)
        self.assertIn('Codex W:68%', label)
        self.assertNotIn('98%', label)
        self.value['codexQuota']['fiveHourEnforced'] = False
        label = ''.join(text for text, _ in provider_quotas.label_segments(self.value, self.now)[0])
        self.assertIn('48mp', label)
        self.assertEqual(provider_quotas.normalize(None)['claudeQuota'], codex_quota.UNAVAILABLE)

    def test_extra_rows_fit_without_losing_windows_at_supported_widths(self):
        for width in (40, 60, 70, 80, 100, 184):
            rows = provider_quotas.status_rows(self.value, width, self.now)
            for row in rows:
                self.assertLessEqual(len(plain_text(row)), width)
            label = ' '.join(plain_text(row) for row in rows)
            for percent in ('68%', '91%', '98%', '20%'):
                self.assertIn(percent, label)
            self.assertEqual(label.count('↻'), 4)
        for width in (1, 10, 20):
            self.assertTrue(all(len(plain_text(row)) <= width
                                for row in provider_quotas.status_rows(self.value, width, self.now)))

    def test_projection_never_forwards_credentials_and_old_hosts_decode(self):
        public = {**self.value['claudeQuota'], 'ok': True, 'available': True, 'stale': False,
                  'token': 'private', 'planType': 'private', 'extra_usage': {'private': True}}
        payload = status_stream.snapshot({'subsystems': {'claudeQuota': public}}, self.now)
        self.assertEqual(payload['codexQuota'], codex_quota.UNAVAILABLE)
        self.assertEqual(payload['claudeQuota']['weekly']['remainingPercent'], 98)
        self.assertNotIn('private', json.dumps(payload))
        self.assertIn('provider_quotas.py', install.FILES)

    def test_no_tmux_injection_or_reset_refill(self):
        self.value['claudeQuota']['weekly']['resetAt'] = '#{unsafe}'
        self.value['claudeQuota']['fiveHour']['resetAt'] = (self.now - dt.timedelta(seconds=1)).isoformat()
        labels = provider_quotas.label_segments(self.value, self.now)
        label = ''.join(text for text, _ in labels[0])
        self.assertNotIn('unsafe', label)
        self.assertIn('98%↻?', label)
        self.assertIn('20%↻due', label)


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class DualQuotaTmuxTests(unittest.TestCase):
    def setUp(self):
        self.socket = 'pi-desk-dual-quota-test-' + uuid.uuid4().hex
        patch = mock.patch.object(core, 'SOCKET', self.socket)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: core.tmux('kill-server', check=False))
        self.name = 'viewer-' + 'b' * 32
        core.tmux('-f', '/dev/null', 'new-session', '-d', '-s', self.name, '-x', '184', '-y', '45', 'sleep 120')
        now = dt.datetime.now(dt.timezone.utc)
        self.value = {'codexQuota': sample(now), 'claudeQuota': sample(now)}
        self.value['claudeQuota']['weekly']['remainingPercent'] = 98

    def test_width_changes_keep_all_values_visible_and_panes_untouched(self):
        pane = core.tmux('list-panes', '-t', self.name, '-F', '#{pane_id}:#{pane_pid}').stdout
        previous = {}
        for width in (184, 80, 40, 120, 184):
            current = desktop.render_viewers({}, 0, previous, '',
                session_rows=f'{self.name}\t{width}\t1\t5\n', quota=self.value)
            rows = current[self.name]
            expanded = [core.tmux('display-message', '-p', '-t', self.name + ':0', '-F', row).stdout.rstrip('\n')
                        for row in rows]
            text = ' '.join(plain_text(row) for row in expanded)
            self.assertIn('68%', text)
            self.assertIn('98%', text)
            self.assertEqual(text.count('5h:'), 2)
            self.assertEqual(text.count('↻'), 4)
            for row in expanded:
                self.assertLessEqual(len(plain_text(row)), width)
            self.assertEqual(core.tmux('show-options', '-v', '-t', self.name, 'status').stdout.strip(),
                             str(len(rows)) if len(rows) > 1 else 'on')
            previous = current
        self.assertEqual(core.tmux('list-panes', '-t', self.name, '-F', '#{pane_id}:#{pane_pid}').stdout, pane)

    def test_warning_keeps_separate_row_and_idle_does_not_rewrite(self):
        rows = f'{self.name}\t80\t1\t5\n'
        first = desktop.render_viewers({}, 0, {}, 'Test warning', session_rows=rows, quota=self.value)
        self.assertEqual(first[self.name][-1], 'Test warning')
        self.assertLessEqual(len(first[self.name]), 4)
        with mock.patch.object(desktop, 'apply_status_commands') as apply:
            desktop.render_viewers({}, 0, first, 'Test warning', session_rows=rows, quota=self.value)
        apply.assert_called_once_with([])


if __name__ == '__main__':
    unittest.main()
