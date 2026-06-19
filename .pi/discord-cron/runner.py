#!/usr/bin/env python3
"""Independent Pi scheduled-job runner with Discord output.

This file is cron/launchd-safe so it can be called without an already-running
Pi process. It stores jobs and configuration in SQLite, launches fresh
`pi --mode json` processes for due jobs, and posts run summaries to a Discord
channel using DISCORD_BOT_TOKEN from the project .env. Run output is not
persisted locally; Discord is the durable run log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

config.load_project_env(ROOT / ".env")
LOGGER = config.get_logger("jarvis.discord_cron")

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - surfaced at runtime
    requests = None  # type: ignore

PI_DIR = ROOT / ".pi"
DISCORD_CRON_DIR = PI_DIR / "discord-cron"
DB_PATH = DISCORD_CRON_DIR / "discord-cron.sqlite"
LEGACY_DB_PATH = PI_DIR / "discord-cron.sqlite"
LEGACY_CONFIG_PATH = PI_DIR / "discord-cron.json"
DEVNULL_PATH = Path("/dev/null")
LAUNCHD_LABEL = "com.jarvis.pi-discord-cron"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
DISCORD_API = "https://discord.com/api/v10"
DEFAULT_CHANNEL_NAME = "jarvis-cron"
DISCORD_PUBLIC_THREAD_TYPE = 11
DISCORD_THREAD_AUTO_ARCHIVE_MINUTES = 1440
DISCORD_SUPPRESS_EMBEDS_FLAG = 1 << 2
LOCK_STALE_SECONDS = 20 * 60
DEFAULT_PATH = config.DEFAULT_SCHEDULER_PATH
DIRECT_STDOUT_MODEL = "__direct_stdout__"


def _split_env_csv(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))


DISCORD_AUTO_THREAD_MEMBER_IDS = _split_env_csv(os.environ.get("DISCORD_AUTO_THREAD_MEMBER_IDS", ""))
DISCORD_AUTO_THREAD_MEMBER_QUERY = os.environ.get("DISCORD_AUTO_THREAD_MEMBER_QUERY", "dyl pickle").strip()

DURATION_RE = re.compile(r"^(\+?)(\d+)(s|m|h|d)$", re.I)
ISOISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime | None = None) -> str:
    return (ts or utcnow()).astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone(dt.timezone.utc)


def load_dotenv() -> dict[str, str]:
    return config.load_project_env(ROOT / ".env")


def _load_legacy_config() -> dict[str, Any]:
    if not LEGACY_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        LOGGER.warning("Failed to read legacy Discord cron config %s", LEGACY_CONFIG_PATH, exc_info=True)
        return {}


def _remove_legacy_config() -> None:
    try:
        LEGACY_CONFIG_PATH.unlink(missing_ok=True)
        LEGACY_CONFIG_PATH.with_suffix(".json.tmp").unlink(missing_ok=True)
    except Exception:
        LOGGER.debug("Failed to remove legacy Discord cron config", exc_info=True)


def load_config() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        config = {str(r["key"]): str(r["value"]) for r in rows}
        if config:
            _remove_legacy_config()
            return config

        legacy = _load_legacy_config()
        if legacy:
            now = iso()
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO config(key, value, updated_at) VALUES(?,?,?)",
                    [(str(k), str(v), now) for k, v in legacy.items() if v is not None],
                )
            _remove_legacy_config()
            return {str(k): str(v) for k, v in legacy.items() if v is not None}
    return {}


def save_config(config: dict[str, Any]) -> None:
    with connect() as conn:
        now = iso()
        with conn:
            conn.execute("DELETE FROM config")
            conn.executemany(
                "INSERT OR REPLACE INTO config(key, value, updated_at) VALUES(?,?,?)",
                [(str(k), str(v), now) for k, v in config.items() if v is not None],
            )
    _remove_legacy_config()


def connect() -> sqlite3.Connection:
    DISCORD_CRON_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        LEGACY_DB_PATH.replace(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


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
          discord_thread_id TEXT
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
        """
    )
    columns = {str(r[1]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "discord_thread_id" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN discord_thread_id TEXT")
    conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def infer_kind(schedule: str, explicit: str | None = None) -> str:
    if explicit:
        if explicit not in {"once", "interval", "cron"}:
            raise ValueError("kind must be once, interval, or cron")
        return explicit
    s = schedule.strip()
    if DURATION_RE.match(s):
        return "once" if s.startswith("+") else "interval"
    if ISOISH_RE.match(s):
        return "once"
    fields = s.split()
    if len(fields) in (5, 6):
        return "cron"
    raise ValueError("Could not infer schedule kind. Use +5m/2026-... for once, 5m for interval, or a 5/6-field cron expression.")


def parse_duration_ms(value: str) -> int:
    m = DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"Invalid duration: {value}. Use 30s, 5m, 1h, 2d, or +5m for one-shot.")
    amount = int(m.group(2))
    unit = m.group(3).lower()
    mult = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}[unit]
    return amount * mult


def cron_values(field: str, min_value: int, max_value: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            out.update(range(min_value, max_value + 1))
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError(f"Invalid cron step: {part}")
            out.update(range(min_value, max_value + 1, step))
            continue
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if "-" in base:
                start_s, end_s = base.split("-", 1)
                start, end = int(start_s), int(end_s)
            else:
                start, end = min_value, int(base)
            out.update(range(start, end + 1, step))
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            out.update(range(int(start_s), int(end_s) + 1))
            continue
        out.add(int(part))
    bad = [v for v in out if v < min_value or v > max_value]
    if bad:
        raise ValueError(f"Cron value out of range {min_value}-{max_value}: {bad[0]}")
    return out


def cron_next(schedule: str, after: dt.datetime) -> dt.datetime:
    fields = schedule.split()
    if len(fields) == 5:
        minute_f, hour_f, dom_f, month_f, dow_f = fields
        seconds = {0}
    elif len(fields) == 6:
        sec_f, minute_f, hour_f, dom_f, month_f, dow_f = fields
        seconds = cron_values(sec_f, 0, 59)
    else:
        raise ValueError("Cron schedule must have 5 or 6 fields")

    minutes = cron_values(minute_f, 0, 59)
    hours = cron_values(hour_f, 0, 23)
    dom = cron_values(dom_f, 1, 31)
    months = cron_values(month_f, 1, 12)
    dow = cron_values(dow_f, 0, 7)
    if 7 in dow:
        dow.add(0)
        dow.discard(7)

    # Cron runner is minute-granularity by default, but support second fields for
    # validation and for users who invoke run-due more often.
    cursor = (after + dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).replace(microsecond=0)
    for _ in range(366 * 24 * 60 * 60):
        cron_dow = (cursor.weekday() + 1) % 7  # Python Mon=0, cron Sun=0
        if (
            cursor.second in seconds
            and cursor.minute in minutes
            and cursor.hour in hours
            and cursor.day in dom
            and cursor.month in months
            and cron_dow in dow
        ):
            return cursor
        # Jump faster when seconds field cannot match.
        cursor += dt.timedelta(seconds=1 if len(seconds) != 1 else 60)
        if len(seconds) == 1:
            cursor = cursor.replace(second=next(iter(seconds)))
    raise ValueError("Could not find next cron run within one year")


def compute_next_run(schedule: str, kind: str, after: dt.datetime | None = None) -> str | None:
    after = after or utcnow()
    if kind == "once":
        s = schedule.strip()
        if s.startswith("+"):
            target = after + dt.timedelta(milliseconds=parse_duration_ms(s))
        else:
            target = parse_iso(s)
        if target <= after:
            raise ValueError(f"One-shot schedule is in the past: {target.isoformat()}")
        return iso(target)
    if kind == "interval":
        return iso(after + dt.timedelta(milliseconds=parse_duration_ms(schedule)))
    if kind == "cron":
        return iso(cron_next(schedule, after))
    raise ValueError(f"Unknown schedule kind: {kind}")


def validate_schedule(schedule: str, kind: str) -> None:
    compute_next_run(schedule, kind, utcnow())


def acquire_lock(conn: sqlite3.Connection, name: str) -> str | None:
    owner = str(uuid.uuid4())
    now = utcnow()
    stale_before = now - dt.timedelta(seconds=LOCK_STALE_SECONDS)
    with conn:
        conn.execute("DELETE FROM locks WHERE name = ? AND acquired_at < ?", (name, iso(stale_before)))
        try:
            conn.execute("INSERT INTO locks(name, owner, acquired_at) VALUES(?,?,?)", (name, owner, iso(now)))
            return owner
        except sqlite3.IntegrityError:
            return None


def release_lock(conn: sqlite3.Connection, name: str, owner: str) -> None:
    with conn:
        conn.execute("DELETE FROM locks WHERE name = ? AND owner = ?", (name, owner))


def add_job(args: argparse.Namespace) -> dict[str, Any]:
    kind = infer_kind(args.schedule, args.kind)
    next_run = compute_next_run(args.schedule, kind)
    job_id = args.job_id or f"job_{uuid.uuid4().hex[:12]}"
    name = args.name or job_id
    now = iso()
    with connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO jobs(id,name,schedule,kind,prompt,enabled,model,next_run_at,created_at,updated_at,description)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (job_id, name, args.schedule, kind, args.prompt, 1, args.model, next_run, now, now, args.description),
            )
        job = row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        thread_error: str | None = None
        if job:
            try:
                thread_id = get_or_create_job_thread(conn, job)
                if thread_id:
                    job["discord_thread_id"] = thread_id
            except Exception as exc:
                thread_error = str(exc)
    message = f"Scheduled {name} ({job_id}) next at {next_run}"
    if thread_error:
        message += f"; Discord thread creation failed: {thread_error}"
    return {"ok": True, "message": message, "job": job, "thread_error": thread_error}


def list_jobs(_args: argparse.Namespace) -> dict[str, Any]:
    with connect() as conn:
        jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY enabled DESC, next_run_at ASC, created_at DESC").fetchall()]
    lines = ["Scheduled Discord/Pi jobs:"]
    if not jobs:
        lines.append("  none")
    for j in jobs:
        status = "✓" if j["enabled"] else "✗"
        lines.append(f"  {status} {j['name']} ({j['id']}) {j['kind']} {j['schedule']} next={j['next_run_at'] or '-'} runs={j['run_count']}")
    return {"ok": True, "message": "\n".join(lines), "jobs": jobs}


def set_enabled(args: argparse.Namespace, enabled: bool) -> dict[str, Any]:
    with connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        next_run = compute_next_run(job["schedule"], job["kind"]) if enabled else job["next_run_at"]
        with conn:
            conn.execute("UPDATE jobs SET enabled=?, next_run_at=?, updated_at=? WHERE id=?", (1 if enabled else 0, next_run, iso(), job["id"]))
        updated = row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone())
    return {"ok": True, "message": f"{'Enabled' if enabled else 'Disabled'} {job['name']}", "job": updated}


def remove_job(args: argparse.Namespace) -> dict[str, Any]:
    with connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        thread_id = job["discord_thread_id"] if "discord_thread_id" in job.keys() else None
        with conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
    if thread_id:
        try:
            discord_request("PATCH", f"/channels/{thread_id}", json={"archived": True})
        except Exception:
            LOGGER.warning("Discord thread archive failed for %s", job["name"], exc_info=True)
    return {"ok": True, "message": f"Removed {job['name']} ({job['id']})"}


def discord_request(method: str, path: str, **kwargs: Any) -> Any:
    if requests is None:
        raise RuntimeError("The requests package is required. Install with: pip install -r requirements.txt")
    load_dotenv()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is missing from .env")
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bot {token}"
    url = f"{DISCORD_API}{path}"
    for _ in range(3):
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code == 429:
            try:
                delay = float(resp.json().get("retry_after", 1.0))
            except Exception:
                delay = 1.0
            time.sleep(delay)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"Discord API {method} {path} failed: HTTP {resp.status_code}: {resp.text[:500]}")
        if not resp.text:
            return None
        return resp.json()
    raise RuntimeError(f"Discord API {method} {path} failed after rate-limit retries")


def _job_value(job: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(job, sqlite3.Row):
        return job[key] if key in job.keys() else default
    return job.get(key, default)


def job_suppresses_embeds(job: sqlite3.Row | dict[str, Any]) -> bool:
    load_dotenv()
    targets = {
        target.casefold()
        for target in _split_env_csv(
            os.environ.get(
                "DISCORD_CRON_SUPPRESS_EMBEDS_JOBS",
                "gear-hunter,gear_hunter_scraper,job_b0aa6caad0c9,briefing,ai-news,job_b9396449910a",
            )
        )
    }
    identifiers = (
        str(_job_value(job, "name", "") or "").strip().casefold(),
        str(_job_value(job, "id", "") or "").strip().casefold(),
    )
    return any(identifier and identifier in targets for identifier in identifiers)


def job_posts_success_body_only(job: sqlite3.Row | dict[str, Any]) -> bool:
    """Return True for jobs whose successful assistant output should be posted without scheduler metadata."""
    load_dotenv()
    targets = {
        target.casefold()
        for target in _split_env_csv(
            os.environ.get(
                "DISCORD_CRON_BODY_ONLY_SUCCESS_JOBS",
                "briefing,ai-news,job_b9396449910a",
            )
        )
    }
    identifiers = (
        str(_job_value(job, "name", "") or "").strip().casefold(),
        str(_job_value(job, "id", "") or "").strip().casefold(),
    )
    return any(identifier and identifier in targets for identifier in identifiers)


def discord_thread_name(job_name: str) -> str:
    name = re.sub(r"\s+", " ", str(job_name or "")).strip() or "unnamed-cron-job"
    return name[:100]


def _thread_member_names(member_payload: dict[str, Any]) -> tuple[str, ...]:
    user_payload = member_payload.get("user")
    user = user_payload if isinstance(user_payload, dict) else {}
    names = [member_payload.get("nick"), user.get("global_name"), user.get("username")]
    return tuple(str(name).strip() for name in names if isinstance(name, str) and name.strip())


def resolve_auto_thread_member_ids(guild_id: str | None = None) -> tuple[str, ...]:
    resolved = list(DISCORD_AUTO_THREAD_MEMBER_IDS)
    query = DISCORD_AUTO_THREAD_MEMBER_QUERY.strip()
    if query and guild_id:
        try:
            members = discord_request("GET", f"/guilds/{guild_id}/members/search?query={quote(query)}&limit=25")
            needle = query.casefold()
            exact_match_id: str | None = None
            fallback_match_id: str | None = None
            for member in members if isinstance(members, list) else []:
                if not isinstance(member, dict):
                    continue
                names = _thread_member_names(member)
                user_payload = member.get("user")
                user = user_payload if isinstance(user_payload, dict) else {}
                user_id = str(user.get("id") or "").strip()
                if not user_id:
                    continue
                if exact_match_id is None and any(name.casefold() == needle for name in names):
                    exact_match_id = user_id
                    break
                if fallback_match_id is None and any(needle in name.casefold() for name in names):
                    fallback_match_id = user_id
            chosen = exact_match_id or fallback_match_id
            if chosen:
                resolved.append(chosen)
        except Exception:
            LOGGER.debug("Failed to resolve auto thread member by query '%s' in guild %s", query, guild_id, exc_info=True)
    return tuple(dict.fromkeys(member_id for member_id in resolved if str(member_id).strip()))


def add_auto_members_to_thread(thread_id: str, *, guild_id: str | None = None) -> None:
    for member_id in resolve_auto_thread_member_ids(guild_id):
        try:
            discord_request("PUT", f"/channels/{thread_id}/thread-members/{member_id}")
        except Exception:
            LOGGER.debug("Failed to auto-add member %s to thread %s", member_id, thread_id, exc_info=True)


def get_or_create_job_thread(
    conn: sqlite3.Connection,
    job: sqlite3.Row | dict[str, Any],
    *,
    channel_id: str | None = None,
    force_new: bool = False,
) -> str | None:
    channel_id = channel_id or get_discord_channel_id()
    if not channel_id:
        return None

    job_id = str(_job_value(job, "id"))
    job_name = str(_job_value(job, "name", job_id))
    thread_name = discord_thread_name(job_name)
    stored_thread_id = str(_job_value(job, "discord_thread_id", "") or "").strip()

    if stored_thread_id and not force_new:
        try:
            discord_request("PATCH", f"/channels/{stored_thread_id}", json={"name": thread_name, "archived": False})
            add_auto_members_to_thread(stored_thread_id, guild_id=str(load_config().get("discord_guild_id") or "") or None)
            return stored_thread_id
        except Exception:
            LOGGER.warning("Stored Discord thread unavailable for %s", job_name, exc_info=True)

    thread = discord_request(
        "POST",
        f"/channels/{channel_id}/threads",
        json={
            "name": thread_name,
            "type": DISCORD_PUBLIC_THREAD_TYPE,
            "auto_archive_duration": DISCORD_THREAD_AUTO_ARCHIVE_MINUTES,
        },
    )
    thread_id = str(thread["id"])
    with conn:
        conn.execute("UPDATE jobs SET discord_thread_id=?, updated_at=? WHERE id=?", (thread_id, iso(), job_id))
    add_auto_members_to_thread(thread_id, guild_id=str(thread.get("guild_id") or load_config().get("discord_guild_id") or "") or None)
    try:
        discord_request("POST", f"/channels/{thread_id}/messages", json={"content": f"🧵 Scheduled Pi job thread for **{job_name}**."})
    except Exception:
        LOGGER.warning("Discord thread intro post failed for %s", job_name, exc_info=True)
    return thread_id


def ensure_job_threads_for_channel(channel_id: str, *, force_new: bool = False) -> tuple[list[dict[str, str]], list[str]]:
    threads: list[dict[str, str]] = []
    errors: list[str] = []
    with connect() as conn:
        if force_new:
            with conn:
                conn.execute("UPDATE jobs SET discord_thread_id=NULL")
        jobs = conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
        for job in jobs:
            try:
                thread_id = get_or_create_job_thread(conn, job, channel_id=channel_id, force_new=force_new)
                if thread_id:
                    threads.append({"job_id": str(job["id"]), "job_name": str(job["name"]), "thread_id": thread_id})
            except Exception as exc:
                errors.append(f"{job['name']}: {exc}")
    return threads, errors


def setup_discord(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv()
    config = load_config()
    channel_name = args.channel_name or os.environ.get("DISCORD_CRON_CHANNEL_NAME") or config.get("discord_channel_name") or DEFAULT_CHANNEL_NAME
    guild_id = args.guild_id or os.environ.get("DISCORD_CRON_GUILD_ID") or os.environ.get("DISCORD_GUILD_ID") or config.get("discord_guild_id")
    recreate = bool(getattr(args, "recreate_channel", False))

    if not guild_id:
        guilds = discord_request("GET", "/users/@me/guilds")
        if len(guilds) == 1:
            guild_id = guilds[0]["id"]
        elif len(guilds) == 0:
            raise RuntimeError("Bot is not in any Discord guild/server")
        else:
            names = ", ".join(f"{g.get('name')}={g.get('id')}" for g in guilds)
            raise RuntimeError(f"Bot is in multiple guilds. Set DISCORD_CRON_GUILD_ID in .env. Guilds: {names}")

    channels = discord_request("GET", f"/guilds/{guild_id}/channels")
    configured_channel_id = str(config.get("discord_channel_id") or "")
    delete_targets: dict[str, dict[str, Any]] = {}
    if recreate:
        for c in channels:
            if c.get("type") == 0 and (str(c.get("id")) == configured_channel_id or c.get("name") == channel_name):
                delete_targets[str(c["id"])] = c
        for channel_id in delete_targets:
            try:
                discord_request("DELETE", f"/channels/{channel_id}")
            except Exception as exc:
                if "HTTP 404" not in str(exc):
                    raise
        channels = discord_request("GET", f"/guilds/{guild_id}/channels")

    channel = next((c for c in channels if c.get("type") == 0 and c.get("name") == channel_name), None)
    created = False
    if channel is None:
        channel = discord_request("POST", f"/guilds/{guild_id}/channels", json={"name": channel_name, "type": 0, "topic": "Hidden Pi scheduled job output, with one thread per cron job"})
        created = True

    config.update({
        "discord_guild_id": str(guild_id),
        "discord_channel_id": str(channel["id"]),
        "discord_channel_name": channel_name,
        "updated_at": iso(),
    })
    save_config(config)

    threads, thread_errors = ensure_job_threads_for_channel(str(channel["id"]), force_new=recreate)
    thread_summary = f"Created/configured {len(threads)} job thread(s)."
    if thread_errors:
        thread_summary += " Thread errors: " + "; ".join(thread_errors)
    post_discord(
        f"✅ Pi scheduled job output channel {'created' if created else 'configured'}: <#{channel['id']}>\n{thread_summary}",
        force_channel_id=str(channel["id"]),
    )
    action = "recreated" if recreate else ("created" if created else "configured")
    return {
        "ok": True,
        "message": f"Discord channel {action}: #{channel_name} ({channel['id']}); {thread_summary}",
        "channel": channel,
        "created": created,
        "recreated": recreate,
        "deleted_channel_ids": list(delete_targets.keys()),
        "threads": threads,
        "thread_errors": thread_errors,
    }


def get_discord_channel_id() -> str | None:
    load_dotenv()
    config = load_config()
    return str(os.environ.get("DISCORD_CRON_CHANNEL_ID") or config.get("discord_channel_id") or "").strip() or None


def chunk_text(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current += line
    if current:
        chunks.append(current)
    return chunks


def post_discord(
    content: str,
    *,
    force_channel_id: str | None = None,
    thread_id: str | None = None,
    file_path: Path | None = None,
    suppress_embeds: bool = False,
) -> None:
    """Post text to Discord.

    file_path is accepted for backwards-compatible call sites, but intentionally
    ignored: cron output should live only in Discord messages, not attachments.
    """
    del file_path
    channel_id = thread_id or force_channel_id or get_discord_channel_id()
    if not channel_id:
        return
    for chunk in chunk_text(content):
        payload: dict[str, Any] = {"content": chunk}
        if suppress_embeds:
            payload["flags"] = DISCORD_SUPPRESS_EMBEDS_FLAG
        discord_request("POST", f"/channels/{channel_id}/messages", json=payload)


def safe_post_discord(
    content: str,
    *,
    file_path: Path | None = None,
    thread_id: str | None = None,
    suppress_embeds: bool = False,
) -> None:
    try:
        post_discord(content, file_path=file_path, thread_id=thread_id, suppress_embeds=suppress_embeds)
    except Exception:
        # Do not persist a separate runner log; launchd/cron output is discarded
        # by installation below and Discord is the only durable run log.
        LOGGER.warning("Discord post failed", exc_info=True)


def safe_post_job_discord(conn: sqlite3.Connection, job: sqlite3.Row | dict[str, Any], content: str, *, file_path: Path | None = None) -> None:
    thread_id: str | None = None
    suppress_embeds = job_suppresses_embeds(job)
    try:
        thread_id = get_or_create_job_thread(conn, job)
    except Exception:
        LOGGER.warning("Discord job thread lookup failed for %s", _job_value(job, "name", "unknown"), exc_info=True)
    safe_post_discord(content, file_path=file_path, thread_id=thread_id, suppress_embeds=suppress_embeds)


def extract_text_part(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


def _json_event_error(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    error_message = str(message.get("errorMessage") or message.get("error_message") or "").strip()
    if error_message:
        return error_message
    stop_reason = str(message.get("stopReason") or message.get("stop_reason") or "").strip().lower()
    if stop_reason == "error":
        return "Assistant message stopped with an error."
    return None


def parse_json_events(stdout: str) -> tuple[str, str | None, str | None]:
    assistant = ""
    deltas: list[str] = []
    session_file: str | None = None
    json_errors: list[str] = []
    non_json_lines: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            if line.strip():
                non_json_lines.append(line)
            continue
        if isinstance(event, dict):
            session_file = session_file or event.get("sessionFile") or event.get("session_file")
            for candidate in (event, event.get("message")):
                json_error = _json_event_error(candidate)
                if json_error and json_error not in json_errors:
                    json_errors.append(json_error)
            if event.get("type") == "message_update":
                ame = event.get("assistantMessageEvent") or event.get("assistant_message_event") or {}
                if isinstance(ame, dict):
                    json_error = _json_event_error(ame.get("partial"))
                    if json_error and json_error not in json_errors:
                        json_errors.append(json_error)
                    if ame.get("type") == "text_delta":
                        deltas.append(str(ame.get("delta", "")))
            msg = event.get("message")
            if event.get("type") in {"message_end", "message"} and isinstance(msg, dict) and msg.get("role") == "assistant":
                text = extract_text_part(msg.get("content"))
                if text.strip():
                    assistant = text.strip()
    if not assistant and deltas:
        assistant = "".join(deltas).strip()
    if not assistant and non_json_lines and not json_errors:
        assistant = "\n".join(non_json_lines).strip()[-4000:]
    json_error = "\n".join(json_errors[:3]) if json_errors else None
    return assistant, session_file, json_error



def write_run_artifacts(
    *,
    run_id: str,
    job: sqlite3.Row,
    started: dt.datetime,
    finished: dt.datetime,
    status: str,
    exit_code: int | None,
    duration_seconds: float,
    assistant_text: str,
    error: str | None,
    stdout: str,
    stderr: str,
    stdout_is_jsonl: bool,
    session_file: str | None = None,
) -> dict[str, str | None]:
    # Runs are intentionally not persisted to disk. Discord messages are the
    # durable log; returning empty artifact paths keeps older call sites safe.
    del run_id, job, started, finished, status, exit_code, duration_seconds
    del assistant_text, error, stdout, stderr, stdout_is_jsonl, session_file
    return {"md_path": None, "jsonl_path": None, "stderr_path": None}


def build_pi_command(job: sqlite3.Row) -> list[str]:
    load_dotenv()
    pi_cmd = os.environ.get("PI_CODING_AGENT_COMMAND", "pi")
    cmd = shlex.split(pi_cmd)
    cmd.extend(["--mode", "json", "--no-session"])
    model = job["model"] or os.environ.get("DISCORD_CRON_PI_MODEL") or os.environ.get("DISCORD_PI_MODEL")
    if model:
        cmd.extend(["--model", model])
    system_note = (
        "You are running as an unattended scheduled Pi job. "
        f"Job name: {job['name']}. Job id: {job['id']}. "
        "Return the requested result as your final answer only; the scheduler will post it to the job's Discord thread. "
        "Do not call discord_ping, do not ping anyone, and do not send messages to other channels or threads unless the job prompt explicitly requests that tool. "
        "Do not ask the user for clarification; make a best effort and report blockers."
    )
    cmd.extend(["--append-system-prompt", system_note, job["prompt"]])
    return cmd


def run_direct_stdout_for_job(conn: sqlite3.Connection, job: sqlite3.Row) -> dict[str, Any]:
    run_id = f"run_{utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    started = utcnow()

    load_dotenv()
    cmd = shlex.split(job["prompt"])
    timeout = int(os.environ.get("DISCORD_CRON_TIMEOUT_SECONDS") or "900")
    env = os.environ.copy()
    existing_path = env.get("PATH", "")
    env["PATH"] = DEFAULT_PATH if not existing_path else f"{DEFAULT_PATH}:{existing_path}"
    status = "success"
    exit_code: int | None = None
    error: str | None = None
    stdout = ""
    stderr = ""
    try:
        LOGGER.info("Starting scheduled command run_id=%s job=%s", run_id, job["name"])
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=timeout)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
        if proc.returncode != 0:
            status = "error"
            error = f"command exited with code {proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        status = "error"
        error = f"command timed out after {timeout}s"
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        exit_code = 124
    except Exception as exc:
        status = "error"
        error = str(exc)
        exit_code = 1

    finished = utcnow()
    duration = (finished - started).total_seconds()
    if stderr.strip():
        stderr_tail = stderr[-4000:]
        error = f"{error}\n\nstderr tail:\n{stderr_tail}" if error else f"stderr tail:\n{stderr_tail}"

    artifacts = write_run_artifacts(
        run_id=run_id,
        job=job,
        started=started,
        finished=finished,
        status=status,
        exit_code=exit_code,
        duration_seconds=duration,
        assistant_text=stdout,
        error=error,
        stdout=stdout,
        stderr=stderr,
        stdout_is_jsonl=False,
    )

    with conn:
        conn.execute(
            """
            UPDATE jobs SET last_run_at=?, last_status=?, run_count=run_count+1, updated_at=? WHERE id=?
            """,
            (iso(finished), status, iso(finished), job["id"]),
        )

    LOGGER.info("Finished scheduled command run_id=%s job=%s status=%s duration=%.1fs", run_id, job["name"], status, duration)
    if stdout.strip():
        safe_post_job_discord(conn, job, stdout)
    elif error:
        safe_post_job_discord(
            conn,
            job,
            f"❌ Scheduled command failed: **{job['name']}**\nRun: `{run_id}`\nDuration: `{duration:.1f}s`\n\n{error}",
        )

    return {
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "assistant_text": stdout,
        "error": error,
        **artifacts,
    }


def run_pi_for_job(conn: sqlite3.Connection, job: sqlite3.Row, *, forced: bool = False) -> dict[str, Any]:
    if job["model"] == DIRECT_STDOUT_MODEL:
        return run_direct_stdout_for_job(conn, job)

    run_id = f"run_{utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    started = utcnow()

    cmd = build_pi_command(job)
    timeout = int(os.environ.get("DISCORD_CRON_TIMEOUT_SECONDS") or os.environ.get("PI_CODING_AGENT_RPC_TIMEOUT_SECONDS") or "900")
    env = os.environ.copy()
    existing_path = env.get("PATH", "")
    env["PATH"] = DEFAULT_PATH if not existing_path else f"{DEFAULT_PATH}:{existing_path}"
    status = "success"
    exit_code: int | None = None
    error: str | None = None
    stdout = ""
    stderr = ""
    try:
        LOGGER.info("Starting scheduled Pi run_id=%s job=%s forced=%s", run_id, job["name"], forced)
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=timeout)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
        if proc.returncode != 0:
            status = "error"
            error = f"pi exited with code {proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        status = "error"
        error = f"pi timed out after {timeout}s"
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        exit_code = 124
    except Exception as exc:
        status = "error"
        error = str(exc)
        exit_code = 1

    assistant, session_file, json_error = parse_json_events(stdout)
    if json_error:
        status = "error"
        error = f"{error}\n\n{json_error}" if error else json_error
    finished = utcnow()
    duration = (finished - started).total_seconds()
    if stderr.strip():
        stderr_tail = stderr[-4000:]
        error = f"{error}\n\nstderr tail:\n{stderr_tail}" if error else f"stderr tail:\n{stderr_tail}"

    artifacts = write_run_artifacts(
        run_id=run_id,
        job=job,
        started=started,
        finished=finished,
        status=status,
        exit_code=exit_code,
        duration_seconds=duration,
        assistant_text=assistant,
        error=error,
        stdout=stdout,
        stderr=stderr,
        stdout_is_jsonl=True,
        session_file=session_file,
    )

    with conn:
        conn.execute(
            """
            UPDATE jobs SET last_run_at=?, last_status=?, run_count=run_count+1, updated_at=? WHERE id=?
            """,
            (iso(finished), status, iso(finished), job["id"]),
        )

    LOGGER.info("Finished scheduled Pi run_id=%s job=%s status=%s duration=%.1fs", run_id, job["name"], status, duration)
    body = assistant.strip() or error or "No assistant output captured."
    if status == "success" and assistant.strip() and job_posts_success_body_only(job):
        msg = body
    else:
        icon = "✅" if status == "success" else "❌"
        msg = f"{icon} Scheduled Pi job {status}: **{job['name']}**\nRun: `{run_id}`\nDuration: `{duration:.1f}s`\n\n{body}"
    safe_post_job_discord(conn, job, msg)
    return {
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "assistant_text": assistant,
        "error": error,
        **artifacts,
    }


def claim_due_jobs(conn: sqlite3.Connection, now: dt.datetime) -> list[sqlite3.Row]:
    due = conn.execute(
        "SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at ASC LIMIT 10",
        (iso(now),),
    ).fetchall()
    claimed: list[sqlite3.Row] = []
    with conn:
        for job in due:
            try:
                if job["kind"] == "once":
                    next_run = None
                    enabled = 0
                else:
                    next_run = compute_next_run(job["schedule"], job["kind"], now)
                    enabled = 1
                conn.execute(
                    "UPDATE jobs SET enabled=?, next_run_at=?, last_status='running', updated_at=? WHERE id=?",
                    (enabled, next_run, iso(now), job["id"]),
                )
                claimed.append(job)
            except Exception as exc:
                conn.execute(
                    "UPDATE jobs SET last_status='error', updated_at=? WHERE id=?",
                    (iso(now), job["id"]),
                )
                safe_post_job_discord(conn, job, f"❌ Failed to compute next run for **{job['name']}**: {exc}")
    return claimed


def run_due(_args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv()
    with connect() as conn:
        owner = acquire_lock(conn, "run-due")
        if not owner:
            return {"ok": True, "message": "Another runner is active; skipped.", "runs": []}
        try:
            jobs = claim_due_jobs(conn, utcnow())
        finally:
            release_lock(conn, "run-due", owner)

        results = []
        for job in jobs:
            results.append(run_pi_for_job(conn, job))
    return {"ok": True, "message": f"Ran {len(results)} due job(s)", "runs": results}


def run_one(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv()
    with connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? OR name=?", (args.job_id, args.job_id)).fetchone()
        if not job:
            raise ValueError(f"Job not found: {args.job_id}")
        result = run_pi_for_job(conn, job, forced=True)
    return {"ok": True, "message": f"Ran {job['name']}: {result['status']}", "run": result}


def list_runs(args: argparse.Namespace) -> dict[str, Any]:
    del args
    message = "Run history storage is disabled. Scheduled job output is posted only to Discord."
    return {"ok": True, "message": message, "runs": []}


def show_output(args: argparse.Namespace) -> dict[str, Any]:
    del args
    raise ValueError("Run output storage is disabled. Scheduled job output is available only in Discord.")


def scheduler_python() -> str:
    configured = os.environ.get("PI_PYTHON")
    if configured:
        path = Path(configured)
        return str(path if path.is_absolute() else ROOT / path)
    return str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable


def install_launchd() -> dict[str, Any]:
    # macOS cron installation can hang in some managed terminals. launchd is the
    # native per-user scheduler and continues running independently of Pi.
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{scheduler_python()}</string>
    <string>{Path(__file__).resolve()}</string>
    <string>run-due</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{DEFAULT_PATH}</string>
  </dict>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{DEVNULL_PATH}</string>
  <key>StandardErrorPath</key><string>{DEVNULL_PATH}</string>
</dict>
</plist>
'''
    LAUNCHD_PLIST.write_text(plist, encoding="utf-8")
    os.chmod(LAUNCHD_PLIST, 0o644)
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], text=True, capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "launchctl load failed")
    return {"ok": True, "message": f"Installed launchd scheduler: {LAUNCHD_PLIST}\nRuns every 60 seconds; runner stdout/stderr are discarded", "plist": str(LAUNCHD_PLIST)}


def uninstall_launchd() -> dict[str, Any]:
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], text=True, capture_output=True)
    if LAUNCHD_PLIST.exists():
        LAUNCHD_PLIST.unlink()
    return {"ok": True, "message": f"Removed launchd scheduler: {LAUNCHD_PLIST}"}


def install_cron(_args: argparse.Namespace) -> dict[str, Any]:
    if sys.platform == "darwin":
        return install_launchd()
    python = scheduler_python()
    marker = "# pi-discord-cron:JARVIS"
    line = f"* * * * * cd {shlex.quote(str(ROOT))} && {shlex.quote(python)} {shlex.quote(str(Path(__file__).resolve()))} run-due > {shlex.quote(str(DEVNULL_PATH))} 2>&1 {marker}"
    existing = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    current = existing.stdout if existing.returncode == 0 else ""
    kept = [l for l in current.splitlines() if marker not in l]
    kept.append(line)
    new_tab = "\n".join(kept).rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(new_tab)
        temp_name = f.name
    try:
        proc = subprocess.run(["crontab", temp_name], text=True, capture_output=True)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "crontab install failed")
    return {"ok": True, "message": f"Installed cron runner:\n{line}", "line": line}


def uninstall_cron(_args: argparse.Namespace) -> dict[str, Any]:
    if sys.platform == "darwin":
        return uninstall_launchd()
    marker = "# pi-discord-cron:JARVIS"
    existing = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    current = existing.stdout if existing.returncode == 0 else ""
    kept = [l for l in current.splitlines() if marker not in l]
    new_tab = "\n".join(kept).rstrip() + "\n" if kept else ""
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(new_tab)
        temp_name = f.name
    try:
        proc = subprocess.run(["crontab", temp_name], text=True, capture_output=True)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "crontab uninstall failed")
    return {"ok": True, "message": "Removed pi-discord-cron crontab entry"}


def status(_args: argparse.Namespace) -> dict[str, Any]:
    config = load_config()
    with connect() as conn:
        job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        enabled_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE enabled=1").fetchone()[0]
    if sys.platform == "darwin":
        scheduler_installed = LAUNCHD_PLIST.exists()
        scheduler_label = f"launchd {LAUNCHD_LABEL}"
    else:
        cron = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
        scheduler_installed = "pi-discord-cron:JARVIS" in (cron.stdout or "")
        scheduler_label = "cron"
    message = (
        f"Discord cron status\n"
        f"- db: {DB_PATH}\n- channel: {config.get('discord_channel_name')} ({config.get('discord_channel_id')})\n"
        f"- jobs: {enabled_count}/{job_count} enabled\n- scheduler: {scheduler_label} installed={scheduler_installed}\n"
    )
    return {"ok": True, "message": message, "config": config, "cron_installed": scheduler_installed, "last_runs": []}


def setup(args: argparse.Namespace) -> dict[str, Any]:
    discord = setup_discord(args)
    cron = install_cron(args)
    return {"ok": True, "message": discord["message"] + "\n" + cron["message"], "discord": discord, "cron": cron}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Independent Pi scheduled-job runner with Discord output")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common_job(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--job-id")
        sp.add_argument("--name")
        sp.add_argument("--schedule", required=True)
        sp.add_argument("--kind", choices=["once", "interval", "cron"])
        sp.add_argument("--prompt", required=True)
        sp.add_argument("--model")
        sp.add_argument("--description")

    add_common_job(sub.add_parser("add"))
    sub.add_parser("list")
    for cmd in ["remove", "enable", "disable", "run"]:
        sp = sub.add_parser(cmd)
        sp.add_argument("job_id")
    sub.add_parser("run-due")
    sp = sub.add_parser("runs")
    sp.add_argument("--job-id")
    sp.add_argument("--limit", default="20")
    sp = sub.add_parser("output")
    sp.add_argument("run_id")
    sp = sub.add_parser("setup-discord")
    sp.add_argument("--guild-id")
    sp.add_argument("--channel-name")
    sp.add_argument("--recreate-channel", action="store_true", help="Delete and recreate the configured cron channel, then create one thread per job")
    sp = sub.add_parser("setup")
    sp.add_argument("--guild-id")
    sp.add_argument("--channel-name")
    sp.add_argument("--recreate-channel", action="store_true", help="Delete and recreate the configured cron channel, then create one thread per job")
    sub.add_parser("install-cron")
    sub.add_parser("uninstall-cron")
    sub.add_parser("status")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command = args.command
        if command == "add":
            result = add_job(args)
        elif command == "list":
            result = list_jobs(args)
        elif command == "remove":
            result = remove_job(args)
        elif command == "enable":
            result = set_enabled(args, True)
        elif command == "disable":
            result = set_enabled(args, False)
        elif command == "run-due":
            result = run_due(args)
        elif command == "run":
            result = run_one(args)
        elif command == "runs":
            result = list_runs(args)
        elif command == "output":
            result = show_output(args)
        elif command == "setup-discord":
            result = setup_discord(args)
        elif command == "install-cron":
            result = install_cron(args)
        elif command == "uninstall-cron":
            result = uninstall_cron(args)
        elif command == "status":
            result = status(args)
        elif command == "setup":
            result = setup(args)
        else:
            raise ValueError(f"Unknown command: {command}")
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        elif not (args.command == "run-due" and not result.get("runs")):
            print(result.get("message", json.dumps(result, indent=2, default=str)))
        return 0
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(result, indent=2), file=sys.stdout)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
