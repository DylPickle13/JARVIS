#!/bin/zsh
set -eu

readonly TMUX_BIN="/opt/homebrew/bin/tmux"
readonly TMUX_SOCKET="jarvis-mobile"
readonly TMUX_CONFIG="/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/config/jarvis-mobile.tmux.conf"
readonly JARVIS_ROOT="/Users/dylanrapanan/JARVIS"
readonly PI_COMMAND='/opt/homebrew/bin/pi --tui-mode regular'

slot="1"
slot_was_set="0"
ensure_only="0"
while (( $# > 0 )); do
  case "$1" in
    --slot)
      [[ "$slot_was_set" == "0" && $# -ge 2 ]] || {
        print -u2 -- "A mobile terminal slot must be supplied exactly once."
        exit 64
      }
      slot="$2"
      slot_was_set="1"
      shift 2
      ;;
    --ensure-only)
      [[ "$ensure_only" == "0" ]] || {
        print -u2 -- "--ensure-only may be supplied only once."
        exit 64
      }
      ensure_only="1"
      shift
      ;;
    *)
      print -u2 -- "Unsupported mobile terminal argument."
      exit 64
      ;;
  esac
done

case "$slot" in
  1)
    readonly TMUX_SESSION="jarvis-ios"
    ;;
  2)
    readonly TMUX_SESSION="jarvis-ios-2"
    ;;
  3)
    readonly TMUX_SESSION="jarvis-ios-3"
    ;;
  4)
    readonly TMUX_SESSION="jarvis-ios-4"
    ;;
  5)
    readonly TMUX_SESSION="jarvis-ios-5"
    ;;
  6)
    readonly TMUX_SESSION="jarvis-ios-6"
    ;;
  7)
    readonly TMUX_SESSION="jarvis-ios-7"
    ;;
  8)
    readonly TMUX_SESSION="jarvis-ios-8"
    ;;
  9)
    readonly TMUX_SESSION="jarvis-ios-9"
    ;;
  10)
    readonly TMUX_SESSION="jarvis-ios-10"
    # Dedicated room ownership is provisioned on the host, never allocated by a phone reconnect.
    "$TMUX_BIN" -L "$TMUX_SOCKET" has-session -t "=$TMUX_SESSION" 2>/dev/null || {
      print -u2 -- "Room Audio Session 10 is offline; host setup is required."
      exit 69
    }
    ;;
  *)
    print -u2 -- "The mobile terminal slot must be an integer from 1 through 10."
    exit 64
    ;;
esac

# Remote OpenSSH commands receive a minimal macOS PATH. Pi's absolute launcher
# still uses `#!/usr/bin/env node`, so make Homebrew's Node resolvable inside the
# detached tmux server and every session it creates.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Each fixed slot owns one persistent tmux session and one Pi process. Creation
# remains detached so a short-lived SSH or Watch client can never own process
# lifetime. The exact target allowlist above prevents client-controlled tmux
# command construction.
if ! "$TMUX_BIN" -L "$TMUX_SOCKET" has-session -t "=$TMUX_SESSION" 2>/dev/null; then
  # Share the restart lock: a reconnect must not allocate a fresh slot while
  # maintenance is recreating that slot with its explicit session path.
  /usr/bin/python3 - "$JARVIS_ROOT" "$TMUX_BIN" "$TMUX_SOCKET" "$TMUX_CONFIG" "$TMUX_SESSION" "$PI_COMMAND" <<'PY'
import fcntl
from pathlib import Path
import subprocess
import sys
root, tmux, socket, config, session, command = sys.argv[1:]
path = Path(root) / ".pi/runtime/jarvis-mobile-vscode-restart.lock"
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a+") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Pi maintenance is running; reconnect shortly.")
    base = [tmux, "-L", socket]
    if subprocess.run(base + ["has-session", "-t", "=" + session],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(base + ["-f", config, "new-session", "-d", "-s", session,
                              "-c", root, command], check=True)
PY
fi

# Reapply the checked-in profile for an already-running server so mobile wheel
# bindings take effect after an app upgrade without replacing any Pi process.
"$TMUX_BIN" -L "$TMUX_SOCKET" source-file "$TMUX_CONFIG"
# Never issue resize-window/resize-pane. Clear any historical per-window manual
# override and retain latest-client sizing independently for this slot.
"$TMUX_BIN" -L "$TMUX_SOCKET" set-option -w -t "=$TMUX_SESSION:0" window-size latest

# terminald eagerly ensures all nine slots without attaching a second client or
# changing the dimensions retained by an existing iPhone PTY.
if [[ "$ensure_only" == "1" ]]; then
  exit 0
fi

exec "$TMUX_BIN" -L "$TMUX_SOCKET" attach-session -t "=$TMUX_SESSION"
