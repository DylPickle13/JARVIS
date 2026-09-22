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


class SessionChoice:
    """Explicit Enter keeps session 1 and session 10 unambiguous."""
    def __init__(self):
        self.value = ''
        self.error = ''

    def press(self, key):
        self.error = ''
        if ord('0') <= key <= ord('9'):
            self.value = (self.value + chr(key))[:3]
        elif key in (curses.KEY_BACKSPACE, 8, 127):
            self.value = self.value[:-1]
        elif key == 27:
            self.value = ''
        elif key in (ord('s'), ord('S')):
            self.value = ''
            return 's'
        elif key in (10, 13, curses.KEY_ENTER):
            if self.value in tuple(str(n) for n in range(1, 11)):
                result, self.value = self.value, ''
                return result
            self.error = 'Choose a session from 1 to 10.'
            self.value = ''
        return None


def session_group(number):
    for key, numbers in GROUPS.items():
        if number in numbers:
            return key, numbers.index(number)
    raise ValueError('Session must be between 1 and 10')


def open_workspace(key):
    if key == 's':
        command = ['ssh', '-t', '-o', 'ConnectTimeout=5', HOST]
    else:
        group_key, pane_index = session_group(int(key))
        group = ensure_group(group_key)
        tmux('select-pane', '-t', f'{group}:0.{pane_index}')
        command = ['tmux', '-L', SOCKET, 'attach-session', '-t', '=' + group]
    return subprocess.run(['foot', '--fullscreen',
                           '--font=DejaVu Sans Mono:size=14,Noto Color Emoji:size=14',
                           *command], check=False).returncode


def diagnostic_pair(value):
    """Quiet normal readings; distinguish explicit failures from uncertainty."""
    lowered = value.lower()
    if 'failed' in lowered:
        return 10
    if any(word in lowered for word in ('disconnected', 'retry', 'reconnecting',
                                        'unavailable', 'invalid', 'unknown',
                                        'no reply', '--', 'inactive', 'deactivating')):
        return 1
    return 7


def paint(screen, states, error='', connection='Connecting to Mac…', health=UNKNOWN, selection=''):
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
        text(1, 2, connection, curses.color_pair(diagnostic_pair(connection)))
        text(2, 2, health[0], curses.color_pair(diagnostic_pair(health[0])))
        text(3, 2, health[1], curses.color_pair(diagnostic_pair(health[1])))
        text(5, 2, f'Session: {selection or "_"}  ·  Type 1–10 + Enter')
        text(6, 2, 's: Shell  q: Quit  F12: Back from sessions')
        for n in range(1, 11):
            text(7+n, 2, f'{n:2}: {states.get(str(n), "unknown").title()}')
        text(19, 2, error, curses.color_pair(1))
        screen.refresh()
        return
    width = min(23, (cols-12)//3)
    left = max(1, (cols-(width*3+9))//2)
    text(0, left, 'P I  D E S K', curses.color_pair(4) | curses.A_BOLD)
    text(1, left, connection, curses.color_pair(diagnostic_pair(connection)))
    text(2, left, health[0], curses.color_pair(diagnostic_pair(health[0])))
    text(3, left, health[1], curses.color_pair(diagnostic_pair(health[1])))
    y = 5
    for numbers in GROUPS.values():
        for col, number in enumerate(numbers):
            state = states.get(str(number), 'unknown')
            color = curses.color_pair(STATES.index(state)+1)
            x = left + 5 + col*(width+2)
            border = curses.color_pair(8)
            text(y, x, '╭'+'─'*(width-2)+'╮', border)
            for row in (y+1, y+2):
                text(row, x, '│'+' '*(width-2)+'│', border)
            text(y+1, x+3, str(number), curses.color_pair(9) | curses.A_BOLD)
            text(y+2, x+2, '●', color)
            text(y+2, x+4, state.title(), curses.color_pair(7))
            text(y+3, x, '╰'+'─'*(width-2)+'╯', border)
        y += 5 if rows >= 29 else 4
    text(y, left, f'Session: {selection or "_"}  ·  Type 1–10 + Enter', curses.color_pair(9))
    text(y+1, left, error or 'Opens its group · s Shell · q Quit · F12 Menu',
         curses.color_pair(1) if error else curses.A_DIM)
    screen.refresh()


def main(screen):
    curses.curs_set(0)
    curses.use_default_colors()
    # Unknown amber, Running green, Idle purple, New cyan, Compacting blue, Offline grey.
    for i, color in enumerate((179, 77, 141, 80, 75, 245), 1):
        curses.init_pair(i, color if curses.COLORS >= 256 else i % 7 + 1, -1)
    # Muted text, subtle borders, bright numbers, explicit failure red.
    for i, color, fallback in ((7, 245, curses.COLOR_WHITE), (8, 239, curses.COLOR_WHITE),
                               (9, 252, curses.COLOR_WHITE), (10, 203, curses.COLOR_RED)):
        curses.init_pair(i, color if curses.COLORS >= 256 else fallback, -1)
    screen.timeout(250)
    feed = StatusFeed()
    monitor = HealthMonitor(HOST)
    choice = SessionChoice()
    error = ''
    previous = None
    try:
        while True:
            states = feed.poll()
            health = monitor.poll()
            signature = (tuple(sorted(states.items())), screen.getmaxyx(), error, feed.connection, health, choice.value)
            if signature != previous:
                paint(screen, states, error, feed.connection, health, choice.value)
                previous = signature
            key = screen.getch()
            if key in (ord('q'), ord('Q')):
                return
            selected = choice.press(key)
            if key != -1:
                error = choice.error
            if selected is not None:
                feed.close()
                curses.def_prog_mode()
                curses.endwin()
                try:
                    result = open_workspace(selected)
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
