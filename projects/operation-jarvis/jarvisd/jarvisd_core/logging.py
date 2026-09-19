"""Private bounded operational logging, independent of HTTP and adapters."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
from typing import Callable

MAX_LOG_LINE_CHARS = 4096


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that keeps every active/backup log owner-only."""

    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream

    def handleError(self, _record):  # noqa: N802
        # Logging must never recurse through redirected stderr or stop jarvisd
        # when the disk is temporarily unavailable.
        return


class BoundedLogWriter:
    """Small stderr-compatible writer backed by bounded rotating files."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        self._handler = _PrivateRotatingFileHandler(
            self.path,
            mode="a",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger = logging.Logger(f"jarvisd.bounded.{id(self)}", level=logging.INFO)
        self._logger.propagate = False
        self._logger.addHandler(self._handler)

    def write(self, value: str) -> int:
        if not value:
            return 0
        for line in value.rstrip("\n").splitlines():
            if not line:
                continue
            if len(line) > MAX_LOG_LINE_CHARS:
                line = line[: MAX_LOG_LINE_CHARS - 1] + "…"
            self._logger.info("%s", line)
        return len(value)

    def flush(self) -> None:
        self._handler.flush()

    def close(self) -> None:
        self._handler.close()
        self._logger.handlers.clear()

    def isatty(self) -> bool:
        return False


class RoutineRequestLogGate:
    """Coalesce repetitive successful read logs while retaining a count."""

    def __init__(
        self,
        interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 128,
    ):
        self.interval = interval
        self.clock = clock
        self.max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], tuple[float, int]] = {}

    def record(self, client: str, path: str) -> tuple[bool, int]:
        now = self.clock()
        key = (client, path)
        with self._lock:
            previous = self._entries.get(key)
            if previous is None:
                if len(self._entries) >= self.max_entries:
                    oldest = min(self._entries, key=lambda item: self._entries[item][0])
                    self._entries.pop(oldest, None)
                self._entries[key] = (now, 0)
                return True, 0
            last_logged, suppressed = previous
            if now - last_logged >= self.interval:
                self._entries[key] = (now, 0)
                return True, suppressed
            self._entries[key] = (last_logged, suppressed + 1)
            return False, 0
