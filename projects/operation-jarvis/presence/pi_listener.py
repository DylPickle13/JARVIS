#!/usr/bin/env python3
"""Linux BLE collector: only IRK-resolved enrolled devices count as presence."""
import asyncio
from collections import deque
import statistics
import json
import os
from pathlib import Path
import time
from policy import Presence, atomic_json

ROOT = Path.home() / '.local/share/jarvis-presence'


def load_config(path):
    data = json.loads(path.read_text())
    if type(data.get('positioned')) is not bool or not isinstance(data.get('devices'), dict):
        raise ValueError('Invalid configuration')
    if set(data['devices']) - {'watch', 'iphone'}:
        raise ValueError('Invalid aliases')
    keys = set()
    for config in data['devices'].values():
        irk = bytes.fromhex(config['irk'])
        if len(irk) != 16 or irk in keys:
            raise ValueError('Invalid or duplicate identity key')
        keys.add(irk)
        enter, exit_ = config['enterRssi'], config['exitRssi']
        if type(enter) is not int or type(exit_) is not int or not -110 <= exit_ < enter <= -20:
            raise ValueError('Invalid thresholds')
    return data


def summarize_observations(observations, policy, now):
    """Private alias-only, bounded 60-second calibration; no keys or addresses."""
    output = {}
    for alias, readings in observations.items():
        recent = [rssi for stamp, rssi in readings if 0 <= now-stamp <= 60]
        sample = policy.samples.get(alias)
        output[alias] = {
            'matchedPacketsLast60Seconds': len(recent),
            'lastSeenAgeSeconds': round(now-sample[1], 1) if sample else None,
            'smoothedRssi': round(sample[0], 1) if sample else None,
            'minRssi': min(recent) if recent else None,
            'medianRssi': statistics.median(recent) if recent else None,
            'maxRssi': max(recent) if recent else None,
        }
    return {'updatedAt': time.time(), 'windowSeconds': 60, 'devices': output}


async def run():
    from bleak import BleakScanner
    from bluetooth_data_tools import get_cipher_for_irk, resolve_private_address
    config = load_config(ROOT / 'config.json')
    devices = config['devices']
    ciphers = {alias: get_cipher_for_irk(bytes.fromhex(item['irk'])) for alias, item in devices.items()}
    # Shared smoothing/timeout policy sees aliases, never private keys or MACs.
    policy = Presence({alias: {'uuid': alias.upper(), 'enterRssi': item['enterRssi'],
                              'exitRssi': item['exitRssi']} for alias, item in devices.items()})

    observations = {alias: deque(maxlen=600) for alias in devices}

    def observe(device, advertisement):
        for alias, cipher in ciphers.items():
            if resolve_private_address(cipher, device.address):
                now, rssi = time.monotonic(), advertisement.rssi
                policy.observe(alias, rssi, now)
                if isinstance(rssi, (int, float)) and -127 <= rssi <= -1:
                    observations[alias].append((now, rssi))

    def publish(stopped=False):
        state = policy.snapshot(time.monotonic())
        state['updatedMonotonic'] = time.monotonic()
        state['bootId'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        state['reason'] = 'ble-proximity'
        if stopped or not devices or not config['positioned']:
            state.update(state='unknown', sources=[], reason='listener-unavailable' if stopped else
                         ('not-enrolled' if not devices else 'awaiting-placement'))
        atomic_json(ROOT / 'state.json', state)
        if not stopped:
            atomic_json(ROOT / 'diagnostics.json',
                        summarize_observations(observations, policy, time.monotonic()))

    try:
        async with BleakScanner(detection_callback=observe):
            while True:
                publish()
                await asyncio.sleep(3)
    finally:
        publish(stopped=True)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        asyncio.run(run())
    except Exception:
        # Never put identity keys or advertisements in service logs.
        raise SystemExit('Presence listener unavailable; check Bluetooth and private configuration.') from None
