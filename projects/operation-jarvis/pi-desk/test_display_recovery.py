"""Display-only recovery; mocks and private tmux sockets, never hosted agents."""
import fcntl
import os
from pathlib import Path
import pty
import shutil
import shlex
import struct
import subprocess
import sys
import termios
import time
import unittest
from unittest import mock
import uuid

import core


class StartupRecoveryTests(unittest.TestCase):
    def test_healthy_or_absent_workspace_never_flushes_live_output(self):
        for code in (0, 1):
            with self.subTest(code=code), \
                    mock.patch.object(core.sys, 'platform', 'darwin'), \
                    mock.patch.object(core, 'recover_closed_displays') as closed, \
                    mock.patch.object(core, 'recover_blocked_display_output') as blocked, \
                    mock.patch.object(core.subprocess, 'run', return_value=mock.Mock(returncode=code)) as run:
                core.prepare_workspace()
                closed.assert_called_once()
                blocked.assert_not_called()
                self.assertEqual(run.call_args.args[0], ['tmux', '-L', core.SOCKET, 'list-sessions'])

    def test_only_read_only_probe_is_retried_after_timeout(self):
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core, 'recover_closed_displays'), \
                mock.patch.object(core, 'recover_blocked_display_output') as blocked, \
                mock.patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired('tmux', 2)), \
                mock.patch.object(core, 'tmux') as retry:
            core.prepare_workspace()
            blocked.assert_called_once()
            retry.assert_called_once_with('list-sessions', check=False)

    def test_unrecoverable_server_still_reports_bounded_error(self):
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core, 'recover_closed_displays'), \
                mock.patch.object(core, 'recover_blocked_display_output'), \
                mock.patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired('tmux', 2)):
            with self.assertRaisesRegex(RuntimeError, 'workspace is not responding'):
                core.prepare_workspace()

    def test_linux_keeps_existing_recovery_path(self):
        with mock.patch.object(core.sys, 'platform', 'linux'), \
                mock.patch.object(core, 'recover_closed_displays') as closed, \
                mock.patch.object(core.subprocess, 'run') as run:
            core.prepare_workspace()
            closed.assert_called_once()
            run.assert_not_called()


class ServerOutputRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.socket = (Path(os.environ.get('TMUX_TMPDIR', '/tmp')) /
                       f'tmux-{os.getuid()}' / core.SOCKET).resolve()
        self.discovery = f'p42\nctmux\nn{self.socket}\n'
        self.process = f'{os.getuid()} tmux -L {core.SOCKET} new-session -d -s viewer-test\n'
        self.files = f'p42\nf5\nn{self.socket}\nf7\nn/dev/ttys035\nf8\nn/dev/ptmx\n'

    def recover(self, discovery=None, process=None, files=None, recheck=None, probes=None):
        results = [mock.Mock(stdout=discovery if discovery is not None else self.discovery),
                   mock.Mock(stdout=process if process is not None else self.process),
                   mock.Mock(stdout=files if files is not None else self.files),
                   mock.Mock(stdout=self.process),
                   mock.Mock(stdout=recheck if recheck is not None else self.files)]
        results += probes if probes is not None else [mock.Mock(returncode=0)]
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core.subprocess, 'run', side_effect=results), \
                mock.patch.object(core.os, 'open', return_value=99) as opened, \
                mock.patch.object(core.os, 'close') as closed, \
                mock.patch.object(core.termios, 'tcflush') as flush:
            core.recover_blocked_display_output()
        return opened, closed, flush

    def test_flushes_display_server_slave_even_without_attach_client(self):
        opened, closed, flush = self.recover()
        opened.assert_called_once_with('/dev/ttys035', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        flush.assert_called_once_with(99, termios.TCOFLUSH)
        closed.assert_called_once_with(99)

    def test_large_pending_write_is_flushed_until_first_responsive_probe(self):
        opened, closed, flush = self.recover(probes=[
            subprocess.TimeoutExpired('tmux', .1),
            subprocess.TimeoutExpired('tmux', .1), mock.Mock(returncode=0)])
        self.assertEqual(flush.call_args_list, [mock.call(99, termios.TCOFLUSH)] * 3)
        opened.assert_called_once()
        closed.assert_called_once_with(99)

    def test_flush_loop_is_bounded_when_server_cannot_recover(self):
        _, closed, flush = self.recover(probes=[subprocess.TimeoutExpired('tmux', .1)] * 20)
        self.assertEqual(flush.call_count, 20)
        closed.assert_called_once_with(99)

    def test_probe_error_closes_owned_descriptor(self):
        _, closed, flush = self.recover(probes=[OSError('missing tmux')])
        flush.assert_called_once()
        closed.assert_called_once_with(99)

    def test_never_opens_agent_socket_or_master_pty(self):
        for discovery, files in (
            (self.discovery.replace(core.SOCKET, 'jarvis-mobile'), self.files),
            (self.discovery, self.files.replace('/dev/ttys035', '/dev/ptmx')),
            (self.discovery, self.files.replace(str(self.socket), '/tmp/other-socket')),
        ):
            with self.subTest(discovery=discovery, files=files):
                opened, _, flush = self.recover(discovery=discovery, files=files)
                opened.assert_not_called()
                flush.assert_not_called()

    def test_rejects_wrong_process_or_uid(self):
        for process in (self.process.replace('tmux -L', 'python -L'),
                        self.process.replace(core.SOCKET, 'jarvis-mobile'),
                        self.process.replace(str(os.getuid()), str(os.getuid() + 1), 1)):
            with self.subTest(process=process):
                opened, _, flush = self.recover(process=process)
                opened.assert_not_called()
                flush.assert_not_called()

    def test_rechecks_socket_and_terminal_ownership(self):
        for recheck in (self.files.replace('/dev/ttys035', '/dev/ttys099'),
                        self.files.replace(str(self.socket), '/tmp/other-socket')):
            with self.subTest(recheck=recheck):
                opened, _, flush = self.recover(recheck=recheck)
                opened.assert_not_called()
                flush.assert_not_called()

    def test_discovery_failure_is_nonfatal(self):
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired('lsof', 3)), \
                mock.patch.object(core.os, 'open') as opened:
            core.recover_blocked_display_output()
            opened.assert_not_called()


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('tmux'), 'macOS tmux required')
class RealBlockedTerminalTests(unittest.TestCase):
    def test_killed_client_live_pty_recovers_without_server_or_pane_restart(self):
        """Model the macOS shared-fd O_NONBLOCK loss with a still-open VS Code PTY."""
        socket = 'pi-desk-test-' + uuid.uuid4().hex
        master, slave = pty.openpty()
        child = None
        command = ['tmux', '-L', socket]
        env = dict(os.environ, TERM='xterm-256color')
        env.pop('TMUX', None)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))

        def run(*args, timeout=3):
            return subprocess.run(command + list(args), env=env, capture_output=True,
                                  text=True, timeout=timeout, check=True).stdout.strip()

        try:
            dummy = shlex.join([sys.executable, '-c',
                "import time; print('\\n'.join(''.join(chr(33+(r+c)%90) for c in range(180)) "
                "for r in range(44)), flush=True); time.sleep(120)"])
            run('new-session', '-d', '-s', 'dummy', '-x', '184', '-y', '45', dummy)
            identity = run('display-message', '-p', '#{pid}:#{pane_id}:#{pane_pid}')
            child = subprocess.Popen(command + ['-T', 'hyperlinks', 'attach-session', '-t', '=dummy'],
                                     stdin=slave, stdout=slave, stderr=slave, env=env)
            deadline = time.monotonic() + 3
            while not run('list-clients'):
                if time.monotonic() > deadline:
                    self.fail('Dummy viewer did not attach')
                time.sleep(.02)
            # Let initial terminal setup finish before changing its shared fd.
            time.sleep(.3)
            # Server and attach client share this open-file description. Losing
            # O_NONBLOCK while the emulator stops reading makes writev block.
            fcntl.fcntl(slave, fcntl.F_SETFL, fcntl.fcntl(slave, fcntl.F_GETFL) & ~os.O_NONBLOCK)
            # Free a little queue space so libevent attempts its next large draw.
            fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
            try:
                os.read(master, 65536)
            except BlockingIOError:
                pass
            blocked = False
            for _ in range(12):
                try:
                    run('refresh-client', '-t', os.ttyname(slave), timeout=.3)
                    time.sleep(.03)
                except subprocess.TimeoutExpired:
                    blocked = True
                    break
            self.assertTrue(blocked, 'Failed to reproduce blocked terminal output')
            child.kill()
            child.wait(timeout=2)
            # Keep both PTY ends open: no hung-up tty and no surviving client.
            with self.assertRaises(subprocess.TimeoutExpired):
                run('list-sessions', timeout=.3)
            with mock.patch.object(core, 'SOCKET', socket):
                core.prepare_workspace()
            self.assertEqual(run('display-message', '-p', '#{pid}:#{pane_id}:#{pane_pid}'), identity)
            self.assertEqual(run('list-clients'), '')
            run('new-session', '-d', '-s', 'reopened', 'sleep 120')
            self.assertEqual(run('display-message', '-p', '-t', 'dummy',
                                 '#{pid}:#{pane_id}:#{pane_pid}'), identity)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            # Free a blocked write even when the assertion/setup fails.
            termios.tcflush(slave, termios.TCOFLUSH)
            os.close(master)
            os.close(slave)
            subprocess.run(command + ['kill-server'], env=env, capture_output=True, timeout=3)


if __name__ == '__main__':
    unittest.main()
