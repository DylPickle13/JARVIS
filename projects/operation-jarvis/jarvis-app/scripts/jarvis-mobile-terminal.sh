#!/bin/zsh
set -eu

readonly TMUX_BIN="/opt/homebrew/bin/tmux"
readonly TMUX_SOCKET="jarvis-mobile"
readonly TMUX_SESSION="jarvis-ios"
readonly TMUX_CONFIG="/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/config/jarvis-mobile.tmux.conf"
readonly JARVIS_ROOT="/Users/dylanrapanan/JARVIS"
readonly PI_COMMAND='/opt/homebrew/bin/pi --tui-mode regular'

# Remote OpenSSH commands receive a minimal macOS PATH. Pi's absolute launcher
# still uses `#!/usr/bin/env node`, so make Homebrew's Node resolvable inside the
# detached tmux server and every session it creates.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Create the host-side session while detached, then attach this SSH PTY to it.
# Keeping creation separate from attachment lets a fresh session survive a
# short-lived SSH client and reliably recreates it after Pi's /quit command.
if ! "$TMUX_BIN" -L "$TMUX_SOCKET" has-session -t "=$TMUX_SESSION" 2>/dev/null; then
  if ! "$TMUX_BIN" -L "$TMUX_SOCKET" -f "$TMUX_CONFIG" \
      new-session -d -s "$TMUX_SESSION" -c "$JARVIS_ROOT" "$PI_COMMAND"; then
    # A simultaneous reconnect may have won the create race.
    "$TMUX_BIN" -L "$TMUX_SOCKET" has-session -t "=$TMUX_SESSION"
  fi
fi

# Reapply the checked-in profile for an already-running server so one-line
# wheel fallback bindings take effect after an app upgrade without replacing
# the persistent Pi process.
"$TMUX_BIN" -L "$TMUX_SOCKET" source-file "$TMUX_CONFIG"

# The Watch HTTPS bridge needs to create/recreate the persistent pane without
# attaching a second terminal client or changing the iPhone's tmux dimensions.
if [[ "${1:-}" == "--ensure-only" ]]; then
  exit 0
fi

exec "$TMUX_BIN" -L "$TMUX_SOCKET" attach-session -t "=$TMUX_SESSION"
