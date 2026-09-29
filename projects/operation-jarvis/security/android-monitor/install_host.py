#!/usr/bin/env python3
"""Install only the new monitor relay LaunchAgent; existing services are untouched."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = 'com.jarvis.android-monitor'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--private-dir', required=True, type=Path)
    args = p.parse_args()
    root = args.private_dir.resolve()
    if not (root/'server.json').is_file(): raise SystemExit('Provision first.')
    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    if plist.exists(): raise SystemExit('Existing LaunchAgent: inspect it before changing.')
    spec = {'Label': LABEL, 'ProgramArguments': [sys.executable,
        str(Path(__file__).resolve().with_name('server.py')), '--private-dir', str(root)],
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
        'WorkingDirectory': str(Path(__file__).resolve().parent),
        'StandardOutPath': str(root/'server.log'), 'StandardErrorPath': str(root/'server-error.log'),
        'Umask': 63}
    os.umask(0o077)
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open('xb') as f: plistlib.dump(spec, f)
    subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(plist)], check=True)
    print('Installed new Android monitor LaunchAgent only.')


if __name__ == '__main__': main()
