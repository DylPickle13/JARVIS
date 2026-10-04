"""Private bounded room-server logging; no file I/O until explicitly configured."""
from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import sys
from typing import Iterator

JARVISD_ROOT = Path(__file__).resolve().parents[1] / "jarvisd"
if str(JARVISD_ROOT) not in sys.path:
    sys.path.insert(0, str(JARVISD_ROOT))

from jarvisd_core.logging import BoundedLogWriter, RoutineRequestLogGate  # noqa: E402,F401


@contextmanager
def bounded_stderr(
    path: Path, *, max_bytes: int, backup_count: int
) -> Iterator[BoundedLogWriter | None]:
    """Redirect Python stderr and existing stderr handlers for this process only.

    Existing logger levels/formatters and non-stderr handlers are preserved.
    Setup failure falls back to launchd stderr without leaking exception details.
    Native writes to OS fd 2 remain in the launchd fallback file.
    """
    original = sys.stderr
    writer = None
    rebound: list[logging.StreamHandler] = []

    def restore() -> None:
        if writer is None:
            return
        if sys.stderr is writer:
            sys.stderr = original
        for handler in rebound:
            if handler.stream is writer:
                try:
                    handler.setStream(original)
                except Exception:
                    # Do not mask a server exception during shutdown.
                    handler.stream = original
        try:
            writer.close()
        except Exception:
            pass

    try:
        writer = BoundedLogWriter(path, max_bytes=max_bytes, backup_count=backup_count)
        loggers = [logging.getLogger(), *[
            item for item in logging.Logger.manager.loggerDict.values()
            if isinstance(item, logging.Logger)
        ]]
        handlers = {handler for logger in loggers for handler in logger.handlers}
        for handler in handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream is original:
                rebound.append(handler)
                handler.setStream(writer)
        sys.stderr = writer
    except Exception:
        restore()
        writer = None
        try:
            original.write("[room-audio] bounded logging unavailable; retaining launchd stderr.\n")
        except Exception:
            pass

    try:
        yield writer
    finally:
        restore()
