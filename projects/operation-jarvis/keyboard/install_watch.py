#!/usr/bin/env python3
"""Explicit installation of the owner-authorized local keyboard presence watcher."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parent
LABEL = 'com.jarvis.ajazz-keyboard-watch'


def definition():
    return {
        'Label': LABEL,
        'ProgramArguments': [str(ROOT / '.venv/bin/python'), str(ROOT / 'watch.py'), '--watch'],
        'WorkingDirectory': str(ROOT),
        'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1'},
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 30,
        'ProcessType': 'Background',
        'StandardOutPath': '/dev/null',
        'StandardErrorPath': '/dev/null',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', required=True)
    parser.parse_args()
    os.umask(0o077)
    domain = f'gui/{os.getuid()}'
    if subprocess.run(['launchctl', 'print', f'{domain}/{LABEL}'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise SystemExit('Already registered; refusing to restart or modify the running watcher.')
    target = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as handle:
        plistlib.dump(definition(), handle)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=False)
    if result.returncode:
        raise SystemExit('Bootstrap failed; inspect the plist/service before any retry. No automatic retry performed.')
    print(f'Installed {LABEL}; plist: {target}')


if __name__ == '__main__':
    main()
