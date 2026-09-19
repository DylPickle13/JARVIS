"""Bounded event history; disk persistence is an explicit construction option."""
from __future__ import annotations

import collections
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any
import uuid

from .diagnostics import _safe_error

DEFAULT_MAX_JSON_BYTES = 64 * 1024


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


EVENT_FIELDS = {"source", "eventType", "action", "ok", "summary", "error", "artifacts", "data", "at"}
EVENT_STRING_LIMITS = {"source": 120, "eventType": 160, "action": 160, "summary": 2000, "error": 2000, "at": 80}


class EventInputError(ValueError):
    """Raised when an event payload is not safe to persist."""


def _validate_event(payload: Any, *, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES) -> dict:
    if not isinstance(payload, dict):
        raise EventInputError("event body must be a JSON object")
    unknown = set(payload) - EVENT_FIELDS
    if unknown:
        raise EventInputError("event contains unsupported fields")
    event: dict[str, Any] = {}
    for key, value in payload.items():
        if key in EVENT_STRING_LIMITS:
            if value is not None and (not isinstance(value, str) or len(value) > EVENT_STRING_LIMITS[key]):
                raise EventInputError(f"event field {key!r} is invalid or too long")
            event[key] = value
        elif key == "ok":
            if value is not None and not isinstance(value, bool):
                raise EventInputError("event field 'ok' must be boolean or null")
            event[key] = value
        elif key == "artifacts":
            if value is not None and (not isinstance(value, list) or len(value) > 20):
                raise EventInputError("event artifacts must be an array of at most 20 items")
            event[key] = value or []
        elif key == "data":
            if value is not None and not isinstance(value, dict):
                raise EventInputError("event data must be an object or null")
            event[key] = value
    encoded_size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
    if encoded_size > max_json_bytes:
        raise EventInputError("event payload is too large")
    return event


class EventStore:
    def __init__(self, max_events: int = 500, persist_path: Path | None = None,
                 *, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES):
        self._max_json_bytes = max_json_bytes
        self._max_events = max(1, int(max_events))
        self._events: collections.deque[dict] = collections.deque(maxlen=self._max_events)
        self._lock = threading.RLock()
        self._seq = 0
        self._persist_path = persist_path
        if persist_path:
            try:
                persist_path.parent.mkdir(parents=True, exist_ok=True)
                if persist_path.exists():
                    self._load(persist_path)
                    self._rewrite_locked()
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"[jarvisd] event store unavailable: {_safe_error(exc)}\n")
                self._persist_path = None

    def _load(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            continue
                        self._events.append(event)
                        self._seq = max(self._seq, int(event.get("seq", 0)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError:
            return

    def _rewrite_locked(self) -> None:
        if not self._persist_path:
            return
        path = self._persist_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def add(self, payload: dict) -> dict:
        event = _validate_event(payload, max_json_bytes=self._max_json_bytes)
        with self._lock:
            evicted = len(self._events) == self._max_events
            self._seq += 1
            event["seq"] = self._seq
            event.setdefault("receivedAt", _iso_now())
            self._events.append(event)
            if self._persist_path:
                try:
                    if evicted or (self._persist_path.exists() and self._persist_path.stat().st_size > 1024 * 1024):
                        self._rewrite_locked()
                    else:
                        with self._persist_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                except Exception as exc:  # noqa: BLE001
                    sys.stderr.write(f"[jarvisd] could not persist event: {_safe_error(exc)}\n")
            return copy.deepcopy(event)

    def list(self, since: int | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            events = list(self._events)
        if since is not None:
            events = [event for event in events if int(event.get("seq", 0)) > int(since)]
        limit = max(1, min(int(limit), self._max_events))
        return copy.deepcopy(events[-limit:])
