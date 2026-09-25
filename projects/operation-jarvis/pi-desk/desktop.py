#!/usr/bin/env python3
"""Persistent tmux selector with an optional warning row; no extra pane."""
import fcntl
import os
from pathlib import Path
import subprocess
import signal
import sys
import threading
import time

from health import HealthMonitor
from backend import clean_environment
from core import ROOT, SOCKET, StatusFeed, GROUPS, ensure_group, session_group, tmux, recover_closed_displays

STATE = Path.home() / '.local/state/pi-desk'
COLORS = {'running': 77, 'idle': 141, 'new': 80, 'compacting': 75,
          'offline': 245, 'unknown': 179}
PULSE_PHASE_SECONDS = 0.75


def session_number(value):
    if value not in tuple(str(n) for n in range(1, 11)):
        raise ValueError('Choose a session from 1 to 10')
    return int(value)


def last_session():
    live = tmux('show-options', '-gv', '@pi-desk-last', check=False).stdout.strip()
    if live in tuple(str(n) for n in range(1, 11)):
        return int(live)
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
        tmux('set-option', '-g', '@pi-desk-last', str(number))
        temporary = STATE / 'last-session.tmp'
        temporary.write_text(str(number) + '\n')
        os.replace(temporary, STATE / 'last-session')
    return group


def pulse_is_dim(now=None):
    now = time.monotonic() if now is None else now
    return bool(int(now / PULSE_PHASE_SECONDS) % 2)


def selector(states, *, pulse_dim=False):
    parts = ['#[align=left,norange,fg=colour80,bg=#000000,nobold] PI-DESK ']
    for n in range(1, 11):
        key, _ = session_group(n)
        group = '#{==:#{session_name},group-' + key + '}'
        active = '#{==:#{@pi-desk-session},' + str(n) + '}'
        background = '#{?' + group + ',#16252a,#000000}'
        foreground = '#{?' + active + ',cyan,colour252}'
        weight = '#{?' + active + ',bold,nobold}'
        state = states.get(str(n))
        color = COLORS.get(state, COLORS['unknown'])
        # Pulse only working dots; never blink text, selection, or idle sessions.
        if pulse_dim:
            color = {'running': 22, 'compacting': 24}.get(state, color)
        parts.append(f'#[range=user|{n},bg={background},fg={foreground},{weight}] {n:02d} '
                     f'#[fg=colour{color}]● #[norange,bg=#000000,nobold]')
        if n in (3, 6, 9):
            parts.append('#[fg=colour238] │ ')
        elif n != 10:
            parts.append(' ')
    parts.append('#[align=right,norange,fg=colour245,bg=#000000,nobold] '
                 '#{?#{>=:#{client_width},120},'
                 'F12 Select · F10 Restart · Ctrl + ←/→ Switch,'
                 'F12 · F10 · Ctrl + ←/→} ')
    return ''.join(parts)


def health_line(connection, health):
    # Only unhealthy fields are visible; an empty string removes the entire row.
    summary = connection.replace('Mac connected · Session status ', 'Status: ')
    fields = [summary] + [field.strip() for line in health for field in line.split('|')]
    markers = ('disconnected', 'unavailable', 'unknown', 'no reply', '--', 'retry',
               'invalid', 'inactive', 'connecting', 'activating', 'failed', 'stale')
    warnings = [field for field in fields if any(word in field.lower() for word in markers)]
    if not warnings:
        return ''
    text = (' Warning: ' + ' | '.join(warnings)).replace('#', '##').replace('\n', ' ')
    color = 203 if 'failed' in text.lower() else 179
    return f'#[align=left,norange,bg=#000000,fg=colour{color},nobold]{text}'


def render_status(rows):
    # One queue keeps both rows and their count together, with one client spawn.
    tmux('set-option', '-g', 'status-format[0]', rows[0], ';',
         'set-option', '-g', 'status-format[1]', rows[1], ';',
         'set-option', '-g', 'status', '2' if rows[1] else 'on')


def persist_selection():
    # Native key events update one server option synchronously. Sample under the
    # same lock as recovery; never let queued background writers save old keys.
    with (STATE / 'selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = tmux('show-options', '-gv', '@pi-desk-last', check=False).stdout.strip()
        if value not in tuple(str(n) for n in range(1, 11)):
            return
        target = STATE / 'last-session'
        if target.exists() and target.read_text().strip() == value:
            return
        temporary = STATE / 'last-session.tmp'
        temporary.write_text(value + '\n')
        os.replace(temporary, target)


def configuration_version():
    import hashlib
    digest = hashlib.sha256(str(ROOT).encode())
    for name in ('desktop.py', 'native_navigation.py', 'config/tmux.conf'):
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def configure(force=False):
    # Cache configuration only, never pane health. A new server or changed file
    # invalidates this marker; choose() still validates live panes on every open.
    version = configuration_version()
    if not force and tmux('show-options', '-gv', '@pi-desk-config', check=False).stdout.strip() == version:
        return
    from native_navigation import script
    with script() as path:
        current = tmux('source-file', str(ROOT / 'config/tmux.conf'), ';',
                       'source-file', path, ';',
                       'show-options', '-gv', 'status-format[0]').stdout
    if 'PI-DESK' not in current and 'PI DESK' not in current:
        render_status((selector({}), health_line('Connecting to Mac…', ())))
    else:
        tmux('if-shell', '-F', '#{==:#{status-format[1]},}',
             'set-option -g status on', 'set-option -g status 2')
    # Publish only after every configuration command succeeds.
    tmux('set-option', '-g', '@pi-desk-config', version)


def watch_status(stop):
    feed = StatusFeed()
    health = HealthMonitor(feed.backend.host)
    previous = None
    try:
        while not stop.is_set():
            try:
                persist_selection()
                # One shared monitor drives a 0.75-second-per-phase brightness cycle.
                # Static states produce identical rows, so they cause no extra writes.
                rows = (selector(feed.poll(), pulse_dim=pulse_is_dim()),
                        health_line(feed.connection, health.poll()))
                if rows != previous:
                    render_status(rows)
                    previous = rows
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                feed.close()
                previous = None
            stop.wait(.5)
    finally:
        feed.close()


def monitor(stop):
    # One status stream per machine; another open terminal takes over on exit.
    with (STATE / 'display.lock').open('a') as lock:
        while not stop.is_set():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stop.wait(.5)
                continue
            try:
                watch_status(stop)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            return


def attach_viewer(group):
    """Own only this display client; reap it on terminal hangup or termination."""
    child = None
    handlers = {}

    def interrupted(number, frame):
        raise SystemExit(128 + number)

    try:
        for number in (signal.SIGHUP, signal.SIGTERM):
            handlers[number] = signal.signal(number, interrupted)
        child = subprocess.Popen(
            ['tmux', '-L', SOCKET, 'attach-session', '-t', '=' + group],
            env=clean_environment(),
        )
        return child.wait()
    finally:
        # Ignore repeated shutdown signals while reaping our own child. Never
        # signal the server, a process group, or any hosted agent.
        for number in handlers:
            signal.signal(number, signal.SIG_IGN)
        try:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()  # A job-control-stopped client cannot handle TERM.
                    child.wait(timeout=2)
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)


def main():
    recover_closed_displays()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    group = choose(last_session())
    configure()
    stop = threading.Event()
    worker = threading.Thread(target=monitor, args=(stop,), daemon=True)
    worker.start()
    try:
        return attach_viewer(group)
    finally:
        stop.set()
        worker.join(timeout=12)
        persist_selection()


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
