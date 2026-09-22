#!/usr/bin/env python3
"""Persistent two-row tmux selector; no extra pane or remote layout changes."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import threading

from health import HealthMonitor
from core import ROOT, SOCKET, HOST, StatusFeed, GROUPS, ensure_group, session_group, tmux

STATE = Path.home() / '.local/state/pi-desk'
COLORS = {'running': 77, 'idle': 141, 'new': 80, 'compacting': 75,
          'offline': 245, 'unknown': 179}


def session_number(value):
    if value not in tuple(str(n) for n in range(1, 11)):
        raise ValueError('Choose a session from 1 to 10')
    return int(value)


def last_session():
    try:
        return session_number((STATE / 'last-session').read_text().strip())
    except (OSError, ValueError):
        return 1


def choose(number=None, client_pid=None, step=None):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Serialize rapid mouse clicks and pane reconciliation.
    with (STATE / 'selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        client = None
        if client_pid is not None:
            clients = tmux('list-clients', '-F', '#{client_pid}\t#{client_name}\t#{pane_id}').stdout.splitlines()
            match = next((row.split('\t') for row in clients
                          if row.split('\t', 1)[0] == str(client_pid)), None)
            if match is None:
                raise ValueError('Display client is no longer connected')
            client = match[1]
            if step is not None:
                current = session_number(tmux('display-message', '-p', '-t', match[2],
                                              '#{@pi-desk-session}').stdout.strip())
                number = max(1, min(10, current + step))
        key, index = session_group(number)
        group = f'group-{key}'
        existing = tmux('list-panes', '-t', f'{group}:0', '-F',
                        '#{@pi-desk-session}:#{pane_dead}', check=False)
        if existing.returncode or existing.stdout.splitlines() != [f'{n}:0' for n in GROUPS[key]]:
            group = ensure_group(key)
        tmux('select-pane', '-t', f'{group}:0.{index}')
        if client is not None:
            tmux('switch-client', '-c', client, '-t', '=' + group)
        temporary = STATE / 'last-session.tmp'
        temporary.write_text(str(number) + '\n')
        os.replace(temporary, STATE / 'last-session')
    return group


def selector(states):
    parts = ['#[norange,fg=colour80,bg=#000000,nobold] PI DESK ']
    for n in range(1, 11):
        key, _ = session_group(n)
        group = '#{==:#{session_name},group-' + key + '}'
        active = '#{==:#{@pi-desk-session},' + str(n) + '}'
        background = '#{?' + group + ',#16252a,#000000}'
        foreground = '#{?' + active + ',cyan,colour252}'
        weight = '#{?' + active + ',bold,nobold}'
        color = COLORS.get(states.get(str(n)), COLORS['unknown'])
        parts.append(f'#[range=user|{n},bg={background},fg={foreground},{weight}] {n} '
                     f'#[fg=colour{color}]● #[norange,bg=#000000,nobold] ')
    parts.append('#[fg=colour245] F12: select · Ctrl+←/→: session')
    return ''.join(parts)


def health_line(connection, health):
    # All displayed values come from our bounded, label-only collectors.
    summary = connection.replace('Mac connected · Session status ', 'Status: ')
    text = f' {summary} | {health[0]} | {health[1]}'
    # Escape format introducers, even though collectors currently emit no '#'.
    text = text.replace('#', '##').replace('\n', ' ')
    warning = any(s in text.lower() for s in (
        'disconnected', 'unavailable', 'unknown', 'no reply', '--', 'retry',
        'invalid', 'inactive', 'reconnecting', 'deactivating',
    ))
    color = 203 if 'failed' in text.lower() else 179 if warning else 245
    return f'#[norange,bg=#000000,fg=colour{color},nobold]{text}'


def configure():
    tmux('source-file', str(ROOT / 'config/tmux.conf'))
    tmux('set-option', '-g', 'status-format[0]', selector({}))
    tmux('set-option', '-g', 'status-format[1]', '#[fg=colour245] Connecting…')


def monitor(stop):
    feed, health = StatusFeed(), HealthMonitor(HOST)
    previous = None
    try:
        while not stop.is_set():
            try:
                rows = (selector(feed.poll()), health_line(feed.connection, health.poll()))
                if rows != previous:
                    for index, row in enumerate(rows):
                        tmux('set-option', '-g', f'status-format[{index}]', row)
                    previous = rows
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                feed.close()
                previous = None
            stop.wait(.5)
    finally:
        feed.close()


def main():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'display.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Pi Desk is already running')
        group = choose(last_session())
        configure()
        stop = threading.Event()
        worker = threading.Thread(target=monitor, args=(stop,), daemon=True)
        worker.start()
        try:
            return subprocess.run(
                ['tmux', '-L', SOCKET, 'attach-session', '-t', '=' + group],
                check=False,
            ).returncode
        finally:
            stop.set()
            worker.join(timeout=12)


def dispatch(args):
    if not args:
        return main()
    if len(args) != 3 or args[0] not in ('select', 'click', 'step'):
        return 2
    action, value, client = args
    if action == 'click':
        try:
            session_number(value)
        except ValueError:
            return 0  # Health readings and blank status-bar space are not buttons.
    try:
        if action in ('select', 'click'):
            choose(session_number(value), int(client))
        else:
            if value not in ('-1', '1'):
                raise ValueError('Invalid navigation direction')
            choose(client_pid=int(client), step=int(value))
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired):
        # Never expose remote output or inject data into a coding pane.
        tmux('display-message', 'Pi Desk: selection unavailable; retry with F12', check=False)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(dispatch(sys.argv[1:]))
