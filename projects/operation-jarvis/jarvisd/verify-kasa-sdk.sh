#!/usr/bin/env bash
# Real installed SDK + synthetic loopback peers only. No discovery/devices/config.
set -euo pipefail
cd "$(dirname "$0")"
KASA_PYTHON="${JARVIS_TEST_KASA_PYTHON:-../smart-plug/.venv/bin/python}"
if [[ ! -x "$KASA_PYTHON" ]]; then
  echo 'Existing Kasa interpreter required; no dependencies will be installed.' >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
"$KASA_PYTHON" -I -B tests_sdk/test_kasa_no_replay.py
