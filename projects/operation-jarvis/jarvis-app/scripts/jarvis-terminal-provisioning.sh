#!/usr/bin/env bash
set -euo pipefail

readonly APP_ROOT="/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app"
host="${1:-}"
if [[ -z "$host" ]]; then
  default_interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
  if [[ -n "$default_interface" ]]; then
    host="$(ipconfig getifaddr "$default_interface" 2>/dev/null || true)"
  fi
fi
if [[ -z "$host" ]]; then
  for interface in en0 en1; do
    host="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
    [[ -n "$host" ]] && break
  done
fi
if [[ -z "$host" ]]; then
  echo 'Could not determine the Mac LAN address; pass a hostname or IP.' >&2
  exit 1
fi

printf 'Private Watch terminal setup code for https://%s:8792:\n' "$host" >&2
exec /usr/bin/python3 "$APP_ROOT/terminald/jarvis_terminald.py" --print-provisioning "$host"
