#!/usr/bin/env python3
"""One network-only reachability check for the commissioned picture frame.

A fresh ICMP reply from the privately commissioned address is required for green.
A visible conflicting MAC is rejected; an absent OS neighbor entry is not identity
proof. No ADB, photos, controller configuration, keys, discovery or retries.
Default invocation is a no-I/O dry-run; only --check performs the explicit read.
"""
import argparse
import json


def _private_path(path, *, directory=False):
    import os
    import stat
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Private monitoring state is unavailable')


def _read_config(path):
    import ipaddress
    import os
    import re
    import stat
    # Never follow a file replacement into another runtime/source/key location.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise ValueError('Private monitoring configuration is unavailable')
        value = json.loads(os.read(fd, 4097))
    finally:
        os.close(fd)
    fields = {'schema_version', 'policy', 'ipv4', 'mac_address', 'interface'}
    if (type(value) is not dict or set(value) != fields
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['policy'] != 'owner_approved_frame_lan_presence'):
        raise ValueError('Unsupported network-only monitoring policy')
    address = ipaddress.IPv4Address(value['ipv4'])
    networks = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
    if (str(address) != value['ipv4'] or not any(address in ipaddress.IPv4Network(n) for n in networks)
            or not isinstance(value['interface'], str)
            or not re.fullmatch(r'en[0-9]{1,2}', value['interface'])
            or not isinstance(value['mac_address'], str)
            or not re.fullmatch(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', value['mac_address'])):
        raise ValueError('Invalid literal LAN target or interface/MAC pin')
    octets = bytes.fromhex(value['mac_address'].replace(':', ''))
    if octets[0] & 1 or octets == b'\0' * 6:
        raise ValueError('A unicast Wi-Fi MAC pin is required')
    return value


def _run(argv, timeout):
    import subprocess
    return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})


def _neighbor(result, config):
    import re
    # Read one already-known address only. Never enumerate/flush/write ARP state.
    if len(result.stdout) > 4096 or len(result.stderr) > 4096:
        raise ValueError('Unexpected neighbor response')
    text = result.stdout.decode('ascii')
    if result.returncode != 0:
        # macOS arp reports an absent entry on stdout. Other failures are unknown.
        if (result.returncode == 1 and not result.stderr and
                text.strip() in (f"{config['ipv4']} ({config['ipv4']}) -- no entry",
                                 f"{config['ipv4']} ({config['ipv4']}) -- no entry on {config['interface']}")):
            return None
        raise ValueError('Neighbor query failed')
    match = re.fullmatch(r'\? \(([0-9.]+)\) at ([0-9a-f:]+|\(incomplete\)) on '
                         r'(en[0-9]{1,2})(?: ifscope)?(?: \[ethernet\])?\s*', text)
    if not match or (match[1], match[3]) != (config['ipv4'], config['interface']):
        raise ValueError('Neighbor address/interface not verified')
    if match[2] == '(incomplete)':
        return None
    parts = match[2].split(':')
    if len(parts) != 6 or any(not re.fullmatch('[0-9a-f]{1,2}', part) for part in parts):
        raise ValueError('Neighbor MAC not verified')
    return ':'.join(part.zfill(2) for part in parts)


def _probe(config):
    import re
    import subprocess
    try:
        # -t is macOS's overall seconds limit, -W is per-reply milliseconds.
        # Exactly one echo, fixed system binaries, literal address, no shell/DNS.
        ping = _run(['/sbin/ping', '-n', '-c', '1', '-t', '2', '-W', '1000',
                     '-b', config['interface'], config['ipv4']], 3.0)
        if len(ping.stdout) > 4096 or ping.stderr or len(ping.stderr) > 4096:
            return {'ok': None, 'reason': 'check_failed'}
        text = ping.stdout.decode('ascii')
        summary = re.findall(r'(?m)^1 packets? transmitted, ([01]) packets? received,', text)
        if len(summary) != 1:
            return {'ok': None, 'reason': 'check_failed'}
        replied = summary == ['1'] and ping.returncode == 0
        if not replied and not (summary == ['0'] and ping.returncode in (1, 2)):
            return {'ok': None, 'reason': 'check_failed'}
        arp = _run(['/usr/sbin/arp', '-n', '-i', config['interface'], config['ipv4']], 1.0)
        mac = _neighbor(arp, config)
        if mac is not None and mac != config['mac_address']:
            return {'ok': None, 'reason': 'identity_unverified'}
        if not replied:
            return {'ok': False, 'reason': 'read_failed'}
        # The commissioned IP replied now. Some macOS versions expose no ARP
        # entry even after a reply. This is address reachability, not authenticated
        # hardware identity; never claim MAC verification when cache data is absent.
        return {'ok': True, 'reason': None}
    except subprocess.TimeoutExpired:
        return {'ok': None, 'reason': 'worker_timeout'}
    except (OSError, ValueError, UnicodeError):
        return {'ok': None, 'reason': 'check_failed'}


def check_frame(config_path=None):
    # Deferred stdlib imports preserve the no-contact/no-state dry-run.
    import fcntl
    import os
    from pathlib import Path
    import stat
    path = Path(config_path) if config_path is not None else (
        Path.home() / 'Library/Application Support/JARVIS/picture-frame/network-health.json')
    fd = None
    try:
        _private_path(path.parent, directory=True)
        _private_path(path)
        lock = path.parent / 'controller.lock'
        _private_path(lock)
        # Reuse the existing canonical lock without creating/repairing anything.
        fd = os.open(lock, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Private canonical lock unavailable')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': None, 'reason': 'device_busy'}
        config = _read_config(path)
        return _probe(config)
    except (OSError, ValueError, TypeError, RecursionError):
        return {'ok': None, 'reason': 'configuration_unavailable'}
    except Exception:
        return {'ok': None, 'reason': 'check_failed'}
    finally:
        if fd is not None:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not args.check:
        return {'status': 'dry_run', 'operation': 'frame-network-reachability',
                'device_contacted': False, 'runtime_read': False}
    return check_frame()


if __name__ == '__main__':
    try:
        result = main()
    except Exception:
        result = {'ok': None, 'reason': 'check_failed'}
    print(json.dumps(result, sort_keys=True))
