#!/usr/bin/env python3
"""Prepare pinned bridge source; never installs or starts services."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    upstream = ROOT / 'upstream'
    lock = json.loads((ROOT / 'upstream.lock.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['commit']:
        raise SystemExit('Refusing unexpected upstream revision')
    args = ['git', '-C', str(upstream), 'apply']
    for patch in sorted((ROOT / 'patches').glob('*.patch')):
        if subprocess.run(args + ['--reverse', '--check', str(patch)], capture_output=True).returncode:
            subprocess.run(args + ['--check', str(patch)], check=True)
            subprocess.run(args + [str(patch)], check=True)
    target = upstream / 'src/share/jarvis_ak820'
    target.mkdir(exist_ok=True)
    for name in ('ak820_lighting.hpp', 'ak820_async.hpp', 'ak820_request.hpp',
                 'ak820_journal.hpp', 'ak820_bridge.hpp', 'ak820_cli.hpp'):
        shutil.copyfile(ROOT / 'prototype' / name, target / name)
    # Xcode excludes system headers from some dependency tracking. Force the
    # translation unit to rebuild when updating the vendored monitor patch.
    (upstream / 'src/apps/CoreService/src/main.cpp').touch()
    (upstream / 'src/bin/cli/src/main.cpp').touch()
    print('Prepared bridge source. Build/sign the complete package before deployment.')


if __name__ == '__main__':
    main()
