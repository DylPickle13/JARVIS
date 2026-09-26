"""One-shot signed Karabiner Razer bridge client; never opens HID or retries."""
import json
import subprocess
import time
import uuid
from bridge_client import CLI


class RazerBridgeError(RuntimeError):
    def __init__(self, message, *, uncertain):
        super().__init__(message)
        self.uncertain = uncertain


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != {'operation', 'value', 'y'}:
        raise ValueError('Invalid Razer settings shape')
    op, value, y = (settings[k] for k in ('operation', 'value', 'y'))
    if type(value) is not int or type(y) is not int:
        raise ValueError('Integer settings required')
    valid = ((op == 'effect' and value in (0, 1, 2) and y == 0)
             or (op == 'brightness' and 0 <= value <= 100 and y == 0)
             or (op == 'dpi' and 100 <= value <= 6400 and 100 <= y <= 6400)
             or (op == 'poll' and value in (125, 500, 1000) and y == 0)
             or (op in ('get-brightness', 'get-dpi', 'get-poll') and value == y == 0))
    if not valid:
        raise ValueError('Unsupported Razer settings')
    return settings


def request(action, settings=None):
    if action not in ('apply', 'status', 'acknowledge'):
        raise ValueError('Invalid bridge action')
    if action == 'apply':
        validate_settings(settings)
    elif settings is not None:
        raise ValueError('Unexpected settings')
    body = dict(operation_type='jarvis_razer_v1', action=action, settings=settings,
                id=uuid.uuid4().hex, sent_at=time.time())
    try:
        result = subprocess.run([str(CLI), '--jarvis-razer', json.dumps(body, allow_nan=False)],
                                capture_output=True, text=True, timeout=6)
    except subprocess.TimeoutExpired:
        raise RazerBridgeError('Razer bridge timeout; outcome uncertain. Do not retry', uncertain=True) from None
    except OSError:
        raise RazerBridgeError('Signed Razer CLI unavailable; no direct-HID fallback', uncertain=False) from None
    try:
        if len(result.stdout) > 2048:
            raise ValueError()
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or not isinstance(response.get('status'), str):
            raise ValueError()
    except (ValueError, TypeError):
        raise RazerBridgeError('Missing/invalid bridge reply; outcome uncertain. Check installed bridge version; no retry', uncertain=True) from None
    expected = {'status': 'ok', 'apply': 'success', 'acknowledge': 'acknowledged'}[action]
    if result.returncode != 0 or response['status'] != expected:
        raise RazerBridgeError('Razer bridge: ' + json.dumps(response) + '; no retry',
                              uncertain=not (result.returncode == 2 and response['status'] == 'rejected'))
    return response
