import datetime as dt
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


if __name__ == '__main__':
    unittest.main()
