"""Shared unsolicited-speech policy. Stdlib only; no I/O or threads on import.

Legacy installations stay unchanged until explicitly initialized. Activated
installations must set JARVIS_AUTOMATIC_VOICE_POLICY_REQUIRED=1 in every producer;
missing/corrupt private state then suppresses speech, never enables it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

DEFAULT_ROOT = Path.home() / 'Library/Application Support/JARVIS/home-automations'
HEX = re.compile(r'^[0-9a-f]{32}$')
SOURCES = frozenset({'computer-arrival', 'doorbell-departure'})


class PolicyError(ValueError):
    pass


def root_path():
    return Path(os.environ.get('JARVIS_HOME_AUTOMATIONS_ROOT', str(DEFAULT_ROOT)))


def directory(root):
    info = Path(root).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PolicyError('Private automation storage unavailable.')


def read_json(root, name):
    directory(root)
    fd = os.open(Path(root) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PolicyError('Private automation state unavailable.')
        data = stream.read(262145)
    if len(data) > 262144:
        raise PolicyError('Automation state too large.')
    result = json.loads(data)
    if type(result) is not dict:
        raise PolicyError('Invalid automation state.')
    return result


def save_json(root, name, value):
    directory(root)
    fd, temporary = tempfile.mkstemp(prefix='.automation-', dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, Path(root) / name)
        fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def locked(root):
    directory(root)
    fd = os.open(Path(root) / 'policy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PolicyError('Private automation lock unavailable.')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Policy:
    enabled: bool
    revision: str


def current(root=None, *, legacy=None):
    """None is unknown/denied. Legacy is only a pre-activation compatibility mode."""
    root = root_path() if root is None else Path(root)
    if legacy is None:
        legacy = os.environ.get('JARVIS_AUTOMATIC_VOICE_POLICY_REQUIRED', '0') == '0'
    try:
        if legacy and not root.exists() and not root.is_symlink():
            return Policy(True, 'legacy')
        value = read_json(root, 'voice.json')
        if (set(value) != {'version', 'enabled', 'revision'} or type(value['version']) is not int
                or value['version'] != 1 or type(value['enabled']) is not bool
                or type(value['revision']) is not str or not HEX.fullmatch(value['revision'])):
            return None
        return Policy(value['enabled'], value['revision'])
    except (OSError, ValueError, TypeError):
        return None


def admitted(source, revision=None):
    """Internal source classification only; interactive cues never use this gate."""
    value = current()
    return (source in SOURCES and value is not None and value.enabled
            and (revision is None or value.revision == revision))


def initialize(root, *, enabled, barn_door_ref):
    """Explicit deployment step only. Never replaces an existing installation."""
    if type(enabled) is not bool or not re.fullmatch(r'[0-9a-f]{16}', barn_door_ref):
        raise PolicyError('Invalid automation initialization.')
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    with locked(root):
        save_json(root, 'voice.json', {'version': 1, 'enabled': enabled, 'revision': secrets.token_hex(16)})
        save_json(root, 'binding.json', {'version': 1, 'barnDoorRef': barn_door_ref})
        save_json(root, 'requests.json', {'version': 1, 'requests': {}})


def set_enabled(root, enabled, revision):
    """Caller holds policy.lock; admission and persistence share that lock."""
    value = current(root, legacy=False)
    if value is None or value.revision != revision or type(enabled) is not bool:
        raise PolicyError('Automatic Voice changed or is unavailable; refresh first.')
    if value.enabled != enabled:
        save_json(root, 'voice.json', {'version': 1, 'enabled': enabled, 'revision': secrets.token_hex(16)})
    return current(root, legacy=False)
