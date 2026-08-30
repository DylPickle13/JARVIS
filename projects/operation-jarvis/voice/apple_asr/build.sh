#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
swift build --package-path "$ROOT" --configuration release
printf 'Built %s\n' "$ROOT/.build/release/jarvis-apple-asr"
