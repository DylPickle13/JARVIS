#!/usr/bin/env python3
"""Pi Desk: local terminal UI; SSH clients never resize or detach Mac clients."""
import curses
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import time

from health import HealthMonitor, UNKNOWN

ROOT = Path(__file__).resolve().parent
SOCKET = 'pi-desk'
HOST = 'mac-mini-64'
GROUPS = {'1': (1, 2, 3), '2': (4, 5, 6), '3': (7, 8, 9), '4': (10,)}
STATES = ('unknown', 'running', 'idle', 'new', 'compacting', 'offline')
STALE_AFTER = 12


def valid_states(value):
    if not isinstance(value, dict):
        return {}
    return {str(n): value[str(n)] for n in range(1, 11)
            if isinstance(value.get(str(n)), str) and value[str(n)] in STATES}


class StatusFeed:
    """One read-only SSH stream; bounded buffers, freshness, and automatic retry."""
    def __init__(self):
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
        self.connection = 'SSH disconnected · Retrying in 3s'
        self.retry_at = time.monotonic() + 3

    def poll(self):
        now = time.monotonic()
        if self.process is None and now >= self.retry_at:
            try:
                self.process = subprocess.Popen([
                    'ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                    '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', HOST,
                    'exec /usr/bin/python3 "$HOME/.local/bin/pi-grid-status"'],
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
        # Restart a hung stream, not merely its displayed status.
        if self.process and now - (self.received or self.started) > STALE_AFTER:
            self.fail()
        return self.states if now - self.received < STALE_AFTER else {}


def tmux(*args, check=True):
    result = subprocess.run(['tmux', '-L', SOCKET, '-f', str(ROOT / 'config/tmux.conf'),
                             *args], capture_output=True, text=True, timeout=8)
    if check and result.returncode:
        raise RuntimeError('Local workspace could not be prepared; please try again.')
    return result


def connection_command(number):
    return f'/bin/bash {shlex.quote(str(ROOT / "connect.sh"))} {number}'


def ensure_group(key):
    """Repair missing/dead panes on every entry, using explicit local pane tags."""
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
    # Missing panes may have been re-created out of sequence: restore 1|2|3 order.
    for index, number in enumerate(wanted):
        pane = existing[number][0]
        current = tmux('display-message', '-p', '-t', pane, '#{pane_index}').stdout.strip()
        if current != str(index):
            tmux('swap-pane', '-d', '-s', pane, '-t', f'{target}.{index}')
    tmux('select-layout', '-t', target, 'even-horizontal')
    tmux('select-pane', '-t', f'{target}.0')
    return group


def open_workspace(key):
    if key == 's':
        command = ['ssh', '-t', '-o', 'ConnectTimeout=5', HOST]
    else:
        group = ensure_group(key)
        command = ['tmux', '-L', SOCKET, 'attach-session', '-t', '=' + group]
    return subprocess.run(['foot', '--fullscreen',
                           '--font=DejaVu Sans Mono:size=12,Noto Color Emoji:size=12',
                           *command], check=False).returncode


def paint(screen, states, error='', connection='Connecting to Mac…', health=UNKNOWN):
    screen.erase()
    rows, cols = screen.getmaxyx()
    def text(y, x, value, color=0):
        if y >= rows or x >= cols:
            return
        try:
            screen.addnstr(y, max(0, x), value, max(0, cols-max(0, x)-1), color)
        except curses.error:
            pass
    if cols < 57 or rows < 25:
        text(0, 2, 'PI DESK', curses.A_BOLD)
        text(1, 2, connection, curses.color_pair(4))
        text(2, 2, health[0], curses.A_DIM)
        text(3, 2, health[1], curses.A_DIM)
        text(5, 2, '1: 1–3   2: 4–6   3: 7–9   4: 10')
        text(6, 2, 's: Shell  q: Quit  F12: Back from sessions')
        for n in range(1, 11):
            text(7+n, 2, f'{n:2}: {states.get(str(n), "unknown").title()}')
        text(19, 2, error, curses.color_pair(1))
        screen.refresh()
        return
    width = min(23, (cols-12)//3)
    left = max(1, (cols-(width*3+9))//2)
    text(0, left, 'P I  D E S K', curses.color_pair(4) | curses.A_BOLD)
    text(1, left, connection, curses.color_pair(4))
    text(2, left, health[0], curses.A_DIM)
    text(3, left, health[1], curses.A_DIM)
    y = 5
    for key, numbers in GROUPS.items():
        text(y+1, left, f'[{key}]', curses.color_pair(4))
        for col, number in enumerate(numbers):
            state = states.get(str(number), 'unknown')
            color = curses.color_pair(STATES.index(state)+1)
            x = left + 5 + col*(width+2)
            text(y, x, '╭'+'─'*(width-2)+'╮', color)
            text(y+1, x, '│'+f'  {number}'.ljust(width-2)+'│', color | curses.A_BOLD)
            text(y+2, x, '│'+('  ● '+state.title()).ljust(width-2)+'│', color)
            text(y+3, x, '╰'+'─'*(width-2)+'╯', color)
        y += 5 if rows >= 29 else 4
    text(y, left, '1–3 Open row   4 Session 10   s Shell   q Quit', curses.A_DIM)
    text(y+1, left, error or 'F12 Return to grid · Auto-reconnect enabled',
         curses.color_pair(1) if error else curses.A_DIM)
    screen.refresh()


def main(screen):
    curses.curs_set(0)
    curses.use_default_colors()
    # Unknown amber, Running green, Idle purple, New cyan, Compacting blue, Offline grey.
    for i, color in enumerate((179, 77, 141, 80, 75, 245), 1):
        curses.init_pair(i, color if curses.COLORS >= 256 else i % 7 + 1, -1)
    screen.timeout(250)
    feed = StatusFeed()
    monitor = HealthMonitor(HOST)
    error = ''
    previous = None
    try:
        while True:
            states = feed.poll()
            health = monitor.poll()
            signature = (tuple(sorted(states.items())), screen.getmaxyx(), error, feed.connection, health)
            if signature != previous:
                paint(screen, states, error, feed.connection, health)
                previous = signature
            key = screen.getch()
            if key in (ord('q'), ord('Q')):
                return
            if key in tuple(map(ord, ('1', '2', '3', '4', 's', 'S'))):
                feed.close()
                curses.def_prog_mode()
                curses.endwin()
                try:
                    result = open_workspace(chr(key).lower())
                    error = '' if result == 0 else 'Connection closed; select a workspace to retry.'
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                    error = str(exc)[:70]
                finally:
                    curses.reset_prog_mode()
                    curses.curs_set(0)
                    curses.flushinp()
                    screen.clear()
                    previous = None
    finally:
        feed.close()


if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
