"""Responsive viewer tests: isolated sockets, PTYs and sleep, never real agents."""
import fcntl
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from unittest import mock
import uuid

import backend
import core
import desktop
import layout
import native_navigation
import navigate
import workspace


class LayoutTests(unittest.TestCase):
    def test_thresholds(self):
        for width, count in ((1, 1), (80, 1), (100, 1), (101, 2), (110, 2),
                             (151, 2), (152, 3), (156, 3), (184, 3), (1000, 3)):
            self.assertEqual(layout.capacity(width, minimum=layout.DEFAULT_MIN_COLUMNS), count)

    def test_hysteresis(self):
        for width, previous, expected in ((100, 2, 1), (101, 1, 1), (104, 1, 1),
                                          (105, 1, 2), (110, 1, 2), (151, 3, 2),
                                          (152, 2, 2), (155, 2, 2), (156, 2, 3),
                                          (152, 3, 3), (184, 1, 3)):
            self.assertEqual(layout.capacity(width, previous, layout.DEFAULT_MIN_COLUMNS), expected)

    def test_custom_thresholds(self):
        with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS='60'):
            self.assertEqual(layout.capacity(110), 1)
            self.assertEqual(layout.capacity(173), 2)
            self.assertEqual(layout.capacity(182), 3)
        for value in ('oops', '1', '999'):
            with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS=value):
                self.assertEqual(layout.minimum_columns(), 50)

    def test_resize_waits_for_tmux_to_observe_terminal_dimensions(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(desktop, 'STATE', Path(directory)), \
             mock.patch.object(desktop, 'tmux', return_value=mock.Mock(
                 stdout='123\tviewer-' + 'a' * 32 + '\t184\t45\n')), \
             mock.patch.object(workspace, 'reconcile') as reconcile:
            self.assertFalse(desktop.resize_viewer(123, os.terminal_size((80, 45))))
            reconcile.assert_not_called()
            self.assertTrue(desktop.resize_viewer(123, os.terminal_size((184, 45))))
            reconcile.assert_called_once_with('viewer-' + 'a' * 32, None, 184)

    def test_focus_readiness_checks_live_shape_and_sizing_policy(self):
        details = ['viewer-' + 'a' * 32, '184', '3', '52', '0', '0', layout.shape((4, 5, 6))]
        self.assertTrue(desktop.ready_focus(5, details))
        details[6] = '1:5:0|0:4:0|2:6:0|'
        self.assertTrue(desktop.ready_focus(5, details))  # Pane-ID loop order differs.
        details[6] = layout.shape((4, 5, 6))
        self.assertFalse(desktop.ready_focus(7, details))
        for index, value in ((1, '150'), (2, ''), (2, '4'), (3, '19'),
                             (4, '1'), (5, '1'), (6, layout.shape((6, 5, 4))),
                             (6, '0:4:0|1:5:1|2:6:0|')):
            broken = details[:]
            broken[index] = value
            self.assertFalse(desktop.ready_focus(5, broken), (index, value))
        self.assertFalse(desktop.ready_focus(5, details[:2]))
        # Hysteresis keeps an existing two-pane group until the growth buffer.
        details[1:4] = ['158', '2', '52']
        details[6] = layout.shape((5, 6))
        self.assertTrue(desktop.ready_focus(5, details))
        details[1] = '162'
        self.assertFalse(desktop.ready_focus(5, details))

    def test_groups(self):
        for count in (1, 2, 3):
            for selected in range(1, 11):
                numbers = layout.group(selected, count)
                self.assertIn(selected, numbers)
                self.assertLessEqual(len(numbers), count)
                self.assertTrue(all(n in range(1, 11) for n in numbers))
        self.assertEqual(layout.group(5, 3), (4, 5, 6))
        self.assertEqual(layout.group(5, 2), (5, 6))
        self.assertEqual(layout.group(10, 3), (10,))

    def test_header_groups_and_click_targets(self):
        for count, separators in ((1, 0), (2, 4), (3, 3)):
            bar = desktop.responsive_selector({}, 184, count, 5)
            self.assertEqual(bar.count('│'), separators)
            for n in range(1, 11):
                self.assertIn(f'range=user|{n},', bar)
        self.assertIn('‹', desktop.responsive_selector({}, 30, 1, 10))
        self.assertIn('›', desktop.responsive_selector({}, 30, 1, 1))

    def test_header_dots_pulse(self):
        states = {'1': 'running', '2': 'compacting', '3': 'idle'}
        bright = desktop.responsive_selector(states, 184, 3, 1)
        dim = desktop.responsive_selector(states, 184, 3, 1, pulse_dim=True)
        self.assertEqual(bright.replace('fg=colour77]●', 'fg=colour22]●')
                         .replace('fg=colour75]●', 'fg=colour24]●'), dim)

    def test_debounces_size_changes_without_subprocess_polling(self):
        # Script time and samples: wall-clock sleeps can legitimately exceed the
        # debounce interval under load and make a correct watcher look broken.
        samples = iter(((0, 184), (.06, 180), (.12, 160), (.18, 140), (.24, 100),
                        (.30, 100), (.45, 100), (.55, 100), (.75, 100), (1, 100)))
        clock = [0]
        size = [os.terminal_size((184, 45))]
        applied = []

        def wait(timeout):
            try:
                clock[0], width = next(samples)
                size[0] = os.terminal_size((width, 45))
                return False
            except StopIteration:
                return True

        def resize(pid, expected_size):
            applied.append(expected_size)
            return True

        stop = mock.Mock()
        stop.wait.side_effect = wait
        with mock.patch.object(desktop.time, 'monotonic', side_effect=lambda: clock[0]), \
             mock.patch.object(desktop, 'terminal_size', side_effect=lambda: size[0]), \
             mock.patch.object(desktop, 'resize_viewer', side_effect=resize), \
             mock.patch.object(desktop, 'tmux') as commands:
            desktop.watch_dimensions(stop, 123)
        self.assertEqual(applied, [os.terminal_size((100, 45))])
        commands.assert_not_called()


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.socket = 'pi-desk-test-' + uuid.uuid4().hex
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        for patch in (mock.patch.object(core, 'SOCKET', self.socket),
                      mock.patch.object(core, 'connection_command', return_value='sleep 120'),
                      mock.patch.object(desktop, 'STATE', self.state)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(lambda: core.tmux('kill-server', check=False))
        self.viewers = []
        self.addCleanup(self.close_viewers)

    def close_viewers(self):
        for child, master, slave in self.viewers:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
            os.close(slave)
            os.close(master)

    def attach(self, name, width=184, height=45):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        child = subprocess.Popen(['tmux', '-L', self.socket, 'attach-session', '-t', '=' + name],
                                 stdin=slave, stdout=slave, stderr=slave,
                                 env=dict(backend.clean_environment(), TERM='xterm-256color'))
        self.viewers.append((child, master, slave))
        def drain():
            try:
                while os.read(master, 65536):
                    pass
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
        for _ in range(100):
            rows = core.tmux('list-clients', '-F', '#{client_pid}').stdout.splitlines()
            if str(child.pid) in rows:
                return child, slave
            time.sleep(.02)
        self.fail('Isolated viewer did not attach')

    def resize(self, child, slave, width, height=45):
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        child.send_signal(signal.SIGWINCH)
        for _ in range(100):
            rows = core.tmux('list-clients', '-F', '#{client_pid}:#{client_width}').stdout.splitlines()
            if f'{child.pid}:{width}' in rows:
                self.assertTrue(desktop.resize_viewer(child.pid))
                return
            time.sleep(.01)
        self.fail('Isolated viewer did not resize')

    def visible(self, name):
        return tuple(int(n) for n in core.tmux('list-panes', '-t', name + ':0',
                     '-F', '#{@pi-desk-session}').stdout.splitlines())

    def focus(self, name):
        return int(core.tmux('display-message', '-p', '-t', name + ':0',
                            '#{@pi-desk-session}').stdout.strip())

    def identities(self, name):
        rows = core.tmux('list-panes', '-s', '-t', name, '-F',
                         '#{@pi-desk-session}:#{pane_id}:#{pane_pid}').stdout.splitlines()
        return {row.split(':')[0]: row for row in rows}

    def test_all_sessions_all_modes_and_identity_preservation(self):
        name = workspace.create(5, 184, 45)
        client, slave = self.attach(name)
        for width, count in ((184, 3), (150, 2), (80, 1), (190, 3)):
            before = self.identities(name)
            self.resize(client, slave, width)
            self.assertEqual(self.focus(name), 5)
            self.assertEqual(self.visible(name), layout.group(5, count))
            for number in range(1, 11):
                desktop.choose(number, client.pid)
                self.assertEqual(self.focus(name), number)
                self.assertEqual(self.visible(name), layout.group(number, count))
            desktop.choose(5, client.pid)
            after = self.identities(name)
            for n, identity in before.items():
                self.assertEqual(after[n], identity)
        self.assertEqual(len(self.identities(name)), 10)

    def test_click_and_f12_focus_ready_group_without_layout_mutations(self):
        for width, count in ((184, 3), (110, 2), (80, 1)):
            name = workspace.create(5, width, 45)
            client, _ = self.attach(name, width)
            before = self.identities(name)
            for action in ('click', 'select'):
                for number in layout.group(5, count):
                    with mock.patch.object(workspace, 'reconcile') as reconcile, \
                         mock.patch.object(desktop, 'tmux', wraps=core.tmux) as commands:
                        self.assertEqual(desktop.dispatch([action, str(number), str(client.pid)]), 0)
                    reconcile.assert_not_called()
                    calls = [call.args for call in commands.call_args_list]
                    self.assertEqual(len(calls), 3)  # Client, live shape, focus/publication.
                    self.assertEqual(calls[-1][0], 'select-pane')
                    self.assertIn('@pi-desk-last', calls[-1])
                    self.assertFalse(any('select-layout' in call for call in calls))
                    self.assertEqual(self.visible(name), layout.group(5, count))
                    self.assertEqual(self.focus(name), number)
                    self.assertEqual(desktop.last_session(), number)
                    self.assertEqual((self.state / 'last-session').read_text().strip(), str(number))
                    self.assertEqual(self.identities(name), before)
            # Re-selecting a focused pane must not replace the persistence file.
            stamp = (self.state / 'last-session').stat().st_mtime_ns
            desktop.choose(number, client.pid)
            self.assertEqual((self.state / 'last-session').stat().st_mtime_ns, stamp)

    def test_focus_fast_path_falls_back_for_stale_or_broken_layouts(self):
        name = workspace.create(5, 184, 45)
        client, _ = self.attach(name)
        for defect in ('changing', 'order', 'dead', 'missing', 'capacity'):
            if defect == 'changing':
                core.tmux('set-option', '-t', name, '@pi-desk-changing', '1')
            elif defect == 'order':
                core.tmux('swap-pane', '-d', '-s', name + ':0.0', '-t', name + ':0.2')
            elif defect == 'dead':
                core.tmux('respawn-pane', '-k', '-t', name + ':0.0', 'exit 0')
                time.sleep(.1)
            elif defect == 'missing':
                core.tmux('kill-pane', '-t', name + ':0.0')
            else:
                core.tmux('set-option', '-t', name, '@pi-desk-capacity', '2')
            with mock.patch.object(workspace, 'reconcile', wraps=workspace.reconcile) as reconcile:
                desktop.choose(5, client.pid)
            reconcile.assert_called_once_with(name, 5, 184)
            self.assertEqual(self.visible(name), (4, 5, 6))
            self.assertEqual(self.focus(name), 5)
        with mock.patch.object(workspace, 'reconcile', wraps=workspace.reconcile) as reconcile:
            desktop.choose(8, client.pid)
        reconcile.assert_called_once_with(name, 8, 184)
        self.assertEqual(self.visible(name), (7, 8, 9))

    def test_combined_status_snapshot_persists_selection_without_extra_read(self):
        name = workspace.create(5, 184, 45)
        self.attach(name)
        core.tmux('set-option', '-g', '@pi-desk-last', '5')
        with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as calls:
            rows = desktop.persist_selection(include_viewers=True)
        self.assertEqual(calls.call_count, 1)
        self.assertIn('list-sessions', calls.call_args.args)
        self.assertEqual(rows, core.tmux('list-sessions', '-F', desktop.VIEWER_STATUS_FORMAT).stdout)
        self.assertEqual((self.state / 'last-session').read_text(), '5\n')
        stamp = (self.state / 'last-session').stat().st_mtime_ns
        desktop.persist_selection(include_viewers=True)
        self.assertEqual((self.state / 'last-session').stat().st_mtime_ns, stamp)
        core.tmux('set-option', '-g', '@pi-desk-last', 'invalid')
        desktop.persist_selection(include_viewers=True)
        self.assertEqual((self.state / 'last-session').read_text(), '5\n')
        core.tmux('set-option', '-gu', '@pi-desk-last')
        rows = desktop.persist_selection(include_viewers=True)
        self.assertIn(name, rows)  # Empty selection must not consume the first viewer row.

    def test_status_writes_batch_all_viewers_and_preserve_quoted_warning(self):
        names = [workspace.create(n, width, 45) for n, width in ((2, 184), (5, 110), (9, 80))]
        before = {name: self.identities(name) for name in names}
        states = {'2': 'running', '5': 'compacting', '9': 'idle'}
        warning = 'Warning: quotes \' and " ; $HOME # literal'
        rows = core.tmux('list-sessions', '-F', desktop.VIEWER_STATUS_FORMAT).stdout
        global_rows = (desktop.selector(states), warning)
        files = []

        def send(*args, **kwargs):
            if args[0] == 'source-file':
                info = Path(args[1]).stat()
                files.append((info.st_size, info.st_mode & 0o777))
            return core.tmux(*args, **kwargs)

        with mock.patch.object(desktop, 'tmux', side_effect=send) as calls:
            current = desktop.render_viewers(states, False, {}, warning,
                                             session_rows=rows, global_rows=global_rows)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(calls.call_args.args[0], 'source-file')
        self.assertFalse(Path(calls.call_args.args[1]).exists())
        self.assertGreater(files[0][0], 8192)  # More than a single argv IPC message.
        self.assertEqual(files[0][1], 0o600)
        for name in names:
            for i, expected in enumerate(current[name]):
                self.assertEqual(core.tmux('show-options', '-Av', '-t', name,
                                          f'status-format[{i}]').stdout.rstrip('\n'), expected)
            self.assertEqual(self.identities(name), before[name])
        self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), '2')
        self.assertEqual(core.tmux('show-options', '-gv', 'status-format[1]').stdout.rstrip('\n'), warning)
        with mock.patch.object(desktop, 'tmux', wraps=core.tmux) as calls:
            unchanged = desktop.render_viewers(states, False, current, warning, session_rows=rows)
        calls.assert_not_called()
        self.assertEqual(unchanged, current)
        desktop.render_viewers(states, True, current, '', session_rows=rows,
                               global_rows=(desktop.selector(states, pulse_dim=True), ''))
        self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), 'on')
        for name in names:
            self.assertEqual(core.tmux('show-options', '-Av', '-t', name,
                                      'status-format[1]').stdout.rstrip('\n'), '')

    def test_closed_viewer_does_not_abort_batched_header_updates(self):
        closed = workspace.create(2, 184, 45)
        survivor = workspace.create(5, 110, 45)
        rows = core.tmux('list-sessions', '-F', desktop.VIEWER_STATUS_FORMAT).stdout
        workspace.destroy(closed)
        current = desktop.render_viewers({}, False, {}, 'warning', session_rows=rows,
                                         global_rows=(desktop.selector({}), 'warning'))
        self.assertEqual(core.tmux('show-options', '-Av', '-t', survivor,
                                  'status-format[0]').stdout.rstrip('\n'), current[survivor][0])
        rows = core.tmux('list-sessions', '-F', desktop.VIEWER_STATUS_FORMAT).stdout
        self.assertNotIn(closed, desktop.render_viewers({}, False, current, 'warning', session_rows=rows))

    def test_status_monitor_uses_one_read_and_at_most_one_write_per_tick(self):
        for number, width in ((2, 184), (5, 110), (9, 80)):
            workspace.create(number, width, 45)
        core.tmux('set-option', '-g', '@pi-desk-last', '5')
        for state, expected_writes in (('idle', 1), ('running', 3)):
            feed = mock.Mock(backend=mock.Mock(host='test'),
                             connection='Mac connected · Session status live')
            feed.poll.return_value = {'1': state}
            health = mock.Mock()
            health.poll.return_value = ()
            stop = mock.Mock()
            stop.is_set.side_effect = [False, False, False, True]
            with mock.patch.object(desktop, 'StatusFeed', return_value=feed), \
                 mock.patch.object(desktop, 'HealthMonitor', return_value=health), \
                 mock.patch.object(desktop, 'pulse_is_dim', side_effect=[False, True, False]), \
                 mock.patch.object(desktop, 'tmux', wraps=core.tmux) as calls:
                desktop.watch_status(stop)
            args = [call.args for call in calls.call_args_list]
            self.assertEqual(sum('list-sessions' in call for call in args), 3)
            self.assertEqual(sum(call[0] == 'source-file' for call in args), expected_writes)
            self.assertEqual(len(args), 3 + expected_writes)
            feed.close.assert_called_once()

    def test_status_monitor_retries_failed_batch_without_caching_it(self):
        name = workspace.create(5, 184, 45)
        feed = mock.Mock(backend=mock.Mock(host='test'),
                         connection='Mac connected · Session status live')
        feed.poll.return_value = {'5': 'idle'}
        health = mock.Mock()
        health.poll.return_value = ()
        stop = mock.Mock()
        stop.is_set.side_effect = [False, False, True]
        failed = []

        def send(*args, **kwargs):
            if args[0] == 'source-file' and not failed:
                failed.append(args[1])
                raise RuntimeError('Synthetic status batch failure')
            return core.tmux(*args, **kwargs)

        with mock.patch.object(desktop, 'StatusFeed', return_value=feed), \
             mock.patch.object(desktop, 'HealthMonitor', return_value=health), \
             mock.patch.object(desktop, 'pulse_is_dim', return_value=False), \
             mock.patch.object(desktop, 'tmux', side_effect=send) as calls:
            desktop.watch_status(stop)
        self.assertEqual(sum(call.args[0] == 'source-file' for call in calls.call_args_list), 2)
        self.assertFalse(Path(failed[0]).exists())
        self.assertEqual(feed.close.call_count, 2)
        self.assertIn('range=user|5,', core.tmux('show-options', '-Av', '-t', name,
                                               'status-format[0]').stdout)

    def test_warm_regrouping_batches_mutations_and_equalizes_once(self):
        name = workspace.create(2, 184, 45)
        self.attach(name)
        workspace.reconcile(name, 5, 184)
        before = self.identities(name)
        real_tmux = core.tmux
        for number in (2, 6, 1, 4, 3, 5):
            with mock.patch.object(core, 'tmux', wraps=real_tmux) as calls:
                workspace.reconcile(name, number, 184)
            call_args = [call.args for call in calls.call_args_list]
            mutation_calls = [args for args in call_args if 'select-layout' in args]
            self.assertEqual(len(mutation_calls), 1)
            batch = mutation_calls[0]
            self.assertEqual(batch.count('select-layout'), 1)
            for args in call_args:
                if any(command in args for command in
                       ('swap-pane', 'break-pane', 'join-pane', 'select-pane')):
                    self.assertEqual(args, batch)
            self.assertEqual(batch[-5:], ('set-option', '-t', name, '@pi-desk-changing', '0'))
            self.assertEqual(len(call_args), 5)  # Gate, preferences, snapshot, batch.
            self.assertEqual(self.visible(name), layout.group(number, 3))
            self.assertEqual(self.focus(name), number)
            self.assertEqual(self.identities(name), before)
            widths = list(map(int, real_tmux('list-panes', '-t', name + ':0',
                                           '-F', '#{pane_width}').stdout.splitlines()))
            self.assertLessEqual(max(widths) - min(widths), 1)

    def test_failed_mutation_batch_keeps_navigation_gated_and_recovers(self):
        name = workspace.create(2, 184, 45)
        self.attach(name)
        workspace.reconcile(name, 5, 184)
        before = self.identities(name)
        real_tmux = core.tmux

        def fail_join(*args, **kwargs):
            if 'join-pane' in args:
                broken = list(args)
                source = broken.index('-s', broken.index('join-pane')) + 1
                broken[source] = '%99999999'  # Invalid only on the isolated socket.
                return real_tmux(*broken, **kwargs)
            return real_tmux(*args, **kwargs)

        with mock.patch.object(core, 'tmux', side_effect=fail_join):
            with self.assertRaises(RuntimeError):
                workspace.reconcile(name, 2, 184)
        self.assertEqual(real_tmux('show-options', '-v', '-t', name,
                                  '@pi-desk-changing').stdout.strip(), '1')
        workspace.reconcile(name, 2, 184)
        self.assertEqual(self.visible(name), (1, 2, 3))
        self.assertEqual(self.focus(name), 2)
        self.assertEqual(self.identities(name), before)
        self.assertEqual(real_tmux('show-options', '-v', '-t', name,
                                  '@pi-desk-changing').stdout.strip(), '0')

    def test_batch_recovers_scrambled_order_and_small_custom_panes(self):
        with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS='20'):
            name = workspace.create(2, 62, 45)
        self.attach(name, 62)
        before = self.identities(name)
        core.tmux('swap-pane', '-d', '-s', name + ':0.0', '-t', name + ':0.2')
        workspace.reconcile(name, 2, 62)
        self.assertEqual(self.visible(name), (1, 2, 3))
        self.assertEqual(self.identities(name), before)
        for number in (5, 8, 10, 9, 6, 3, 1):
            workspace.reconcile(name, number, 62)
            self.assertEqual(self.visible(name), layout.group(number, 3))
            self.assertEqual(self.focus(name), number)

    def test_110_columns_supports_two_panes_after_live_threshold_change(self):
        with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS='60'):
            name = workspace.create(2, 110, 45)
        client, slave = self.attach(name, 110)
        self.assertEqual(self.visible(name), (2,))
        identity = self.identities(name)['2']
        core.tmux('set-option', '-t', name, '@pi-desk-min-columns', '52')
        self.assertTrue(desktop.resize_viewer(client.pid))
        self.assertEqual(self.visible(name), (1, 2))
        self.assertEqual(self.focus(name), 2)
        self.assertEqual(self.identities(name)['2'], identity)
        widths = core.tmux('list-panes', '-t', name + ':0', '-F', '#{pane_width}').stdout.splitlines()
        self.assertGreaterEqual(min(map(int, widths)), 54)
        self.resize(client, slave, 80)
        self.assertEqual(self.visible(name), (2,))
        self.resize(client, slave, 110)
        self.assertEqual(self.visible(name), (1, 2))
        self.assertEqual(self.identities(name)['2'], identity)
        self.assertEqual(self.focus(name), 2)

    def test_active_title_badge_and_neutral_dividers_in_all_layouts(self):
        for width in (80, 110, 184):
            with self.subTest(width=width):
                name = workspace.create(1, width, 45)
                client, _ = self.attach(name, width)
                before = self.identities(name)
                target = name + ':0'
                border_format = core.tmux('show-options', '-wAv', '-t', target,
                                          'pane-border-format').stdout.strip()
                for number in self.visible(name):
                    desktop.choose(number, client.pid)
                    for option, expected in (('pane-border-lines', 'single'),
                                             ('pane-border-indicators', 'off'),
                                             ('pane-border-style', 'fg=colour240,bg=#1e1e1e'),
                                             ('pane-active-border-style', 'fg=colour240,bg=#1e1e1e')):
                        self.assertEqual(core.tmux('show-options', '-wAv', '-t', target,
                                                  option).stdout.strip(), expected)
                    panes = core.tmux('list-panes', '-t', target,
                                      '-F', '#{pane_id}:#{@pi-desk-session}').stdout.splitlines()
                    for pane in panes:
                        pane_id, session = pane.split(':')
                        label = core.tmux('display-message', '-p', '-t', pane_id,
                                          border_format).stdout.strip()
                        style = ('#[fg=#1e1e1e,bg=#D183E8,bold]' if int(session) == number
                                 else '#[fg=colour245,bg=#1e1e1e,nobold]')
                        self.assertEqual(label, f'#[default] {style} Session {session} #[default]')
                    self.assertEqual(self.focus(name), number)
                self.assertEqual(self.identities(name), before)

    def test_two_viewers_have_independent_sizes_focus_and_headers(self):
        wide = workspace.create(2, 184, 45)
        small = workspace.create(5, 80, 35)
        wide_client, wide_tty = self.attach(wide)
        small_client, small_tty = self.attach(small, 80, 35)
        before = self.identities(wide)
        self.resize(small_client, small_tty, 150)
        desktop.choose(8, small_client.pid)
        self.assertEqual(self.visible(wide), (1, 2, 3))
        self.assertEqual(self.focus(wide), 2)
        self.assertEqual(self.identities(wide), before)
        self.assertEqual(self.visible(small), (7, 8))
        bars = desktop.render_viewers({}, False, {})
        self.assertEqual(bars[wide][0].count('│'), 3)
        self.assertEqual(bars[small][0].count('│'), 4)
        self.resize(wide_client, wide_tty, 80)
        self.assertEqual(self.visible(wide), (2,))
        self.assertEqual(self.visible(small), (7, 8))
        # Killing one display workspace does not touch the other.
        workspace.destroy(wide)
        self.assertEqual(self.focus(small), 8)

    def test_dead_missing_and_parked_panes_recover(self):
        name = workspace.create(5, 184, 45)
        client, slave = self.attach(name)
        before = self.identities(name)
        core.tmux('kill-pane', '-t', name + ':0.0')
        core.tmux('respawn-pane', '-k', '-t', name + ':0.1', 'exit 0')
        time.sleep(.1)
        desktop.choose(5, client.pid)
        self.assertEqual(self.visible(name), (4, 5, 6))
        self.assertEqual(core.tmux('list-panes', '-t', name + ':0', '-F', '#{pane_dead}').stdout,
                         '0\n0\n0\n')
        self.assertEqual(self.identities(name)['5'], before['5'])
        self.resize(client, slave, 80)
        parked = next(row[0] for row in workspace.panes(name) if row[3] == '4')
        core.tmux('respawn-pane', '-k', '-t', parked, 'exit 0')
        time.sleep(.1)
        self.resize(client, slave, 190)
        self.assertEqual(self.visible(name), (4, 5, 6))
        self.assertEqual(core.tmux('display-message', '-p', '-t', parked, '#{pane_dead}').stdout.strip(), '0')

    def test_missing_visible_window_recovers_from_parked_attachments(self):
        name = workspace.create(5, 184, 45)
        client, slave = self.attach(name)
        self.resize(client, slave, 80)
        before = self.identities(name)
        core.tmux('kill-window', '-t', name + ':0')
        desktop.choose(5, client.pid)
        self.assertEqual(self.visible(name), (5,))
        self.assertEqual(self.focus(name), 5)
        for n in ('4', '6'):
            self.assertEqual(self.identities(name)[n], before[n])
        self.resize(client, slave, 190)
        self.assertEqual(self.visible(name), (4, 5, 6))

    def test_missing_visible_window_reuses_existing_parked_group_in_batch(self):
        name = workspace.create(5, 184, 45)
        self.attach(name)
        workspace.reconcile(name, 8, 184)
        core.tmux('kill-window', '-t', name + ':0')
        before = self.identities(name)
        real_tmux = core.tmux
        with mock.patch.object(core, 'tmux', wraps=real_tmux) as calls:
            workspace.reconcile(name, 5, 184)
        args = [call.args for call in calls.call_args_list]
        self.assertFalse(any('new-window' in call for call in args))
        batches = [call for call in args if 'move-window' in call]
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].count('select-layout'), 1)
        self.assertEqual(self.visible(name), (4, 5, 6))
        self.assertEqual(self.focus(name), 5)
        self.assertEqual(self.identities(name), before)

    def test_header_fits_and_selected_tab_is_clickable(self):
        name = workspace.create(1, 184, 45)
        for width in (1, 2, 3, 4, 5, 9, 20, 29, 30, 40, 60, 80, 99, 100, 121, 181, 184):
            for selected in (1, 5, 10):
                bar = desktop.responsive_selector({}, width, layout.capacity(width), selected)
                self.assertIn(f'range=user|{selected},', bar)
                expanded = core.tmux('display-message', '-p', '-t', name + ':0', '-F', bar).stdout.rstrip('\n')
                plain = re.sub(r'#\[[^\]]*\]', '', expanded)
                self.assertLessEqual(len(plain), width, (width, selected, plain))
        # tmux format expressions really evaluate: visible group has its tint.
        bar = desktop.responsive_selector({}, 184, 3, 1)
        expanded = core.tmux('display-message', '-p', '-t', name + ':0', '-F', bar).stdout
        self.assertIn('range=user|1,bg=#16252a,fg=#D183E8,bold', expanded)
        self.assertIn('range=user|4,bg=#1e1e1e,', expanded)
        self.assertIn('range=user|10,bg=#1e1e1e,', expanded)

    def test_warning_row_and_heights_with_session_specific_header(self):
        name = workspace.create(5, 184, 45)
        self.attach(name)
        before = self.identities(name)
        heights = []
        for warning in ('', desktop.health_line('SSH disconnected', ()), ''):
            desktop.render_status((desktop.selector({}), warning))
            desktop.render_viewers({}, False, {})
            time.sleep(.05)
            heights.append(int(core.tmux('display-message', '-p', '-t', name + ':0',
                                        '#{pane_height}').stdout))
            # Verify the session-local array explicitly includes the warning row.
            actual = core.tmux('show-options', '-Av', '-t', name, 'status-format[1]').stdout.rstrip('\n')
            self.assertEqual(actual, warning)
        self.assertEqual(heights[0], heights[1] + 1)
        self.assertEqual(heights[0], heights[2])
        self.assertEqual(self.identities(name), before)

    def install_test_navigation(self):
        # Cross-group helpers must inherit the isolated socket/state and dummy
        # connection command. Never run installed helpers against live agents.
        helper = self.state / 'navigate-test.py'
        helper.write_text('import sys\nfrom pathlib import Path\n'
            + f'sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
            + 'import core, desktop\n'
            + f'core.SOCKET = {self.socket!r}\n'
            + f'desktop.STATE = Path({str(self.state)!r})\n'
            + 'core.connection_command = lambda n: "sleep 120"\n'
            + f'with Path({str(self.state / "fallback-calls")!r}).open("a") as f: f.write("x")\n'
            + 'raise SystemExit(desktop.dispatch(["step", *sys.argv[1:]]))\n')
        def fallback(direction):
            return 'run-shell -b ' + shlex.quote(shlex.join([sys.executable, str(helper),
                                              str(direction)]) + ' "#{client_pid}"')
        with mock.patch.object(native_navigation, 'adaptive_fallback', side_effect=fallback):
            native_navigation.install(core.tmux)

    def test_real_native_keys_all_groups_modes_and_bounds(self):
        name = workspace.create(1, 184, 45)
        client, slave = self.attach(name)
        self.install_test_navigation()
        client_name = core.tmux('list-clients', '-F', '#{client_name}').stdout.strip()
        for width in (184, 150, 80):
            self.resize(client, slave, width)
            expected = 1
            for direction in [1] * 11 + [-1] * 11:
                core.tmux('send-keys', '-K', '-c', client_name,
                          'C-Right' if direction == 1 else 'C-Left')
                expected = max(1, min(10, expected + direction))
                for _ in range(200):
                    if self.focus(name) == expected:
                        # Cross-group reconciliation publishes readiness last.
                        changing = core.tmux('show-options', '-v', '-t', name, '@pi-desk-changing').stdout.strip()
                        if changing == '0':
                            break
                    time.sleep(.01)
                self.assertEqual(self.focus(name), expected)
                self.assertEqual(self.visible(name), layout.group(expected, layout.capacity(width)))
        self.assertEqual(desktop.last_session(), 1)
        # Exactly group-boundary keys used Python; healthy in-group/boundary-stop
        # keys remained native (6 in triple, 8 in double, 18 in single mode).
        self.assertEqual(len((self.state / 'fallback-calls').read_text()), 32)
        # Python fallback path agrees with the native mapping.
        navigate.step(1, client.pid, socket=self.socket, state=str(self.state))
        self.assertEqual(self.focus(name), 2)

    def test_native_missing_pane_falls_back_and_recovers(self):
        name = workspace.create(1, 184, 45)
        self.attach(name)
        self.install_test_navigation()
        client_name = core.tmux('list-clients', '-F', '#{client_name}').stdout.strip()
        core.tmux('kill-pane', '-t', name + ':0.1')
        core.tmux('send-keys', '-K', '-c', client_name, 'C-Right')
        for _ in range(200):
            if self.focus(name) == 2 and self.visible(name) == (1, 2, 3):
                break
            time.sleep(.01)
        self.assertEqual(self.focus(name), 2)
        self.assertEqual(self.visible(name), (1, 2, 3))

    def test_full_viewer_resizes_and_cleans_up_on_terminal_hangup(self):
        (self.state / 'last-session').write_text('5\n')
        helper = self.state / 'viewer-test.py'
        helper.write_text('import sys\nfrom pathlib import Path\nfrom types import SimpleNamespace\n'
            + f'sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n'
            + 'import core, desktop\n'
            + f'core.SOCKET = desktop.SOCKET = {self.socket!r}\n'
            + f'desktop.STATE = Path({str(self.state)!r})\n'
            + 'core.connection_command = lambda n: "sleep 120"\n'
            + 'desktop.prepare_workspace = lambda: None\n'
            + 'desktop.StatusFeed = lambda: SimpleNamespace(backend=SimpleNamespace(host="test"), '
              'connection="Mac connected · Session status live", poll=lambda: {"5": "idle"}, close=lambda: None)\n'
            + 'desktop.HealthMonitor = lambda host: SimpleNamespace(poll=lambda: ())\n'
            + 'raise SystemExit(desktop.main())\n')
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))
        child = subprocess.Popen([sys.executable, str(helper)], stdin=slave, stdout=slave, stderr=slave,
                                 env=dict(backend.clean_environment(), TERM='xterm-256color'))
        self.viewers.append((child, master, slave))
        def drain():
            try:
                while os.read(master, 65536):
                    pass
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
        for _ in range(200):
            rows = core.tmux('list-clients', '-F', '#{client_pid}\t#{session_name}', check=False).stdout.strip()
            if rows:
                break
            time.sleep(.02)
        self.assertTrue(rows)
        pid, name = rows.split('\t')
        before = self.identities(name)
        for width, count in ((150, 2), (80, 1), (190, 3)):
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, width, 0, 0))
            os.kill(int(pid), signal.SIGWINCH)
            for _ in range(200):
                capacity = core.tmux('show-options', '-v', '-t', name, '@pi-desk-capacity').stdout.strip()
                changing = core.tmux('show-options', '-v', '-t', name, '@pi-desk-changing').stdout.strip()
                if capacity == str(count) and changing == '0':
                    break
                time.sleep(.02)
            self.assertEqual(self.visible(name), layout.group(5, count))
            self.assertEqual(self.focus(name), 5)
        self.assertEqual(self.identities(name), before)
        child.send_signal(signal.SIGHUP)
        child.wait(timeout=15)
        self.assertEqual(child.returncode, 128 + signal.SIGHUP)
        self.assertNotEqual(core.tmux('has-session', '-t', '=' + name, check=False).returncode, 0)

    def test_cleanup_rejects_unowned_names(self):
        core.ensure_group('1')
        workspace.destroy('group-1')
        self.assertEqual(self.visible('group-1'), (1, 2, 3))
        with self.assertRaises(ValueError):
            workspace.reconcile('group-1', 1, 80)


if __name__ == '__main__':
    unittest.main()
