#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
bash "$root/scripts/build.sh"
dest="${APPLE_MODEL_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$dest"
target="$dest/apple-model"
if [[ -e "$target" || -L "$target" ]]; then
  if [[ ! -L "$target" || "$(readlink "$target")" != "$root/bin/apple-model" ]]; then
    echo "Refusing to overwrite unrelated $target" >&2
    exit 1
  fi
else
  ln -s "$root/bin/apple-model" "$target"
fi
printf 'Installed %s\n' "$target"
case ":$PATH:" in
  *":$dest:"*) ;;
  *) printf 'Add to your shell PATH if needed: export PATH="%s:$PATH"\n' "$dest" ;;
esac
