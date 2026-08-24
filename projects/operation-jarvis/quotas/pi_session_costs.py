#!/usr/bin/env python3
"""Summarize Pi agent session costs from JSONL logs.

Pi session logs store per-response usage/reference-cost data on assistant
messages, e.g. `message.usage.cost.total`. This script sums those logged values
without re-pricing tokens. They are model-price estimates, not invoices or
subscription charges. A GitHub AI Credits equivalent is reported only for
GitHub Copilot records, at 1 credit = $0.01 USD. Local providers such as
`omlx`, `omlx-64`, and `omlx-voice` are excluded from the non-local reference
cost by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python always has zoneinfo here.
    ZoneInfo = None  # type: ignore[assignment]

DEFAULT_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"
DEFAULT_LOCAL_PROVIDERS = {
    "local",
    "llama.cpp",
    "llamacpp",
    "lmstudio",
    "mlx",
    "ollama",
    "omlx",
    "omlx-64",
    "omlx-voice",
}
DEFAULT_LOCAL_MODEL_HINTS = (
    "mlx-community/",
    "gguf",
)
AI_CREDIT_VALUE_USD = 0.01


def usd_to_ai_credits(value: float) -> float:
    return value / AI_CREDIT_VALUE_USD


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    raw_logged_cost: float = 0.0
    nonlocal_reference_cost: float = 0.0
    ignored_local_cost: float = 0.0
    copilot_reference_cost: float = 0.0
    usage_records: int = 0

    def add(self, other: "UsageTotals") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.total_tokens += other.total_tokens
        self.raw_logged_cost += other.raw_logged_cost
        self.nonlocal_reference_cost += other.nonlocal_reference_cost
        self.ignored_local_cost += other.ignored_local_cost
        self.copilot_reference_cost += other.copilot_reference_cost
        self.usage_records += other.usage_records


@dataclass
class SessionCost:
    path: str
    session_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    cwd: str = ""
    providers: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    user_turns: int = 0
    assistant_messages: int = 0
    totals: UsageTotals = field(default_factory=UsageTotals)
    provider_model_totals: dict[tuple[str, str], UsageTotals] = field(default_factory=lambda: defaultdict(UsageTotals))
    local_usage_records: int = 0
    parse_errors: int = 0

    @property
    def primary_provider(self) -> str:
        return self.providers.most_common(1)[0][0] if self.providers else ""

    @property
    def primary_model(self) -> str:
        return self.models.most_common(1)[0][0] if self.models else ""


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_time(value: str, tz_name: str) -> str:
    dt = parse_iso_datetime(value)
    if not dt or not ZoneInfo:
        return value
    return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def cost_total(cost_obj: Any) -> float:
    """Return the logged cost total from a Pi usage.cost object.

    Prefer `total` when present.  If an older log only has component costs, sum
    those components.  Missing cost means zero; this script intentionally does
    not estimate prices from tokens.
    """
    if not isinstance(cost_obj, dict):
        return 0.0
    if "total" in cost_obj:
        return numeric(cost_obj.get("total"))
    return sum(
        numeric(cost_obj.get(key))
        for key in ("input", "output", "cacheRead", "cacheWrite")
    )


def is_local_usage(
    provider: str,
    model: str,
    local_providers: set[str],
    local_model_hints: tuple[str, ...],
) -> bool:
    provider_l = (provider or "").lower()
    model_l = (model or "").lower()
    if provider_l in local_providers or provider_l.startswith("omlx-"):
        return True
    return any(hint.lower() in model_l for hint in local_model_hints)


def usage_totals_from_message(
    usage: dict[str, Any],
    *,
    provider: str,
    is_local: bool,
    include_local_cost: bool,
) -> UsageTotals:
    totals = UsageTotals()
    totals.input_tokens = integer(usage.get("input"))
    totals.output_tokens = integer(usage.get("output"))
    totals.cache_read_tokens = integer(usage.get("cacheRead"))
    totals.cache_write_tokens = integer(usage.get("cacheWrite"))
    totals.total_tokens = integer(usage.get("totalTokens") or usage.get("total"))
    totals.raw_logged_cost = cost_total(usage.get("cost"))
    totals.usage_records = 1

    if is_local and not include_local_cost:
        totals.nonlocal_reference_cost = 0.0
        totals.ignored_local_cost = totals.raw_logged_cost
    else:
        totals.nonlocal_reference_cost = totals.raw_logged_cost
    if provider.lower() == "github-copilot":
        totals.copilot_reference_cost = totals.raw_logged_cost
    return totals


def iter_session_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        if expanded.is_file() and expanded.suffix == ".jsonl":
            files.append(expanded)
        elif expanded.is_dir():
            files.extend(expanded.rglob("*.jsonl"))
        else:
            print(f"warning: skipping missing/non-jsonl path: {path}", file=sys.stderr)
    return sorted(set(files))


def parse_session_file(
    path: Path,
    *,
    include_local_cost: bool,
    local_providers: set[str],
    local_model_hints: tuple[str, ...],
) -> SessionCost:
    session = SessionCost(path=str(path))
    current_provider = ""
    current_model = ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                session.parse_errors += 1
                continue

            timestamp = event.get("timestamp") or ""
            if timestamp:
                session.ended_at = timestamp

            event_type = event.get("type")
            if event_type == "session":
                session.session_id = str(event.get("id") or session.session_id)
                session.started_at = str(event.get("timestamp") or session.started_at)
                session.cwd = str(event.get("cwd") or session.cwd)
                continue

            if event_type == "model_change":
                current_provider = str(event.get("provider") or current_provider)
                current_model = str(event.get("modelId") or current_model)
                if current_provider:
                    session.providers[current_provider] += 1
                if current_model:
                    session.models[current_model] += 1
                continue

            if event_type != "message":
                continue

            message = event.get("message") or {}
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            if role == "user":
                session.user_turns += 1
                continue
            if role != "assistant":
                continue

            session.assistant_messages += 1
            provider = str(message.get("provider") or current_provider or "unknown")
            model = str(message.get("model") or current_model or "unknown")
            session.providers[provider] += 1
            session.models[model] += 1

            usage = message.get("usage") or {}
            if not isinstance(usage, dict) or not usage:
                continue

            local = is_local_usage(provider, model, local_providers, local_model_hints)
            if local:
                session.local_usage_records += 1
            message_totals = usage_totals_from_message(
                usage,
                provider=provider,
                is_local=local,
                include_local_cost=include_local_cost,
            )
            session.totals.add(message_totals)
            session.provider_model_totals[(provider, model)].add(message_totals)

    if not session.session_id:
        session.session_id = path.stem.split("_")[-1]
    if not session.started_at:
        session.started_at = path.name.split("_")[0]
    return session


def session_to_row(session: SessionCost, tz: str) -> dict[str, Any]:
    totals = session.totals
    return {
        "started_at": format_time(session.started_at, tz),
        "ended_at": format_time(session.ended_at, tz),
        "session_id": session.session_id,
        "cwd": session.cwd,
        "provider": session.primary_provider,
        "model": session.primary_model,
        "user_turns": session.user_turns,
        "assistant_messages": session.assistant_messages,
        "usage_records": totals.usage_records,
        "local_usage_records": session.local_usage_records,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cache_read_tokens": totals.cache_read_tokens,
        "cache_write_tokens": totals.cache_write_tokens,
        "total_tokens": totals.total_tokens,
        "raw_logged_reference_cost_usd": round(totals.raw_logged_cost, 8),
        "nonlocal_reference_cost_usd": round(totals.nonlocal_reference_cost, 8),
        "ignored_local_reference_cost_usd": round(totals.ignored_local_cost, 8),
        "copilot_reference_cost_usd": round(totals.copilot_reference_cost, 8),
        "estimated_copilot_ai_credits": round(usd_to_ai_credits(totals.copilot_reference_cost), 4),
        "parse_errors": session.parse_errors,
        "path": session.path,
    }


def print_summary(
    sessions: list[SessionCost],
    *,
    tz: str,
    show_sessions: bool,
    limit: int,
    sort_by: str,
) -> None:
    grand = UsageTotals()
    by_provider_model: dict[tuple[str, str], UsageTotals] = defaultdict(UsageTotals)
    local_usage_records = 0
    for session in sessions:
        grand.add(session.totals)
        local_usage_records += session.local_usage_records
        for provider_model, totals in session.provider_model_totals.items():
            by_provider_model[provider_model].add(totals)

    print(f"Sessions scanned: {len(sessions)}")
    print(f"Usage records:    {grand.usage_records}")
    print(f"Local records:    {local_usage_records}")
    print(f"Non-local reference cost: ${grand.nonlocal_reference_cost:.6f} USD")
    print(f"Raw logged reference:     ${grand.raw_logged_cost:.6f} USD")
    print(f"Ignored local reference:  ${grand.ignored_local_cost:.6f} USD")
    print(
        f"Copilot reference cost:   ${grand.copilot_reference_cost:.6f} USD "
        f"(~{usd_to_ai_credits(grand.copilot_reference_cost):.2f} AI credits)"
    )
    print("Note: logged reference costs are estimates, not actual invoices or subscription charges.")
    print(f"Total tokens:     {grand.total_tokens:,}")
    print()

    print("Reference cost by provider/model:")
    print(f"{'non-local':>12} {'raw':>12} {'usage':>8} {'tokens':>14}  provider / model")
    for (provider, model), totals in sorted(
        by_provider_model.items(), key=lambda item: item[1].nonlocal_reference_cost, reverse=True
    ):
        print(
            f"${totals.nonlocal_reference_cost:>11.6f} "
            f"${totals.raw_logged_cost:>11.6f} "
            f"{totals.usage_records:>8} "
            f"{totals.total_tokens:>14,}  "
            f"{provider} / {model}"
        )

    if not show_sessions:
        return

    print()
    print("Sessions:")
    rows = [session_to_row(session, tz) for session in sessions]
    if sort_by == "cost":
        rows.sort(key=lambda row: row["nonlocal_reference_cost_usd"], reverse=True)
    elif sort_by == "tokens":
        rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    else:
        rows.sort(key=lambda row: row["started_at"])

    if limit > 0:
        rows = rows[:limit]

    print(f"{'non-local':>12} {'raw':>12} {'turns':>5} {'tokens':>12} {'started':<23}  session / model")
    for row in rows:
        print(
            f"${row['nonlocal_reference_cost_usd']:>11.6f} "
            f"${row['raw_logged_reference_cost_usd']:>11.6f} "
            f"{row['user_turns']:>5} "
            f"{row['total_tokens']:>12,} "
            f"{row['started_at']:<23}  "
            f"{row['session_id']} / {row['model']}"
        )


def write_csv(path: Path, sessions: list[SessionCost], tz: str) -> None:
    rows = [session_to_row(session, tz) for session in sessions]
    fieldnames = list(rows[0].keys()) if rows else list(session_to_row(SessionCost(path=""), tz).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[DEFAULT_SESSIONS_DIR],
        help=f"session .jsonl files or directories to scan (default: {DEFAULT_SESSIONS_DIR})",
    )
    parser.add_argument(
        "--cwd",
        help="only include sessions whose session cwd exactly matches this path",
    )
    parser.add_argument(
        "--include-local-cost",
        action="store_true",
        help="include logged reference cost from local providers in the non-local total",
    )
    parser.add_argument(
        "--local-provider",
        action="append",
        default=[],
        help="provider name to treat as local/reference-cost-free; can be repeated",
    )
    parser.add_argument(
        "--local-model-hint",
        action="append",
        default=[],
        help="model-name substring to treat as local/reference-cost-free; can be repeated",
    )
    parser.add_argument(
        "--sessions",
        action="store_true",
        help="also print per-session rows",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="max per-session rows to print when --sessions is used; 0 means all",
    )
    parser.add_argument(
        "--sort",
        choices=("cost", "started", "tokens"),
        default="cost",
        help="per-session sort order when --sessions is used",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="write per-session CSV to this path",
    )
    parser.add_argument(
        "--tz",
        default="America/Toronto",
        help="timezone for displayed timestamps (default: America/Toronto)",
    )
    args = parser.parse_args()

    local_providers = {provider.lower() for provider in DEFAULT_LOCAL_PROVIDERS}
    local_providers.update(provider.lower() for provider in args.local_provider)
    local_model_hints = tuple(DEFAULT_LOCAL_MODEL_HINTS + tuple(args.local_model_hint))

    files = iter_session_files(args.paths)
    sessions = [
        parse_session_file(
            path,
            include_local_cost=args.include_local_cost,
            local_providers=local_providers,
            local_model_hints=local_model_hints,
        )
        for path in files
    ]
    if args.cwd:
        sessions = [session for session in sessions if session.cwd == args.cwd]

    sessions = [session for session in sessions if session.totals.usage_records > 0]

    if args.csv:
        write_csv(args.csv, sessions, args.tz)

    if args.format == "json":
        grand = UsageTotals()
        for session in sessions:
            grand.add(session.totals)
        print(
            json.dumps(
                {
                    "sessions_scanned": len(sessions),
                    "usage_records": grand.usage_records,
                    "raw_logged_reference_cost_usd": grand.raw_logged_cost,
                    "nonlocal_reference_cost_usd": grand.nonlocal_reference_cost,
                    "ignored_local_reference_cost_usd": grand.ignored_local_cost,
                    "copilot_reference_cost_usd": grand.copilot_reference_cost,
                    "estimated_copilot_ai_credits": usd_to_ai_credits(grand.copilot_reference_cost),
                    "ai_credit_value_usd": AI_CREDIT_VALUE_USD,
                    "cost_note": "Logged reference costs are estimates, not actual invoices or subscription charges.",
                    "total_tokens": grand.total_tokens,
                    "sessions": [session_to_row(session, args.tz) for session in sessions],
                },
                indent=2,
            )
        )
    else:
        print_summary(
            sessions,
            tz=args.tz,
            show_sessions=args.sessions,
            limit=args.limit,
            sort_by=args.sort,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
