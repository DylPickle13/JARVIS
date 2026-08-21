#!/usr/bin/env bash
# Install the canonical per-user LaunchAgent for the root JARVIS Discord bot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JARVIS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON="$JARVIS_ROOT/.venv/bin/python"
BOT="$JARVIS_ROOT/discord_bot.py"
LABEL="com.operation-jarvis.discord-bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WRITE_ONLY=0

if [[ "${1:-}" == "--write-only" ]]; then
  WRITE_ONLY=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--write-only]" >&2
  exit 2
fi

[[ -x "$PYTHON" ]] || { echo "missing virtual-environment Python: $PYTHON" >&2; exit 1; }
[[ -f "$BOT" ]] || { echo "missing Discord bot entry point: $BOT" >&2; exit 1; }
mkdir -p "$(dirname "$PLIST")" "$JARVIS_ROOT/.pi/runtime"
TMP="$(mktemp "${TMPDIR:-/tmp}/discord-bot-launchagent.XXXXXX.plist")"
trap 'rm -f "$TMP"' EXIT

python3 - "$TMP" "$LABEL" "$PYTHON" "$BOT" "$JARVIS_ROOT" <<'PY'
import plistlib
import sys
from pathlib import Path

output, label, python, bot, root = sys.argv[1:]
payload = {
    "Label": label,
    "ProgramArguments": [python, bot],
    "WorkingDirectory": root,
    "EnvironmentVariables": {
        "PATH": "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
    },
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "StandardOutPath": str(Path(root) / ".pi/runtime/discord_bot.launchd.out.log"),
    "StandardErrorPath": str(Path(root) / ".pi/runtime/discord_bot.launchd.err.log"),
}
with open(output, "wb") as handle:
    plistlib.dump(payload, handle, sort_keys=False)
PY

plutil -lint "$TMP" >/dev/null
install -m 0644 "$TMP" "$PLIST"
echo "wrote $PLIST"

if (( WRITE_ONLY )); then
  exit 0
fi

target="gui/$UID/$LABEL"
launchctl bootout "$target" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "$target"
echo "started $LABEL"
