"""Small private SQLite incident store and sustained-unavailability detector.

No hardware access. A check means evaluation of current cache health, not a new
radio observation. Only transitions are persisted; no per-poll database writes.
"""
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone


def stamp():
    return datetime.now(timezone.utc).isoformat()


class MonitorStore:
    def __init__(self, path, keys, *, clock=time.monotonic, notifier=None):
        self.keys = tuple(keys)
        if (len(self.keys) > 64 or len(set(self.keys)) != len(self.keys) or
                any(not re.fullmatch(r'[a-zA-Z0-9_/-]{1,100}', key) for key in self.keys)):
            raise ValueError('Invalid monitor configuration')
        self.clock, self.notifier = clock, notifier
        self._lock = threading.RLock()
        self._current = {}
        self._streaks = {}
        path = Path(path)
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Invalid monitoring storage')
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        self._db = sqlite3.connect(str(path), timeout=1, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA journal_mode=DELETE')
        self._db.execute('PRAGMA max_page_count=1024')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS active (monitor TEXT PRIMARY KEY, started_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, monitor TEXT NOT NULL, kind TEXT NOT NULL,
                at TEXT NOT NULL, notification TEXT NOT NULL);
        ''')
        # Removed monitors cannot accumulate open incidents indefinitely.
        with self._db:
            for row in self._db.execute('SELECT monitor FROM active').fetchall():
                if row['monitor'] not in self.keys:
                    self._db.execute('DELETE FROM active WHERE monitor=?', (row['monitor'],))

    def observe(self, observations):
        """One sample per >=30 seconds/key. Three checks spanning >=120s alert.

        Persist before attempting a notification: uncertain delivery is never
        replayed, including after restart. Raw reasons and sensor data are absent.
        """
        now, at = self.clock(), stamp()
        pending = []
        with self._lock:
            for key in self.keys:
                previous = self._current.get(key)
                if previous and now - previous['time'] < 30:
                    continue
                available = observations.get(key) is True
                self._current[key] = {'available': available, 'time': now, 'observedAt': at}
                count, first = self._streaks.get(key, (0, now))
                if count == 0:
                    first = now
                count = 0 if available else count + 1
                self._streaks[key] = (count, now if available else first)
                active = self._db.execute('SELECT 1 FROM active WHERE monitor=?', (key,)).fetchone()
                kind = None
                if available and active:
                    kind = 'recovered'
                elif not available and not active and count >= 3 and now - first >= 120:
                    kind = 'unavailable'
                if kind is None:
                    continue
                notification = 'attempted' if self.notifier is not None else 'disabled'
                with self._db:
                    if kind == 'unavailable':
                        self._db.execute('INSERT INTO active VALUES (?,?)', (key, at))
                    else:
                        self._db.execute('DELETE FROM active WHERE monitor=?', (key,))
                    cursor = self._db.execute('INSERT INTO history(monitor,kind,at,notification) VALUES (?,?,?,?)',
                                              (key, kind, at, notification))
                    pending.append((cursor.lastrowid, kind))
                    self._db.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 1000)')
            # Do not turn monitor history into a second notification service.
        for event_id, kind in pending:
            if self.notifier is None:
                continue
            try:
                accepted = self.notifier(kind) is True
            except Exception:
                accepted = False
            with self._lock, self._db:
                self._db.execute('UPDATE history SET notification=? WHERE id=?',
                                 ('submitted' if accepted else 'failed', event_id))

    def status(self):
        now = self.clock()
        with self._lock:
            active = {row['monitor'] for row in self._db.execute('SELECT monitor FROM active')}
            return {key: {
                'availability': 'available' if self._current.get(key, {}).get('available') is True
                    and now - self._current[key]['time'] <= 90 else 'unavailable',
                'observedAt': self._current.get(key, {}).get('observedAt'),
                'incidentOpen': key in active,
            } for key in self.keys}

    def history(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Invalid history limit')
        with self._lock:
            return [dict(row) for row in self._db.execute(
                'SELECT id,monitor,kind,at,notification FROM history ORDER BY id DESC LIMIT ?', (limit,))]

    def close(self):
        with self._lock:
            self._db.close()
