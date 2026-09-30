"""Bounded DHCP recovery for batch reads only; never executes a power command.

State/lock survive the backend's short-lived vendor processes. Recovery is limited
to configured private IPv4 /24 LANs and explicitly recorded, unique MACs.
"""
from __future__ import annotations

import asyncio
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from kasa import Discover

from .config import normalize_name

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 300
# Initial batch reads use at most 7s; keep recovery inside the existing 12s
# backend worker deadline, including interpreter startup and cleanup.
DISCOVERY_BUDGET_SECONDS = 3
MAX_FILE_BYTES = 65536


def _mac(value):
    if not isinstance(value, str):
        return None
    value = value.replace(':', '').replace('-', '').lower()
    return value if re.fullmatch(r'[0-9a-f]{12}', value) and value != '0' * 12 else None


def _lan(host):
    try:
        address = ipaddress.IPv4Address(host)
        # Do not recover public, loopback, link-local or unspecified targets.
        if not any(address in ipaddress.IPv4Network(cidr) for cidr in
                   ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            return None
        network = ipaddress.IPv4Network(f'{address}/24', strict=False)
        return network if address not in (network.network_address, network.broadcast_address) else None
    except (ValueError, TypeError):
        return None


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Unsafe recovery file')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Recovery file too large')
    return raw, json.loads(raw)


def _atomic_json(path, payload, mode=0o600):
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(json.dumps(payload, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _entries(settings, payload):
    """Only the unambiguous wrapped JSON format with no environment override."""
    plugs = payload.get('plugs') if isinstance(payload, dict) else None
    if not isinstance(plugs, dict) or len(plugs) > 64:
        return {}
    entries, mac_counts, name_counts = {}, {}, {}
    for key, item in plugs.items():
        name = normalize_name(key)
        name_counts[name] = name_counts.get(name, 0) + 1
        mac = _mac(item.get('mac')) if isinstance(item, dict) else None
        if mac:
            mac_counts[mac] = mac_counts.get(mac, 0) + 1
        configured = settings.plugs.get(name)
        if (configured and mac and item.get('host') == configured.host
                and _lan(configured.host)):
            entries[name] = (key, mac, configured.host)
    return {name: entry for name, entry in entries.items()
            if mac_counts[entry[1]] == 1 and name_counts[name] == 1}


async def _discover(controller, eligible):
    """Inspect raw identities before refreshing; aliases are never selectors."""
    from .kasa_client import _close_device, _safe_get, _status_from_device

    networks = {_lan(entry[2]) for entry in eligible.values()}
    # One LAN broadcast per recovery, not one per failed device/subnet.
    if len(networks) != 1:
        return {}
    network = networks.pop()
    devices = {}
    try:
        async with asyncio.timeout(DISCOVERY_BUDGET_SECONDS):
            devices = await Discover.discover(
                target=str(network.broadcast_address), discovery_timeout=1,
                discovery_packets=2, timeout=2, **controller._primary_auth_kwargs())
            if len(devices) > 64:
                return {}
            by_mac = {}
            for host, device in devices.items():
                mac = _mac(_safe_get(device, 'mac'))
                by_mac.setdefault(mac, []).append((host, device))

            async def verify(name, entry):
                matches = by_mac.get(entry[1], [])
                if len(matches) != 1:
                    return None
                host, device = matches[0]
                if host == entry[2] or _lan(host) != network:
                    return None
                try:
                    async with asyncio.timeout(1.5):
                        await device.update()
                    value = _status_from_device(name, host, device).as_dict()
                    if (_mac(value['mac']) == entry[1] and value['host'] == host
                            and type(value['is_on']) is bool):
                        return name, {'ok': True, **value}
                except Exception:
                    pass
                return None

            verified = await asyncio.gather(*(verify(name, entry)
                                              for name, entry in eligible.items()))
            return dict(item for item in verified if item is not None)
    finally:
        # Cleanup is bounded separately, including when verification is cancelled.
        try:
            async with asyncio.timeout(.25):
                await asyncio.gather(*(_close_device(device) for device in devices.values()),
                                     return_exceptions=True)
        except TimeoutError:
            pass


async def recover_failed_hosts(controller, results):
    """Best effort: failures never discard normal batch results or retry writes."""
    settings = controller.settings
    path = getattr(settings, 'config_path', None)
    if path is None:
        return results
    path = Path(path)
    state_path = path.with_name(f'.{path.name}.ip-recovery.json')
    lock_path = path.with_name(f'.{path.name}.ip-recovery.lock')
    # Normal healthy reads perform no recovery I/O until a failure has occurred.
    if all(item.get('ok') is True for item in results.values()) and not state_path.exists():
        return results
    fd = None
    try:
        if path.is_symlink() or state_path.is_symlink():
            return results
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return results
        # Do not queue a second discovery behind an in-flight recovery.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw, payload = _read(path)
        entries = _entries(settings, payload)
        state = _read(state_path)[1] if state_path.exists() else {}
        if not isinstance(state, dict) or not isinstance(state.get('failures', {}), dict):
            return results
        previous = state.get('failures', {})
        failures = {}
        for name, entry in entries.items():
            if results.get(name, {}).get('ok') is True:
                continue
            fingerprint = f'{entry[1]}@{entry[2]}'
            old = previous.get(name, {})
            count = old.get('count', 0) if old.get('identity') == fingerprint else 0
            failures[name] = {'identity': fingerprint, 'count': min(FAILURE_THRESHOLD, int(count) + 1)}
        now = time.time()
        last_attempt = float(state.get('lastAttempt', 0))
        eligible = {name: entries[name] for name, value in failures.items()
                    if value['count'] >= FAILURE_THRESHOLD}
        attempt = bool(eligible) and now - last_attempt >= COOLDOWN_SECONDS
        updated = {'failures': failures, 'lastAttempt': now if attempt else last_attempt}
        if updated != state:
            # Persist cooldown BEFORE network I/O, including failed/cancelled attempts.
            _atomic_json(state_path, updated)
        if not attempt:
            return results
        recovered = await _discover(controller, eligible)
        if not recovered:
            return results
        # Reload/compare before replacing: never overwrite an intervening edit.
        if path.is_symlink() or path.read_bytes() != raw:
            return results
        proposed = {name: value['host'] for name, value in recovered.items()}
        all_hosts = [proposed.get(name, plug.host) for name, plug in settings.plugs.items()]
        if len(all_hosts) != len(set(all_hosts)):
            return results
        # Check against unselected JSON entries too (including environment overrides).
        raw_hosts = [proposed.get(normalize_name(key), item.get('host') or item.get('ip'))
                     if isinstance(item, dict) else item for key, item in payload['plugs'].items()]
        if len(raw_hosts) != len(set(raw_hosts)):
            return results
        for name, value in recovered.items():
            payload['plugs'][entries[name][0]]['host'] = value['host']
        mode = stat.S_IMODE(path.stat().st_mode)
        _atomic_json(path, payload, mode)
        return {**results, **recovered}
    except Exception:
        # Deliberately do not expose SDK/provider errors or credentials.
        return results
    finally:
        if fd is not None:
            os.close(fd)
