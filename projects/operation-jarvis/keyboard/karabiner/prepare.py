#!/usr/bin/env python3
"""Prepare pinned bridge source; never installs or starts services."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    upstream = ROOT / 'upstream'
    lock = json.loads((ROOT / 'upstream.lock.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['commit']:
        raise SystemExit('Refusing unexpected upstream revision')
    # Overlapping sequential patches cannot be individually reverse-checked on
    # the final tree. Reconstruct every reviewed intermediate in a temp tree,
    # and refuse to overwrite any file not matching a known intermediate.
    patches = sorted((ROOT / 'patches').glob('*.patch'))
    names = {line[6:] for patch in patches for line in patch.read_text().splitlines()
             if line.startswith('--- a/')}
    with tempfile.TemporaryDirectory(prefix='jarvis-karabiner-prepare-') as tmp:
        stage = Path(tmp)
        known = {}
        for name in names:
            data = subprocess.check_output(['git', '-C', str(upstream), 'show', f'HEAD:{name}'])
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            known[name] = {data}
        for patch in patches:
            subprocess.run(['git', 'apply', '--check', str(patch)], cwd=stage, check=True)
            subprocess.run(['git', 'apply', str(patch)], cwd=stage, check=True)
            for name in names:
                known[name].add((stage / name).read_bytes())
        for name in names:
            target = upstream / name
            if target.is_symlink() or target.read_bytes() not in known[name]:
                raise SystemExit(f'Refusing unreviewed source changes: {name}')
        for name in names:
            target = upstream / name
            expected = (stage / name).read_bytes()
            if target.read_bytes() != expected:
                target.write_bytes(expected)
    target = upstream / 'src/share/jarvis_ak820'
    target.mkdir(exist_ok=True)
    for name in ('ak820_lighting.hpp', 'ak820_async.hpp', 'ak820_request.hpp',
                 'ak820_journal.hpp', 'ak820_bridge.hpp', 'ak820_cli.hpp',
                 'razer_protocol.hpp', 'razer_request.hpp', 'razer_async.hpp', 'razer_bridge.hpp'):
        shutil.copyfile(ROOT / 'prototype' / name, target / name)
    # Xcode excludes system headers from some dependency tracking. Force the
    # translation unit to rebuild when updating the vendored monitor patch.
    (upstream / 'src/apps/CoreService/src/main.cpp').touch()
    (upstream / 'src/bin/cli/src/main.cpp').touch()
    print('Prepared bridge source. Build/sign the complete package before deployment.')


if __name__ == '__main__':
    main()
