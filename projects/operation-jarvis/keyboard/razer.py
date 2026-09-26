#!/usr/bin/env python3
"""DeathAdder Essential 2021 controls through the signed Karabiner bridge.

Effects, brightness, DPI and polling rate. Writes preview unless --apply is
supplied. No direct-HID fallback. discover only enumerates local metadata.
Legacy direct transport helpers remain for offline protocol tests, not CLI use.
"""
import argparse
import ctypes
import fcntl
import functools
import json
import operator
from pathlib import Path
import sys
import time

VID, PID = 0x1532, 0x0098
STATE = Path.home() / 'Library/Application Support/JARVIS/razer-lighting'


def checksum(report):
    return functools.reduce(operator.xor, report[2:88], 0)


def build_report(effect=None, brightness=None):
    if (effect is None) == (brightness is None):
        raise ValueError('Choose exactly one effect or brightness operation')
    if brightness is not None:
        if type(brightness) is not int or not 0 <= brightness <= 100:
            raise ValueError('Brightness must be an integer from 0 to 100')
        command, args = 0x04, [1, 4, (brightness * 255 + 50) // 100]
    else:
        if effect not in ('off', 'steady', 'breathing'):
            raise ValueError('Unsupported effect')
        command = 0x02
        args = [1, 4, {'off': 0, 'steady': 1, 'breathing': 2}[effect], 0, 0, 0]
        if effect != 'off':
            args[5] = 1
            # Fixed-colour hardware; RGB slots are protocol placeholders.
            args.extend([255, 255, 255])
        if effect == 'breathing':
            args[3] = 1
    report = bytearray(90)
    report[1] = 0x3F
    report[5:8] = bytes([len(args), 0x0F, command])
    report[8:8 + len(args)] = bytes(args)
    report[88] = checksum(report)
    return bytes(report)


def validate_response(request, response):
    # macOS hidapi returns the unnumbered report itself (no synthetic ID byte).
    if len(response) != 90:
        raise RuntimeError(f'Unexpected response length: {len(response)}')
    if response[88] != checksum(response) or response[89] != 0:
        raise RuntimeError('Invalid response checksum/reserved byte')
    if response[1:5] != request[1:5] or response[6:8] != request[6:8] or response[5] > 80:
        raise RuntimeError('Response does not match the request')
    if response[0] != 2:
        raise RuntimeError(f'Unconfirmed device status: 0x{response[0]:02x}')


def candidates(hid):
    # Enumeration may contain both mouse and pointer collections for one path.
    found = {}
    for d in hid.enumerate(VID, PID):
        if (d['vendor_id'], d['product_id'], d['interface_number'],
                d['usage_page'], d['usage']) == (VID, PID, 0, 1, 2):
            found[d['path']] = d
    return list(found.values())


def open_shared(hid, devices):
    if sys.platform != 'darwin':
        raise RuntimeError('Only macOS is supported')
    if len(devices) != 1:
        raise RuntimeError('Expected exactly one matching mouse interface')
    lib = ctypes.CDLL(hid.__file__)
    setter = lib.hid_darwin_set_open_exclusive
    setter.argtypes, setter.restype = [ctypes.c_int], None
    getter = lib.hid_darwin_get_open_exclusive
    getter.argtypes, getter.restype = [], ctypes.c_int
    setter(0)
    if getter() != 0:
        raise RuntimeError('Shared access unavailable; will not seize the mouse')
    dev = hid.device()
    try:
        dev.open_path(devices[0]['path'])
    except Exception:
        dev.close()
        raise
    return dev


def exchange(dev, report):
    # HIDAPI requires a synthetic report ID 0 before an unnumbered payload.
    data = b'\x00' + report
    count = dev.send_feature_report(data)
    if count != len(data):
        raise RuntimeError(f'Short feature write: {count}/{len(data)}')
    time.sleep(0.05)
    response = bytes(dev.get_feature_report(0, 90))
    validate_response(report, response)


def apply(hid, devices, report):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = STATE / 'uncertain.json'
        if journal.exists():
            raise RuntimeError('Previous write is unresolved. Inspect the mouse, then use acknowledge-uncertain')
        last = STATE / 'last-attempt'
        if last.exists() and time.time() - last.stat().st_mtime < 3:
            raise RuntimeError('Wait at least three seconds between attempts')
        dev = open_shared(hid, devices)
        try:
            # Persist BEFORE submitting: a crash/exception must never cause replay.
            with journal.open('x') as f:
                json.dump({'report': report.hex(), 'time': time.time()}, f)
                f.flush()
                import os
                os.fsync(f.fileno())
            last.touch()
            exchange(dev, report)
            journal.unlink()
        finally:
            dev.close()
    print('Device acknowledged the command. Visual effect/persistence not verified.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('discover', help='Enumerate metadata only')
    sub.add_parser('probe', help='Alias for bridge-status; no device reports')
    sub.add_parser('bridge-status', help='Bridge availability/pending state, not hardware state')
    sub.add_parser('acknowledge-uncertain', help='Acknowledge daemon uncertainty; sends no device report')
    read_parser = sub.add_parser('read', help='One device query through Karabiner')
    read_parser.add_argument('setting', choices=['brightness', 'dpi', 'poll'])
    for action in ('dpi', 'poll'):
        p = sub.add_parser(action)
        p.add_argument('value', type=int)
        if action == 'dpi':
            p.add_argument('--y', type=int, help='Optional separate Y DPI; defaults to X')
        mode = p.add_mutually_exclusive_group()
        mode.add_argument('--apply', action='store_true')
        mode.add_argument('--dry-run', action='store_true')
    for action in ('effect', 'brightness'):
        p = sub.add_parser(action)
        if action == 'effect':
            p.add_argument('value', choices=['off', 'steady', 'breathing'])
        else:
            p.add_argument('value', type=int, choices=range(101), metavar='0..100')
        mode = p.add_mutually_exclusive_group()
        mode.add_argument('--apply', action='store_true', help='Actually send one command')
        mode.add_argument('--dry-run', action='store_true', help='Preview (the default)')
    args = parser.parse_args()
    import razer_bridge
    if args.action == 'discover':
        import hid
        devices = candidates(hid)
        print(json.dumps([{**d, 'path': d['path'].decode(errors='replace')} for d in devices], indent=2))
        return
    if args.action in ('bridge-status', 'probe', 'acknowledge-uncertain'):
        action = 'acknowledge' if args.action == 'acknowledge-uncertain' else 'status'
        print(json.dumps(razer_bridge.request(action), indent=2))
        return
    if args.action == 'read':
        settings = dict(operation='get-' + args.setting, value=0, y=0)
    else:
        value = {'off': 0, 'steady': 1, 'breathing': 2}[args.value] if args.action == 'effect' else args.value
        y = (args.y if args.y is not None else value) if args.action == 'dpi' else 0
        settings = dict(operation=args.action, value=value, y=y)
    razer_bridge.validate_settings(settings)
    if args.action != 'read' and not args.apply:
        print(json.dumps({'dry_run': True, 'backend': 'karabiner', 'settings': settings}, indent=2))
        return
    if (STATE / 'uncertain.json').exists():
        raise RuntimeError('Legacy direct-HID uncertainty exists; inspect before bridge use')
    print(json.dumps(razer_bridge.request('apply', settings), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, AttributeError) as exc:
        print(f'Error: {exc}. No automatic retry. If submission began, outcome may be uncertain.', file=sys.stderr)
        sys.exit(1)
