import datetime as dt
import os
import health
import shutil
import subprocess
import time
import unittest
from unittest import mock
import uuid

import status_stream
import terminal


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc)
        self.data = {'stale': False, 'subsystems': {'pi': {
            'ok': True, 'stale': False, 'updatedAt': self.now.isoformat(),
            'mobileSessions': [{'sessionID': 1, 'lifecycle': 'idle'}]}}}

    def test_fresh(self):
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_stale(self):
        self.assertEqual(status_stream.extract(self.data, self.now+dt.timedelta(seconds=16)), {})

    def test_future(self):
        self.assertEqual(status_stream.extract(self.data, self.now-dt.timedelta(seconds=6)), {})

    def test_backend_stale(self):
        self.data['stale'] = True
        self.assertEqual(status_stream.extract(self.data, self.now), {})

    def test_missing_timestamp(self):
        del self.data['subsystems']['pi']['updatedAt']
        self.assertEqual(status_stream.extract(self.data, self.now), {})

    def test_no_private_payload(self):
        self.data['subsystems']['pi']['mobileSessions'][0]['private'] = 'not emitted'
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_invalid_rows(self):
        self.data['subsystems']['pi']['mobileSessions'] += [None, {'sessionID': True, 'lifecycle': 'idle'},
            {'sessionID': 11, 'lifecycle': 'idle'}, {'sessionID': 2, 'lifecycle': []}]
        self.assertEqual(status_stream.extract(self.data, self.now), {'1': 'idle'})

    def test_grid_validation(self):
        self.assertEqual(terminal.valid_states({'1': 'running', '2': [], '11': 'idle'}), {'1': 'running'})
        self.assertEqual(terminal.valid_states([]), {})

    def test_feed_retries_failed_start(self):
        feed = terminal.StatusFeed()
        with mock.patch.object(terminal.subprocess, 'Popen', side_effect=OSError) as start:
            with mock.patch.object(terminal.time, 'monotonic', return_value=100):
                self.assertEqual(feed.poll(), {})
                feed.poll()
                self.assertEqual(start.call_count, 1)
            with mock.patch.object(terminal.time, 'monotonic', return_value=104):
                feed.poll()
                self.assertEqual(start.call_count, 2)


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class PaneRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.socket = mock.patch.object(terminal, 'SOCKET', 'pi-desk-test-'+uuid.uuid4().hex)
        self.socket.start()
        self.command = mock.patch.object(terminal, 'connection_command', return_value='sleep 120')
        self.command.start()

    def tearDown(self):
        terminal.tmux('kill-server', check=False)
        self.command.stop()
        self.socket.stop()

    def tags(self, target='group-1:0'):
        return terminal.tmux('list-panes', '-t', target, '-F', '#{@pi-desk-session}').stdout.splitlines()

    def test_create_and_idempotent(self):
        terminal.ensure_group('1')
        terminal.ensure_group('1')
        self.assertEqual(self.tags(), ['1', '2', '3'])

    def test_missing_middle_restored_in_order(self):
        terminal.ensure_group('1')
        terminal.tmux('kill-pane', '-t', 'group-1:0.1')
        terminal.ensure_group('1')
        self.assertEqual(self.tags(), ['1', '2', '3'])

    def test_dead_pane_respawned(self):
        terminal.ensure_group('1')
        terminal.tmux('respawn-pane', '-k', '-t', 'group-1:0.1', 'exit 0')
        time.sleep(0.1)
        terminal.ensure_group('1')
        dead = terminal.tmux('list-panes', '-t', 'group-1:0', '-F', '#{pane_dead}').stdout.splitlines()
        self.assertEqual(dead, ['0', '0', '0'])

    def test_tenth_solo(self):
        terminal.ensure_group('4')
        self.assertEqual(self.tags('group-4:0'), ['10'])


class FeedbackTests(unittest.TestCase):
    def test_stream_feedback_and_watchdog(self):
        read_fd, write_fd = os.pipe()
        process = mock.Mock(stdout=os.fdopen(read_fd, 'rb'))
        feed = terminal.StatusFeed()
        try:
            with mock.patch.object(terminal.subprocess, 'Popen', return_value=process), \
                 mock.patch.object(terminal.time, 'monotonic', return_value=100) as clock:
                feed.poll()
                self.assertEqual(feed.connection, 'Connecting to Mac…')
                os.write(write_fd, b'{}\n')
                feed.poll()
                self.assertIn('connected · Session status unavailable', feed.connection)
                os.write(write_fd, b'{"1":"running"}\n')
                self.assertEqual(feed.poll(), {'1': 'running'})
                self.assertIn('status live', feed.connection)
                os.write(write_fd, b'[]\n')
                self.assertEqual(feed.poll(), {})
                self.assertIn('Invalid status', feed.connection)
                clock.return_value = 113
                feed.poll()
                self.assertIn('SSH disconnected', feed.connection)
        finally:
            feed.close()
            os.close(write_fd)

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
            worker.assert_called_once()  # A hung worker must not spawn more workers.

    def test_worker_exception_is_unknown(self):
        monitor = health.HealthMonitor('mac-mini-64')
        monitor.busy = True
        with mock.patch.object(health, 'collect', side_effect=RuntimeError):
            monitor.sample()
        self.assertFalse(monitor.busy)
        self.assertEqual(monitor.lines, health.UNKNOWN)

    def test_diagnostic_colors(self):
        self.assertEqual(terminal.diagnostic_pair('Presence service: active'), 7)
        self.assertEqual(terminal.diagnostic_pair('Mac connected · Session status live'), 7)
        for value in ('Mac ping no reply', 'Presence service: inactive',
                      'SSH disconnected · Retrying in 3s', 'Wi-Fi --', 'Session status unavailable'):
            self.assertEqual(terminal.diagnostic_pair(value), 1)
        self.assertEqual(terminal.diagnostic_pair('Presence service: failed'), 10)

    def test_card_color_is_limited_to_dot(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (25, 57)
        with mock.patch.object(terminal.curses, 'color_pair', side_effect=lambda n: n):
            terminal.paint(screen, {'1': 'compacting'})
        calls = [call.args for call in screen.addnstr.call_args_list]
        self.assertTrue(any(row[2] == '●' and row[4] == 5 for row in calls))
        self.assertTrue(any(row[2].startswith('╭') and row[4] == 8 for row in calls))
        self.assertTrue(any(row[2] == 'Compacting' and row[4] == 7 for row in calls))
        # Longest lifecycle label fits inside the narrowest card.
        label = next(row for row in calls if row[2] == 'Compacting')
        edge = next(row for row in calls if row[0] == label[0] and row[2].startswith('│'))
        self.assertLess(label[1] + len(label[2])-1, edge[1] + len(edge[2])-1)

    def test_grid_fits_with_health_strip(self):
        screen = mock.Mock()
        screen.getmaxyx.return_value = (25, 96)
        with mock.patch.object(terminal.curses, 'color_pair', return_value=0):
            terminal.paint(screen, {}, connection='Connection test', health=('Health one', 'Health two'))
        calls = [call.args for call in screen.addnstr.call_args_list]
        self.assertTrue(any(row[0] == 1 and row[2] == 'Connection test' for row in calls))
        self.assertTrue(any(row[0] == 3 and row[2] == 'Health two' for row in calls))
        self.assertTrue(any(row[2] == '[4]' for row in calls))
        self.assertTrue(all(0 <= row[0] < 25 for row in calls))


if __name__ == '__main__':
    unittest.main()
