"""Bounded, read-only Pi health checks, off the curses/UI thread.

No backend state, radio scanning, SSH connections, sudo, or persistent logs.
Ping is diagnostic only: blocked ICMP does not imply the Mac is offline.
"""
from pathlib import Path
import re
import subprocess
import threading
import time

INTERVAL = 10
MAX_AGE = 25
UNKNOWN = ('Wi-Fi -- | Mac ping -- | Pi --', 'Presence service: unknown')


def output(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def collect(host):
    # `iw link` reads the existing association; it does not scan or reconnect.
    link = output(['iw', 'dev', 'wlan0', 'link'])
    signal = re.search(r'signal:\s*(-?\d+)\s*dBm', link)
    wifi = signal.group(1) + ' dBm' if signal else ('disconnected' if 'Not connected.' in link else '--')
    # Resolve the same OpenSSH alias without connecting or displaying SSH config.
    config = output(['ssh', '-G', host])
    hostname = re.search(r'^hostname\s+(\S+)$', config, re.MULTILINE)
    latency = '--'
    if hostname and not hostname.group(1).startswith('-'):
        reply = output(['ping', '-n', '-c', '1', '-W', '1', hostname.group(1)])
        timing = re.search(r'time([=<])([\d.]+)\s*ms', reply)
        latency = (('<' if timing.group(1) == '<' else '') + timing.group(2) + ' ms'
                   if timing else 'no reply')
    temperature = '--'
    try:
        degrees = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
        if 0 <= degrees <= 150:
            temperature = f'{degrees:.0f}°C'
    except (OSError, ValueError):
        pass
    # `show` exits successfully for inactive/failed units too. No BLE identity data.
    state = output(['systemctl', '--user', 'show', 'jarvis-presence.service',
                    '--property=ActiveState', '--value']).strip()
    presence = state if state in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown'
    return (f'Wi-Fi {wifi} | Mac ping {latency} | Pi {temperature}',
            f'Presence service: {presence}')


class HealthMonitor:
    def __init__(self, host):
        self.host = host
        self.lock = threading.Lock()
        self.busy = False
        self.next_check = 0
        self.updated = None
        self.lines = UNKNOWN

    def sample(self):
        try:
            lines = collect(self.host)
        except Exception:
            # Diagnostic failure must never take down the session menu.
            lines = UNKNOWN
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
            return self.lines if self.updated is not None and now-self.updated <= MAX_AGE else UNKNOWN
