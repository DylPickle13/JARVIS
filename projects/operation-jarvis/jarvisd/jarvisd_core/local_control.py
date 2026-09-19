"""Small, loopback-only CLI command transport; no retry or vendor fallback.

Deliberately process-local coordination, not durable exclusive ownership. The
existing dispatcher and vendor no-replay/identity guards remain authoritative.
"""
import hmac
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import stat

PATH = '/api/v1/local-control'
WRITES = frozenset({'plug-on', 'plug-off', 'plug-toggle', 'purifier-set'})
LIMIT = 1_048_576


def token_path():
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / 'Library/Application Support/JARVIS/local-control/token'


def read_token(path=None):
    path = token_path() if path is None else Path(path)
    directory = fd = None
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError()
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError()
        value = os.read(fd, 66).decode('ascii').strip()
        if info.st_size not in (64, 65) or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError):
        raise ValueError('Local backend credentials unavailable; no direct fallback.') from None
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)


def authorized(handler):
    expected = getattr(handler.server, 'local_control_token', None)
    values = handler.headers.get_all('Authorization', [])
    return (isinstance(expected, str) and handler.client_address[0] == '127.0.0.1'
        and not any(name in handler.headers for name in ('Origin', 'Cookie', 'Forwarded', 'X-Forwarded-For'))
        and len(values) == 1 and values[0].isascii()
        and hmac.compare_digest(values[0], 'Bearer ' + expected))


def validated(payload, snapshot):
    from .control_protocol import _command
    from .devices import _purifier_id
    if type(payload) is not dict or set(payload) != {'action', 'params'}:
        raise ValueError('Expected action and params only')
    action, params = payload['action'], payload['params']
    if type(action) is not str or action not in WRITES or type(params) is not dict:
        raise ValueError('Unsupported local device command')
    params = dict(params)
    if action == 'purifier-set':
        selector = params.pop('selector', None)
        if selector is not None:
            if type(selector) is not str or not selector.strip() or len(selector) > 256 or 'deviceID' in params:
                raise ValueError('Invalid purifier selector')
            selector = selector.strip()
            devices = snapshot()['subsystems'].get('purifier', {}).get('devices', {})
            matches = [key for key, item in devices.items() if key in (selector, _purifier_id(selector))
                or str(item.get('name') or '').casefold() == selector.casefold()]
            if len(matches) != 1:
                raise ValueError('Use the default, an opaque deviceID, exact CID or unique cached purifier name')
            params['deviceID'] = matches[0]
        has_id = 'deviceID' in params
        canonical = _command(action, {**params, 'deviceID': params.get('deviceID', '0' * 24)})
        params = dict(canonical.params)
        if not has_id: params.pop('deviceID')
    else:
        params = dict(_command(action, params).params)
    return action, params


def exchange(method, body=None, *, port=8790, token=None):
    """One HTTP request, numeric loopback, no proxies/pooling/redirect/retry."""
    token = read_token() if token is None else token
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=45)
    try:
        raw = None if body is None else json.dumps(body, separators=(',', ':'), allow_nan=False).encode()
        connection.request(method, PATH, raw, {'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json', 'Connection': 'close'})
        reply = connection.getresponse()
        data = reply.read(LIMIT + 1)
        if len(data) > LIMIT or reply.status not in (200, 400, 401, 403, 409, 503):
            raise ValueError()
        payload = json.loads(data)
        if type(payload) is not dict or type(payload.get('ok')) is not bool:
            raise ValueError()
        if reply.status != 200 and payload['ok']:
            raise ValueError()
        if method == 'POST' and payload['ok'] and payload.get('action') != body.get('action'):
            raise ValueError()
        return payload
    except (Exception, KeyboardInterrupt):
        # Even a timeout/lost reply can follow a completed device effect.
        raise ValueError('Backend command delivery may be unknown. Inspect state; do not retry automatically. No direct fallback.') from None
    finally:
        connection.close()


class Router:
    def __init__(self, legacy):
        self.legacy = legacy

    def __call__(self, args):
        if args.command not in WRITES:
            return None
        # Reuse the already tested pure argument translation, not its v2 client.
        from .control_cli import operation
        try:
            command = operation(self.legacy, args)
        except ValueError as exc:
            raise ValueError(str(exc).replace('v2', 'Backend')) from None
        params = dict(command.params)
        if args.command == 'purifier-set':
            params.pop('deviceID')
            if args.purifier is not None: params['selector'] = args.purifier
        result = exchange('POST', {'action': command.action, 'params': params})
        result['action'] = args.command
        if result.get('ok') is not True:
            message = str(result.get('error') or 'Backend did not confirm the command.')
            result['error'] = message + ' Inspect state; do not retry automatically. No direct fallback.'
        return result
