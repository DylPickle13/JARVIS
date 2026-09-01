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
  *)
    print -u2 -- "The mobile terminal slot must be 1, 2, 3, 4, 5, or 6."
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
  if ! "$TMUX_BIN" -L "$TMUX_SOCKET" -f "$TMUX_CONFIG" \
      new-session -d -s "$TMUX_SESSION" -c "$JARVIS_ROOT" "$PI_COMMAND"; then
    # A simultaneous phone/Watch reconnect may have won the create race.
    "$TMUX_BIN" -L "$TMUX_SOCKET" has-session -t "=$TMUX_SESSION"
  fi
fi

# Reapply the checked-in profile for an already-running server so mobile wheel
# bindings take effect after an app upgrade without replacing any Pi process.
"$TMUX_BIN" -L "$TMUX_SOCKET" source-file "$TMUX_CONFIG"
# Never issue resize-window/resize-pane. Clear any historical per-window manual
# override and retain latest-client sizing independently for this slot.
"$TMUX_BIN" -L "$TMUX_SOCKET" set-option -w -t "=$TMUX_SESSION:0" window-size latest

# terminald eagerly ensures all six slots without attaching a second client or
# changing the dimensions retained by an existing iPhone PTY.
if [[ "$ensure_only" == "1" ]]; then
  exit 0
fi

exec "$TMUX_BIN" -L "$TMUX_SOCKET" attach-session -t "=$TMUX_SESSION"
