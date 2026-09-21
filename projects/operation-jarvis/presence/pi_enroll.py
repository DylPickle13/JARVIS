#!/usr/bin/env python3
"""Interactive, local-only IRK enrollment. Keys never enter argv, stdout or logs."""
import argparse
import base64
import binascii
import getpass
import json
import os
from pathlib import Path
import re
from policy import atomic_json
from pi_listener import load_config

ROOT = Path.home() / '.local/share/jarvis-presence'


def parse_irk(value):
    value = value.strip()
    if re.fullmatch(r'[0-9a-fA-F]{32}', value):
        result = bytes.fromhex(value)
    else:
        try:
            result = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('Expected a 16-byte IRK in hexadecimal or base64.') from None
    if len(result) != 16:
        raise ValueError('Expected a 16-byte IRK in hexadecimal or base64.')
    return result.hex()


def enroll(alias, key, root=ROOT):
    path = root / 'config.json'
    config = load_config(path)
    if alias not in ('watch', 'iphone'):
        raise ValueError('Invalid device alias.')
    if alias in config['devices']:
        raise ValueError('Device already enrolled; review configuration before replacement.')
    if key in {bytes.fromhex(item['irk']).hex() for item in config['devices'].values()}:
        raise ValueError('This key is already enrolled under another alias.')
    config['devices'][alias] = {'irk': key, 'enterRssi': -65, 'exitRssi': -70}
    atomic_json(path, config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device', choices=('watch', 'iphone'))
    args = parser.parse_args()
    if not os.isatty(0):
        raise SystemExit('Use an interactive terminal; no piped secrets.')
    os.umask(0o077)
    try:
        key = parse_irk(getpass.getpass('Identity resolving key (hidden): '))
        enroll(args.device, key)
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit('Enrollment not completed. Check the key and private configuration; no key was logged.') from None
    print('Enrollment saved. Placement remains unchanged; scanner reload and identity validation are still required.')


if __name__ == '__main__':
    main()
