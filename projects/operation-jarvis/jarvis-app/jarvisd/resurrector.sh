#!/usr/bin/env bash
# jarvisd resurrector — keeps the app backend alive.
#
# Every 10s: curl /health on the local port. If it's down, kickstart the
# jarvisd LaunchAgent. Basic backoff: at most one restart per 30s so a
# crash-looping daemon doesn't hammer launchctl.
#
# This is a separate LaunchAgent (com.operation-jarvis.jarvisd-resurrector)
# so that stopping *other* services from the app can never strand the
# control plane.
set -u

PORT="${JARVISD_PORT:-8790}"
LABEL="com.operation-jarvis.jarvisd"
UID_NUM="$(id -u)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
INTERVAL=10
MIN_RESTART_GAP=30
LAST_RESTART=0
LOG_PREFIX="[jarvisd-resurrector]"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"
}

is_healthy() {
  curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1
}

maybe_restart() {
  local now
  now="$(date +%s)"
  if (( now - LAST_RESTART < MIN_RESTART_GAP )); then
    log "down but within ${MIN_RESTART_GAP}s backoff; skipping restart"
    return
  fi
  log "jarvisd down — kickstarting ${LABEL}"
  if launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null; then
    LAST_RESTART="$now"
    log "kickstart issued"
  else
    # Fallback: bootstrap in case it was fully unloaded.
    log "kickstart failed; trying bootstrap"
    launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null \
      && LAST_RESTART="$now"
  fi
}

log "started (port=${PORT} label=${LABEL} uid=${UID_NUM})"
while true; do
  if ! is_healthy; then
    maybe_restart
  fi
  sleep "$INTERVAL"
done
