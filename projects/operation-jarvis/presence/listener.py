#!/usr/bin/env python3
"""Mac BLE collector. Only explicitly enrolled CoreBluetooth UUIDs affect presence."""
import argparse
import asyncio
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


async def run(discover=False):
    from bleak import BleakScanner
    devices = load_devices(ROOT / "config.json")
    policy = Presence(devices)
    candidates = {}

    def observed(device, advertisement):
        policy.observe(device.address, advertisement.rssi, time.monotonic())
        if discover:
            # Local-only enrollment aid; never sent to jarvisd or committed.
            candidates[device.address] = {"name": device.name, "rssi": advertisement.rssi}

    try:
        async with BleakScanner(detection_callback=observed):
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
