"""Monitoring projections: HTTP 200/503 from cached health, never device reads."""
import re
from .read_health import fresh


def unavailable(reason):
    return 503, {'ok': False, 'availability': 'unavailable', 'reason': reason,
                 'scope': 'status_availability'}


def security(alias, *, enabled, configured, observations):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', alias) or alias not in configured:
        return 404, {'ok': False, 'error': 'unknown monitor'}
    if not enabled:
        return unavailable('monitoring_disabled')
    row = observations.get(alias)
    if not row:
        return unavailable('not_checked')
    available = row.get('availability') == 'available'
    return (200 if available else 503), {
        'ok': available, 'availability': 'available' if available else 'unavailable',
        'scope': 'hub_snapshot_read_availability', 'radioFreshness': 'unknown',
        'lastAttemptAt': row.get('lastAttemptAt'), 'lastSuccessAt': row.get('lastSuccessAt'),
        'ageSeconds': row.get('ageSeconds'),
        'reason': row.get('reason'),
    }


def integration(name, snapshot, *, observation_limit=None):
    meta = snapshot.get('subsystemsMeta', {}).get(name)
    if not isinstance(meta, dict):
        return 404, {'ok': False, 'error': 'unknown monitor'}
    available = fresh(meta) and meta.get('stale') is False
    if observation_limit is not None:
        # oMLX's six-second UI activity freshness is not its idle read-health
        # window. Never loosen the actual UI/data contract or ignore read errors.
        age = meta.get('ageSeconds')
        available = (meta.get('ok') is True and not meta.get('error')
                     and type(age) in (int, float) and 0 <= age <= observation_limit)
    return (200 if available else 503), {
        'ok': available, 'availability': 'available' if available else 'unavailable',
        'scope': 'recent_read_health' if observation_limit is not None else 'status_availability',
        'observedAt': meta.get('updatedAt'),
        'ageSeconds': meta.get('ageSeconds'),
        'reason': None if available else 'data_unavailable_or_expired',
    }
