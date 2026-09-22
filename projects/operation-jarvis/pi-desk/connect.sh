#!/bin/bash
# This is only a local display client. Never kill/restart/detach other Mac clients.
case "$1" in
  1) target=jarvis-ios ;;
  2|3|4|5|6|7|8|9|10) target=jarvis-ios-$1 ;;
  *) exit 2 ;;
esac
trap 'exit 0' INT TERM
while true; do
  ssh -t -o BatchMode=yes -o ConnectTimeout=5 \
    -o ServerAliveInterval=5 -o ServerAliveCountMax=2 mac-mini-64 \
    "/opt/homebrew/bin/tmux -L jarvis-mobile attach-session -f ignore-size -t '=$target'"
  printf '\nConnection closed. Reconnecting session %s in 3 seconds…\n' "$1"
  sleep 3
done
