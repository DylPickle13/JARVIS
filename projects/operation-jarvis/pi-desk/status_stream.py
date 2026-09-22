#!/usr/bin/env python3
"""Mac-side read-only status projection; no credentials or session contents emitted."""
import datetime as dt
import json
import time
import urllib.request

STATES = {'running', 'idle', 'new', 'compacting', 'offline', 'unknown'}
URL = 'http://127.0.0.1:8790/api/v1/state'


def extract(data, now=None):
    if not isinstance(data, dict) or data.get('stale', True):
        return {}
    pi = data.get('subsystems', {}).get('pi', {})
    if pi.get('ok') is not True or pi.get('stale') is not False:
        return {}
    # Do not make an old successful collector sample look fresh by re-streaming it.
    try:
        updated = dt.datetime.fromisoformat(pi['updatedAt'].replace('Z', '+00:00'))
        age = ((now or dt.datetime.now(dt.timezone.utc)) - updated).total_seconds()
        if age < -5 or age > 15:
            return {}
    except (KeyError, ValueError, TypeError):
        return {}
    result = {}
    for row in pi.get('mobileSessions', []):
        if not isinstance(row, dict):
            continue
        n, state = row.get('sessionID'), row.get('lifecycle')
        if type(n) is int and 1 <= n <= 10 and isinstance(state, str) and state in STATES:
            result[str(n)] = state
    return result


def collect():
    try:
        with urllib.request.urlopen(URL, timeout=4) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            return {}
        return extract(json.loads(raw))
    except Exception:
        return {}


def main():
    while True:
        try:
            print(json.dumps(collect()), flush=True)
        except (BrokenPipeError, OSError):
            return
        time.sleep(3)


if __name__ == '__main__':
    main()
