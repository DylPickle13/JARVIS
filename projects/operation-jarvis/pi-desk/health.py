"""Bounded, read-only macOS host health checks, off the UI thread.

No backend state, radio scanning, SSH connections, sudo, or persistent logs.
Pi Desk hosts are macOS only; other platforms report diagnostics unavailable.
"""
import os
import platform

from backend import load
import subprocess
import threading
import time

INTERVAL = 10
MAX_AGE = 25
UNKNOWN = ('Host diagnostics unavailable', 'Load: --')


def output(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def unknown():
    return ('macOS | Host diagnostics unavailable', 'Load: --') if platform.system() == 'Darwin' else UNKNOWN


def collect(host):
    if platform.system() != 'Darwin':
        return UNKNOWN
    mode = load().mode
    return (f'macOS | Sessions: {"local" if mode == "local" else "SSH to " + host}',
            f'Load: {os.getloadavg()[0]:.2f}')


class HealthMonitor:
    def __init__(self, host):
        self.host = host
        self.lock = threading.Lock()
        self.busy = False
        self.next_check = 0
        self.updated = None
        self.lines = unknown()

    def sample(self):
        try:
            lines = collect(self.host)
        except Exception:
            # Diagnostic failure must never take down the session menu.
            lines = unknown()
        with self.lock:
            self.lines = lines
            self.updated = time.monotonic()
            self.busy = False

    def poll(self):
        now = time.monotonic()
        with self.lock:
            if not self.busy and now >= self.next_check:
                self.busy = True
                self.next_check = now + INTERVAL
                threading.Thread(target=self.sample, daemon=True).start()
            return self.lines if self.updated is not None and now-self.updated <= MAX_AGE else unknown()
