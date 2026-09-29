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
        for width, count in ((1, 1), (80, 1), (104, 1), (105, 2), (110, 2),
                             (157, 2), (158, 3), (184, 3), (1000, 3)):
            self.assertEqual(layout.capacity(width, minimum=layout.DEFAULT_MIN_COLUMNS), count)

    def test_hysteresis(self):
        for width, previous, expected in ((104, 2, 1), (105, 1, 1), (108, 1, 1),
                                          (109, 1, 2), (110, 1, 2), (157, 3, 2),
                                          (158, 2, 2), (161, 2, 2), (162, 2, 3),
                                          (158, 3, 3), (184, 1, 3)):
            self.assertEqual(layout.capacity(width, previous, layout.DEFAULT_MIN_COLUMNS), expected)

    def test_custom_thresholds(self):
        with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS='60'):
            self.assertEqual(layout.capacity(110), 1)
            self.assertEqual(layout.capacity(173), 2)
            self.assertEqual(layout.capacity(182), 3)
        for value in ('oops', '1', '999'):
            with mock.patch.dict(os.environ, PI_DESK_MIN_COLUMNS=value):
                self.assertEqual(layout.minimum_columns(), 52)

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
        stop = threading.Event()
        size = [os.terminal_size((184, 45))]
        applied = []
        def resize(pid, expected_size):
            applied.append(expected_size)
            return True
        with mock.patch.object(desktop, 'terminal_size', side_effect=lambda: size[0]), \
             mock.patch.object(desktop, 'resize_viewer', side_effect=resize):
            thread = threading.Thread(target=desktop.watch_dimensions, args=(stop, 123))
            thread.start()
            try:
                for width in (180, 160, 140, 100):
                    size[0] = os.terminal_size((width, 45))
                    time.sleep(.06)
                time.sleep(.32)
                self.assertEqual(applied, [os.terminal_size((100, 45))])
                time.sleep(.25)
                self.assertEqual(len(applied), 1)
            finally:
                stop.set()
                thread.join(2)


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

    def test_two_pane_divider_uses_full_active_border_colour(self):
        name = workspace.create(2, 110, 45)
        client, _ = self.attach(name, 110)
        before = self.identities(name)
        for number in (1, 2):
            desktop.choose(number, client.pid)
            self.assertEqual(core.tmux('show-options', '-wAv', '-t', name + ':0',
                                       'pane-border-indicators').stdout.strip(), 'off')
            self.assertIn('fg=#D183E8', core.tmux('show-options', '-wAv', '-t', name + ':0',
                                              'pane-active-border-style').stdout)
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
            + 'desktop.recover_closed_displays = lambda: None\n'
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
