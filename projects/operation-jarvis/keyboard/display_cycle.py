#!/usr/bin/env python3
"""Opt-in basement display locking. Configuration stays disabled until owner setup."""
import json
import subprocess
import sys
import time

import cycle

MAX_GAP = 30


def initial():
    return dict(version=2, mode=None, away_since=None, away_checks=0, last_tick=None,
                pending=False, fault=False, completed_at=None)


def send(action):
    subprocess.run([sys.executable, str(cycle.ROOT / 'display_session.py'), action],
                   check=True, capture_output=True, timeout=8)


def observe():
    result = subprocess.run([sys.executable, str(cycle.ROOT / 'display_session.py'), 'observe'],
                            check=True, capture_output=True, timeout=8)
    if len(result.stdout) > 2048:
        raise RuntimeError('Display observation unavailable')
    return json.loads(result.stdout)


def run_once(store, *, now=time.time, get_presence=cycle.read_presence, apply=None, readback=None):
    config = store.load('display-config.json', {'enabled': False})
    if type(config) is not dict or set(config) != {'enabled'} or type(config['enabled']) is not bool:
        raise cycle.CycleError('state')
    if not config['enabled']:
        return '', 0
    state = store.load('display-state.json', initial())
    migrated = False
    # Legacy state did not distinguish initial nearby from a completed wake.
    # Migration publishes no phone action and NEVER clears a pending/fault latch.
    if type(state) is dict and type(state.get('version')) is int and state['version'] == 1:
        legacy = set(initial()) - {'completed_at'}
        if set(state) == legacy - {'away_checks'}:
            state.update(away_checks=0, away_since=None)
        if set(state) == legacy:
            state.update(version=2, completed_at=None)
            migrated = True
    if (type(state) is not dict or set(state) != set(initial())
            or type(state['version']) is not int or state['version'] != 2
            or state['mode'] not in (None, 'nearby', 'away')
            or type(state['away_checks']) is not int or not 0 <= state['away_checks'] <= 3
            or any(state[k] is not None and not cycle.finite(state[k])
                   for k in ('away_since', 'last_tick', 'completed_at'))
            or any(type(state[k]) is not bool for k in ('pending', 'fault'))):
        raise cycle.CycleError('state')

    def save():
        store.save('display-state.json', state)

    if migrated:
        save()  # Persist schema only, including every existing uncertainty marker.
    if state['pending'] or state['fault']:
        first = not state['fault']
        state['fault'] = True
        current = now()
        if not cycle.finite(current):
            raise cycle.CycleError('state')
        if state['last_tick'] is None or current - state['last_tick'] >= 60:
            state['last_tick'] = current
            save()  # Read-only recovery is paced and requires the helper idle lock.
            try:
                actual = (readback or observe)()
                if (type(actual) is not dict or set(actual) != {'locked', 'all_asleep', 'idle'}
                        or any(type(actual[k]) is not bool for k in actual) or actual['idle'] is not True):
                    raise RuntimeError('Display observation unavailable')
                target = 'nearby' if state['mode'] == 'away' else 'away'
                matched = (not actual['all_asleep']) if target == 'nearby' else (actual['locked'] and actual['all_asleep'])
                completed = now()
                if not cycle.finite(completed) or completed < current:
                    raise RuntimeError('Clock invalid')
                if state['pending'] and matched:
                    state.update(mode=target, completed_at=completed)
                else:
                    state['completed_at'] = None
                state.update(pending=False, fault=False, away_since=None, away_checks=0, last_tick=completed)
                save()
                return 'RECOVERED: Display action reconciled from idle, actual lock/power state; no action replayed.', 0
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError):
                pass
        save()
        return ('ERROR: Display state unverified; retrying readback before any further action.', 1) if first else ('', 0)
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
        return 'ERROR: Display lock/wake unverified; waiting for automatic lock/power readback.', 1
    # Publish only after the helper completed and the durable pending marker can
    # be cleared. The phone relay never treats an initial nearby as a wake.
    completed = now()
    if not cycle.finite(completed) or completed < current:
        state['fault'] = True
        save()
        return 'ERROR: Display lock/wake unverified; waiting for automatic lock/power readback.', 1
    state.update(mode=presence, away_since=None, away_checks=0, pending=False,
                 fault=False, completed_at=completed, last_tick=completed)
    save()
    return '', 0
