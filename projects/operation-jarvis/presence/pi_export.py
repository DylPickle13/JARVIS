#!/usr/bin/env python3
"""Bounded, sanitized snapshot export over existing authenticated SSH."""
import json
import math
from pathlib import Path
import time


def export(root=None):
    root = root or Path.home() / '.local/share/jarvis-presence'
    unknown = {'state': 'unknown', 'sources': [], 'ageSeconds': 0, 'reason': 'listener-unavailable'}
    try:
        path = root / 'state.json'
        if path.stat().st_size > 16384:
            return unknown
        raw = json.loads(path.read_text())
        if raw['bootId'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            return unknown
        age = time.monotonic() - raw['updatedMonotonic']
        if not math.isfinite(age) or not 0 <= age <= 15:
            return unknown
        state, sources = raw['state'], raw['sources']
        if state not in ('nearby', 'away', 'unknown') or not isinstance(sources, list) or any(s not in ('watch', 'iphone') for s in sources):
            return unknown
        reason = raw.get('reason')
        if reason not in ('ble-proximity', 'not-enrolled', 'awaiting-placement', 'listener-unavailable'):
            return unknown
        return {'state': state, 'sources': sources, 'ageSeconds': age, 'reason': reason}
    except (OSError, KeyError, TypeError, ValueError):
        return unknown


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--rpc']:
        for line in sys.stdin:
            if line.strip() != 'status':
                break
            print(json.dumps(export()), flush=True)
    else:
        print(json.dumps(export()))
