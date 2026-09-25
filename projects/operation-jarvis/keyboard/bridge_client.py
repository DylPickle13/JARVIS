"""One-shot client for the signed Karabiner CLI. Never opens HID or retries."""
import json
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parent
CLI = Path('/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli')


class BridgeError(RuntimeError):
    def __init__(self, uncertain):
        self.uncertain = uncertain
        super().__init__('Karabiner bridge outcome uncertain; acknowledgment required' if uncertain
                         else 'Karabiner bridge rejected before write')


def backend():
    try:
        value = json.loads((ROOT / 'transport.json').read_text())
    except FileNotFoundError:
        return 'direct'
    if value not in ({'backend': 'direct'}, {'backend': 'karabiner'}):
        raise ValueError('Invalid lighting transport configuration; no fallback')
    return value['backend']


def request(action, settings=None):
    if action not in ('apply', 'status', 'acknowledge'):
        raise ValueError('Invalid bridge action')
    body = dict(operation_type='jarvis_ak820_v1', action=action, id=uuid.uuid4().hex,
                sent_at=time.time(), settings=settings)
    try:
        result = subprocess.run([str(CLI), '--jarvis-ak820', json.dumps(body, allow_nan=False)],
                                capture_output=True, text=True, timeout=6)
    except OSError:
        raise BridgeError(False) from None
    except subprocess.TimeoutExpired:
        raise BridgeError(True) from None
    try:
        if len(result.stdout) > 2048:
            raise ValueError()
        response = json.loads(result.stdout)
        status = response['status']
        if status == 'rejected' and result.returncode == 2:
            raise BridgeError(False)
        expected = {'apply': 'success', 'status': 'ok', 'acknowledge': 'acknowledged'}[action]
        if result.returncode != 0 or status != expected:
            raise ValueError()
        return response
    except (ValueError, KeyError, TypeError):
        # A lost/malformed acknowledgment may follow a successful hardware write.
        raise BridgeError(True) from None


def send(report):
    if len(report) != 65 or report[:5] != bytes([4, 0x2a, 0x3d, 6, 0x1d]):
        raise ValueError('Invalid local report')
    # The wire protocol exposes settings, NEVER raw HID report bytes.
    settings = dict(effect=report[9], brightness=report[10], speed=report[11],
                    direction=report[12], rainbow=bool(report[13]), rgb=list(report[14:17]))
    request('apply', settings)
    return 65
