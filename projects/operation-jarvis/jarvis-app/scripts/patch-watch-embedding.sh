#!/usr/bin/env bash
# Keep the modern single-target watchOS companion in the iOS app's Watch/
# directory. XcodeGen 2.46 emits this destination, but this idempotent guard
# prevents generated-project drift and preserves the companion-manager layout.
set -euo pipefail

PROJECT="${1:-JARVIS.xcodeproj/project.pbxproj}"
python3 - "$PROJECT" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"(?P<head>/\* Embed Watch Content \*/ = \{\n)"
    r"(?P<body>.*?)"
    r"(?P<tail>\n\s*\};)",
    flags=re.DOTALL,
)
match = pattern.search(text)
if match is None:
    raise SystemExit("error: Embed Watch Content phase is missing")

body = match.group("body")
body, path_count = re.subn(
    r'dstPath = ".*?";',
    'dstPath = "$(CONTENTS_FOLDER_PATH)/Watch";',
    body,
    count=1,
)
body, destination_count = re.subn(
    r"dstSubfolderSpec = \d+;",
    "dstSubfolderSpec = 16;",
    body,
    count=1,
)
if path_count != 1 or destination_count != 1:
    raise SystemExit("error: malformed Embed Watch Content phase")

updated = text[: match.start()] + match.group("head") + body + match.group("tail") + text[match.end() :]
path.write_text(updated, encoding="utf-8")
PY
