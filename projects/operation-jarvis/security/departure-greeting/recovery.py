"""Pure retry policy for READ-ONLY sensor recovery. Never retries a mutation.

A fault is diagnostic, not an acknowledgment requirement. Successful recovery
requires three new paired reads; unknown exception classes get slower probes.
"""
import hashlib
import random
import re
import runtime


def validate_pins(pins):
    if (not pins or set(pins) != {'version', 'hub', 'sensors'} or type(pins['version']) is not int or pins['version'] != 1
            or type(pins['hub']) is not str or not re.fullmatch('[0-9a-f]{64}', pins['hub'])
            or type(pins['sensors']) is not list or len(pins['sensors']) != 2
            or any(type(x) is not str or not re.fullmatch('[0-9a-f]{64}', x) for x in pins['sensors'])
            or pins['sensors'][0] == pins['sensors'][1]):
        raise runtime.TrialError('reviewed_sensor_identity_required')
    return pins


def verify_identity(root, reader):
    """Use reviewed pins, never learn/replace identity during outage recovery."""
    pins = validate_pins(runtime.read_json(root / 'sensor-identity.json'))
    mac = re.sub('[:-]', '', reader.hub_info.get('mac', '')).lower()
    if (reader.hub_info.get('device_model') != 'H200' or not re.fullmatch('[0-9a-f]{12}', mac)
            or hashlib.sha256(mac.encode()).hexdigest() != pins['hub']
            or [hashlib.sha256(x.encode()).hexdigest() for x in (reader.motion_id, reader.door_id)] != pins['sensors']):
        raise runtime.TrialError('sensor_identity_changed')

READ_FAULTS = frozenset({'sensor_read_requires_review', 'sensor_read_problem'})


def transient(exc):
    from kasa.exceptions import AuthenticationError, KasaException, _ConnectionError, _RetryableError
    # Authentication and explicit device errors are real problems even when a
    # wrapper happens to carry a transport cause. Do not classify by message text.
    if isinstance(exc, AuthenticationError) or getattr(exc, 'error_code', None) is not None:
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, _ConnectionError, _RetryableError)):
        return True
    return (type(exc) is KasaException and isinstance(exc.__cause__, (TimeoutError, ConnectionError, OSError)))


def delay(failures, *, transport, jitter=random.random):
    if type(failures) is not int or failures < 1:
        raise ValueError('positive read failure count required')
    # Constant space, no exponent overflow or retry exhaustion. Slow probing of
    # invalid credentials/configuration cannot dispatch an action or renew auth.
    base = min(60, 2 ** min(failures, 6)) if transport else 300
    return min(60 if transport else 300, base * (1 + 0.2 * jitter()))
