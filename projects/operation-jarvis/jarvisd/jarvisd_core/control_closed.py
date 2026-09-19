"""Write-closed recovery role; never restores old unfenced vendor wrappers.

Requires independently retained SDK source pins, not hashes computed from live
files to bypass a failure. Existing healthy ledger is opened CLOSED and held;
missing/corrupt history is not created/repaired. This is not API activation.
"""
import json
import os
import stat
from pathlib import Path

from .control_http import ControlHTTPServer
from .control_identity import source_digest, hexadecimal, HEX64
from .control_ledger import ControlLedger, LedgerError
from . import vendor_fence

# Retained from the independently tested delegation-stage artifact. An arbitrary
# manifest may NOT bless the old unfenced wrappers merely by adding helper files.
FENCED_MUTATORS = {
    'smart-plug/smart_plug/kasa_client.py': 'b06582ec8cced26c91984458da957568e55257b7c52298f29e4d903084a8c69f',
    'air-purifier/air_purifier/write_safety.py': '69ea80798bc7e6d0055c59edc358b380dd9271d3e70fc5732989a1ed622b3a7b',
}
REQUIRED = frozenset({
    'smart-plug/smart_plug/kasa_client.py', 'smart-plug/smart_plug/vendor_fence.py',
    'air-purifier/air_purifier/write_safety.py', 'air-purifier/air_purifier/vendor_fence.py',
})
ALLOWED = REQUIRED | frozenset({
    'smart-plug/smart_plug/__init__.py', 'smart-plug/smart_plug/cli.py', 'smart-plug/smart_plug/config.py',
    'air-purifier/air_purifier/__init__.py', 'air-purifier/air_purifier/cli.py',
    'air-purifier/air_purifier/config.py', 'air-purifier/air_purifier/cooldown.py',
    'air-purifier/air_purifier/vesync_client.py',
})


class ClosedRoleError(RuntimeError):
    pass


def verify_fences(operation, pins):
    if (type(pins) is not dict or set(pins) != ALLOWED
            or any(not hexadecimal(value, HEX64) for value in pins.values())
            or any(pins[path] != expected for path, expected in FENCED_MUTATORS.items())):
        raise ClosedRoleError('closed-role-fence-manifest-invalid')
    operation = Path(operation)
    for relative, expected in pins.items():
        try:
            if source_digest(operation / relative) != expected:
                raise ClosedRoleError('closed-role-vendor-fence-drift')
        except (OSError, ValueError):
            raise ClosedRoleError('closed-role-vendor-fence-unavailable') from None
    # A malformed build must not silently pin unrelated helper copies.
    helper = source_digest(Path(vendor_fence.__file__))
    if any(pins[path] != helper for path in REQUIRED if path.endswith('/vendor_fence.py')):
        raise ClosedRoleError('closed-role-fence-helper-mismatch')


def run_closed(daemon, *, pins, root=None):
    """Keep status/services available, reject all v1 device writes before dispatch.

    The deployment owner still must establish real process/worker drain and pair
    these pins with the reviewed stage. This function never kills workers or
    restores config/events/ledger snapshots. A held/busy store refuses startup.
    """
    verify_fences(daemon.OPERATION_ROOT, pins)
    root = vendor_fence.root_directory() if root is None else Path(root)
    store = None
    ledger = root / 'ledger'
    if ledger.exists() or ledger.is_symlink():
        try:
            store = ControlLedger.open(ledger)  # Advancing incarnation/epochs; CLOSED.
        except LedgerError as error:
            # Do not mistake another active owner or invalid history for absence.
            raise ClosedRoleError('closed-role-ledger-unavailable') from error
    original = daemon.ThreadingHTTPServer
    daemon.ThreadingHTTPServer = ControlHTTPServer  # Bounded, v1 writes closed, no v2 endpoint.
    try:
        return daemon.main()
    finally:
        daemon.ThreadingHTTPServer = original
        if store is not None:
            store.close()


def load_pins(path):
    path = Path(path)
    parent = None
    try:
        if not path.is_absolute():
            raise ValueError()
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(parent)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError()
        data = vendor_fence.read(parent, path.name, 16384)
        if set(data) != {'schema', 'files'} or type(data['schema']) is not int or data['schema'] != 1:
            raise ValueError()
        return data['files']
    except (OSError, ValueError, vendor_fence.FenceError):
        raise ClosedRoleError('closed-role-fence-manifest-unavailable') from None
    finally:
        if parent is not None:
            os.close(parent)
