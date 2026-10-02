#!/usr/bin/env python3
"""Explicit idle-only Network DVT screenshot probe. No phone image file or recording.

Run on mac-mini-16 with .iphone-venv/bin/python. Default: capture once, report
byte count, discard image. This is not yet wired into dashboard Check framing.
No auto-mount, pairing, privileged tunnel, USB fallback or persistent daemon.
"""
import asyncio
from contextlib import AsyncExitStack
import fcntl
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def capture():
    import managed_control as c
    with (c.ROOT / '.pair-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (c.ROOT / 'pending-take.json').exists() or c.status() != c.IDLE:
            raise RuntimeError('No pending take and every enabled camera idle required')
        from iphone_preview import capture as snapshot
        data = snapshot()
        if c.status() != c.IDLE:
            raise RuntimeError('Camera state changed; screenshot discarded')
        return data


if __name__ == '__main__':
    image = capture()
    print(f'Network screenshot received: {len(image)} bytes; discarded; no phone image file')
    del image
