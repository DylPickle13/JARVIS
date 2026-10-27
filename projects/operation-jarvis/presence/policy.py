"""Shared Mac/Pi proximity policy; no Bluetooth or import-time I/O."""
import json
import math
import os
import time

DEPARTURE_SECONDS = 10
# Owner-requested arrival confirmation: a device that is not already within its
# nearby hold must stay qualifying across readings at least this far apart, with
# no weak reading or long gap between, before it can report nearby. A one-off
# strong advertisement therefore never starts the 10-second hold on its own.
CONFIRM_SECONDS = 3
CONFIRM_GAP = 15


class Presence:
    def __init__(self, devices, started=None):
        self.started = time.monotonic() if started is None else started
        self.devices = devices
        # alias -> (smooth, at, active, last_near, candidate_since)
        self.samples = {}
        self.events = []  # Bounded private diagnostics drained by the listener.

    def _event(self, now, kind, alias, smooth):
        self.events.append({'kind': kind, 'source': alias, 'rssi': round(smooth, 1), 'monotonic': now})
        del self.events[:-64]

    def observe(self, address, rssi, now):
        if not isinstance(rssi, (int, float)) or not math.isfinite(rssi) or not -127 <= rssi <= -1:
            return
        for alias, config in self.devices.items():
            if address.upper() != config['uuid']:
                continue
            old = self.samples.get(alias)
            recent = old is not None and now-old[1] <= CONFIRM_GAP
            smooth = old[0]*.65+rssi*.35 if old is not None and now-old[1] <= 15 else rssi
            last_near = old[3] if old else None
            held = last_near is not None and now-last_near < DEPARTURE_SECONDS
            # Exit hysteresis applies only to an already-confirmed nearby device.
            active = smooth >= (config['exitRssi'] if held else config['enterRssi'])
            candidate = None
            if active and held:
                last_near = now
            elif active:
                candidate = old[4] if recent and old[2] and old[4] is not None else now
                if now-candidate >= CONFIRM_SECONDS:
                    last_near, candidate = now, None
                    self._event(now, 'confirmed', alias, smooth)
            elif old is not None and old[4] is not None:
                self._event(now, 'rejected-spike', alias, smooth)
            self.samples[alias] = (smooth, now, active, last_near, candidate)

    def snapshot(self, now):
        sources = [alias for alias, s in self.samples.items()
                   if s[3] is not None and now-s[3] < DEPARTURE_SECONDS]
        state = 'nearby' if sources else ('away' if self.devices and now-self.started >= DEPARTURE_SECONDS else 'unknown')
        return {'state': state, 'sources': sorted(sources), 'updatedAt': time.time()}

    def rssi(self):
        """Smoothed RSSI by alias for the private local log; never published."""
        return {alias: round(s[0], 1) for alias, s in sorted(self.samples.items())}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    os.replace(temporary, path)


def append_log(path, entry, keep=1000):
    """Owner-requested bounded private transition log (0600, local only)."""
    lines = []
    try:
        lines = path.read_text().splitlines()[-(keep - 1):]
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('\n'.join(lines + [json.dumps(entry)]) + '\n')
    os.replace(temporary, path)
