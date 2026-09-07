#!/usr/bin/env python3
"""Future-only, content-free Pi completion alerts. Never creates Jobs results.

Invoked once for a fresh successful settled turn by the local lifecycle extension.
An independent owner-only receipt DB stores identifiers/outcomes, never tokens.
No startup scan, historical replay, or retry after uncertain transmission.
"""
from __future__ import annotations

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


def deliver(*, event_id: str, slot: int, store: sqlite3.Connection,
            registry: sqlite3.Connection, provider, gate, invalidate,
            now=time.time, sleep=time.sleep, configuration_failed=lambda: None) -> None:
    """Only a current explicit event is eligible; old receipts are never drained."""
    if str(uuid.UUID(event_id)) != event_id or type(slot) is not int or not 1 <= slot <= 9:
        raise ValueError("invalid completion identity")
    if not gate():
        return
    started = int(now())
    devices = registry.execute(
        "SELECT platform,installation_id FROM notification_devices WHERE active=1 ORDER BY platform"
    ).fetchall()
    for initial in devices:
        if not gate():
            return
        platform, installation = initial[0], initial[1]
        if platform not in {"iphone", "watch"}:
            continue
        request_id = str(uuid.uuid4())
        with store:
            inserted = store.execute(
                "INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?)",
                (event_id, platform, slot, "claimed", request_id, started),
            ).rowcount
        if inserted != 1:
            continue
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
            # signal never retries a possibly transmitted request.
            with store:
                store.execute("UPDATE receipts SET state='ambiguous' WHERE event_id=? AND platform=?",
                              (event_id, platform))
            result = provider.send_session_completion(
                topic=device[0], device_token=device[1], session_id=slot,
                apns_id=request_id, expiration=started + 300,
            )
            if result.invalidate_token:
                invalidate(platform, device[1], result)
            if result.status_code == 403:
                configuration_failed()
                with store:
                    store.execute("UPDATE receipts SET state='failed' WHERE event_id=? AND platform=?",
                                  (event_id, platform))
                return  # fail before attempting another topic
            state = "accepted" if result.outcome == "accepted" else "ambiguous" if result.outcome == "ambiguous" else "failed"
            if result.outcome != "retry" or result.status_code not in {429, 500, 503} or attempt == 3:
                break
            delay = max(1, int(result.retry_after_seconds or (30 * 2 ** attempt)))
            if now() + delay >= started + 300:
                break
            sleep(delay)
        with store:
            store.execute("UPDATE receipts SET state=? WHERE event_id=? AND platform=?",
                          (state, event_id, platform))
    # Bounded receipts; UUIDs from completed older processes are never replayed.
    with store:
        store.execute("DELETE FROM receipts WHERE created_at < ?", (started - 86400,))
        store.execute("DELETE FROM receipts WHERE rowid NOT IN (SELECT rowid FROM receipts ORDER BY rowid DESC LIMIT 1000)")


def main() -> None:
    os.umask(0o077)
    if len(sys.argv) != 4:
        return
    pane, raw_pid, event_id = sys.argv[1:]
    if not raw_pid.isdecimal():
        return
    if str(uuid.UUID(event_id)) != event_id:
        return
    slot = resolve_slot(pane, int(raw_pid))
    if slot is None:
        return
    import runner
    from apns_provider import APNsProvider
    directory = runner.ROOT / ".pi/runtime/session-notifications"
    enabled = directory / "enabled"
    if not enabled.is_file() or enabled.is_symlink():
        return
    directory.chmod(0o700)
    # Serialize duplicate signals for this event, not independent sessions.
    # Lock files contain no data; bound their retention independently.
    for old in directory.glob("event-*.lock"):
        if old.stat().st_mtime < time.time() - 86400:
            old.unlink(missing_ok=True)
    with (directory / f"event-{event_id}.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # lossy notification, never historical backfill
        # Open existing registry only. Never create/migrate the scheduler DB.
        with sqlite3.connect(f"file:{runner.DB_PATH}?mode=rw", uri=True, timeout=3) as registry:
            registry.row_factory = sqlite3.Row
            def gate():
                return enabled.is_file() and runner.notification_dispatch_enabled(registry)
            if not gate():
                return
            configuration = runner._provider_configuration()
            configuration.validate_for_send()
            provider = APNsProvider(configuration)
            def invalidate(platform, token, result):
                with registry:
                    runner._invalidate_notification_device(
                        registry, platform=platform, expected_token=token,
                        reason=result.reason, invalidation_timestamp=result.invalidation_timestamp,
                    )
            with receipts(directory / "receipts.sqlite") as store:
                deliver(event_id=event_id, slot=slot, store=store,
                        registry=registry, provider=provider, gate=gate, invalidate=invalidate,
                        configuration_failed=lambda: enabled.unlink(missing_ok=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never log transport exceptions, device tokens, or provider credentials.
        sys.exit(1)
