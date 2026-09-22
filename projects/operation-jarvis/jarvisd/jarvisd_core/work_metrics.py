"""Bounded in-memory work counters. Fixed keys only; no payload/error retention."""
import threading
import time


class WorkMetrics:
    def __init__(self, keys, *, clock=time.monotonic):
        keys = tuple(keys)
        if len(keys) > 64:
            raise ValueError('Too many metric keys')
        self.clock = clock
        self._lock = threading.Lock()
        self._rows = {key: dict(started=0, completed=0, failed=0, busy=0,
                               lastSeconds=None, maxSeconds=0.0, totalSeconds=0.0)
                      for key in keys}

    def run(self, key, function, *args, **kwargs):
        started = self.clock()
        with self._lock:
            self._rows[key]['started'] += 1
        ok, busy = False, False
        try:
            result = function(*args, **kwargs)
            body = result[1] if isinstance(result, tuple) and len(result) == 2 else result
            ok = isinstance(body, dict) and body.get('ok') is True
            busy = isinstance(body, dict) and body.get('errorCode') == 'device_busy'
            return result
        finally:
            elapsed = max(0.0, self.clock() - started)
            with self._lock:
                row = self._rows[key]
                row['completed'] += 1
                row['failed'] += int(not ok and not busy)
                row['busy'] += int(busy)
                row['lastSeconds'] = round(elapsed, 4)
                row['maxSeconds'] = round(max(row['maxSeconds'], elapsed), 4)
                row['totalSeconds'] = round(row['totalSeconds'] + elapsed, 4)

    def snapshot(self):
        with self._lock:
            return {key: {**row, 'inFlight': row['started'] - row['completed']}
                    for key, row in self._rows.items()}
