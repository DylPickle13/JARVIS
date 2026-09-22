#!/usr/bin/env bash
# launchd handles crashes; this watchdog handles sustained HTTP unavailability.
# A single slow check must not kill in-flight work. Deployment stops this agent
# before quiescing jarvisd. Never interpret device/integration failures as liveness.
set -u

PORT="${JARVISD_PORT:-8790}"
LABEL="com.operation-jarvis.jarvisd"
UID_NUM="$(id -u)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
INTERVAL=10
MIN_RESTART_GAP=30
MIN_FAILURE_SECONDS=20
MIN_FAILURES=3
LAST_ATTEMPT=-30
FIRST_FAILURE=-1
FAILURES=0
LOG_PREFIX="[jarvisd-resurrector]"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_PREFIX $*"; }
is_healthy() { curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; }

maybe_restart() {
  local now="$1"
  if (( now - LAST_ATTEMPT < MIN_RESTART_GAP )); then
    return
  fi
  # Back off every attempt, including failed kickstart/bootstrap operations.
  LAST_ATTEMPT="$now"
  log "sustained liveness failure — kickstarting ${LABEL}"
  if ! launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" 2>/dev/null; then
    log "kickstart failed; trying bootstrap"
    launchctl bootstrap "gui/${UID_NUM}" "$PLIST" 2>/dev/null || true
  fi
}

check_once() {
  local now="${1:-$SECONDS}"
  if is_healthy; then
    FAILURES=0
    FIRST_FAILURE=-1
    return
  fi
  if (( FIRST_FAILURE < 0 )); then FIRST_FAILURE="$now"; fi
  FAILURES=$((FAILURES + 1))
  if (( FAILURES >= MIN_FAILURES && now - FIRST_FAILURE >= MIN_FAILURE_SECONDS )); then
    maybe_restart "$now"
  fi
}

main() {
  log "started (port=${PORT} label=${LABEL})"
  while true; do
    check_once
    sleep "$INTERVAL"
  done
}

# Sourceable by offline tests; importing never probes or restarts a service.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main; fi
