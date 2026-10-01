"""One explicit read through the existing private CLI; no cache or background work."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time

from .work_metrics import WorkMetrics
METRICS = WorkMetrics(('reads',))

MAX_OUTPUT = 128 * 1024
# CLI owns sensor-read retries within 60 seconds, plus disconnect cleanup.
# Never add subprocess retries here (including for non-sensor reads).
TIMEOUT = 65.0
_READ_LOCK = threading.Lock()
ERRORS = frozenset({"device_busy", "sensor_missing_or_ambiguous", "device_identity_mismatch",
    "unknown_device", "unreachable", "authentication_failed", "timeout", "operation_failed",
    "dependency_unavailable", "private_credentials_unavailable", "invalid_device_registry",
    "network_or_local_io_error", "invalid_output", "output_limit", "worker_failed"})


class ReadError(Exception):
    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in ERRORS else "operation_failed"
        super().__init__(self.code)


def run_cli(cli: Path, alias: str) -> dict:
    """Fixed argv, bounded streaming output/deadline, private stderr, no retry."""
    process = None
    try:
        process = subprocess.Popen(
            [str(cli), "--json", "status", alias], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(cli.parent),
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                 "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            start_new_session=True, close_fds=True)
        deadline = time.monotonic() + TIMEOUT
        raw = bytearray()
        with selectors.DefaultSelector() as poller:
            os.set_blocking(process.stdout.fileno(), False)
            poller.register(process.stdout, selectors.EVENT_READ)
            while poller.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReadError("timeout")
                for key, _ in poller.select(min(remaining, 0.05)):
                    chunk = os.read(key.fileobj.fileno(), min(8192, MAX_OUTPUT + 1 - len(raw)))
                    if not chunk:
                        poller.unregister(key.fileobj)
                    else:
                        raw.extend(chunk)
                        if len(raw) > MAX_OUTPUT:
                            raise ReadError("output_limit")
                if not poller.get_map() and process.poll() is None:
                    time.sleep(min(remaining, 0.05))
        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise ReadError("invalid_output") from None
        if type(result) is not dict:
            raise ReadError("invalid_output")
        if result.get("result") == "error":
            raise ReadError(result.get("reason"))
        if process.returncode != 0:
            raise ReadError("worker_failed")
        return result
    except OSError:
        raise ReadError("network_or_local_io_error") from None
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                process.wait()
                process.stdout.close()


def _feature(features, name, kind):
    row = features.get(name)
    if type(row) is not dict or row.get("status") is not None:
        return None
    value = row.get("value")
    if type(value) is not kind or (kind is int and not -127 <= value <= 0):
        return None
    return value


def _lighting_data(features):
    """Strict public lighting projection; missing/errored fields stay unknown."""
    def value(name):
        row = features.get(name)
        return row.get('value') if type(row) is dict and row.get('status') is None else None

    def number(name, minimum, maximum):
        raw = value(name)
        return raw if type(raw) is int and minimum <= raw <= maximum else None

    hsv = value('hsv')
    if not (type(hsv) is list and len(hsv) == 3 and
            all(type(x) is int and 0 <= x <= bound for x, bound in zip(hsv, (360, 100, 100)))):
        hsv = None
    effect = value('light_effect')
    effect_row = features.get('light_effect')
    choices = effect_row.get('choices', []) if type(effect_row) is dict else []
    if not (type(effect) is str and re.fullmatch(r"[A-Za-z][A-Za-z '\-]{0,63}", effect)
            and type(choices) is list and effect in choices[:64]):
        effect = None
    temperature = number('color_temperature', 2500, 6500)
    if value('color_temperature') == 0 and type(value('color_temperature')) is int:
        temperature = 0  # Colour mode, not an invalid Kelvin reading.
    return {'isOn': _feature(features, 'state', bool),
            'brightness': number('brightness', 0, 100), 'hsv': hsv,
            'colorTemperature': temperature, 'lightEffect': effect,
            'effectBrightness': number('effect_brightness', 1, 100),
            'smoothTransitionOn': number('smooth_transition_on', 0, 60),
            'smoothTransitionOff': number('smooth_transition_off', 0, 60),
            'rssi': _feature(features, 'rssi', int)}


def read_status(cli_path: str, alias: str, *, runner=run_cli) -> tuple[int, dict]:
    from .read_health import SECURITY_HEALTH
    code, body = METRICS.run('reads', _read_status, cli_path, alias, runner=runner)
    body['availability'] = 'available' if body.get('ok') is True else 'unavailable'
    # Contention means no new check occurred. Retain the previous observation
    # without refreshing its age; it expires normally if contention persists.
    if code != 400 and body.get('errorCode') != 'device_busy':
        SECURITY_HEALTH.record(alias, body.get('ok') is True)
    return code, body


def _read_status(cli_path: str, alias: str, *, runner=run_cli) -> tuple[int, dict]:
    """Called only after HTTP authorization. Blank config disables the route.

    The CLI validates the alias against its private registry and checks hardware
    identity. The request cannot select a command, host, env file or executable.
    """
    base = {"ok": False, "securityAssessment": "not_assessed", "observedAt": None}
    if not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", alias):
        return 400, {**base, "errorCode": "invalid_device"}
    if not cli_path:
        return 503, {**base, "errorCode": "disabled"}
    cli = Path(cli_path)
    if not cli.is_absolute():
        return 503, {**base, "errorCode": "invalid_configuration"}
    # Explicit deployment opt-in: both dashboard polling and HTTP reads use the
    # same fresh paired samples as departure detection. Never fall back on staleness.
    from . import security_snapshot
    snapshot = os.environ.get('JARVISD_SECURITY_SHARED_SNAPSHOT', '')
    if snapshot and alias in security_snapshot.ALIASES:
        return security_snapshot.read(snapshot, alias)
    if not _READ_LOCK.acquire(blocking=False):
        return 503, {**base, "errorCode": "device_busy"}
    try:
        started = datetime.now(timezone.utc).isoformat()
        result = runner(cli, alias)
        if type(result) is not dict:
            raise ReadError("invalid_output")
        if result.get("result") == "error":
            raise ReadError(result.get("reason"))
        model = result.get("model")
        features = result.get("features")
        if (result.get("result") != "read_succeeded" or result.get("device") != alias or
                model not in ("H200", "C230", "T100", "T110", "L930-5") or type(features) is not dict):
            raise ReadError("invalid_output")
        data = {}
        sensor = model in ("T100", "T110")
        if sensor:
            data = {
                "motionDetected" if model == "T100" else "isOpen":
                    _feature(features, "motion_detected" if model == "T100" else "is_open", bool),
                "batteryLow": _feature(features, "battery_low", bool),
                "rssi": _feature(features, "rssi", int),
                "radioFreshness": "unknown",
            }
        if model == 'L930-5':
            data = _lighting_data(features)
        required_available = (data.get('isOn') is not None if model == 'L930-5' else
            not sensor or data.get('motionDetected' if model == 'T100' else 'isOpen') is not None)
        attempts = result.get('read_attempts', 1)
        attempts = attempts if type(attempts) is int and 1 <= attempts <= 3 else 1
        return (200 if required_available else 503), {**base, "ok": required_available,
                     **({} if required_available else {'errorCode': 'required_state_unavailable'}),
                     'readAttempts': attempts, 'transientRecovered': attempts > 1,
                     "device": alias, "model": model,
                     "observedAt": started, "source": "hub_snapshot" if sensor else "device_read",
                     "data": data}
    except Exception as exc:
        return 503, {**base, "errorCode": exc.code if isinstance(exc, ReadError) else "operation_failed"}
    finally:
        _READ_LOCK.release()
