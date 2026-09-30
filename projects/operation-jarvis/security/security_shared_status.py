"""Read-only CLI projection of the departure watcher's private paired snapshot.

No network, lock acquisition, SDK initialization, or direct-read fallback.
"""
from pathlib import Path
import sys

# Reuse the dashboard's strict validator rather than maintain a second policy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'jarvisd'))
from jarvisd_core import security_snapshot

ALIASES = security_snapshot.ALIASES


def read(alias, *, path=None, now=None, tick=None):
    path = path or Path.home() / 'Library/Application Support/JARVIS/departure-greeting/sensor-snapshot.json'
    code, value = security_snapshot.read(path, alias, now=now, tick=tick)
    if code != 200:
        return {'result': 'error', 'reason': 'shared_snapshot_unavailable',
                'stage': 'state_read', 'device': alias,
                'security_assessment': 'not_assessed'}
    feature, key = ('motion_detected', 'motionDetected') if alias == 'motion-sensor' else ('is_open', 'isOpen')
    return {'result': 'read_succeeded', 'device': alias, 'model': value['model'],
            'observed_at': value['observedAt'], 'hub_snapshot_at': value['observedAt'],
            'shared_reader': True, 'radio_freshness': 'unknown', 'sensor_updated_at': None,
            'security_assessment': 'not_assessed',
            'features': {feature: {'value': value['data'][key]},
                         'battery_low': {'value': None, 'status': 'unknown'},
                         'rssi': {'value': None, 'status': 'unknown'}}}
