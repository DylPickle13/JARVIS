#!/usr/bin/env python3
"""Read-only, bounded status stream for the living-room terminal menu."""
import json
import time
import urllib.request

ALLOWED = {'running', 'idle', 'new', 'compacting', 'offline', 'unknown'}
while True:
    states = {}
    try:
        with urllib.request.urlopen('http://127.0.0.1:8790/api/v1/state', timeout=4) as response:
            data = json.loads(response.read(2_000_000))
        pi = data.get('subsystems', {}).get('pi', {})
        if pi.get('ok') is True and pi.get('stale') is False and not data.get('stale', True):
            for row in pi.get('mobileSessions', []):
                n, state = row.get('sessionID'), row.get('lifecycle')
                if type(n) is int and 1 <= n <= 10 and state in ALLOWED:
                    states[str(n)] = state
    except Exception:
        pass
    try:
        print(json.dumps(states), flush=True)
    except (BrokenPipeError, OSError):
        break
    time.sleep(3)
