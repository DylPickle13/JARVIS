#!/usr/bin/env python3
"""Explicit Pi notifications; the filename is retained for deployment compatibility.

Only ``--notify`` with a bounded stdin envelope can send. Legacy lifecycle argv
is inert, including from Pi processes that have not reloaded. No startup scan,
Jobs result, content persistence, or replay after uncertain transmission.
"""
from __future__ import annotations

from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

SLOTS = {"jarvis-ios": 1, **{f"jarvis-ios-{i}": i for i in range(2, 10)}}
MAX_REQUEST_BYTES = 16_384
DEVICE_STATES = {"accepted", "failed", "ambiguous", "suppressed"}


def resolve_slot(pane: str, pid: int) -> int | None:
    if not re.fullmatch(r"%[0-9]+", pane) or type(pid) is not int or pid <= 0:
        return None
    result = subprocess.run(
        ["/opt/homebrew/bin/tmux", "-L", "jarvis-mobile", "display-message", "-p", "-t", pane,
         "#{session_name}\t#{pane_pid}\t#{pane_dead}"],
        capture_output=True, text=True, timeout=2, check=False,
    )
    fields = result.stdout.strip().split("\t")
    if result.returncode != 0 or len(fields) != 3 or fields[1] != str(pid) or fields[2] != "0":
        return None
    return SLOTS.get(fields[0])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate notification field")
        result[key] = value
    return result


def decode_request(raw: bytes) -> dict:
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("notification request is too large")
    request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(request, dict) or set(request) != {
        "version", "pane", "pid", "eventID", "title", "message"
    }:
        raise ValueError("invalid notification request")
    if type(request["version"]) is not int or request["version"] != 1:
        raise ValueError("invalid notification version")
    if type(request["pid"]) is not int or request["pid"] <= 0:
        raise ValueError("invalid notification process")
    if not isinstance(request["pane"], str) or not re.fullmatch(r"%[0-9]+", request["pane"]):
        raise ValueError("invalid notification pane")
    validate_event(request["eventID"])
    validate_text(request["title"], request["message"])
    return request


def validate_event(event_id: str) -> None:
    if not isinstance(event_id, str) or str(uuid.UUID(event_id)) != event_id:
        raise ValueError("invalid notification identity")


def validate_text(title: str, message: str) -> None:
    for text, maximum in ((title, 120), (message, 2048)):
        if not isinstance(text, str) or not text.strip() or len(text) > maximum:
            raise ValueError("invalid notification text")


def receipts(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    conn = sqlite3.connect(path, timeout=3)
    path.chmod(0o600)
    conn.execute("""CREATE TABLE IF NOT EXISTS receipts (
        event_id TEXT NOT NULL, platform TEXT NOT NULL, slot INTEGER NOT NULL,
        state TEXT NOT NULL, apns_id TEXT NOT NULL, created_at INTEGER NOT NULL,
        PRIMARY KEY(event_id, platform))""")
    conn.commit()
    return conn


def outcome(devices: list[dict], slot: int) -> dict:
    states = [device["outcome"] for device in devices]
    status = ("accepted" if states and all(state == "accepted" for state in states)
              else "partial" if "accepted" in states
              else "ambiguous" if "ambiguous" in states
              else "failed" if "failed" in states
              else "unavailable")
    return {"ok": status == "accepted", "outcome": status, "sessionID": slot, "devices": devices}


def deliver(*, event_id: str, slot: int, title: str, message: str,
            store: sqlite3.Connection, registry: sqlite3.Connection, provider, gate, invalidate,
            now=time.time, sleep=time.sleep, configuration_failed=lambda: None) -> dict:
    """Only this explicit event is eligible; old receipts are never drained."""
    validate_event(event_id)
    validate_text(title, message)
    if type(slot) is not int or not 1 <= slot <= 9:
        raise ValueError("invalid notification session")
    if not gate():
        return {"ok": False, "outcome": "disabled", "sessionID": slot, "devices": []}
    started = int(now())
    devices = registry.execute(
        "SELECT platform,installation_id FROM notification_devices WHERE active=1 ORDER BY platform"
    ).fetchall()
    outcomes = []
    for initial in devices:
        platform, installation = initial[0], initial[1]
        if platform not in {"iphone", "watch"}:
            continue
        if not gate():
            outcomes.append({"platform": platform, "outcome": "suppressed"})
            continue
        request_id = str(uuid.uuid4())
        with store:
            inserted = store.execute(
                "INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?)",
                (event_id, platform, slot, "claimed", request_id, started),
            ).rowcount
        if inserted != 1:
            previous = store.execute(
                "SELECT state FROM receipts WHERE event_id=? AND platform=?", (event_id, platform)
            ).fetchone()
            state = previous[0] if previous and previous[0] in DEVICE_STATES else "ambiguous"
            outcomes.append({"platform": platform, "outcome": state, "deduplicated": True})
            continue
        state = "failed"
        for attempt in range(4):
            if not gate() or now() >= started + 300:
                state = "suppressed"
                break
            device = registry.execute(
                "SELECT topic,device_token,environment FROM notification_devices "
                "WHERE platform=? AND installation_id=? AND active=1", (platform, installation),
            ).fetchone()
            if device is None or device[2] != provider.configuration.environment:
                state = "suppressed"
                break
            # Commit uncertainty BEFORE transmission. A crash or duplicate
            # tool call never retries a possibly transmitted request.
            with store:
                store.execute("UPDATE receipts SET state='ambiguous' WHERE event_id=? AND platform=?",
                              (event_id, platform))
            try:
                result = provider.send_session_notification(
                    topic=device[0], device_token=device[1], session_id=slot,
                    title=title, message=message, apns_id=request_id, expiration=started + 300,
                )
            except Exception:
                state = "ambiguous"
                break  # never expose exception text or replay an unknown send
            if result.invalidate_token:
                invalidate(platform, device[1], result)
            if result.status_code == 403:
                configuration_failed()
                with store:
                    store.execute("UPDATE receipts SET state='failed' WHERE event_id=? AND platform=?",
                                  (event_id, platform))
                outcomes.append({"platform": platform, "outcome": "failed"})
                return outcome(outcomes, slot)  # fail before attempting another topic
            state = ("accepted" if result.outcome == "accepted"
                     else "ambiguous" if result.outcome == "ambiguous" else "failed")
            if result.outcome != "retry" or result.status_code not in {429, 500, 503} or attempt == 3:
                break
            delay = max(1, int(result.retry_after_seconds or (30 * 2 ** attempt)))
            if now() + delay >= started + 300:
                break
            sleep(delay)
        with store:
            store.execute("UPDATE receipts SET state=? WHERE event_id=? AND platform=?",
                          (state, event_id, platform))
        outcomes.append({"platform": platform, "outcome": state})
    # Bounded identity-only receipts. No notification text or tokens are stored.
    with store:
        store.execute("DELETE FROM receipts WHERE created_at < ?", (started - 86400,))
        store.execute("DELETE FROM receipts WHERE rowid NOT IN (SELECT rowid FROM receipts ORDER BY rowid DESC LIMIT 1000)")
    return outcome(outcomes, slot)


def main() -> dict:
    os.umask(0o077)
    if sys.argv[1:] != ["--notify"]:
        # This must stay inert for the old detached lifecycle helper invocation.
        return {"ok": False, "outcome": "retired", "devices": []}
    try:
        request = decode_request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
    except (ValueError, UnicodeError, TypeError):
        return {"ok": False, "outcome": "invalid", "devices": []}
    slot = resolve_slot(request["pane"], request["pid"])
    if slot is None:
        return {"ok": False, "outcome": "unavailable", "devices": []}
    if __package__:
        from . import runner
        from .apns_provider import APNsConfigurationError, APNsProvider, build_session_notification_payload
    else:
        import runner
        from apns_provider import APNsConfigurationError, APNsProvider, build_session_notification_payload
    # Sanitize before any transport and report whether visible text was adjusted.
    preview = json.loads(build_session_notification_payload(
        slot, title=request["title"], message=request["message"]
    ))["aps"]["alert"]
    adjusted = preview != {"title": request["title"], "body": request["message"]}
    directory = runner.SESSION_NOTIFICATIONS_DIR
    enabled = directory / "enabled"
    def enabled_gate():
        return enabled.is_file() and not enabled.is_symlink()
    if not enabled_gate():
        return {"ok": False, "outcome": "disabled", "sessionID": slot, "devices": []}
    directory.chmod(0o700)
    for old in directory.glob("event-*.lock"):
        if not old.is_symlink() and old.stat().st_mtime < time.time() - 86400:
            old.unlink(missing_ok=True)
    with (directory / f"event-{request['eventID']}.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "outcome": "ambiguous", "sessionID": slot, "devices": []}
        # Open existing registry only. Never create/migrate the scheduler DB.
        with closing(sqlite3.connect(f"file:{runner.DB_PATH}?mode=rw", uri=True, timeout=3)) as registry:
            registry.row_factory = sqlite3.Row
            def gate():
                return enabled_gate() and runner.notification_dispatch_enabled(registry)
            if not gate():
                return {"ok": False, "outcome": "disabled", "sessionID": slot, "devices": []}
            try:
                configuration = runner._provider_configuration()
                configuration.validate_for_send()
            except APNsConfigurationError:
                return {"ok": False, "outcome": "unavailable", "sessionID": slot, "devices": []}
            provider = APNsProvider(configuration)
            def invalidate(platform, token, result):
                with registry:
                    runner._invalidate_notification_device(
                        registry, platform=platform, expected_token=token,
                        reason=result.reason, invalidation_timestamp=result.invalidation_timestamp,
                    )
            store = receipts(directory / "receipts.sqlite")
            try:
                result = deliver(event_id=request["eventID"], slot=slot,
                                 title=preview["title"], message=preview["body"],
                                 store=store, registry=registry, provider=provider, gate=gate,
                                 invalidate=invalidate,
                                 configuration_failed=lambda: enabled.unlink(missing_ok=True))
                result["textAdjusted"] = adjusted
                return result
            finally:
                store.close()


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        # Never log transport exceptions, text, device tokens, or credentials.
        # Conservatively unknown: an error may have occurred after a send.
        result = {"ok": False, "outcome": "ambiguous", "devices": []}
    print(json.dumps(result, separators=(",", ":")))
