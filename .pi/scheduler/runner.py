#!/usr/bin/env python3
"""Private, transport-neutral Pi/JARVIS scheduled-job runner.

The scheduler owns job timing, bounded local result history, and a dormant
carrier-neutral notification outbox. Native clients receive only sanitized
read-only projections through jarvisd. Job prompts, models, local paths, and
credentials never cross that boundary.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

config.load_project_env(ROOT / ".env")
LOGGER = config.get_logger("jarvis.scheduler")

PI_DIR = ROOT / ".pi"
SCHEDULER_DIR = Path(os.environ.get("JARVIS_SCHEDULER_DIR", str(PI_DIR / "scheduler"))).expanduser().resolve()
DB_PATH = Path(os.environ.get("JARVIS_SCHEDULER_DB_PATH", str(SCHEDULER_DIR / "scheduler.sqlite"))).expanduser().resolve()
LEGACY_DB_PATH = Path(
    os.environ.get("JARVIS_LEGACY_SCHEDULER_DB_PATH", str(SCHEDULER_DIR / "migration-source.sqlite"))
).expanduser().resolve()
DEVNULL_PATH = Path("/dev/null")
LAUNCHD_LABEL = "com.jarvis.pi-scheduler"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
DEFAULT_PATH = config.DEFAULT_SCHEDULER_PATH
DIRECT_STDOUT_MODEL = "__direct_stdout__"
PI_FIRST_ENABLED_MODEL = "__pi_first_enabled__"
DAILY_JOB_NAME = "daily-job-search"
DAILY_JOB_ID = "job_ca728bbf8731"
LEGACY_DAILY_JOB_MODELS = ("omlx-64/Qwen3.6-35B-A3B-6bit", "Qwen3.6-35B-A3B-6bit")
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
LOCK_STALE_SECONDS = 20 * 60
MAX_RESULTS = 500
MAX_RESULT_BYTES = 64 * 1024
MAX_RESULT_SUMMARY_CHARS = 280
MAX_RESULT_PAGE = 100
APNS_PROVIDER_ENABLED = os.environ.get("JARVIS_APNS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
APNS_ENVIRONMENT = os.environ.get("JARVIS_APNS_ENVIRONMENT", "development").strip().lower()
APNS_TEAM_ID = os.environ.get("JARVIS_APNS_TEAM_ID", "").strip()
APNS_KEY_ID = os.environ.get("JARVIS_APNS_KEY_ID", "").strip()
APNS_KEY_PATH = Path(os.environ.get("JARVIS_APNS_KEY_PATH", "")).expanduser()
APNS_MAX_DELIVERY_ATTEMPTS = 4
APNS_DELIVERY_EXPIRY_SECONDS = 5 * 60
APNS_PLATFORM_TOPICS = {
    "iphone": "com.operation-jarvis.jarvis",
    "watch": "com.operation-jarvis.jarvis.watchkitapp",
}
APNS_DEVICE_TOKEN_RE = re.compile(r"^[0-9A-Fa-f]{64,200}$")
APNS_INSTALLATION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
DURATION_RE = re.compile(r"^(\+?)(\d+)(s|m|h|d)$", re.I)
ISOISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|api[_ -]?key|authorization)\b\s*([=:])\s*([^\s,;]+)"
)
SECRET_JSON_RE = re.compile(
    r'''(?i)(["'](?:token|secret|password|api[_ -]?key|authorization)["']\s*:\s*["'])(.*?)(["'])'''
)
SENSITIVE_ENV_KEY_RE = re.compile(r"(?i)(?:token|secret|password|api_?key|authorization|cookie|sp_dc|sp_key)")
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
LOCAL_PATH_RE = re.compile(r"(?:/Users/[^\s,;:'\"<>]+|/private/[^\s,;:'\"<>]+|/tmp/[^\s,;:'\"<>]+)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MIGRATION_JOB_COLUMNS = (
    "id",
    "name",
    "schedule",
    "kind",
    "prompt",
    "enabled",
    "model",
    "next_run_at",
    "last_run_at",
    "last_status",
    "run_count",
    "created_at",
    "updated_at",
    "description",
)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime | None = None) -> str:
    return (ts or utcnow()).astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone(dt.timezone.utc)


def _split_env_csv(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))


def secure_database_permissions(path: Path = DB_PATH) -> None:
    for candidate in (path, *(Path(f"{path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)):
        try:
            candidate.chmod(PRIVATE_FILE_MODE)
        except FileNotFoundError:
            pass


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          schedule TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('once','interval','cron')),
          prompt TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          model TEXT,
          next_run_at TEXT,
          last_run_at TEXT,
          last_status TEXT,
          run_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          description TEXT,
          last_silent_success_at TEXT,
          last_output_at TEXT,
          last_error_at TEXT,
          consecutive_errors INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS locks (
          name TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          acquired_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS config (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          id TEXT NOT NULL UNIQUE,
          job_id TEXT NOT NULL,
          job_name TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('success','error')),
          output_kind TEXT NOT NULL CHECK(output_kind IN ('direct','pi','scheduler')),
          started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL,
          duration_seconds REAL NOT NULL,
          exit_code INTEGER,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          output TEXT,
          error TEXT,
          truncated INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS results_job_sequence_idx ON results(job_id, sequence DESC);
        CREATE INDEX IF NOT EXISTS results_status_sequence_idx ON results(status, sequence DESC);
        CREATE TABLE IF NOT EXISTS notification_outbox (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          result_sequence INTEGER NOT NULL UNIQUE,
          carrier TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','accepted','suppressed','failed','ambiguous')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_attempt_at TEXT,
          accepted_at TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(result_sequence) REFERENCES results(sequence) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS notification_devices (
          platform TEXT PRIMARY KEY CHECK(platform IN ('iphone','watch')),
          installation_id TEXT NOT NULL,
          topic TEXT NOT NULL,
          environment TEXT NOT NULL CHECK(environment IN ('development','production')),
          device_token TEXT NOT NULL,
          token_sha256 TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          registered_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          invalidated_at TEXT,
          invalidation_reason TEXT,
          last_accepted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS notification_deliveries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          outbox_id INTEGER NOT NULL,
          platform TEXT NOT NULL CHECK(platform IN ('iphone','watch')),
          apns_id TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','accepted','suppressed','failed','ambiguous')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_attempt_at TEXT,
          accepted_at TEXT,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(outbox_id, platform),
          FOREIGN KEY(outbox_id) REFERENCES notification_outbox(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS notification_deliveries_due_idx
          ON notification_deliveries(status, next_attempt_at, id);
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    additions = {
        "last_silent_success_at": "TEXT",
        "last_output_at": "TEXT",
        "last_error_at": "TEXT",
        "consecutive_errors": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
    conn.execute(
        """
        UPDATE jobs
           SET model=?, updated_at=?
         WHERE (id=? OR name=?) AND model IN (?, ?)
        """,
        (PI_FIRST_ENABLED_MODEL, iso(), DAILY_JOB_ID, DAILY_JOB_NAME, *LEGACY_DAILY_JOB_MODELS),
    )
    conn.commit()


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = (path or DB_PATH).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    target.parent.chmod(PRIVATE_DIR_MODE)
    previous_umask = os.umask(0o077)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(target, timeout=30)
        target.chmod(PRIVATE_FILE_MODE)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        init_db(conn)
        secure_database_permissions(target)
        return conn
    except Exception:
        if conn is not None:
            conn.close()
        raise
    finally:
        os.umask(previous_umask)


def migration_job_snapshot(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    columns = ",".join(MIGRATION_JOB_COLUMNS)
    return [
        tuple(row[column] for column in MIGRATION_JOB_COLUMNS)
        for row in conn.execute(f"SELECT {columns} FROM jobs ORDER BY id").fetchall()
    ]


def assert_migration_preserved(
    source: list[tuple[Any, ...]],
    target: list[tuple[Any, ...]],
) -> None:
    if len(source) != len(target):
        raise RuntimeError(f"Scheduler migration count mismatch: source={len(source)} target={len(target)}")
    for source_row, target_row in zip(source, target):
        if source_row == target_row:
            continue
        job_id = str(source_row[0]) if source_row else "unknown"
        changed = [
            column
            for column, source_value, target_value in zip(MIGRATION_JOB_COLUMNS, source_row, target_row)
            if source_value != target_value
        ]
        raise RuntimeError(f"Scheduler migration mismatch for {job_id}: {', '.join(changed)}")


def infer_kind(schedule: str, explicit: str | None = None) -> str:
    if explicit:
        if explicit not in {"once", "interval", "cron"}:
            raise ValueError("kind must be once, interval, or cron")
        return explicit
    value = schedule.strip()
    if DURATION_RE.match(value):
        return "once" if value.startswith("+") else "interval"
    if ISOISH_RE.match(value):
        return "once"
    if len(value.split()) in (5, 6):
        return "cron"
    raise ValueError("Could not infer schedule kind. Use +5m/ISO, 5m interval, or a 5/6-field cron expression.")


def parse_duration_ms(value: str) -> int:
    match = DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid duration: {value}")
    amount = int(match.group(2))
    multiplier = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}[match.group(3).lower()]
    return amount * multiplier


def cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for raw_part in field.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError(f"Invalid cron step: {part}")
            values.update(range(minimum, maximum + 1, step))
            continue
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ValueError(f"Invalid cron step: {part}")
            if "-" in base:
                start_text, end_text = base.split("-", 1)
                start, end = int(start_text), int(end_text)
            else:
                start, end = minimum, int(base)
            values.update(range(start, end + 1, step))
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            values.update(range(int(start_text), int(end_text) + 1))
            continue
        values.add(int(part))
    invalid = [value for value in values if value < minimum or value > maximum]
    if invalid:
        raise ValueError(f"Cron value out of range {minimum}-{maximum}: {invalid[0]}")
    if not values:
        raise ValueError("Cron field is empty")
    return values


def cron_next(schedule: str, after: dt.datetime) -> dt.datetime:
    fields = schedule.split()
    if len(fields) == 5:
        minute_field, hour_field, day_field, month_field, weekday_field = fields
        seconds = {0}
    elif len(fields) == 6:
        second_field, minute_field, hour_field, day_field, month_field, weekday_field = fields
        seconds = cron_values(second_field, 0, 59)
    else:
        raise ValueError("Cron schedule must have 5 or 6 fields")
    minutes = cron_values(minute_field, 0, 59)
    hours = cron_values(hour_field, 0, 23)
    days = cron_values(day_field, 1, 31)
    months = cron_values(month_field, 1, 12)
    weekdays = cron_values(weekday_field, 0, 7)
    if 7 in weekdays:
        weekdays.add(0)
        weekdays.discard(7)
    cursor = (after + dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).replace(microsecond=0)
    for _ in range(366 * 24 * 60 * 60):
        cron_weekday = (cursor.weekday() + 1) % 7
        if (
            cursor.second in seconds
            and cursor.minute in minutes
            and cursor.hour in hours
            and cursor.day in days
            and cursor.month in months
            and cron_weekday in weekdays
        ):
            return cursor
        cursor += dt.timedelta(seconds=1 if len(seconds) != 1 else 60)
        if len(seconds) == 1:
            cursor = cursor.replace(second=next(iter(seconds)))
    raise ValueError("Could not find next cron run within one year")


def compute_next_run(schedule: str, kind: str, after: dt.datetime | None = None) -> str | None:
    base = after or utcnow()
    if kind == "once":
        target = base + dt.timedelta(milliseconds=parse_duration_ms(schedule)) if schedule.strip().startswith("+") else parse_iso(schedule)
        if target <= base:
            raise ValueError(f"One-shot schedule is in the past: {target.isoformat()}")
        return iso(target)
    if kind == "interval":
        return iso(base + dt.timedelta(milliseconds=parse_duration_ms(schedule)))
    if kind == "cron":
        return iso(cron_next(schedule, base))
    raise ValueError(f"Unknown schedule kind: {kind}")


def acquire_lock(conn: sqlite3.Connection, name: str) -> str | None:
    owner = str(uuid.uuid4())
    now = utcnow()
    with conn:
        conn.execute("DELETE FROM locks WHERE name=? AND acquired_at<?", (name, iso(now - dt.timedelta(seconds=LOCK_STALE_SECONDS))))
        try:
            conn.execute("INSERT INTO locks(name,owner,acquired_at) VALUES(?,?,?)", (name, owner, iso(now)))
            return owner
        except sqlite3.IntegrityError:
            return None


def release_lock(conn: sqlite3.Connection, name: str, owner: str) -> None:
    with conn:
        conn.execute("DELETE FROM locks WHERE name=? AND owner=?", (name, owner))


def _config_value(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row is not None else None


def _set_config_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO config(key,value,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
        """,
        (key, value, iso()),
    )


def notification_dispatch_enabled(conn: sqlite3.Connection) -> bool:
    return APNS_PROVIDER_ENABLED and _config_value(conn, "apns_dispatch_enabled") == "1"


def _provider_configuration():
    from apns_provider import APNsConfiguration

    return APNsConfiguration(
        team_id=APNS_TEAM_ID,
        key_id=APNS_KEY_ID,
        key_path=APNS_KEY_PATH,
        enabled=APNS_PROVIDER_ENABLED,
        environment=APNS_ENVIRONMENT,
    )


def register_notification_device(payload: dict[str, Any]) -> dict[str, Any]:
    common_fields = {"protocolVersion", "action", "platform", "environment", "installationID"}
    if not isinstance(payload, dict):
        raise ValueError("Notification registration must be an object")
    action = payload.get("action")
    if action not in {"register", "deactivate"}:
        raise ValueError("Notification registration action is invalid")
    expected_fields = common_fields | ({"deviceToken"} if action == "register" else set())
    if set(payload) != expected_fields:
        raise ValueError("Notification registration fields are invalid")
    if payload.get("protocolVersion") != 1:
        raise ValueError("Notification registration protocol version is unsupported")
    platform = payload.get("platform")
    if platform not in APNS_PLATFORM_TOPICS:
        raise ValueError("Notification registration platform is invalid")
    environment = payload.get("environment")
    if environment not in {"development", "production"}:
        raise ValueError("Notification registration environment is invalid")
    if environment != APNS_ENVIRONMENT:
        raise ValueError("Notification registration environment does not match the host")
    raw_installation = payload.get("installationID")
    if not isinstance(raw_installation, str) or not APNS_INSTALLATION_ID_RE.fullmatch(raw_installation):
        raise ValueError("Notification installation identifier is invalid")
    installation_id = str(uuid.UUID(raw_installation)).lower()
    now = iso()

    with closing(connect()) as conn:
        if action == "deactivate":
            with conn:
                # Owner disable removes the private token instead of retaining
                # an inactive copy. The installation-scoped predicate prevents
                # stale clients from deleting a newer registration.
                cursor = conn.execute(
                    "DELETE FROM notification_devices WHERE platform=? AND installation_id=? AND active=1",
                    (platform, installation_id),
                )
            secure_database_permissions()
            return {
                "ok": True,
                "protocolVersion": 1,
                "platform": platform,
                "active": False,
                "changed": cursor.rowcount == 1,
            }

        raw_token = payload.get("deviceToken")
        if not isinstance(raw_token, str) or not APNS_DEVICE_TOKEN_RE.fullmatch(raw_token):
            raise ValueError("Notification device token is invalid")
        token = raw_token.lower()
        digest = __import__("hashlib").sha256(token.encode("ascii")).hexdigest()
        with conn:
            mixed = conn.execute(
                "SELECT 1 FROM notification_devices WHERE active=1 AND environment<>? LIMIT 1",
                (environment,),
            ).fetchone()
            if mixed is not None:
                raise ValueError("Mixed APNs registration environments are not allowed")
            existing = conn.execute(
                "SELECT installation_id,device_token,registered_at FROM notification_devices WHERE platform=?",
                (platform,),
            ).fetchone()
            is_same_registration = (
                existing is not None
                and existing["installation_id"] == installation_id
                and existing["device_token"] == token
            )
            registered_at = existing["registered_at"] if is_same_registration else now
            conn.execute(
                """
                INSERT INTO notification_devices(
                  platform,installation_id,topic,environment,device_token,token_sha256,
                  active,registered_at,updated_at,invalidated_at,invalidation_reason,last_accepted_at
                ) VALUES(?,?,?,?,?,?,1,?,?,NULL,NULL,NULL)
                ON CONFLICT(platform) DO UPDATE SET
                  installation_id=excluded.installation_id,
                  topic=excluded.topic,
                  environment=excluded.environment,
                  device_token=excluded.device_token,
                  token_sha256=excluded.token_sha256,
                  active=1,
                  registered_at=excluded.registered_at,
                  updated_at=excluded.updated_at,
                  invalidated_at=NULL,
                  invalidation_reason=NULL,
                  last_accepted_at=CASE
                    WHEN notification_devices.installation_id=excluded.installation_id
                     AND notification_devices.device_token=excluded.device_token
                    THEN notification_devices.last_accepted_at
                    ELSE NULL
                  END
                """,
                (
                    platform,
                    installation_id,
                    APNS_PLATFORM_TOPICS[platform],
                    environment,
                    token,
                    digest,
                    registered_at,
                    now,
                ),
            )
        secure_database_permissions()
        return {
            "ok": True,
            "protocolVersion": 1,
            "platform": platform,
            "active": True,
            "tokenFingerprint": digest[:12],
            "registeredAt": registered_at,
        }


def enqueue_notification_for_result(
    conn: sqlite3.Connection,
    *,
    result_sequence: int,
    created_at: str,
) -> None:
    if not notification_dispatch_enabled(conn):
        return
    devices = conn.execute(
        "SELECT platform FROM notification_devices WHERE active=1 AND environment=? ORDER BY platform",
        (APNS_ENVIRONMENT,),
    ).fetchall()
    outbox_status = "pending" if devices else "suppressed"
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO notification_outbox(
          result_sequence,carrier,status,attempt_count,next_attempt_at,last_attempt_at,
          accepted_at,last_error,created_at,updated_at
        ) VALUES(?,'apns',?,0,?,NULL,NULL,?,?,?)
        """,
        (
            result_sequence,
            outbox_status,
            created_at if devices else None,
            None if devices else "no-active-device",
            created_at,
            created_at,
        ),
    )
    if cursor.rowcount != 1:
        return
    outbox_id = int(cursor.lastrowid)
    for device in devices:
        conn.execute(
            """
            INSERT INTO notification_deliveries(
              outbox_id,platform,apns_id,status,attempt_count,next_attempt_at,
              last_attempt_at,accepted_at,last_error,created_at,updated_at
            ) VALUES(?,?,?,'pending',0,?,NULL,NULL,NULL,?,?)
            """,
            (outbox_id, device["platform"], str(uuid.uuid4()), created_at, created_at, created_at),
        )


def _update_outbox_aggregate(conn: sqlite3.Connection, outbox_id: int) -> None:
    rows = conn.execute(
        "SELECT status,attempt_count,last_attempt_at,accepted_at,last_error,next_attempt_at FROM notification_deliveries WHERE outbox_id=?",
        (outbox_id,),
    ).fetchall()
    if not rows:
        status = "suppressed"
    else:
        states = {str(row["status"]) for row in rows}
        if "pending" in states:
            status = "pending"
        elif "ambiguous" in states:
            status = "ambiguous"
        elif "accepted" in states:
            status = "accepted"
        elif states == {"suppressed"}:
            status = "suppressed"
        else:
            status = "failed"
    attempts = sum(int(row["attempt_count"] or 0) for row in rows)
    last_attempt = max((row["last_attempt_at"] for row in rows if row["last_attempt_at"]), default=None)
    accepted_at = max((row["accepted_at"] for row in rows if row["accepted_at"]), default=None)
    next_attempt = min((row["next_attempt_at"] for row in rows if row["next_attempt_at"]), default=None)
    errors = [str(row["last_error"]) for row in rows if row["last_error"]]
    conn.execute(
        """
        UPDATE notification_outbox
           SET status=?,attempt_count=?,next_attempt_at=?,last_attempt_at=?,accepted_at=?,last_error=?,updated_at=?
         WHERE id=?
        """,
        (status, attempts, next_attempt, last_attempt, accepted_at, errors[0][:160] if errors else None, iso(), outbox_id),
    )


def _invalidate_notification_device(
    conn: sqlite3.Connection,
    *,
    platform: str,
    expected_token: str,
    reason: str,
    invalidation_timestamp: int | None,
) -> None:
    device = conn.execute(
        "SELECT device_token,updated_at FROM notification_devices WHERE platform=? AND active=1",
        (platform,),
    ).fetchone()
    if device is None or device["device_token"] != expected_token:
        return
    if invalidation_timestamp is not None:
        confirmed_at = parse_iso(str(device["updated_at"])).timestamp()
        if confirmed_at >= invalidation_timestamp:
            return
    # APNs invalidation removes the unusable private token immediately. Public
    # status needs only the fail-closed absence of a current registration.
    conn.execute("DELETE FROM notification_devices WHERE platform=?", (platform,))


def drain_notifications(conn: sqlite3.Connection) -> dict[str, Any]:
    if not notification_dispatch_enabled(conn):
        return {"enabled": False, "attempted": 0}
    owner = acquire_lock(conn, "notification-dispatch")
    if not owner:
        return {"enabled": True, "attempted": 0, "locked": True}
    attempted = 0
    try:
        configuration = _provider_configuration()
        configuration.validate_for_send()
        from apns_provider import APNsProvider

        provider = APNsProvider(configuration)
        now = utcnow()
        rows = conn.execute(
            """
            SELECT d.id AS delivery_id,d.outbox_id,d.platform,d.apns_id,d.attempt_count,d.created_at,
                   o.result_sequence,r.job_id,nd.topic,nd.environment,nd.device_token
              FROM notification_deliveries d
              JOIN notification_outbox o ON o.id=d.outbox_id
              JOIN results r ON r.sequence=o.result_sequence
              LEFT JOIN notification_devices nd ON nd.platform=d.platform AND nd.active=1
             WHERE d.status='pending' AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=?)
             ORDER BY d.id ASC LIMIT 20
            """,
            (iso(now),),
        ).fetchall()
        for row in rows:
            attempted += 1
            delivery_id = int(row["delivery_id"])
            outbox_id = int(row["outbox_id"])
            attempt_count = int(row["attempt_count"] or 0) + 1
            current_iso = iso()
            created_at = parse_iso(str(row["created_at"]))
            age = max(0, (now - created_at).total_seconds())
            if age >= APNS_DELIVERY_EXPIRY_SECONDS or attempt_count > APNS_MAX_DELIVERY_ATTEMPTS:
                with conn:
                    conn.execute(
                        "UPDATE notification_deliveries SET status='failed',attempt_count=?,last_attempt_at=?,last_error='expired',next_attempt_at=NULL,updated_at=? WHERE id=?",
                        (attempt_count, current_iso, current_iso, delivery_id),
                    )
                    _update_outbox_aggregate(conn, outbox_id)
                continue
            if row["device_token"] is None:
                with conn:
                    conn.execute(
                        "UPDATE notification_deliveries SET status='suppressed',attempt_count=?,last_attempt_at=?,last_error='inactive-device',next_attempt_at=NULL,updated_at=? WHERE id=?",
                        (attempt_count, current_iso, current_iso, delivery_id),
                    )
                    _update_outbox_aggregate(conn, outbox_id)
                continue
            if row["environment"] != APNS_ENVIRONMENT:
                raise RuntimeError("Active APNs registration environment mismatch")
            result = provider.send_alert(
                topic=str(row["topic"]),
                device_token=str(row["device_token"]),
                result_sequence=int(row["result_sequence"]),
                job_id=str(row["job_id"]),
                apns_id=str(row["apns_id"]),
                expiration=int(created_at.timestamp()) + APNS_DELIVERY_EXPIRY_SECONDS,
            )
            fatal_configuration_failure = result.status_code == 403
            with conn:
                if result.outcome == "accepted":
                    conn.execute(
                        "UPDATE notification_deliveries SET status='accepted',attempt_count=?,last_attempt_at=?,accepted_at=?,last_error=NULL,next_attempt_at=NULL,updated_at=? WHERE id=?",
                        (attempt_count, current_iso, current_iso, current_iso, delivery_id),
                    )
                    conn.execute(
                        "UPDATE notification_devices SET last_accepted_at=? WHERE platform=?",
                        (current_iso, row["platform"]),
                    )
                elif result.outcome == "retry" and attempt_count < APNS_MAX_DELIVERY_ATTEMPTS and age < APNS_DELIVERY_EXPIRY_SECONDS:
                    retry_after = max(1, int(result.retry_after_seconds or min(30 * (2 ** (attempt_count - 1)), 120)))
                    next_attempt = iso(now + dt.timedelta(seconds=retry_after))
                    conn.execute(
                        "UPDATE notification_deliveries SET status='pending',attempt_count=?,last_attempt_at=?,next_attempt_at=?,last_error=?,updated_at=? WHERE id=?",
                        (attempt_count, current_iso, next_attempt, result.reason[:80], current_iso, delivery_id),
                    )
                else:
                    final_status = "ambiguous" if result.outcome == "ambiguous" else "failed"
                    conn.execute(
                        "UPDATE notification_deliveries SET status=?,attempt_count=?,last_attempt_at=?,next_attempt_at=NULL,last_error=?,updated_at=? WHERE id=?",
                        (final_status, attempt_count, current_iso, result.reason[:80], current_iso, delivery_id),
                    )
                if result.invalidate_token:
                    _invalidate_notification_device(
                        conn,
                        platform=str(row["platform"]),
                        expected_token=str(row["device_token"]),
                        reason=result.reason,
                        invalidation_timestamp=result.invalidation_timestamp,
                    )
                _update_outbox_aggregate(conn, outbox_id)
                if fatal_configuration_failure:
                    # A provider-auth or topic-authorization rejection closes
                    # the durable dispatch gate. A later owner-reviewed enable
                    # is required before either topic can transmit again.
                    _set_config_value(conn, "apns_dispatch_enabled", "0")
            if fatal_configuration_failure:
                raise RuntimeError("APNs provider authentication or topic authorization was rejected")
        if attempted:
            with conn:
                _set_config_value(conn, "apns_last_error", "")
                _set_config_value(conn, "apns_last_attempt_at", iso())
    except Exception as exc:
        with conn:
            _set_config_value(conn, "apns_last_error", sanitize_text(exc)[:160])
        LOGGER.error("APNs dispatch failed: %s", sanitize_text(exc))
        return {"enabled": True, "attempted": attempted, "error": "APNs dispatch is unavailable"}
    finally:
        release_lock(conn, "notification-dispatch", owner)
        secure_database_permissions()
    return {"enabled": True, "attempted": attempted}


def _provider_is_configured() -> bool:
    try:
        _provider_configuration().validate_for_send()
        return True
    except Exception:  # noqa: BLE001
        return False


def notification_status(_args: argparse.Namespace | None = None) -> dict[str, Any]:
    provider_configured = _provider_is_configured()
    with closing(connect()) as conn:
        devices = {
            str(row["platform"]): {
                "registered": bool(row["active"]),
                "registeredAt": row["updated_at"] if row["active"] else None,
                "lastAcceptedAt": row["last_accepted_at"],
            }
            for row in conn.execute(
                "SELECT platform,active,updated_at,last_accepted_at FROM notification_devices ORDER BY platform"
            ).fetchall()
        }
        counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM notification_deliveries GROUP BY status"
            ).fetchall()
        }
        last_row = conn.execute(
            "SELECT status,last_attempt_at,accepted_at FROM notification_outbox ORDER BY id DESC LIMIT 1"
        ).fetchone()
        dispatch = notification_dispatch_enabled(conn)
        last_error = _config_value(conn, "apns_last_error") or None
    payload = {
        "ok": True,
        "providerConfigured": provider_configured,
        "dispatchEnabled": dispatch,
        "environment": APNS_ENVIRONMENT if provider_configured else None,
        "devices": {
            "iphone": devices.get("iphone", {"registered": False, "registeredAt": None, "lastAcceptedAt": None}),
            "watch": devices.get("watch", {"registered": False, "registeredAt": None, "lastAcceptedAt": None}),
        },
        "pendingCount": counts.get("pending", 0),
        "failedCount": counts.get("failed", 0),
        "ambiguousCount": counts.get("ambiguous", 0),
        "lastOutcome": str(last_row["status"]) if last_row is not None else None,
        "lastAttemptAt": last_row["last_attempt_at"] if last_row is not None else None,
        "lastAcceptedAt": last_row["accepted_at"] if last_row is not None else None,
        "error": last_error,
    }
    payload["message"] = (
        "JARVIS notifications "
        + ("enabled" if dispatch else "disabled")
        + f"; iPhone={'registered' if payload['devices']['iphone']['registered'] else 'missing'}"
        + f"; Watch={'registered' if payload['devices']['watch']['registered'] else 'missing'}"
    )
    return payload


def enable_notification_dispatch(_args: argparse.Namespace) -> dict[str, Any]:
    configuration = _provider_configuration()
    configuration.validate_for_send()
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT platform,environment FROM notification_devices WHERE active=1 ORDER BY platform"
        ).fetchall()
        platforms = {str(row["platform"]) for row in rows if row["environment"] == APNS_ENVIRONMENT}
        if platforms != set(APNS_PLATFORM_TOPICS):
            raise ValueError("Both current iPhone and Watch APNs registrations are required")
        with conn:
            _set_config_value(conn, "apns_dispatch_enabled", "1")
            _set_config_value(conn, "apns_last_error", "")
    result = notification_status()
    result["message"] = "JARVIS APNs dispatch enabled for future scheduled results"
    return result


def disable_notification_dispatch(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        with conn:
            _set_config_value(conn, "apns_dispatch_enabled", "0")
    result = notification_status()
    result["message"] = "JARVIS APNs dispatch disabled"
    return result


def drain_notifications_command(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        result = drain_notifications(conn)
    result["ok"] = "error" not in result
    result["message"] = f"Notification drain attempted {result.get('attempted', 0)} delivery(s)"
    return result


def sanitize_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_RE.sub("", text)
    # Redact configured secret values even when a tool prints the bare value
    # without a helpful assignment label. Values are never persisted here.
    for key, secret in os.environ.items():
        if SENSITIVE_ENV_KEY_RE.search(key) and len(secret) >= 8 and secret in text:
            text = text.replace(secret, "[REDACTED]")
    text = BEARER_RE.sub("Bearer [REDACTED]", text)
    text = SECRET_JSON_RE.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = LOCAL_PATH_RE.sub("<local-path>", text)
    return text.strip()


def truncate_utf8(value: str, maximum: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value, False
    suffix = "\n\n[Output truncated by JARVIS]"
    allowance = max(0, maximum - len(suffix.encode("utf-8")))
    prefix = encoded[:allowance]
    while prefix:
        try:
            return prefix.decode("utf-8") + suffix, True
        except UnicodeDecodeError as exc:
            prefix = prefix[: exc.start]
    return suffix.encode("utf-8")[:maximum].decode("utf-8", "ignore"), True


def summarize(text: str, fallback: str) -> str:
    clean = " ".join(text.split())
    if not clean:
        clean = fallback
    return clean if len(clean) <= MAX_RESULT_SUMMARY_CHARS else clean[: MAX_RESULT_SUMMARY_CHARS - 1].rstrip() + "…"


def persist_completion(
    conn: sqlite3.Connection,
    *,
    job: sqlite3.Row,
    run_id: str,
    output_kind: str,
    started: dt.datetime,
    finished: dt.datetime,
    status: str,
    exit_code: int | None,
    output: str,
    error: str | None,
) -> dict[str, Any] | None:
    safe_output = sanitize_text(output)
    safe_error = sanitize_text(error)
    should_persist = status == "error" or bool(safe_output)
    duration = max(0.0, (finished - started).total_seconds())
    result: dict[str, Any] | None = None
    with conn:
        if status == "error":
            conn.execute(
                """
                UPDATE jobs
                   SET last_run_at=?, last_status='error', run_count=run_count+1,
                       updated_at=?, last_error_at=?, consecutive_errors=consecutive_errors+1
                 WHERE id=?
                """,
                (iso(finished), iso(finished), iso(finished), job["id"]),
            )
        elif should_persist:
            conn.execute(
                """
                UPDATE jobs
                   SET last_run_at=?, last_status='success', run_count=run_count+1,
                       updated_at=?, last_output_at=?, consecutive_errors=0
                 WHERE id=?
                """,
                (iso(finished), iso(finished), iso(finished), job["id"]),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                   SET last_run_at=?, last_status='success', run_count=run_count+1,
                       updated_at=?, last_silent_success_at=?, consecutive_errors=0
                 WHERE id=?
                """,
                (iso(finished), iso(finished), iso(finished), job["id"]),
            )
        if should_persist:
            if status == "error":
                bounded_error, error_truncated = truncate_utf8(safe_error, min(MAX_RESULT_BYTES, 16 * 1024))
            else:
                bounded_error, error_truncated = "", False
            output_budget = max(0, MAX_RESULT_BYTES - len(bounded_error.encode("utf-8")))
            bounded_output, output_truncated = truncate_utf8(safe_output, output_budget)
            title = f"{job['name']} {'failed' if status == 'error' else 'completed'}"
            summary = summarize(bounded_error or bounded_output, title)
            cursor = conn.execute(
                """
                INSERT INTO results(
                  id,job_id,job_name,status,output_kind,started_at,finished_at,
                  duration_seconds,exit_code,title,summary,output,error,truncated,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    job["id"],
                    job["name"],
                    status,
                    output_kind,
                    iso(started),
                    iso(finished),
                    duration,
                    exit_code,
                    title,
                    summary,
                    bounded_output or None,
                    bounded_error or None,
                    1 if output_truncated or error_truncated else 0,
                    iso(finished),
                ),
            )
            sequence = int(cursor.lastrowid)
            enqueue_notification_for_result(
                conn,
                result_sequence=sequence,
                created_at=iso(finished),
            )
            conn.execute(
                "DELETE FROM results WHERE sequence IN (SELECT sequence FROM results ORDER BY sequence DESC LIMIT -1 OFFSET ?)",
                (MAX_RESULTS,),
            )
            result = result_row_to_public(conn.execute("SELECT * FROM results WHERE sequence=?", (sequence,)).fetchone())
    secure_database_permissions()
    return result


def result_row_to_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "sequence": int(row["sequence"]),
        "id": str(row["id"]),
        "jobId": str(row["job_id"]),
        "jobName": str(row["job_name"]),
        "status": str(row["status"]),
        "outputKind": str(row["output_kind"]),
        "startedAt": str(row["started_at"]),
        "finishedAt": str(row["finished_at"]),
        "durationSeconds": round(float(row["duration_seconds"]), 3),
        "exitCode": row["exit_code"],
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "output": row["output"],
        "error": row["error"],
        "truncated": bool(row["truncated"]),
    }


def add_job(args: argparse.Namespace) -> dict[str, Any]:
    kind = infer_kind(args.schedule, args.kind)
    next_run = compute_next_run(args.schedule, kind)
    job_id = args.job_id or f"job_{uuid.uuid4().hex[:12]}"
    name = args.name or job_id
    now = iso()
    with closing(connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO jobs(id,name,schedule,kind,prompt,enabled,model,next_run_at,created_at,updated_at,description)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (job_id, name, args.schedule, kind, args.prompt, 1, args.model, next_run, now, now, args.description),
            )
        job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    return {"ok": True, "message": f"Scheduled {name} ({job_id}) next at {next_run}", "job": job}


def list_jobs(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        jobs = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY enabled DESC,next_run_at ASC,created_at DESC")]
    lines = ["Scheduled Pi jobs:"]
    lines.extend(
        f"  {'✓' if job['enabled'] else '✗'} {job['name']} ({job['id']}) {job['kind']} {job['schedule']} next={job['next_run_at'] or '-'} runs={job['run_count']}"
        for job in jobs
    )
    if not jobs:
        lines.append("  none")
    return {"ok": True, "message": "\n".join(lines), "jobs": jobs}


def list_public_jobs(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        rows = conn.execute(
            """
            SELECT id,name,kind,schedule,enabled,next_run_at,last_run_at,last_status,
                   run_count,description,last_silent_success_at,last_output_at,
                   last_error_at,consecutive_errors
              FROM jobs
             ORDER BY enabled DESC,next_run_at ASC,created_at DESC
            """
        ).fetchall()
    jobs = [
        {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "kind": str(row["kind"]),
            "schedule": str(row["schedule"]),
            "enabled": bool(row["enabled"]),
            "nextRunAt": row["next_run_at"],
            "lastRunAt": row["last_run_at"],
            "lastStatus": row["last_status"],
            "runCount": int(row["run_count"] or 0),
            "description": sanitize_text(row["description"]) if row["description"] else None,
            "lastSilentSuccessAt": row["last_silent_success_at"],
            "lastOutputAt": row["last_output_at"],
            "lastErrorAt": row["last_error_at"],
            "consecutiveErrors": int(row["consecutive_errors"] or 0),
        }
        for row in rows
    ]
    return {
        "ok": True,
        "generatedAt": iso(),
        "summary": {
            "total": len(jobs),
            "enabled": sum(1 for job in jobs if job["enabled"]),
            "running": sum(1 for job in jobs if job["lastStatus"] == "running"),
            "errors": sum(1 for job in jobs if job["lastStatus"] == "error"),
        },
        "jobs": jobs,
    }


def list_public_results(args: argparse.Namespace) -> dict[str, Any]:
    try:
        limit = min(MAX_RESULT_PAGE, max(1, int(args.limit)))
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer") from None
    after = None
    if args.after is not None:
        try:
            after = max(0, int(args.after))
        except (TypeError, ValueError):
            raise ValueError("after must be a nonnegative integer") from None
    clauses: list[str] = []
    values: list[Any] = []
    if after is not None:
        clauses.append("sequence>?")
        values.append(after)
    if args.job_id:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", args.job_id):
            raise ValueError("job-id is invalid")
        clauses.append("job_id=?")
        values.append(args.job_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ASC" if after is not None else "DESC"
    with closing(connect()) as conn:
        rows = conn.execute(
            f"SELECT * FROM results {where} ORDER BY sequence {order} LIMIT ?",
            (*values, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    results = [result_row_to_public(row) for row in rows]
    return {
        "ok": True,
        "generatedAt": iso(),
        "results": results,
        "hasMore": has_more,
        "nextAfter": max((result["sequence"] for result in results if result), default=after or 0),
    }


def set_enabled(args: argparse.Namespace, enabled: bool) -> dict[str, Any]:
    with closing(connect()) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        next_run = compute_next_run(job["schedule"], job["kind"]) if enabled else job["next_run_at"]
        with conn:
            conn.execute("UPDATE jobs SET enabled=?,next_run_at=?,updated_at=? WHERE id=?", (1 if enabled else 0, next_run, iso(), job["id"]))
        updated = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone())
    return {"ok": True, "message": f"{'Enabled' if enabled else 'Disabled'} {job['name']}", "job": updated}


def remove_job(args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        with conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
    return {"ok": True, "message": f"Removed {job['name']} ({job['id']})"}


def extract_text_part(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text")
    return ""


def _json_event_error(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    error = str(message.get("errorMessage") or message.get("error_message") or "").strip()
    if error:
        return error
    reason = str(message.get("stopReason") or message.get("stop_reason") or "").strip().lower()
    return "Assistant message stopped with an error." if reason == "error" else None


def parse_json_events(stdout: str) -> tuple[str, str | None]:
    assistant = ""
    deltas: list[str] = []
    errors: list[str] = []
    non_json: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            if line.strip():
                non_json.append(line)
            continue
        if not isinstance(event, dict):
            continue
        for candidate in (event, event.get("message")):
            found = _json_event_error(candidate)
            if found and found not in errors:
                errors.append(found)
        if event.get("type") == "message_update":
            update = event.get("assistantMessageEvent") or event.get("assistant_message_event") or {}
            if isinstance(update, dict):
                found = _json_event_error(update.get("partial"))
                if found and found not in errors:
                    errors.append(found)
                if update.get("type") == "text_delta":
                    deltas.append(str(update.get("delta", "")))
        message = event.get("message")
        if event.get("type") in {"message_end", "message"} and isinstance(message, dict) and message.get("role") == "assistant":
            text = extract_text_part(message.get("content"))
            if text.strip():
                assistant = text.strip()
    if not assistant and deltas:
        assistant = "".join(deltas).strip()
    if not assistant and non_json and not errors:
        assistant = "\n".join(non_json).strip()[-4000:]
    return assistant, "\n".join(errors[:3]) if errors else None


def first_enabled_pi_model() -> str | None:
    merged: dict[str, Any] = {}
    for path in (Path.home() / ".pi" / "agent" / "settings.json", PI_DIR / "settings.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not read Pi settings: %s", path, exc_info=True)
            continue
        if isinstance(payload, dict):
            merged.update(payload)
    values = merged.get("enabledModels")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip() and not value.strip().startswith("!"):
                return value.strip()
    return None


def build_pi_command(job: sqlite3.Row) -> list[str]:
    config.load_project_env(ROOT / ".env")
    command = shlex.split(os.environ.get("PI_CODING_AGENT_COMMAND", "pi"))
    command.extend(["--mode", "json", "--no-session"])
    configured_model = str(job["model"] or "").strip()
    if configured_model == PI_FIRST_ENABLED_MODEL:
        model = first_enabled_pi_model() or os.environ.get("JARVIS_SCHEDULER_PI_MODEL") or os.environ.get("JARVIS_PI_MODEL")
    else:
        model = configured_model or os.environ.get("JARVIS_SCHEDULER_PI_MODEL") or os.environ.get("JARVIS_PI_MODEL")
    if model:
        command.extend(["--model", model])
    note = (
        "You are running as an unattended scheduled Pi job. "
        f"Job name: {job['name']}. Job id: {job['id']}. "
        "Return the requested result as your final answer only. The scheduler stores it in the private JARVIS Jobs history. "
        "Do not send messages or notifications through external services. "
        "Do not ask for clarification; make a best effort and report blockers."
    )
    command.extend(["--append-system-prompt", note, job["prompt"]])
    return command


def validate_success_output(job: sqlite3.Row, assistant_text: str) -> str | None:
    identifiers = {str(job["name"]).casefold(), str(job["id"]).casefold()}
    text = assistant_text.strip()
    if {DAILY_JOB_NAME, DAILY_JOB_ID} & identifiers:
        if len(text) < 80:
            return f"Output validation failed: daily-job-search output was too short ({len(text)} chars)."
        if not text.startswith("☀️ Daily Job Picks"):
            return "Output validation failed: daily-job-search output must start with '☀️ Daily Job Picks'."
    for rule in _split_env_csv(os.environ.get("JARVIS_SCHEDULER_REQUIRED_OUTPUT_PREFIXES", "")):
        if "=" not in rule:
            continue
        target, prefix = rule.split("=", 1)
        if target.strip().casefold() in identifiers and prefix and not text.startswith(prefix):
            return f"Output validation failed: expected output to start with {prefix!r}."
    return None


def scheduler_timeout() -> int:
    raw = os.environ.get("JARVIS_SCHEDULER_TIMEOUT_SECONDS") or os.environ.get("PI_CODING_AGENT_RPC_TIMEOUT_SECONDS") or "900"
    return min(7200, max(1, int(raw)))


def run_direct_stdout_for_job(conn: sqlite3.Connection, job: sqlite3.Row) -> dict[str, Any]:
    run_id = f"run_{utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    started = utcnow()
    command = shlex.split(job["prompt"])
    timeout = scheduler_timeout()
    environment = os.environ.copy()
    existing_path = environment.get("PATH", "")
    environment["PATH"] = DEFAULT_PATH if not existing_path else f"{DEFAULT_PATH}:{existing_path}"
    status, exit_code, error, stdout, stderr = "success", None, None, "", ""
    try:
        proc = subprocess.run(command, cwd=str(ROOT), env=environment, text=True, capture_output=True, timeout=timeout)
        stdout, stderr, exit_code = proc.stdout or "", proc.stderr or "", proc.returncode
        if proc.returncode != 0:
            status, error = "error", f"command exited with code {proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        status, error, exit_code = "error", f"command timed out after {timeout}s", 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        status, error, exit_code = "error", str(exc), 1
    if stderr.strip():
        error = f"{error}\n\nstderr tail:\n{stderr[-4000:]}" if error else f"stderr tail:\n{stderr[-4000:]}"
    finished = utcnow()
    result = persist_completion(
        conn,
        job=job,
        run_id=run_id,
        output_kind="direct",
        started=started,
        finished=finished,
        status=status,
        exit_code=exit_code,
        output=stdout,
        error=error,
    )
    LOGGER.info("Finished scheduled command run_id=%s job=%s status=%s duration=%.1fs", run_id, job["name"], status, (finished - started).total_seconds())
    return {"run_id": run_id, "status": status, "exit_code": exit_code, "result": result, "silent": result is None}


def run_pi_for_job(conn: sqlite3.Connection, job: sqlite3.Row, *, forced: bool = False) -> dict[str, Any]:
    if job["model"] == DIRECT_STDOUT_MODEL:
        return run_direct_stdout_for_job(conn, job)
    run_id = f"run_{utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    started = utcnow()
    command = build_pi_command(job)
    timeout = scheduler_timeout()
    environment = os.environ.copy()
    existing_path = environment.get("PATH", "")
    environment["PATH"] = DEFAULT_PATH if not existing_path else f"{DEFAULT_PATH}:{existing_path}"
    status, exit_code, error, stdout, stderr = "success", None, None, "", ""
    try:
        LOGGER.info("Starting scheduled Pi run_id=%s job=%s forced=%s", run_id, job["name"], forced)
        proc = subprocess.run(command, cwd=str(ROOT), env=environment, text=True, capture_output=True, timeout=timeout)
        stdout, stderr, exit_code = proc.stdout or "", proc.stderr or "", proc.returncode
        if proc.returncode != 0:
            status, error = "error", f"pi exited with code {proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        status, error, exit_code = "error", f"pi timed out after {timeout}s", 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        status, error, exit_code = "error", str(exc), 1
    assistant, json_error = parse_json_events(stdout)
    if json_error:
        status = "error"
        error = f"{error}\n\n{json_error}" if error else json_error
    if stderr.strip():
        error = f"{error}\n\nstderr tail:\n{stderr[-4000:]}" if error else f"stderr tail:\n{stderr[-4000:]}"
    if status == "success":
        validation_error = validate_success_output(job, assistant)
        if validation_error:
            status, error = "error", validation_error
    finished = utcnow()
    result = persist_completion(
        conn,
        job=job,
        run_id=run_id,
        output_kind="pi",
        started=started,
        finished=finished,
        status=status,
        exit_code=exit_code,
        output=assistant or (stdout[-4000:] if status == "error" else ""),
        error=error,
    )
    LOGGER.info("Finished scheduled Pi run_id=%s job=%s status=%s duration=%.1fs", run_id, job["name"], status, (finished - started).total_seconds())
    return {"run_id": run_id, "status": status, "exit_code": exit_code, "result": result, "silent": result is None}


def record_scheduler_failure(conn: sqlite3.Connection, job: sqlite3.Row, message: str, at: dt.datetime) -> None:
    run_id = f"run_{at.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    persist_completion(
        conn,
        job=job,
        run_id=run_id,
        output_kind="scheduler",
        started=at,
        finished=at,
        status="error",
        exit_code=None,
        output="",
        error=message,
    )


def claim_due_jobs(conn: sqlite3.Connection, now: dt.datetime) -> list[sqlite3.Row]:
    due = conn.execute(
        "SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at ASC LIMIT 10",
        (iso(now),),
    ).fetchall()
    claimed: list[sqlite3.Row] = []
    for job in due:
        try:
            next_run = None if job["kind"] == "once" else compute_next_run(job["schedule"], job["kind"], now)
            enabled = 0 if job["kind"] == "once" else 1
            with conn:
                conn.execute(
                    "UPDATE jobs SET enabled=?,next_run_at=?,last_status='running',updated_at=? WHERE id=?",
                    (enabled, next_run, iso(now), job["id"]),
                )
            claimed.append(job)
        except Exception as exc:  # noqa: BLE001
            record_scheduler_failure(conn, job, f"Failed to compute next run: {exc}", now)
    return claimed


def run_due(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        owner = acquire_lock(conn, "run-due")
        if not owner:
            return {"ok": True, "message": "Another runner is active; skipped.", "runs": []}
        try:
            jobs = claim_due_jobs(conn, utcnow())
        finally:
            release_lock(conn, "run-due", owner)
        results = [run_pi_for_job(conn, job) for job in jobs]
        notification_result = drain_notifications(conn)
    return {
        "ok": True,
        "message": f"Ran {len(results)} due job(s)",
        "runs": results,
        "notifications": notification_result,
    }


def run_one(args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        result = run_pi_for_job(conn, job, forced=True)
        notification_result = drain_notifications(conn)
    return {
        "ok": True,
        "message": f"Ran {job['name']}: {result['status']}",
        "run": result,
        "notifications": notification_result,
    }


def list_runs(args: argparse.Namespace) -> dict[str, Any]:
    proxy = argparse.Namespace(after=None, limit=args.limit, job_id=args.job_id)
    payload = list_public_results(proxy)
    return {"ok": True, "message": f"Returned {len(payload['results'])} result(s)", "runs": payload["results"]}


def show_output(args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM results WHERE id=?", (args.run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Result not found: {args.run_id}")
    return {"ok": True, "result": result_row_to_public(row)}


def legacy_migration_snapshot() -> list[tuple[Any, ...]]:
    if not LEGACY_DB_PATH.is_file():
        raise ValueError("Legacy scheduler database is unavailable")
    with closing(sqlite3.connect(LEGACY_DB_PATH, timeout=30)) as legacy:
        legacy.row_factory = sqlite3.Row
        legacy.execute("PRAGMA query_only=ON")
        locks = legacy.execute("SELECT name FROM locks LIMIT 1").fetchall()
        if locks:
            raise ValueError("Legacy scheduler has an active lock; retry after the current run finishes")
        return migration_job_snapshot(legacy)


def verify_legacy_migration(_args: argparse.Namespace) -> dict[str, Any]:
    source = legacy_migration_snapshot()
    with closing(connect()) as target:
        target_rows = migration_job_snapshot(target)
    assert_migration_preserved(source, target_rows)
    return {
        "ok": True,
        "message": f"Verified exact migration of {len(source)} job(s)",
        "jobs": len(source),
        "fields": len(MIGRATION_JOB_COLUMNS),
    }


def migrate_legacy(_args: argparse.Namespace) -> dict[str, Any]:
    source = legacy_migration_snapshot()
    with closing(connect()) as target:
        existing = int(target.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        if existing:
            raise ValueError("Generic scheduler database already contains jobs")
        now = iso()
        with target:
            target.executemany(
                """
                INSERT INTO jobs(
                  id,name,schedule,kind,prompt,enabled,model,next_run_at,last_run_at,
                  last_status,run_count,created_at,updated_at,description
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                source,
            )
            assert_migration_preserved(source, migration_job_snapshot(target))
            target.execute("INSERT OR REPLACE INTO config(key,value,updated_at) VALUES('migrated_at',?,?)", (now, now))
    secure_database_permissions()
    return {
        "ok": True,
        "message": f"Migrated and verified {len(source)} job(s) into {DB_PATH}",
        "jobs": len(source),
        "fields": len(MIGRATION_JOB_COLUMNS),
    }


def scheduler_python() -> str:
    configured = os.environ.get("PI_PYTHON")
    if configured:
        path = Path(configured)
        return str(path if path.is_absolute() else ROOT / path)
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def install_launchd(_args: argparse.Namespace) -> dict[str, Any]:
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{scheduler_python()}</string><string>{Path(__file__).resolve()}</string><string>run-due</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{DEFAULT_PATH}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>{DEVNULL_PATH}</string>
  <key>StandardErrorPath</key><string>{DEVNULL_PATH}</string>
</dict></plist>
'''
    LAUNCHD_PLIST.write_text(plist, encoding="utf-8")
    os.chmod(LAUNCHD_PLIST, 0o644)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(LAUNCHD_PLIST)], capture_output=True, text=True)
    proc = subprocess.run(["launchctl", "bootstrap", domain, str(LAUNCHD_PLIST)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "launchctl bootstrap failed")
    return {"ok": True, "message": f"Installed scheduler: {LAUNCHD_PLIST}", "plist": str(LAUNCHD_PLIST)}


def uninstall_launchd(_args: argparse.Namespace) -> dict[str, Any]:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(LAUNCHD_PLIST)], capture_output=True, text=True)
    LAUNCHD_PLIST.unlink(missing_ok=True)
    return {"ok": True, "message": f"Removed scheduler: {LAUNCHD_PLIST}"}


def status(_args: argparse.Namespace) -> dict[str, Any]:
    with closing(connect()) as conn:
        job_count = int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        enabled_count = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE enabled=1").fetchone()[0])
        result_count = int(conn.execute("SELECT COUNT(*) FROM results").fetchone()[0])
        pending_count = int(conn.execute("SELECT COUNT(*) FROM notification_outbox WHERE status='pending'").fetchone()[0])
    installed = LAUNCHD_PLIST.exists() if sys.platform == "darwin" else False
    message = (
        f"JARVIS scheduler status\n- db: {DB_PATH}\n- jobs: {enabled_count}/{job_count} enabled\n"
        f"- results: {result_count}/{MAX_RESULTS}\n- pending notifications: {pending_count}\n"
        f"- launchd {LAUNCHD_LABEL} installed={installed}"
    )
    return {"ok": True, "message": message, "scheduler_installed": installed, "jobs": job_count, "results": result_count}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private Pi/JARVIS scheduled-job runner")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--job-id")
    add.add_argument("--name")
    add.add_argument("--schedule", required=True)
    add.add_argument("--kind", choices=["once", "interval", "cron"])
    add.add_argument("--prompt", required=True)
    add.add_argument("--model")
    add.add_argument("--description")
    sub.add_parser("list")
    sub.add_parser("list-public")
    results = sub.add_parser("list-results-public")
    results.add_argument("--after")
    results.add_argument("--limit", default="50")
    results.add_argument("--job-id")
    for command in ("remove", "enable", "disable", "run"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("job_id")
    sub.add_parser("run-due")
    runs = sub.add_parser("runs")
    runs.add_argument("--job-id")
    runs.add_argument("--limit", default="20")
    output = sub.add_parser("output")
    output.add_argument("run_id")
    sub.add_parser("migrate-legacy")
    sub.add_parser("verify-legacy-migration")
    sub.add_parser("install")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    sub.add_parser("notification-status")
    sub.add_parser("notification-enable")
    sub.add_parser("notification-disable")
    sub.add_parser("notification-drain")
    return parser


def main(argv: list[str] | None = None) -> int:
    config.load_project_env(ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        commands = {
            "add": add_job,
            "list": list_jobs,
            "list-public": list_public_jobs,
            "list-results-public": list_public_results,
            "remove": remove_job,
            "enable": lambda value: set_enabled(value, True),
            "disable": lambda value: set_enabled(value, False),
            "run-due": run_due,
            "run": run_one,
            "runs": list_runs,
            "output": show_output,
            "migrate-legacy": migrate_legacy,
            "verify-legacy-migration": verify_legacy_migration,
            "install": install_launchd,
            "uninstall": uninstall_launchd,
            "status": status,
            "notification-status": notification_status,
            "notification-enable": enable_notification_dispatch,
            "notification-disable": disable_notification_dispatch,
            "notification-drain": drain_notifications_command,
        }
        result = commands[args.command](args)
        if args.json:
            print(json.dumps(result, default=str))
        else:
            print(result.get("message") or json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        if args.json:
            print(json.dumps({"ok": False, "error": sanitize_text(exc)}))
        else:
            print(f"Error: {sanitize_text(exc)}", file=sys.stderr)
        return 1
    finally:
        secure_database_permissions()


if __name__ == "__main__":
    raise SystemExit(main())
