"""Viewer lifetime safety: isolated tmux sockets and dummy panes, never agents."""
import fcntl
import os
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
import unittest
from unittest import mock
import uuid

import backend
import core
import workspace


class OrphanSafetyTests(unittest.TestCase):
    def setUp(self):
        self.name = 'viewer-' + 'a' * 32

    def test_only_old_unattached_viewers_with_proven_dead_owners_are_candidates(self):
        rows = '\n'.join((
            f'{self.name}\t100\t0\t42',
            'viewer-' + 'b' * 32 + '\t100\t1\t42',
            'viewer-' + 'c' * 32 + '\t950\t0\t42',
            'viewer-' + 'd' * 32 + '\t100\t0\t43',
            'viewer-' + 'e' * 32 + '\t100\t0\t',  # Legacy / unknown ownership.
            'viewer-' + 'f' * 32 + '\t100\t0\t0',
            'jarvis-ios\t100\t0\t42',
            'group-1\t100\t0\t42',
            'viewer-invalid\t100\t0\t42',
            'malformed',
        ))

        def command(*args, **kwargs):
            if args[0] == 'list-sessions':
                return mock.Mock(returncode=0, stdout=rows)
            return mock.Mock(returncode=int(args[0] == 'has-session'), stdout='')

        with mock.patch.object(core, 'tmux', side_effect=command) as tmux, \
             mock.patch.object(workspace, 'owner_running', side_effect=lambda pid: pid == 43):
            self.assertEqual(workspace.cleanup_orphans(now=1000), [self.name])
        mutations = [call.args for call in tmux.call_args_list if call.args[0] == 'if-shell']
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0][-1], 'kill-session -t =' + self.name)
        self.assertIn('#{session_attached}', mutations[0][-2])
        self.assertIn('#{session_created}', mutations[0][-2])
        self.assertIn('#{@pi-desk-owner-pid}', mutations[0][-2])

    def test_owner_check_fails_closed(self):
        for error, running in ((ProcessLookupError(), False), (PermissionError(), True),
                               (OSError(), True), (OverflowError(), True)):
            with mock.patch.object(workspace.os, 'kill', side_effect=error):
                self.assertEqual(workspace.owner_running(42), running)
        with mock.patch.object(workspace.os, 'kill') as probe:
            self.assertTrue(workspace.owner_running(42))
            probe.assert_called_once_with(42, 0)

    def test_failed_or_raced_cleanup_does_not_claim_removal(self):
        with mock.patch.object(core, 'tmux', side_effect=(
                mock.Mock(returncode=0, stdout=f'{self.name}\t100\t0\t42'),
                mock.Mock(returncode=0), mock.Mock(returncode=0))), \
             mock.patch.object(workspace, 'owner_running', return_value=False):
            self.assertEqual(workspace.cleanup_orphans(now=1000), [])

    def test_missing_server_is_a_noop(self):
        with mock.patch.object(core, 'tmux', return_value=mock.Mock(returncode=1)) as tmux:
            self.assertEqual(workspace.cleanup_orphans(), [])
            self.assertEqual(tmux.call_count, 1)

    def test_cleanup_arming_rejects_agent_and_legacy_names(self):
        with mock.patch.object(core, 'tmux') as tmux:
            for name in ('jarvis-ios', 'group-1', 'viewer-invalid', 'viewer-' + 'a' * 32 + '; kill-server'):
                with self.assertRaises(ValueError):
                    workspace.arm_cleanup(name)
            tmux.assert_not_called()


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class ViewerLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.socket = 'pi-desk-cleanup-test-' + uuid.uuid4().hex
        self.clients = []
        for patch in (mock.patch.object(core, 'SOCKET', self.socket),
                      mock.patch.object(core, 'connection_command', return_value='sleep 120')):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(lambda: core.tmux('kill-server', check=False))
        self.addCleanup(self.close_clients)
        # A sibling dummy session proves cleanup does not destroy the server.
        core.tmux('new-session', '-d', '-s', 'unrelated', 'sleep 120')
        self.unrelated = core.tmux('list-panes', '-t', '=unrelated', '-F',
                                   '#{pane_id}:#{pane_pid}').stdout

    def close_clients(self):
        for child, master, slave in self.clients:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
            os.close(slave)
            os.close(master)

    def attach(self, name):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))
        child = subprocess.Popen(['tmux', '-L', self.socket, 'attach-session', '-t', '=' + name],
                                 stdin=slave, stdout=slave, stderr=slave,
                                 env=dict(backend.clean_environment(), TERM='xterm-256color'))
        self.clients.append((child, master, slave))

        def drain():
            try:
                while os.read(master, 65536):
                    pass
            except OSError:
                pass

        threading.Thread(target=drain, daemon=True).start()
        self.wait_for(lambda: str(child.pid) in core.tmux(
            'list-clients', '-F', '#{client_pid}').stdout.splitlines())
        self.wait_for(lambda: core.tmux('show-options', '-v', '-t', name,
                                       'destroy-unattached').stdout.strip() == 'on')
        return child

    def wait_for(self, check):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.02)
        self.fail('Isolated viewer lifecycle condition did not become true')

    def detach(self, child):
        rows = core.tmux('list-clients', '-F', '#{client_pid}\t#{client_name}').stdout
        name = next(row.split('\t')[1] for row in rows.splitlines()
                    if row.split('\t')[0] == str(child.pid))
        core.tmux('detach-client', '-t', name)
        child.wait(timeout=2)

    def exists(self, name):
        return core.tmux('has-session', '-t', '=' + name, check=False).returncode == 0

    def assert_sibling_unchanged(self):
        self.assertEqual(core.tmux('list-panes', '-t', '=unrelated', '-F',
                                  '#{pane_id}:#{pane_pid}').stdout, self.unrelated)
        self.assertEqual(core.tmux('show-options', '-gv', 'destroy-unattached').stdout.strip(), 'off')

    def test_new_viewer_survives_before_first_attachment(self):
        name = workspace.create(1, 184, 45)
        self.assertTrue(self.exists(name))
        self.assertEqual(core.tmux('show-options', '-v', '-t', name,
                                  workspace.OWNER_OPTION).stdout.strip(), str(os.getpid()))
        self.assertEqual(workspace.cleanup_orphans(now=time.time() + 1000), [])
        self.assertTrue(self.exists(name))
        self.assert_sibling_unchanged()

    def test_last_client_detach_destroys_only_its_viewer(self):
        name = workspace.create(1, 184, 45)
        first = self.attach(name)
        second = self.attach(name)
        self.detach(first)
        self.assertTrue(self.exists(name))
        self.detach(second)
        self.wait_for(lambda: not self.exists(name))
        self.assert_sibling_unchanged()

    def test_sigkill_display_still_destroys_workspace_without_python_cleanup(self):
        name = workspace.create(1, 184, 45)
        client = self.attach(name)
        client.send_signal(signal.SIGKILL)
        client.wait(timeout=2)
        self.wait_for(lambda: not self.exists(name))
        self.assert_sibling_unchanged()

    def test_arming_live_legacy_viewer_preserves_client_and_panes(self):
        name = 'viewer-' + uuid.uuid4().hex
        core.tmux('new-session', '-d', '-s', name, 'sleep 120')
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))
        child = subprocess.Popen(['tmux', '-L', self.socket, 'attach-session', '-t', '=' + name],
                                 stdin=slave, stdout=slave, stderr=slave,
                                 env=dict(backend.clean_environment(), TERM='xterm-256color'))
        self.clients.append((child, master, slave))
        self.wait_for(lambda: str(child.pid) in core.tmux(
            'list-clients', '-F', '#{client_pid}').stdout.splitlines())
        before = core.tmux('list-panes', '-t', '=' + name, '-F', '#{pane_id}:#{pane_pid}').stdout
        workspace.arm_cleanup(name)
        self.assertIsNone(child.poll())
        self.assertEqual(core.tmux('list-panes', '-t', '=' + name, '-F',
                                  '#{pane_id}:#{pane_pid}').stdout, before)
        self.detach(child)
        self.wait_for(lambda: not self.exists(name))
        self.assert_sibling_unchanged()

    def test_sweep_removes_dead_owner_but_retains_unknown_and_live_owners(self):
        dead = workspace.create(1, 80, 45)
        alive = workspace.create(2, 80, 45)
        legacy = 'viewer-' + uuid.uuid4().hex
        core.tmux('new-session', '-d', '-s', legacy, 'sleep 120')
        # An exited dummy process supplies a real, confirmed-dead PID.
        child = subprocess.Popen(['true'])
        child.wait(timeout=2)
        core.tmux('set-option', '-t', dead, workspace.OWNER_OPTION, str(child.pid))
        self.assertEqual(workspace.cleanup_orphans(), [])  # Grace period.
        self.assertEqual(workspace.cleanup_orphans(now=time.time() + 1000), [dead])
        self.assertFalse(self.exists(dead))
        self.assertTrue(self.exists(alive))
        self.assertTrue(self.exists(legacy))
        self.assert_sibling_unchanged()

    def test_sweep_rechecks_attachment_inside_tmux_before_removing(self):
        name = workspace.create(1, 80, 45)
        # Simulate an old detached snapshot, followed by a concurrent attachment.
        self.attach(name)
        real_tmux = core.tmux
        created = core.tmux('display-message', '-p', '-t', name,
                            '#{session_created}').stdout.strip()
        core.tmux('set-option', '-t', name, workspace.OWNER_OPTION, '42')
        snapshot = mock.Mock(returncode=0, stdout=f'{name}\t{created}\t0\t42\n')

        def run(*args, **kwargs):
            return snapshot if args[0] == 'list-sessions' else real_tmux(*args, **kwargs)

        with mock.patch.object(core, 'tmux', side_effect=run), \
             mock.patch.object(workspace, 'owner_running', return_value=False):
            self.assertEqual(workspace.cleanup_orphans(now=time.time() + 1000), [])
        self.assertTrue(self.exists(name))
        self.assert_sibling_unchanged()


if __name__ == '__main__':
    unittest.main()
