"""Bounded, read-only frame probe. No import-time I/O or HTTP/control surface.

Worker/interpreter paths are owner configuration, never request parameters.
The worker reuses the commissioned controller's exact identity and legacy consent.
"""
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

TIMEOUT = 6.0
MAX_OUTPUT = 4096
UNKNOWN_REASONS = frozenset({"configuration_unavailable", "transport_unavailable",
    "identity_unverified", "device_busy", "worker_timeout", "worker_failed",
    "invalid_output", "check_failed"})


def configure(registry, env):
    """Pure startup opt-in validation; no reads, imports of ADB or processes."""
    if not any(row['kind'] == 'frame' for row in registry):
        return None
    worker = env.get('JARVISD_FRAME_HEALTH_WORKER', '')
    python = env.get('JARVISD_FRAME_HEALTH_PYTHON', '')
    if (not isinstance(worker, str) or not worker or not Path(worker).is_absolute()
            or Path(worker).name != 'health_worker.py'
            or not isinstance(python, str) or not python or not Path(python).is_absolute()):
        raise ValueError('Frame monitoring requires explicit absolute worker and approved Python paths')
    return FrameProbe(worker, python)


def collect(worker, python):
    """One fixed subprocess, bounded output and total deadline, no retries."""
    process = None
    try:
        # Code is public but must be owner-controlled and not symlink-replaced.
        for path, directory in ((Path(worker).parent, True), (Path(worker), False)):
            info = path.lstat()
            kind = stat.S_ISDIR if directory else stat.S_ISREG
            if not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                return None, 'configuration_unavailable'
        # Reviewed venv interpreter symlinks are intentional; do not replace them.
        if not os.access(python, os.X_OK):
            return None, 'configuration_unavailable'
        deadline = time.monotonic() + TIMEOUT
        process = subprocess.Popen([python, '-B', worker, '--check'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(Path(worker).parent), close_fds=True, start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        data = bytearray()
        with selectors.DefaultSelector() as poller:
            os.set_blocking(process.stdout.fileno(), False)
            poller.register(process.stdout, selectors.EVENT_READ)
            while poller.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, 'worker_timeout'
                for key, _ in poller.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, min(4096, MAX_OUTPUT + 1 - len(data)))
                    if not chunk:
                        poller.unregister(key.fileobj)
                    else:
                        data.extend(chunk)
                        if len(data) > MAX_OUTPUT:
                            return None, 'invalid_output'
                if not poller.get_map() and process.poll() is None:
                    time.sleep(min(remaining, 0.01))
        if process.returncode != 0:
            return None, 'worker_failed'
        result = json.loads(data.decode('utf-8'))
        if type(result) is not dict or set(result) != {'ok', 'reason'}:
            return None, 'invalid_output'
        ok, reason = result['ok'], result['reason']
        if ok is True and reason is None:
            return True, None
        if ok is False and reason == 'read_failed':
            return False, reason
        if ok is None and type(reason) is str and reason in UNKNOWN_REASONS:
            return None, reason
        return None, 'invalid_output'
    except (OSError, ValueError, TypeError, RecursionError):
        return None, 'worker_failed'
    finally:
        if process is not None:
            # Also close descendants that may retain the pipe after worker exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                process.wait()
                process.stdout.close()


class FrameProbe:
    def __init__(self, worker, python, *, collector=collect):
        self.worker, self.python, self.collector = worker, python, collector

    def __call__(self, row):
        # Registry rows select the one commissioned frame, never transport args.
        if row.get('kind') != 'frame':
            return None, 'configuration_unavailable'
        return self.collector(self.worker, self.python)
