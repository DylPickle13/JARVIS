"""Bounded, private chart history. Explicit startup only; no device polling.

Each row is a sampled cached-state evaluation, not a new device observation.
Intervals are capped by freshness, a 90s coverage lease, and process boundaries.
Responses are fixed-resolution buckets preserving failures and missing coverage.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
import uuid

from .system_health import (COMPONENTS, MAX_COMPONENTS, REASONS, SERVICE_ID,
                            STATES, number, project, stamp)

INTERVAL = 60
COVERAGE_LEASE = 90
RETENTION = 7 * 86400
MAX_SAMPLES = RETENTION // INTERVAL + 1
MAX_PAYLOAD = 16 * 1024
PAYLOAD_BUDGET = 24 * 1024 * 1024
MAX_PAGES = 8192  # 32 MiB with the explicitly selected 4 KiB SQLite pages.
WINDOWS = {'1h': (3600, 60), '24h': (86400, 300), '7d': (RETENTION, 1800)}
DEFAULT_SERIES = ('services', 'pi', 'network', 'devices', 'overall')


class HistoryUnavailable(Exception):
    """No private database/filesystem details cross the HTTP boundary."""


def valid_component(key):
    return isinstance(key, str) and (key in COMPONENTS or SERVICE_ID.fullmatch(key) is not None)


def selectors(raw):
    """Strict, bounded query parsing; no refresh, arbitrary ranges or resolution."""
    import urllib.parse
    if len(raw) > 256:
        raise ValueError('Invalid history query')
    try:
        pairs = urllib.parse.parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    except ValueError:
        raise ValueError('Invalid history query') from None
    values = dict(pairs)
    if len(values) != len(pairs) or set(values) - {'window', 'component'}:
        raise ValueError('Invalid history query')
    window, component = values.get('window', '24h'), values.get('component')
    if window not in WINDOWS or (component is not None and not valid_component(component)):
        raise ValueError('Invalid history query')
    return window, component


class HistoryStore:
    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Invalid history storage')
        # Reject symlinks in ancestors too; never chmod someone else's linked path.
        if any(parent.is_symlink() for parent in path.parents):
            raise ValueError('Invalid history storage')
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Invalid history storage')
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(str(path), timeout=0.25, check_same_thread=False)
        try:
            self._db.row_factory = sqlite3.Row
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Unsupported history schema')
            self._db.execute('PRAGMA page_size=4096')
            if self._db.execute('PRAGMA page_size').fetchone()[0] != 4096:
                raise ValueError('Invalid history storage')
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('PRAGMA max_page_count=%d' % MAX_PAGES)
            if self._db.execute('PRAGMA page_count').fetchone()[0] > MAX_PAGES:
                raise ValueError('Invalid history storage')
            with self._db:
                self._db.execute('''CREATE TABLE IF NOT EXISTS samples (
                    checked_ms INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                    payload TEXT NOT NULL, bytes INTEGER NOT NULL)''')
                self._db.execute('PRAGMA user_version=1')
        except Exception:
            self._db.close()
            raise

    @contextmanager
    def _access(self):
        if not self._lock.acquire(timeout=0.05):
            raise HistoryUnavailable()
        try:
            if self._closed:
                raise HistoryUnavailable()
            yield
        finally:
            self._lock.release()

    def append(self, rows, *, at, run_id):
        if (not number(at) or not isinstance(run_id, str) or len(run_id) != 32
                or any(c not in '0123456789abcdef' for c in run_id)
                or not isinstance(rows, dict) or not 1 <= len(rows) <= MAX_COMPONENTS):
            raise ValueError('Invalid history sample')
        clean = {}
        for key, row in rows.items():
            if (not valid_component(key) or not isinstance(row, dict)
                    or row.get('state') not in STATES or row.get('reason') not in REASONS):
                raise ValueError('Invalid history sample')
            source, until = row.get('sourceObservedAt'), row.get('validUntil')
            if ((source is not None and (not number(source) or source > at))
                    or (until is not None and not number(until))):
                raise ValueError('Invalid history sample')
            # Only these four allowlisted fields are persisted, even if callers
            # accidentally attach private errors, paths or raw device payloads.
            clean[key] = {k: row.get(k) for k in ('state', 'reason', 'sourceObservedAt', 'validUntil')}
        payload = json.dumps(clean, sort_keys=True, separators=(',', ':'), allow_nan=False)
        size = len(payload.encode('utf-8')) + 128
        if size > MAX_PAYLOAD:
            raise ValueError('Invalid history sample')
        at_ms = int(at * 1000)
        with self._access(), self._db:
            # Backward clock changes must not overwrite, reorder or bridge data.
            latest = self._db.execute('SELECT checked_ms FROM samples ORDER BY checked_ms DESC LIMIT 1').fetchone()
            if latest and at_ms <= latest[0]:
                raise HistoryUnavailable()
            self._db.execute('DELETE FROM samples WHERE checked_ms < ?', (at_ms - RETENTION * 1000,))
            sizes = self._db.execute('SELECT checked_ms, bytes FROM samples ORDER BY checked_ms').fetchall()
            total, remaining = sum(r['bytes'] for r in sizes) + size, len(sizes) + 1
            # Explicit payload budget leaves space for indexes/pages and journals.
            for old in sizes:
                if total <= PAYLOAD_BUDGET and remaining <= MAX_SAMPLES:
                    break
                self._db.execute('DELETE FROM samples WHERE checked_ms=?', (old['checked_ms'],))
                total -= old['bytes']
                remaining -= 1
            self._db.execute('INSERT INTO samples VALUES (?,?,?,?)', (at_ms, run_id, payload, size))

    def read(self, *, window, component=None, now, run_id):
        if window not in WINDOWS or (component is not None and not valid_component(component)) or not number(now):
            raise ValueError('Invalid history query')
        span, resolution = WINDOWS[window]
        end, start = int(now * 1000), max(0, int((now - span) * 1000))
        with self._access():
            # Include a preceding evaluation so the left edge can be clipped.
            records = self._db.execute('''SELECT checked_ms,run_id,payload FROM samples
                WHERE checked_ms >= ? AND checked_ms <= ? ORDER BY checked_ms LIMIT ?''',
                (start - COVERAGE_LEASE * 1000, end, MAX_SAMPLES)).fetchall()
            earliest = self._db.execute('SELECT MIN(checked_ms) FROM samples').fetchone()[0]
        # JSON parsing/bucketing happens after releasing the DB lock. No collector
        # work, writes, foreground leases, or sampling are performed by reads.
        ids = (component,) if component else DEFAULT_SERIES
        step = resolution * 1000
        count = max(1, math.ceil((end - start) / step))
        by_key = {key: [{'durations': {}, 'reasons': set(), 'source': None} for _ in range(count)] for key in ids}
        found = component in COMPONENTS if component else True
        # Decode one row at a time rather than materializing up to seven days of
        # Python dictionaries. Memory stays bounded by raw DB bytes + buckets.
        for index, record in enumerate(records):
            checked, sample_run = record['checked_ms'], record['run_id']
            rows = json.loads(record['payload'])
            found = found or component in rows
            following = records[index+1] if index+1 < len(records) else None
            base_stop = min(end, checked + COVERAGE_LEASE * 1000)
            if following:
                base_stop = min(base_stop, following['checked_ms'])
                if following['run_id'] != sample_run:
                    base_stop = min(base_stop, checked)
            elif sample_run != run_id:
                base_stop = min(base_stop, checked)
            for key, buckets in by_key.items():
                row = rows.get(key)
                if not row:
                    continue
                stop = base_stop
                if row['state'] in ('healthy', 'inactive'):
                    until = row.get('validUntil')
                    stop = checked if until is None else min(stop, int(until * 1000))
                lo, hi = max(start, checked), stop
                while lo < hi:
                    b = min(count-1, (lo-start)//step)
                    boundary = min(hi, start+(b+1)*step)
                    bucket = buckets[b]
                    bucket['durations'][row['state']] = bucket['durations'].get(row['state'], 0) + boundary-lo
                    bucket['reasons'].add(row['reason'])
                    source = row.get('sourceObservedAt')
                    if source is not None:
                        bucket['source'] = max(bucket['source'] or 0, source)
                    lo = boundary
        if not found:
            raise KeyError('Unknown history component')
        series = []
        for key, buckets in by_key.items():
            points = []
            for index, bucket in enumerate(buckets):
                lo, hi = start+index*step, min(end, start+(index+1)*step)
                durations = bucket['durations']
                covered = sum(durations.values())
                # Worst observed state survives aggregation; missing coverage is
                # also explicit so a partially green bucket cannot appear solid.
                states = list(durations)
                if covered < hi-lo:
                    states.append('unknown')
                state = max(states or ['unknown'], key=STATES.index)
                points.append({'from': stamp(lo/1000), 'to': stamp(hi/1000), 'state': state,
                    'reasonCodes': sorted(bucket['reasons']),
                    'coverageSeconds': round(covered/1000, 3),
                    'stateSeconds': {s: round(ms/1000, 3) for s, ms in sorted(durations.items())},
                    'missingSeconds': round((hi-lo-covered)/1000, 3),
                    'mixed': len(set(states)) > 1,
                    'sourceObservedAt': stamp(bucket['source']) if bucket['source'] is not None else None})
            series.append({'id': key, 'buckets': points})
        return {'ok': True, 'schemaVersion': 1, 'scope': 'cached_status_health',
            'window': window, 'from': stamp(start/1000), 'to': stamp(end/1000),
            'sampleIntervalSeconds': INTERVAL, 'resolutionSeconds': resolution,
            'coverageLeaseSeconds': COVERAGE_LEASE, 'retentionSeconds': RETENTION,
            'earliestSampleAt': stamp(earliest/1000) if earliest is not None else None,
            'latestSampleAt': stamp(records[-1]['checked_ms']/1000) if records else None,
            'series': series}

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._db.close()


class HistoryRecorder:
    """Called by the existing monitor cycle, independently of incident storage."""
    def __init__(self, store, cached_snapshot, *, clock=time.time, monotonic=time.monotonic):
        self.store, self.cached_snapshot = store, cached_snapshot
        self.clock, self.monotonic = clock, monotonic
        self.run_id = uuid.uuid4().hex
        self.storage_available = True
        self._last_tick = None
        self._last_wall = None
        self._closed = False
        self._lock = threading.RLock()
        self._reads = threading.BoundedSemaphore(2)

    def tick(self):
        with self._lock:
            if self._closed:
                return
            mono = self.monotonic()
            if self._last_tick is not None and mono-self._last_tick < INTERVAL:
                return
            self._last_tick = mono
            try:
                try:
                    snapshot = self.cached_snapshot()
                except Exception:
                    snapshot = {'ok': False}
                now = self.clock()
                # A wall-clock jump invalidates the continuity of the run, even
                # if the forward jump is smaller than the coverage lease.
                if self._last_wall is not None and abs((now-self._last_wall[0])-(mono-self._last_wall[1])) > 5:
                    self.run_id = uuid.uuid4().hex
                self._last_wall = (now, mono)
                self.store.append(project(snapshot, now), at=now, run_id=self.run_id)
                self.storage_available = True
            except Exception:
                # Failed writes leave a hole, not a success or a replay backlog.
                self.storage_available = False
                self.run_id = uuid.uuid4().hex

    def read(self, window, component=None):
        # A stalled/stopped recorder's data remains inspectable, with bounded
        # coverage and holes after its last lease, never extended to "now".
        if self._closed or not self.storage_available:
            raise HistoryUnavailable()
        if not self._reads.acquire(blocking=False):
            raise HistoryUnavailable()
        try:
            now, mono, run_id = self.clock(), self.monotonic(), self.run_id
            reference = self._last_wall
            if reference is not None and abs((now-reference[0])-(mono-reference[1])) > 5:
                # A read can notice a clock jump before the next recorder tick.
                # Invalidate the final coverage without sampling/writing or
                # mutating recorder state from an HTTP request.
                run_id = None
            return self.store.read(window=window, component=component, now=now, run_id=run_id)
        finally:
            self._reads.release()

    def close(self):
        with self._lock:
            self._closed = True
            self.store.close()
