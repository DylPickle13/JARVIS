"""Mandatory SDK-side ownership checkpoint candidate (stdlib, no import-time IO).

Copied identically into uninstalled staged vendor packages. It has NO legacy,
missing-file, timeout, environment-selected root or recovery fallback. The explicit
control_delegation/control_worker candidates compose this checkpoint; no live
entry point or current checkout/installed vendor controller selects it.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time

TOKEN_ENV = 'JARVIS_CONTROL_GRANT'
MAX_RECORD = 1_048_576
MAX_GRANT = 16_384
TTL_NS = 25_000_000_000
SKEW_NS = 2_000_000_000
HEX = re.compile(r'[0-9a-f]{64}\Z')
HEX32 = re.compile(r'[0-9a-f]{32}\Z')
MAX_INT = 2**53 - 1


class FenceError(RuntimeError):
    def __init__(self):
        super().__init__('Backend write permission unavailable; no direct fallback or automatic retry.')


def root_directory():
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / 'Library/Application Support/JARVIS/control-owner'


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise FenceError()
        value[key] = item
    return value


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


def _hex(value, pattern=HEX):
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_INT


def _private(metadata, mode, *, directory=False):
    if (metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != mode
            or (not stat.S_ISDIR(metadata.st_mode) if directory else
                not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1)):
        raise FenceError()


@contextmanager
def directory(path, *, parent=None):
    fd = None
    try:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            _private(os.fstat(fd), 0o700, directory=True)
        except (OSError, ValueError, TypeError):
            raise FenceError() from None
        yield fd
    finally:
        if fd is not None:
            os.close(fd)


def read(fd, name, maximum):
    source = None
    try:
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        before = os.fstat(source)
        _private(before, 0o600)
        if not 0 < before.st_size <= maximum:
            raise FenceError()
        raw = os.read(source, maximum + 1)
        after = os.fstat(source)
        named = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if (len(raw) != before.st_size or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)):
            raise FenceError()
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(FenceError()))
        if type(value) is not dict:
            raise FenceError()
        return value
    except (OSError, ValueError, TypeError, RecursionError):
        raise FenceError() from None
    finally:
        if source is not None:
            os.close(source)


def sync(fd):
    os.fsync(fd)
    if hasattr(fcntl, 'F_FULLFSYNC'):
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def write_new(fd, name, value):
    """Durable no-overwrite creation. Failure never refunds/removes the name."""
    raw = encode(value)
    if not 0 < len(raw) <= MAX_GRANT:
        raise FenceError()
    handle = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        _private(os.fstat(handle), 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(handle, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); sync(handle)
        os.fsync(fd)
        return handle  # Lease remains held through the caller's whole guarded operation.
    except BaseException:
        os.close(handle)
        raise


def _owner_alive(ledger):
    """Observe, never take over, the existing ledger owner's lifetime lock."""
    fd = None
    try:
        fd = os.open('owner.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=ledger)
        before = os.fstat(fd); _private(before, 0o600)
        named = os.stat('owner.lock', dir_fd=ledger, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino):
            raise FenceError()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # No owner held the lock. Release our probe, but never authorize a write.
        fcntl.flock(fd, fcntl.LOCK_UN)
        raise FenceError()
    finally:
        if fd is not None:
            os.close(fd)


def _current(ledger, grant):
    _owner_alive(ledger)
    record = read(ledger, 'record.json', MAX_RECORD)
    if (set(record) != {'schema', 'revision', 'incarnation', 'cohorts', 'records'}
            or type(record['schema']) is not int or record['schema'] != 1
            or not _integer(record['revision'], 1) or record['incarnation'] != grant['incarnation']
            or type(record['cohorts']) is not dict or set(record['cohorts']) != {'plugs', 'purifier'}
            or type(record['records']) is not list or not 0 < len(record['records']) <= 1024):
        raise FenceError()
    seen, previous = set(), 0
    for owner in record['cohorts'].values():
        if (type(owner) is not dict or set(owner) != {'epoch', 'mode'}
                or not _integer(owner['epoch']) or type(owner['mode']) is not str
                or owner['mode'] not in ('closed', 'draining', 'maintenance', 'api-owned')
                or owner['mode'] == 'api-owned' and owner['epoch'] in (0, MAX_INT)):
            raise FenceError()
    for row in record['records']:
        if (type(row) is not dict or set(row) != {'client', 'request_id', 'cohort', 'incarnation', 'epoch',
                'resource', 'command', 'action', 'outcome', 'unresolved', 'revision'}
                or not all(_hex(row[k]) for k in ('client', 'resource', 'command'))
                or not all(_hex(row[k], HEX32) for k in ('request_id', 'incarnation'))
                or type(row['cohort']) is not str or row['cohort'] not in record['cohorts']
                or not _integer(row['epoch'], 1) or row['epoch'] > record['cohorts'][row['cohort']]['epoch']
                or not _integer(row['revision'], 1) or not previous < row['revision'] <= record['revision']
                or type(row['outcome']) is not str
                or row['outcome'] not in ('reserved', 'acknowledged', 'verification-pending', 'delivery-unknown')
                or type(row['unresolved']) is not bool
                or row['outcome'] == 'reserved' and row['unresolved'] is not True
                or type(row['action']) is not str
                or row['action'] not in (('plug-on', 'plug-off', 'plug-toggle') if row['cohort'] == 'plugs' else ('purifier-set',))
                or (row['client'], row['request_id']) in seen):
            raise FenceError()
        previous = row['revision']
        seen.add((row['client'], row['request_id']))
    owner = record['cohorts'].get(grant['cohort'])
    if (type(owner) is not dict or set(owner) != {'epoch', 'mode'} or owner['mode'] != 'api-owned'
            or not _integer(owner['epoch'], 1) or owner['epoch'] != grant['epoch']):
        raise FenceError()
    matches = [row for row in record['records'] if type(row) is dict and row.get('revision') == grant['revision']]
    if len(matches) != 1:
        raise FenceError()
    row = matches[0]
    keys = {'client', 'request_id', 'cohort', 'incarnation', 'epoch', 'resource', 'command', 'action',
            'outcome', 'unresolved', 'revision'}
    if (set(row) != keys or row['outcome'] != 'reserved' or row['unresolved'] is not True
            or not _integer(row['epoch'], 1) or not _integer(row['revision'], 1)
            or any(row[key] != grant[key] for key in keys - {'outcome', 'unresolved'})):
        raise FenceError()
    now = time.monotonic_ns(), time.time_ns()
    age = now[0] - grant['monotonic'], now[1] - grant['wall']
    if min(age) < 0 or max(age) >= TTL_NS or abs(age[0] - age[1]) > SKEW_NS:
        raise FenceError()


def validate_grant(grant):
    expected = {'schema', 'token', 'client', 'request_id', 'cohort', 'incarnation', 'epoch', 'resource',
                'command', 'action', 'revision', 'monotonic', 'wall', 'call'}
    if (type(grant) is not dict or set(grant) != expected or type(grant['schema']) is not int or grant['schema'] != 1
            or not all(_hex(grant[k]) for k in ('token', 'client', 'resource', 'command'))
            or not all(_hex(grant[k], HEX32) for k in ('request_id', 'incarnation'))
            or not all(_integer(grant[k], 1) for k in ('epoch', 'revision'))
            or not all(type(grant[k]) is int and grant[k] >= 0 for k in ('monotonic', 'wall'))
            or grant['cohort'] not in ('plugs', 'purifier')
            or grant['action'] not in ('plug-on', 'plug-off', 'plug-toggle', 'purifier-set')
            or type(grant['call']) is not dict):
        raise FenceError()
    return grant


@contextmanager
def permission(call, *, phase='mutation', desired=None):
    """One immutable operation and one durable checkpoint per issued token.

    `worker` covers the entire private worker lifetime. `mutation` is independently
    consumed at the SDK boundary and carries the effective intended state, when
    known. Neither entry can be reused/refunded, including on cancellation/error.
    Directory selection is NOT an env/CLI option; only the token is inherited.
    """
    lease = None
    entered = False
    try:
        token = os.environ.get(TOKEN_ENV)
        if not _hex(token) or phase not in ('worker', 'mutation') or type(call) is not dict:
            raise FenceError()
        if desired is not None and type(desired) is not dict:
            raise FenceError()
        with directory(root_directory()) as root, directory('ledger', parent=root) as ledger, directory('grants', parent=root) as grants:
            grant = validate_grant(read(grants, token + '.json', MAX_GRANT))
            if grant['token'] != token or encode(grant['call']) != encode(call):
                raise FenceError()
            _current(ledger, grant)
            lease = write_new(grants, token + '.' + phase, {'schema': 1, 'grant': fingerprint(grant),
                'pid': os.getpid(), 'monotonic': time.monotonic_ns(), 'wall': time.time_ns(), 'desired': desired})
            # Closure, expiry, callback completion and owner death still veto a
            # just-consumed token. Never delete/refund it on failed final checks.
            _current(ledger, grant)
            for fd, name, parent in ((root, root_directory(), None), (ledger, 'ledger', root), (grants, 'grants', root)):
                opened = os.fstat(fd); named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                _private(named, 0o700, directory=True)
                if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                    raise FenceError()
            entered = True
            yield grant
    except (OSError, ValueError, TypeError, KeyError):
        if entered:
            raise  # Preserve SDK cancellation/rate-limit/verification behavior.
        raise FenceError() from None
    finally:
        if lease is not None:
            os.close(lease)


def reject_catalogue_change():
    raise FenceError()
