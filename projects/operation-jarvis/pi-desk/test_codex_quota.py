"""Read-only quota and isolated tmux tests; never contact a provider/real agent."""
import copy
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest import mock
import uuid

import backend
import codex_quota as quota
import core
import desktop
import install
import status_stream


def sample(now):
    return {'status': 'live', 'checkedAt': now.isoformat(),
            'weekly': {'remainingPercent': 68, 'resetAt': (now + dt.timedelta(days=2, hours=4)).isoformat()},
            'fiveHour': {'remainingPercent': 91, 'resetAt': (now + dt.timedelta(minutes=48)).isoformat()},
            'fiveHourEnforced': True, 'limitReached': False}


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc)
        self.quota = sample(self.now)
        self.source = {**self.quota, 'ok': True, 'available': True, 'stale': False}
        self.state = {'subsystems': {
            'pi': {'ok': True, 'stale': False, 'updatedAt': self.now.isoformat(),
                   'mobileSessions': [{'sessionID': 1, 'lifecycle': 'running'}]},
            'codexQuota': self.source}}

    def test_additive_wire_retains_old_session_contract(self):
        payload = status_stream.snapshot(self.state, self.now)
        self.assertEqual(core.valid_states(payload), {'1': 'running'})
        self.assertEqual(payload['codexQuota'], quota.normalize(self.quota, self.now))
        self.assertEqual(status_stream.extract(self.state, self.now), {'1': 'running'})

    def test_quota_failure_does_not_hide_sessions(self):
        for broken in (None, [], {'ok': False}, {'ok': True, 'available': False}):
            self.state['subsystems']['codexQuota'] = broken
            payload = status_stream.snapshot(self.state, self.now)
            self.assertEqual(core.valid_states(payload), {'1': 'running'})
            self.assertEqual(payload['codexQuota'], quota.UNAVAILABLE)

    def test_session_failure_does_not_hide_quota(self):
        for broken in (None, [], {}, {'ok': False},
                       {'ok': True, 'stale': False, 'updatedAt': {}},
                       {'ok': True, 'stale': False, 'updatedAt': self.now.isoformat(), 'mobileSessions': None}):
            self.state['subsystems']['pi'] = broken
            payload = status_stream.snapshot(self.state, self.now)
            self.assertEqual(core.valid_states(payload), {})
            self.assertEqual(payload['codexQuota']['status'], 'live')

    def test_malformed_snapshots_are_bounded(self):
        for broken in (None, [], {}, {'subsystems': None}, {'subsystems': []}):
            self.assertEqual(status_stream.snapshot(broken, self.now), {'codexQuota': quota.UNAVAILABLE})

    def test_projection_never_emits_private_or_error_fields(self):
        self.source.update(token='secret', accountID='private', lastError='private failure',
                           planType='private', creditBalance=42)
        self.source['weekly']['extra'] = 'private'
        projected = quota.project(self.source, self.now)
        encoded = json.dumps(projected)
        self.assertNotIn('private', encoded)
        self.assertNotIn('secret', encoded)
        self.assertEqual(projected['status'], 'stale')
        self.assertEqual(set(projected), {'status', 'checkedAt', 'weekly', 'fiveHour', 'fiveHourEnforced', 'limitReached'})

    def test_quota_has_independent_freshness(self):
        for seconds, expected in ((16, 'live'), (60, 'live'), (900, 'live'), (901, 'stale'), (-6, 'stale')):
            self.assertEqual(quota.normalize(self.quota, self.now + dt.timedelta(seconds=seconds))['status'], expected)
        payload = status_stream.snapshot(self.state, self.now + dt.timedelta(seconds=60))
        self.assertEqual(core.valid_states(payload), {})
        self.assertEqual(payload['codexQuota']['status'], 'live')

    def test_missing_or_invalid_timestamp_never_looks_fresh(self):
        for invalid in (None, [], 'not a date', '2026-01-01T12:00:00', 'x' * 65):
            self.quota['checkedAt'] = invalid
            self.assertEqual(quota.normalize(self.quota, self.now)['status'], 'stale')
        self.source.pop('checkedAt')
        self.source['updatedAt'] = self.now.isoformat()
        self.assertEqual(quota.project(self.source, self.now)['status'], 'live')

    def test_stale_cannot_be_renewed_by_restreaming(self):
        stale = quota.normalize(self.quota, self.now + dt.timedelta(seconds=901))
        self.assertEqual(quota.normalize(stale, self.now)['status'], 'stale')
        self.source['stale'] = True
        self.assertEqual(quota.project(self.source, self.now)['status'], 'stale')

    def test_malformed_percentages_are_not_zero_or_injected(self):
        for invalid in (True, -1, 101, float('nan'), float('inf'), 10 ** 1000, '0', '#(evil)', []):
            self.quota['weekly']['remainingPercent'] = invalid
            self.quota['fiveHour']['remainingPercent'] = None
            self.assertEqual(quota.normalize(self.quota, self.now), quota.UNAVAILABLE)
        self.quota['weekly']['remainingPercent'] = 0
        self.assertIn('W:0%', quota.labels(self.quota, self.now)[0])

    def test_display_rounding_does_not_invent_exhaustion(self):
        for value, expected in ((0, '0%'), (.2, '1%'), (29.6, '30%'), (99.8, '99%'), (100, '100%')):
            self.assertEqual(quota.percent(value), expected)

    def test_colors_and_paused_window(self):
        for value, expected in ((68, '#D183E8'), (50, '#D183E8'), (49, 'colour179'), (30, 'colour179'), (29, 'colour203'), (0, 'colour203')):
            self.quota['weekly']['remainingPercent'] = value
            self.assertEqual(quota.color(self.quota, self.now), expected)
        self.quota['weekly']['remainingPercent'] = 68
        self.quota['fiveHour']['remainingPercent'] = 0
        self.assertEqual(quota.color(self.quota, self.now), 'colour203')
        self.quota['fiveHourEnforced'] = False
        self.assertEqual(quota.color(self.quota, self.now), '#D183E8')
        self.assertIn('5h:paused', quota.labels(self.quota, self.now)[0])
        self.assertIn('5-hour: paused (not enforced)', quota.details(self.quota, self.now))
        self.quota['limitReached'] = True
        self.assertEqual(quota.color(self.quota, self.now), 'colour203')
        self.assertIn('limit reached', quota.details(self.quota, self.now))

    def test_unavailable_and_stale_do_not_show_old_percentages(self):
        for value, expected in ((None, 'unavailable'), ({'status': 'unavailable'}, 'unavailable'),
                                ({**self.quota, 'status': 'stale'}, 'stale')):
            self.assertEqual(quota.labels(value, self.now), (f' Codex {expected} ',))
            self.assertEqual(quota.color(value, self.now), 'colour245')
            self.assertNotIn('%', quota.details(value, self.now))

    def test_details_and_reset_countdown(self):
        text = quota.details(self.quota, self.now)
        self.assertIn('Weekly: 68% left, resets in 2d 4h', text)
        self.assertIn('5-hour: 91% left, resets in 48m', text)
        self.assertIn('resets in 47m', quota.details(self.quota, self.now + dt.timedelta(minutes=1)))
        self.quota['fiveHour']['resetAt'] = self.now.isoformat()
        self.assertIn('reset due; awaiting usage update', quota.details(self.quota, self.now))
        self.assertIn('91% left', quota.details(self.quota, self.now))  # Reset time never fabricates replenishment.

    def test_relative_reset_is_anchored_to_sample_not_redraw(self):
        self.quota['weekly'] = {'remainingPercent': 68, 'resetAfterSeconds': 7200}
        first = quota.normalize(self.quota, self.now)
        later = quota.normalize(first, self.now + dt.timedelta(minutes=1))
        self.assertEqual(first['weekly']['resetAt'], later['weekly']['resetAt'])
        self.assertIn('resets in 1h 59m', quota.details(later, self.now + dt.timedelta(minutes=1)))

    def test_missing_weekly_and_five_hour_are_explicit(self):
        self.quota['weekly'] = None
        self.assertIn('W:n/a', quota.labels(self.quota, self.now)[0])
        self.assertIn('5h:91% left', quota.labels(self.quota, self.now)[1])
        self.quota['fiveHourEnforced'] = False
        self.assertEqual(quota.normalize(self.quota, self.now), quota.UNAVAILABLE)
        self.quota['fiveHourEnforced'] = True
        self.quota['weekly'] = {'remainingPercent': 68}
        self.quota['fiveHour'] = None
        self.assertIn('5h:n/a', quota.labels(self.quota, self.now)[0])
        self.assertIn('5-hour: unavailable', quota.details(self.quota, self.now))

    def test_source_collector_uses_one_existing_state_read(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(self.state).encode()
        with mock.patch.object(status_stream.urllib.request, 'urlopen', return_value=response) as request:
            result = status_stream.collect()
        request.assert_called_once_with(status_stream.URL, timeout=4)
        self.assertEqual(result['codexQuota']['status'], 'live')
        with mock.patch.object(status_stream.urllib.request, 'urlopen', side_effect=OSError):
            self.assertEqual(status_stream.collect(), {'codexQuota': quota.UNAVAILABLE})

    def test_feed_supports_legacy_and_extended_streams_and_clears_on_disconnect(self):
        read_fd, write_fd = os.pipe()
        process = mock.Mock(stdout=os.fdopen(read_fd, 'rb'))
        with mock.patch.object(core, 'load', return_value=backend.Backend(mode='local')):
            feed = core.StatusFeed()
        try:
            with mock.patch.object(core.subprocess, 'Popen', return_value=process), \
                 mock.patch.object(core.time, 'monotonic', return_value=100) as clock:
                feed.poll()
                for payload, expected in ((status_stream.snapshot(self.state, self.now), 'live'),
                                          ({'1': 'idle'}, 'unavailable'),
                                          ({'1': 'running', 'codexQuota': []}, 'unavailable')):
                    os.write(write_fd, (json.dumps(payload) + '\n').encode())
                    self.assertEqual(feed.poll(), core.valid_states(payload))
                    self.assertEqual(feed.quota['status'], expected)
                os.write(write_fd, (json.dumps(status_stream.snapshot(self.state, self.now)) + '\n').encode())
                feed.poll()
                clock.return_value = 113
                self.assertEqual(feed.poll(), {})
                self.assertEqual(feed.quota, quota.UNAVAILABLE)
                self.assertIn('Local status disconnected', feed.connection)
        finally:
            feed.close()
            os.close(write_fd)

    def test_feed_rechecks_quota_age_without_new_sample(self):
        with mock.patch.object(core, 'load', return_value=backend.Backend(mode='local')):
            feed = core.StatusFeed()
        feed.process = mock.Mock(stdout=mock.Mock())
        feed.quota = sample(self.now - dt.timedelta(seconds=901))
        feed.received = 100
        with mock.patch.object(core.select, 'select', return_value=([], [], [])), \
             mock.patch.object(core.time, 'monotonic', return_value=100):
            feed.poll()
        self.assertEqual(feed.quota['status'], 'stale')
        feed.process = None

    def test_every_responsive_width_preserves_navigation(self):
        for width in range(1, 221):
            for count in (1, 2, 3):
                for selected in (1, 5, 10):
                    plain = []
                    for value in (self.quota, quota.UNAVAILABLE, {**self.quota, 'status': 'stale'}):
                        bar = desktop.responsive_selector({}, width, count, selected, quota=value)
                        plain.append(re.sub(r'#\[[^\]]*\]', '', bar).replace('%%', '%'))
                        self.assertIn(f'range=user|{selected},', bar)
                        # Quota may not reduce the number of session tabs.
                        original = desktop.responsive_selector({}, width, count, selected)
                        self.assertEqual(re.findall(r'range=user\|(\d+),', original),
                                         re.findall(r'range=user\|(\d+),', bar))
                    self.assertTrue(all(len(text) <= width for text in plain), (width, plain))

    def test_footer_prioritizes_quota_before_hints_and_shortens(self):
        wide = desktop.responsive_selector({}, 184, 3, 5, quota=self.quota).replace('%%', '%')
        self.assertIn('W:68% · 5h:91% left', wide)
        self.assertIn('F10 Restart', wide)
        compact = desktop.responsive_selector({}, 80, 1, 5, quota=self.quota).replace('%%', '%')
        self.assertIn('W:68% · 5h:91% left', compact)
        self.assertNotIn('F10', compact)
        weekly = desktop.responsive_selector({}, 70, 1, 5, quota=self.quota).replace('%%', '%')
        self.assertIn('W:68% left', weekly)
        self.assertNotIn('5h:', weekly)
        tiny = desktop.responsive_selector({}, 40, 1, 5, quota=self.quota)
        self.assertNotIn('range=user|codex', tiny)

    def test_installer_includes_shared_module(self):
        self.assertIn('codex_quota.py', install.FILES)


class QuotaClickTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc)
        self.quota = sample(self.now)

    def test_detail_is_client_scoped_and_does_not_change_focus(self):
        results = [mock.Mock(stdout='123\t/dev/ttys001\n456\t/dev/ttys002\n'),
                   mock.Mock(stdout=json.dumps(self.quota)), mock.Mock()]
        with mock.patch.object(desktop, 'tmux', side_effect=results) as calls, \
             mock.patch.object(desktop, 'choose') as choose:
            self.assertEqual(desktop.dispatch(['click', 'codex', '456']), 0)
        choose.assert_not_called()
        last = calls.call_args.args
        self.assertEqual(last[:5], ('display-message', '-c', '/dev/ttys002', '-d', '8000'))
        self.assertEqual(last[5], '-l')
        self.assertIn('Weekly: 68% left', last[6])
        self.assertFalse(any('send-keys' in call.args or 'select-pane' in call.args for call in calls.call_args_list))

    def test_vanished_client_is_noop(self):
        with mock.patch.object(desktop, 'tmux', return_value=mock.Mock(stdout='123\t/dev/ttys001\n')) as calls:
            self.assertEqual(desktop.dispatch(['click', 'codex', '456']), 0)
        self.assertEqual(calls.call_count, 1)

    def test_failures_never_open_run_shell_view_mode(self):
        for invalid in ('not-pid', '123'):
            with mock.patch.object(desktop, 'tmux', side_effect=RuntimeError('gone')):
                self.assertEqual(desktop.dispatch(['click', 'codex', invalid]), 0)

    def test_corrupt_cache_cannot_inject_tmux_formats(self):
        for raw in ('{invalid', '#(touch unsafe)', 'x' * 4097,
                    json.dumps({'status': 'live', 'checkedAt': '#(evil)', 'weekly': {'remainingPercent': '#{evil}'}})):
            with mock.patch.object(desktop, 'tmux', side_effect=[
                    mock.Mock(stdout='123\tclient-one\n'), mock.Mock(stdout=raw), mock.Mock()]) as calls:
                self.assertEqual(desktop.dispatch(['click', 'codex', '123']), 0)
            self.assertEqual(calls.call_args.args[-1], 'Codex usage unavailable')


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class QuotaTmuxTests(unittest.TestCase):
    def setUp(self):
        self.socket = 'pi-desk-quota-test-' + uuid.uuid4().hex
        patch = mock.patch.object(core, 'SOCKET', self.socket)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: core.tmux('kill-server', check=False))
        self.name = 'viewer-' + 'a' * 32
        core.tmux('-f', '/dev/null', 'new-session', '-d', '-s', self.name, '-x', '184', '-y', '45', 'sleep 120')
        core.tmux('set-option', '-t', self.name, '@pi-desk-session', '5', ';',
                  'set-option', '-t', self.name, '@pi-desk-capacity', '3', ';',
                  'set-option', '-t', self.name, '@pi-desk-first', '4', ';',
                  'set-option', '-t', self.name, '@pi-desk-end', '6')
        self.quota = sample(dt.datetime.now(dt.timezone.utc))

    def expanded(self, bar):
        return core.tmux('display-message', '-p', '-t', self.name + ':0', '-F', bar).stdout.rstrip('\n')

    def test_actual_tmux_formats_fit_and_preserve_click_ranges(self):
        for width in (1, 2, 3, 4, 20, 30, 40, 60, 70, 80, 90, 99, 100, 105, 110, 120, 130, 158, 173, 184):
            bar = desktop.responsive_selector({'5': 'running'}, width, 3, 5, quota=self.quota)
            expanded = self.expanded(bar)
            self.assertLessEqual(len(re.sub(r'#\[[^\]]*\]', '', expanded)), width)
            self.assertIn('range=user|5,', expanded)
        wide = self.expanded(desktop.responsive_selector({}, 184, 3, 5, quota=self.quota))
        self.assertIn('range=user|codex,fg=#D183E8', wide)
        self.assertIn('W:68% · 5h:91% left', wide)
        self.assertIn('range=user|5,bg=#8D4CA3,fg=#ffffff,bold', wide)

    def test_legacy_dynamic_footer_is_valid_tmux_format(self):
        # client_width is zero without an attached client. Substitute the same
        # terminal width expression for deterministic expansion on this socket.
        bar = desktop.selector({}, quota=self.quota)
        for width in (84, 100, 105, 110, 130, 158, 173, 184):
            expanded = self.expanded(bar.replace('#{client_width}', str(width)))
            plain = re.sub(r'#\[[^\]]*\]', '', expanded)
            self.assertLessEqual(len(plain), width, (width, plain))
            self.assertNotIn('#{?', plain)
        self.assertIn('W:68%', self.expanded(bar.replace('#{client_width}', '184')))

    def test_real_status_and_mouse_click_keep_panes_untouched(self):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))
        child = None
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'click.py'
            helper.write_text(f'import sys\nsys.path.insert(0, {str(desktop.ROOT)!r})\n'
                              f'import core, desktop\ncore.SOCKET = {self.socket!r}\n'
                              'raise SystemExit(desktop.dispatch(sys.argv[1:]))\n')
            command = shlex.join([sys.executable, str(helper), 'click']) + ' "#{mouse_status_range}" "#{client_pid}"'
            core.tmux('set-option', '-g', 'mouse', 'on', ';',
                      'set-option', '-g', 'status-position', 'top', ';',
                      'set-option', '-g', 'status-format[0]', desktop.responsive_selector({}, 184, 3, 5, quota=self.quota), ';',
                      'set-option', '-g', desktop.QUOTA_OPTION, json.dumps(self.quota), ';',
                      'bind-key', '-n', 'MouseDown1Status', 'run-shell', '-b', command)
            before = core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}:#{pane_in_mode}:#{pane_active}').stdout
            try:
                child = subprocess.Popen(['tmux', '-L', self.socket, 'attach-session', '-t', '=' + self.name],
                    stdin=slave, stdout=slave, stderr=slave,
                    env=dict(backend.clean_environment(), TERM='xterm-256color'))
                output = b''
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and b'5h:91%' not in output:
                    if select.select([master], [], [], .1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(b'W:68%', output)  # Literal %, not strftime deletion/%%.
                self.assertIn(b'5h:91%', output)
                self.assertNotIn(b'68%%', output)
                # Quota starts at column 129 at this width; SGR click its label.
                os.write(master, b'\x1b[<0;133;1M\x1b[<0;133;1m')
                deadline = time.monotonic() + 2
                clicked = b''
                while time.monotonic() < deadline and b'Weekly: 68% left' not in clicked:
                    if select.select([master], [], [], .1)[0]:
                        clicked += os.read(master, 65536)
                self.assertIn(b'Weekly: 68% left', clicked)
                self.assertIn(b'5-hour: 91% left', clicked)
                self.assertEqual(core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}:#{pane_in_mode}:#{pane_active}').stdout, before)
            finally:
                if child is not None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=2)
                os.close(master)
                os.close(slave)

    def test_reset_only_change_is_published_without_rewriting_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            feed = mock.Mock(backend=mock.Mock(host='test'), connection='Mac connected · Session status live')
            updated = copy.deepcopy(self.quota)
            updated['weekly']['resetAt'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).isoformat()
            samples = iter((self.quota, updated, updated))
            def poll():
                feed.quota = next(samples)
                return {'5': 'idle'}
            feed.poll.side_effect = poll
            health = mock.Mock()
            health.poll.return_value = ()
            stop = mock.Mock()
            stop.is_set.side_effect = [False, False, False, True]
            clock = [0]
            stop.wait.side_effect = lambda delay: clock.__setitem__(0, clock[0] + delay)
            writes = []
            def send(*args, **kwargs):
                if args[0] == 'source-file':
                    writes.append(Path(args[1]).read_text())
                return core.tmux(*args, **kwargs)
            with mock.patch.object(desktop, 'STATE', Path(directory)), \
                 mock.patch.object(desktop, 'StatusFeed', return_value=feed), \
                 mock.patch.object(desktop, 'HealthMonitor', return_value=health), \
                 mock.patch.object(desktop.time, 'monotonic', side_effect=lambda: clock[0]), \
                 mock.patch.object(desktop, 'tmux', side_effect=send) as calls:
                desktop.watch_status(stop)
            self.assertEqual(len(writes), 2)
            self.assertIn('status-format[0]', writes[0])
            self.assertIn(desktop.QUOTA_OPTION, writes[1])
            self.assertNotIn('status-format', writes[1])
            self.assertEqual(sum('list-sessions' in call.args for call in calls.call_args_list), 3)
            self.assertEqual(len(calls.call_args_list), 5)

    def test_batched_quota_updates_keep_one_row_and_all_pane_identities(self):
        second = 'viewer-' + 'b' * 32
        core.tmux('new-session', '-d', '-s', second, '-x', '70', '-y', '45', 'sleep 120', ';',
                  'set-option', '-t', second, '@pi-desk-session', '1', ';',
                  'set-option', '-t', second, '@pi-desk-capacity', '1')
        before = core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').stdout
        rows = core.tmux('list-sessions', '-F', desktop.VIEWER_STATUS_FORMAT).stdout
        current = desktop.render_viewers({}, False, {}, '', session_rows=rows,
            global_rows=(desktop.selector({}, quota=self.quota), ''), quota=self.quota,
            quota_payload=json.dumps(self.quota))
        self.assertEqual(core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').stdout, before)
        self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), 'on')
        self.assertEqual(core.tmux('show-options', '-gv', 'status-format[1]').stdout.strip(), '')
        self.assertIn('5h:91%', current[self.name][0])
        self.assertNotIn('5h:', current[second][0])
        with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as calls:
            desktop.render_viewers({}, False, current, '', session_rows=rows, quota=self.quota)
        calls.assert_not_called()
        self.assertEqual(json.loads(core.tmux('show-options', '-gv', desktop.QUOTA_OPTION).stdout), self.quota)


if __name__ == '__main__':
    unittest.main()
