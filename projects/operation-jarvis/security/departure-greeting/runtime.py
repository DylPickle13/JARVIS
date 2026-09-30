"""Private departure trial journal and configuration; never restore armed motion."""
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

ROOT = Path.home() / 'Library/Application Support/JARVIS/departure-greeting'
PHRASE = 'Have a good trip, sir.'


class TrialError(Exception):
    pass


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TrialError('private_directory_required')
    return path


def read_json(path, default=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return default
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TrialError('private_file_required')
        text = source.read(65537)
    if len(text) > 65536:
        raise TrialError('invalid_private_state')
    try:
        value = json.loads(text)
    except ValueError:
        raise TrialError('invalid_private_state') from None
    if type(value) is not dict:
        raise TrialError('invalid_private_state')
    return value


def save_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def config(root):
    value = read_json(root / 'config.json')
    required = {'version', 'enabled', 'motion_device', 'door_device', 'speaker_device', 'volume'}
    if (not value or set(value) != required or type(value['version']) is not int
            or value['version'] != 1 or type(value['enabled']) is not bool
            or type(value['volume']) is not int or not 1 <= value['volume'] <= 60
            or any(type(value[key]) is not str or not value[key]
                   for key in ('motion_device', 'door_device', 'speaker_device'))):
        raise TrialError('invalid_trial_configuration')
    return value


def default_state():
    return {'version': 1, 'pending': None, 'fault': None, 'last_attempt': None,
            'last_outcome': None, 'heartbeat': None, 'health': 'starting',
            'last_reason': 'baseline_required', 'read_count': 0,
            'candidate_count': 0, 'completed_count': 0, 'events': []}


class Journal:
    def __init__(self, root):
        self.root = private_dir(root)
        self.path = self.root / 'state.json'
        self.state = read_json(self.path)
        if self.state is None:
            raise TrialError('trial_not_installed')
        state = self.state
        if (set(state) != set(default_state()) or type(state.get('version')) is not int
                or state.get('version') != 1 or type(state.get('events')) is not list
                or len(state['events']) > 64
                or any(type(state.get(key)) is not int or state[key] < 0
                       for key in ('read_count', 'candidate_count', 'completed_count'))
                or state.get('pending') is not None and type(state['pending']) is not str
                or state.get('fault') is not None and type(state['fault']) is not str
                or state.get('last_attempt') is not None and (
                    type(state['last_attempt']) not in (int, float)
                    or not math.isfinite(state['last_attempt']))):
            raise TrialError('invalid_private_state')
        self.last_save_tick = 0.0

    @property
    def blocked(self):
        return self.state['pending'] is not None or self.state['fault'] is not None

    def flush(self):
        self.state['heartbeat'] = datetime.now(timezone.utc).isoformat()
        save_json(self.path, self.state)
        self.last_save_tick = time.monotonic()

    def event(self, reason, **fields):
        self.state['events'] = (self.state['events'] + [{
            'at': datetime.now(timezone.utc).isoformat(), 'reason': reason, **fields}])[-64:]
        self.state['last_reason'] = reason

    def reserve(self, attempt, now):
        if self.blocked:
            return False
        last = self.state['last_attempt']
        if last is not None and now - last < 120:
            return False  # Includes backward wall-clock jumps.
        self.state.update(pending=attempt, last_attempt=now, last_outcome='pending')
        self.event('playback_reserved')
        self.flush()  # Durable BEFORE starting a speaker worker.
        return True

    def finish(self, attempt, outcome):
        if self.state['pending'] != attempt:
            raise TrialError('attempt_mismatch')
        if outcome not in ('completed', 'expired_before_play', 'failed_before_play'):
            self.state.update(fault='playback_outcome_unknown', last_outcome='unknown')
            # Pending remains latched. No restart, config change, or retry clears it.
        else:
            self.state.update(pending=None, last_outcome=outcome)
            if outcome == 'completed':
                self.state['completed_count'] += 1
        self.event(self.state['last_outcome'])
        self.flush()


def singleton(root):
    fd = os.open(root / 'watcher.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise TrialError('private_lock_required')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise TrialError('watcher_already_running') from None
    return fd  # Caller keeps it open for process lifetime.


def installed_status(root):
    import person_gate
    gate = person_gate.status(root)
    if not (root / 'config.json').exists():
        return {'installed': False, 'enabled': False, 'running': False, **gate}
    value = config(root)
    state = read_json(root / 'state.json', {})
    age = None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['heartbeat'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    fresh = age is not None and 0 <= age < 30 and state.get('health') != 'stopped'
    blocked = state.get('pending') is not None or state.get('fault') is not None
    return {'installed': True, 'enabled': value['enabled'], 'running': fresh,
            'delivery_enabled': value['enabled'] and fresh and not blocked
                and gate['person_gate_verified'] and state.get('health') == 'observing',
            'health': state.get('health', 'unknown'), 'fault': state.get('fault'),
            'pending': state.get('pending') is not None,
            'last_reason': state.get('last_reason'), 'last_outcome': state.get('last_outcome'),
            'read_count': state.get('read_count', 0), 'candidate_count': state.get('candidate_count', 0),
            'completed_count': state.get('completed_count', 0), 'volume': value['volume'],
            'radio_freshness': 'unknown', 'physical_verification': 'pending', **gate}
