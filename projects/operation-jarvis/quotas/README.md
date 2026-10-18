# Operation JARVIS Provider Quotas

Check remaining subscription quota for Pi's Codex, Claude and Copilot accounts, plus Codex/Copilot model availability.

The checker uses Pi's saved OAuth credentials and refreshes tokens when needed. It queries the providers' quota and model endpoints, then optionally saves a report for Pi and the native apps.

## Project files

```text
quotas.py            # CLI and provider quota/model checks
pi_session_costs.py  # Pi JSONL session cost summarizer
data/latest.json     # most recent saved quota report
README.md            # this guide
```

## What it checks

### OpenAI Codex

Uses the ChatGPT account authenticated through Pi's `openai-codex` login.

Read-only checks:

- `GET https://chatgpt.com/backend-api/wham/usage`
  - plan type
  - 5-hour Codex usage/reset tracking and its separate enforcement status
  - weekly Codex usage/reset

  - Codex credit balance when present
  - banked rate-limit reset credit count when present
- `GET https://chatgpt.com/backend-api/wham/rate-limit-reset-credits`
  - read-only list of banked Codex reset credits, status, and expiry
  - the checker does **not** redeem/consume reset credits
- `GET https://chatgpt.com/backend-api/codex/models?client_version=...`
  - Codex model catalog available to the account

The checker was adjusted for OpenAI's July 12, 2026 removal of five-hour enforcement on Plus, Pro, and Business plans. In that configuration, `primary_limit.enforced=false`. It identifies windows by duration because the seven-day window can appear in `primary_window`; use the stable `five_hour` and `weekly` fields rather than relying on upstream slot names. Set `QUOTAS_CODEX_5H_LIMIT_STATUS=active` if five-hour enforcement returns.

Optional probes send a real Pi prompt and may consume quota.

### Claude subscription

Uses Pi's `anthropic` OAuth login (not an Anthropic API billing key).

- `GET https://api.anthropic.com/api/oauth/usage`
- Overall `seven_day` and `five_hour` utilization become stable `weekly` /
  `five_hour` windows with remaining percentages and absolute reset times.
- Per-model windows, extra-usage billing and account details are deliberately excluded.
- No model calls or extra-usage changes. Expired OAuth tokens may refresh under Pi's
  existing auth-file lock; unrelated credentials are preserved. `--no-refresh`
  prevents token refresh/writes.
- Combined reports use provider key `anthropic`; `claude --json` is usage-only,
  with no catalog/probe dependency. Errors are sanitized. HTTP 429 adds only
  `rate_limited: true` and a bounded `retry_after_seconds` (or null) to the failed
  report (exit 2). Retry-After seconds/HTTP-date values are capped at one day;
  raw response bodies and headers are not included. The CLI itself makes no retry.

### GitHub Copilot

Uses the GitHub account authenticated through Pi's `github-copilot` login.

Copilot moved most plans to **GitHub AI Credits** on June 1, 2026. The checker reports `billing_model: ai_credits` when GitHub's internal quota snapshot indicates token-based billing. Legacy annual Pro/Pro+ accounts may still report premium requests until renewal.

Read-only checks:

- `GET https://api.github.com/copilot_internal/user`
  - Copilot plan/access SKU
  - billing model detection (`token_based_billing`)
  - internal allowance snapshot, still named `premium_interactions` by GitHub
  - reset date
- Optional official GitHub Billing REST API AI Credit usage, when `QUOTAS_GITHUB_BILLING_TOKEN` is set:
  - `GET /users/{username}/settings/billing/ai_credit/usage`
  - `GET /organizations/{org}/settings/billing/ai_credit/usage`
  - `GET /enterprises/{enterprise}/settings/billing/ai_credit/usage`
- `GET <Copilot API endpoint>/models`
  - full model catalog plus the manually selectable subset
  - honours `model_picker_enabled`, nested policy state, and tool-call support
  - accounts such as Student/Free that are restricted to automatic model selection may correctly report zero manually selectable models

The normal Copilot checks do not send chat/completion requests and should not consume AI Credits or legacy premium requests.

## Requirements

- Python 3.9+
- Pi credentials at `~/.pi/agent/auth.json`
- Existing Pi logins for whichever providers you want to check

No third-party Python package is required; the script uses the standard library.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Checks completed and required/probed models, if any, passed. |
| `2` | Script ran but one or more provider checks/requirements failed. |
| `1` | Unexpected runtime error or interruption. |

## Usage

From the repository root:

```bash
python3 projects/operation-jarvis/quotas/quotas.py check
```

Equivalent from this folder:

```bash
python3 quotas.py check
```

If no subcommand is provided, `check` is used by default.

### Common commands

```bash
# Check all three providers and print a human-readable summary
python3 projects/operation-jarvis/quotas/quotas.py check

# Print JSON
python3 projects/operation-jarvis/quotas/quotas.py check --json

# Save JSON to projects/operation-jarvis/quotas/data/latest.json
python3 projects/operation-jarvis/quotas/quotas.py check --json --save

# Check only OpenAI Codex
python3 projects/operation-jarvis/quotas/quotas.py codex

# Check only Claude subscription usage
python3 projects/operation-jarvis/quotas/quotas.py claude

# Check only GitHub Copilot
python3 projects/operation-jarvis/quotas/quotas.py copilot

# Check Copilot with official AI Credits usage from GitHub Billing API
# Requires QUOTAS_GITHUB_BILLING_TOKEN to be provided securely in the environment.
python3 projects/operation-jarvis/quotas/quotas.py copilot --copilot-billing-scope user

# Show all available models in human output
python3 projects/operation-jarvis/quotas/quotas.py check --list-models

# Fail if a required model is missing
python3 projects/operation-jarvis/quotas/quotas.py check --require-codex-model gpt-5.4 --require-copilot-model claude-sonnet-4.5
```

### Probe warning

These flags make a real model call through Pi and can consume quota:

```bash
python3 projects/operation-jarvis/quotas/quotas.py codex --probe gpt-5.4
python3 projects/operation-jarvis/quotas/quotas.py check --probe-codex gpt-5.4
```

Use probes only when you need to verify end-to-end model execution, not just quota/model catalog visibility.

## Configuration

Environment variables:

- `PI_AUTH_PATH`: override the Pi auth file path. Default: `~/.pi/agent/auth.json`.
- `QUOTAS_TZ`: timezone for local reset timestamps. Default: `America/New_York`.
- `QUOTAS_CODEX_5H_LIMIT_STATUS`: operational override for five-hour enforcement; currently defaults to `temporarily_suspended`. Set to `active` when OpenAI restores it.
- `CODEX_CLIENT_VERSION`: Codex model catalog client version. Default: `1.0.0`.
- `QUOTAS_GITHUB_BILLING_TOKEN`: optional GitHub token for official Copilot AI Credits billing usage. Requires billing/plan permissions for the selected account level.
- `QUOTAS_COPILOT_BILLING_SCOPE`: `auto`, `none`, `user`, `org`, or `enterprise`. Default: `auto`.
- `QUOTAS_COPILOT_USERNAME`: username for user-level billing usage. If omitted and a billing token is present, the checker calls `GET /user`.
- `QUOTAS_GITHUB_ORG`: organization for org-level billing usage.
- `QUOTAS_GITHUB_ENTERPRISE`: enterprise slug for enterprise-level billing usage.
- `QUOTAS_COPILOT_BILLING_COST_CENTER_ID`: optional enterprise cost-center filter.
- `QUOTAS_COPILOT_BILLING_YEAR`, `QUOTAS_COPILOT_BILLING_MONTH`, `QUOTAS_COPILOT_BILLING_DAY`: optional billing usage period. Defaults to the current UTC month.
- `QUOTAS_GITHUB_API_BASE_URL`: GitHub REST API base URL. Default: `https://api.github.com`.
- `QUOTAS_GITHUB_API_VERSION`: GitHub REST API version. Default: `2026-03-10`.
- `QUOTAS_COPILOT_MODELS_API_VERSION`: Copilot model-catalog API version. Default: `2026-06-01`.

CLI flags:

- `--auth-path PATH`: auth file path.
- `--data-dir DIR`: save directory for `latest.json`.
- `--no-refresh`: do not refresh expired OAuth/IDE tokens.
- `--json`: emit JSON.
- `--save`: write the latest report to disk.

## Pi session cost summary

Pi session JSONL logs include per-response usage and cost fields. From the repository root, summarize them with:

```bash
python3 projects/operation-jarvis/quotas/pi_session_costs.py --cwd "$PWD"
```

Show the highest-cost sessions too:

```bash
python3 projects/operation-jarvis/quotas/pi_session_costs.py --cwd "$PWD" --sessions --limit 20
```

Export per-session CSV:

```bash
python3 projects/operation-jarvis/quotas/pi_session_costs.py --cwd "$PWD" --csv projects/operation-jarvis/quotas/data/session-costs.csv
```

Notes:

- The script sums logged `message.usage.cost.total` values; it does not re-price tokens.
- Logged costs are model-price estimates, **not invoices or subscription charges**. In particular, Codex subscription usage must not be interpreted as an OpenAI bill.
- The GitHub AI Credits equivalent uses only `github-copilot` records and `1 AI Credit = $0.01 USD`; it remains an estimate, not the official Billing API total.
- Local providers such as `omlx`, `omlx-64`, and `omlx-voice`, including future `omlx-*` aliases, are excluded from non-local reference cost by default.
- Text, JSON, and CSV output use `reference_cost` terminology rather than the misleading `billable_cost` terminology.

## Output JSON shape

`check --json --save` writes an atomic JSON file with this high-level shape:

```json
{
  "ok": true,
  "checked_at": "YYYY-MM-DDTHH:MM:SSZ",
  "providers": {
    "openai-codex": {
      "provider": "openai-codex",
      "ok": true,
      "checked_at": "...",
      "usage": {},
      "usage_error": null,
      "models": {"models": []},
      "models_error": null,
      "required_models": {},
      "probes": []
    },
    "anthropic": {
      "provider": "anthropic",
      "ok": true,
      "checked_at": "...",
      "usage": {"weekly": {}, "five_hour": {}},
      "usage_error": null
    },
    "github-copilot": {
      "provider": "github-copilot",
      "ok": true,
      "checked_at": "...",
      "usage": {
        "billing_model": "ai_credits",
        "ai_credits": {},
        "ai_credit_billing": {},
        "legacy_premium_interactions": {}
      },
      "usage_error": null,
      "models": {"models": []},
      "models_error": null,
      "required_models": {}
    }
  }
}
```

Some fields follow the provider's response and can change. Code that reads the report should tolerate missing or new fields and use the stable `ok`, `*_error`, `usage`, `models`, and `required_models` keys where possible.

## Failure modes

- Missing/expired auth can appear as `usage_error` or `models_error`; rerun without `--no-refresh` first.
- Missing `QUOTAS_GITHUB_BILLING_TOKEN` does **not** fail Copilot checks; the checker falls back to GitHub's internal allowance snapshot and records `ai_credit_billing.available=false`.
- GitHub Billing API permission failures are captured under `usage.ai_credit_billing_error` and do not make provider model/quota checks fail.
- Network/provider HTTP failures are captured in provider error fields when the script can continue.
- Required-model misses make `ok=false` and return exit code `2`.
- Probe failures may consume quota and are reported under `probes`; avoid probes for routine dashboard refreshes.

## Local consumers

An explicit `--save` writes the report for offline consumers at:

```text
projects/operation-jarvis/quotas/data/latest.json
```

Refresh it explicitly with:

```bash
python3 projects/operation-jarvis/quotas/quotas.py check --json --save
```

`jarvisd` runs the fixed `codex --json` and `claude --json` commands independently;
it does **not** depend on `latest.json` being refreshed. Apps and Pi-desk read its
sanitized `codexQuota` / `claudeQuota` caches (Codex 60s active; Claude 120s active;
both 300s idle / 900s freshness). The backend shares a 120-second minimum across
Claude refresh requests and backs off 5/10/20/30 minutes on 429, honoring longer
valid Retry-After hints up to one day. Standalone CLI checks do not share that
in-memory backend budget.
See [provider quota integration](../docs/provider-quotas.md).

## Security notes

- `~/.pi/agent/auth.json` contains sensitive credentials. Do not commit or share it.
- `QUOTAS_GITHUB_BILLING_TOKEN` is a secret. Prefer environment injection; do not write it to files or command history.
- `data/latest.json` does not contain OAuth tokens or full Codex reset-credit IDs, but it can reveal account plan, AI Credit usage/allowance, banked reset-credit counts/expiry times, model availability, and timestamps.
