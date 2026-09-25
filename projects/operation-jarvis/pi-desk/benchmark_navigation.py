#!/usr/bin/env python3
"""Isolated PTY-input to first terminal-output benchmark; NOT screen latency.

Uses this directory's config/native bindings and dummy panes, never agent data.
Run on each platform with Python 3.9+ and tmux in PATH.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import statistics
import struct
import subprocess
import termios
import time
import uuid

from desktop import selector
from native_navigation import install


def main():
    socket = 'pi-desk-bench-' + uuid.uuid4().hex
    master = slave = client = None

    def tmux(*args):
        return subprocess.run(['tmux', '-L', socket, *args], check=True,
                              capture_output=True, text=True, timeout=10)

    try:
        for group, numbers in enumerate(([1, 2, 3], [4, 5, 6], [7, 8, 9], [10]), 1):
            name = f'group-{group}'
            tmux('-f', '/dev/null', 'new-session', '-d', '-s', name,
                 '-x', '190', '-y', '55', 'sleep 180')
            for _ in numbers[1:]:
                tmux('split-window', '-h', '-t', name, 'sleep 180')
                tmux('select-layout', '-t', name, 'even-horizontal')
            for index, number in enumerate(numbers):
                tmux('set-option', '-p', '-t', f'{name}:0.{index}',
                     '@pi-desk-session', str(number))
        tmux('source-file', str(Path(__file__).resolve().parent / 'config/tmux.conf'))
        install(tmux)
        tmux('set-option', '-g', 'status-format[0]',
             selector({str(n): 'idle' for n in range(1, 11)}))
        # Eliminate periodic status redraws as a source of false measurements.
        tmux('set-option', '-g', 'status-interval', '0')
        tmux('select-pane', '-t', 'group-1:0.0')
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 55, 190, 0, 0))
        env = dict(os.environ, TERM='xterm-256color')
        env.pop('TMUX', None)
        client = subprocess.Popen(['tmux', '-L', socket, 'attach-session', '-t', '=group-1'],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env=env, start_new_session=True)
        os.set_blocking(master, False)

        def drain(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if select.select([master], [], [], max(0, end - time.monotonic()))[0]:
                    os.read(master, 1048576)

        drain(.5)
        viewer = tmux('list-clients', '-F', '#{client_name}').stdout.strip()
        samples = []
        current = 1
        for lap in range(2):
            for direction in (1, -1):
                for _ in range(9):
                    target = current + direction
                    drain(.08)
                    start = time.perf_counter_ns()
                    os.write(master, b'\x1b[1;5C' if direction == 1 else b'\x1b[1;5D')
                    if not select.select([master], [], [], 2)[0]:
                        raise RuntimeError('No terminal output within two seconds')
                    if not os.read(master, 1048576):
                        raise RuntimeError('Terminal closed')
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    focus = tmux('display-message', '-p', '-c', viewer,
                                 '#{@pi-desk-session}').stdout.strip()
                    if focus != str(target):
                        raise RuntimeError(f'Focus {focus!r}, expected {target}')
                    samples.append({'lap': lap + 1, 'ms': round(elapsed, 3),
                                    'kind': 'cross-group' if (current - 1) // 3 != (target - 1) // 3
                                    else 'within-group'})
                    current = target

        def summarize(rows):
            values = sorted(row['ms'] for row in rows)
            return {'n': len(values), 'min_ms': min(values),
                    'median_ms': round(statistics.median(values), 3),
                    'max_ms': max(values)}

        print(json.dumps({'method': __doc__.split('\n')[0],
                          'all': summarize(samples),
                          **{kind: summarize([s for s in samples if s['kind'] == kind])
                             for kind in ('within-group', 'cross-group')},
                          'samples': samples}, indent=2))
    finally:
        # Only our unique, isolated socket; never pi-desk or jarvis-mobile.
        subprocess.run(['tmux', '-L', socket, 'kill-server'], capture_output=True, timeout=10)
        if client is not None:
            try:
                client.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # A detached PTY client can be stopped by terminal job control
                # on macOS; SIGTERM cannot finish it while stopped.
                client.kill()
                client.wait(timeout=3)
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)


if __name__ == '__main__':
    main()
