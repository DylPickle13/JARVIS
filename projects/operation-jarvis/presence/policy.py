"""Shared Mac/Pi proximity policy; no Bluetooth or import-time I/O."""
import json
import math
import os
import time

DEPARTURE_SECONDS = 10


class Presence:
    def __init__(self, devices, started=None):
        self.started = time.monotonic() if started is None else started
        self.devices = devices
        self.samples = {}

    def observe(self, address, rssi, now):
        if not isinstance(rssi, (int, float)) or not math.isfinite(rssi) or not -127 <= rssi <= -1:
            return
        for alias, config in self.devices.items():
            if address.upper() != config['uuid']:
                continue
            old = self.samples.get(alias)
            smooth = rssi if old is None or now-old[1] > 15 else old[0]*.65+rssi*.35
            active = smooth >= (config['exitRssi'] if old and old[2] else config['enterRssi'])
            last_near = now if active else (old[3] if old else None)
            self.samples[alias] = (smooth, now, active, last_near)

    def snapshot(self, now):
        sources = [alias for alias, s in self.samples.items()
                   if s[3] is not None and now-s[3] < DEPARTURE_SECONDS]
        state = 'nearby' if sources else ('away' if self.devices and now-self.started >= DEPARTURE_SECONDS else 'unknown')
        return {'state': state, 'sources': sorted(sources), 'updatedAt': time.time()}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    os.replace(temporary, path)
