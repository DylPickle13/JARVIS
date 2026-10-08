#!/usr/bin/env python3
"""Mac BLE collector. Only explicitly enrolled CoreBluetooth UUIDs affect presence."""
import argparse
import asyncio
from functools import wraps
import inspect
import json
import math
import os
from pathlib import Path
import time
import uuid

ROOT = Path.home() / "Library/Application Support/JARVIS/presence"
from policy import Presence, atomic_json


def load_devices(path):
    data = json.loads(path.read_text())
    devices = data["devices"]
    if not isinstance(devices, dict) or set(devices) - {"watch", "iphone"}:
        raise ValueError("Invalid device aliases")
    seen = set()
    for config in devices.values():
        config["uuid"] = str(uuid.UUID(config["uuid"])).upper()
        if config["uuid"] in seen:
            raise ValueError("Duplicate enrollment")
        seen.add(config["uuid"])
        enter, exit_ = config["enterRssi"], config["exitRssi"]
        if type(enter) is not int or type(exit_) is not int or not -110 <= exit_ < enter <= -20:
            raise ValueError("Invalid RSSI thresholds")
    return devices


def pooled_corebluetooth_backend(base, pool, *, allowed_addresses=None):
    """Drain Cocoa temporaries on the asyncio thread, once per BLE event.

    Bleak 2.1.1 dispatches did_discover_peripheral onto asyncio, outside the
    native dispatch queue's autorelease pool. Pool the entire synchronous
    dispatch, not just observed(): advertisement conversion precedes it.
    No pool spans an await. This private backend seam is covered by an
    installed-dependency regression test; review it when upgrading Bleak.
    Filter enrolled identities before conversion/cache insertion in production;
    None deliberately preserves full discovery for the explicit 30-second mode.
    """
    allowed = (None if allowed_addresses is None
               else frozenset(address.upper() for address in allowed_addresses))

    class PooledCoreBluetoothScanner(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            dispatch = self._manager.did_discover_peripheral
            if (not callable(dispatch) or inspect.iscoroutinefunction(dispatch)
                    or (allowed is not None
                        and 'peripheral' not in inspect.signature(dispatch).parameters)):
                raise RuntimeError('Unsupported CoreBluetooth dispatch API')

            @wraps(dispatch)
            def pooled_dispatch(*args, **kwargs):
                with pool():
                    if allowed is not None:
                        peripheral = args[1] if len(args) > 1 else kwargs.get('peripheral')
                        if peripheral is None:
                            raise RuntimeError('Unsupported CoreBluetooth callback arguments')
                        if str(peripheral.identifier().UUIDString()).upper() not in allowed:
                            return None
                    return dispatch(*args, **kwargs)

            # Installed before start() can begin scanning. The native delegate
            # resolves this method when scheduling each event on asyncio.
            self._manager.did_discover_peripheral = pooled_dispatch

    return PooledCoreBluetoothScanner


async def run(discover=False):
    from bleak import BleakScanner
    from bleak.backends.corebluetooth.scanner import BleakScannerCoreBluetooth
    from objc import autorelease_pool
    devices = load_devices(ROOT / "config.json")
    policy = Presence(devices)
    candidates = {}

    def observed(device, advertisement):
        policy.observe(device.address, advertisement.rssi, time.monotonic())
        if discover:
            # Local-only enrollment aid; never sent to jarvisd or committed.
            candidates[device.address] = {"name": device.name, "rssi": advertisement.rssi}

    try:
        backend = pooled_corebluetooth_backend(
            BleakScannerCoreBluetooth, autorelease_pool,
            allowed_addresses=None if discover else (config['uuid'] for config in devices.values()),
        )
        async with BleakScanner(detection_callback=observed, backend=backend):
            if discover:
                await asyncio.sleep(30)
                atomic_json(ROOT / "candidates.json", candidates)
            else:
                while True:
                    atomic_json(ROOT / "state.json", policy.snapshot(time.monotonic()))
                    await asyncio.sleep(3)
    finally:
        if not discover:
            atomic_json(ROOT / "state.json", {"state": "unknown", "sources": [], "updatedAt": time.time()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(run(args.discover))
