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
                                self.received = now
                                self.failed = False
                                available = any(state != 'unknown' for state in self.states.values())
                                self.connection = ('Mac connected · Session status live' if available else
                                                   'Mac connected · Session status unavailable')
                            except (ValueError, TypeError):
                                self.states = {}
                                self.connection = 'Mac connected · Invalid status data'
        if self.process and now - (self.received or self.started) > STALE_AFTER:
            self.fail()
        return self.states if now - self.received < STALE_AFTER else {}


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
            if (not args or Path(args[0]).name != 'tmux' or
                    args[1:5] != ['-L', SOCKET, 'attach-session', '-t'] or
                    len(args) != 6 or args[5] not in {'=group-' + k for k in GROUPS}):
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


def tmux(*args, check=True):
    try:
        result = subprocess.run(['tmux', '-L', SOCKET, '-f', str(ROOT / 'config/tmux.conf'),
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
