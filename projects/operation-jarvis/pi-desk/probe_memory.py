#!/usr/bin/env python3
"""Isolated Pi Desk memory diagnostic. No real viewers, feeds, agents, or UI."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import select
import struct
import subprocess
import sys
import termios
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import core
import desktop
import tmux_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('actual', 'responsive', 'legacy', 'plain', 'rgb', 'palette'), default='actual')
    parser.add_argument('--frames', type=int, default=1600)
    parser.add_argument('--detached', action='store_true')
    parser.add_argument('--delay', type=float, default=0)
    parser.add_argument('--tmux', type=Path, help='Explicit build for this isolated probe only')
    parser.add_argument('--assert-plateau', action='store_true',
                        help='Fail if growth after 800 warm-up frames exceeds 2 MiB')
    args = parser.parse_args()
    if args.frames < 1200 and args.assert_plateau:
        parser.error('--assert-plateau requires at least 1200 frames')
    if args.tmux is not None:
        binary = args.tmux.resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            parser.error('--tmux must be an executable file')
        tmux_runtime.executable = lambda: str(binary)
    # Every mutation is confined to a new diagnostic socket.
    token = 'pd-memory-audit-' + uuid.uuid4().hex
    core.SOCKET = desktop.SOCKET = token
    name = 'viewer-' + uuid.uuid4().hex
    env = dict(os.environ, TERM='xterm-256color')
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    command = tmux_runtime.command(token)
    child = None
    master = slave = None
    stop = threading.Event()
    drained = [0]
    worker = None
    states = {str(n): 'running' if n in (7, 9) else 'idle' for n in range(1, 11)}
    quota = {'status': 'live', 'weekly': {'remainingPercent': 78, 'resetAt': None},
             'fiveHour': {'remainingPercent': None, 'resetAt': None}, 'fiveHourEnforced': None}

    def run(*parts):
        return subprocess.run(command + list(parts), env=env, capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()

    def footprint(pid):
        out = subprocess.run(['footprint', '-p', str(pid), '--noCategories', '-f', 'bytes'],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        match = re.search(r'phys_footprint:\s*([\d,]+)', out)
        rss = int(subprocess.check_output(['ps', '-p', str(pid), '-o', 'rss='], text=True)) * 1024
        return {'footprint_bytes': int(match.group(1).replace(',', '')) if match else out,
                'rss_bytes': rss, 'drained_bytes': drained[0]}

    try:
        run('-f', str(ROOT / 'config/tmux.conf'), 'new-session', '-d', '-s', name,
            '-x', '184', '-y', '45', 'sleep 240', ';',
            'set-option', '-t', name, '@pi-desk-capacity', '3', ';',
            'set-option', '-t', name, '@pi-desk-session', '8', ';',
            'set-option', '-t', name, '@pi-desk-first', '7', ';',
            'set-option', '-t', name, '@pi-desk-end', '9')
        pid = int(run('display-message', '-p', '-t', name, '#{pid}'))
        if not args.detached:
            master, slave = os.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 184, 0, 0))
            child = subprocess.Popen(command + ['-T', 'hyperlinks', 'attach-session', '-t', '=' + name],
                                     stdin=slave, stdout=slave, stderr=slave, env=env)
            def drain():
                while not stop.is_set():
                    if not select.select([master], [], [], .1)[0]:
                        continue
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    drained[0] += len(data)
            worker = threading.Thread(target=drain, daemon=True)
            worker.start()
            for _ in range(100):
                if str(child.pid) in run('list-clients', '-F', '#{client_pid}').splitlines():
                    break
                time.sleep(.01)
            else:
                raise RuntimeError('Diagnostic PTY attach failed')
        session_rows = f'{name}\t184\t3\t8\n'
        previous = {}
        previous_global = None
        started = time.monotonic()
        print(json.dumps({'mode': args.mode, 'attached': not args.detached, 'pid': pid,
                          'frames': 0, 'seconds': 0, **footprint(pid)}), flush=True)
        warmup = None
        measured = []
        for frame in range(args.frames):
            if args.mode == 'actual':
                rows = (desktop.selector(states, frame=frame, quota=quota), '')
                previous = desktop.render_viewers(states, frame, previous, '',
                    session_rows=session_rows, global_rows=rows,
                    previous_global_rows=previous_global, quota=quota)
                previous_global = rows
            elif args.mode in ('responsive', 'legacy'):
                header = (desktop.responsive_selector(states, 184, 3, 8, frame=frame, quota=quota)
                          if args.mode == 'responsive' else desktop.selector(states, frame=frame, quota=quota))
                desktop.apply_status_commands([['set-option', '-t', name, 'status-format[0]', header]])
            else:
                fg, bg = ('#D183E8', '#1e1e1e') if args.mode == 'rgb' else ('colour141', 'colour234')
                header = str(frame % 10) if args.mode == 'plain' else f'#[fg={fg},bg={bg}] PI-DESK {desktop.SPINNER_FRAMES[frame % 10]}'
                desktop.apply_status_commands([['set-option', '-t', name, 'status-format[0]', header]])
            if args.delay:
                time.sleep(args.delay)
            if (frame + 1) % 400 == 0 or frame + 1 == args.frames:
                reading = footprint(pid)
                if frame + 1 == 800:
                    warmup = reading['footprint_bytes']
                if frame + 1 > 800:
                    measured.append(reading['footprint_bytes'])
                print(json.dumps({'mode': args.mode, 'attached': not args.detached, 'pid': pid,
                                  'frames': frame + 1, 'seconds': round(time.monotonic()-started, 2),
                                  **reading}), flush=True)
        time.sleep(1)
        print(json.dumps({'mode': args.mode, 'idle_after': True, **footprint(pid)}), flush=True)
        if args.assert_plateau:
            growth = max(measured) - warmup
            print(json.dumps({'post_warmup_growth_bytes': growth,
                              'plateau_pass': growth <= 2 * 1024 * 1024}), flush=True)
            if growth > 2 * 1024 * 1024:
                raise RuntimeError('Guarded updates have not reached a memory plateau')
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        # Only this fresh diagnostic server, never the installed viewer.
        subprocess.run(command + ['kill-server'], env=env, capture_output=True, timeout=5)
        stop.set()
        if worker is not None:
            worker.join(timeout=1)
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)
        socket = Path(os.environ.get('TMUX_TMPDIR', '/tmp')) / f'tmux-{os.getuid()}' / token
        socket.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
