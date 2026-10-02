#!/usr/bin/env python3
"""Run synthetic tests in a disposable source copy, never live runtime state.

Usage: .sync-venv/bin/python tests/run_isolated.py
Optional unittest arguments follow this script (default: discover all tests).
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='phone-recording-tests-') as temp:
        source = Path(temp)
        # Explicit allowlist excludes authentication, device pairing and job journals.
        for pattern in ('*.py', '*.command', 'camera-config.json', 'phone-recording'):
            for path in ROOT.glob(pattern):
                shutil.copy2(path, source / path.name)
        for name in ('tests', 'dashboard'):
            shutil.copytree(ROOT / name, source / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        cameras = json.loads((source / 'camera-config.json').read_text())['cameras']
        transports = {c['role']: {'mode': 'wifi', 'host': '192.168.21.' + str(240 + i), 'port': 5555}
                      for i, c in enumerate(cameras) if c['enabled'] and c['platform'] == 'android'}
        (source / 'android-transports.json').write_text(json.dumps(transports))
        (source / '.iphone-network.json').write_text(json.dumps({'identifier': 'a' * 40}))
        args = sys.argv[1:] or ['discover', '-s', 'tests', '-p', 'test_*.py']
        result = subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=source,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
