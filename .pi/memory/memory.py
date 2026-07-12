#!/usr/bin/env python3
"""Project-local long-term memory for JARVIS/Pi.

Stores durable facts, preferences, lessons, and workflow notes in a local SQLite
DB and exposes simple keyword/FTS recall for the Pi extension. This v1 avoids
automatic LLM consolidation so memories are explicit and auditable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / ".pi" / "memory" / "memory.sqlite"
SCHEMA_VERSION = "2"
KINDS = {"preference", "fact", "lesson", "project", "workflow"}
SCOPES = {"global", "project", "discord-channel"}
MAX_TEXT_CHARS = 8000


class MemoryError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            quoted = value[0] == '"'
            value = value[1:-1]
            if quoted:
                value = bytes(value, "utf-8").decode("unicode_escape")
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value


def resolve_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise MemoryError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise MemoryError(f"{name} must be >= {minimum}, got {value}")
    return value


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA secure_delete=ON")
    init_db(conn)
    purge_legacy_deleted_memories(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            scope TEXT NOT NULL DEFAULT 'global',
            confidence REAL NOT NULL DEFAULT 0.95,
            source TEXT NOT NULL DEFAULT 'user',
            cwd TEXT,
            discord_channel_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT,
            deleted_at TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            id UNINDEXED,
            kind,
            text,
            tags,
            scope
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            memory_id TEXT,
            summary TEXT,
            timestamp TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
        CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
        CREATE INDEX IF NOT EXISTS idx_memories_deleted_at ON memories(deleted_at);
        """
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def secure_compact(conn: sqlite3.Connection) -> None:
    """Remove recoverable deleted content from SQLite pages and WAL files."""
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def purge_legacy_deleted_memories(conn: sqlite3.Connection) -> int:
    """Permanently remove rows left by the former soft-delete implementation."""
    count = int(conn.execute("SELECT COUNT(*) FROM memories WHERE deleted_at IS NOT NULL").fetchone()[0])
    if count == 0:
        return 0
    with conn:
        conn.execute("DELETE FROM memories_fts WHERE id IN (SELECT id FROM memories WHERE deleted_at IS NOT NULL)")
        conn.execute("DELETE FROM events WHERE memory_id IN (SELECT id FROM memories WHERE deleted_at IS NOT NULL)")
        conn.execute("DELETE FROM memories WHERE deleted_at IS NOT NULL")
    secure_compact(conn)
    return count


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MemoryError(f"tags must be JSON array or comma-separated text: {exc}") from exc
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise MemoryError("tags JSON must be an array of strings")
        parts = data
    else:
        parts = raw.split(",")
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = re.sub(r"\s+", "-", str(part).strip().lower())
        tag = re.sub(r"[^a-z0-9_.:-]", "", tag)
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def validate_kind(kind: str) -> str:
    kind = (kind or "fact").strip().lower()
    if kind not in KINDS:
        raise MemoryError(f"kind must be one of {', '.join(sorted(KINDS))}, got {kind!r}")
    return kind


def validate_scope(scope: str) -> str:
    scope = (scope or "global").strip().lower()
    if scope not in SCOPES:
        raise MemoryError(f"scope must be one of {', '.join(sorted(SCOPES))}, got {scope!r}")
    return scope


def clean_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise MemoryError("memory text cannot be empty")
    if len(text) > MAX_TEXT_CHARS:
        raise MemoryError(f"memory text is too long ({len(text)} chars, max {MAX_TEXT_CHARS})")
    secret_patterns = [
        r"sk-[A-Za-z0-9_-]{20,}",
        r"ghp_[A-Za-z0-9_]{20,}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S{8,}",
    ]
    if any(re.search(pattern, text) for pattern in secret_patterns):
        raise MemoryError("refusing to store text that looks like a secret/token/password")
    return text


def row_to_memory(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags") or "[]")
    except json.JSONDecodeError:
        item["tags"] = []
    return item


def upsert_fts(conn: sqlite3.Connection, memory: dict[str, Any]) -> None:
    conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory["id"],))
    if memory.get("deleted_at"):
        return
    tags = memory.get("tags")
    if not isinstance(tags, str):
        tags = " ".join(tags or [])
    conn.execute(
        "INSERT INTO memories_fts(id, kind, text, tags, scope) VALUES(?, ?, ?, ?, ?)",
        (memory["id"], memory["kind"], memory["text"], tags, memory["scope"]),
    )


def log_event(conn: sqlite3.Connection, action: str, memory_id: str | None, summary: str | None = None) -> None:
    conn.execute(
        "INSERT INTO events(action, memory_id, summary, timestamp) VALUES(?, ?, ?, ?)",
        (action, memory_id, summary, utc_now()),
    )


def fts_query(query: str) -> str:
    tokens = re.findall(r"[\w][\w_.:-]*", query.lower())
    tokens = [token for token in tokens if len(token) > 1]
    if not tokens:
        return ""
    return " OR ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens[:20])


def base_filters(args: argparse.Namespace, values: list[Any], *, alias: str = "m") -> list[str]:
    filters = []
    if getattr(args, "kind", None):
        filters.append(f"{alias}.kind = ?")
        values.append(validate_kind(args.kind))
    if getattr(args, "scope", None):
        filters.append(f"{alias}.scope = ?")
        values.append(validate_scope(args.scope))
    if not getattr(args, "include_deleted", False):
        filters.append(f"{alias}.deleted_at IS NULL")
    return filters


def search_memories(conn: sqlite3.Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    query = (getattr(args, "query", "") or "").strip()
    limit = max(1, min(int(getattr(args, "limit", 10) or 10), 100))
    values: list[Any] = []
    filters = base_filters(args, values)
    match = fts_query(query)

    if match:
        where = ["memories_fts MATCH ?", *filters]
        params: list[Any] = [match, *values]
        sql = f"""
            SELECT m.*, bm25(memories_fts) AS rank
            FROM memories_fts
            JOIN memories m ON m.id = memories_fts.id
            WHERE {' AND '.join(where)}
            ORDER BY rank ASC, m.updated_at DESC
            LIMIT ?
        """
        rows = conn.execute(sql, (*params, limit)).fetchall()
    else:
        where = filters or ["1=1"]
        sql = f"SELECT m.*, 0.0 AS rank FROM memories m WHERE {' AND '.join(where)} ORDER BY m.updated_at DESC LIMIT ?"
        rows = conn.execute(sql, (*values, limit)).fetchall()

    results = []
    now = utc_now()
    for row in rows:
        memory = row_to_memory(row)
        memory["score"] = round(float(row["rank"]), 4) if "rank" in row.keys() else 0.0
        results.append(memory)
    if results:
        with conn:
            conn.executemany("UPDATE memories SET last_used_at = ? WHERE id = ?", [(now, item["id"]) for item in results])
    return results


def command_remember(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    text = clean_text(args.text or "")
    kind = validate_kind(args.kind or "fact")
    scope = validate_scope(args.scope or "global")
    tags = parse_tags(args.tags)
    confidence = float(args.confidence if args.confidence is not None else 0.95)
    if confidence < 0 or confidence > 1:
        raise MemoryError("confidence must be between 0 and 1")
    memory_id = uuid.uuid4().hex[:8]
    now = utc_now()
    memory = {
        "id": memory_id,
        "kind": kind,
        "text": text,
        "tags": tags,
        "scope": scope,
        "confidence": confidence,
        "source": (args.source or "user").strip() or "user",
        "cwd": args.cwd or None,
        "discord_channel_id": args.discord_channel_id or None,
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
        "deleted_at": None,
    }
    with conn:
        conn.execute(
            """
            INSERT INTO memories(id, kind, text, tags, scope, confidence, source, cwd, discord_channel_id, created_at, updated_at, last_used_at, deleted_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory["id"],
                memory["kind"],
                memory["text"],
                json.dumps(memory["tags"], ensure_ascii=False),
                memory["scope"],
                memory["confidence"],
                memory["source"],
                memory["cwd"],
                memory["discord_channel_id"],
                memory["created_at"],
                memory["updated_at"],
                memory["last_used_at"],
                memory["deleted_at"],
            ),
        )
        upsert_fts(conn, memory)
        log_event(conn, "remember", memory_id, text[:300])
    return {"ok": True, "memory": memory, "message": f"Remembered {kind} memory {memory_id}."}


def require_memory(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        raise MemoryError(f"memory not found: {memory_id}")
    return row_to_memory(row)


def command_update(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    if not args.id:
        raise MemoryError("update requires --id")
    memory = require_memory(conn, args.id)
    if args.text is not None:
        memory["text"] = clean_text(args.text)
    if args.kind is not None:
        memory["kind"] = validate_kind(args.kind)
    if args.scope is not None:
        memory["scope"] = validate_scope(args.scope)
    if args.tags is not None:
        memory["tags"] = parse_tags(args.tags)
    if args.confidence is not None:
        confidence = float(args.confidence)
        if confidence < 0 or confidence > 1:
            raise MemoryError("confidence must be between 0 and 1")
        memory["confidence"] = confidence
    memory["updated_at"] = utc_now()
    with conn:
        conn.execute(
            """
            UPDATE memories
            SET kind = ?, text = ?, tags = ?, scope = ?, confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                memory["kind"],
                memory["text"],
                json.dumps(memory["tags"], ensure_ascii=False),
                memory["scope"],
                memory["confidence"],
                memory["updated_at"],
                memory["id"],
            ),
        )
        upsert_fts(conn, memory)
        log_event(conn, "update", memory["id"], memory["text"][:300])
    return {"ok": True, "memory": memory, "message": f"Updated memory {memory['id']}."}


def command_forget(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    if not args.id:
        raise MemoryError("forget requires --id")
    memory_id = str(args.id)
    require_memory(conn, memory_id)
    with conn:
        conn.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
        conn.execute("DELETE FROM events WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    secure_compact(conn)
    return {"ok": True, "id": memory_id, "message": f"Permanently purged memory {memory_id}."}


def command_search(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    results = search_memories(conn, args)
    return {"ok": True, "query": args.query or "", "results": results}


def command_list(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    args.query = ""
    results = search_memories(conn, args)
    return {"ok": True, "results": results}


def format_recall_block(results: list[dict[str, Any]], max_chars: int) -> str:
    if not results:
        return ""
    lines = ["## Relevant long-term memory", "", "Use these project-local memories only when helpful; user instructions in the current conversation take priority."]
    for item in results:
        tags = f" tags={','.join(item['tags'])}" if item.get("tags") else ""
        lines.append(f"- [{item['kind']}/{item['scope']}] {item['text']} (id: {item['id']}; confidence: {item['confidence']}{tags})")
    block = "\n".join(lines).strip()
    if len(block) > max_chars:
        block = block[: max(0, max_chars - 20)].rstrip() + "\n… memory truncated …"
    return block


def command_recall(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    max_chars = max(500, min(int(args.max_chars or 3500), 12000))
    results = search_memories(conn, args)
    block = format_recall_block(results, max_chars)
    return {"ok": True, "query": args.query or "", "results": results, "block": block}


def command_status(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE deleted_at IS NULL").fetchone()["n"]
    deleted = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE deleted_at IS NOT NULL").fetchone()["n"]
    events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    by_kind = {row["kind"]: row["n"] for row in conn.execute("SELECT kind, COUNT(*) AS n FROM memories WHERE deleted_at IS NULL GROUP BY kind")}
    by_scope = {row["scope"]: row["n"] for row in conn.execute("SELECT scope, COUNT(*) AS n FROM memories WHERE deleted_at IS NULL GROUP BY scope")}
    latest = [row_to_memory(row) for row in conn.execute("SELECT * FROM memories WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT 5")]
    return {
        "ok": True,
        "db_path": str(resolve_path(args.db, DEFAULT_DB_PATH)),
        "schema_version": SCHEMA_VERSION,
        "active_memories": total,
        "deleted_memories": deleted,
        "events": events,
        "by_kind": by_kind,
        "by_scope": by_scope,
        "latest": latest,
    }


def emit(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("message"):
        print(result["message"])
    elif result.get("block"):
        print(result["block"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project-local JARVIS long-term memory")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--db", help="SQLite memory DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--kind", choices=sorted(KINDS))
        p.add_argument("--scope", choices=sorted(SCOPES))
        p.add_argument("--limit", type=int, default=10)

    p_search = sub.add_parser("search", help="search memories")
    p_search.add_argument("query", nargs="?", default="")
    add_common_filters(p_search)
    p_search.set_defaults(func=command_search)

    p_recall = sub.add_parser("recall", help="build a compact memory block for prompt injection")
    p_recall.add_argument("query", nargs="?", default="")
    p_recall.add_argument("--max-chars", type=int, default=3500)
    add_common_filters(p_recall)
    p_recall.set_defaults(func=command_recall)

    p_list = sub.add_parser("list", help="list recent memories")
    add_common_filters(p_list)
    p_list.set_defaults(func=command_list)

    p_remember = sub.add_parser("remember", help="store a memory")
    p_remember.add_argument("--text", required=True)
    p_remember.add_argument("--kind", choices=sorted(KINDS), default="fact")
    p_remember.add_argument("--tags")
    p_remember.add_argument("--scope", choices=sorted(SCOPES), default="global")
    p_remember.add_argument("--confidence", type=float, default=0.95)
    p_remember.add_argument("--source", default="user")
    p_remember.add_argument("--cwd")
    p_remember.add_argument("--discord-channel-id")
    p_remember.set_defaults(func=command_remember)

    p_update = sub.add_parser("update", help="update a memory")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--text")
    p_update.add_argument("--kind", choices=sorted(KINDS))
    p_update.add_argument("--tags")
    p_update.add_argument("--scope", choices=sorted(SCOPES))
    p_update.add_argument("--confidence", type=float)
    p_update.set_defaults(func=command_update)

    p_forget = sub.add_parser("forget", help="permanently purge a memory and its event history")
    p_forget.add_argument("--id", required=True)
    p_forget.set_defaults(func=command_forget)

    p_status = sub.add_parser("status", help="show memory DB status")
    p_status.set_defaults(func=command_status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = resolve_path(args.db, DEFAULT_DB_PATH)
    try:
        with connect(db_path) as conn:
            result = args.func(conn, args)
        emit(result, args.json)
        return 0
    except MemoryError as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        payload = {"ok": False, "error": f"SQLite error: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload["error"], file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
