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
SCHEMA_VERSION = "2"
DOC_PREFIX = "Represent this coding-agent session chunk for retrieval: "
QUERY_PREFIX = "Represent this query for retrieving relevant coding-agent session history: "
MAX_CHARS_PER_CHUNK = 6500
OVERLAP_CHARS = 900
MAX_FIELD_CHARS = 5000
QUALITY_POLICIES = {"none", "hybrid", "strict"}
TOOL_CONTENT_TYPES = {"toolCall", "toolUse", "function_call"}
STRICT_PRODUCTIVE_TOOLS = {
    "edit",
    "write",
    "github_cli",
    "session_search",
    "memory",
    "memory_remember",
    "discord_cron",
    "code_search",
}
STRICT_MIN_USER_MESSAGES = 15
STRICT_MIN_TOTAL_TOKENS = 500_000
STRICT_MIN_TOTAL_COST = 1.0
DEFAULT_DELETE_MIN_AGE_MINUTES = 60


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


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise SessionSearchError(f"{name} must be a boolean, got {raw!r}")


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
        CREATE TABLE IF NOT EXISTS session_files (
            path TEXT PRIMARY KEY,
            session_id TEXT,
            started_at TEXT,
            cwd TEXT,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            user_messages INTEGER NOT NULL DEFAULT 0,
            assistant_messages INTEGER NOT NULL DEFAULT 0,
            tool_events INTEGER NOT NULL DEFAULT 0,
            tool_names TEXT NOT NULL DEFAULT '[]',
            error_messages INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0,
            quality_policy TEXT NOT NULL DEFAULT 'none',
            is_helpful INTEGER NOT NULL DEFAULT 1,
            quality_reason TEXT NOT NULL DEFAULT '',
            last_index_action TEXT NOT NULL DEFAULT '',
            analyzed_at TEXT NOT NULL,
            deleted_raw_at TEXT
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
        CREATE INDEX IF NOT EXISTS idx_session_files_helpful ON session_files(is_helpful, deleted_raw_at);
        CREATE INDEX IF NOT EXISTS idx_session_files_policy ON session_files(quality_policy);
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


def tool_name_from_content_item(item: dict[str, Any]) -> str | None:
    name = item.get("name") or item.get("toolName")
    function = item.get("function")
    if not name and isinstance(function, dict):
        name = function.get("name")
    return str(name) if name else None


def empty_session_analysis(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "session_id": None,
        "started_at": None,
        "cwd": None,
        "sha256": "",
        "user_messages": 0,
        "assistant_messages": 0,
        "tool_events": 0,
        "tool_names": set(),
        "error_messages": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
    }


def analyze_session_file(path: Path) -> dict[str, Any]:
    """Extract lightweight quality metadata and a sha256 in one pass."""
    analysis = empty_session_analysis(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for raw_bytes in handle:
            digest.update(raw_bytes)
            raw = raw_bytes.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            typ = record.get("type")
            if typ == "session":
                analysis["session_id"] = str(record.get("id", "")) or analysis["session_id"]
                analysis["started_at"] = str(record.get("timestamp", "")) or analysis["started_at"]
                analysis["cwd"] = str(record.get("cwd", "")) or analysis["cwd"]
                continue
            if typ != "message":
                continue
            msg = record.get("message") if isinstance(record.get("message"), dict) else {}
            role = msg.get("role")
            if role == "user":
                analysis["user_messages"] += 1
            elif role == "assistant":
                analysis["assistant_messages"] += 1
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                analysis["total_tokens"] += int(usage.get("totalTokens") or 0)
                cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
                try:
                    analysis["total_cost"] += float(cost.get("total") or 0)
                except (TypeError, ValueError):
                    pass
                if msg.get("stopReason") == "error":
                    analysis["error_messages"] += 1

            if role == "toolResult" or msg.get("toolName") or msg.get("toolCallId"):
                analysis["tool_events"] += 1
                tool_name = msg.get("toolName")
                if tool_name:
                    analysis["tool_names"].add(str(tool_name))

            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") in TOOL_CONTENT_TYPES:
                        analysis["tool_events"] += 1
                        tool_name = tool_name_from_content_item(item)
                        if tool_name:
                            analysis["tool_names"].add(tool_name)
    analysis["sha256"] = digest.hexdigest()
    return analysis


def normalize_quality_policy(raw: str | None) -> str:
    policy = (raw or os.environ.get("SESSION_SEARCH_QUALITY_POLICY") or "none").strip().lower()
    if policy not in QUALITY_POLICIES:
        raise SessionSearchError(f"quality policy must be one of {sorted(QUALITY_POLICIES)}, got {policy!r}")
    return policy


def evaluate_session_quality(analysis: dict[str, Any], policy: str) -> tuple[bool, str]:
    if policy == "none":
        return True, "policy:none"

    user_messages = int(analysis.get("user_messages") or 0)
    tool_events = int(analysis.get("tool_events") or 0)
    tool_names = set(analysis.get("tool_names") or [])
    total_tokens = int(analysis.get("total_tokens") or 0)
    total_cost = float(analysis.get("total_cost") or 0)

    if policy == "hybrid":
        if user_messages >= 3:
            return True, f"hybrid:user_messages>={user_messages}"
        if tool_events > 0:
            return True, f"hybrid:tool_events={tool_events}"
        return False, f"hybrid_pruned:user_messages={user_messages},tool_events={tool_events}"

    productive = sorted(tool_names & STRICT_PRODUCTIVE_TOOLS)
    if productive:
        return True, "strict:productive_tool=" + ",".join(productive[:5])
    if user_messages >= STRICT_MIN_USER_MESSAGES:
        return True, f"strict:user_messages={user_messages}"
    if total_tokens >= STRICT_MIN_TOTAL_TOKENS:
        return True, f"strict:total_tokens={total_tokens}"
    if total_cost >= STRICT_MIN_TOTAL_COST:
        return True, f"strict:total_cost={total_cost:.2f}"
    return (
        False,
        f"strict_pruned:user_messages={user_messages},tool_events={tool_events},total_tokens={total_tokens},total_cost={total_cost:.2f}",
    )


def upsert_session_file_metadata(
    conn: sqlite3.Connection,
    path: Path,
    stat: os.stat_result,
    analysis: dict[str, Any],
    *,
    policy: str,
    is_helpful: bool,
    quality_reason: str,
    last_index_action: str,
    deleted_raw_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO session_files(
          path, session_id, started_at, cwd, mtime_ns, size, sha256,
          user_messages, assistant_messages, tool_events, tool_names,
          error_messages, total_tokens, total_cost, quality_policy, is_helpful,
          quality_reason, last_index_action, analyzed_at, deleted_raw_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          session_id=excluded.session_id,
          started_at=excluded.started_at,
          cwd=excluded.cwd,
          mtime_ns=excluded.mtime_ns,
          size=excluded.size,
          sha256=excluded.sha256,
          user_messages=excluded.user_messages,
          assistant_messages=excluded.assistant_messages,
          tool_events=excluded.tool_events,
          tool_names=excluded.tool_names,
          error_messages=excluded.error_messages,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          quality_policy=excluded.quality_policy,
          is_helpful=excluded.is_helpful,
          quality_reason=excluded.quality_reason,
          last_index_action=excluded.last_index_action,
          analyzed_at=excluded.analyzed_at,
          deleted_raw_at=excluded.deleted_raw_at
        """,
        (
            str(path),
            analysis.get("session_id"),
            analysis.get("started_at"),
            analysis.get("cwd"),
            stat.st_mtime_ns,
            stat.st_size,
            str(analysis.get("sha256") or ""),
            int(analysis.get("user_messages") or 0),
            int(analysis.get("assistant_messages") or 0),
            int(analysis.get("tool_events") or 0),
            json.dumps(sorted(analysis.get("tool_names") or []), ensure_ascii=False),
            int(analysis.get("error_messages") or 0),
            int(analysis.get("total_tokens") or 0),
            float(analysis.get("total_cost") or 0),
            policy,
            1 if is_helpful else 0,
            quality_reason,
            last_index_action,
            utc_now(),
            deleted_raw_at,
        ),
    )


def remove_indexed_session(conn: sqlite3.Connection, session_path: str) -> tuple[bool, int]:
    row = conn.execute("SELECT chunk_count FROM sessions WHERE path = ?", (session_path,)).fetchone()
    indexed = row is not None
    chunk_count = int(row["chunk_count"] or 0) if row else 0
    conn.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE session_path = ?)", (session_path,))
    conn.execute("DELETE FROM chunks WHERE session_path = ?", (session_path,))
    conn.execute("DELETE FROM sessions WHERE path = ?", (session_path,))
    return indexed, chunk_count


def deletion_manifest_path(db_path: Path) -> Path:
    stamp = utc_now().replace(":", "").replace("-", "").replace("Z", "Z")
    return db_path.parent / f"deleted-sessions-{stamp}.json"


def write_deletion_manifest(db_path: Path, payload: dict[str, Any]) -> str:
    manifest_path = deletion_manifest_path(db_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(manifest_path)


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
    quality_policy = normalize_quality_policy(getattr(args, "quality_policy", None))
    delete_pruned = bool(getattr(args, "delete_pruned", False)) or env_bool("SESSION_SEARCH_DELETE_PRUNED", False)
    min_age_minutes = getattr(args, "min_age_minutes", None)
    if min_age_minutes is None:
        min_age_minutes = env_int("SESSION_SEARCH_DELETE_MIN_AGE_MINUTES", DEFAULT_DELETE_MIN_AGE_MINUTES, minimum=0)
    if delete_pruned and quality_policy == "none":
        raise SessionSearchError("--delete-pruned requires --quality-policy hybrid or strict")

    start_time = time.time()
    indexed: list[dict[str, Any]] = []
    deleted_entries: list[dict[str, Any]] = []
    deferred_entries: list[dict[str, Any]] = []
    pruned_entries: list[dict[str, Any]] = []
    skipped = 0
    removed = 0
    scanned = 0
    quality_kept = 0
    quality_pruned = 0
    pruned_index_files = 0
    pruned_index_chunks = 0

    with index_lock(db_path), connect(db_path) as conn:
        files = iter_session_files(sessions_dir)
        existing = {row["path"] for row in conn.execute("SELECT path FROM sessions")}
        current = {str(path) for path in files}
        for stale in sorted(existing - current):
            with conn:
                removed_indexed, _chunk_count = remove_indexed_session(conn, stale)
            if removed_indexed:
                removed += 1
        for path in files:
            scanned += 1
            digest: str | None = None
            if quality_policy != "none":
                stat = path.stat()
                analysis = analyze_session_file(path)
                digest = str(analysis.get("sha256") or "")
                is_helpful, quality_reason = evaluate_session_quality(analysis, quality_policy)
                if is_helpful:
                    quality_kept += 1
                    with conn:
                        upsert_session_file_metadata(
                            conn,
                            path,
                            stat,
                            analysis,
                            policy=quality_policy,
                            is_helpful=True,
                            quality_reason=quality_reason,
                            last_index_action="kept",
                            deleted_raw_at=None,
                        )
                else:
                    quality_pruned += 1
                    entry = {
                        "path": str(path),
                        "reason": quality_reason,
                        "user_messages": int(analysis.get("user_messages") or 0),
                        "tool_events": int(analysis.get("tool_events") or 0),
                        "tool_names": sorted(analysis.get("tool_names") or []),
                        "total_tokens": int(analysis.get("total_tokens") or 0),
                        "total_cost": round(float(analysis.get("total_cost") or 0), 6),
                        "size": stat.st_size,
                    }
                    with conn:
                        removed_indexed, chunk_count = remove_indexed_session(conn, str(path))
                        if removed_indexed:
                            pruned_index_files += 1
                            pruned_index_chunks += chunk_count
                        upsert_session_file_metadata(
                            conn,
                            path,
                            stat,
                            analysis,
                            policy=quality_policy,
                            is_helpful=False,
                            quality_reason=quality_reason,
                            last_index_action="pruned_pending_delete" if delete_pruned else "pruned_index_only",
                            deleted_raw_at=None,
                        )
                    pruned_entries.append(entry)
                    if delete_pruned:
                        age_seconds = max(0.0, start_time - stat.st_mtime)
                        if age_seconds >= float(min_age_minutes) * 60:
                            try:
                                path.unlink()
                            except OSError as exc:
                                raise SessionSearchError(f"Failed to delete pruned session {path}: {exc}") from exc
                            deleted_at = utc_now()
                            entry["deleted_raw_at"] = deleted_at
                            deleted_entries.append(entry)
                            with conn:
                                upsert_session_file_metadata(
                                    conn,
                                    path,
                                    stat,
                                    analysis,
                                    policy=quality_policy,
                                    is_helpful=False,
                                    quality_reason=quality_reason,
                                    last_index_action="deleted_pruned",
                                    deleted_raw_at=deleted_at,
                                )
                        else:
                            entry["deferred_reason"] = f"modified within {min_age_minutes} minute safety window"
                            deferred_entries.append(entry)
                    continue

            needed, stat, old_digest = needs_index(conn, path)
            if not args.rebuild and not needed:
                skipped += 1
                continue
            if digest is None:
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

    manifest_path = None
    if deleted_entries:
        manifest_path = write_deletion_manifest(
            db_path,
            {
                "created_at": utc_now(),
                "quality_policy": quality_policy,
                "delete_pruned": delete_pruned,
                "min_age_minutes": min_age_minutes,
                "deleted_files": deleted_entries,
                "deferred_files": deferred_entries,
                "pruned_files": pruned_entries,
            },
        )

    return {
        "ok": True,
        "indexed_files": len(indexed),
        "indexed_chunks": sum(item["chunks"] for item in indexed),
        "skipped_files": skipped,
        "removed_files": removed,
        "duration_seconds": round(time.time() - start_time, 2),
        "model": embedding_model(),
        "endpoint": embedding_url(),
        "quality_policy": quality_policy,
        "delete_pruned": delete_pruned,
        "min_age_minutes": min_age_minutes,
        "scanned_files": scanned,
        "quality_kept_files": quality_kept if quality_policy != "none" else None,
        "quality_pruned_files": quality_pruned if quality_policy != "none" else None,
        "deleted_pruned_files": len(deleted_entries),
        "deferred_pruned_files": len(deferred_entries),
        "pruned_index_files": pruned_index_files,
        "pruned_index_chunks": pruned_index_chunks,
        "delete_manifest": manifest_path,
        "indexed": indexed[:50],
    }


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    sessions_dir = resolve_path(args.sessions_dir, resolve_path(os.environ.get("SESSION_SEARCH_SESSIONS_DIR"), DEFAULT_SESSIONS_DIR))
    db_path = resolve_path(args.db, resolve_path(os.environ.get("SESSION_SEARCH_DB_PATH"), DEFAULT_DB_PATH))
    with connect(db_path) as conn:
        indexed_files = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        embeddings = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
        quality_total = conn.execute("SELECT COUNT(*) AS n FROM session_files").fetchone()["n"]
        quality_helpful = conn.execute("SELECT COUNT(*) AS n FROM session_files WHERE is_helpful = 1 AND deleted_raw_at IS NULL").fetchone()["n"]
        quality_pruned = conn.execute("SELECT COUNT(*) AS n FROM session_files WHERE is_helpful = 0 AND deleted_raw_at IS NULL").fetchone()["n"]
        quality_deleted = conn.execute("SELECT COUNT(*) AS n FROM session_files WHERE deleted_raw_at IS NOT NULL").fetchone()["n"]
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
        "quality_metadata_files": quality_total,
        "quality_helpful_files": quality_helpful,
        "quality_pruned_files": quality_pruned,
        "quality_deleted_files": quality_deleted,
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
    index_args = os.environ.get(
        "SESSION_SEARCH_CRON_INDEX_ARGS",
        "index --quality-policy strict --delete-pruned --min-age-minutes 60",
    ).strip()
    return f"0 5 * * * cd {PROJECT_ROOT} && {python} {script} {index_args} >> {DEFAULT_LOG_PATH} 2>&1"


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
    return {"ok": True, "message": "Installed daily 5am session search index cron with strict pruning", "cron_line": line}


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
    p_index.add_argument(
        "--quality-policy",
        choices=sorted(QUALITY_POLICIES),
        default=None,
        help="optional quality filter before indexing: none, hybrid, or strict",
    )
    p_index.add_argument("--delete-pruned", action="store_true", help="delete raw session files rejected by the quality policy")
    p_index.add_argument(
        "--min-age-minutes",
        type=int,
        default=None,
        help="minimum file age before deleting pruned raw sessions; default 60",
    )
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
