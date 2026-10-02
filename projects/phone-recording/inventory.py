#!/usr/bin/env python3
"""Read-only inventory for known USB Android cameras; run on the attached Mac."""
import argparse
import json
from pathlib import Path
import subprocess

DEFAULT_ADB = '/opt/homebrew/bin/adb'
PHONES = {'R5CRC27FBMP': 'Dyl Cam', 'R5CT10S8GEY': 'Overhead', 'LGH873bb5b4b79': 'Wide Angle'}


def run(adb, args):
    result = subprocess.run([adb, *args], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('ADB command failed; check USB connection and authorization')
    return result.stdout.strip()


def parse_devices(text):
    devices = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in PHONES:
            devices[parts[0]] = parts[1]
    return devices


def parse_battery(text):
    result = {}
    # Anchored labels exclude Samsung's appended battery event history.
    for line in text.splitlines():
        key, sep, value = line.strip().partition(': ')
        if not sep:
            continue
        if key == 'level' and value.isdigit():
            result['percent'] = int(value)
        elif key == 'temperature':
            try:
                result['temperature_c'] = int(value) / 10
            except ValueError:
                pass
        elif key in ('USB powered', 'AC powered', 'Wireless powered'):
            result[key] = value == 'true'
    return result


def inspect(adb, runner=run):
    states = parse_devices(runner(adb, ['devices', '-l']))
    phones = []
    for serial, role in PHONES.items():
        row = {'role': role, 'serial': serial, 'usb_state': states.get(serial, 'disconnected')}
        if row['usb_state'] == 'device':
            try:
                def shell(*args):
                    return runner(adb, ['-s', serial, 'shell', *args])
                row['model'] = shell('getprop', 'ro.product.model')
                row['android'] = shell('getprop', 'ro.build.version.release')
                row['storage'] = shell('df', '-h', '/data')
                row['battery'] = parse_battery(shell('dumpsys', 'battery'))
                # Exact package lookups; do not dump unrelated installed applications.
                row['apps'] = {name: ('package:' + package) in shell('pm', 'list', 'packages', package).splitlines() for name, package in (
                    ('open_camera', 'net.sourceforge.opencamera'),
                    ('blackmagic_camera', 'com.blackmagicdesign.android.blackmagiccam'))}
            except (RuntimeError, subprocess.TimeoutExpired):
                row['error'] = 'Inspection incomplete; connection/authorization/timeout issue'
        phones.append(row)
    return {'read_only': True, 'transport': 'usb', 'android': phones,
            'iphone': {'status': 'Not inspected by this Android inventory; USB API control remains unverified'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default=DEFAULT_ADB)
    args = parser.parse_args()
    try:
        result = inspect(args.adb)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        print(json.dumps({'ok': False, 'error': 'ADB inventory unavailable; verify executable and attached host'}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if all(p['usb_state'] == 'device' and 'error' not in p for p in result['android']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
