"""Explicit owner-authorized sensor-only trial; never masquerades as person evidence."""
from datetime import datetime
import math
import runtime


def authorization(root):
    value = runtime.read_json(root / 'sensor-trial.json')
    if value is None:
        return None
    if (set(value) != {'version', 'authorized', 'authorized_at'} or
            type(value['version']) is not int or value['version'] != 1 or
            value['authorized'] is not True or type(value['authorized_at']) is not str):
        raise runtime.TrialError('invalid_sensor_trial_authorization')
    try:
        if datetime.fromisoformat(value['authorized_at']).utcoffset() is None:
            raise ValueError()
    except ValueError:
        raise runtime.TrialError('invalid_sensor_trial_authorization') from None
    return value


def reserve_proof(root, attempt, opened_at, expires, *, now):
    value = authorization(root)
    state = runtime.Journal(root).state
    if (not value or state['pending'] != attempt or state['fault'] is not None
            or not runtime.config(root)['enabled'] or not 0 <= now-opened_at <= 1
            or expires != opened_at + 16):
        return False
    runtime.save_json(root / 'sensor-proof.json', {'version': 1, 'attempt': attempt,
        'opened_at': opened_at, 'expires': expires, 'authorized_at': value['authorized_at']})
    return valid_proof(root, attempt, expires, now=now)


def valid_proof(root, attempt, expires, *, now):
    value = authorization(root)
    proof = runtime.read_json(root / 'sensor-proof.json')
    if not value or not proof or set(proof) != {'version', 'attempt', 'opened_at', 'expires', 'authorized_at'}:
        return False
    if (type(proof['version']) is not int or proof['version'] != 1 or proof['attempt'] != attempt
            or proof['authorized_at'] != value['authorized_at']):
        return False
    if any(type(x) not in (int, float) or not math.isfinite(x)
           for x in (proof['opened_at'], proof['expires'], expires, now)):
        return False
    state = runtime.Journal(root).state
    return (state['pending'] == attempt and state['fault'] is None
        and runtime.config(root)['enabled'] and proof['expires'] == expires == proof['opened_at'] + 16
        and proof['opened_at'] <= now < expires - 1.5)
