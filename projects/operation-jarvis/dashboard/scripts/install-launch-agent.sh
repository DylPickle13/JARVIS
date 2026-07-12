#!/usr/bin/env bash
set -euo pipefail

LABEL="com.operation-jarvis.dashboard"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JARVIS_ROOT="$(cd "$ROOT/../../.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
NODE_BIN="$(command -v node || true)"
ENV_FILE="${JARVIS_DASHBOARD_ENV_FILE:-$JARVIS_ROOT/.env}"
PORT="${PORT:-8787}"
HOST="${HOST:-0.0.0.0}"

if [[ -z "$NODE_BIN" ]]; then
  echo "Node.js was not found on PATH. Install Node.js first, then rerun this script." >&2
  exit 1
fi

xml_escape() {
  printf '%s' "$1" | LC_ALL=C sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\&apos;/g"
}

XML_LABEL="$(xml_escape "$LABEL")"
XML_NODE_BIN="$(xml_escape "$NODE_BIN")"
XML_ROOT="$(xml_escape "$ROOT")"
XML_ENV_FILE="$(xml_escape "$ENV_FILE")"
XML_HOST="$(xml_escape "$HOST")"
XML_PORT="$(xml_escape "$PORT")"

ENV_FILE_ARGUMENT=""
if [[ -f "$ENV_FILE" ]]; then
  if ! "$NODE_BIN" --help 2>&1 | grep -q -- '--env-file='; then
    echo "Node.js $($NODE_BIN --version) does not support --env-file. Upgrade Node.js before installing the dashboard service." >&2
    exit 1
  fi
  ENV_FILE_ARGUMENT="    <string>--env-file=$XML_ENV_FILE</string>"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$XML_LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$XML_NODE_BIN</string>
$ENV_FILE_ARGUMENT
    <string>$XML_ROOT/src/server.mjs</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$XML_ROOT</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>HOST</key>
    <string>$XML_HOST</string>
    <key>PORT</key>
    <string>$XML_PORT</string>
    <key>NODE_ENV</key>
    <string>production</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>StandardOutPath</key>
  <string>$XML_ROOT/logs/launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>$XML_ROOT/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST" >/dev/null

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed and started $LABEL"
echo "Plist: $PLIST"
if [[ -n "$ENV_FILE_ARGUMENT" ]]; then
  echo "Environment: $ENV_FILE"
else
  echo "Environment: none ($ENV_FILE was not found)"
fi
echo
PORT="$PORT" "$NODE_BIN" "$ROOT/scripts/lan-url.mjs"
