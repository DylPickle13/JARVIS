#!/usr/bin/env python3
"""Mac-side fixed-host SSH collector. No new network listener or Pi API token."""
import json
import math
import os
import subprocess
import selectors
import time
from listener import ROOT, atomic_json

COMMAND = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ConnectTimeout=4', '-o', 'ServerAliveInterval=3',
           '-o', 'ServerAliveCountMax=1', 'raspberrypi',
           '/home/pi/.local/share/jarvis-presence/venv/bin/python /home/pi/.local/share/jarvis-presence/pi_export.py']


def normalize(raw, elapsed, now):
    age = raw['ageSeconds']
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0 or not 0 <= age + elapsed <= 15:
        raise ValueError('Stale snapshot')
    state, sources = raw['state'], raw['sources']
    if state not in ('nearby', 'away', 'unknown') or not isinstance(sources, list) or any(s not in ('watch', 'iphone') for s in sources):
        raise ValueError('Invalid snapshot')
    reason = raw['reason']
    if reason not in ('ble-proximity', 'not-enrolled', 'awaiting-placement', 'listener-unavailable'):
        raise ValueError('Invalid reason')
    return {'state': state, 'sources': sources, 'updatedAt': now-age-elapsed, 'reason': reason}


def collect():
    started = time.monotonic()
    result = subprocess.run(COMMAND, capture_output=True, timeout=8, check=True)
    if len(result.stdout) > 16384:
        raise ValueError('Oversized snapshot')
    return normalize(json.loads(result.stdout), time.monotonic()-started, time.time())


def main():
    os.umask(0o077)
    while True:
        process = None
        try:
            command = [*COMMAND[:-1], COMMAND[-1] + ' --rpc']
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, bufsize=0)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    started = time.monotonic()
                    process.stdin.write(b'status\n')
                    raw = b''
                    while not raw.endswith(b'\n'):
                        remaining = 8-(time.monotonic()-started)
                        if remaining <= 0 or not selector.select(remaining):
                            raise TimeoutError()
                        chunk = os.read(process.stdout.fileno(), 16385-len(raw))
                        if not chunk:
                            raise EOFError()
                        raw += chunk
                        if len(raw) > 16384:
                            raise ValueError('Oversized snapshot')
                    state = normalize(json.loads(raw), time.monotonic()-started, time.time())
                    atomic_json(ROOT / 'living-room.json', state)
                    time.sleep(3)
        except Exception:
            atomic_json(ROOT / 'living-room.json', {'state': 'unknown', 'sources': [],
                        'updatedAt': time.time(), 'reason': 'listener-unavailable'})
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process.stdin.close()
                process.stdout.close()
        time.sleep(15)


if __name__ == '__main__':
    main()
