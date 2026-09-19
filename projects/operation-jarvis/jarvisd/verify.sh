#!/usr/bin/env bash
# Backend-only verification: no Xcode, live configuration, or hardware access.
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
TEST_RUNTIME="$(mktemp -d "${TMPDIR:-/tmp}/jarvisd-verify.XXXXXX")"
trap 'rm -rf "$TEST_RUNTIME"' EXIT
mkdir -p "$TEST_RUNTIME/project"

# Keep tests away from live configuration and explicit persistence setup, even
# when run directly in the operational checkout. Core imports perform no I/O.
export JARVISD_PROJECT_ROOT="$TEST_RUNTIME/project"
export JARVISD_JARVIS_ROOT="$TEST_RUNTIME/project"
export JARVISD_EVENTS_FILE="$TEST_RUNTIME/events.jsonl"
export JARVISD_LOG_FILE="$TEST_RUNTIME/jarvisd.log"
export JARVISD_SERVICES_FILE="$PWD/services.json"
export PYTHONDONTWRITEBYTECODE=1
"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" - <<'PY'
from pathlib import Path
import os
import plistlib
for path in [*Path('.').glob('*.py'), *Path('jarvisd_core').glob('*.py'),
             *Path('tests').glob('*.py'), *Path('tests_sdk').glob('*.py')]:
    compile(path.read_bytes(), str(path), 'exec')
vendor_root = Path(os.environ.get('JARVIS_TEST_VENDOR_ROOT', '..'))
for entry in ('jarvis.py', 'control-cli.py'):
    path = vendor_root / entry
    compile(path.read_bytes(), str(path), 'exec')
for name in ('smart-plug/smart_plug/kasa_client.py', 'smart-plug/smart_plug/cli.py',
             'air-purifier/air_purifier/vesync_client.py', 'air-purifier/air_purifier/cli.py',
             'air-purifier/air_purifier/write_safety.py'):
    path = vendor_root / name
    compile(path.read_bytes(), str(path), 'exec')
for path in Path('launchd').glob('*.plist'):
    plistlib.loads(path.read_bytes())
print('Python syntax and LaunchAgent plists: OK')
PY
bash -n resurrector.sh
bash -n verify.sh
bash -n verify-kasa-sdk.sh
bash -n verify-vesync-sdk.sh
bash -n verify-delegation-sdk.sh
