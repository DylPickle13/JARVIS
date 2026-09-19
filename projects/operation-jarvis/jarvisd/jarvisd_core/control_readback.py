"""Bounded owner-requested readback scheduling; NEVER mutation replay.

One ordinary read attempt per completed command, once existing single-flight and
purifier spacing allow it. Failed/expired/unmodeled readback retains quarantine.
This module does not implement manual recovery, restart reconstruction or activation.
"""
import threading
import time
from .control_ledger import TTL_NS


class ReadbackQueue:
    def __init__(self, *, host, state, limit=32, monotonic=time.monotonic):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('invalid-readback-capacity')
        self._host, self._state, self._limit, self._now = host, state, limit, monotonic
        self._lock = threading.RLock()
        self._pending = {}
        self._active = {}
        self._closed = False
        self._counts = {'reconciled': 0, 'unresolved': 0, 'unsupported': 0, 'capacity': 0}

    def submit(self, bound):
        """Post-callback owner request only; no IO/collection on the HTTP thread."""
        with self._lock:
            if self._closed:
                return False
            try:
                self._host._binding(bound)
                self._host._expectation(bound)
            except Exception:
                self._counts['unsupported'] += 1
                return False
            if bound.resource in self._pending or any(b.resource == bound.resource for b, _, _ in self._active.values()):
                return False  # Never overwrite another pending proof/command.
            if len(self._pending) + len(self._active) >= self._limit:
                self._counts['capacity'] += 1
                return False  # Refusal, not eviction or barrier clearing.
            self._pending[bound.resource] = bound
            return True

    def _abandon(self, readback):
        try:
            self._host.abandon_reconciliation(readback)
        except Exception:
            pass  # Cleanup failure confers no proof or retry permission.

    def tick(self):
        """Bounded work, no wait/queue for a device mutation. No exception replay."""
        with self._lock:
            if self._closed:
                return
            now = self._now()
            for cohort, (_, readback, deadline) in list(self._active.items()):
                completed = self._state.control_read_completed(readback.fence)
                if now >= deadline:
                    self._abandon(readback)
                    self._counts['unresolved'] += 1
                elif completed:
                    try:
                        self._host.finish_reconciliation(readback)
                        self._counts['reconciled'] += 1
                    except Exception:
                        self._abandon(readback)
                        self._counts['unresolved'] += 1
                else:
                    continue
                del self._active[cohort]
            for resource, bound in list(self._pending.items()):
                cohort = bound.command.cohort.value
                if cohort in self._active or not self._state.control_read_ready(cohort):
                    continue
                readback = None
                started = self._now()
                try:
                    readback = self._host.begin_reconciliation(bound)
                    if not self._state.schedule_control_read(readback.fence):
                        self._abandon(readback)
                        continue  # No read started. Recheck normal scheduling later.
                    self._active[cohort] = (bound, readback, started + TTL_NS / 1_000_000_000)
                except Exception:
                    if readback is not None:
                        self._abandon(readback)
                    self._counts['unresolved'] += 1
                del self._pending[resource]

    def close(self):
        with self._lock:
            self._closed = True
            for _, readback, _ in self._active.values():
                self._abandon(readback)
            self._pending.clear()
            self._active.clear()

    def snapshot(self):
        with self._lock:
            return {**self._counts, 'waiting': len(self._pending), 'reading': len(self._active), 'closed': self._closed}
