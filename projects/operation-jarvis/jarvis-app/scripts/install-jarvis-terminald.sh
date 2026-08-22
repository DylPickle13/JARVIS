#!/usr/bin/env bash
set -euo pipefail

readonly APP_ROOT="/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app"
readonly SOURCE_PLIST="$APP_ROOT/terminald/launchd/com.operation-jarvis.jarvis-terminald.plist"
readonly TARGET_PLIST="$HOME/Library/LaunchAgents/com.operation-jarvis.jarvis-terminald.plist"
readonly DOMAIN="gui/$(id -u)"
readonly LABEL="com.operation-jarvis.jarvis-terminald"

mkdir -p "$HOME/Library/LaunchAgents" "$APP_ROOT/terminald/logs"
chmod 700 "$APP_ROOT/terminald/jarvis_terminald.py"
cp "$SOURCE_PLIST" "$TARGET_PLIST"
plutil -lint "$TARGET_PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET_PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL"
printf 'jarvis-terminald installed on TCP 8792\n'
printf 'Run scripts/jarvis-terminal-provisioning.sh and paste its private output into iPhone JARVIS Settings.\n'
