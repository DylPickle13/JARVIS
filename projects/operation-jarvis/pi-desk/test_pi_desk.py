"""Isolated tests: no real Mac sessions, household actions or private state."""
import datetime as dt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import uuid

import core
import desktop
import health
import install_pi
import status_stream


class StatusTests(unittest.TestCase):
    def setUp(self):
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
            self.assertEqual(core.tmux('show-options', '-gv', 'status').stdout.strip(), '2')
            self.assertEqual(core.tmux('show-options', '-gv', 'status-position').stdout.strip(), 'top')


class DesktopTests(unittest.TestCase):
    def test_all_click_targets(self):
        bar = desktop.selector({'1': 'running'})
        for n in range(1, 11):
            self.assertIn(f'range=user|{n},', bar)
        for text in ('fg=colour77', 'F12', '#{session_name}', '#{@pi-desk-session}'):
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
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(desktop, 'STATE', Path(directory)):
            self.assertEqual(desktop.last_session(), 1)
            (Path(directory)/'last-session').write_text('bad')
            self.assertEqual(desktop.last_session(), 1)

    def test_health_style_and_escape(self):
        self.assertIn('colour245', desktop.health_line('live', ('test', 'active')))
        self.assertIn('colour203', desktop.health_line('live', ('test', 'failed')))
        for status in ('unavailable', 'reconnecting', 'deactivating'):
            self.assertIn('colour179', desktop.health_line(status, ('test', 'active')))
        self.assertIn('##(bad)', desktop.health_line('live', ('#(bad)', 'active')))

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


if __name__ == '__main__':
    unittest.main()
