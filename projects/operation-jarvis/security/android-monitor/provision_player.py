#!/usr/bin/env python3
"""One-time local RTSP viewer provisioning over authorized USB; never prints secrets.

Config is private JSON with version=1, host, port=554, path=/stream1 or /stream2,
username and password. Does not modify the camera or tinyCam configuration.
"""
import argparse
import base64
import ipaddress
import json
from pathlib import Path
import subprocess


def validate(config):
    try:
        address = ipaddress.IPv4Address(config['host'])
        private = any(address in ipaddress.ip_network(n) for n in
                      ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        return (private and config['version'] == 1 and config['port'] == 554
                and config['path'] in ('/stream1', '/stream2')
                and ':' not in config['username']
                and all(isinstance(config[k], str) and 1 <= len(config[k]) <= 256
                        and not any(ord(c) < 32 or ord(c) == 127 for c in config[k])
                        for k in ('username', 'password')))
    except (KeyError, TypeError, ValueError):
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--replace-existing-sha256', help='Explicit compare-and-swap of ONLY player config')
    args = p.parse_args()
    if ':' in args.serial:
        raise SystemExit('USB ADB required; network debugging not supported.')
    try:
        stat = args.config.stat()
        if stat.st_mode & 0o077 or not 1 <= stat.st_size <= 4096:
            raise ValueError()
        config = json.loads(args.config.read_text())
        if not validate(config):
            raise ValueError()
        raw = json.dumps({k: config[k] for k in
                          ('version', 'host', 'port', 'path', 'username', 'password')}).encode()
        if len(raw) > 4096:
            raise ValueError()
        encoded = base64.b64encode(raw).decode('ascii')
        # stdin avoids secret-bearing local process argv. Android 6 ADB lacks
        # non-PTY shell support: disable echo, use a noninteractive inner shell,
        # and always capture/suppress output (including any early PTY echo).
        if args.replace_existing_sha256 and (len(args.replace_existing_sha256) != 64 or
                any(c not in '0123456789abcdef' for c in args.replace_existing_sha256)):
            raise ValueError()
        replacement = (' --extra expectedSha256:s:' + args.replace_existing_sha256
                       if args.replace_existing_sha256 else '')
        command = ('content call --uri content://local.jarvis.monitor.provision '
                   '--method provision-player --extra config:s:' + encoded + replacement + '\nexit\n')
        result = subprocess.run(['adb', '-s', args.serial, 'shell', 'stty -echo; sh -s'], input=command,
                                capture_output=True, text=True, timeout=20)
    except Exception:
        raise SystemExit('Private player provisioning failed; diagnostics suppressed.') from None
    if result.returncode == 0 and 'status=provisioned' in result.stdout:
        print('Private player provisioned. No camera or pairing settings changed.')
    elif 'status=already-provisioned' in result.stdout:
        raise SystemExit('Already provisioned; refusing replacement.')
    else:
        raise SystemExit('Provisioning failed; credential-bearing diagnostics suppressed.')


if __name__ == '__main__':
    main()
