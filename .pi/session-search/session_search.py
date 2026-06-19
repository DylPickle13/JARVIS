#!/usr/bin/env python3
"""Semantic search over Pi JSONL session history using a local OpenAI-compatible embeddings endpoint.

The indexer is intentionally incremental: it embeds only new or changed session files.
Defaults are tuned for the JARVIS project, but every path/model/endpoint can be overridden
with environment variables or CLI flags.
"""

from __future__ import annotations

import argparse
import array
import contextlib
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import math
import os
import sqlite3
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions" / "--Users-gemma-JARVIS--"
DEFAULT_DB_PATH = PROJECT_ROOT / ".pi" / "session-search" / "index.sqlite"
DEFAULT_LOG_PATH = PROJECT_ROOT / ".pi" / "session-search" / "cron.log"
DEFAULT_MODEL = "mlx-community/Qwen3-Embedding-8B-4bit-DWQ"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
SCHEMA_VERSION = "1"
DOC_PREFIX = "Represent this coding-agent session chunk for retrieval: "
QUERY_PREFIX = "Represent this query for retrieving relevant coding-agent session history: "
MAX_CHARS_PER_CHUNK = 6500
OVERLAP_CHARS = 900
MAX_FIELD_CHARS = 5000


def sanitize_text(value: str) -> str:
    """Remove invalid Unicode surrogates that can crash local tokenizers/JSON decoders."""
    if not value:
        return ""
    return "".join("\ufffd" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in value)


class SessionSearchError(RuntimeError):
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
            value = value[1:-1]
            if raw.strip().split("=", 1)[1].strip().startswith('"'):
                value = bytes(value, "utf-8").decode("unicode_escape")
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SessionSearchError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise SessionSearchError(f"{name} must be >= {minimum}, got {value}")
    return value


def resolve_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def embedding_base_url() -> str:
    return (
        os.environ.get("SESSION_SEARCH_EMBEDDING_BASE_URL", "").strip()
        or os.environ.get("OMLX_EMBEDDING_BASE_URL", "").strip()
        or os.environ.get("OMLX_BASE_URL", "").strip()
        or os.environ.get("DISCORD_AUDIO_TRANSCRIPTION_BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )


def embedding_url() -> str:
    base = embedding_base_url().rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


def embedding_model() -> str:
    return os.environ.get("SESSION_SEARCH_EMBEDDING_MODEL", "").strip() or DEFAULT_MODEL


def embedding_dimensions() -> int | None:
    raw = os.environ.get("SESSION_SEARCH_EMBEDDING_DIMENSIONS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise SessionSearchError(f"SESSION_SEARCH_EMBEDDING_DIMENSIONS must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise SessionSearchError("SESSION_SEARCH_EMBEDDING_DIMENSIONS must be positive")
    return value


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            path TEXT PRIMARY KEY,
            session_id TEXT,
            started_at TEXT,
            cwd TEXT,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_path TEXT NOT NULL REFERENCES sessions(path) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            start_line INTEGER,
            end_line INTEGER,
            started_at TEXT,
            text TEXT NOT NULL,
            preview TEXT NOT NULL,
            UNIQUE(session_path, chunk_index)
        );
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            norm REAL NOT NULL,
            vector BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_session_path ON chunks(session_path);
        CREATE INDEX IF NOT EXISTS idx_embeddings_model_dims ON embeddings(model, dimensions);
        """
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.commit()


@contextlib.contextmanager
def index_lock(db_path: Path):
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SessionSearchError(f"Index lock is already held: {lock_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_session_files(sessions_dir: Path) -> list[Path]:
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*.jsonl"))


def text_content(content: Any, role: str) -> str:
    parts: list[str] = []
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    for item in content:
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        if typ == "text":
            text = str(item.get("text", ""))
            if len(text) > MAX_FIELD_CHARS:
                text = text[:MAX_FIELD_CHARS] + "\n… truncated field …"
            parts.append(text)
        elif typ == "toolCall":
            name = item.get("name", "tool")
            arguments = item.get("arguments", {})
            try:
                arg_text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
            except TypeError:
                arg_text = str(arguments)
            if len(arg_text) > 1500:
                arg_text = arg_text[:1500] + "…"
            parts.append(f"[tool call: {name}] {arg_text}")
        elif role == "toolResult" and typ in {"json", "data"}:
            try:
                parts.append(json.dumps(item, ensure_ascii=False)[:MAX_FIELD_CHARS])
            except TypeError:
                pass
        # Deliberately skip assistant thinking / encrypted reasoning entries.
    return "\n".join(part for part in parts if part.strip())


def record_to_text(record: dict[str, Any], line_no: int) -> tuple[str, str | None, str | None, str | None]:
    typ = record.get("type")
    if typ == "session":
        session_id = str(record.get("id", "")) or None
        started_at = str(record.get("timestamp", "")) or None
        cwd = str(record.get("cwd", "")) or None
        return (f"[session] id={session_id or ''} cwd={cwd or ''} started_at={started_at or ''}", session_id, started_at, cwd)
    if typ == "model_change":
        provider = record.get("provider", "")
        model_id = record.get("modelId", "")
        timestamp = record.get("timestamp", "")
        return (f"[{timestamp}] model_change: {provider}/{model_id}", None, None, None)
    if typ == "thinking_level_change":
        timestamp = record.get("timestamp", "")
        level = record.get("thinkingLevel", "")
        return (f"[{timestamp}] thinking_level_change: {level}", None, None, None)
    if typ == "message":
        msg = record.get("message") if isinstance(record.get("message"), dict) else {}
        role = str(msg.get("role", "message"))
        timestamp = str(record.get("timestamp") or msg.get("timestamp") or "")
        body = text_content(msg.get("content"), role)
        tool_name = msg.get("toolName")
        if tool_name:
            role = f"{role}:{tool_name}"
        if not body.strip():
            return ("", None, None, None)
        return (f"[{timestamp}] {role}:\n{body}", None, None, None)
    if typ == "custom":
        timestamp = record.get("timestamp", "")
        custom_type = record.get("customType", "custom")
        data = record.get("data")
        summary = ""
        if isinstance(data, dict):
            if data.get("type") == "search" and data.get("queries"):
                summaries = []
                for q in data.get("queries", [])[:3]:
                    if isinstance(q, dict):
                        summaries.append(f"query={q.get('query', '')}\n{str(q.get('answer', ''))[:MAX_FIELD_CHARS]}")
                summary = "\n".join(summaries)
            elif "message" in data:
                summary = str(data.get("message"))
        if not summary:
            return ("", None, None, None)
        return (f"[{timestamp}] custom:{custom_type}\n{summary}", None, None, None)
    return ("", None, None, None)


def parse_session(path: Path) -> tuple[str | None, str | None, str | None, list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    session_id = started_at = cwd = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            text, sid, ts, this_cwd = record_to_text(record, line_no)
            session_id = sid or session_id
            started_at = ts or started_at
            cwd = this_cwd or cwd
            if text.strip():
                entries.append({"line": line_no, "text": text})
    return session_id, started_at, cwd, entries


def make_chunks(entries: list[dict[str, Any]], max_chars: int = MAX_CHARS_PER_CHUNK, overlap_chars: int = OVERLAP_CHARS) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        text = sanitize_text("\n\n".join(e["text"] for e in current).strip())
        if text:
            chunks.append(
                {
                    "text": text,
                    "start_line": current[0]["line"],
                    "end_line": current[-1]["line"],
                }
            )
        if overlap_chars <= 0:
            current = []
            current_len = 0
            return
        overlap: list[dict[str, Any]] = []
        total = 0
        for entry in reversed(current):
            entry_len = len(entry["text"]) + 2
            if overlap and total + entry_len > overlap_chars:
                break
            overlap.insert(0, entry)
            total += entry_len
        current = overlap
        current_len = total

    for entry in entries:
        entry_len = len(entry["text"]) + 2
        if current and current_len + entry_len > max_chars:
            flush()
            if current and current_len + entry_len > max_chars:
                # The overlap window can contain a large prior entry; drop it rather than
                # creating an oversized chunk for the embedding model.
                current = []
                current_len = 0
        if entry_len > max_chars:
            text = entry["text"]
            start = 0
            while start < len(text):
                part = sanitize_text(text[start : start + max_chars])
                chunks.append({"text": part, "start_line": entry["line"], "end_line": entry["line"]})
                if start + max_chars >= len(text):
                    break
                start += max_chars - min(overlap_chars, max_chars // 3)
            current = []
            current_len = 0
        else:
            current.append(entry)
            current_len += entry_len
    flush()
    return chunks


def openai_embed(texts: Sequence[str], *, kind: str) -> list[list[float]]:
    if not texts:
        return []
    prefixed = [(QUERY_PREFIX if kind == "query" else DOC_PREFIX) + sanitize_text(text) for text in texts]
    body: dict[str, Any] = {"model": embedding_model(), "input": list(prefixed)}
    dims = embedding_dimensions()
    if dims is not None:
        body["dimensions"] = dims
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("SESSION_SEARCH_EMBEDDING_API_KEY", "").strip() or os.environ.get("OMLX_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = env_int("SESSION_SEARCH_EMBEDDING_TIMEOUT_SECONDS", 300, minimum=1)
    retries = env_int("SESSION_SEARCH_EMBEDDING_RETRIES", 3, minimum=1)
    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            embedding_url(),
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600 and attempt < retries:
                last_error = exc
                time.sleep(min(2 * attempt, 10))
                continue
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise SessionSearchError(f"Embedding endpoint returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 * attempt, 10))
                continue
            raise SessionSearchError(f"Could not reach embedding endpoint {embedding_url()}: {exc.reason}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 * attempt, 10))
                continue
            raise SessionSearchError(f"Embedding endpoint timed out after {timeout}s") from exc
        except (http.client.IncompleteRead, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 * attempt, 10))
                continue
            raise SessionSearchError(f"Embedding endpoint returned an incomplete or invalid response after {retries} attempt(s): {exc}") from exc
    if payload is None:
        raise SessionSearchError(f"Embedding endpoint failed after {retries} attempt(s): {last_error}")

    data = payload.get("data")
    if not isinstance(data, list):
        raise SessionSearchError(f"Embedding response missing data list: {payload!r}")
    data = sorted(data, key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
    vectors: list[list[float]] = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise SessionSearchError(f"Malformed embedding item: {item!r}")
        vectors.append([float(x) for x in item["embedding"]])
    if len(vectors) != len(texts):
        raise SessionSearchError(f"Embedding endpoint returned {len(vectors)} vectors for {len(texts)} inputs")
    return vectors


def pack_vector(vector: Sequence[float]) -> tuple[bytes, float]:
    arr = array.array("f", (float(x) for x in vector))
    if sys.byteorder != "little":
        arr.byteswap()
    norm = math.sqrt(sum(float(x) * float(x) for x in arr))
    return arr.tobytes(), norm


def unpack_vector(blob: bytes) -> array.array:
    arr = array.array("f")
    arr.frombytes(blob)
    if sys.byteorder != "little":
        arr.byteswap()
    return arr


def cosine(query: Sequence[float], query_norm: float, vector_blob: bytes, vector_norm: float) -> float:
    if query_norm <= 0 or vector_norm <= 0:
        return 0.0
    vec = unpack_vector(vector_blob)
    if len(vec) != len(query):
        return -1.0
    dot = 0.0
    # A Python loop is fine for the current ~150-session corpus and avoids a native dependency.
    for a, b in zip(query, vec):
        dot += float(a) * float(b)
    return dot / (query_norm * vector_norm)


def needs_index(conn: sqlite3.Connection, path: Path) -> tuple[bool, os.stat_result, str | None]:
    stat = path.stat()
    row = conn.execute("SELECT mtime_ns, size, sha256 FROM sessions WHERE path = ?", (str(path),)).fetchone()
    if row is None:
        return True, stat, None
    if int(row["mtime_ns"]) != stat.st_mtime_ns or int(row["size"]) != stat.st_size:
        return True, stat, None
    return False, stat, str(row["sha256"])


def index_session(conn: sqlite3.Connection, path: Path, stat: os.stat_result, digest: str, batch_size: int) -> int:
    session_id, started_at, cwd, entries = parse_session(path)
    chunks = make_chunks(entries)

    # Embed before mutating the index so a transient model/server failure cannot leave a
    # session marked as indexed with missing vectors.
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors.extend(openai_embed([chunk["text"] for chunk in batch], kind="document"))

    now = utc_now()
    with conn:
        conn.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE session_path = ?)", (str(path),))
        conn.execute("DELETE FROM chunks WHERE session_path = ?", (str(path),))
        conn.execute(
            """
            INSERT INTO sessions(path, session_id, started_at, cwd, mtime_ns, size, sha256, indexed_at, chunk_count)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              session_id=excluded.session_id,
              started_at=excluded.started_at,
              cwd=excluded.cwd,
              mtime_ns=excluded.mtime_ns,
              size=excluded.size,
              sha256=excluded.sha256,
              indexed_at=excluded.indexed_at,
              chunk_count=excluded.chunk_count
            """,
            (str(path), session_id, started_at, cwd, stat.st_mtime_ns, stat.st_size, digest, now, len(chunks)),
        )
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            preview = " ".join(chunk["text"].split())[:500]
            cursor = conn.execute(
                "INSERT INTO chunks(session_path, chunk_index, start_line, end_line, started_at, text, preview) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (str(path), i, chunk["start_line"], chunk["end_line"], started_at, chunk["text"], preview),
            )
            blob, norm = pack_vector(vector)
            conn.execute(
                "INSERT OR REPLACE INTO embeddings(chunk_id, model, dimensions, norm, vector, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (cursor.lastrowid, embedding_model(), len(vector), norm, sqlite3.Binary(blob), utc_now()),
            )
    return len(chunks)


def command_index(args: argparse.Namespace) -> dict[str, Any]:
    sessions_dir = resolve_path(args.sessions_dir, resolve_path(os.environ.get("SESSION_SEARCH_SESSIONS_DIR"), DEFAULT_SESSIONS_DIR))
    db_path = resolve_path(args.db, resolve_path(os.environ.get("SESSION_SEARCH_DB_PATH"), DEFAULT_DB_PATH))
    batch_size = args.batch_size or env_int("SESSION_SEARCH_EMBEDDING_BATCH_SIZE", 4, minimum=1)
    max_files = args.max_files
    start_time = time.time()
    indexed: list[dict[str, Any]] = []
    skipped = 0
    removed = 0

    with index_lock(db_path), connect(db_path) as conn:
        files = iter_session_files(sessions_dir)
        existing = {row["path"] for row in conn.execute("SELECT path FROM sessions")}
        current = {str(path) for path in files}
        for stale in sorted(existing - current):
            with conn:
                conn.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE session_path = ?)", (stale,))
                conn.execute("DELETE FROM chunks WHERE session_path = ?", (stale,))
                conn.execute("DELETE FROM sessions WHERE path = ?", (stale,))
            removed += 1
        for path in files:
            needed, stat, old_digest = needs_index(conn, path)
            if not args.rebuild and not needed:
                skipped += 1
                continue
            digest = file_sha256(path)
            if not args.rebuild and old_digest == digest:
                # Metadata changed but content is identical; refresh mtime/size without re-embedding.
                with conn:
                    conn.execute(
                        "UPDATE sessions SET mtime_ns = ?, size = ?, indexed_at = ? WHERE path = ?",
                        (stat.st_mtime_ns, stat.st_size, utc_now(), str(path)),
                    )
                skipped += 1
                continue
            chunk_count = index_session(conn, path, stat, digest, batch_size)
            indexed.append({"path": str(path), "chunks": chunk_count})
            if max_files and len(indexed) >= max_files:
                break
    return {
        "ok": True,
        "indexed_files": len(indexed),
        "indexed_chunks": sum(item["chunks"] for item in indexed),
        "skipped_files": skipped,
        "removed_files": removed,
        "duration_seconds": round(time.time() - start_time, 2),
        "model": embedding_model(),
        "endpoint": embedding_url(),
        "indexed": indexed[:50],
    }


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    sessions_dir = resolve_path(args.sessions_dir, resolve_path(os.environ.get("SESSION_SEARCH_SESSIONS_DIR"), DEFAULT_SESSIONS_DIR))
    db_path = resolve_path(args.db, resolve_path(os.environ.get("SESSION_SEARCH_DB_PATH"), DEFAULT_DB_PATH))
    with connect(db_path) as conn:
        indexed_files = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        embeddings = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
        latest = conn.execute("SELECT path, indexed_at FROM sessions ORDER BY indexed_at DESC LIMIT 5").fetchall()
        files = iter_session_files(sessions_dir)
        indexed_paths = {row["path"] for row in conn.execute("SELECT path FROM sessions")}
        pending = [str(path) for path in files if str(path) not in indexed_paths]
        changed = []
        for path in files:
            row = conn.execute("SELECT mtime_ns, size FROM sessions WHERE path = ?", (str(path),)).fetchone()
            if row is None:
                continue
            stat = path.stat()
            if int(row["mtime_ns"]) != stat.st_mtime_ns or int(row["size"]) != stat.st_size:
                changed.append(str(path))
    return {
        "ok": True,
        "sessions_dir": str(sessions_dir),
        "db_path": str(db_path),
        "model": embedding_model(),
        "endpoint": embedding_url(),
        "indexed_files": indexed_files,
        "session_files": len(files),
        "pending_files": len(pending),
        "changed_files": len(changed),
        "chunks": chunks,
        "embeddings": embeddings,
        "latest": [dict(row) for row in latest],
        "pending_sample": pending[:10],
        "changed_sample": changed[:10],
    }


def command_search(args: argparse.Namespace) -> dict[str, Any]:
    if not args.query:
        raise SessionSearchError("search requires a query")
    db_path = resolve_path(args.db, resolve_path(os.environ.get("SESSION_SEARCH_DB_PATH"), DEFAULT_DB_PATH))
    limit = args.limit or 8
    query_vector = openai_embed([args.query], kind="query")[0]
    _blob, query_norm = pack_vector(query_vector)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.vector, e.norm, e.dimensions, e.model,
                   c.id AS chunk_id, c.session_path, c.chunk_index, c.start_line, c.end_line, c.text, c.preview,
                   s.session_id, s.started_at, s.cwd
            FROM embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            JOIN sessions s ON s.path = c.session_path
            WHERE e.model = ? AND e.dimensions = ?
            """,
            (embedding_model(), len(query_vector)),
        ).fetchall()
        scored = []
        for row in rows:
            score = cosine(query_vector, query_norm, row["vector"], float(row["norm"]))
            if score < -0.5:
                continue
            text = row["text"] if args.include_text else row["preview"]
            if not args.include_text and len(text) > args.snippet_chars:
                text = text[: args.snippet_chars] + "…"
            scored.append(
                {
                    "score": round(score, 4),
                    "chunk_id": row["chunk_id"],
                    "session_path": row["session_path"],
                    "session_file": Path(row["session_path"]).name,
                    "session_id": row["session_id"],
                    "started_at": row["started_at"],
                    "cwd": row["cwd"],
                    "chunk_index": row["chunk_index"],
                    "line_range": [row["start_line"], row["end_line"]],
                    "text": text,
                }
            )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "ok": True,
        "query": args.query,
        "model": embedding_model(),
        "dimensions": len(query_vector),
        "searched_chunks": len(rows),
        "results": scored[:limit],
    }


def install_cron_line() -> str:
    python = os.environ.get("SESSION_SEARCH_PYTHON", "").strip() or str(PROJECT_ROOT / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable
    script = Path(__file__).resolve()
    return f"0 5 * * * cd {PROJECT_ROOT} && {python} {script} index >> {DEFAULT_LOG_PATH} 2>&1"


def command_install_cron(_args: argparse.Namespace) -> dict[str, Any]:
    import subprocess

    marker_begin = "# BEGIN JARVIS PI SESSION SEARCH"
    marker_end = "# END JARVIS PI SESSION SEARCH"
    line = install_cron_line()
    try:
        current = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
        cron = current.stdout if current.returncode == 0 else ""
    except FileNotFoundError as exc:
        raise SessionSearchError("crontab command not found") from exc
    output_lines: list[str] = []
    skipping = False
    for raw in cron.splitlines():
        if raw.strip() == marker_begin:
            skipping = True
            continue
        if raw.strip() == marker_end:
            skipping = False
            continue
        if not skipping:
            output_lines.append(raw)
    if output_lines and output_lines[-1].strip():
        output_lines.append("")
    output_lines.extend([marker_begin, line, marker_end])
    new_cron = "\n".join(output_lines).rstrip() + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SessionSearchError(proc.stderr.strip() or "failed to install crontab")
    return {"ok": True, "message": "Installed daily 5am session search index cron", "cron_line": line}


def command_uninstall_cron(_args: argparse.Namespace) -> dict[str, Any]:
    import subprocess

    marker_begin = "# BEGIN JARVIS PI SESSION SEARCH"
    marker_end = "# END JARVIS PI SESSION SEARCH"
    current = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    cron = current.stdout if current.returncode == 0 else ""
    output_lines: list[str] = []
    skipping = False
    removed = False
    for raw in cron.splitlines():
        if raw.strip() == marker_begin:
            skipping = True
            removed = True
            continue
        if raw.strip() == marker_end:
            skipping = False
            continue
        if not skipping:
            output_lines.append(raw)
    new_cron = "\n".join(output_lines).rstrip() + ("\n" if output_lines else "")
    proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SessionSearchError(proc.stderr.strip() or "failed to update crontab")
    return {"ok": True, "removed": removed}


def emit(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if "message" in result:
        print(result["message"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index and search Pi session history with local embeddings")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--db", help="SQLite index path (default: .pi/session-search/index.sqlite)")
    parser.add_argument("--sessions-dir", help="Pi session JSONL directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="embed new or changed session files")
    p_index.add_argument("--rebuild", action="store_true", help="re-embed every session file")
    p_index.add_argument("--batch-size", type=int, help="embedding request batch size")
    p_index.add_argument("--max-files", type=int, help="index at most this many changed files")
    p_index.set_defaults(func=command_index)

    p_status = sub.add_parser("status", help="show index status without contacting the embedding server")
    p_status.set_defaults(func=command_status)

    p_search = sub.add_parser("search", help="search indexed sessions")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.add_argument("--snippet-chars", type=int, default=1200)
    p_search.add_argument("--include-text", action="store_true", help="return full matched chunk text")
    p_search.set_defaults(func=command_search)

    p_install = sub.add_parser("install-cron", help="install daily 5am indexing cron")
    p_install.set_defaults(func=command_install_cron)

    p_uninstall = sub.add_parser("uninstall-cron", help="remove daily indexing cron")
    p_uninstall.set_defaults(func=command_uninstall_cron)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        emit(result, args.json)
        return 0
    except SessionSearchError as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
