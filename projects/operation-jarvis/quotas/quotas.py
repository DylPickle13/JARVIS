#!/usr/bin/env python3
"""
Subscription quota and model availability checks for OpenAI Codex and GitHub Copilot.

Uses the same OAuth credentials Pi stores in ~/.pi/agent/auth.json. The checks are
read-only by default: they fetch usage/quota and model catalogs without sending a
model prompt. Explicit --probe checks may consume quota.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python <3.9 fallback, kept for portability.
    ZoneInfo = None  # type: ignore


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_AUTH_PATH = Path(os.environ.get("PI_AUTH_PATH", "~/.pi/agent/auth.json")).expanduser()
DEFAULT_DATA_DIR = PROJECT_DIR / "data"
DEFAULT_TIMEOUT = 30
DEFAULT_TZ = os.environ.get("QUOTAS_TZ", "America/New_York")
DEFAULT_CODEX_CLIENT_VERSION = os.environ.get("CODEX_CLIENT_VERSION", "1.0.0")
# OpenAI temporarily removed the rolling five-hour enforcement for Plus, Pro,
# and Business on 2026-07-12. The usage endpoint still returns/tracks that
# window, so keep the operational status separate from the raw counter. Set
# this to `active` when OpenAI restores enforcement without changing the API.
CODEX_5H_LIMIT_STATUS = os.environ.get(
    "QUOTAS_CODEX_5H_LIMIT_STATUS", "temporarily_suspended"
).strip().lower()
CODEX_5H_LIMIT_SUSPENDED_ON = "2026-07-12"
CODEX_5H_LIMIT_SUSPENSION_SOURCE = "https://x.com/thsottiaux/status/2076365965915467978"

OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
OPENAI_CODEX_RESET_CREDITS_URL = f"{OPENAI_CODEX_BASE_URL}/wham/rate-limit-reset-credits"
OPENAI_JWT_AUTH_CLAIM = "https://api.openai.com/auth"

COPILOT_IDE_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}

GITHUB_API_BASE_URL = os.environ.get("QUOTAS_GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/")
GITHUB_API_VERSION = os.environ.get("QUOTAS_GITHUB_API_VERSION", "2026-03-10")
COPILOT_MODELS_API_VERSION = os.environ.get("QUOTAS_COPILOT_MODELS_API_VERSION", "2026-06-01")
COPILOT_BILLING_TOKEN_ENV = "QUOTAS_GITHUB_BILLING_TOKEN"
COPILOT_AI_CREDIT_VALUE_USD = 0.01
COPILOT_USAGE_BASED_BILLING_STARTED = dt.date(2026, 6, 1)
COPILOT_BUSINESS_ENTERPRISE_PROMO_END = dt.date(2026, 9, 1)
COPILOT_USAGE_BASED_BILLING_DOCS = "https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals"
COPILOT_USAGE_BASED_BILLING_ORG_DOCS = "https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-organizations-and-enterprises"
COPILOT_BILLING_USAGE_API_DOCS = "https://docs.github.com/en/rest/billing/usage?apiVersion=2026-03-10"

COPILOT_PLAN_ALLOWANCES: Dict[str, Dict[str, Any]] = {
    "pro": {
        "label": "Copilot Pro",
        "scope": "individual",
        "price_usd": 10,
        "base_credits": 1000.0,
        "flex_credits": 500.0,
        "total_credits": 1500.0,
        "source": COPILOT_USAGE_BASED_BILLING_DOCS,
    },
    "pro_plus": {
        "label": "Copilot Pro+",
        "scope": "individual",
        "price_usd": 39,
        "base_credits": 3900.0,
        "flex_credits": 3100.0,
        "total_credits": 7000.0,
        "source": COPILOT_USAGE_BASED_BILLING_DOCS,
    },
    "max": {
        "label": "Copilot Max",
        "scope": "individual",
        "price_usd": 100,
        "base_credits": 10000.0,
        "flex_credits": 10000.0,
        "total_credits": 20000.0,
        "source": COPILOT_USAGE_BASED_BILLING_DOCS,
    },
    "business": {
        "label": "Copilot Business",
        "scope": "organization",
        "total_credits_per_user": 1900.0,
        "promotional_total_credits_per_user": 3000.0,
        "promotional_through": COPILOT_BUSINESS_ENTERPRISE_PROMO_END.isoformat(),
        "pooled": True,
        "source": COPILOT_USAGE_BASED_BILLING_ORG_DOCS,
    },
    "enterprise": {
        "label": "Copilot Enterprise",
        "scope": "enterprise",
        "total_credits_per_user": 3900.0,
        "promotional_total_credits_per_user": 7000.0,
        "promotional_through": COPILOT_BUSINESS_ENTERPRISE_PROMO_END.isoformat(),
        "pooled": True,
        "source": COPILOT_USAGE_BASED_BILLING_ORG_DOCS,
    },
    "free": {
        "label": "Copilot Free",
        "scope": "individual",
        "total_credits": None,
        "source": COPILOT_USAGE_BASED_BILLING_DOCS,
        "note": "GitHub documents that Free includes an AI Credits allowance but does not publish a fixed amount in the plan table.",
    },
    "student": {
        "label": "Copilot Student/Education",
        "scope": "individual",
        "total_credits": None,
        "source": COPILOT_USAGE_BASED_BILLING_DOCS,
        "note": "GitHub documents that Student/Education includes an AI Credits allowance but does not publish a fixed amount in the plan table.",
    },
}


class QuotaError(RuntimeError):
    """Expected runtime failure for quota checks."""


class HttpRequestError(QuotaError):
    def __init__(self, method: str, url: str, status: int, body: str):
        clean_body = body.strip().replace("\n", " ")[:1000]
        super().__init__(f"HTTP {status} from {method} {url}: {clean_body}")
        self.method = method
        self.url = url
        self.status = status
        self.body = body


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat().replace("+00:00", "Z")


def get_tz(name: str):
    if ZoneInfo is None:
        return dt.timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return dt.timezone.utc


def format_epoch(seconds: Optional[float], tz_name: str = DEFAULT_TZ) -> Optional[str]:
    if seconds in (None, 0):
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    tz = get_tz(tz_name)
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_iso_datetime(value: Any, tz_name: str = DEFAULT_TZ) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(get_tz(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_int(value: Any) -> Optional[int]:
    number = coerce_float(value)
    if number is None:
        return None
    return int(number)


def clamp_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, min(100.0, value))


def identifier_preview(value: Any, keep: int = 24) -> Any:
    if not isinstance(value, str) or len(value) <= keep:
        return value
    return f"{value[:keep]}…"


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part.encode()).decode())
    except Exception as exc:
        raise QuotaError(f"Could not decode JWT payload: {exc}") from exc


def codex_account_id_from_token(token: str) -> Optional[str]:
    try:
        payload = decode_jwt_payload(token)
    except QuotaError:
        return None
    auth = payload.get(OPENAI_JWT_AUTH_CLAIM) or {}
    account_id = auth.get("chatgpt_account_id")
    return account_id if isinstance(account_id, str) and account_id else None


def request_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    body: Any = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Tuple[Any, Dict[str, str]]:
    data: Optional[bytes] = None
    merged_headers = dict(headers or {})
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=merged_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            payload = json.loads(raw) if raw.strip() else {}
            return payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise HttpRequestError(method.upper(), url, exc.code, raw) from exc
    except urllib.error.URLError as exc:
        raise QuotaError(f"Network error from {method.upper()} {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise QuotaError(f"Invalid JSON from {method.upper()} {url}: {exc}") from exc


def request_form(method: str, url: str, *, headers: Dict[str, str], fields: Dict[str, str]) -> Tuple[Any, Dict[str, str]]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    merged = dict(headers)
    merged.setdefault("Content-Type", "application/x-www-form-urlencoded")
    return request_json(method, url, headers=merged, body=body)


@contextlib.contextmanager
def auth_file_lock(auth_path: Path, timeout: float = 30.0, stale_after: float = 60.0):
    """Cooperate with Pi/proper-lockfile's auth.json.lock directory."""

    lock_path = Path(str(auth_path) + ".lock")
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            os.mkdir(lock_path)
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_after:
                shutil.rmtree(lock_path, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise QuotaError(f"Timed out waiting for auth lock: {lock_path}")
            time.sleep(0.1)
    try:
        yield
    finally:
        if acquired:
            shutil.rmtree(lock_path, ignore_errors=True)


class AuthStore:
    def __init__(self, path: Path):
        self.path = path.expanduser()

    def load_unlocked(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise QuotaError(f"Auth file not found: {self.path}. Run `pi /login` for the provider first.")
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise QuotaError(f"Auth file is not valid JSON: {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise QuotaError(f"Auth file has unexpected shape: {self.path}")
        return data

    def save_unlocked(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)

    def get_provider(self, provider: str) -> Dict[str, Any]:
        data = self.load_unlocked()
        cred = data.get(provider)
        if not isinstance(cred, dict):
            raise QuotaError(f"No `{provider}` credentials found in {self.path}. Run `pi /login {provider}` first.")
        return cred

    def ensure_codex(self, refresh: bool = True) -> Dict[str, Any]:
        with auth_file_lock(self.path):
            data = self.load_unlocked()
            cred = data.get("openai-codex")
            if not isinstance(cred, dict):
                raise QuotaError("No `openai-codex` credentials found. Run `pi /login openai-codex` first.")
            if cred.get("type") != "oauth":
                raise QuotaError("`openai-codex` credential is not an OAuth credential.")
            access = cred.get("access")
            refresh_token = cred.get("refresh")
            expires_ms = coerce_float(cred.get("expires")) or 0
            if not isinstance(access, str) or not access:
                raise QuotaError("`openai-codex` access token is missing.")
            if refresh and time.time() * 1000 >= expires_ms - 60_000:
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise QuotaError("`openai-codex` refresh token is missing; re-login with Pi.")
                refreshed = refresh_openai_codex(refresh_token)
                cred = {"type": "oauth", **refreshed}
                data["openai-codex"] = cred
                self.save_unlocked(data)
            elif not cred.get("accountId"):
                account_id = codex_account_id_from_token(access)
                if account_id:
                    cred["accountId"] = account_id
                    data["openai-codex"] = cred
                    self.save_unlocked(data)
            return dict(cred)

    def ensure_copilot(self, refresh: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        with auth_file_lock(self.path):
            data = self.load_unlocked()
            cred = data.get("github-copilot")
            if not isinstance(cred, dict):
                raise QuotaError("No `github-copilot` credentials found. Run `pi /login github-copilot` first.")
            if cred.get("type") != "oauth":
                raise QuotaError("`github-copilot` credential is not an OAuth credential.")
            access = cred.get("access")
            refresh_token = cred.get("refresh")
            expires_ms = coerce_float(cred.get("expires")) or 0
            needs_refresh = force_refresh or not isinstance(access, str) or not access or time.time() * 1000 >= expires_ms - 60_000
            if refresh and needs_refresh:
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise QuotaError("`github-copilot` GitHub OAuth token is missing; re-login with Pi.")
                refreshed = refresh_github_copilot(refresh_token, cred.get("enterpriseUrl"))
                cred = {"type": "oauth", **refreshed}
                data["github-copilot"] = cred
                self.save_unlocked(data)
            return dict(cred)


def refresh_openai_codex(refresh_token: str) -> Dict[str, Any]:
    payload, _ = request_form(
        "POST",
        OPENAI_TOKEN_URL,
        headers={"Accept": "application/json"},
        fields={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OPENAI_CODEX_CLIENT_ID,
        },
    )
    if not isinstance(payload, dict):
        raise QuotaError("OpenAI Codex token refresh returned unexpected data.")
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = coerce_float(payload.get("expires_in"))
    if not isinstance(access, str) or not isinstance(refresh, str) or expires_in is None:
        raise QuotaError("OpenAI Codex token refresh response was missing access_token/refresh_token/expires_in.")
    account_id = codex_account_id_from_token(access)
    if not account_id:
        raise QuotaError("Could not extract ChatGPT account ID from refreshed OpenAI Codex token.")
    return {
        "access": access,
        "refresh": refresh,
        "expires": int(time.time() * 1000 + expires_in * 1000),
        "accountId": account_id,
    }


def normalize_github_domain(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = urllib.parse.urlparse(text if "://" in text else f"https://{text}")
        return parsed.hostname
    except Exception:
        return None


def refresh_github_copilot(github_token: str, enterprise_url: Any = None) -> Dict[str, Any]:
    domain = normalize_github_domain(enterprise_url) or "github.com"
    url = f"https://api.{domain}/copilot_internal/v2/token"
    payload, _ = request_json(
        "GET",
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {github_token}",
            **COPILOT_IDE_HEADERS,
        },
    )
    if not isinstance(payload, dict):
        raise QuotaError("GitHub Copilot token refresh returned unexpected data.")
    token = payload.get("token")
    expires_at = coerce_float(payload.get("expires_at"))
    if not isinstance(token, str) or expires_at is None:
        raise QuotaError("GitHub Copilot token refresh response was missing token/expires_at.")
    out = {
        "access": token,
        "refresh": github_token,
        "expires": int(expires_at * 1000 - 5 * 60 * 1000),
    }
    if enterprise_url:
        out["enterpriseUrl"] = enterprise_url
    return out


def codex_headers(cred: Dict[str, Any]) -> Dict[str, str]:
    access = cred.get("access")
    if not isinstance(access, str) or not access:
        raise QuotaError("OpenAI Codex access token is missing.")
    account_id = cred.get("accountId") or codex_account_id_from_token(access)
    if not account_id:
        raise QuotaError("OpenAI Codex accountId is missing and could not be decoded.")
    return {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
        "ChatGPT-Account-ID": str(account_id),
        "User-Agent": "quotas/1.0",
    }


def infer_window_label(window_seconds: Optional[int], fallback: str) -> str:
    if window_seconds is None:
        return fallback
    if 4 * 60 * 60 <= window_seconds <= 6 * 60 * 60:
        return "5h"
    if 6 * 24 * 60 * 60 <= window_seconds <= 8 * 24 * 60 * 60:
        return "weekly"
    if window_seconds % (24 * 60 * 60) == 0:
        return f"{window_seconds // (24 * 60 * 60)}d"
    if window_seconds % (60 * 60) == 0:
        return f"{window_seconds // (60 * 60)}h"
    return fallback


def normalize_window(raw: Any, label: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    used_percent = clamp_percent(coerce_float(raw.get("used_percent")))
    remaining_percent = clamp_percent(100.0 - used_percent) if used_percent is not None else None
    reset_at = coerce_int(raw.get("reset_at"))
    window_seconds = coerce_int(raw.get("limit_window_seconds") or raw.get("window_seconds"))
    if window_seconds is None:
        minutes = coerce_int(raw.get("window_minutes"))
        window_seconds = minutes * 60 if minutes is not None else None
    return {
        "label": infer_window_label(window_seconds, label),
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "window_seconds": window_seconds,
        "window_minutes": int(window_seconds / 60) if window_seconds else coerce_int(raw.get("window_minutes")),
        "reset_at": reset_at,
        "reset_at_local": format_epoch(reset_at),
        "reset_after_seconds": coerce_int(raw.get("reset_after_seconds") or raw.get("reset_after")),
    }


def codex_primary_limit_status(plan_type: Any, window: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe enforcement separately from the still-reported 5h counter."""

    plan = str(plan_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    affected_plan = plan in {"plus", "pro", "business", "team"} or plan.startswith(("plus_", "pro_", "business_"))
    suspended = CODEX_5H_LIMIT_STATUS in {
        "suspended",
        "temporarily_suspended",
        "removed",
        "disabled",
        "off",
    }
    if suspended and affected_plan:
        return {
            "status": "temporarily_suspended",
            "enforced": False,
            "temporary": True,
            "tracking_continues": window is not None,
            "announced_on": CODEX_5H_LIMIT_SUSPENDED_ON,
            "source": CODEX_5H_LIMIT_SUSPENSION_SOURCE,
            "note": "OpenAI temporarily removed the five-hour usage restriction; the API may continue reporting a tracking window.",
        }
    return {
        "status": "active" if window is not None else "unavailable",
        "enforced": True if window is not None else None,
        "temporary": False,
        "tracking_continues": window is not None,
        "source": "https://chatgpt.com/backend-api/wham/usage",
    }


def normalize_codex_reset_credits(raw: Any, source: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    credits: List[Dict[str, Any]] = []
    raw_credits = raw.get("credits")
    if isinstance(raw_credits, list):
        for item in raw_credits:
            if not isinstance(item, dict):
                continue
            credit = {
                "id_preview": identifier_preview(item.get("id")),
                "status": item.get("status"),
                "title": item.get("title"),
                "reset_type": item.get("reset_type"),
                "granted_at": item.get("granted_at"),
                "granted_at_local": format_iso_datetime(item.get("granted_at")),
                "expires_at": item.get("expires_at"),
                "expires_at_local": format_iso_datetime(item.get("expires_at")),
                "redeemed_at": item.get("redeemed_at"),
                "redeemed_at_local": format_iso_datetime(item.get("redeemed_at")),
            }
            credits.append(credit)

    available_count = coerce_int(raw.get("available_count"))
    if available_count is None and credits:
        available_count = sum(1 for credit in credits if credit.get("status") == "available")
    available = available_count > 0 if available_count is not None else any(credit.get("status") == "available" for credit in credits)
    return {
        "available": available,
        "available_count": available_count,
        "total_earned_count": coerce_int(raw.get("total_earned_count")),
        "credits": credits,
        "source": source,
    }


def fetch_codex_reset_credits(cred: Dict[str, Any]) -> Dict[str, Any]:
    payload, _ = request_json("GET", OPENAI_CODEX_RESET_CREDITS_URL, headers=codex_headers(cred))
    normalized = normalize_codex_reset_credits(payload, OPENAI_CODEX_RESET_CREDITS_URL)
    if normalized is None:
        raise QuotaError("OpenAI Codex reset credits response had unexpected shape.")
    return normalized


def fetch_codex_usage(auth: AuthStore, refresh: bool = True) -> Dict[str, Any]:
    cred = auth.ensure_codex(refresh=refresh)
    payload, _ = request_json("GET", f"{OPENAI_CODEX_BASE_URL}/wham/usage", headers=codex_headers(cred))
    if not isinstance(payload, dict):
        raise QuotaError("OpenAI Codex usage response had unexpected shape.")
    rate_limit = payload.get("rate_limit") or {}
    code_review = payload.get("code_review_rate_limit")
    reset_credits = normalize_codex_reset_credits(payload.get("rate_limit_reset_credits"), "https://chatgpt.com/backend-api/wham/usage")
    reset_credits_error = None
    try:
        reset_credits = fetch_codex_reset_credits(cred)
    except Exception as exc:
        reset_credits_error = str(exc)
    # OpenAI may move a surviving weekly window into `primary_window` when the
    # rolling five-hour window is disabled. Classify by duration rather than by
    # upstream slot name.
    primary = normalize_window(rate_limit.get("primary_window") if isinstance(rate_limit, dict) else None, "primary")
    secondary = normalize_window(rate_limit.get("secondary_window") if isinstance(rate_limit, dict) else None, "secondary")
    windows = [window for window in (primary, secondary) if window]
    five_hour = next((window for window in windows if window.get("label") == "5h"), None)
    weekly = next((window for window in windows if window.get("label") == "weekly"), None)
    primary_limit = codex_primary_limit_status(payload.get("plan_type"), five_hour)
    upstream_limit_reached = rate_limit.get("limit_reached") if isinstance(rate_limit, dict) else None
    summary = {
        "plan_type": payload.get("plan_type"),
        "allowed": rate_limit.get("allowed") if isinstance(rate_limit, dict) else None,
        "limit_reached": upstream_limit_reached,
        "effective_limit_reached": False if primary_limit.get("enforced") is False else upstream_limit_reached,
        "rate_limit_reached_type": payload.get("rate_limit_reached_type"),
        "primary": primary,
        "secondary": secondary,
        "five_hour": five_hour,
        "weekly": weekly,
        "primary_limit": primary_limit,
        "code_review": normalize_window(code_review.get("primary_window"), "code_review") if isinstance(code_review, dict) else None,
        "credits": payload.get("credits") if isinstance(payload.get("credits"), dict) else None,
        "rate_limit_reset_credits": reset_credits,
        "rate_limit_reset_credits_error": reset_credits_error,
        "additional_rate_limits": payload.get("additional_rate_limits"),
        "source": "https://chatgpt.com/backend-api/wham/usage",
    }
    return summary


def fetch_codex_models(auth: AuthStore, client_version: str, refresh: bool = True) -> Dict[str, Any]:
    cred = auth.ensure_codex(refresh=refresh)
    version = urllib.parse.quote(client_version)
    url = f"{OPENAI_CODEX_BASE_URL}/codex/models?client_version={version}"
    payload, _ = request_json("GET", url, headers=codex_headers(cred))
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise QuotaError("OpenAI Codex models response had unexpected shape.")
    models: List[Dict[str, Any]] = []
    for item in payload["models"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("slug") or item.get("id") or item.get("model")
        if not isinstance(model_id, str) or not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "display_name": item.get("display_name") or item.get("displayName"),
                "description": item.get("description"),
                "default_reasoning_level": item.get("default_reasoning_level"),
                "supported_reasoning_levels": item.get("supported_reasoning_levels"),
                "supported_in_api": item.get("supported_in_api"),
                "visibility": item.get("visibility"),
                "priority": item.get("priority"),
                "upgrade": item.get("upgrade"),
                "context_window": item.get("context_window"),
                "minimal_client_version": item.get("minimal_client_version"),
            }
        )
    return {
        "client_version": client_version,
        "count": len(models),
        "models": models,
        "source": f"{OPENAI_CODEX_BASE_URL}/codex/models",
    }


def parse_codex_error_payload(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"Codex error:\s*(\{.*\})", text, flags=re.DOTALL)
    if not match:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
    else:
        candidate = match.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def parse_codex_rate_limit_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    lower = {str(k).lower(): v for k, v in headers.items()}
    primary = normalize_window(
        {
            "used_percent": lower.get("x-codex-primary-used-percent"),
            "window_minutes": lower.get("x-codex-primary-window-minutes"),
            "reset_at": lower.get("x-codex-primary-reset-at"),
            "reset_after_seconds": lower.get("x-codex-primary-reset-after-seconds"),
        },
        "5h",
    )
    secondary = normalize_window(
        {
            "used_percent": lower.get("x-codex-secondary-used-percent"),
            "window_minutes": lower.get("x-codex-secondary-window-minutes"),
            "reset_at": lower.get("x-codex-secondary-reset-at"),
            "reset_after_seconds": lower.get("x-codex-secondary-reset-after-seconds"),
        },
        "weekly",
    )
    return {
        "active_limit": lower.get("x-codex-active-limit"),
        "plan_type": lower.get("x-codex-plan-type"),
        "primary": primary,
        "secondary": secondary,
        "credits": {
            "has_credits": lower.get("x-codex-credits-has-credits"),
            "balance": lower.get("x-codex-credits-balance"),
            "unlimited": lower.get("x-codex-credits-unlimited"),
        },
    }


def run_codex_probe(model: str, prompt: str = "Reply with OK.", timeout: int = 90) -> Dict[str, Any]:
    full_model = model if model.startswith("openai-codex/") else f"openai-codex/{model}"
    cmd = ["pi", "--model", full_model, "--no-tools", "-p", prompt]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "model": model, "error": "`pi` command not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "model": model, "error": f"probe timed out after {timeout}s"}
    output = (proc.stdout or "") + (proc.stderr or "")
    payload = parse_codex_error_payload(output)
    result: Dict[str, Any] = {
        "ok": proc.returncode == 0,
        "model": model,
        "command": " ".join(cmd[:-1] + ["<prompt>"]),
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
    }
    if payload:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        result.update(
            {
                "ok": False,
                "error_type": error.get("type"),
                "message": error.get("message") or payload.get("message"),
                "status_code": payload.get("status_code"),
                "plan_type": error.get("plan_type") or payload.get("plan_type"),
                "resets_at": error.get("resets_at"),
                "resets_at_local": format_epoch(error.get("resets_at")),
                "resets_in_seconds": error.get("resets_in_seconds"),
            }
        )
        if isinstance(payload.get("headers"), dict):
            result["rate_limits"] = parse_codex_rate_limit_headers(payload["headers"])
    elif proc.returncode != 0:
        result["error"] = output.strip()[:2000] or f"pi exited with {proc.returncode}"
    else:
        result["message"] = output.strip()[:2000]
    return result


def copilot_base_url(token: str, enterprise_url: Any = None) -> str:
    match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token or "", flags=re.IGNORECASE)
    if match:
        host = match.group(1).strip().replace("proxy.", "api.", 1)
        return f"https://{host}"
    domain = normalize_github_domain(enterprise_url)
    if domain:
        return f"https://copilot-api.{domain}"
    return "https://api.individual.githubcopilot.com"


def get_arg_or_env(args: Optional[argparse.Namespace], attr: str, env_name: str, default: Any = None) -> Any:
    if args is not None and hasattr(args, attr):
        value = getattr(args, attr)
        if value not in (None, ""):
            return value
    value = os.environ.get(env_name)
    if value not in (None, ""):
        return value
    return default


def copilot_snapshot_token_based(snapshots: Dict[str, Any]) -> bool:
    for snapshot in snapshots.values():
        if isinstance(snapshot, dict) and snapshot.get("token_based_billing") is True:
            return True
    return False


def normalize_copilot_premium_snapshot(raw: Any) -> Dict[str, Any]:
    premium = raw if isinstance(raw, dict) else {}
    remaining_value = premium.get("remaining")
    if remaining_value is None:
        remaining_value = premium.get("quota_remaining")
    remaining = coerce_float(remaining_value)
    entitlement = coerce_float(premium.get("entitlement"))
    percent_remaining = coerce_float(premium.get("percent_remaining"))
    used = entitlement - remaining if entitlement is not None and remaining is not None else None
    used_percent = 100.0 - percent_remaining if percent_remaining is not None else None
    return {
        "used": used,
        "remaining": remaining,
        "entitlement": entitlement,
        "used_percent": clamp_percent(used_percent),
        "percent_remaining": clamp_percent(percent_remaining),
        "unlimited": premium.get("unlimited"),
        "overage_count": premium.get("overage_count"),
        "overage_permitted": premium.get("overage_permitted"),
        "timestamp_utc": premium.get("timestamp_utc"),
    }


def infer_copilot_plan_key(usage: Dict[str, Any]) -> Optional[str]:
    text = " ".join(
        str(usage.get(key) or "")
        for key in ("plan", "access_type_sku", "copilot_plan", "sku")
    ).lower()
    text = text.replace("-", "_").replace(" ", "_")
    if "enterprise" in text:
        return "enterprise"
    if "business" in text or "organization" in text or "org" in text:
        return "business"
    if "max" in text:
        return "max"
    if "pro_plus" in text or "pro+" in text or "proplus" in text:
        return "pro_plus"
    if re.search(r"(?:^|_)pro(?:_|$)", text) or "standalone" in text:
        return "pro"
    if "student" in text or "education" in text or "educational" in text:
        return "student"
    if "free" in text:
        return "free"
    return None


def copilot_plan_allowance(plan_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not plan_key:
        return None
    allowance = COPILOT_PLAN_ALLOWANCES.get(plan_key)
    if not allowance:
        return None
    out = dict(allowance)
    if plan_key in {"business", "enterprise"}:
        today = now_utc().date()
        out["promotional_period_active"] = COPILOT_USAGE_BASED_BILLING_STARTED <= today < COPILOT_BUSINESS_ENTERPRISE_PROMO_END
        out["pool_note"] = "Included AI Credits are pooled at the billing entity level."
    return out


def github_api_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "quotas/1.0",
    }


def fetch_github_login(token: str, api_base_url: str) -> str:
    payload, _ = request_json("GET", f"{api_base_url.rstrip('/')}/user", headers=github_api_headers(token))
    if not isinstance(payload, dict) or not isinstance(payload.get("login"), str) or not payload["login"]:
        raise QuotaError("Could not determine GitHub username from billing token.")
    return payload["login"]


def normalize_copilot_billing_scope(args: Optional[argparse.Namespace], token: Optional[str]) -> str:
    scope = str(get_arg_or_env(args, "copilot_billing_scope", "QUOTAS_COPILOT_BILLING_SCOPE", "auto")).strip().lower()
    if scope in {"", "auto"}:
        if get_arg_or_env(args, "copilot_billing_enterprise", "QUOTAS_GITHUB_ENTERPRISE"):
            return "enterprise"
        if get_arg_or_env(args, "copilot_billing_org", "QUOTAS_GITHUB_ORG"):
            return "org"
        return "user" if token else "none"
    if scope in {"off", "disabled", "false", "0"}:
        return "none"
    if scope == "organization":
        return "org"
    return scope


def copilot_billing_period(args: Optional[argparse.Namespace]) -> Dict[str, int]:
    current = now_utc()
    year = coerce_int(get_arg_or_env(args, "copilot_billing_year", "QUOTAS_COPILOT_BILLING_YEAR")) or current.year
    month = coerce_int(get_arg_or_env(args, "copilot_billing_month", "QUOTAS_COPILOT_BILLING_MONTH")) or current.month
    day = coerce_int(get_arg_or_env(args, "copilot_billing_day", "QUOTAS_COPILOT_BILLING_DAY"))
    period = {"year": year, "month": month}
    if day is not None:
        period["day"] = day
    return period


def copilot_billing_endpoint(args: Optional[argparse.Namespace], token: str, api_base_url: str, scope: str) -> Tuple[str, Dict[str, Any]]:
    target: Dict[str, Any] = {"scope": scope}
    if scope == "user":
        username = get_arg_or_env(args, "copilot_billing_username", "QUOTAS_COPILOT_USERNAME")
        if not username:
            username = fetch_github_login(token, api_base_url)
        target["username"] = username
        path = f"/users/{urllib.parse.quote(str(username), safe='')}/settings/billing/ai_credit/usage"
    elif scope == "org":
        org = get_arg_or_env(args, "copilot_billing_org", "QUOTAS_GITHUB_ORG")
        if not org:
            raise QuotaError("Copilot billing scope is org, but QUOTAS_GITHUB_ORG/--copilot-billing-org is not set.")
        target["org"] = org
        path = f"/organizations/{urllib.parse.quote(str(org), safe='')}/settings/billing/ai_credit/usage"
    elif scope == "enterprise":
        enterprise = get_arg_or_env(args, "copilot_billing_enterprise", "QUOTAS_GITHUB_ENTERPRISE")
        if not enterprise:
            raise QuotaError("Copilot billing scope is enterprise, but QUOTAS_GITHUB_ENTERPRISE/--copilot-billing-enterprise is not set.")
        target["enterprise"] = enterprise
        path = f"/enterprises/{urllib.parse.quote(str(enterprise), safe='')}/settings/billing/ai_credit/usage"
    else:
        raise QuotaError(f"Unsupported Copilot billing scope: {scope}")
    return f"{api_base_url.rstrip('/')}{path}", target


def first_number(item: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        number = coerce_float(item.get(key))
        if number is not None:
            return number
    return None


def is_copilot_ai_credit_item(item: Dict[str, Any]) -> bool:
    product = str(item.get("product") or "").lower().replace(" ", "_").replace("-", "_")
    sku = str(item.get("sku") or "").lower().replace(" ", "_").replace("-", "_")
    unit_type = str(item.get("unitType") or item.get("unit_type") or "").lower().replace(" ", "_").replace("-", "_")
    return "ai_credit" in product or "ai_credit" in sku or "ai_credit" in unit_type or (
        product in {"copilot", "github_copilot"} and "credit" in unit_type
    )


def normalize_copilot_billing_summary(payload: Dict[str, Any], period: Dict[str, int]) -> Dict[str, Any]:
    raw_items = payload.get("usageItems") or payload.get("usage_items") or []
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    filtered = [item for item in items if is_copilot_ai_credit_item(item)]
    considered = filtered

    gross_quantity = 0.0
    discount_quantity = 0.0
    net_quantity = 0.0
    gross_amount = 0.0
    discount_amount = 0.0
    net_amount = 0.0
    saw_gross_quantity = False
    saw_discount_quantity = False
    saw_net_quantity = False
    unit_types = set()
    models = set()

    for item in considered:
        unit_type = item.get("unitType") or item.get("unit_type")
        if unit_type:
            unit_types.add(str(unit_type))
        model = item.get("model")
        if model:
            models.add(str(model))
        number = first_number(item, ("grossQuantity", "gross_quantity", "quantity"))
        if number is not None:
            gross_quantity += number
            saw_gross_quantity = True
        number = first_number(item, ("discountQuantity", "discount_quantity"))
        if number is not None:
            discount_quantity += number
            saw_discount_quantity = True
        number = first_number(item, ("netQuantity", "net_quantity"))
        if number is not None:
            net_quantity += number
            saw_net_quantity = True
        gross_amount += first_number(item, ("grossAmount", "gross_amount")) or 0.0
        discount_amount += first_number(item, ("discountAmount", "discount_amount")) or 0.0
        net_amount += first_number(item, ("netAmount", "net_amount")) or 0.0

    credits_used = gross_quantity if saw_gross_quantity else (gross_amount / COPILOT_AI_CREDIT_VALUE_USD if gross_amount else 0.0)
    included_credits = discount_quantity if saw_discount_quantity else (discount_amount / COPILOT_AI_CREDIT_VALUE_USD if discount_amount else 0.0)
    billed_credits = net_quantity if saw_net_quantity else (net_amount / COPILOT_AI_CREDIT_VALUE_USD if net_amount else 0.0)
    return {
        "available": True,
        "period": period,
        "items_total": len(items),
        "items_matched": len(filtered),
        "unit_types": sorted(unit_types),
        "models": sorted(models),
        "credits_used": credits_used,
        "included_credits": included_credits,
        "billed_credits": billed_credits,
        "gross_amount_usd": gross_amount,
        "discount_amount_usd": discount_amount,
        "net_amount_usd": net_amount,
        "source_docs": COPILOT_BILLING_USAGE_API_DOCS,
    }


def fetch_copilot_billing_usage(args: Optional[argparse.Namespace]) -> Dict[str, Any]:
    token = os.environ.get(COPILOT_BILLING_TOKEN_ENV)
    api_base_url = str(get_arg_or_env(args, "github_api_base_url", "QUOTAS_GITHUB_API_BASE_URL", GITHUB_API_BASE_URL)).rstrip("/")
    raw_scope = str(get_arg_or_env(args, "copilot_billing_scope", "QUOTAS_COPILOT_BILLING_SCOPE", "auto")).strip().lower()
    scope = normalize_copilot_billing_scope(args, token)
    if scope == "none" and raw_scope not in {"", "auto"}:
        return {
            "available": False,
            "reason": "GitHub Billing API AI Credits usage is disabled by configuration.",
            "scope": scope,
            "source_docs": COPILOT_BILLING_USAGE_API_DOCS,
        }
    if not token:
        return {
            "available": False,
            "reason": f"{COPILOT_BILLING_TOKEN_ENV} is not set; only internal Copilot allowance snapshots are available.",
            "scope": None if scope == "none" else scope,
            "source_docs": COPILOT_BILLING_USAGE_API_DOCS,
        }
    if scope == "none":
        return {
            "available": False,
            "reason": "GitHub Billing API AI Credits usage is disabled by configuration.",
            "scope": scope,
            "source_docs": COPILOT_BILLING_USAGE_API_DOCS,
        }

    endpoint, target = copilot_billing_endpoint(args, token, api_base_url, scope)
    period = copilot_billing_period(args)
    # The dedicated endpoint only returns AI Credit records, so do not apply
    # generic usage-summary SKU filters (their names differ by account scope).
    params: Dict[str, Any] = dict(period)
    cost_center_id = get_arg_or_env(args, "copilot_billing_cost_center_id", "QUOTAS_COPILOT_BILLING_COST_CENTER_ID")
    if cost_center_id and scope == "enterprise":
        params["cost_center_id"] = cost_center_id
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    payload, _ = request_json("GET", url, headers=github_api_headers(token))
    if not isinstance(payload, dict):
        raise QuotaError("GitHub Billing API usage summary response had unexpected shape.")
    summary = normalize_copilot_billing_summary(payload, period)
    summary.update({"scope": scope, "target": target, "source": url})
    return summary


def build_copilot_ai_credit_summary(usage: Dict[str, Any], billing_usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if usage.get("billing_model") != "ai_credits":
        return None

    plan_allowance = usage.get("plan_allowance") if isinstance(usage.get("plan_allowance"), dict) else {}
    premium = usage.get("legacy_premium_interactions") if isinstance(usage.get("legacy_premium_interactions"), dict) else {}
    summary: Dict[str, Any] = {
        "unit": "GitHub AI Credits",
        "credit_value_usd": COPILOT_AI_CREDIT_VALUE_USD,
        "source_docs": COPILOT_USAGE_BASED_BILLING_DOCS,
        "available": False,
    }

    if isinstance(billing_usage, dict):
        summary["billing_api"] = {
            "available": billing_usage.get("available"),
            "reason": billing_usage.get("reason"),
            "scope": billing_usage.get("scope"),
            "period": billing_usage.get("period"),
            "source_docs": billing_usage.get("source_docs"),
        }
        if billing_usage.get("available"):
            summary["used"] = billing_usage.get("credits_used")
            summary["included_credits_applied"] = billing_usage.get("included_credits")
            summary["additional_billed_credits"] = billing_usage.get("billed_credits")
            summary["additional_billed_usd"] = billing_usage.get("net_amount_usd")
            summary["billing_period"] = billing_usage.get("period")
            summary["usage_source"] = "github_billing_usage_summary"
            summary["source"] = billing_usage.get("source")

    if plan_allowance:
        summary["plan_allowance"] = plan_allowance
        if plan_allowance.get("total_credits") is not None:
            summary.setdefault("entitlement", plan_allowance.get("total_credits"))
            summary["base_credits"] = plan_allowance.get("base_credits")
            summary["flex_credits"] = plan_allowance.get("flex_credits")
            summary["allowance_source"] = plan_allowance.get("source")
        if plan_allowance.get("total_credits_per_user") is not None:
            summary["entitlement_per_user"] = plan_allowance.get("total_credits_per_user")
            summary["promotional_entitlement_per_user"] = plan_allowance.get("promotional_total_credits_per_user")
            summary["pooled"] = plan_allowance.get("pooled")
            summary["allowance_source"] = plan_allowance.get("source")

    internal_has_numbers = any(premium.get(key) is not None for key in ("used", "remaining", "entitlement"))
    if internal_has_numbers:
        summary["internal_allowance_snapshot"] = premium
        if summary.get("used") is None and premium.get("used") is not None:
            summary["used"] = premium.get("used")
            summary["usage_source"] = "copilot_internal_user.quota_snapshots.premium_interactions"
        if summary.get("entitlement") is None and premium.get("entitlement") is not None:
            summary["entitlement"] = premium.get("entitlement")
            summary["allowance_source"] = "copilot_internal_user.quota_snapshots.premium_interactions"
        if summary.get("remaining") is None and premium.get("remaining") is not None:
            summary["remaining"] = premium.get("remaining")
        summary.setdefault(
            "source_note",
            "GitHub's internal user endpoint still labels this allowance snapshot premium_interactions; token_based_billing=true indicates AI Credits are active.",
        )

    used = coerce_float(summary.get("used"))
    entitlement = coerce_float(summary.get("entitlement"))
    if summary.get("remaining") is None and used is not None and entitlement is not None:
        summary["remaining"] = max(0.0, entitlement - used)
    remaining = coerce_float(summary.get("remaining"))
    if summary.get("used_percent") is None and used is not None and entitlement not in (None, 0):
        summary["used_percent"] = clamp_percent((used / entitlement) * 100.0)
    if summary.get("percent_remaining") is None and remaining is not None and entitlement not in (None, 0):
        summary["percent_remaining"] = clamp_percent((remaining / entitlement) * 100.0)
    summary["reset_date"] = usage.get("quota_reset_date")
    summary["reset_date_utc"] = usage.get("quota_reset_date_utc")
    summary["reset_at_local"] = usage.get("quota_reset_at_local")
    summary["available"] = any(summary.get(key) is not None for key in ("used", "remaining", "entitlement", "entitlement_per_user"))
    return summary


def fetch_copilot_usage(auth: AuthStore, refresh: bool = True, args: Optional[argparse.Namespace] = None) -> Dict[str, Any]:
    cred = auth.ensure_copilot(refresh=refresh)
    github_token = cred.get("refresh")
    if not isinstance(github_token, str) or not github_token:
        raise QuotaError("GitHub Copilot OAuth token is missing.")
    payload, _ = request_json(
        "GET",
        "https://api.github.com/copilot_internal/user",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/json",
            "User-Agent": "quotas/1.0",
        },
    )
    if not isinstance(payload, dict):
        raise QuotaError("GitHub Copilot usage response had unexpected shape.")
    snapshots = payload.get("quota_snapshots") if isinstance(payload.get("quota_snapshots"), dict) else {}
    premium = normalize_copilot_premium_snapshot(snapshots.get("premium_interactions") if isinstance(snapshots, dict) else {})
    token_based_billing = copilot_snapshot_token_based(snapshots)
    billing_model = "ai_credits" if token_based_billing else "premium_requests"
    usage: Dict[str, Any] = {
        "billing_model": billing_model,
        "token_based_billing": token_based_billing,
        "plan": payload.get("copilot_plan") or payload.get("access_type_sku"),
        "access_type_sku": payload.get("access_type_sku"),
        "chat_enabled": payload.get("chat_enabled"),
        "quota_reset_date": payload.get("quota_reset_date"),
        "quota_reset_date_utc": payload.get("quota_reset_date_utc"),
        "quota_reset_at_local": format_iso_datetime(payload.get("quota_reset_date_utc")),
        "legacy_premium_interactions": premium,
        "premium_interactions": premium,
        "chat": snapshots.get("chat") if isinstance(snapshots, dict) else None,
        "completions": snapshots.get("completions") if isinstance(snapshots, dict) else None,
        "source": "https://api.github.com/copilot_internal/user",
    }
    plan_key = infer_copilot_plan_key(usage)
    usage["plan_key"] = plan_key
    usage["plan_allowance"] = copilot_plan_allowance(plan_key)

    billing_usage: Optional[Dict[str, Any]] = None
    billing_error: Optional[str] = None
    try:
        billing_usage = fetch_copilot_billing_usage(args)
    except Exception as exc:
        billing_error = str(exc)
    usage["ai_credit_billing"] = billing_usage
    usage["ai_credit_billing_error"] = billing_error
    usage["ai_credits"] = build_copilot_ai_credit_summary(usage, billing_usage)
    return usage


def fetch_copilot_models(auth: AuthStore, refresh: bool = True) -> Dict[str, Any]:
    cred = auth.ensure_copilot(refresh=refresh)
    token = cred.get("access")
    if not isinstance(token, str) or not token:
        raise QuotaError("GitHub Copilot IDE token is missing.")
    base_url = copilot_base_url(token, cred.get("enterpriseUrl"))
    payload, _ = request_json(
        "GET",
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": COPILOT_MODELS_API_VERSION,
            **COPILOT_IDE_HEADERS,
        },
    )
    raw_models: Any
    if isinstance(payload, dict):
        raw_models = payload.get("data", [])
    elif isinstance(payload, list):
        raw_models = payload
    else:
        raise QuotaError("GitHub Copilot models response had unexpected shape.")
    if not isinstance(raw_models, list):
        raise QuotaError("GitHub Copilot models response did not contain a list.")
    catalog_models: List[Dict[str, Any]] = []
    selectable_models: List[Dict[str, Any]] = []
    for item in raw_models:
        if isinstance(item, str):
            model = {"id": item, "selectable": True}
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
            if not isinstance(model_id, str) or not model_id:
                continue
            billing = item.get("billing") if isinstance(item.get("billing"), dict) else {}
            capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
            supports = capabilities.get("supports") if isinstance(capabilities.get("supports"), dict) else {}
            policy = item.get("policy") if isinstance(item.get("policy"), dict) else {}
            supported_endpoints = item.get("supported_endpoints")
            if not isinstance(supported_endpoints, list):
                supported_endpoints = capabilities.get("supported_endpoints") if isinstance(capabilities.get("supported_endpoints"), list) else []
            picker_enabled = item.get("model_picker_enabled") is True
            policy_state = policy.get("state") or item.get("policy_state")
            tool_calls_supported = supports.get("tool_calls") is not False
            selectable = picker_enabled and policy_state != "disabled" and tool_calls_supported
            model = {
                "id": model_id,
                "name": item.get("name"),
                "version": item.get("version"),
                "vendor": item.get("vendor"),
                "selectable": selectable,
                "model_picker_enabled": picker_enabled,
                "model_picker_category": item.get("model_picker_category"),
                "model_picker_price_category": item.get("model_picker_price_category"),
                "policy_state": policy_state,
                "tool_calls_supported": tool_calls_supported,
                "supported_endpoints": supported_endpoints,
                "preview": item.get("preview"),
                "billing_multiplier": billing.get("multiplier"),
                "billing": billing or None,
            }
        else:
            continue
        catalog_models.append(model)
        if model.get("selectable"):
            selectable_models.append(model)
    return {
        "base_url": base_url,
        "api_version": COPILOT_MODELS_API_VERSION,
        "count": len(selectable_models),
        "catalog_count": len(catalog_models),
        "auto_model_selection_only": bool(catalog_models and not selectable_models),
        "models": selectable_models,
        "catalog_models": catalog_models,
        "source": f"{base_url}/models",
    }


def check_required_models(models_payload: Dict[str, Any], required: Iterable[str]) -> Dict[str, bool]:
    ids = {m.get("id") for m in models_payload.get("models", []) if isinstance(m, dict)}
    return {name: name in ids for name in required}


def provider_result(callable_obj, *args, **kwargs) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return callable_obj(*args, **kwargs), None
    except Exception as exc:
        return None, str(exc)


def build_codex_report(args: argparse.Namespace) -> Dict[str, Any]:
    auth = AuthStore(Path(args.auth_path))
    usage, usage_error = provider_result(fetch_codex_usage, auth, not args.no_refresh)
    models, models_error = provider_result(fetch_codex_models, auth, args.codex_client_version, not args.no_refresh)
    required = check_required_models(models or {"models": []}, args.require_model or []) if models else {m: False for m in (args.require_model or [])}
    probes = [run_codex_probe(model, timeout=args.probe_timeout) for model in (args.probe or [])]
    ok = usage_error is None and models_error is None and all(required.values()) and all(p.get("ok") for p in probes)
    return {
        "provider": "openai-codex",
        "ok": ok,
        "checked_at": iso_now(),
        "usage": usage,
        "usage_error": usage_error,
        "models": models,
        "models_error": models_error,
        "required_models": required,
        "probes": probes,
        "probe_warning": "Probes send a real prompt through Pi and may consume Codex quota." if probes else None,
    }


def build_copilot_report(args: argparse.Namespace) -> Dict[str, Any]:
    auth = AuthStore(Path(args.auth_path))
    usage, usage_error = provider_result(fetch_copilot_usage, auth, not args.no_refresh, args)
    models, models_error = provider_result(fetch_copilot_models, auth, not args.no_refresh)
    required = check_required_models(models or {"models": []}, args.require_model or []) if models else {m: False for m in (args.require_model or [])}
    ok = usage_error is None and models_error is None and all(required.values())
    return {
        "provider": "github-copilot",
        "ok": ok,
        "checked_at": iso_now(),
        "usage": usage,
        "usage_error": usage_error,
        "models": models,
        "models_error": models_error,
        "required_models": required,
    }


def build_combined_report(args: argparse.Namespace) -> Dict[str, Any]:
    codex_args = argparse.Namespace(**vars(args))
    copilot_args = argparse.Namespace(**vars(args))
    codex_args.require_model = args.require_codex_model or []
    copilot_args.require_model = args.require_copilot_model or []
    codex_args.probe = args.probe_codex or []
    codex = build_codex_report(codex_args)
    copilot = build_copilot_report(copilot_args)
    report = {
        "ok": bool(codex.get("ok") and copilot.get("ok")),
        "checked_at": iso_now(),
        "providers": {
            "openai-codex": codex,
            "github-copilot": copilot,
        },
    }
    return report


def save_report(report: Dict[str, Any], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    latest_path = data_dir / "latest.json"
    tmp = latest_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, latest_path)


def print_window(prefix: str, window: Optional[Dict[str, Any]]) -> None:
    if not window:
        print(f"  {prefix}: unavailable")
        return
    used = window.get("used_percent")
    remaining = window.get("remaining_percent")
    reset = window.get("reset_at_local") or "unknown"
    if used is None:
        print(f"  {prefix}: unavailable")
    else:
        print(f"  {prefix}: {used:.0f}% used, {remaining:.0f}% remaining; resets {reset}")


def print_codex_human(report: Dict[str, Any], list_models: bool = False) -> None:
    status = "OK" if report.get("ok") else "CHECK FAILED"
    usage = report.get("usage") or {}
    plan = usage.get("plan_type") or "unknown plan"
    print(f"OpenAI Codex: {status} ({plan})")
    if report.get("usage_error"):
        print(f"  Usage error: {report['usage_error']}")
    else:
        primary_limit = usage.get("primary_limit") if isinstance(usage.get("primary_limit"), dict) else {}
        five_hour_window = usage.get("five_hour") if "five_hour" in usage else usage.get("primary")
        weekly_window = usage.get("weekly") if "weekly" in usage else usage.get("secondary")
        if primary_limit.get("enforced") is False:
            print("  5h: limit temporarily removed")
        else:
            print_window("5h", five_hour_window)
        print_window("Weekly", weekly_window)
        credits = usage.get("credits") or {}
        if isinstance(credits, dict) and credits.get("has_credits"):
            print(f"  Credits: balance {credits.get('balance')} (unlimited={credits.get('unlimited')})")
        reset_credits = usage.get("rate_limit_reset_credits") or {}
        if isinstance(reset_credits, dict) and reset_credits.get("available_count") is not None:
            line = f"  Banked resets: {human_number(reset_credits.get('available_count'))} available"
            available_credits = [
                credit
                for credit in (reset_credits.get("credits") or [])
                if isinstance(credit, dict) and credit.get("status") == "available"
            ]
            expires = [credit.get("expires_at_local") or credit.get("expires_at") for credit in available_credits if credit.get("expires_at_local") or credit.get("expires_at")]
            if expires:
                line += f"; expires {', '.join(str(item) for item in expires[:2])}{'...' if len(expires) > 2 else ''}"
            print(line)
        if usage.get("rate_limit_reset_credits_error"):
            print(f"  Banked resets detail error: {usage['rate_limit_reset_credits_error']}")
    if report.get("models_error"):
        print(f"  Models error: {report['models_error']}")
    else:
        models = (report.get("models") or {}).get("models", [])
        ids = [m.get("id") for m in models if isinstance(m, dict)]
        print(f"  Models: {len(ids)} available" + (f" ({', '.join(ids[:8])}{'...' if len(ids) > 8 else ''})" if ids else ""))
        if list_models:
            for model_id in ids:
                print(f"    - {model_id}")
    for name, ok in (report.get("required_models") or {}).items():
        print(f"  Required {name}: {'available' if ok else 'MISSING'}")
    for probe in report.get("probes") or []:
        print(f"  Probe {probe.get('model')}: {'OK' if probe.get('ok') else 'FAILED'}")
        if not probe.get("ok"):
            detail = probe.get("message") or probe.get("error") or probe.get("error_type")
            print(f"    {detail}")


def human_number(value: Any) -> str:
    number = coerce_float(value)
    if number is None:
        return "?"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}".rstrip("0").rstrip(".")


def print_copilot_human(report: Dict[str, Any], list_models: bool = False) -> None:
    status = "OK" if report.get("ok") else "CHECK FAILED"
    usage = report.get("usage") or {}
    plan = usage.get("plan") or usage.get("access_type_sku") or "unknown plan"
    plan_allowance = usage.get("plan_allowance") if isinstance(usage.get("plan_allowance"), dict) else {}
    plan_label = plan_allowance.get("label") or plan
    print(f"GitHub Copilot: {status} ({plan_label})")
    if report.get("usage_error"):
        print(f"  Usage error: {report['usage_error']}")
    else:
        billing_model = usage.get("billing_model")
        if billing_model == "ai_credits":
            ai = usage.get("ai_credits") if isinstance(usage.get("ai_credits"), dict) else {}
            reset = (ai.get("reset_at_local") if isinstance(ai, dict) else None) or usage.get("quota_reset_at_local") or usage.get("quota_reset_date_utc") or usage.get("quota_reset_date") or "unknown"
            if ai and ai.get("used") is not None and ai.get("entitlement") is not None:
                print(
                    "  AI credits: "
                    f"{human_number(ai.get('used'))}/{human_number(ai.get('entitlement'))} used, "
                    f"{human_number(ai.get('remaining'))} remaining "
                    f"({human_number(ai.get('used_percent'))}% used); resets {reset}"
                )
            elif ai and ai.get("used") is not None:
                print(f"  AI credits: {human_number(ai.get('used'))} used in billing period {ai.get('billing_period') or 'current'}; resets {reset}")
            elif ai and ai.get("entitlement") is not None:
                print(f"  AI credits: {human_number(ai.get('entitlement'))} included; usage unavailable; resets {reset}")
            elif ai and ai.get("entitlement_per_user") is not None:
                print(f"  AI credits: {human_number(ai.get('entitlement_per_user'))} per user/month, pooled; usage unavailable")
            else:
                print("  AI credits: token-based billing active; usage unavailable")

            if isinstance(ai, dict) and ai.get("usage_source") == "copilot_internal_user.quota_snapshots.premium_interactions":
                print("  Source: internal Copilot allowance snapshot; configure GitHub Billing API for official AI Credit spend.")
            billing = usage.get("ai_credit_billing") if isinstance(usage.get("ai_credit_billing"), dict) else {}
            if usage.get("ai_credit_billing_error"):
                print(f"  Billing API: {usage['ai_credit_billing_error']}")
            elif billing and not billing.get("available") and billing.get("reason"):
                print(f"  Billing API: {billing.get('reason')}")
        else:
            premium = usage.get("legacy_premium_interactions") or usage.get("premium_interactions") or {}
            if premium:
                used = premium.get("used")
                entitlement = premium.get("entitlement")
                remaining = premium.get("remaining")
                pct = premium.get("used_percent")
                reset = usage.get("quota_reset_at_local") or usage.get("quota_reset_date_utc") or usage.get("quota_reset_date") or "unknown"
                if used is not None and entitlement is not None:
                    print(f"  Premium requests: {used:.0f}/{entitlement:.0f} used, {remaining:.0f} remaining ({pct:.0f}% used); resets {reset}")
                else:
                    print(f"  Premium requests: {premium}")
    if report.get("models_error"):
        print(f"  Models error: {report['models_error']}")
    else:
        models_payload = report.get("models") or {}
        models = models_payload.get("models", [])
        ids = [m.get("id") for m in models if isinstance(m, dict)]
        catalog_count = models_payload.get("catalog_count", len(ids))
        print(
            f"  Models: {len(ids)} manually selectable, {catalog_count} catalog entries"
            + (f" ({', '.join(ids[:8])}{'...' if len(ids) > 8 else ''})" if ids else "")
        )
        if models_payload.get("auto_model_selection_only"):
            print("  Model selection: account is restricted to automatic model selection")
        if list_models:
            for model_id in ids:
                print(f"    - {model_id}")
    for name, ok in (report.get("required_models") or {}).items():
        print(f"  Required {name}: {'available' if ok else 'MISSING'}")


def print_human(report: Dict[str, Any], command: str, list_models: bool = False) -> None:
    if command == "codex":
        print_codex_human(report, list_models=list_models)
    elif command == "copilot":
        print_copilot_human(report, list_models=list_models)
    else:
        print(f"Quotas check: {'OK' if report.get('ok') else 'CHECK FAILED'} at {report.get('checked_at')}")
        providers = report.get("providers") or {}
        print_codex_human(providers.get("openai-codex") or {}, list_models=list_models)
        print_copilot_human(providers.get("github-copilot") or {}, list_models=list_models)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth-path", default=str(DEFAULT_AUTH_PATH), help=f"Pi auth file path (default: {DEFAULT_AUTH_PATH})")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human summary")
    parser.add_argument("--save", action="store_true", help="Write data/latest.json")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help=f"Data directory for --save (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--no-refresh", action="store_true", help="Do not refresh expired OAuth/IDE tokens")
    parser.add_argument("--list-models", action="store_true", help="Show every available model in human output")


def add_copilot_billing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--copilot-billing-scope",
        choices=("auto", "none", "user", "org", "enterprise"),
        default=os.environ.get("QUOTAS_COPILOT_BILLING_SCOPE", "auto"),
        help="GitHub Billing API account level for Copilot AI Credits usage (default: auto). Requires QUOTAS_GITHUB_BILLING_TOKEN.",
    )
    parser.add_argument("--copilot-billing-username", default=os.environ.get("QUOTAS_COPILOT_USERNAME"), help="GitHub username for user-level AI Credits usage.")
    parser.add_argument("--copilot-billing-org", default=os.environ.get("QUOTAS_GITHUB_ORG"), help="GitHub organization for org-level AI Credits usage.")
    parser.add_argument("--copilot-billing-enterprise", default=os.environ.get("QUOTAS_GITHUB_ENTERPRISE"), help="GitHub enterprise slug for enterprise-level AI Credits usage.")
    parser.add_argument("--copilot-billing-cost-center-id", default=os.environ.get("QUOTAS_COPILOT_BILLING_COST_CENTER_ID"), help="Optional enterprise cost center ID for billing usage filtering.")
    parser.add_argument("--copilot-billing-year", type=int, default=coerce_int(os.environ.get("QUOTAS_COPILOT_BILLING_YEAR")), help="Billing usage year to query (default: current UTC year).")
    parser.add_argument("--copilot-billing-month", type=int, default=coerce_int(os.environ.get("QUOTAS_COPILOT_BILLING_MONTH")), help="Billing usage month to query (default: current UTC month).")
    parser.add_argument("--copilot-billing-day", type=int, default=coerce_int(os.environ.get("QUOTAS_COPILOT_BILLING_DAY")), help="Optional billing usage day to query.")
    parser.add_argument("--github-api-base-url", default=GITHUB_API_BASE_URL, help=f"GitHub REST API base URL for billing endpoints (default: {GITHUB_API_BASE_URL}).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check OpenAI Codex and GitHub Copilot quotas/model availability.")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Check both OpenAI Codex and GitHub Copilot")
    add_common_args(check)
    add_copilot_billing_args(check)
    check.add_argument("--codex-client-version", default=DEFAULT_CODEX_CLIENT_VERSION, help=f"Codex model catalog client version (default: {DEFAULT_CODEX_CLIENT_VERSION})")
    check.add_argument("--require-codex-model", action="append", default=[], help="Require a Codex model to appear in the catalog (repeatable)")
    check.add_argument("--require-copilot-model", action="append", default=[], help="Require a Copilot model to appear in the catalog (repeatable)")
    check.add_argument("--probe-codex", action="append", default=[], metavar="MODEL", help="Actually prompt a Codex model through Pi (repeatable; consumes quota)")
    check.add_argument("--probe-timeout", type=int, default=90, help="Seconds before a Codex probe times out")

    codex = sub.add_parser("codex", help="Check OpenAI Codex only")
    add_common_args(codex)
    codex.add_argument("--codex-client-version", default=DEFAULT_CODEX_CLIENT_VERSION, help=f"Codex model catalog client version (default: {DEFAULT_CODEX_CLIENT_VERSION})")
    codex.add_argument("--require-model", action="append", default=[], help="Require a model to appear in the Codex catalog (repeatable)")
    codex.add_argument("--probe", action="append", default=[], metavar="MODEL", help="Actually prompt a Codex model through Pi (repeatable; consumes quota)")
    codex.add_argument("--probe-timeout", type=int, default=90, help="Seconds before a Codex probe times out")

    copilot = sub.add_parser("copilot", help="Check GitHub Copilot only")
    add_common_args(copilot)
    add_copilot_billing_args(copilot)
    copilot.add_argument("--require-model", action="append", default=[], help="Require a model to appear in the Copilot catalog (repeatable)")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args or raw_args[0].startswith("-"):
        raw_args = ["check", *raw_args]
    args = parser.parse_args(raw_args)

    try:
        if args.command == "codex":
            report = build_codex_report(args)
        elif args.command == "copilot":
            report = build_copilot_report(args)
        else:
            report = build_combined_report(args)

        if args.save:
            save_report(report, Path(args.data_dir))
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_human(report, args.command, list_models=args.list_models)
        return 0 if report.get("ok") else 2
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "checked_at": iso_now(), "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
