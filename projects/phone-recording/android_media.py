"""Read-only Android media fingerprints with bounded, size-aware hash timeouts."""
import math
import re


def hash_timeout(size):
    if type(size) is not int or size <= 0:
        raise ValueError('Invalid Android media size')
    # Budget at least 4 MiB/s plus setup; never use the 15s control timeout.
    return min(3600, max(60, 30 + math.ceil(size / (4 * 1024**2))))


def fingerprint(adb, phone, remote):
    size = int(adb(phone, 'shell', 'stat', '-c', '%s', remote).strip())
    timeout = hash_timeout(size)
    sha = adb(phone, 'shell', 'sha256sum', remote, timeout=timeout).split()[0]
    if not re.fullmatch('[0-9a-f]{64}', sha):
        raise RuntimeError('Invalid device hash')
    if int(adb(phone, 'shell', 'stat', '-c', '%s', remote).strip()) != size:
        raise RuntimeError('Android media size changed during fingerprinting')
    return sha, size
