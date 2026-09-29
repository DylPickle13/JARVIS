#!/usr/bin/env python3
"""One-time pairing over already-authorized USB ADB, with no network debugging.
Only the shell UID can provision. Configuration goes to non-backed-up internal
app storage, not public APK assets, Downloads or external storage.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--serial', required=True)
    p.add_argument('--private-dir', type=Path, required=True)
    args = p.parse_args()
    if ':' in args.serial: raise SystemExit('Use USB ADB, not network debugging.')
    raw = (args.private_dir/'client.json').read_bytes()
    config = json.loads(raw)
    if not config['url'].startswith('https://') or len(config['token']) < 32:
        raise SystemExit('Invalid provisioning')
    encoded = base64.b64encode(raw).decode('ascii')
    # Do not use check=True: exception command rendering could reveal the token.
    result = subprocess.run(['adb', '-s', args.serial, 'shell', 'content', 'call',
        '--uri', 'content://local.jarvis.monitor.provision', '--method', 'provision',
        '--extra', 'config:s:' + encoded], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0 and 'status=provisioned' in result.stdout:
        print('Phone privately provisioned. No credential printed.')
    elif 'status=already-provisioned' in result.stdout:
        raise SystemExit('Already provisioned; no configuration overwritten.')
    else:
        raise SystemExit('Provisioning failed; raw credential-bearing diagnostics suppressed.')


if __name__ == '__main__': main()
