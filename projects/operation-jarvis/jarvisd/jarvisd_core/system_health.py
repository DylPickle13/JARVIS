"""Sanitized chart projection of cached state; no collectors, I/O or side effects.

Chart colours describe observation/service health, never physical connectivity.
Expired evidence is unknown, not a prolonged healthy or physical-offline claim.
Overall health includes the six dashboard collectors and configured sensor-read
health when supplied. Optional stopped services are inactive; successful periodic
services may be idle. Sensor state and radio freshness are never inferred.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .state import StateCoordinator

COMPONENTS = ('services', 'pi', 'network', 'plugs', 'purifier', 'codexQuota', 'security', 'devices', 'overall')
MAX_COMPONENTS = 32
SERVICE_ID = re.compile(r'service:[A-Za-z0-9_-]{1,48}\Z')
STATES = ('inactive', 'healthy', 'unknown', 'degraded', 'unavailable')
REASONS = frozenset({
    'current', 'optional_inactive', 'metadata_missing', 'timestamp_invalid',
    'observation_expired', 'collector_failed', 'loading', 'details_missing',
    'required_service_missing', 'required_service_stopped', 'service_read_failed',
    'scheduled_check_failed', 'scheduled_completion_unknown', 'service_state_unknown',
    'service_not_ready', 'service_readiness_unknown',
    'device_observation_failed', 'device_observation_unknown', 'snapshot_failed',
    'inventory_limit', 'monitoring_disabled', 'not_checked',
    'sensor_read_failed', 'sensor_read_unknown',
})
LIMITS = StateCoordinator.DEFAULT_FRESHNESS_LIMITS


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.timestamp() if date.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def observation(state, reason, *, source=None, valid_until=None):
    return {'state': state, 'reason': reason, 'sourceObservedAt': source, 'validUntil': valid_until}


def aggregate(rows):
    if not rows:
        return observation('unknown', 'details_missing')
    # Known failure wins over missing evidence, but uncertainty can never be green.
    worst = max(rows, key=lambda r: STATES.index(r['state']))
    sources = [r['sourceObservedAt'] for r in rows if r['sourceObservedAt'] is not None]
    limits = [r['validUntil'] for r in rows if r['validUntil'] is not None]
    return observation(worst['state'], worst['reason'], source=min(sources) if sources else None,
                       valid_until=min(limits) if limits else None)


def _collector(snapshot, name, now):
    meta = snapshot.get('subsystemsMeta', {}).get(name)
    if not isinstance(meta, dict):
        return observation('unknown', 'metadata_missing')
    generated = timestamp(snapshot.get('generatedAt'))
    source = timestamp(meta.get('updatedAt'))
    age = meta.get('ageSeconds')
    if meta.get('error') == 'loading' or (meta.get('refreshing') is True and age is None):
        return observation('unknown', 'loading')
    if meta.get('ok') is False or meta.get('error'):
        # Retain the last-good timestamp, but never retain a green failure.
        return observation('unavailable', 'collector_failed',
                           source=source if source is not None and source <= now else None)
    if (generated is None or generated > now or source is None or source > now
            or not number(age)):
        return observation('unknown', 'timestamp_invalid')
    # Both clocks must agree that evidence is recent. Rewrapping an old snapshot
    # with a new generation date cannot rejuvenate its collector observations.
    age = max(age + now - generated, now - source)
    limit = LIMITS[name]
    if meta.get('stale') is True or age > limit:
        return observation('unknown', 'observation_expired', source=source)
    if meta.get('ok') is not True or meta.get('stale') is not False:
        return observation('unknown', 'metadata_missing', source=source)
    return observation('healthy', 'current', source=source, valid_until=now + limit - age)


def _service(data):
    if not isinstance(data, dict):
        return observation('unknown', 'details_missing')
    if data.get('ok') is not True:
        return observation('unavailable', 'service_read_failed')
    critical = data.get('critical')
    if critical is True and data.get('configured') is False:
        return observation('unavailable', 'required_service_missing')
    if data.get('executionMode') == 'periodic':
        if data.get('loaded') is False:
            return (observation('unavailable', 'required_service_missing') if critical is True else
                    observation('inactive', 'optional_inactive') if critical is False else
                    observation('unknown', 'service_state_unknown'))
        if data.get('loaded') is not True:
            return observation('unknown', 'service_state_unknown')
        if any(data.get(field) is not None and type(data[field]) is not int
               for field in ('lastExitSignal', 'lastExitCode')):
            return observation('unknown', 'scheduled_completion_unknown')
        if (data.get('lastExitSignal') is not None
                or (data.get('lastExitCode') is not None and data.get('lastExitCode') != 0)):
            return observation('degraded', 'scheduled_check_failed')
        if data.get('running') is True or (data.get('running') is False and data.get('lastExitCode') == 0):
            return observation('healthy', 'current')
        return observation('unknown', 'scheduled_completion_unknown')
    if data.get('running') is True:
        if 'ready' in data:
            if data['ready'] is False:
                return observation('degraded', 'service_not_ready')
            if data['ready'] is not True:
                return observation('unknown', 'service_readiness_unknown')
        return observation('healthy', 'current')
    if critical is False and data.get('running') is False:
        return observation('inactive', 'optional_inactive')
    if critical is True and data.get('running') is False and data.get('executionMode') == 'continuous':
        return observation('unavailable', 'required_service_stopped')
    return observation('unknown', 'service_state_unknown')


def security_reads(observations, aliases, *, enabled, ttl, now):
    """Project existing sensor-read evidence only; no device I/O or contact state."""
    if not enabled or not aliases:
        return observation('inactive', 'monitoring_disabled')
    if not isinstance(observations, dict) or not number(ttl) or ttl == 0 or len(aliases) > 8:
        return observation('unknown', 'sensor_read_unknown')
    rows = []
    for alias in aliases:
        row = observations.get(alias)
        if not isinstance(row, dict):
            rows.append(observation('unknown', 'not_checked'))
            continue
        source = timestamp(row.get('lastAttemptAt'))
        age = row.get('ageSeconds')
        if source is None or source > now or not number(age):
            rows.append(observation('unknown', 'timestamp_invalid'))
            continue
        age = max(age, now-source)
        if row.get('reason') == 'observation_expired' or age > ttl:
            rows.append(observation('unknown', 'observation_expired', source=source))
        elif row.get('availability') == 'unavailable':
            rows.append(observation('unavailable', 'sensor_read_failed', source=source))
        elif row.get('availability') == 'available' and row.get('reason') is None:
            rows.append(observation('healthy', 'current', source=source,
                                    valid_until=now+ttl-age))
        else:
            rows.append(observation('unknown', 'sensor_read_unknown', source=source))
    return aggregate(rows)


def project(snapshot, now, *, security=None):
    """At most 32 components; optional security is a sanitized cache projection."""
    if not isinstance(snapshot, dict):
        snapshot = {}
    # Malformed containers from an older/failed backend must fail closed.
    snapshot = {**snapshot,
                'subsystems': snapshot.get('subsystems') if isinstance(snapshot.get('subsystems'), dict) else {},
                'subsystemsMeta': snapshot.get('subsystemsMeta') if isinstance(snapshot.get('subsystemsMeta'), dict) else {}}
    rows = {name: _collector(snapshot, name, now) for name in COMPONENTS[:6]}
    if security is not None:
        rows['security'] = security
    service_slots = MAX_COMPONENTS-len(rows)-2  # Reserve devices and overall.
    subsystems = snapshot['subsystems']
    services = subsystems.get('services', {})
    inventory = services.get('services') if isinstance(services, dict) else None
    if isinstance(inventory, dict):
        keys = sorted(key for key in inventory if isinstance(key, str) and SERVICE_ID.fullmatch('service:' + key))
        service_rows = []
        for key in keys[:service_slots]:
            base = rows['services']
            if base['state'] == 'healthy':
                row = {**_service(inventory[key]), 'sourceObservedAt': base['sourceObservedAt'],
                       'validUntil': base['validUntil']}
            else:
                row = dict(base)
            rows['service:' + key] = row
            service_rows.append(row)
        if rows['services']['state'] == 'healthy':
            if len(keys) != len(inventory) or len(keys) > service_slots:
                service_rows.append(observation('unknown', 'inventory_limit'))
            if service_rows:
                rows['services'] = aggregate(service_rows)
    elif rows['services']['state'] == 'healthy':
        rows['services'] = observation('unknown', 'details_missing')

    for name in ('plugs', 'purifier'):
        if rows[name]['state'] != 'healthy':
            continue
        data = subsystems.get(name)
        items = None
        if isinstance(data, dict):
            items = data.get('plugs') if name == 'plugs' else data.get('devices', {'default': data})
        if not isinstance(items, dict) or (name == 'purifier' and not items):
            state, reason = 'unknown', 'details_missing'
        elif any(isinstance(item, dict) and (item.get('ok') is False or item.get('stale') is True)
                 for item in items.values()):
            state, reason = 'unavailable', 'device_observation_failed'
        elif any(not isinstance(item, dict) or item.get('ok') is not True or item.get('stale') is not False
                 or (name == 'plugs' and not isinstance(item.get('isOn'), bool))
                 or (name == 'purifier' and item.get('verificationPending') is True)
                 for item in items.values()):
            state, reason = 'unknown', 'device_observation_unknown'
        else:
            continue
        rows[name] = {**rows[name], 'state': state, 'reason': reason}
    sensor_rows = [rows['security']] if 'security' in rows else []
    rows['devices'] = aggregate([rows['plugs'], rows['purifier'], *sensor_rows])
    rows['overall'] = aggregate([rows[name] for name in COMPONENTS[:6]] + sensor_rows)
    if snapshot.get('ok') is False:
        rows['overall'] = observation('unavailable', 'snapshot_failed')
    return rows
