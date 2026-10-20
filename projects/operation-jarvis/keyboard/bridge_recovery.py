"""Retire a spent HID request only through the signed bridge's idle check.

Not a retry or lighting readback. The bridge refuses recovery while an OS output
callback remains outstanding. A later watcher tick selects current intent afresh.
No root-journal edits, direct-HID fallback, signature changes or service restarts.
Legacy local journals retire only under their original writer lock.
"""

def reconcile(request):
    status = request('status')
    if (type(status) is not dict or status.get('status') != 'ok'
            or status.get('device_available') is not True
            or type(status.get('pending')) is not bool):
        return False
    # Even pending=False needs the sender's explicit outstanding-operation check:
    # readiness alone is not evidence that an old IOKit callback is finished.
    result = request('acknowledge')
    return (type(result) is dict and result.get('status') == 'acknowledged'
            and result.get('hardware_write') is False)


def keyboard():
    import bridge_client
    if bridge_client.backend() == 'karabiner':
        return reconcile(bridge_client.request)
    # Direct CLI writes are synchronous, close HID before releasing this lock,
    # and subprocess timeout kills/reaps the child. Enumeration is NOT readback.
    import ajazz
    import fcntl
    import os
    from pathlib import Path
    fd = os.open(Path(ajazz.__file__).with_name('.lighting.lock'),
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = ajazz.keyboard_status(ajazz.hid_module())
        return (status.get('matching_interfaces') == 1 and status.get('connected') is True
                and status.get('hardware_write') is False)
    finally:
        os.close(fd)


def legacy_mouse_pending(root=None):
    import razer
    root = razer.STATE if root is None else root
    path = root / 'uncertain.json'
    return path.exists() or path.is_symlink()


def retire_legacy_mouse(root, request, *, now=None):
    """No HID I/O; preserve the old report/outcome under a diagnostic filename."""
    import fcntl
    import json
    import math
    import os
    import re
    import stat
    import time
    now = time.time() if now is None else now
    if not legacy_mouse_pending(root):
        return False
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Legacy mouse storage permissions need repair')
    fd = os.open(root / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Legacy mouse lock unavailable')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = os.open(root / 'uncertain.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(source) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 4096:
                raise RuntimeError('Legacy mouse journal unavailable')
            value = json.load(stream)
        if (type(value) is not dict or set(value) != {'report', 'time'}
                or not isinstance(value['report'], str) or not re.fullmatch('[0-9a-f]{180}', value['report'])
                or type(value['time']) not in (int, float) or not math.isfinite(value['time'])):
            raise RuntimeError('Legacy mouse journal metadata needs repair')
        if now - value['time'] < 60 or not reconcile(request):
            return False
        os.replace(root / 'uncertain.json', root / 'retired-uncertain.json')
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        os.close(fd)


def mouse():
    import razer
    import razer_bridge
    if legacy_mouse_pending():
        return retire_legacy_mouse(razer.STATE, razer_bridge.request)
    return reconcile(razer_bridge.request)
