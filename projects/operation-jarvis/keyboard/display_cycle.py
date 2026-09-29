#!/usr/bin/env python3
"""Opt-in basement display locking. Configuration stays disabled until owner setup."""
import subprocess
import sys
import time

import cycle

MAX_GAP = 30


def initial():
    return dict(version=1, mode=None, away_since=None, away_checks=0, last_tick=None,
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
    # Migrate old state conservatively: no previous check counts as confirmed.
    if type(state) is dict and set(state) == set(initial()) - {'away_checks'}:
        state.update(away_checks=0, away_since=None)
    if (type(state) is not dict or set(state) != set(initial())
            or type(state['version']) is not int or state['version'] != 1
            or state['mode'] not in (None, 'nearby', 'away')
            or type(state['away_checks']) is not int or not 0 <= state['away_checks'] <= 3
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
        state.update(away_since=None, away_checks=0)
    state['last_tick'] = current
    try:
        presence = cycle.basement(get_presence())
    except cycle.CycleError:
        state.update(away_since=None, away_checks=0)  # Unknown breaks confirmation.
        save()
        return '', 0
    action = None
    if presence == 'nearby':
        state.update(away_since=None, away_checks=0)
        # No unsolicited startup wake. Wake only after a successfully applied away.
        if state['mode'] == 'away':
            action = 'wake'
        else:
            state['mode'] = 'nearby'
    elif state['mode'] != 'away':
        if state['away_since'] is None:
            state.update(away_since=current, away_checks=1)
        elif last is not None and current > last:
            state['away_checks'] = min(3, state['away_checks'] + 1)
            # Only distinct watcher checks count, not the post-save recheck.
            if state['away_checks'] >= 3:
                action = 'lock-sleep'
    save()
    if action is None:
        return '', 0
    # Recheck freshness after persistence; shared snapshot includes elapsed time.
    try:
        if cycle.basement(get_presence()) != presence:
            state.update(away_since=None, away_checks=0)
            save()
            return '', 0
    except cycle.CycleError:
        state.update(away_since=None, away_checks=0)
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
    state.update(mode=presence, away_since=None, away_checks=0, pending=False, fault=False)
    save()
    return '', 0
