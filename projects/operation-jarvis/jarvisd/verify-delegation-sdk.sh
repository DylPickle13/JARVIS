#!/usr/bin/env bash
# Uninstalled mandatory fences + existing SDKs + synthetic loopback peers only.
set -euo pipefail
cd "$(dirname "$0")"
SOURCE="${JARVIS_TEST_VENDOR_ROOT:-$(cd .. && pwd)}"
KASA="${JARVIS_TEST_KASA_PYTHON:-$SOURCE/smart-plug/.venv/bin/python}"
VESYNC="${JARVIS_TEST_VESYNC_PYTHON:-$SOURCE/air-purifier/.venv/bin/python}"
[[ -x "$KASA" && -x "$VESYNC" ]] || { echo 'Existing SDK interpreters required; no installation.' >&2; exit 1; }
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/jarvisd-fenced-sdk.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
"$KASA" -I -B stage-fenced-vendors.py "$SOURCE" "$STAGE/vendor" > "$STAGE/manifest.json"
JARVIS_TEST_VENDOR_ROOT="$STAGE/vendor" "$KASA" -I -B tests_sdk/test_delegation_fences.py kasa
JARVIS_TEST_VENDOR_ROOT="$STAGE/vendor" "$VESYNC" -I -B tests_sdk/test_delegation_fences.py vesync
