"""Explicit private credential bundle. No import-time IO or auto-provisioning.

Provision only into a new owner-only directory after reviewing the supplied
certificate. Missing, partial, replaced, permissive or corrupt stores fail closed;
never recover by generating a new identity or by falling back to vendor control.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import pwd
import secrets
import stat

from . import client_policy as policy, control_protocol as protocol
from . import control_identity as identity

SCHEMA = 'jarvis-control-credentials/1'
MAX_BYTES = 32_768


class CredentialError(ValueError):
    pass


@dataclass(frozen=True)
class DefaultTarget:
    device_id: str
    incarnation: str
    epoch: int

    def __post_init__(self):
        if (not protocol._hex(self.device_id, protocol._DEVICE_ID)
                or not protocol._hex(self.incarnation, protocol._HEX32) or not protocol._epoch(self.epoch)):
            raise CredentialError('invalid-default-binding')


@dataclass(frozen=True)
class Bundle:
    enrollment: identity.Enrollment = field(repr=False)
    certificate: identity.TransportCertificate = field(repr=False)
    default: DefaultTarget | None = None


def default_directory():
    # HOME/CLI/env options cannot select an alternate credential/ownership realm.
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / 'Library/Application Support/JARVIS/control-client'


def _directory(path):
    if not isinstance(path, Path):
        raise CredentialError('private-credentials-unavailable')
    if not path.is_absolute():
        raise CredentialError('private-credentials-unavailable')
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise CredentialError('private-credentials-unavailable')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _same_directory(path, descriptor):
    opened, current = os.fstat(descriptor), path.lstat()
    if (stat.S_ISLNK(current.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            or current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o700):
        raise CredentialError('private-credentials-unavailable')


def _decode(raw):
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=protocol._pairs,
                          parse_constant=protocol._invalid_constant)
        if (type(data) is not dict or set(data) != {'schema', 'clientID', 'key', 'principal', 'cohorts', 'certificate', 'default'}
                or data['schema'] != SCHEMA or type(data['cohorts']) is not list
                or not 0 < len(data['cohorts']) <= len(policy.Cohort)
                or any(type(c) is not str for c in data['cohorts'])
                or len(set(data['cohorts'])) != len(data['cohorts'])):
            raise ValueError()
        enrollment = identity.Enrollment(identity.Credential(data['clientID'], data['key']),
            data['principal'], frozenset(policy.Cohort(c) for c in data['cohorts']))
        cert = data['certificate']
        if (type(cert) is not dict or set(cert) != {'profile', 'pythonVersion', 'sources'}
                or type(cert['pythonVersion']) is not list or len(cert['pythonVersion']) != 3
                or any(type(n) is not int for n in cert['pythonVersion'])
                or cert['profile'] != identity.PROFILE or type(cert['sources']) is not list
                or not 0 < len(cert['sources']) <= 64
                or any(type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str
                       or not Path(pair[0]).is_absolute() or not identity.hexadecimal(pair[1], identity.HEX64)
                       for pair in cert['sources'])
                or len({pair[0] for pair in cert['sources']}) != len(cert['sources'])):
            raise ValueError()
        certificate = identity.TransportCertificate(cert['profile'], tuple(cert['pythonVersion']),
                                                    tuple(tuple(pair) for pair in cert['sources']))
        default = data['default']
        if default is not None:
            if type(default) is not dict or set(default) != {'deviceID', 'incarnation', 'epoch'}:
                raise ValueError()
            default = DefaultTarget(default['deviceID'], default['incarnation'], default['epoch'])
            if policy.Cohort.PURIFIER not in enrollment.cohorts:
                raise ValueError()
        return Bundle(enrollment, certificate, default)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CredentialError('private-credentials-unavailable') from None


def load(directory):
    root = descriptor = None
    try:
        root = _directory(directory)
        descriptor = os.open('bundle.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_BYTES):
            raise CredentialError('private-credentials-unavailable')
        raw = os.read(descriptor, MAX_BYTES + 1)
        after = os.fstat(descriptor)
        named = os.stat('bundle.json', dir_fd=root, follow_symlinks=False)
        if (len(raw) != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)):
            raise CredentialError('private-credentials-unavailable')
        _same_directory(directory, root)
        return _decode(raw)
    except (OSError, ValueError):
        raise CredentialError('private-credentials-unavailable') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if root is not None:
            os.close(root)


def initialize(directory, *, certificate, cohorts, default=None):
    """Owner action only, not a listener/client recovery path. No overwrite/reset.

    A failure leaves a possibly incomplete, inaccessible bundle for explicit owner
    diagnosis. It is never automatically removed/reinitialized. No ledger/history
    is touched. The caller must separately establish writer fences and ownership.
    """
    if (type(certificate) is not identity.TransportCertificate or not certificate.valid()
            or type(cohorts) is not frozenset or not cohorts
            or any(type(c) is not policy.Cohort for c in cohorts)
            or (default is not None and (type(default) is not DefaultTarget or policy.Cohort.PURIFIER not in cohorts))):
        raise CredentialError('credential-provisioning-not-approved')
    root = descriptor = parent = None
    try:
        if not isinstance(directory, Path) or not directory.is_absolute():
            raise CredentialError('credential-provisioning-failed')
        # Existing trusted parent required; do not create an arbitrary directory tree.
        parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(parent)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise CredentialError('credential-provisioning-failed')
        os.mkdir(directory.name, 0o700, dir_fd=parent)
        root = _directory(directory)
        pinned = os.stat(directory.name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(root)
        if (pinned.st_dev, pinned.st_ino) != (opened.st_dev, opened.st_ino):
            raise CredentialError('credential-provisioning-failed')
        data = {'schema': SCHEMA, 'clientID': secrets.token_hex(16), 'key': secrets.token_hex(32),
            'principal': secrets.token_hex(32), 'cohorts': sorted(c.value for c in cohorts),
            'certificate': {'profile': certificate.profile, 'pythonVersion': list(certificate.python_version),
                            'sources': [list(pair) for pair in certificate.sources]},
            'default': None if default is None else {'deviceID': default.device_id,
                'incarnation': default.incarnation, 'epoch': default.epoch}}
        raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('ascii')
        if len(raw) > MAX_BYTES:
            raise CredentialError('credential-provisioning-failed')
        _decode(raw)
        descriptor = os.open('bundle.next', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
        with os.fdopen(descriptor, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(descriptor)
        os.rename('bundle.next', 'bundle.json', src_dir_fd=root, dst_dir_fd=root)
        os.fsync(root); os.fsync(parent)
        _same_directory(directory, root)
        return load(directory)
    except (OSError, ValueError):
        raise CredentialError('credential-provisioning-failed') from None
    finally:
        for fd in (descriptor, root, parent):
            if fd is not None:
                os.close(fd)
