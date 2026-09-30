#!/usr/bin/env python3
"""Persistent tmux selector with an optional warning row; no extra pane."""
import fcntl
import os
from pathlib import Path
import subprocess
import signal
import shlex
import sys
import tempfile
import threading
import time

import workspace
from layout import RESIZE_DELAY, capacity, group as session_members, shape
from health import HealthMonitor
from backend import clean_environment
from core import ROOT, SOCKET, StatusFeed, GROUPS, ensure_group, session_group, tmux, prepare_workspace

STATE = Path.home() / '.local/state/pi-desk'
COLORS = {'running': 77, 'idle': 141, 'new': 80, 'compacting': 75,
          'offline': 245, 'unknown': 179}
PULSE_PHASE_SECONDS = 0.75
VIEWER_STATUS_FORMAT = ('#{session_name}\t#{window_width}\t'
                        '#{@pi-desk-capacity}\t#{@pi-desk-session}')
FOCUS_FORMAT = ('#{session_name}\t#{window_width}\t#{@pi-desk-capacity}\t'
                '#{@pi-desk-min-columns}\t#{@pi-desk-changing}\t#{window_index}\t'
                '#{P:#{pane_index}:#{@pi-desk-session}:#{pane_dead}|}')


def ready_focus(number, details):
    """Validate live pane order/liveness and current sizing policy, never a cache."""
    if len(details) != 7:
        return False
    _, width, count, minimum, changing, window, actual = details
    if not all(value.isdecimal() for value in (width, count, minimum)):
        return False
    count, minimum = int(count), int(minimum)
    if count not in (1, 2, 3) or not 20 <= minimum <= 300:
        return False
    return (changing == '0' and window == '0'
            and capacity(int(width), count, minimum) == count
            # tmux's pane loop may iterate by pane ID, not pane index. Match
            # indexed entries rather than mistaking loop order for visual order.
            and sorted(actual.split('|')) == sorted(shape(session_members(number, count)).split('|')))


def viewer_attach_command(group, environ=None):
    """Advertise OSC 8 per viewer, not for every xterm-256color terminal."""
    environ = os.environ if environ is None else environ
    command = ['tmux', '-L', SOCKET]
    if environ.get('TERM_PROGRAM') == 'vscode':
        command += ['-T', 'hyperlinks']
    return command + ['attach-session', '-t', '=' + group]


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
        if client is not None:
            details = tmux('display-message', '-p', '-t', match[2],
                           FOCUS_FORMAT).stdout.rstrip('\n').split('\t')
            if len(details) >= 2 and workspace.is_viewer(details[0]):
                group = details[0]
                if ready_focus(number, details):
                    index = session_members(number, int(details[2])).index(number)
                    tmux('select-pane', '-t', f'{group}:0.{index}', ';',
                         'set-option', '-g', '@pi-desk-last', str(number))
                    save_selection(number, publish=False)
                else:
                    workspace.reconcile(group, number, int(details[1]))
                    save_selection(number)
                return group
        key, index = session_group(number)
        group = f'group-{key}'
        existing = tmux('list-panes', '-t', f'{group}:0', '-F',
                        '#{@pi-desk-session}:#{pane_dead}', check=False)
        if existing.returncode or existing.stdout.splitlines() != [f'{n}:0' for n in GROUPS[key]]:
            group = ensure_group(key)
        tmux('select-pane', '-t', f'{group}:0.{index}')
        if client is not None:
            tmux('switch-client', '-c', client, '-t', '=' + group)
        save_selection(number)
    return group


def write_selection(value):
    # Caller holds selection.lock; avoid rewriting an unchanged selection.
    if value not in tuple(str(n) for n in range(1, 11)):
        return
    target = STATE / 'last-session'
    if target.exists() and target.read_text().strip() == value:
        return
    temporary = STATE / 'last-session.tmp'
    temporary.write_text(value + '\n')
    os.replace(temporary, target)


def save_selection(number, publish=True):
    # Focus-only navigation already publishes in the same queue as select-pane.
    if publish:
        tmux('set-option', '-g', '@pi-desk-last', str(number))
    write_selection(str(number))


def pulse_is_dim(now=None):
    now = time.monotonic() if now is None else now
    return bool(int(now / PULSE_PHASE_SECONDS) % 2)


def selector(states, *, pulse_dim=False):
    parts = ['#[align=left,norange,fg=#D183E8,bg=#1e1e1e,nobold] PI-DESK ']
    for n in range(1, 11):
        key, _ = session_group(n)
        group = '#{==:#{session_name},group-' + key + '}'
        active = '#{==:#{@pi-desk-session},' + str(n) + '}'
        background = '#{?' + group + ',#16252a,#1e1e1e}'
        foreground = '#{?' + active + ',##D183E8,colour252}'
        weight = '#{?' + active + ',bold,nobold}'
        state = states.get(str(n))
        color = COLORS.get(state, COLORS['unknown'])
        # Pulse only working dots; never blink text, selection, or idle sessions.
        if pulse_dim:
            color = {'running': 22, 'compacting': 24}.get(state, color)
        parts.append(f'#[range=user|{n},bg={background},fg={foreground},{weight}] {n:02d} '
                     f'#[fg=colour{color}]● #[norange,bg=#1e1e1e,nobold]')
        if n in (3, 6, 9):
            parts.append('#[fg=colour238] │ ')
        elif n != 10:
            parts.append(' ')
    parts.append('#[align=right,norange,fg=colour245,bg=#1e1e1e,nobold] '
                 '#{?#{>=:#{client_width},120},'
                 'F12 Select · F10 Restart · Ctrl + ←/→ Switch,'
                 'F12 · F10 · Ctrl + ←/→} ')
    return ''.join(parts)


def responsive_selector(states, width, count, selected, *, pulse_dim=False):
    """Fit actual terminal cells; retain clickable numbers even on tiny displays."""
    width = max(1, width)
    compact = width < 100
    brand = ' PI-DESK ' if width >= 30 else ''
    tab_width = 4 if compact else 6
    separator = '│' if compact else ' │ '
    boundaries = tuple(n for n in range(1, 10) if count > 1 and n % count == 0)
    total = len(brand) + 10 * tab_width + len(boundaries) * len(separator)
    numbers = list(range(1, 11))
    overflow = total > width
    if width < 4:
        numbers, boundaries, overflow = [selected], (), False
    elif overflow:
        # Reserve cells for explicit hidden-tab indicators; omit group separators.
        available = max(1, (width - len(brand) - 2) // tab_width)
        first = max(1, min(selected - available // 2, 11 - available))
        numbers = list(range(first, min(11, first + available)))
        boundaries = ()
    parts = [f'#[align=left,norange,fg=#D183E8,bg=#1e1e1e,nobold]{brand}']
    used = len(brand)
    if overflow and numbers[0] > 1 and used + len(numbers) * tab_width < width:
        parts.append('#[fg=colour245]‹')
        used += 1
    for n in numbers:
        active = '#{==:#{@pi-desk-session},' + str(n) + '}'
        visible = '#{&&:#{e|>=:' + str(n) + ',#{@pi-desk-first}},#{e|<=:' + str(n) + ',#{@pi-desk-end}}}'
        bg = '#{?' + visible + ',#16252a,#1e1e1e}'
        fg = '#{?' + active + ',##D183E8,colour252}'
        weight = '#{?' + active + ',bold,nobold}'
        state = states.get(str(n))
        color = COLORS.get(state, COLORS['unknown'])
        if pulse_dim:
            color = {'running': 22, 'compacting': 24}.get(state, color)
        # Below four columns show just the selected number (no clipped dot).
        label = f'{n:02d}' if width >= 2 else str(n % 10)
        dot = '' if width < 4 else f'#[fg=colour{color}]● '
        text = label if compact else f' {label} '
        parts.append(f'#[range=user|{n},bg={bg},fg={fg},{weight}]{text}{dot}'
                     '#[norange,bg=#1e1e1e,nobold]')
        used += len(text) + (2 if dot else 0)
        if n in boundaries:
            parts.append('#[fg=colour238]' + separator)
            used += len(separator)
    if overflow and numbers[-1] < 10 and used < width:
        parts.append('#[fg=colour245]›')
        used += 1
    for hint in (' F12 Select · F10 Restart · Ctrl + ←/→ Switch ',
                 ' F12 · F10 · Ctrl + ←/→ ', ' F12 Select ', ''):
        if len(hint) + used <= width:
            parts.append('#[align=right,norange,fg=colour245,bg=#1e1e1e,nobold]' + hint)
            break
    return ''.join(parts)


def apply_status_commands(commands):
    if not commands:
        return
    # Several full headers can exceed tmux's argv message-size limit. A private
    # command file batches every write without truncating headers or extra clients.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tmux') as stream:
        stream.write('\n'.join(shlex.join(command) for command in commands) + '\n')
        stream.flush()
        tmux('source-file', stream.name)


def render_viewers(states, dim, previous, warning=None, *, session_rows=None, global_rows=None):
    # A local tmux array shadows the entire global array, not just index 0.
    if warning is None:
        warning = (global_rows[1] if global_rows is not None else
                   tmux('show-options', '-gv', 'status-format[1]').stdout.rstrip('\n'))
    if session_rows is None:
        session_rows = tmux('list-sessions', '-F', VIEWER_STATUS_FORMAT).stdout
    commands = []
    if global_rows is not None:
        commands.extend([
            ['set-option', '-g', 'status-format[0]', global_rows[0]],
            ['set-option', '-g', 'status-format[1]', global_rows[1]],
            ['set-option', '-g', 'status', '2' if global_rows[1] else 'on'],
        ])
    current = {}
    for row in session_rows.splitlines():
        fields = row.split('\t')
        if len(fields) != 4:
            continue
        name, width, count, selected = fields
        if (not workspace.is_viewer(name) or not all(v.isdecimal() for v in fields[1:])
                or int(count) not in (1, 2, 3) or int(selected) not in range(1, 11)):
            continue
        bar = responsive_selector(states, int(width), int(count), int(selected), pulse_dim=dim)
        current[name] = (bar, warning)
        if previous.get(name) != current[name]:
            writes = [['set-option', '-t', name, 'status-format[0]', bar],
                      ['set-option', '-t', name, 'status-format[1]', warning]]
            # A viewer may close after the snapshot. Guard at execution time so
            # its disappearance cannot abort updates for the surviving viewers.
            exists = '#{S:#{?#{==:#{session_name},' + name + '},1,}}'
            commands.append(['if-shell', '-F', exists,
                             ' ; '.join(shlex.join(command) for command in writes)])
    apply_status_commands(commands)
    return current


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
    return f'#[align=left,norange,bg=#1e1e1e,fg=colour{color},nobold]{text}'


def render_status(rows):
    # One queue keeps both rows and their count together, with one client spawn.
    tmux('set-option', '-g', 'status-format[0]', rows[0], ';',
         'set-option', '-g', 'status-format[1]', rows[1], ';',
         'set-option', '-g', 'status', '2' if rows[1] else 'on')


def persist_selection(*, include_viewers=False):
    # Native key events update one server option synchronously. Sample and write
    # under the recovery lock; optionally fetch viewer metadata in the same client.
    with (STATE / 'selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if include_viewers:
            output = tmux('display-message', '-p', '#{@pi-desk-last}', ';',
                          'list-sessions', '-F', VIEWER_STATUS_FORMAT).stdout
            value, _, session_rows = output.partition('\n')
        else:
            value = tmux('show-options', '-gv', '@pi-desk-last', check=False).stdout.strip()
            session_rows = None
        write_selection(value)
        return session_rows


def configuration_version():
    import hashlib
    digest = hashlib.sha256(str(ROOT).encode())
    for name in ('desktop.py', 'native_navigation.py', 'core.py', 'layout.py',
                 'workspace.py', 'navigate.py', 'config/tmux.conf'):
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
    viewer_rows = {}
    try:
        while not stop.is_set():
            try:
                session_rows = persist_selection(include_viewers=True)
                # One shared monitor drives a 0.75-second-per-phase brightness cycle.
                # Static states produce identical rows, so they cause no extra writes.
                states, dim = feed.poll(), pulse_is_dim()
                rows = (selector(states, pulse_dim=dim),
                        health_line(feed.connection, health.poll()))
                viewer_rows = render_viewers(states, dim, viewer_rows, rows[1],
                    session_rows=session_rows, global_rows=rows if rows != previous else None)
                previous = rows
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                feed.close()
                previous = None
                viewer_rows = {}
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


def terminal_size():
    try:
        return os.get_terminal_size(sys.stdin.fileno())
    except (OSError, ValueError):
        return os.terminal_size((184, 45))


def resize_viewer(client_pid, expected_size=None):
    """Read tmux's latest size/focus, not the dimensions of a stale resize event."""
    with (STATE / 'selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        clients = tmux('list-clients', '-F',
                       '#{client_pid}\t#{session_name}\t#{client_width}\t#{client_height}').stdout.splitlines()
        match = next((row.split('\t') for row in clients
                      if row.split('\t', 1)[0] == str(client_pid)), None)
        if match is None:
            return False  # Initial attach may not yet be registered.
        if expected_size is not None and tuple(map(int, match[2:4])) != tuple(expected_size):
            return False  # tmux has not handled SIGWINCH yet; do not lose the event.
        if workspace.is_viewer(match[1]):
            workspace.reconcile(match[1], None, int(match[2]))
        return True


def watch_dimensions(stop, client_pid):
    # Query the parent terminal directly: no subprocess polling during idle use,
    # and no Python process per resize event. tmux still handles pane geometry.
    pending = None
    applied = None
    changed_at = 0
    while not stop.wait(.05):
        size = terminal_size()
        if size != pending:
            pending, changed_at = size, time.monotonic()
        if pending != applied and time.monotonic() - changed_at >= RESIZE_DELAY:
            try:
                if resize_viewer(client_pid, pending):
                    applied = pending
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                # Leave the size pending for recovery; never restart an agent.
                changed_at = time.monotonic() + .5


def attach_viewer(group):
    """Own only this display client; reap it on terminal hangup or termination."""
    child = None
    handlers = {}
    resize_stop = threading.Event()
    resize_worker = None

    def interrupted(number, frame):
        raise SystemExit(128 + number)

    try:
        for number in (signal.SIGHUP, signal.SIGTERM):
            handlers[number] = signal.signal(number, interrupted)
        child = subprocess.Popen(
            viewer_attach_command(group),
            env=clean_environment(),
        )
        if workspace.is_viewer(group):
            resize_worker = threading.Thread(target=watch_dimensions,
                args=(resize_stop, child.pid), daemon=True)
            resize_worker.start()
        return child.wait()
    finally:
        resize_stop.set()
        # Ignore repeated shutdown signals while reaping our own child. Never
        # signal the server, a process group, or any hosted agent.
        for number in handlers:
            signal.signal(number, signal.SIG_IGN)
        try:
            if resize_worker is not None:
                resize_worker.join(timeout=10)
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
    prepare_workspace()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    size = terminal_size()
    with (STATE / 'selection.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        group = workspace.create(last_session(), size.columns, size.lines)
    stop = threading.Event()
    worker = None
    try:
        configure()
        worker = threading.Thread(target=monitor, args=(stop,), daemon=True)
        worker.start()
        return attach_viewer(group)
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=12)
        try:
            persist_selection()
        finally:
            workspace.destroy(group)


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
