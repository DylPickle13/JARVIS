"""Isolated tests: no real Mac sessions, household actions or private state."""
import datetime as dt
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest import mock
import uuid

import backend
import cli
import core
import install
import desktop
import navigate
import native_navigation
import health
import install_pi
import status_stream


class ViewerCleanupTests(unittest.TestCase):
    def test_normal_exit_does_not_terminate_client(self):
        child = mock.Mock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with mock.patch.object(desktop.subprocess, 'Popen', return_value=child):
            self.assertEqual(desktop.attach_viewer('group-1'), 0)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_interruption_reaps_only_owned_client(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = [KeyboardInterrupt(), 0]
        with mock.patch.object(desktop.subprocess, 'Popen', return_value=child):
            with self.assertRaises(KeyboardInterrupt):
                desktop.attach_viewer('group-1')
        child.terminate.assert_called_once()
        child.kill.assert_not_called()

    def test_stopped_client_is_killed_after_bounded_wait(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = [SystemExit(143), subprocess.TimeoutExpired('tmux', 2), 0]
        with mock.patch.object(desktop.subprocess, 'Popen', return_value=child):
            with self.assertRaises(SystemExit):
                desktop.attach_viewer('group-1')
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args, mock.call(timeout=2))


class ClosedDisplayRecoveryTests(unittest.TestCase):
    def recover(self, rows, current='?? tmux -L pi-desk attach-session -t =group-1'):
        results = [mock.Mock(stdout=rows), mock.Mock(stdout='p42\nn/dev/ttys036\n'),
                   mock.Mock(stdout=current)]
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core.subprocess, 'run', side_effect=results), \
                mock.patch.object(core.os, 'open', return_value=99) as opened, \
                mock.patch.object(core.os, 'close') as closed, \
                mock.patch.object(core.termios, 'tcflush') as flush:
            core.recover_closed_displays()
        return opened, closed, flush

    def test_flushes_only_closed_display_output(self):
        opened, closed, flush = self.recover('42 ?? tmux -L pi-desk attach-session -t =group-1')
        self.assertEqual(opened.call_args.args[0], '/dev/ttys036')
        flush.assert_called_once_with(99, core.termios.TCOFLUSH)
        closed.assert_called_once_with(99)

    def test_recognizes_private_viewer_targets(self):
        command = 'tmux -L pi-desk attach-session -t =viewer-' + 'a' * 32
        opened, closed, flush = self.recover('42 ?? ' + command, '?? ' + command)
        opened.assert_called_once()
        flush.assert_called_once_with(99, core.termios.TCOFLUSH)
        closed.assert_called_once_with(99)

    def test_recognizes_closed_vscode_viewer(self):
        command = 'tmux -L pi-desk -T hyperlinks attach-session -t =viewer-' + 'a' * 32
        opened, closed, flush = self.recover('42 ?? ' + command, '?? ' + command)
        opened.assert_called_once()
        flush.assert_called_once_with(99, core.termios.TCOFLUSH)
        closed.assert_called_once_with(99)

    def test_ignores_live_displays_and_agent_clients(self):
        for row in ('42 ttys036 tmux -L pi-desk attach-session -t =group-1',
                    '42 ?? tmux -L jarvis-mobile attach-session -t =jarvis-ios',
                    '42 ?? tmux -L pi-desk new-session -d -s group-1'):
            with self.subTest(row=row):
                opened, _, flush = self.recover(row)
                opened.assert_not_called()
                flush.assert_not_called()

    def test_rechecks_terminal_before_flush(self):
        opened, _, flush = self.recover(
            '42 ?? tmux -L pi-desk attach-session -t =group-1',
            'ttys036 tmux -L pi-desk attach-session -t =group-1')
        opened.assert_not_called()
        flush.assert_not_called()

    def test_probe_failure_is_nonfatal(self):
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ps', 3)):
            core.recover_closed_displays()


class WorkspaceTimeoutTests(unittest.TestCase):
    def test_timeout_is_actionable_even_for_unchecked_queries(self):
        for check in (True, False):
            with self.subTest(check=check), mock.patch.object(
                    core.subprocess, 'run',
                    side_effect=subprocess.TimeoutExpired('tmux', 8)):
                with self.assertRaisesRegex(RuntimeError, 'workspace is not responding'):
                    core.tmux('show-options', '-gv', '@pi-desk-last', check=check)

    def test_cli_reports_workspace_failure_without_traceback(self):
        with mock.patch.object(sys, 'argv', ['pi-desk']), \
                mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                mock.patch.object(desktop, 'main', side_effect=RuntimeError('workspace unavailable')), \
                mock.patch('builtins.print') as output:
            self.assertEqual(cli.main(), 1)
            output.assert_called_once_with('Pi Desk: workspace unavailable', file=sys.stderr)


class StatusTests(unittest.TestCase):
    def setUp(self):
        transport = mock.patch.object(core, 'load', return_value=backend.Backend())
        transport.start()
        self.addCleanup(transport.stop)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.data = {'stale': False, 'subsystems': {'pi': {
            'ok': True, 'stale': False, 'updatedAt': self.now.isoformat(),
            'mobileSessions': [{'sessionID': 1, 'lifecycle': 'idle'}]}}}

    def test_fresh(self):
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_stale_and_future(self):
        for delta in (16, -6):
            self.assertEqual(status_stream.extract(self.data, self.now+dt.timedelta(seconds=delta)), {})

    def test_unrelated_backend_staleness_does_not_hide_pi(self):
        self.data['stale'] = True
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_pi_stale_or_unhealthy(self):
        for field, value in (('stale', True), ('ok', False)):
            with self.subTest(field=field):
                pi = dict(self.data['subsystems']['pi'])
                pi[field] = value
                data = {'stale': False, 'subsystems': {'pi': pi}}
                self.assertEqual(status_stream.extract(data, self.now), {})

    def test_missing_timestamp(self):
        del self.data['subsystems']['pi']['updatedAt']
        self.assertEqual(status_stream.extract(self.data, self.now), {})

    def test_no_private_payload_or_invalid_rows(self):
        rows = self.data['subsystems']['pi']['mobileSessions']
        rows[0]['private'] = 'not emitted'
        rows += [None, {'sessionID': True, 'lifecycle': 'idle'},
                 {'sessionID': 11, 'lifecycle': 'idle'}, {'sessionID': 2, 'lifecycle': []}]
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_state_validation(self):
        self.assertEqual(core.valid_states({'1': 'running', '2': [], '11': 'idle'}), {'1': 'running'})
        self.assertEqual(core.valid_states([]), {})

    def test_feed_retries_failed_start(self):
        feed = core.StatusFeed()
        with mock.patch.object(core.subprocess, 'Popen', side_effect=OSError) as start:
            with mock.patch.object(core.time, 'monotonic', return_value=100):
                self.assertEqual(feed.poll(), {})
                feed.poll()
                self.assertEqual(start.call_count, 1)
            with mock.patch.object(core.time, 'monotonic', return_value=104):
                feed.poll()
                self.assertEqual(start.call_count, 2)

    def test_stream_feedback_and_watchdog(self):
        read_fd, write_fd = os.pipe()
        process = mock.Mock(stdout=os.fdopen(read_fd, 'rb'))
        feed = core.StatusFeed()
        try:
            with mock.patch.object(core.subprocess, 'Popen', return_value=process), \
                 mock.patch.object(core.time, 'monotonic', return_value=100) as clock:
                feed.poll()
                self.assertEqual(feed.connection, 'Connecting to Mac…')
                for payload, expected, label in (
                    (b'{}\n', {}, 'status unavailable'),
                    (b'{"1":"running"}\n', {'1': 'running'}, 'status live'),
                    (b'[]\n', {}, 'Invalid status'),
                ):
                    os.write(write_fd, payload)
                    self.assertEqual(feed.poll(), expected)
                    self.assertIn(label, feed.connection)
                clock.return_value = 113
                feed.poll()
                self.assertIn('SSH disconnected', feed.connection)
        finally:
            feed.close()
            os.close(write_fd)


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class PaneRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.socket = mock.patch.object(core, 'SOCKET', 'pi-desk-test-'+uuid.uuid4().hex)
        self.socket.start()
        self.command = mock.patch.object(core, 'connection_command', return_value='sleep 120')
        self.command.start()

    def tearDown(self):
        core.tmux('kill-server', check=False)
        self.command.stop()
        self.socket.stop()

    def tags(self, target='group-1:0'):
        return core.tmux('list-panes', '-t', target, '-F', '#{@pi-desk-session}').stdout.splitlines()

    def test_batched_configure_repairs_bindings_and_preserves_status(self):
        core.ensure_group('1')
        identity = core.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_id}:#{pane_pid}').stdout
        with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as commands:
            desktop.configure()
            self.assertEqual(commands.call_count, 4)
        with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as commands:
            desktop.configure()
            self.assertEqual(commands.call_count, 1)
        with mock.patch.object(desktop, 'configuration_version', return_value='changed'), \
                mock.patch.object(desktop, 'tmux', wraps=core.tmux) as commands:
            desktop.configure()
            self.assertEqual(commands.call_count, 4)
        self.assertIn('PI-DESK', core.tmux('show-options', '-gv', 'status-format[0]').stdout)
        self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), '2')
        for warning in ('', desktop.health_line('SSH disconnected', ())):
            rows = (desktop.selector({'1': 'idle'}), warning)
            desktop.render_status(rows)
            core.tmux('unbind-key', '-T', 'root', 'C-Right')
            with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as commands:
                desktop.configure(force=True)
                self.assertEqual(commands.call_count, 3)
            for index, row in enumerate(rows):
                self.assertEqual(core.tmux('show-options', '-gv', f'status-format[{index}]').stdout.rstrip('\n'), row)
            self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), '2' if warning else 'on')
            for table, key in (('root', 'C-Left'), ('root', 'C-Right'),
                               ('prefix', 'Left'), ('prefix', 'Right'),
                               ('prefix', 'C-Left'), ('prefix', 'C-Right')):
                lines = core.tmux('list-keys', '-T', table).stdout.splitlines()
                self.assertTrue(any(line.split()[3] == key and 'if-shell' in line
                                    for line in lines))
        self.assertEqual(identity, core.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_id}:#{pane_pid}').stdout)

    def test_create_and_idempotent(self):
        core.ensure_group('1')
        core.ensure_group('1')
        self.assertEqual(self.tags(), ['1', '2', '3'])

    def test_missing_middle_restored_in_order(self):
        core.ensure_group('1')
        core.tmux('kill-pane', '-t', 'group-1:0.1')
        core.ensure_group('1')
        self.assertEqual(self.tags(), ['1', '2', '3'])

    def test_dead_pane_respawned(self):
        core.ensure_group('1')
        core.tmux('respawn-pane', '-k', '-t', 'group-1:0.1', 'exit 0')
        time.sleep(0.1)
        core.ensure_group('1')
        dead = core.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_dead}').stdout.splitlines()
        self.assertEqual(dead, ['0', '0', '0'])

    def test_persistent_selector_focus_for_all_sessions(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(desktop, 'STATE', Path(directory)):
            for number in range(1, 11):
                key, _ = core.session_group(number)
                group = desktop.choose(number)
                self.assertEqual(group, 'group-'+key)
                focused = core.tmux('display-message', '-p', '-t', group,
                                    '#{@pi-desk-session}').stdout.strip()
                self.assertEqual(focused, str(number))
                self.assertEqual(desktop.last_session(), number)
            self.assertEqual(self.tags('group-4:0'), ['10'])
            self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), 'on')
            self.assertEqual(core.tmux('show-options', '-gv', 'status-position').stdout.strip(), 'top')


    def test_warning_row_reclaims_terminal_height_and_recovers(self):
        core.ensure_group('1')
        before = core.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_id}:#{pane_pid}').stdout
        heights = []
        master, slave = os.openpty()
        viewer = subprocess.Popen(['tmux', '-L', core.SOCKET, 'attach-session', '-t', 'group-1'],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env=dict(backend.clean_environment(), TERM='xterm-256color'))
        try:
            for _ in range(50):
                if core.tmux('list-clients').stdout.strip():
                    break
                time.sleep(.02)
            self.assertTrue(core.tmux('list-clients').stdout.strip())
            for warning, expected in (('', 'on'), ('Warning: disconnected', '2'), ('', 'on')):
                desktop.render_status((desktop.selector({}), warning))
                self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), expected)
                time.sleep(.05)
                heights.append(int(core.tmux('display-message', '-p', '-t', 'group-1:0.0', '#{pane_height}').stdout))
        finally:
            viewer.terminate()
            os.close(master)
            os.close(slave)
            try:
                viewer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                viewer.kill()  # Only the isolated test viewer, never a real client.
                viewer.wait(timeout=3)
        self.assertEqual(heights[0], heights[1] + 1)
        self.assertEqual(heights[0], heights[2])
        self.assertEqual(before, core.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_id}:#{pane_pid}').stdout)


    def test_lightweight_navigation_all_groups_and_bounds(self):
        for key in core.GROUPS:
            core.ensure_group(key)
        before = core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').stdout
        master, slave = os.openpty()
        viewer = subprocess.Popen(['tmux', '-L', core.SOCKET, 'attach-session', '-t', 'group-1'],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env=dict(backend.clean_environment(), TERM='xterm-256color'))
        def drain():
            try:
                while os.read(master, 65536):
                    pass
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
        try:
            for _ in range(50):
                if core.tmux('list-clients').stdout.strip():
                    break
                time.sleep(.02)
            with tempfile.TemporaryDirectory() as directory:
                expected = 1
                for direction in [1] * 11 + [-1] * 11:
                    navigate.step(direction, viewer.pid, socket=core.SOCKET, state=directory)
                    expected = max(1, min(10, expected + direction))
                    self.assertEqual((Path(directory)/'last-session').read_text().strip(), str(expected))
                    actual = core.tmux('list-clients', '-F', '#{@pi-desk-session}').stdout.strip()
                    self.assertEqual(actual, str(expected))
                with self.assertRaises(ValueError):
                    navigate.step(1, -999, socket=core.SOCKET, state=directory)
            native_navigation.install(core.tmux)
            client_name = core.tmux('list-clients', '-F', '#{client_name}').stdout.strip()
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(desktop, 'STATE', Path(directory)):
                expected = 1
                for direction in [1] * 11 + [-1] * 11:
                    key = 'C-Right' if direction == 1 else 'C-Left'
                    core.tmux('send-keys', '-K', '-c', client_name, key)
                    expected = max(1, min(10, expected + direction))
                    for _ in range(30):
                        actual = core.tmux('list-clients', '-F', '#{@pi-desk-session}').stdout.strip()
                        if actual == str(expected):
                            break
                        time.sleep(.01)
                    self.assertEqual(actual, str(expected))
                    self.assertEqual(desktop.last_session(), expected)
                    desktop.persist_selection()
                    self.assertEqual((Path(directory)/'last-session').read_text().strip(), str(expected))
            self.assertEqual(before, core.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}').stdout)
            fallback = ('run-shell -b \'python3 "$HOME/.local/share/pi-desk/navigate.py" '
                        '1 "#{client_pid}"\'')
            command = native_navigation.legacy_binding(1).replace(fallback, 'set-option -g @fallback yes')
            core.tmux('bind-key', '-T', 'root', 'C-Right', command)
            core.tmux('kill-pane', '-t', 'group-1:0.1')
            core.tmux('send-keys', '-K', '-c', client_name, 'C-Right')
            self.assertEqual(core.tmux('show-options', '-gv', '@fallback').stdout.strip(), 'yes')
            self.assertEqual(core.tmux('list-clients', '-F', '#{@pi-desk-session}').stdout.strip(), '1')
        finally:
            viewer.terminate()
            os.close(slave)
            os.close(master)
            try:
                viewer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                viewer.kill()
                viewer.wait(timeout=3)


class DesktopTests(unittest.TestCase):
    def test_viewer_sets_terminal_tab_title(self):
        config = (Path(__file__).resolve().parent / 'config/tmux.conf').read_text()
        self.assertIn('set -g set-titles on', config)
        self.assertIn("set -g set-titles-string 'pi-desk'", config)

    def test_vscode_viewer_advertises_hyperlinks(self):
        self.assertEqual(desktop.viewer_attach_command('viewer-test', {'TERM_PROGRAM': 'vscode'}),
                         ['tmux', '-L', desktop.SOCKET, '-T', 'hyperlinks',
                          'attach-session', '-t', '=viewer-test'])

    def test_other_viewers_keep_terminal_auto_detection(self):
        for program in ('Apple_Terminal', 'foot', ''):
            command = desktop.viewer_attach_command('viewer-test', {'TERM_PROGRAM': program})
            self.assertNotIn('-T', command)
            self.assertEqual(command[-3:], ['attach-session', '-t', '=viewer-test'])

    def test_all_click_targets(self):
        bar = desktop.selector({'1': 'running'})
        for n in range(1, 11):
            self.assertIn(f'range=user|{n},', bar)
        for text in ('fg=colour77', 'F10', '#{session_name}', '#{@pi-desk-session}',
                     '#[align=right,norange', 'Ctrl + ←/→ Switch'):
            self.assertIn(text, bar)

    def test_quiet_selector_groups(self):
        bar = desktop.selector({})
        self.assertIn(' PI-DESK ', bar)
        self.assertIn('fg=#D183E8', bar)
        self.assertIn('fg=#{?#{==:#{@pi-desk-session},1},##D183E8,#{?', bar)
        self.assertIn(',##B28CBD,colour252}}', bar)
        self.assertNotIn('bg=#{', bar)
        self.assertEqual(bar.count(' │ '), 3)
        for n in range(1, 11):
            self.assertIn(f']{n:02d}#[nobold,nounderscore] ', bar)
        for n in (3, 6, 9):
            tab = bar.split(f'range=user|{n},', 1)[1].split('range=user|', 1)[0]
            self.assertIn('#[norange,bg=#1e1e1e,nobold,nounderscore]#[fg=colour238] │ ', tab)
        self.assertNotIn('blink', bar)

    def test_session_dividers_are_heavy_and_neutral(self):
        config = (Path(__file__).resolve().parent / 'config/tmux.conf').read_text()
        self.assertIn('set -g pane-border-lines heavy', config)
        self.assertIn('set -g pane-border-indicators off', config)
        for option in ('pane-border-style', 'pane-active-border-style'):
            self.assertIn(f"set -g {option} 'fg=#8a8a8a,bg=#1e1e1e'", config)

    def test_border_grey_meets_vscode_default_contrast_threshold(self):
        config = (Path(__file__).resolve().parent / 'config/tmux.conf').read_text()
        match = re.search(r"set -g pane-border-style 'fg=#([0-9a-f]{6}),bg=#([0-9a-f]{6})'", config)
        self.assertIsNotNone(match)

        def luminance(color):
            channels = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        foreground, background = (luminance(color) for color in match.groups())
        self.assertGreaterEqual((foreground + 0.05) / (background + 0.05), 4.5)

    def test_all_session_titles_are_white_with_active_purple_badge(self):
        config = (Path(__file__).resolve().parent / 'config/tmux.conf').read_text()
        self.assertIn("set -g pane-border-format '#[default] #[fg=##ffffff,"
                      "bg=#{?pane_active,##8D4CA3,##1e1e1e},#{?pane_active,bold,nobold}]"
                      " Session #{@pi-desk-session} #[default] '", config)

    def test_white_active_title_meets_vscode_default_contrast_threshold(self):
        config = (Path(__file__).resolve().parent / 'config/tmux.conf').read_text()
        match = re.search(r'bg=#\{\?pane_active,##([0-9A-Fa-f]{6}),', config)
        self.assertIsNotNone(match)
        channels = [int(match.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        # xterm can darken low-contrast white text even when tmux sends white.
        self.assertGreaterEqual(1.05 / (luminance + 0.05), 4.5)

    def test_only_working_indicators_rotate_without_dimming(self):
        states = {'1': 'running', '2': 'compacting', '3': 'idle'}
        start = desktop.selector(states)
        next_frame = desktop.selector(states, frame=2)
        self.assertEqual(start.replace('nounderscore]⠋', 'nounderscore]⠹', 1)
                         .replace('nounderscore]⠋', 'nounderscore]⠏', 1), next_frame)
        self.assertIn('fg=#FF7A00,bg=#1e1e1e,nobold,nounderscore]⠋', start)
        for state in ('idle', 'new', 'offline', 'unknown', 'unrecognized'):
            values = {'1': state}
            self.assertEqual(desktop.selector(values), desktop.selector(values, frame=2))
        self.assertEqual(desktop.selector({}), desktop.selector({}, frame=2))

    def test_running_rotates_quickly_and_compaction_reverses_more_slowly(self):
        self.assertEqual(desktop.ANIMATION_SECONDS, 0.25)
        for time, expected in ((0, 0), (.25, 1), (.5, 2), (.75, 3), (1, 4)):
            self.assertEqual(desktop.animation_frame(time), expected)
        self.assertEqual(desktop.SPINNER_FRAMES, tuple('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'))
        for n in range(40):  # Two complete compacting cycles and wrap-around.
            running = desktop.status_indicator('running', n, '#1e1e1e')
            compacting = desktop.status_indicator('compacting', n, '#1e1e1e')
            self.assertIn('nounderscore]' + desktop.SPINNER_FRAMES[n % 10], running)
            self.assertIn('nounderscore]' + desktop.SPINNER_FRAMES[-(n // 2) % 10], compacting)

    def test_ascii_and_static_spinner_options(self):
        with mock.patch.dict(os.environ, PI_DESK_SPINNER='ascii'):
            for n, glyph in enumerate(desktop.ASCII_SPINNER_FRAMES):
                self.assertIn('nobold,nounderscore]' + glyph, desktop.status_indicator('running', n, '#1e1e1e'))
        with mock.patch.dict(os.environ, PI_DESK_SPINNER='off'):
            self.assertFalse(desktop.working({'1': 'running'}))
            self.assertEqual(desktop.selector({'1': 'running'}), desktop.selector({'1': 'running'}, frame=2))
            self.assertIn('nobold,nounderscore]●', desktop.status_indicator('compacting', 2, '#1e1e1e'))
        self.assertTrue(desktop.working({'10': 'compacting'}))
        self.assertFalse(desktop.working({'1': 'unknown'}))

    def test_static_state_icons_are_distinct_and_unknown_is_explicit(self):
        icons = {'idle': '●', 'new': '○', 'offline': '×', 'unknown': '?',
                 'unrecognized': '?', None: '?'}
        for state, glyph in icons.items():
            for frame in (0, 1, 9, 10, 39):
                with self.subTest(state=state, frame=frame):
                    color = desktop.COLORS.get(state, desktop.COLORS['unknown'])
                    self.assertEqual(desktop.status_indicator(state, frame, '#1e1e1e'),
                                     f'#[fg=colour{color},bg=#1e1e1e,nobold,nounderscore]{glyph} ')

    def test_ascii_icons_and_reverse_spinner_remain_single_ascii_characters(self):
        with mock.patch.dict(os.environ, PI_DESK_SPINNER='ascii'):
            for state, glyph in {'idle': '.', 'new': 'o', 'offline': 'x',
                                 'unknown': '?', None: '?'}.items():
                self.assertTrue(desktop.status_indicator(state, 0, '#1e1e1e').isascii())
                self.assertIn('nounderscore]' + glyph, desktop.status_indicator(state, 9, '#1e1e1e'))
            for frame in range(16):
                glyph = desktop.ASCII_SPINNER_FRAMES[-(frame // 2) % 4]
                self.assertIn('nounderscore]' + glyph, desktop.status_indicator('compacting', frame, '#1e1e1e'))
        with mock.patch.dict(os.environ, PI_DESK_SPINNER='off'):
            for state, glyph in desktop.STATE_ICONS.items():
                self.assertIn('nounderscore]' + glyph, desktop.status_indicator(state, 39, '#1e1e1e'))
                self.assertFalse(desktop.working({'1': state}))

    def test_all_indicator_glyphs_occupy_one_terminal_cell(self):
        import ctypes
        import locale
        width = ctypes.CDLL(None).wcwidth
        width.argtypes, width.restype = [ctypes.c_wchar], ctypes.c_int
        original = locale.setlocale(locale.LC_CTYPE)
        try:
            locale.setlocale(locale.LC_CTYPE, '')
            glyphs = set(desktop.SPINNER_FRAMES + desktop.ASCII_SPINNER_FRAMES)
            glyphs.update(desktop.STATE_ICONS.values())
            glyphs.update(desktop.ASCII_STATE_ICONS.values())
            for glyph in glyphs:
                with self.subTest(glyph=glyph):
                    self.assertEqual(len(glyph), 1)
                    self.assertEqual(width(glyph), 1)
        finally:
            locale.setlocale(locale.LC_CTYPE, original)

    def test_header_background_is_uniform_and_focus_never_decorates_indicators(self):
        for bar in (desktop.selector({'1': 'running'}),
                    desktop.responsive_selector({'1': 'running'}, 184, 3, 1)):
            self.assertEqual(set(re.findall(r'bg=(#[0-9A-Fa-f]{6})', bar)), {'#1e1e1e'})
            self.assertNotIn('bg=#{', bar)
            self.assertNotIn('#4B2D59', bar)
            self.assertNotIn('#8D4CA3', bar)
            self.assertIn(']01#[nobold,nounderscore]', bar)
            self.assertIn('nobold,nounderscore]⠋ ', bar)

    def test_header_number_purples_meet_vscode_contrast_threshold(self):
        def luminance(color):
            channels = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        for color in ('D183E8', 'B28CBD'):
            self.assertGreaterEqual((luminance(color) + .05) / (luminance('1e1e1e') + .05), 4.5)

    def test_compaction_color_matches_shared_app_exact_rgb(self):
        app = Path(__file__).resolve().parent.parent / 'jarvis-app'
        color = (app / 'JARVISKit/Sources/JARVISKit/PiSessionStatusColor.swift').read_text()
        self.assertEqual(desktop.COLORS['compacting'], '#FF7A00')
        self.assertIn('case .compacting: return Color(red: 1, green: 122.0 / 255, blue: 0)', color)

    def test_invalid_input(self):
        for value in ('', '11', '-1', '01', '1;exit', 'left'):
            with self.assertRaises(ValueError):
                desktop.session_number(value)

    def test_background_click_is_ignored(self):
        with mock.patch.object(desktop, 'choose') as choose:
            self.assertEqual(desktop.dispatch(['click', '', '999']), 0)
            choose.assert_not_called()
            self.assertEqual(desktop.dispatch(['click', '5', '999']), 0)
            choose.assert_called_once_with(5, 999)

    def test_restore_invalid_state(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(desktop, 'STATE', Path(directory)), \
                mock.patch.object(desktop, 'tmux', return_value=mock.Mock(stdout='')):
            self.assertEqual(desktop.last_session(), 1)
            (Path(directory)/'last-session').write_text('bad')
            self.assertEqual(desktop.last_session(), 1)

    def test_multiple_displays_share_status_and_take_over(self):
        entered = [threading.Event(), threading.Event()]
        stops = [threading.Event(), threading.Event()]
        def watch(stop):
            entered[stops.index(stop)].set()
            stop.wait(5)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(desktop, 'STATE', Path(directory)), \
             mock.patch.object(desktop, 'watch_status', side_effect=watch):
            threads = [threading.Thread(target=desktop.monitor, args=(stop,)) for stop in stops]
            try:
                threads[0].start()
                self.assertTrue(entered[0].wait(2))
                threads[1].start()
                self.assertFalse(entered[1].wait(.1))
                stops[0].set()
                self.assertTrue(entered[1].wait(2))
            finally:
                for stop in stops:
                    stop.set()
                for thread in threads:
                    if thread.ident:
                        thread.join(3)

    def test_health_style_and_escape(self):
        self.assertEqual('', desktop.health_line('live', ('test', 'active')))
        self.assertIn('colour203', desktop.health_line('live', ('test', 'failed')))
        for status in ('unavailable', 'reconnecting', 'deactivating', 'stale', 'unknown',
                       'disconnected', 'Connecting to Mac…', 'invalid', 'inactive', '--', 'no reply'):
            self.assertIn('colour179', desktop.health_line(status, ('test', 'active')))
        self.assertIn('##(bad)', desktop.health_line('live', ('unknown #(bad)', 'active')))

    def test_only_unhealthy_fields_are_shown(self):
        for healthy in (('macOS | Sessions: local', 'Load: 1.25'),
                        ('Wi-Fi -50 dBm | Mac ping 2 ms | Pi 45°C', 'Presence service: active')):
            self.assertEqual(desktop.health_line('Mac connected · Session status live', healthy), '')
        row = desktop.health_line('Mac connected · Session status live',
                                  ('Wi-Fi -50 dBm | Mac ping no reply | Pi 45°C', 'Presence service: active'))
        self.assertIn('Mac ping no reply', row)
        for field in ('Wi-Fi', '45°C', 'Presence', 'live'):
            self.assertNotIn(field, row)

    def test_navigation_boundaries(self):
        for current, step, wanted in ((4, -1, 3), (3, 1, 4), (9, 1, 10),
                                      (10, -1, 9), (1, -1, 1), (10, 1, 10)):
            calls = []
            def mux(*args, **kwargs):
                calls.append(args)
                if args[0] == 'list-clients':
                    return mock.Mock(stdout='999\tclient\t%1\n', returncode=0)
                if args[0] == 'display-message':
                    return mock.Mock(stdout=str(current), returncode=0)
                return mock.Mock(stdout='', returncode=1 if args[0] == 'list-panes' else 0)
            key, index = core.session_group(wanted)
            with tempfile.TemporaryDirectory() as directory, \
                 mock.patch.object(desktop, 'STATE', Path(directory)), \
                 mock.patch.object(desktop, 'tmux', side_effect=mux), \
                 mock.patch.object(desktop, 'ensure_group', return_value='group-'+key):
                desktop.choose(client_pid=999, step=step)
                self.assertIn(('select-pane', '-t', f'group-{key}:0.{index}'), calls)
                self.assertIn(('switch-client', '-c', 'client', '-t', '=group-'+key), calls)
                self.assertEqual(desktop.last_session(), wanted)


class HealthTests(unittest.TestCase):
    def setUp(self):
        system = mock.patch.object(health.platform, 'system', return_value='Linux')
        system.start()
        self.addCleanup(system.stop)

    def test_health_values(self):
        with mock.patch.object(health, 'output', side_effect=[
                'signal: -49 dBm', 'hostname 192.0.2.1\n',
                '64 bytes time=12.5 ms', 'active\n']) as run, \
             mock.patch.object(health.Path, 'read_text', return_value='56400'):
            lines = health.collect('mac-mini-64')
        self.assertEqual(lines, ('Wi-Fi -49 dBm | Mac ping 12.5 ms | Pi 56°C',
                                 'Presence service: active'))
        self.assertEqual(run.call_args_list[2].args[0][-1], '192.0.2.1')

    def test_health_missing_tools_and_temperature(self):
        with mock.patch.object(health, 'output', return_value=''), \
             mock.patch.object(health.Path, 'read_text', side_effect=OSError):
            self.assertEqual(health.collect('mac-mini-64'), health.UNKNOWN)

    def test_ping_failure_does_not_claim_mac_offline(self):
        with mock.patch.object(health, 'output', side_effect=[
                'Not connected.', 'hostname 192.0.2.1\n', '', 'failed']), \
             mock.patch.object(health.Path, 'read_text', return_value='bad'):
            lines = health.collect('mac-mini-64')
        self.assertIn('Wi-Fi disconnected', lines[0])
        self.assertIn('Mac ping no reply', lines[0])
        self.assertEqual(lines[1], 'Presence service: failed')

    def test_command_timeout_is_unknown(self):
        with mock.patch.object(health.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 2)):
            self.assertEqual(health.output(['test']), '')

    def test_background_single_worker_and_expiry(self):
        monitor = health.HealthMonitor('mac-mini-64')
        with mock.patch.object(health.threading, 'Thread') as worker, \
             mock.patch.object(health.time, 'monotonic', return_value=100) as clock:
            self.assertEqual(monitor.poll(), health.UNKNOWN)
            monitor.poll()
            worker.assert_called_once()
            self.assertTrue(worker.call_args.kwargs['daemon'])
            monitor.lines = ('old reading', 'old status')
            monitor.updated = 100
            self.assertEqual(monitor.poll(), monitor.lines)
            clock.return_value = 126
            self.assertEqual(monitor.poll(), health.UNKNOWN)
            worker.assert_called_once()

    def test_worker_exception_is_unknown(self):
        monitor = health.HealthMonitor('mac-mini-64')
        monitor.busy = True
        with mock.patch.object(health, 'collect', side_effect=RuntimeError):
            monitor.sample()
        self.assertFalse(monitor.busy)
        self.assertEqual(monitor.lines, health.UNKNOWN)


class InstallerTests(unittest.TestCase):
    def test_retired_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'terminal.py').write_text('retired')
            (root/'core.py').write_text('current')
            (root/'__pycache__').mkdir()
            (root/'__pycache__/terminal.pyc').touch()
            install_pi.remove_retired(root)
            self.assertFalse((root/'terminal.py').exists())
            self.assertFalse((root/'__pycache__').exists())
            self.assertTrue((root/'core.py').exists())


class BackendTests(unittest.TestCase):
    def test_local_all_sessions_without_ssh(self):
        for number in range(1, 11):
            command = backend.Backend(mode='local').attachment(number)
            self.assertEqual(command[0], '/opt/homebrew/bin/tmux')
            self.assertIn('ignore-size', command)
            self.assertEqual(command[-1], '=jarvis-ios' + (f'-{number}' if number > 1 else ''))
            self.assertNotIn('ssh', command)

    def test_remote_uses_same_sessions_with_strict_ssh(self):
        command = backend.Backend().attachment(10)
        self.assertEqual(command[0], 'ssh')
        for token in ('StrictHostKeyChecking=yes', 'ClearAllForwardings=yes', '-a', '-x'):
            self.assertIn(token, command)
        self.assertEqual(shlex.split(command[-1]), backend.Backend(mode='local').attachment(10))

    @unittest.skipUnless(shutil.which('zsh'), 'zsh required')
    def test_remote_tokens_survive_zsh_equals_expansion(self):
        for number in range(1, 11):
            target = backend.Backend(mode='local').attachment(number)[-1]
            tokens = [target, "spaces and 'quotes'", '$(exit 99)', '*']
            command = backend.Backend().run_on_host(['printf', '%s\\n', *tokens])[-1]
            result = subprocess.run(['zsh', '-f', '-c', command], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), tokens)

    def test_invalid_configuration_and_slots(self):
        for args in ({'mode': 'auto'}, {'host': '-oProxyCommand=bad'}, {'project_root': 'relative'}):
            with self.assertRaises(ValueError):
                backend.Backend(**args)
        for number in (0, 11, True, '1'):
            with self.assertRaises(ValueError):
                backend.Backend().attachment(number)

    def test_config_load_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'client.json'
            self.assertEqual(backend.load(path).mode, 'ssh')
            path.write_text('{"mode":"local"}')
            self.assertEqual(backend.load(path).mode, 'local')
            path.write_text('{"mode":"local", "unexpected":true}')
            with self.assertRaises(ValueError):
                backend.load(path)
            path.write_text('invalid')
            with self.assertRaises(ValueError):
                backend.load(path)

    def test_nesting_environment_removed(self):
        with mock.patch.dict(os.environ, {'TMUX': 'outer', 'TMUX_PANE': '%0'}):
            cleaned = backend.clean_environment()
            self.assertNotIn('TMUX', cleaned)
            self.assertNotIn('TMUX_PANE', cleaned)
            self.assertEqual(os.environ['TMUX'], 'outer')

    def test_status_and_restart_routing(self):
        local, remote = backend.Backend(mode='local'), backend.Backend()
        self.assertTrue(local.status()[-1].endswith('status_stream.py'))
        self.assertEqual(remote.status()[0], 'ssh')
        self.assertIn('/pi-desk/status_stream.py', remote.status()[-1])
        self.assertEqual(local.restart(True)[-2:], ['--all', '--dry-run'])
        self.assertEqual(shlex.split(remote.restart()[-1]), local.restart())

    def test_confirmed_restart_scopes_notification_and_preserves_exit_code(self):
        for code in (0, 1):
            with self.subTest(code=code), \
                 mock.patch.object(cli.sys, 'argv', ['pi-desk', 'restart', '--confirmed',
                                                    '--client', '/dev/test-client']), \
                 mock.patch('restart_status.run', return_value=code) as run:
                self.assertEqual(cli.main(), code)
                run.assert_called_once_with(client='/dev/test-client')

    def test_restart_client_requires_confirmed_request(self):
        with mock.patch.object(cli.sys, 'argv', ['pi-desk', 'restart', '--client', '/dev/test-client']), \
             mock.patch.object(cli.sys, 'stderr'), \
             mock.patch('restart_status.run') as run:
            with self.assertRaises(SystemExit) as error:
                cli.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_restart_requires_interactive_confirmation(self):
        with mock.patch.object(cli.sys.stdin, 'isatty', return_value=False), \
             mock.patch.object(cli.subprocess, 'run') as run:
            self.assertEqual(cli.restart(), 1)
            run.assert_not_called()

    def test_restart_confirmed_once_and_never_retried(self):
        with mock.patch.object(cli, 'load', return_value=backend.Backend(mode='local')), \
             mock.patch.object(cli.sys.stdin, 'isatty', return_value=True), \
             mock.patch('builtins.input', side_effect=['', '']), \
             mock.patch.object(cli.subprocess, 'run', return_value=mock.Mock(returncode=1)) as run:
            self.assertEqual(cli.restart(), 1)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][-1], '--all')

    def test_restart_cancelled_on_text_eof_or_ctrl_c(self):
        for response in ('RESTART', ' ', EOFError(), KeyboardInterrupt()):
            with self.subTest(response=response), \
                 mock.patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                 mock.patch('builtins.input', side_effect=[response]), \
                 mock.patch.object(cli.subprocess, 'run') as run:
                self.assertEqual(cli.restart(), 1)
                run.assert_not_called()

    def test_macos_diagnostics_never_run_linux_commands(self):
        with mock.patch.object(health.platform, 'system', return_value='Darwin'), \
             mock.patch.object(health, 'load', return_value=backend.Backend(mode='local')), \
             mock.patch.object(health.os, 'getloadavg', return_value=(1.2, 1, 1)), \
             mock.patch.object(health, 'output') as output:
            self.assertEqual(health.collect('mac-mini-64'), ('macOS | Sessions: local', 'Load: 1.20'))
            output.assert_not_called()
            self.assertNotIn('Presence', str(health.unknown()))

    def test_mac_install_and_upgrade_are_non_destructive(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(install.Path, 'home', return_value=Path(directory)), \
             mock.patch.object(install.platform, 'system', return_value='Darwin'), \
             mock.patch.object(install.subprocess, 'run') as run:
            home = Path(directory)
            (home/'.zshrc').write_text('# existing profile\n')
            install.install('local')
            app = home/'.local/share/pi-desk'
            (app/'terminal.py').write_text('retired')
            install.install('local')
            self.assertFalse((app/'terminal.py').exists())
            self.assertEqual((home/'.zshrc').read_text().count(install.PATH_LINE), 1)
            self.assertTrue((home/'.zshrc').read_text().startswith('# existing profile'))
            self.assertEqual(backend.load(home/'.config/pi-desk/client.json').mode, 'local')
            entry = home/'Applications/Pi Desk.app/Contents/MacOS/Pi Desk'
            self.assertTrue(entry.is_file())
            self.assertIn('open -a Terminal', entry.read_text())
            self.assertNotIn('osascript', entry.read_text())
            profile = install.plistlib.loads((app/'launch.terminal').read_bytes())
            self.assertIn('pi-desk', profile['CommandString'])
            self.assertEqual((profile['columnCount'], profile['rowCount']), (173, 47))
            self.assertIn('cli.py', (home/'.local/bin/pi-desk').read_text())
            backups = list((home/'.local/state/pi-desk/backups').iterdir())
            self.assertEqual(len(backups), 2)
            self.assertTrue(any((p/'app/terminal.py').exists() for p in backups))
            self.assertFalse(any((p/'home/.zshrc').exists() for p in backups))
            run.assert_not_called()  # No sudo, service or hosted-session mutation.


if __name__ == '__main__':
    unittest.main()
