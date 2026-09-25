"""Isolated tests: no real Mac sessions, household actions or private state."""
import datetime as dt
import os
from pathlib import Path
import shutil
import shlex
import subprocess
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

    def test_backend_stale(self):
        self.data['stale'] = True
        self.assertEqual(status_stream.extract(self.data, self.now), {})

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
        self.assertIn('PI DESK', core.tmux('show-options', '-gv', 'status-format[0]').stdout)
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
            command = native_navigation.binding(1).replace(fallback, 'set-option -g @fallback yes')
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
    def test_all_click_targets(self):
        bar = desktop.selector({'1': 'running'})
        for n in range(1, 11):
            self.assertIn(f'range=user|{n},', bar)
        for text in ('fg=colour77', 'F12', '#{session_name}', '#{@pi-desk-session}',
                     '#[align=right,norange', 'Ctrl + ←/→ Switch'):
            self.assertIn(text, bar)

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
