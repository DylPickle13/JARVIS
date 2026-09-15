"""Conservative local backoff, not a claim about VeSync's throttle duration.

No scheduled retries. An explicit read may probe recovery early. The shared
nonblocking lock serializes CLI/daemon cloud sessions using the same auth path.
"""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import tempfile
import time


class CooldownError(RuntimeError):
    pass


def is_rate_limit(exc: Exception) -> bool:
    return (getattr(exc, "status", None) == 429 or getattr(exc, "status_code", None) == 429
            or any(term in str(exc).lower() for term in ("rate limit", "too many requests", "request_high", "-11003000")))


def _load(path: Path) -> tuple[float, int]:
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            until, failures = raw["until"], raw["failures"]
        else:  # Existing epoch-only cooldown files remain readable.
            until, failures = raw, 1
        if isinstance(until, bool) or not isinstance(until, (int, float)) or not math.isfinite(until) or until < 0:
            raise ValueError()
        if type(failures) is not int or failures < 0 or failures > 100:
            raise ValueError()
        return float(until), failures
    except FileNotFoundError:
        return 0.0, 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CooldownError("Cannot read VeSync cooldown; refusing cloud calls") from exc


def _save(path: Path, until: float, failures: int) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"until": until, "failures": failures}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)  # tempfile is private (0600); never expose partial JSON.
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def cloud_request(auth_path: Path, *, retry: bool = False):
    cooldown = auth_path.with_name(".vesync_cooldown")
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(auth_path.with_name(".vesync_request.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CooldownError("Another VeSync request is in progress; no cloud call made") from exc
        until, failures = _load(cooldown)
        remaining = until - time.time()
        if remaining > 0 and not retry:
            raise CooldownError(f"VeSync local backoff: {math.ceil(remaining)} seconds remaining; an owner-authorized status recovery read can probe earlier")
        try:
            yield
        except Exception as exc:
            if is_rate_limit(exc):
                failures = min(failures + 1, 100)
                delay = min(300 * 2 ** min(failures - 1, 4), 3600)
                # Honour a structured server-provided retry delay when exposed.
                guidance = getattr(exc, "retry_after", None)
                try:
                    guidance = float(guidance)
                    if math.isfinite(guidance) and guidance > 0:
                        delay = max(delay, guidance)
                except (TypeError, ValueError):
                    pass
                _save(cooldown, time.time() + delay, failures)
            raise
        else:
            cooldown.unlink(missing_ok=True)
