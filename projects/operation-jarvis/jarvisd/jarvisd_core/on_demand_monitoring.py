"""Passive read-health projections; no I/O, retries, incidents or credentials."""
from .monitoring import integration

ROUTES = {
    'presence': '/api/v1/presence',
    'room-audio-pi': '/api/v1/room-audio/pi',
    'room-audio-mac': '/api/v1/room-audio/mac',
}
NAMES = ('purifier', *ROUTES)


def observations(snapshot, endpoint_rows):
    result = {}
    code, purifier = integration('purifier', snapshot)
    result['purifier'] = {
        'availability': 'available' if code == 200 else 'unavailable',
        'reason': purifier.get('reason', 'not_checked'),
        'observedAt': purifier.get('observedAt'),
        'ageSeconds': purifier.get('ageSeconds'),
    }
    for name, route in ROUTES.items():
        row = endpoint_rows.get(route, {})
        result[name] = {
            'availability': 'available' if row.get('availability') == 'available' else 'unavailable',
            'reason': row.get('reason', 'not_checked'),
            'observedAt': row.get('lastAttemptAt'),
            'ageSeconds': row.get('ageSeconds'),
        }
    for row in result.values():
        row.update(mode='on_demand', scope='recent_read_availability',
                   backgroundPolled=False, incidentTracking=False)
    return result
