#!/bin/sh
# Compatibility entry point for existing display panes.
exec python3 "$(dirname "$0")/connect.py" "$@"
