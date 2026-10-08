"""Shared status transport and local workspace recovery for Pi Desk."""
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import time
import sys
import re
import termios

from backend import clean_environment, load
from tmux_runtime import command as tmux_command
from codex_quota import normalize as normalize_quota, UNAVAILABLE

ROOT = Path(__file__).resolve().parent
SOCKET = 'pi-desk'
GROUPS = {'1': (1, 2, 3), '2': (4, 5, 6), '3': (7, 8, 9), '4': (10,)}
STATES = ('unknown', 'running', 'idle', 'new', 'compacting', 'offline')
STALE_AFTER = 12


def valid_states(value):
    if not isinstance(value, dict):
        return {}
    return {str(n): value[str(n)] for n in range(1, 11)
            if isinstance(value.get(str(n)), str) and value[str(n)] in STATES}


class StatusFeed:
    """One local/SSH status stream; bounded buffers, freshness, automatic retry."""
    def __init__(self):
        self.backend = load()
        self.process = None
        self.buffer = b''
        self.states = {}
        self.quota = dict(UNAVAILABLE)
        self.received = 0
        self.retry_at = 0
        self.started = 0
        self.connection = 'Connecting to Mac…'
        self.failed = False

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdout.close()
        self.process = None
        self.buffer = b''
        self.states = {}
        self.quota = dict(UNAVAILABLE)
        self.received = 0

    def fail(self):
        self.close()
        self.failed = True
        self.connection = ('SSH disconnected' if self.backend.mode == 'ssh' else 'Local status disconnected') + ' · Retrying in 3s'
        self.retry_at = time.monotonic() + 3

    def poll(self):
        now = time.monotonic()
        if self.process is None and now >= self.retry_at:
            try:
                self.process = subprocess.Popen(
                    self.backend.status(), env=clean_environment(),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL)
                self.started = now
                self.connection = 'Reconnecting to Mac…' if self.failed else 'Connecting to Mac…'
            except OSError:
                self.fail()
        if self.process:
            stream = self.process.stdout
            if select.select([stream], [], [], 0)[0]:
                chunk = os.read(stream.fileno(), 4096)
                if not chunk:
                    self.fail()
                else:
                    self.buffer += chunk
                    if len(self.buffer) > 16384:
                        self.fail()
                    else:
                        while b'\n' in self.buffer:
                            line, self.buffer = self.buffer.split(b'\n', 1)
                            try:
                                payload = json.loads(line)
                                if not isinstance(payload, dict):
                                    raise ValueError('Expected status object')
                                self.states = valid_states(payload)
                                self.quota = normalize_quota(payload.get('codexQuota'))
                                self.received = now
                                self.failed = False
                                available = any(state != 'unknown' for state in self.states.values())
                                self.connection = ('Mac connected · Session status live' if available else
                                                   'Mac connected · Session status unavailable')
                            except (ValueError, TypeError):
                                self.states = {}
                                self.quota = dict(UNAVAILABLE)
                                self.connection = 'Mac connected · Invalid status data'
        if self.process and now - (self.received or self.started) > STALE_AFTER:
            self.fail()
        self.quota = normalize_quota(self.quota)
        return self.states if now - self.received < STALE_AFTER else {}


def is_display_attach(args):
    """Recognize only our display clients, including VS Code capabilities."""
    if not args or Path(args[0]).name != 'tmux' or args[1:3] != ['-L', SOCKET]:
        return False
    tail = args[3:]
    if tail[:2] == ['-T', 'hyperlinks']:
        tail = tail[2:]
    return (len(tail) == 3 and tail[:2] == ['attach-session', '-t'] and
            (tail[2] in {'=group-' + k for k in GROUPS} or
             re.fullmatch(r'=viewer-[0-9a-f]{32}', tail[2]) is not None))


def recover_closed_displays():
    """Unblock macOS tmux tty teardown without signalling clients or agents.

    A hung-up display loses its controlling tty, but tmux can retain an open
    slave fd and block in tty_raw(write). Flush only output for those exact
    Pi Desk attach clients; never touch live terminals or agent PTYs.
    """
    if sys.platform != 'darwin':
        return
    try:
        rows = subprocess.run(
            ['ps', '-U', str(os.getuid()), '-o', 'pid=,tty=,command='],
            capture_output=True, text=True, timeout=3, check=True).stdout
        for row in rows.splitlines():
            fields = row.split(None, 2)
            if len(fields) != 3 or fields[1] != '??':
                continue
            pid, _, command = fields
            args = shlex.split(command)
            if not is_display_attach(args):
                continue
            files = subprocess.run(
                ['/usr/sbin/lsof', '-a', '-p', pid, '-d', '0', '-Fn'],
                capture_output=True, text=True, timeout=3).stdout
            for line in files.splitlines():
                if not re.fullmatch(r'n/dev/ttys\d+', line):
                    continue
                # Recheck hangup after lsof: never flush a live display.
                current = subprocess.run(
                    ['ps', '-p', pid, '-o', 'tty=,command='],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                if current.split(None, 1) != ['??', command]:
                    continue
                fd = os.open(line[1:], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                try:
                    termios.tcflush(fd, termios.TCOFLUSH)
                finally:
                    os.close(fd)
    except (OSError, ValueError, termios.error, subprocess.SubprocessError):
        # Best effort; the normal bounded workspace probe reports any failure.
        return


def display_server_files(pid):
    """Fail closed unless this user's tmux process owns the exact display socket."""
    row = subprocess.run(
        ['ps', '-p', str(pid), '-o', 'uid=,command='],
        capture_output=True, text=True, timeout=3, check=True).stdout.split(None, 1)
    if len(row) != 2 or row[0] != str(os.getuid()):
        return ''
    args = shlex.split(row[1])
    if not args or Path(args[0]).name != 'tmux' or args[1:3] != ['-L', SOCKET]:
        return ''
    files = subprocess.run(
        ['/usr/sbin/lsof', '-a', '-p', str(pid), '-Ffn'],
        capture_output=True, text=True, timeout=3, check=True).stdout
    socket = (Path(os.environ.get('TMUX_TMPDIR', '/tmp')) /
              f'tmux-{os.getuid()}' / SOCKET).resolve()
    if not any(line.startswith('n/') and Path(line[1:]).resolve() == socket
               for line in files.splitlines()):
        return ''
    return files


def recover_blocked_display_output():
    """Last-resort macOS output flush after a read-only workspace probe times out.

    A killed attach client can leave the server blocked in writev even while its
    VS Code PTY still looks live. Discover the server through its UNIX socket,
    not through surviving attach clients. Touch only server-owned tty slaves;
    never PTY masters, agent sockets, terminal settings, or process signals.
    """
    if sys.platform != 'darwin':
        return
    try:
        rows = subprocess.run(
            ['/usr/sbin/lsof', '-a', '-U', '-u', str(os.getuid()), '-Fpcn'],
            capture_output=True, text=True, timeout=3, check=True).stdout
        socket = (Path(os.environ.get('TMUX_TMPDIR', '/tmp')) /
                  f'tmux-{os.getuid()}' / SOCKET).resolve()
        pid, command = None, None
        candidates = set()
        for line in rows.splitlines():
            if re.fullmatch(r'p\d+', line):
                pid, command = int(line[1:]), None
            elif line.startswith('c'):
                command = line[1:]
            elif (pid is not None and command == 'tmux' and line.startswith('n/')
                  and Path(line[1:]).resolve() == socket):
                candidates.add(pid)
        for pid in candidates:
            try:
                files = display_server_files(pid)
                terminals = set(line[1:] for line in files.splitlines()
                                if re.fullmatch(r'n/dev/ttys\d+', line))
                descriptors = []
                try:
                    for terminal in terminals:
                        # Revalidate process identity AND socket/tty ownership.
                        if 'n' + terminal not in display_server_files(pid).splitlines():
                            continue
                        descriptors.append(os.open(
                            terminal, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK))
                    if not descriptors:
                        continue
                    # A single blocked writev can exceed the kernel tty queue.
                    # Flush until it completes and tmux processes the lost client,
                    # stopping immediately once a read-only probe responds.
                    for _ in range(20):
                        for fd in descriptors:
                            termios.tcflush(fd, termios.TCOFLUSH)
                        try:
                            subprocess.run(tmux_command(SOCKET) + ['list-sessions'],
                                           capture_output=True, text=True, timeout=.1)
                            return
                        except subprocess.TimeoutExpired:
                            pass
                finally:
                    for fd in descriptors:
                        os.close(fd)
            except (OSError, ValueError, termios.error, subprocess.SubprocessError):
                continue
    except (OSError, ValueError, subprocess.SubprocessError):
        return


def prepare_workspace():
    """Recover before creating panes; never replay a timed-out mutation."""
    recover_closed_displays()
    if sys.platform != 'darwin':
        return
    try:
        subprocess.run(tmux_command(SOCKET) + ['list-sessions'],
                       capture_output=True, text=True, timeout=2)
    except subprocess.TimeoutExpired:
        recover_blocked_display_output()
        # Only the read-only probe is retried. If still blocked, report the
        # normal bounded error rather than killing a server or restarting agents.
        tmux('list-sessions', check=False)


def tmux(*args, check=True):
    try:
        result = subprocess.run(tmux_command(SOCKET) + ['-f', str(ROOT / 'config/tmux.conf'),
                                 *args], capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            'Pi Desk workspace is not responding (tmux timed out after 8 seconds). '
            'A stale display terminal may be blocking it; underlying agents were not restarted.'
        ) from exc
    if check and result.returncode:
        raise RuntimeError('Local workspace could not be prepared; please try again.')
    return result


def connection_command(number):
    return shlex.join([sys.executable, str(ROOT / 'connect.py'), str(number)])


def session_group(number):
    for key, numbers in GROUPS.items():
        if number in numbers:
            return key, numbers.index(number)
    raise ValueError('Session must be between 1 and 10')


def ensure_group(key):
    """Repair missing/dead panes, restore numeric order; never alter Mac layouts."""
    wanted = GROUPS[key]
    group = f'group-{key}'
    target = f'{group}:0'
    if tmux('has-session', '-t', '=' + group, check=False).returncode:
        pane = tmux('new-session', '-d', '-s', group, '-x', '190', '-y', '55',
                    '-P', '-F', '#{pane_id}', connection_command(wanted[0])).stdout.strip()
        tmux('set-option', '-p', '-t', pane, '@pi-desk-session', str(wanted[0]))
    rows = tmux('list-panes', '-t', target, '-F',
                '#{pane_id}\t#{@pi-desk-session}\t#{pane_dead}').stdout.splitlines()
    existing = {}
    for row in rows:
        pane, number, dead = row.split('\t')
        if number.isdecimal():
            existing[int(number)] = (pane, dead == '1')
    for number in wanted:
        if number in existing:
            pane, dead = existing[number]
            if dead:
                tmux('respawn-pane', '-t', pane, connection_command(number))
        else:
            pane = tmux('split-window', '-h', '-t', target, '-P', '-F', '#{pane_id}',
                        connection_command(number)).stdout.strip()
            tmux('set-option', '-p', '-t', pane, '@pi-desk-session', str(number))
            existing[number] = (pane, False)
        tmux('select-pane', '-t', pane, '-T', f'Session {number}')
        tmux('select-layout', '-t', target, 'even-horizontal')
    for index, number in enumerate(wanted):
        pane = existing[number][0]
        current = tmux('display-message', '-p', '-t', pane, '#{pane_index}').stdout.strip()
        if current != str(index):
            tmux('swap-pane', '-d', '-s', pane, '-t', f'{target}.{index}')
    tmux('select-layout', '-t', target, 'even-horizontal')
    tmux('select-pane', '-t', f'{target}.0')
    return group
