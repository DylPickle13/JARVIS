#!/usr/bin/env python3
"""Mac-side read-only status projection; no credentials or session contents emitted."""
import datetime as dt
import json
import time
import urllib.request

from codex_quota import project, timestamp, UNAVAILABLE

STATES = {'running', 'idle', 'new', 'compacting', 'offline', 'unknown'}
URL = 'http://127.0.0.1:8790/api/v1/state'


def extract(data, now=None):
    # Aggregate staleness includes unrelated hardware; only Pi freshness matters here.
    if not isinstance(data, dict):
        return {}
    subsystems = data.get('subsystems')
    if not isinstance(subsystems, dict):
        return {}
    pi = subsystems.get('pi')
    if not isinstance(pi, dict):
        return {}
    if pi.get('ok') is not True or pi.get('stale') is not False:
        return {}
    # Do not make an old successful collector sample look fresh by re-streaming it.
    updated = timestamp(pi.get('updatedAt'))
    if updated is None:
        return {}
    age = ((now or dt.datetime.now(dt.timezone.utc)) - updated).total_seconds()
    if age < -5 or age > 15:
        return {}
    result = {}
    rows = pi.get('mobileSessions')
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        n, state = row.get('sessionID'), row.get('lifecycle')
        if type(n) is int and 1 <= n <= 10 and isinstance(state, str) and state in STATES:
            result[str(n)] = state
    return result


def snapshot(data, now=None):
    # Additive field: old viewers keep reading numeric session keys unchanged.
    subsystems = data.get('subsystems') if isinstance(data, dict) else None
    quota = project(subsystems.get('codexQuota'), now) if isinstance(subsystems, dict) else dict(UNAVAILABLE)
    return {**extract(data, now), 'codexQuota': quota}


def collect():
    try:
        with urllib.request.urlopen(URL, timeout=4) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            return snapshot(None)
        return snapshot(json.loads(raw))
    except Exception:
        return snapshot(None)


def main():
    while True:
        try:
            print(json.dumps(collect()), flush=True)
        except (BrokenPipeError, OSError):
            return
        time.sleep(3)


if __name__ == '__main__':
    main()
