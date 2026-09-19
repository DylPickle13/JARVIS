#!/usr/bin/env bash
# Actual VeSync SDK, synthetic loopback peers only; no cloud/config/device access.
set -euo pipefail
cd "$(dirname "$0")"
VESYNC_PYTHON="${JARVIS_TEST_VESYNC_PYTHON:-../air-purifier/.venv/bin/python}"
if [[ ! -x "$VESYNC_PYTHON" ]]; then
  echo 'Existing VeSync interpreter required; no dependencies will be installed.' >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
"$VESYNC_PYTHON" -I -B tests_sdk/test_vesync_no_replay.py
