#!/usr/bin/env bash
# Provision only the new Mac endpoint. Does not start/restart either endpoint.
set -euo pipefail
umask 077
[[ "$(uname -s)" == Darwin ]] || { echo 'macOS required' >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
ROOM="$ROOT/projects/operation-jarvis/room-audio"
STATE="$HOME/Library/Application Support/JARVIS/room-audio-mac"
command -v uv >/dev/null || { echo 'Install uv first' >&2; exit 1; }
[[ -x "$ROOT/.venv/bin/python" ]] || { echo 'Existing JARVIS server venv required' >&2; exit 1; }
mkdir -p "$STATE"
chmod 700 "$STATE"
if [[ ! -x "$STATE/.venv/bin/python" ]]; then
  uv venv --python 3.13 "$STATE/.venv"
fi
uv pip install --python "$STATE/.venv/bin/python" -r "$ROOM/requirements-macos.txt"
"$STATE/.venv/bin/python" - <<'PY'
from openwakeword.utils import download_models
download_models(model_names=['hey_jarvis'])
PY
"$ROOT/.venv/bin/python" "$ROOM/macos_room_audio_service.py" configure "$@"
