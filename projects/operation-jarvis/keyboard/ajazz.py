#!/usr/bin/env python3
"""AK820 Mac lighting CLI: explicit one-shot controls, no firmware operations."""
import argparse
import ctypes
import fcntl
import json
from pathlib import Path
import re
import sys

import bridge_client

VID, PID, USAGE_PAGE = 0x320F, 0x505B, 0xFF1C
# Protocol observations: openajazz commit 800e8fba3ecd04db41c179d765e14867d5b9683f.
# Static intentionally excluded: upstream maps both Static and Breath to 5.
EFFECTS = dict(corrugated=1, cloud=2, serpentine=3, spectrum=4, breath=5,
               reaction=7, ripples=8, traverse=9, stars=10, flowers=11,
               roll=12, wave=13, cartoon=14, rain=15, scan=16, surmount=17, speed=18)
BRIGHTNESS = ['lowest', 'low', 'medium', 'high', 'highest']
SPEED = ['fastest', 'fast', 'medium', 'slow', 'slowest']
DIRECTION = ['left_to_right', 'right_to_left']
DEFAULT = dict(effect='breath', color='#00AACC', brightness='low', speed='slow',
               direction='left_to_right')


def report(config):
    """Pure encoder; validates everything before accessing HID."""
    if not isinstance(config, dict) or set(config) - set(DEFAULT):
        raise ValueError('Expected an RGB settings object; unknown settings are refused')
    c = DEFAULT | config
    if not all(isinstance(value, str) for value in c.values()):
        raise ValueError('Every lighting setting must be a string')
    if c['effect'] not in EFFECTS:
        raise ValueError('Unsupported effect (static/per-key are not verified)')
    b = bytearray(65)
    b[:5] = bytes([4, 0x2A, 0x3D, 6, 0x1D])
    b[9] = EFFECTS[c['effect']]
    b[10] = BRIGHTNESS.index(c['brightness'])
    b[11] = SPEED.index(c['speed'])
    b[12] = DIRECTION.index(c['direction'])
    color = c['color']
    if color == 'rainbow':
        b[13] = 1
    elif isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        b[14:17] = bytes.fromhex(color[1:])
    else:
        raise ValueError('Color must be #RRGGBB or rainbow')
    return bytes(b)


def matches(d):
    return (d.get('vendor_id'), d.get('product_id'), d.get('usage_page')) == (VID, PID, USAGE_PAGE)


def hid_module():
    try:
        import hid
        return hid
    except ImportError as exc:
        raise RuntimeError('Install project requirements in .venv first; preview needs no dependencies') from exc


def discover(hid):
    # Enumeration only: no device opened, no feature reports, no keystrokes read.
    return hid.enumerate()


PRESET_DIR = Path(__file__).resolve().parent / 'presets'


def preset_path(value):
    """Resolve a bundled name or explicit JSON path; never write presets."""
    bundled = PRESET_DIR / f'{value}.json'
    return bundled if value in preset_names() else Path(value).expanduser()


def preset_names():
    return sorted(p.stem for p in PRESET_DIR.glob('*.json'))


def configure_shared(hid):
    """Called after enumeration initializes hidapi; never fall back to seizing."""
    if sys.platform != 'darwin':
        raise RuntimeError('Hardware control is currently supported only on macOS')
    try:
        lib = ctypes.CDLL(hid.__file__)
        setter = lib.hid_darwin_set_open_exclusive
        setter.argtypes = [ctypes.c_int]
        setter.restype = None
        getter = lib.hid_darwin_get_open_exclusive
        getter.argtypes = []
        getter.restype = ctypes.c_int
        setter(0)
        if getter() != 0:
            raise RuntimeError('Could not enable shared access; refusing exclusive access')
    except (AttributeError, OSError) as exc:
        raise RuntimeError('Installed hidapi lacks shared-access support; no device opened') from exc


def send_once(config, hid, path_hex=None, shared=configure_shared):
    """One validated output write, no reads/retries/recovery writes."""
    data = report(config)
    path = bytes.fromhex(path_hex) if path_hex is not None else None
    candidates = [d for d in discover(hid) if matches(d)
                  and d.get('product_string') == 'AK820'
                  and d.get('interface_number') == 1 and d.get('usage') == 146
                  and (path is None or d['path'] == path)]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one matching AK820 RGB vendor interface; '
                         'run discover and use --path-hex if multiple keyboards are connected')
    shared(hid)
    device = hid.device()
    try:
        device.open_path(candidates[0]['path'])
        count = device.write(data)
        if count != len(data):
            raise RuntimeError(f'Short HID write ({count}/{len(data)}); no retry. '
                               'The keyboard may have partially accepted the command.')
    finally:
        device.close()
    return count


def resolve_settings(args):
    config = {}
    if getattr(args, 'preset', None):
        config = json.loads(preset_path(args.preset).read_text())
        report(config)  # Reject malformed preset even if flags would mask its errors.
    for key in DEFAULT:
        value = getattr(args, key, None)
        if value is not None:
            config[key] = value
    report(config)
    return DEFAULT | config


def lighting_options(parser):
    parser.add_argument('--effect', choices=EFFECTS)
    parser.add_argument('--color', help='Quoted #RRGGBB or rainbow')
    parser.add_argument('--brightness', choices=BRIGHTNESS)
    parser.add_argument('--speed', choices=SPEED)
    parser.add_argument('--direction', choices=DIRECTION)


def keyboard_status(hid):
    """Metadata only. Never substitute intended settings for live hardware state."""
    devices = [d for d in discover(hid) if matches(d)
               and d.get('product_string') == 'AK820'
               and d.get('interface_number') == 1 and d.get('usage') == 146]
    return dict(connected=bool(devices), matching_interfaces=len(devices),
                devices=[dict(product=d['product_string'], vendor_id=f'{VID:04x}',
                              product_id=f'{PID:04x}', path_hex=d['path'].hex())
                         for d in devices],
                lighting_state=None, lighting_readback='not_implemented_unverified_protocol',
                reason='No verified current-lighting query for base wired AK820 320f:505b. '
                       'Enumeration cannot reveal color, effect, brightness, speed, direction, '
                       'or persistence. Cached settings would not establish current state.',
                hardware_write=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('discover', help='Read-only HID enumeration')
    d.add_argument('--all', action='store_true', help='Include non-AJAZZ devices (metadata may be private)')
    sub.add_parser('status', help='Read-only connection status; live lighting state is currently unknown')
    sub.add_parser('bridge-status', help='Read signed bridge safety state; no HID write')
    sub.add_parser('effects', help='List the 17 visually confirmed effect selectors')
    sub.add_parser('options', help='List all allowed controls and default settings')
    sub.add_parser('presets', help='List bundled preset names')
    s = sub.add_parser('preview', help='Offline encoder; no device access')
    s.add_argument('preset', nargs='?', help='Bundled preset name or JSON path')
    lighting_options(s)
    for command in ('set', 'apply'):
        s = sub.add_parser(command, help='Send one lighting report (or use --dry-run)')
        if command == 'apply':
            s.add_argument('preset', help='Bundled preset name or JSON path')
        else:
            s.add_argument('--preset', help='Optional preset as a base for overrides')
        lighting_options(s)
        s.add_argument('--dry-run', action='store_true', help='Preview only; no HID access')
        s.add_argument('--path-hex', help='Exact discovered path; otherwise require one matching keyboard')
    p.epilog = ('Each command sends a complete configuration: defaults, then preset, then flags. '
                'Omitted settings do not preserve current hardware state. No firmware, raw packets, '
                'off/static, or per-key controls. Avoid rapid repeated writes; persistence is unknown.')
    args = p.parse_args()
    try:
        if args.command == 'effects':
            print(json.dumps(EFFECTS, indent=2))
        elif args.command == 'bridge-status':
            print(json.dumps(bridge_client.request('status'), indent=2))
        elif args.command == 'status':
            print(json.dumps(keyboard_status(hid_module()), indent=2))
        elif args.command == 'options':
            print(json.dumps(dict(effects=list(EFFECTS), color='#RRGGBB or rainbow',
                brightness=BRIGHTNESS, speed=SPEED, direction=DIRECTION,
                defaults=DEFAULT), indent=2))
        elif args.command == 'presets':
            print('\n'.join(preset_names()))
        elif args.command == 'discover':
            devices = discover(hid_module())
            result = []
            for d in devices:
                if args.all or d.get('vendor_id') == VID:
                    result.append(dict(vendor_id=f"{d['vendor_id']:04x}",
                        product_id=f"{d['product_id']:04x}",
                        usage_page=f"{d.get('usage_page', 0):04x}",
                        usage=d.get('usage'), interface=d.get('interface_number'),
                        product=d.get('product_string'), path_hex=d['path'].hex(),
                        candidate=matches(d)))
            print(json.dumps(result, indent=2))
        else:
            if args.command == 'set' and not args.preset and not any(
                    getattr(args, key, None) is not None for key in DEFAULT):
                raise ValueError('set requires a preset or at least one setting; use --help')
            config = resolve_settings(args)
            data = report(config)
            if args.command == 'preview' or args.dry_run:
                print(json.dumps(dict(settings=config, bytes=len(data),
                    report_hex=data.hex(' '), hardware_write=False), indent=2))
            else:
                # Serialize CLI access without reading hardware state or retrying commands.
                with Path(__file__).with_name('.lighting.lock').open('a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        raise RuntimeError('Another lighting command is running; stopped') from exc
                    if bridge_client.backend() == 'karabiner':
                        if args.path_hex is not None:
                            raise ValueError('Bridge requires exactly one matching device; explicit paths are not accepted')
                        count = bridge_client.send(data)
                    else:
                        count = send_once(config, hid_module(), args.path_hex)
                print(json.dumps(dict(settings=config, bytes_written=count,
                    hardware_write=True, note='One report sent; connection closed. '
                    'Visual behavior is not read back.'), indent=2))
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        p.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
