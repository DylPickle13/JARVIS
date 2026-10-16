"""Deterministic local jarvisd liveness probe and persisted incident state.

No daemon imports, device reads, notification sends, or service actions. The
scheduler commits each state transition with its result/notification outbox.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import fcntl
import http.client
import json
import math
import os
from pathlib import Path
import socket
import threading
import time
from typing import Iterator

HOST = "127.0.0.1"
PORT = 8790
HEALTH_PATH = "/health"
PROBE_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 4096
FAILURE_THRESHOLD_SECONDS = 300.0
MAX_OBSERVATION_GAP_SECONDS = 150.0
MAX_CLOCK_DRIFT_SECONDS = 5.0
STATE_VERSION = 1


def probe() -> str | None:
    """Return a bounded failure reason, or None for HTTP 200 / {ok: true}.

    Explicit loopback HTTP bypasses proxies and never follows redirects. A
    socket-shutdown deadline also bounds slow/trickling headers and bodies,
    unlike a socket's per-read timeout alone.
    """
    connection = http.client.HTTPConnection(HOST, PORT, timeout=PROBE_TIMEOUT_SECONDS)
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
    expired = threading.Event()
    timer = None
    response = None
    try:
        connection.connect()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        sock = connection.sock
        sock.settimeout(remaining)

        def expire() -> None:
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection.request("GET", HEALTH_PATH, headers={"Accept": "application/json", "Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            return f"HTTP {response.status}"
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if expired.is_set() or time.monotonic() >= deadline:
            return "timeout"
        if len(body) > MAX_RESPONSE_BYTES:
            return "response too large"
        if response.length not in (None, 0):
            return "incomplete response"
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            return "invalid JSON"
        return None if isinstance(payload, dict) and payload.get("ok") is True else "ok not true"
    except TimeoutError:
        return "timeout"
    except ConnectionRefusedError:
        return "connection refused"
    except (OSError, http.client.HTTPException):
        return "timeout" if expired.is_set() else "connection error"
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        if response is not None:
            response.close()
        connection.close()


@dataclass(frozen=True)
class State:
    last_wall: float | None = None
    last_monotonic: float | None = None
    first_failure_wall: float | None = None
    first_failure_monotonic: float | None = None
    alerted: bool = False
    last_error: str | None = None

    def encode(self) -> str:
        return json.dumps({"version": STATE_VERSION, **asdict(self)}, sort_keys=True, allow_nan=False)

    @classmethod
    def decode(cls, raw: str | None) -> State:
        if raw is None:
            return cls()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
            version = payload.pop("version")
            if type(version) is not int or version != STATE_VERSION:
                raise ValueError
            if set(payload) != set(cls.__dataclass_fields__):
                raise ValueError
            state = cls(**payload)
            for value in (state.last_wall, state.last_monotonic,
                          state.first_failure_wall, state.first_failure_monotonic):
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError
            if type(state.alerted) is not bool:
                raise ValueError
            if (state.last_wall is None) != (state.last_monotonic is None):
                raise ValueError
            if (state.first_failure_wall is None) != (state.first_failure_monotonic is None):
                raise ValueError
            if state.first_failure_wall is not None:
                if (state.last_wall is None or state.first_failure_wall > state.last_wall
                        or state.first_failure_monotonic > state.last_monotonic):
                    raise ValueError
            if state.alerted and state.first_failure_wall is None:
                raise ValueError
            if (state.last_error is None) != (state.first_failure_wall is None):
                raise ValueError
            if state.last_error is not None and (not isinstance(state.last_error, str)
                                                or len(state.last_error) > 80):
                raise ValueError
            return state
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
            # Never silently clear an incident latch on corrupt/unknown state.
            raise ValueError("jarvisd health monitor state is invalid") from exc


def observe(previous: State, error: str | None, *, wall: float, monotonic: float) -> tuple[State, str]:
    """Advance one observation; emit output only for an outage or recovery."""
    if error is None:
        recovered = "jarvisd is responding normally again." if previous.alerted else ""
        return State(last_wall=wall, last_monotonic=monotonic), recovered

    continuous = False
    if previous.last_wall is not None:
        wall_gap = wall - previous.last_wall
        monotonic_gap = monotonic - previous.last_monotonic
        continuous = (0 <= wall_gap <= MAX_OBSERVATION_GAP_SECONDS
                      and 0 <= monotonic_gap <= MAX_OBSERVATION_GAP_SECONDS
                      and abs(wall_gap - monotonic_gap) <= MAX_CLOCK_DRIFT_SECONDS)
    first_wall, first_monotonic = wall, monotonic
    if continuous and previous.first_failure_monotonic is not None:
        first_wall = previous.first_failure_wall
        first_monotonic = previous.first_failure_monotonic
    state = State(wall, monotonic, first_wall, first_monotonic, previous.alerted, error)
    if not state.alerted and monotonic - first_monotonic >= FAILURE_THRESHOLD_SECONDS:
        return replace(state, alerted=True), f"jarvisd has failed health checks for at least 5 minutes ({error})."
    # Even after sleep/reboot/clock changes, retain an existing incident latch
    # until a healthy observation; uncertain time never creates a second alert.
    return state, ""


@contextmanager
def exclusive_check(path: Path) -> Iterator[bool]:
    """Process-owned lock; OS releases it on exit, with no stale-lock timeout."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
