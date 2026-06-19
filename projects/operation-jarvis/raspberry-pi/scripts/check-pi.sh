#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-pi}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/jarvis_dashboard_host}"

if [[ -z "$PI_HOST" ]]; then
  echo "Set PI_HOST to the Raspberry Pi hostname or IP." >&2
  exit 2
fi

ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$PI_USER@$PI_HOST" '
  echo "== identity =="; hostname; id; date
  echo; echo "== hardware =="; tr -d "\0" </proc/device-tree/model; echo
  echo; echo "== os =="; cat /etc/os-release
  echo; echo "== kernel =="; uname -a
  echo; echo "== firmware =="; vcgencmd version 2>/dev/null || true
  echo; echo "== disk =="; df -h
  echo; echo "== apt sources =="
  sed -n "1,200p" /etc/apt/sources.list 2>/dev/null || echo "/etc/apt/sources.list missing"
  for f in /etc/apt/sources.list.d/*.list; do echo "--- $f"; sed -n "1,200p" "$f"; done 2>/dev/null || true
  echo; echo "== upgradable with configured sources =="; apt list --upgradable 2>/dev/null || true
'
