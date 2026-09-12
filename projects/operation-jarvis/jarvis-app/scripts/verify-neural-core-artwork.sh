#!/usr/bin/env bash
# Offline native-vector render checks, not physical WidgetKit/energy acceptance.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-neural-render.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/Sources/RenderChecks"
cp "$ROOT/WidgetShared/NeuralCoreArtwork.swift" "$ROOT/WidgetShared/NeuralCoreC2Decoration.swift" "$WORK/Sources/RenderChecks/"
cp "$ROOT/scripts/tests/NeuralCoreRenderChecks.swift" "$WORK/Sources/RenderChecks/"
python3 - "$ROOT" "$WORK" <<'PY'
from pathlib import Path
import json,sys
root, work = map(Path, sys.argv[1:])
(work/'Package.swift').write_text('''// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "RenderChecks", platforms: [.macOS(.v14)], dependencies: [.package(path: ''' + json.dumps(str(root/'JARVISKit')) + ''')], targets: [.executableTarget(name: "RenderChecks", dependencies: ["JARVISKit"])])
''')
PY
swift run --package-path "$WORK" -c release RenderChecks "${JARVIS_NEURAL_RENDER_OUTPUT:-$WORK/renders}"
