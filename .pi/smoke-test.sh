#!/usr/bin/env bash
# Read-only local smoke test for JARVIS/Pi wiring.
# This script deliberately avoids starting services, calling LLMs, posting to Discord,
# launching browsers, touching hardware, contacting dashboard/oMLX/Google/Spotify/Cast,
# or opening SQLite databases in ways that could create/migrate them.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

export PYTHONDONTWRITEBYTECODE=1
export JARVIS_DASHBOARD_EMIT_EVENTS=0
export JARVIS_DASHBOARD_AUTO_EVENTS=0

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

section() {
  printf '\n== %s ==\n' "$1"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '✅ PASS  %s\n' "$1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf '⚠️  WARN  %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '❌ FAIL  %s\n' "$1"
}

info() {
  printf 'ℹ️  %s\n' "$1"
}

indent() {
  sed 's/^/    /'
}

require_file() {
  local label="$1"
  local path="$2"
  if [[ -e "$path" ]]; then
    pass "$label ($path)"
  else
    fail "$label missing ($path)"
  fi
}

file_mode() {
  local path="$1"
  stat -f '%Lp' "$path" 2>/dev/null || stat -c '%a' "$path" 2>/dev/null
}

require_mode() {
  local label="$1"
  local path="$2"
  local expected="$3"
  if [[ ! -e "$path" ]]; then
    fail "$label missing ($path)"
    return
  fi
  local actual
  actual="$(file_mode "$path")"
  if [[ "$actual" == "$expected" ]]; then
    pass "$label mode=$actual ($path)"
  else
    fail "$label expected mode=$expected, got ${actual:-unknown} ($path)"
  fi
}

warn_file() {
  local label="$1"
  local path="$2"
  if [[ -e "$path" ]]; then
    pass "$label ($path)"
  else
    warn "$label missing ($path)"
  fi
}

require_executable() {
  local label="$1"
  local path="$2"
  if [[ -x "$path" ]]; then
    pass "$label ($path)"
  elif [[ -e "$path" ]]; then
    fail "$label exists but is not executable ($path)"
  else
    fail "$label missing ($path)"
  fi
}

warn_executable() {
  local label="$1"
  local path="$2"
  if [[ -x "$path" ]]; then
    pass "$label ($path)"
  elif [[ -e "$path" ]]; then
    warn "$label exists but is not executable ($path)"
  else
    warn "$label missing ($path)"
  fi
}

require_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "command available: $command_name ($(command -v "$command_name"))"
  else
    fail "command missing: $command_name"
  fi
}

warn_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "command available: $command_name ($(command -v "$command_name"))"
  else
    warn "command missing: $command_name"
  fi
}

warn_command_or_executable() {
  local command_name="$1"
  local fallback_path="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "command available: $command_name ($(command -v "$command_name"))"
  elif [[ -x "$fallback_path" ]]; then
    pass "command available via local package: $command_name ($fallback_path)"
  else
    warn "command missing: $command_name (also missing $fallback_path)"
  fi
}

run_check() {
  local label="$1"
  shift
  local output
  if output="$($@ 2>&1)"; then
    pass "$label"
  else
    fail "$label"
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output" | tail -40 | indent
    fi
  fi
}

run_warn_check() {
  local label="$1"
  shift
  local output
  if output="$($@ 2>&1)"; then
    pass "$label"
  else
    warn "$label"
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output" | tail -20 | indent
    fi
  fi
}

PYTHON_BIN=""
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi

section "Safety policy"
info "Read-only local checks only. This script will not start JARVIS, call an LLM, post to Discord, launch Chrome, touch the phone, control Cast/Spotify/Kasa, or contact dashboard/oMLX/Google APIs."
info "SQLite status commands are intentionally not run here because some runners create/init databases on first connect."

section "Repository files"
require_file "root README" "readme.md"
require_file "env template" ".env.example"
require_file "root requirements" "requirements.txt"
require_file "Pi settings" ".pi/settings.json"
require_file "Pi settings template" ".pi/settings.example.json"
require_file "local context template" ".pi/APPEND_SYSTEM.example.md"
require_file "SSH hosts template" ".pi/ssh-hosts.example.json"
require_file "Pi extension docs" ".pi/docs/PI_EXTENSIONS.md"
require_file "rebuild runbook" ".pi/docs/REBUILD_FROM_SCRATCH.md"
require_file "lazy tools extension" ".pi/extensions/99-lazy-tools.ts"
require_file "provider payload slimming extension" ".pi/extensions/98-slim-provider-payload.ts"
require_executable "smoke test script" ".pi/smoke-test.sh"

section "Private local permissions"
require_mode "project secrets" ".env" "600"
require_mode "Pi settings" ".pi/settings.json" "600"
require_mode "local system context" ".pi/APPEND_SYSTEM.md" "600"
require_mode "SSH host allowlist" ".pi/ssh-hosts.json" "600"
for directory in .pi/runtime .pi/memory .pi/session-search .pi/discord-cron; do
  require_mode "private directory" "$directory" "700"
done
while IFS= read -r path; do
  require_mode "private runtime file" "$path" "600"
done < <(find .pi .pi/memory .pi/session-search .pi/discord-cron -maxdepth 1 -type f \
  \( -name '*.sqlite' -o -name '*.sqlite-wal' -o -name '*.sqlite-shm' -o -name '*.sqlite-journal' \
     -o -name '*.sqlite.lock' -o -name 'deleted-sessions-*.json' \) -print 2>/dev/null)
if [[ -d .pi/runtime/pi-web-access ]]; then
  require_mode "scoped web-access directory" ".pi/runtime/pi-web-access" "700"
fi
if [[ -e .pi/runtime/pi-web-access/web-search.json ]]; then
  require_mode "scoped web-access config" ".pi/runtime/pi-web-access/web-search.json" "600"
fi

section "Core commands"
require_command "pi"
require_command "node"
require_command "npm"
require_command "ffmpeg"
warn_command "pdftotext"
warn_command "trash"
warn_command "gws"

if [[ -n "$PYTHON_BIN" ]]; then
  pass "Python available: $PYTHON_BIN"
  run_check "Python version" "$PYTHON_BIN" --version
else
  fail "Python missing: expected .venv/bin/python or python3"
fi

if command -v pi >/dev/null 2>&1; then
  run_check "Pi version" pi --version
  run_check "Pi project package list" pi list
fi
if command -v node >/dev/null 2>&1; then
  run_check "Node version" node --version
fi
if command -v npm >/dev/null 2>&1; then
  run_check "npm version" npm --version
fi
if command -v ffmpeg >/dev/null 2>&1; then
  run_check "ffmpeg version" ffmpeg -version
fi
if command -v pdftotext >/dev/null 2>&1; then
  run_check "pdftotext version" pdftotext -v
fi

section "Local package/install presence"
warn_file "project .env" ".env"
require_file "pi-web-access package" ".pi/npm/node_modules/pi-web-access/package.json"
require_file "browser extension package" ".pi/extensions/50-browser/package.json"
require_file "browser extension package lock" ".pi/extensions/50-browser/package-lock.json"
require_file "browser extension node_modules" ".pi/extensions/50-browser/node_modules"
require_file "shared extension runtime package" ".pi/extensions/lib/package.json"
require_file "shared extension runtime package lock" ".pi/extensions/lib/package-lock.json"
require_file "SSH PTY dependency" ".pi/extensions/lib/node_modules/node-pty/package.json"
require_file "headless terminal dependency" ".pi/extensions/lib/node_modules/@xterm/headless/package.json"
require_file "SSH PTY helper" ".pi/extensions/lib/ssh-pty.ts"
warn_file "dashboard package.json" "projects/operation-jarvis/dashboard/package.json"
warn_file "dashboard node_modules" "projects/operation-jarvis/dashboard/node_modules"
warn_executable "Operation JARVIS venv Python" "projects/operation-jarvis/.venv/bin/python"
warn_executable "smart-plug venv Python" "projects/operation-jarvis/smart-plug/.venv/bin/python"
warn_file "Google Chrome app" "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if command -v node >/dev/null 2>&1; then
  run_check "Read local Pi package versions and verify web-access pin" node - <<'NODE'
const fs = require('fs');
const expectedWebAccess = '0.13.0';
const installedWebAccess = JSON.parse(fs.readFileSync('.pi/npm/node_modules/pi-web-access/package.json', 'utf8'));
const localSettings = JSON.parse(fs.readFileSync('.pi/settings.json', 'utf8'));
const settingsTemplate = JSON.parse(fs.readFileSync('.pi/settings.example.json', 'utf8'));
for (const [label, settings] of [['local settings', localSettings], ['settings template', settingsTemplate]]) {
  const webAccess = settings.packages?.find?.((entry) => entry?.source === `npm:pi-web-access@${expectedWebAccess}`);
  if (!webAccess) throw new Error(`${label} does not pin pi-web-access@${expectedWebAccess}`);
  if (!Array.isArray(webAccess.extensions) || webAccess.extensions.length !== 0) {
    throw new Error(`${label} must disable direct pi-web-access extension autoload`);
  }
}
if (installedWebAccess.version !== expectedWebAccess) {
  throw new Error(`installed pi-web-access is ${installedWebAccess.version}, expected ${expectedWebAccess}`);
}
for (const path of [
  '.pi/npm/node_modules/pi-web-access/package.json',
  '.pi/extensions/50-browser/package.json',
  '.pi/extensions/lib/package.json',
  '.pi/extensions/lib/node_modules/node-pty/package.json',
  '.pi/extensions/lib/node_modules/@xterm/headless/package.json',
]) {
  const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
  console.log(`${pkg.name}@${pkg.version}`);
}
NODE
fi

section "Extension inventory"
expected_extension_roots=(
  .pi/extensions/00-private-permissions.ts
  .pi/extensions/00-web-access-env.ts
  .pi/extensions/01-omlx-provider-setup-and-recovery.ts
  .pi/extensions/04-delete-current-session.ts
  .pi/extensions/10-discord-cron.ts
  .pi/extensions/15-discord-send-file.ts
  .pi/extensions/16-discord-ping.ts
  .pi/extensions/20-session-search.ts
  .pi/extensions/30-google-access.ts
  .pi/extensions/34-maps.ts
  .pi/extensions/35-memory.ts
  .pi/extensions/42-scheduled-prompts.ts
  .pi/extensions/45-jarvis.ts
  .pi/extensions/46-local-pi-session-status.ts
  .pi/extensions/48-agent-phone.ts
  .pi/extensions/50-browser
  .pi/extensions/50-minecraft-jarvis-chat.ts
  .pi/extensions/55-ssh-exec.ts
  .pi/extensions/56-github-cli.ts
  .pi/extensions/58-reaper-bridge.ts
  .pi/extensions/60-pdf-read-result.ts
  .pi/extensions/70-image-generation.ts
  .pi/extensions/71-video-generation.ts
  .pi/extensions/98-slim-provider-payload.ts
  .pi/extensions/99-lazy-tools.ts
  .pi/extensions/xhigh-thinking-on-model-select.ts
)
for path in "${expected_extension_roots[@]}"; do
  require_file "extension root" "$path"
done

expected_extension_files=(
  .pi/extensions/50-browser/chrome-bridge-daemon.mjs
  .pi/extensions/50-browser/daemon-browser-manager.ts
  .pi/extensions/50-browser/index.ts
  .pi/extensions/50-browser/package-lock.json
  .pi/extensions/50-browser/package.json
  .pi/extensions/50-browser/tools.ts
  .pi/extensions/lib/package-lock.json
  .pi/extensions/lib/package.json
  .pi/extensions/lib/ssh-pty.ts
)
for path in "${expected_extension_files[@]}"; do
  require_file "extension source" "$path"
done

expected_extension_roots_sorted="$(printf '%s\n' "${expected_extension_roots[@]}" | sort)"
actual_extension_roots_sorted="$(find .pi/extensions -maxdepth 1 \( \( -type f -name '*.ts' \) -o -type d \) ! -path .pi/extensions ! -name lib | sort)"
if [[ "$actual_extension_roots_sorted" == "$expected_extension_roots_sorted" ]]; then
  pass "extension root inventory matches smoke-test manifest"
else
  fail "extension root inventory differs from smoke-test manifest"
  diff -u <(printf '%s\n' "$expected_extension_roots_sorted") <(printf '%s\n' "$actual_extension_roots_sorted") 2>&1 | indent
fi

section "CLI import/help checks"
if [[ -n "$PYTHON_BIN" ]]; then
  run_check "Root Python direct dependency import check" env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - <<'PY'
import audioop  # noqa: F401
import davey  # noqa: F401
import discord  # noqa: F401
from discord.ext import voice_recv  # noqa: F401
from huggingface_hub import hf_hub_download  # noqa: F401
import nacl  # noqa: F401
import numpy  # noqa: F401
import onnxruntime  # noqa: F401
import openwakeword  # noqa: F401
from piper import PiperVoice, SynthesisConfig  # noqa: F401
import requests  # noqa: F401
print('root direct runtime imports ok')
PY
  run_check "memory CLI help" env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" .pi/memory/memory.py --help
  run_check "session-search CLI help" env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" .pi/session-search/session_search.py --help
  run_check "discord-cron CLI help" env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" .pi/discord-cron/runner.py --help
fi
run_check "Operation JARVIS CLI help" env PYTHONDONTWRITEBYTECODE=1 JARVIS_DASHBOARD_EMIT_EVENTS=0 JARVIS_DASHBOARD_AUTO_EVENTS=0 projects/operation-jarvis/jarvis-cli --help
run_check "agent-phone CLI help" env PYTHONDONTWRITEBYTECODE=1 projects/phone/agent-phone --help

section "Runtime data presence only"
warn_file "memory DB present" ".pi/memory/memory.sqlite"
warn_file "session-search index present" ".pi/session-search/index.sqlite"
warn_file "discord-cron DB present" ".pi/discord-cron/discord-cron.sqlite"
warn_file "Pi sessions directory present" "$HOME/.pi/agent/sessions/--Users-gemma-JARVIS--"

section "Env key audit (names only, values never printed)"
if [[ -n "$PYTHON_BIN" ]]; then
  env_output="$(env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import re

def parse(path: Path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = bool(value)
    return values

example = parse(Path('.env.example'))
actual = parse(Path('.env'))
required = ['DISCORD_BOT_TOKEN']
missing_required = [key for key in required if not actual.get(key)]
set_count = sum(1 for key in example if actual.get(key))
print(f'.env.example keys: {len(example)}')
print(f'.env keys set from template: {set_count}/{len(example)}')
if missing_required:
    print('missing required key names: ' + ', '.join(missing_required))
    raise SystemExit(2)
if not Path('.env').exists():
    print('.env is missing')
    raise SystemExit(3)
PY
)"
  env_status=$?
  if [[ $env_status -eq 0 ]]; then
    pass ".env key audit"
  elif [[ $env_status -eq 2 || $env_status -eq 3 ]]; then
    warn ".env key audit"
  else
    fail ".env key audit"
  fi
  printf '%s\n' "$env_output" | indent
else
  warn "skipped env key audit because Python is unavailable"
fi

section "Docs link audit"
if [[ -n "$PYTHON_BIN" ]]; then
  run_check "relative Markdown links resolve" env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import re
files = [Path('readme.md'), *Path('.pi/docs').glob('*.md')]
missing = []
for file in files:
    text = file.read_text(encoding='utf-8')
    for match in re.finditer(r'\[[^\]]+\]\(([^)]+)\)', text):
        target = match.group(1).split('#', 1)[0]
        if not target or '://' in target or target.startswith(('mailto:', '/', '#')):
            continue
        path = (file.parent / target).resolve()
        if not path.exists():
            missing.append(f'{file}: {target}')
if missing:
    print('\n'.join(missing))
    raise SystemExit(1)
print('relative Markdown links ok')
PY
fi

section "Skipped by design"
info "No Discord API calls, no discord_bot.py startup, no dashboard HTTP requests, no oMLX requests, no web/Google/YouTube calls, no Chrome launch, no phone/ADB commands, no Cast/Spotify/Kasa commands."
info "For deeper subsystem testing, follow .pi/docs/REBUILD_FROM_SCRATCH.md and run only the specific checks you intend."

section "Summary"
printf 'PASS=%d WARN=%d FAIL=%d\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
exit 0
