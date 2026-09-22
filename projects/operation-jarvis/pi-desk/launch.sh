#!/bin/sh
export XKB_DEFAULT_LAYOUT=us
export COLORTERM=truecolor
# TV unavailable at startup must not stop the session.
wlr-randr --output HDMI-A-1 --mode 1920x1080 >/dev/null 2>&1 || true
exec foot --fullscreen --font='DejaVu Sans Mono:size=24,Noto Color Emoji:size=24' \
  python3 "$HOME/.local/share/pi-desk/terminal.py"
