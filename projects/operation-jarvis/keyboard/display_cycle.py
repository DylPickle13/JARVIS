#!/usr/bin/env python3
"""Opt-in basement display locking. Configuration stays disabled until owner setup."""
import subprocess
import sys
import time

import cycle

MAX_GAP = 30


def initial():
    return dict(version=1, mode=None, away_since=None, last_tick=None,
                pending=False, fault=False)


def send(action):
    subprocess.run([sys.executable, str(cycle.ROOT / 'display_session.py'), action],
                   check=True, capture_output=True, timeout=8)


def run_once(store, *, now=time.time, get_presence=cycle.read_presence, apply=None):
    config = store.load('display-config.json', {'enabled': False})
    if type(config) is not dict or set(config) != {'enabled'} or type(config['enabled']) is not bool:
        raise cycle.CycleError('state')
    if not config['enabled']:
        return '', 0
    state = store.load('display-state.json', initial())
    if (type(state) is not dict or set(state) != set(initial())
            or type(state['version']) is not int or state['version'] != 1
            or state['mode'] not in (None, 'nearby', 'away')
            or any(state[k] is not None and not cycle.finite(state[k])
                   for k in ('away_since', 'last_tick'))
            or any(type(state[k]) is not bool for k in ('pending', 'fault'))):
        raise cycle.CycleError('state')

    def save():
        store.save('display-state.json', state)

    if state['pending']:
        if not state['fault']:
            state['fault'] = True
            save()
            return 'ERROR: Display automation blocked after an uncertain action; owner review required.', 1
        return '', 0
    current = now()
    if not cycle.finite(current):
        raise cycle.CycleError('state')
    last = state['last_tick']
    if last is None or not 0 <= current - last <= MAX_GAP:
        state['away_since'] = None
    state['last_tick'] = current
    try:
        presence = cycle.basement(get_presence())
    except cycle.CycleError:
        state['away_since'] = None  # Unknown breaks consecutive away confirmation.
        save()
        return '', 0
    action = None
    if presence == 'nearby':
        state['away_since'] = None
        # No unsolicited startup wake. Wake only after a successfully applied away.
        if state['mode'] == 'away':
            action = 'wake'
        else:
            state['mode'] = 'nearby'
    elif state['mode'] != 'away':
        if state['away_since'] is None:
            state['away_since'] = current
        elif current > state['away_since']:
            # A second consecutive fresh watcher check confirms away. The
            # post-save freshness recheck below is not another watcher check.
            action = 'lock-sleep'
    save()
    if action is None:
        return '', 0
    # Recheck freshness after persistence; shared snapshot includes elapsed time.
    try:
        if cycle.basement(get_presence()) != presence:
            state['away_since'] = None
            save()
            return '', 0
    except cycle.CycleError:
        state['away_since'] = None
        save()
        return '', 0
    state['pending'] = True
    save()
    try:
        (apply or send)(action)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        state['fault'] = True
        save()
        return 'ERROR: Display lock/wake failed or is uncertain; automatic retries blocked pending owner review.', 1
    state.update(mode=presence, away_since=None, pending=False, fault=False)
    save()
    return '', 0
