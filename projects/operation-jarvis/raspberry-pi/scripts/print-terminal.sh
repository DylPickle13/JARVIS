#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-pi}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/jarvis_dashboard_host}"

if [[ -z "$PI_HOST" ]]; then
  echo "Set PI_HOST to the Raspberry Pi hostname or IP." >&2
  exit 2
fi
MESSAGE="${*:-this is jarvis}"
MSG_B64="$(printf '%s' "$MESSAGE" | base64 | tr -d '\n')"

ssh -i "$SSH_KEY" \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  "$PI_USER@$PI_HOST" \
  "sudo env MSG_B64='$MSG_B64' python3 -" <<'PY'
import base64
import os
import subprocess

msg = base64.b64decode(os.environ["MSG_B64"]).decode("utf-8", "replace")
subprocess.run(["/usr/bin/chvt", "1"], check=False)
subprocess.run(
    "/usr/bin/setterm -blank 0 -powerdown 0 -powersave off </dev/tty1 >/dev/tty1 2>/dev/null",
    shell=True,
    check=False,
)
with open("/dev/tty1", "wb", buffering=0) as tty:
    tty.write(("\033c\033[1;1H" + msg + "\n").encode("utf-8"))
PY
