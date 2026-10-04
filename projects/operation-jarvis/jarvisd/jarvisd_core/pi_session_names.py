"""Read only explicit Pi session_info names from the current PID-bound file.

No directory/history search, prompt-derived naming, raw-content logging or writes.
Reads and cache size are bounded. Large files warm incrementally; incomplete
samples expose no name rather than presenting a stale or guessed title.
"""
from collections import OrderedDict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import threading
import unicodedata

MAX_NAME_CHARACTERS = 256
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_METADATA_LINE_BYTES = 16 * 1024
MAX_CACHED_FILES = 32
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x061C, 0x200E, 0x200F}
_CANONICAL_NON_NAME = re.compile(rb'^\s*\{\s*"type"\s*:\s*"(?:message|custom|custom_message|compaction|branch_summary|model_change|thinking_level_change|label)"')


def validated_name(value):
    if not isinstance(value, str):
        return None
    # Reject controls before trimming: a title is a single line, not terminal data.
    if any(unicodedata.category(c) in {"Cc", "Cs", "Zl", "Zp"} or ord(c) in _BIDI for c in value):
        return None
    value = value.strip()
    return value if value and len(value) <= MAX_NAME_CHARACTERS else None


def _metadata(line):
    """Return (is name metadata, validated value); a clear never revives old names."""
    if b'"session_info"' not in line:
        return False, None
    try:
        row = json.loads(line)
        if isinstance(row, dict) and row.get("type") == "session_info":
            return True, validated_name(row.get("name"))
    except (ValueError, UnicodeError):
        # An ambiguous malformed metadata candidate cannot prove a previous name.
        return True, None
    return False, None


@dataclass
class _Cursor:
    identity: tuple
    session_id: str
    offset: int
    size: int
    mtime: int
    name: str | None = None
    skipping: bool = False


class PiSessionNameReader:
    def __init__(self):
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def read(self, session_file, *, root):
        if not isinstance(session_file, str) or not session_file or len(session_file) > 4096:
            return None
        path = Path(session_file)
        try:
            if not path.is_absolute() or path.suffix != ".jsonl" or path.is_symlink():
                return None
            path = path.resolve(strict=True)
            if not path.is_relative_to(Path(root).resolve(strict=True)):
                return None
            with self._lock:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as history:
                    before = os.fstat(history.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid():
                        return None
                    header = history.readline(4097)
                    if len(header) > 4096 or not header.endswith(b"\n"):
                        return None
                    row = json.loads(header)
                    if (not isinstance(row, dict) or row.get("type") != "session"
                            or type(row.get("version")) is not int or row.get("version") not in {1, 2, 3}
                            or not isinstance(row.get("id"), str) or not 0 < len(row["id"]) <= 128):
                        return None
                    identity = (before.st_dev, before.st_ino)
                    entry = self._entries.get(path)
                    if (entry is None or entry.identity != identity or entry.session_id != row["id"]
                            or before.st_size < entry.size
                            or (before.st_size == entry.size and before.st_mtime_ns != entry.mtime)):
                        entry = _Cursor(identity, row["id"], len(header), before.st_size, before.st_mtime_ns)
                        # Usually the most recent explicit name is near the end. A
                        # bounded tail probe avoids warming a whole long conversation.
                        start = max(len(header), before.st_size - MAX_READ_BYTES)
                        history.seek(start)
                        tail = history.read(min(MAX_READ_BYTES, before.st_size - start))
                        if start > len(header):
                            tail = tail.partition(b"\n")[2]  # Never parse a partial first record.
                        if tail.endswith(b"\n"):
                            for line in reversed(tail.splitlines()):
                                if len(line) > MAX_METADATA_LINE_BYTES:
                                    if not _CANONICAL_NON_NAME.match(line):
                                        break
                                    continue
                                found, name = _metadata(line)
                                if found:
                                    entry.name = name
                                    entry.offset = before.st_size
                                    break
                    self._entries[path] = entry
                    self._entries.move_to_end(path)
                    while len(self._entries) > MAX_CACHED_FILES:
                        self._entries.popitem(last=False)
                    if entry.offset < before.st_size:
                        history.seek(entry.offset)
                        # Only the new/uninspected suffix is read after warmup.
                        data = history.read(min(MAX_READ_BYTES, before.st_size - entry.offset))
                        position = 0
                        origin = entry.offset
                        while position < len(data):
                            end = data.find(b"\n", position)
                            if end < 0:
                                fragment = data[position:]
                                if entry.skipping or len(fragment) > MAX_METADATA_LINE_BYTES:
                                    if not entry.skipping and not _CANONICAL_NON_NAME.match(fragment):
                                        entry.name = None
                                    entry.skipping = True
                                    entry.offset = origin + len(data)
                                # A short incomplete record is re-read next time;
                                # no prompt/tool/message fragments are cached.
                                break
                            line = data[position:end]
                            if entry.skipping:
                                entry.skipping = False
                            elif len(line) > MAX_METADATA_LINE_BYTES:
                                if not _CANONICAL_NON_NAME.match(line):
                                    entry.name = None
                            else:
                                found, name = _metadata(line)
                                if found:
                                    entry.name = name
                            position = end + 1
                            entry.offset = origin + position
                    entry.size, entry.mtime = before.st_size, before.st_mtime_ns
                    after = os.fstat(history.fileno())
                    named = os.stat(path, follow_symlinks=False)
                    if ((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                            or (named.st_dev, named.st_ino) != identity or stat.S_ISLNK(named.st_mode)):
                        return None
                    return entry.name if entry.offset == before.st_size and not entry.skipping else None
        except (OSError, ValueError, TypeError, UnicodeError):
            with self._lock:
                self._entries.pop(path, None)
            return None
