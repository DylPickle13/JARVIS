"""Opt-in L930-5 power transitions using the watcher's shared basement snapshot.

No colour/brightness changes, new scanner/scheduler, or replay of uncertain writes.
Run under cycle.lock. Pending outcomes recover through fresh authenticated readback.
"""
import json
import subprocess
import time

import cycle

BUSY_COOLDOWN = 60
FAULTS = {'presence', 'led', 'busy', 'state'}
MESSAGES = {
    'presence': 'LED strip presence unavailable or stale; power unchanged.',
    'led': 'LED strip unavailable or outcome unverified; retrying observation before any new command.',
    'busy': 'LED strip control busy; waiting at least 60 seconds before another fresh-presence attempt.',
    'state': 'LED strip automation state unavailable or invalid; power unchanged.',
}


def initial():
    return dict(version=2, last_tick=None, last_mode=None, pending=False, last_busy=None)


def validate_state(s):
    if (type(s) is dict and type(s.get('version')) is int and s['version'] == 1
            and set(s) == set(initial()) - {'last_busy'}):
        # Schema migration is not an uncertainty acknowledgement.
        s = s | {'version': 2, 'last_busy': None}
    if (type(s) is not dict or set(s) != set(initial()) or type(s['version']) is not int
            or s['version'] != 2 or type(s['pending']) is not bool
            or s['last_mode'] not in (None, 'on', 'off')
            or any(s[k] is not None and not cycle.finite(s[k])
                   for k in ('last_tick', 'last_busy'))):
        raise cycle.CycleError('state')
    return s


class LightingError(RuntimeError):
    def __init__(self, details):
        super().__init__('Unverified lighting response')
        self.details = details


class NotSent(LightingError):
    """Trusted CLI positively rejected this operation before any power mutation."""


class DeviceBusy(LightingError):
    """The CLI positively rejected this invocation before acquiring its device lock."""


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


def read_power():
    """Read through the existing authenticated identity check and device lock."""
    result = subprocess.run(
        [str(cycle.ROOT.parent / 'security' / 'security'), '--json', 'status', 'led-strip'],
        capture_output=True, timeout=29, check=False)
    if len(result.stdout) > 16384:
        raise LightingError({'reason': 'invalid_response'})
    try:
        p = json.loads(result.stdout)
        value = p['features']['state']['value']
        if (result.returncode != 0 or p.get('result') != 'read_succeeded'
                or p.get('device') != 'led-strip' or p.get('model') != 'L930-5'
                or type(value) is not bool):
            raise ValueError()
        return 'on' if value else 'off'
    except (ValueError, TypeError, KeyError):
        raise LightingError(response_diagnostic(result)) from None


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
    if (result.returncode == 2 and payload.get('result') == 'error'
            and payload.get('reason') == 'device_busy' and payload.get('stage') == 'preflight'
            and not (set(payload) - {'result', 'reason', 'stage', 'security_assessment', 'observed_at'})):
        raise DeviceBusy(details)  # No connection or power write was attempted.
    if (result.returncode == 2 and payload.get('reason') == 'presence_deadline_expired'):
        return False  # Explicitly rejected before writing, safe to await fresh presence.
    if (result.returncode == 2 and payload.get('result') == 'error'
            and payload.get('stage') in ('preflight', 'connection', 'state_read')
            and payload.get('reason') in {'authentication_failed', 'timeout', 'dependency_unavailable',
                'private_credentials_unavailable', 'network_or_local_io_error', 'unreachable',
                'device_identity_mismatch'}):
        raise NotSent(details)
    if (result.returncode != 0 or payload.get('result') != 'verified'
            or payload.get('device') != 'led-strip' or payload.get('model') != 'L930-5'
            or payload.get('setting') != 'state' or payload.get('value') is not (mode == 'on')):
        raise LightingError(details)
    return True


def tick(state, faults, *, now, get_presence, apply, save, observe=None, monotonic=time.monotonic):
    state.update(validate_state(state))
    if (not cycle.finite(now)
            or any(state[k] is not None and now < state[k] for k in ('last_tick', 'last_busy'))):
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
        if observe is None or (state['last_busy'] is not None and now - state['last_busy'] < BUSY_COOLDOWN):
            return
        state['last_busy'] = now
        save(state)  # Bound failed read probes too; no permanent retry ceiling.
        try:
            actual = observe()
            if actual not in ('on', 'off'):
                return
            state.update(pending=False, last_mode=actual)
            faults.discard('led')
            save(state)
        except Exception:
            pass  # No new write while outcome/identity remain unobserved.
        return  # A later tick must obtain fresh presence before a new transition.
    target = 'on' if location == 'nearby' else 'off'
    if state['last_mode'] == target:
        faults.discard('busy')  # No transition is needed; retain the cooldown across flips.
        return
    if state['last_busy'] is not None and now - state['last_busy'] < BUSY_COOLDOWN:
        faults.add('busy')
        return
    faults.discard('busy')
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
            state.update(last_mode=target, pending=False, last_busy=None)
            faults.discard('led')
        else:
            faults.add('led')
    except DeviceBusy:
        state.update(pending=False, last_busy=now)
        faults.add('busy')
    except NotSent:
        state.update(pending=False, last_busy=now)
        faults.add('led')
    except Exception:
        state['last_busy'] = now
        faults.add('led')  # Read/reconcile next; never blindly replay the old request.
    save(state)


def run_once(store, *, now=time.time, get_presence=cycle.read_presence, apply=None, observe=None):
    observe = observe or read_power
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
             save=lambda s: store.save('led-state.json', s), observe=observe)
    except (cycle.CycleError, OSError, ValueError, TypeError, KeyError):
        faults.add('state')
    store.save('led-alerts.json', sorted(faults))
    order = ('state', 'presence', 'led', 'busy')
    kind = next((k for k in order if k in faults), None)
    old_kind = next((k for k in order if k in old), None)
    if kind is not None and kind != old_kind:
        return 'ERROR: ' + MESSAGES[kind], 1
    if old and not faults:
        return 'RECOVERED: LED strip automation checks are working again.', 0
    return '', 0
