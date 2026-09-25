#!/usr/bin/env python3
"""Isolated multi-viewer terminal probe; no live sockets, agents or transcripts.

Tests independent terminals and overlapping clients on one terminal. All output
is synthetic. Each query is bounded; a failed query fails the probe. Retained PTY
slaves allow bounded emergency flushing of *only* this probe's terminals.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import termios
import time
import uuid


def main():
    socket = 'pi-desk-viewer-probe-' + uuid.uuid4().hex
    terminals = []
    children = []
    results = []

    def tmux(*args):
        return subprocess.run(['tmux', '-L', socket, *args], capture_output=True,
                              text=True, check=True, timeout=3)

    def drain(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            fds = [m for m, s in terminals]
            if not fds:
                return
            ready, _, _ = select.select(fds, [], [], max(0, end - time.monotonic()))
            for fd in ready:
                try:
                    os.read(fd, 65536)
                except OSError:
                    pass

    def spawn(terminal=None, wrapper=False):
        if terminal is None:
            terminal = pty.openpty()
            terminals.append(terminal)
        master, slave = terminal
        os.set_blocking(master, False)
        env = dict(os.environ, TERM='xterm-256color')
        env.pop('TMUX', None)
        if wrapper:
            code = ('import sys;sys.path.insert(0,sys.argv[1]);import desktop;'
                    'desktop.SOCKET=sys.argv[2];'
                    'raise SystemExit(desktop.attach_viewer("test"))')
            command = [sys.executable, '-c', code, str(Path(__file__).resolve().parent), socket]
        else:
            command = ['tmux', '-L', socket, 'attach-session', '-t', '=test']
        # A controlling terminal avoids job-control artefacts from setsid alone.
        def setup():
            os.setsid()
            if terminal not in used_terminals:
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                 env=env, preexec_fn=setup)
        used_terminals.add(terminal)
        children.append(child)
        drain(.3)
        return child, terminal

    def check(label, expected_clients):
        start = time.monotonic()
        clients = tmux('list-clients', '-F', '#{client_pid}').stdout.splitlines()
        assert len(clients) == expected_clients, (label, clients)
        assert tmux('list-panes', '-t', 'test', '-F', '#{pane_pid}').stdout == identity
        results.append({'check': label, 'clients': len(clients),
                        'query_ms': round((time.monotonic() - start) * 1000, 1)})

    def stop(child, sig=signal.SIGTERM):
        child.send_signal(sig)
        # Drain while the client restores terminal state on exit.
        end = time.monotonic() + 3
        while child.poll() is None and time.monotonic() < end:
            drain(.05)
        if child.poll() is None:
            raise RuntimeError('Client failed to exit')
        drain(.2)

    used_terminals = set()
    try:
        tmux('-f', '/dev/null', 'new-session', '-d', '-s', 'test',
             "python3 -c 'import time; [(print(str(i)*100,flush=True),time.sleep(.002)) for i in range(60000)]'")
        identity = tmux('list-panes', '-t', 'test', '-F', '#{pane_pid}').stdout
        one, tty1 = spawn()
        two, tty2 = spawn()
        check('two separate terminals', 2)
        time.sleep(2)
        check('both readers paused', 2)
        drain(.3)
        stop(one)
        check('first viewer exited; second survives', 1)
        three, _ = spawn()
        check('new viewer alongside survivor', 2)
        stop(three)
        stop(two)
        check('all viewers closed; pane preserved', 0)
        four, shared = spawn()
        five, _ = spawn(shared)
        check('two clients sharing a terminal', 2)
        stop(five)
        time.sleep(1)
        check('shared terminal after one exits', 1)
        stop(four)
        check('shared terminal clients closed', 0)
        # Optional source hardening acceptance when present on this platform.
        import desktop
        if hasattr(desktop, 'attach_viewer'):
            for sig in (signal.SIGTERM, signal.SIGHUP):
                viewer, _ = spawn(wrapper=True)
                check('owned viewer attached', 1)
                stop(viewer, sig)
                check('owned viewer reaped after ' + signal.Signals(sig).name, 0)
            viewer, _ = spawn(wrapper=True)
            check('owned viewer before job-control stop', 1)
            client_pid = int(tmux('list-clients', '-F', '#{client_pid}').stdout.strip())
            os.kill(client_pid, signal.SIGSTOP)
            stop(viewer)
            check('stopped owned client reaped after timeout', 0)
        print(json.dumps({'socket': socket, 'checks': results, 'passed': True}, indent=2))
    finally:
        # These descriptors belong solely to this isolated probe.
        for master, slave in terminals:
            try:
                termios.tcflush(slave, termios.TCOFLUSH)
            except (OSError, termios.error):
                pass
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        for master, slave in terminals:
            os.close(master)
            os.close(slave)
        tmux('kill-server')


if __name__ == '__main__':
    main()
