#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
swift build -c release
mkdir -p bin
cp .build/release/apple-model bin/apple-model
printf 'Built %s/bin/apple-model\n' "$root"
