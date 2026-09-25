#!/usr/bin/env python3
"""Low-startup-cost arrow navigation; full recovery is imported only if needed."""
import fcntl
import os
import subprocess
import sys


def step(direction, client_pid, socket='pi-desk', state=None):
    if direction not in (-1, 1) or type(client_pid) is not int:
        raise ValueError('Invalid navigation request')
    state = state or os.path.expanduser('~/.local/state/pi-desk')
    os.makedirs(state, mode=0o700, exist_ok=True)
    env = os.environ.copy()
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '/usr/bin:/bin')

    def tmux(*args):
        return subprocess.run(['tmux', '-L', socket, *args], env=env,
                              capture_output=True, text=True, check=True, timeout=3).stdout

    fallback = False
    with open(os.path.join(state, 'selection.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = tmux('list-clients', '-F', 'C\t#{client_pid}\t#{client_name}\t#{@pi-desk-session}',
                    ';', 'list-panes', '-a', '-F',
                    'P\t#{session_name}\t#{pane_index}\t#{@pi-desk-session}\t#{pane_dead}').splitlines()
        clients = [row.split('\t') for row in rows if row.startswith('C\t')]
        match = next((row for row in clients if row[1] == str(client_pid)), None)
        if match is None or not match[3].isdigit() or not 1 <= int(match[3]) <= 10:
            raise ValueError('Display client is unavailable')
        number = max(1, min(10, int(match[3]) + direction))
        key = (number - 1) // 3 + 1
        group = f'group-{key}'
        expected = [f'P\t{group}\t{i}\t{n}\t0'
                    for i, n in enumerate(range((key - 1) * 3 + 1, min(key * 3, 10) + 1))]
        actual = [row for row in rows if row.startswith(f'P\t{group}\t')]
        if actual != expected:
            fallback = True
        else:
            tmux('select-pane', '-t', f'{group}:0.{(number - 1) % 3}',
                 ';', 'switch-client', '-c', match[2], '-t', '=' + group,
                 ';', 'set-option', '-g', '@pi-desk-last', str(number))
            temporary = os.path.join(state, 'last-session.tmp')
            with open(temporary, 'w') as output:
                output.write(str(number) + '\n')
            os.replace(temporary, os.path.join(state, 'last-session'))
    if fallback:
        # Re-read the current selection under the recovery path's own lock.
        import desktop
        desktop.choose(client_pid=client_pid, step=direction)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('Expected direction and client')
        step(int(sys.argv[1]), int(sys.argv[2]))
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit(1)
