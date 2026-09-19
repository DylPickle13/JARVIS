"""Bounded process-local write admission. No queue, retry, expiry, or replay."""
from contextlib import contextmanager
import threading


class AdmissionError(ValueError):
    """A request was rejected before adapter execution (HTTP 409)."""


class WriteAdmission:
    def __init__(self, max_active: int = 32):
        if type(max_active) is not int or max_active < 1:
            raise ValueError("max_active must be a positive integer")
        self._max_active = max_active
        self._lock = threading.Lock()
        self._active: set[tuple[str, str]] = set()

    @contextmanager
    def hold(self, resource: tuple[str, str]):
        # Only server-resolved resource keys enter here, never caller paths or
        # private selectors in diagnostics. A stuck adapter keeps its slot; we
        # must not release by elapsed time while a write could still be running.
        with self._lock:
            if resource in self._active:
                raise AdmissionError("A change is already in progress for this device; nothing was sent.")
            if len(self._active) >= self._max_active:
                raise AdmissionError("Device control is busy; nothing was sent.")
            self._active.add(resource)
        try:
            yield
        finally:
            with self._lock:
                self._active.remove(resource)
