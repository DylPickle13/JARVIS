"""Presence-gated Razer logo: steady nearby, off away. Never breathing.

Runs inside the existing watcher/cycle lock. Independent durable state prevents
keyboard faults/rotation from replaying mouse writes. No timers or new daemon.
"""
import time

import cycle
import razer_bridge

FAULTS = {'presence', 'mouse', 'state'}
MESSAGES = {
    'presence': 'Basement presence unavailable or stale; mouse light unchanged.',
    'mouse': 'Mouse lighting command failed; check mouse automation status. No immediate retry.',
    'state': 'Mouse automation state unavailable or invalid; mouse light unchanged.',
}


def initial():
    return dict(version=1, last_tick=None, last_attempt=None, last_mode=None,
                pending=False, succeeded=False)


def validate_state(s):
    if (type(s) is not dict or set(s) != set(initial()) or type(s['version']) is not int
            or s['version'] != 1 or type(s['pending']) is not bool
            or type(s['succeeded']) is not bool or s['last_mode'] not in (None, 'steady', 'off')
            or any(v is not None and not cycle.finite(v) for v in (s['last_tick'], s['last_attempt']))
            or (s['succeeded'] and (s['last_mode'] is None or s['last_attempt'] is None))):
        raise cycle.CycleError('state')
    return s


def send(mode):
    if mode not in ('steady', 'off'):
        raise ValueError('Mouse automation only permits steady or off')
    razer_bridge.request('apply', dict(operation='effect', value=1 if mode == 'steady' else 0, y=0))


def tick(state, faults, *, now, get_presence, apply, save, monotonic=time.monotonic):
    state.update(validate_state(state))
    if not cycle.finite(now) or (state['last_tick'] is not None and now < state['last_tick']):
        raise cycle.CycleError('state')
    if state['last_tick'] is not None and now - state['last_tick'] < 3:
        return
    state['last_tick'] = now
    save(state)
    faults.discard('state')
    observed = monotonic()
    try:
        payload = get_presence()
        location = cycle.basement(payload)
        age = next(z['ageSeconds'] for z in payload['zones'] if type(z) is dict and z.get('zone') == 'basement')
        deadline = observed + 15 - age
        if monotonic() > deadline:
            raise cycle.CycleError('presence')
        faults.discard('presence')
    except cycle.CycleError:
        faults.add('presence')
        return
    if state['pending']:
        faults.add('mouse')
        return
    target = 'steady' if location == 'nearby' else 'off'
    if state['last_mode'] == target and state['succeeded']:
        return  # No repeated report for unchanged presence or watcher restart.
    cooldown = 3 if state['succeeded'] else 60
    if state['last_attempt'] is not None and now - state['last_attempt'] < cooldown:
        return
    if monotonic() > deadline:
        faults.add('presence')
        return
    state.update(last_attempt=now, pending=True, succeeded=False)
    save(state)  # Must survive crash/IPC loss before any command is dispatched.
    if monotonic() > deadline:
        state['pending'] = False
        faults.add('presence')
        save(state)
        return
    try:
        apply(target)
    except razer_bridge.RazerBridgeError as exc:
        state['pending'] = exc.uncertain
        faults.add('mouse')
    except Exception:
        # Any unclassified transport exception is uncertain, never replayed.
        faults.add('mouse')
    else:
        state.update(last_mode=target, pending=False, succeeded=True)
        faults.discard('mouse')
    save(state)


def run_once(store, *, now=time.time, get_presence=cycle.read_presence, apply=None):
    if apply is None:
        apply = send
    old = store.load('mouse-alerts.json', [])
    if type(old) is not list or any(type(f) is not str or f not in FAULTS for f in old):
        raise cycle.CycleError('state')
    old, faults = set(old), set(old)
    try:
        state = validate_state(store.load('mouse-state.json', initial()))
        tick(state, faults, now=now(), get_presence=get_presence, apply=apply,
             save=lambda s: store.save('mouse-state.json', s))
    except (cycle.CycleError, OSError, ValueError, TypeError, KeyError):
        faults.add('state')
    store.save('mouse-alerts.json', sorted(faults))
    if faults and not old:
        kind = next(k for k in ('state', 'presence', 'mouse') if k in faults)
        return 'ERROR: ' + MESSAGES[kind], 1
    if old and not faults:
        return 'RECOVERED: Mouse automation checks are working again (last acknowledged command, not visual readback).', 0
    return '', 0


def main():
    import argparse
    import json
    from watch import locked
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--status', action='store_true')
    group.add_argument('--acknowledge-uncertain', action='store_true')
    args = parser.parse_args()
    store = cycle.Store(cycle.RUNTIME)
    with locked(store, 'cycle.lock'):
        state = validate_state(store.load('mouse-state.json', initial()))
        if args.status:
            print(json.dumps({'state': state, 'faults': store.load('mouse-alerts.json', []),
                              'nearby': 'steady', 'away': 'off', 'breathing': False,
                              'lighting_readback': False}, indent=2))
        else:
            razer_bridge.request('acknowledge')
            # Explicit recovery only: preserve last requested mode; require fresh
            # presence and a full minute cooldown before a later watcher attempt.
            state.update(pending=False, succeeded=False, last_attempt=time.time())
            store.save('mouse-state.json', state)
            print('Mouse uncertainty acknowledged; no lighting command sent.')


if __name__ == '__main__':
    main()
