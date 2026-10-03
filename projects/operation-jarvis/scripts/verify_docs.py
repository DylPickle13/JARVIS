#!/usr/bin/env python3
"""Validate local inline Markdown link targets, without fetching URLs.

Checks maintained source documentation only, excluding private/generated trees.
Does not validate heading anchors, external URLs, deployment claims or prose.
"""
from pathlib import Path
import os
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'__pycache__', 'node_modules', 'build', 'dist', 'DerivedData',
            'data', 'logs', 'artifacts', 'staging', 'backups', 'vendor', 'private-notes'}
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+[^)\n]*)?\)')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')


def markdown_files(root):
    # Respect repository ignore rules, including security's private archives.
    # Frozen release trees have no .git and contain only reviewed source files.
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached',
                             '--others', '--exclude-standard', '-z', '--', '*.md'],
                            capture_output=True, timeout=10)
    if result.returncode == 0:
        for name in sorted(set(result.stdout.decode('utf-8').split('\0')) - {''}):
            yield root / name
        return
    for directory, children, files in os.walk(root):
        children[:] = sorted(name for name in children
                             if not name.startswith('.') and name not in EXCLUDED)
        for name in sorted(files):
            if name.endswith('.md'):
                yield Path(directory) / name


def missing_targets(paths):
    missing = []
    for path in paths:
        fence = None
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            marker = FENCE.match(line)
            if marker:
                run = marker.group(1)
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence) and not line[marker.end():].strip():
                    fence = None
                continue
            if fence is not None:
                continue
            for match in LINK.finditer(line):
                target = match.group(1) or match.group(2)
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                if not (path.parent / unquote(url.path)).exists():
                    missing.append((path, number, target))
    return missing


def main():
    paths = list(markdown_files(ROOT))
    missing = missing_targets(paths)
    for path, line, target in missing:
        print(f'{path.relative_to(ROOT)}:{line}: missing local target {target}')
    print(f'{len(paths)} Markdown files checked; {len(missing)} missing local link targets.')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
