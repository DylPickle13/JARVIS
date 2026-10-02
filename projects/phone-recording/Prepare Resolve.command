#!/bin/zsh
# Local mac-mini-64 processing only. No camera start/stop commands.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
if .sync-venv/bin/python prepare_resolve.py --import-resolve; then
  echo '\nPreparation finished. See the report above for Resolve import status.'
else
  echo '\nNeeds review. Original media retained; no guessed timeline/import.'
fi
read -r '?Press Return to close.'
