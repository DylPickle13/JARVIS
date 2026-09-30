"""Opt-in shared paired sensor reads; never fall back to a competing hub session."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import stat
import time

ALIASES = {'motion-sensor': 'T100', 'door-sensor': 'T110'}
MAX_AGE = 8.0


def read(path, alias, *, now=None, tick=None):
    base = {'ok': False, 'device': alias, 'securityAssessment': 'not_assessed',
            'observedAt': None, 'errorCode': 'shared_snapshot_unavailable'}
    try:
        if alias not in ALIASES or not Path(path).is_absolute():
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError()
            raw = f.read(8193)
        if len(raw) > 8192:
            raise ValueError()
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {'version', 'observed_at', 'tick', 'sensors'}:
            raise ValueError()
        if type(value['version']) is not int or value['version'] != 1:
            raise ValueError()
        at = datetime.fromisoformat(value['observed_at'])
        if at.utcoffset() is None:
            raise ValueError()
        if type(value['tick']) not in (int, float) or not math.isfinite(value['tick']):
            raise ValueError()
        age = (time.time() if now is None else now) - at.timestamp()
        elapsed = (time.monotonic() if tick is None else tick) - value['tick']
        if not 0 <= age <= MAX_AGE or not 0 <= elapsed <= MAX_AGE or abs(age - elapsed) > 2:
            raise ValueError()
        sensors = value['sensors']
        if type(sensors) is not dict or set(sensors) != set(ALIASES):
            raise ValueError()
        for name, model in ALIASES.items():
            row = sensors[name]
            if (type(row) is not dict or set(row) != {'model', 'state'} or row['model'] != model
                    or type(row['state']) is not bool):
                raise ValueError()
        return 200, {'ok': True, 'device': alias, 'model': ALIASES[alias],
                     'securityAssessment': 'not_assessed', 'observedAt': at.isoformat(),
                     'source': 'hub_snapshot', 'sharedReader': True, 'sampleAgeSeconds': age,
                     'readAttempts': 1, 'transientRecovered': False,
                     'data': {'motionDetected' if alias == 'motion-sensor' else 'isOpen': sensors[alias]['state'],
                              'batteryLow': None, 'rssi': None, 'radioFreshness': 'unknown'}}
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return 503, base
