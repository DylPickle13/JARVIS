"""Opt-in L930-5 power transitions using the watcher's shared basement snapshot.

No colour/brightness changes, new scanner, scheduler, or automatic write retries.
Run under cycle.lock. A persisted pending marker requires explicit owner review.
"""
import json
import subprocess
import time

import cycle

FAULTS = {'presence', 'led', 'state'}
MESSAGES = {
    'presence': 'LED strip presence unavailable or stale; power unchanged.',
    'led': 'LED strip automation blocked after an unverified command; owner review required.',
    'state': 'LED strip automation state unavailable or invalid; power unchanged.',
}


def initial():
    return dict(version=1, last_tick=None, last_mode=None, pending=False)


def validate_state(s):
    if (type(s) is not dict or set(s) != set(initial()) or type(s['version']) is not int
            or s['version'] != 1 or type(s['pending']) is not bool
            or s['last_mode'] not in (None, 'on', 'off')
            or (s['last_tick'] is not None and not cycle.finite(s['last_tick']))):
        raise cycle.CycleError('state')
    return s


class LightingError(RuntimeError):
    def __init__(self, details):
        super().__init__('Unverified lighting response')
        self.details = details


def response_diagnostic(result):
    """Only fixed labels; never persist raw stderr, device data, or credentials."""
    details = {'exit_code': result.returncode}
    try:
        if len(result.stdout) > 16384:
            raise ValueError()
        payload = json.loads(result.stdout)
        if type(payload) is not dict:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        details['reason'] = 'invalid_response'
        stderr = result.stderr if isinstance(result.stderr, bytes) else b''
        for text, reason in ((b'Operation not permitted', 'operation_not_permitted'),
                             (b'Permission denied', 'permission_denied'),
                             (b'No such file or directory', 'file_not_found'),
                             (b'not found', 'command_not_found')):
            if text in stderr:
                details['reason'] = reason
                break
        return details
    reasons = {'presence_deadline_expired', 'write_outcome_unknown', 'authentication_failed',
               'timeout', 'dependency_unavailable', 'private_credentials_unavailable',
               'network_or_local_io_error', 'operation_failed', 'unreachable',
               'device_identity_mismatch', 'device_busy'}
    reason = payload.get('reason')
    details['reason'] = reason if isinstance(reason, str) and reason in reasons else 'unclassified'
    if payload.get('stage') in ('preflight', 'connection', 'state_read', 'unknown'):
        details['stage'] = payload['stage']
    if payload.get('result') in ('read_succeeded', 'verified', 'readback_mismatch', 'error'):
        details['result'] = payload['result']
    return details


def probe_once(store):
    """Explicit owner-requested read in the real LaunchAgent, consumed before dispatch."""
    request = store.load('led-probe-request.json', False)
    if request is not True:
        return
    store.save('led-probe-request.json', False)
    started = time.monotonic()
    try:
        result = subprocess.run(
            [str(cycle.ROOT.parent / 'security' / 'security'), '--json', 'status', 'led-strip'],
            capture_output=True, timeout=29, check=False)
        details = response_diagnostic(result)
    except subprocess.TimeoutExpired:
        details = {'reason': 'subprocess_timeout'}
    except OSError as exc:
        details = {'reason': 'subprocess_os_error', 'errno': exc.errno}
    store.save('led-probe-result.json', {'at': time.time(),
               'elapsed': round(time.monotonic() - started, 3), **details})


def send(mode, deadline):
    if mode not in ('on', 'off') or not cycle.finite(deadline):
        raise ValueError('Invalid lighting request')
    # CLI checks the model and the same monotonic deadline again after authentication,
    # immediately before dispatch. No credentials in argv, output, or notifications.
    result = subprocess.run(
        [str(cycle.ROOT.parent / 'security' / 'security'), '--json', 'light-set',
         'led-strip', 'state', mode, '--confirm', '--presence-deadline', str(deadline)],
        capture_output=True, timeout=29, check=False)
    details = response_diagnostic(result)
    if len(result.stdout) > 16384:
        raise LightingError(details)
    try:
        payload = json.loads(result.stdout)
        if type(payload) is not dict:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise LightingError(details) from None
    if (result.returncode == 2 and payload.get('reason') == 'presence_deadline_expired'):
        return False  # Explicitly rejected before writing, safe to await fresh presence.
    if (result.returncode != 0 or payload.get('result') != 'verified'
            or payload.get('device') != 'led-strip' or payload.get('model') != 'L930-5'
            or payload.get('setting') != 'state' or payload.get('value') is not (mode == 'on')):
        raise LightingError(details)
    return True


def tick(state, faults, *, now, get_presence, apply, save, monotonic=time.monotonic):
    validate_state(state)
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
        age = next(z['ageSeconds'] for z in payload['zones'] if z.get('zone') == 'basement')
        deadline = observed + 15 - age
        if monotonic() >= deadline:
            raise cycle.CycleError('presence')
    except cycle.CycleError:
        faults.add('presence')
        return
    faults.discard('presence')
    if state['pending']:
        faults.add('led')
        return
    target = 'on' if location == 'nearby' else 'off'
    if state['last_mode'] == target:
        return
    state['pending'] = True
    save(state)
    if monotonic() >= deadline:
        state['pending'] = False
        faults.add('presence')
        save(state)
        return
    try:
        verified = apply(target, deadline)
        if verified is False:
            state['pending'] = False
            faults.add('presence')
        elif verified is True:
            state.update(last_mode=target, pending=False)
            faults.discard('led')
        else:
            faults.add('led')
    except Exception:
        faults.add('led')  # Pending stays durable: never automatically replay.
    save(state)


def run_once(store, *, now=time.time, get_presence=cycle.read_presence, apply=None):
    config = store.load('led-config.json', {'enabled': False})
    if type(config) is not dict or set(config) != {'enabled'} or type(config['enabled']) is not bool:
        return 'ERROR: ' + MESSAGES['state'], 1
    if not config['enabled']:
        return '', 0
    old = store.load('led-alerts.json', [])
    if type(old) is not list or any(type(f) is not str or f not in FAULTS for f in old):
        raise cycle.CycleError('state')
    old, faults = set(old), set(old)

    def diagnosed_apply(mode, deadline):
        try:
            return (apply or send)(mode, deadline)
        except Exception as exc:
            details = (exc.details if isinstance(exc, LightingError) else
                       {'reason': 'subprocess_timeout'} if isinstance(exc, subprocess.TimeoutExpired) else
                       {'reason': 'subprocess_os_error', 'errno': exc.errno} if isinstance(exc, OSError) else
                       {'reason': 'unclassified'})
            store.save('led-failure.json', {'at': now(), **details})
            raise

    try:
        state = validate_state(store.load('led-state.json', initial()))
        tick(state, faults, now=now(), get_presence=get_presence, apply=diagnosed_apply,
             save=lambda s: store.save('led-state.json', s))
    except (cycle.CycleError, OSError, ValueError, TypeError, KeyError):
        faults.add('state')
    store.save('led-alerts.json', sorted(faults))
    if faults and not old:
        kind = next(k for k in ('state', 'presence', 'led') if k in faults)
        return 'ERROR: ' + MESSAGES[kind], 1
    if old and not faults:
        return 'RECOVERED: LED strip automation checks are working again.', 0
    return '', 0
