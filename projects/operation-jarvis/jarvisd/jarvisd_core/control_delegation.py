"""Explicit ledger-to-worker delegation. No default activation or provisioning.

Only a currently executing, admitted callback may issue once. Never derive that
permission from record.json, a boolean, HTTP metadata, or a restored snapshot.
SDK hooks/worker deployment and real cohort transition evidence remain separate.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import threading

from . import client_policy as policy, control_protocol as protocol
from . import vendor_fence as fence
from .device_host import CatalogueEntry
from .commands import PURIFIER_MODES, PURIFIER_AUTO_PREFERENCES
from .device_translation import _purifier_set_cli_args

WRITES = frozenset(('plug-on', 'plug-off', 'plug-toggle', 'purifier-set'))


class DelegationError(RuntimeError):
    def __init__(self):
        super().__init__('Backend delegation unavailable; no fallback or automatic retry.')


def purifier_call(cid, words):
    """Translate reviewed vendor CLI words into the exact existing SDK call."""
    if type(cid) is not str or not cid or type(words) is not list or not words:
        raise DelegationError()
    name, rest = words[0], words[1:]
    kwargs, args = {}, []
    switches = {'on': 'turn_on', 'off': 'turn_off', 'toggle': 'toggle_switch', 'clear-timer': 'clear_timer'}
    if name in switches and not rest:
        method = switches[name]
        if name == 'toggle':
            args = [None]
    elif name in ('display', 'child-lock', 'light-detection') and len(rest) == 1 and rest[0] in ('on', 'off'):
        method = 'turn_' + rest[0] + '_' + name.replace('-', '_')
    elif name == 'mode' and len(rest) == 1 and rest[0] in PURIFIER_MODES:
        method, args = 'set_mode', rest
    elif name in ('speed', 'timer') and len(rest) == 1:
        number = int(rest[0])
        if not 1 <= number <= (4 if name == 'speed' else 1440):
            raise DelegationError()
        method, args = ('set_fan_speed', [number]) if name == 'speed' else ('set_timer', [number * 60])
    elif name == 'auto-preference' and (len(rest) == 1 or len(rest) == 3 and rest[1] == '--room-size'):
        if rest[0] not in PURIFIER_AUTO_PREFERENCES:
            raise DelegationError()
        room = 600 if len(rest) == 1 else int(rest[2])  # Reviewed existing vendor CLI default.
        if not 1 <= room <= 10000:
            raise DelegationError()
        method, args, kwargs = 'set_auto_preference', [rest[0]], {'room_size': room}
    else:
        raise DelegationError()
    return {'cohort': 'purifier', 'target': cid, 'method': method, 'args': args, 'kwargs': kwargs}


def worker_call(args):
    """Bind actual private-worker arguments, never trust a grant's self-description."""
    if args.command in ('plug-on', 'plug-off', 'plug-toggle'):
        host = args.expected_host
        if type(host) is not str or not host.strip():
            raise DelegationError()
        return {'cohort': 'plugs', 'target': host.strip().lower(), 'method': args.command, 'args': [], 'kwargs': {}}
    if args.command != 'purifier-set' or not args.expected_cid or args.purifier != args.expected_cid:
        raise DelegationError()
    # Remove the already-bound selector before translating settings, without
    # mutating the parsed namespace or asking a config/default resolver anything.
    import copy
    plain = copy.copy(args)
    plain.purifier = None
    return purifier_call(args.expected_cid, _purifier_set_cli_args(plain))


def call_for(bound, entry):
    if type(bound) is not protocol.BoundWrite or type(entry) is not CatalogueEntry:
        raise DelegationError()
    command = protocol._command(bound.command.action, dict(bound.command.params))
    params = dict(command.params)
    if (command != bound.command or command.cohort is not entry.cohort
            or bound.target != (entry.cohort.value, entry.identity)
            or params.get('plug', params.get('deviceID')) != entry.name):
        raise DelegationError()
    if entry.cohort is policy.Cohort.PLUGS:
        return {'cohort': 'plugs', 'target': entry.identity, 'method': command.action, 'args': [], 'kwargs': {}}
    setting, value = params['setting'], params.get('value')
    if setting == 'power':
        words = [value]
    elif setting == 'timer':
        words = ['clear-timer'] if value == 'clear' else ['timer', str(params['minutes'])]
    elif setting == 'speed':
        words = ['speed', str(params['level'])]
    else:
        words = [setting, value]
        if setting == 'auto-preference' and 'roomSize' in params:
            words += ['--room-size', str(params['roomSize'])]
    return purifier_call(entry.selector, words)


class DelegatingRunner:
    """Compose as BOTH host scope and dispatcher runner. Defaults never select it.

    root must already contain the exact ledger and a private grants directory.
    No creation, reset, rotation, configuration writes or activation occurs here.
    Scope state is thread-local; a read never inherits a mutation token, including
    from daemon environment or caller env. The worker remains independently fenced.
    """
    def __init__(self, *, store, runner, root=None):
        self._store, self._runner = store, runner
        self._root = fence.root_directory() if root is None else Path(root)
        self._local = threading.local()

    @contextmanager
    def scope(self, bound, entry):
        if getattr(self._local, 'frame', None) is not None:
            raise DelegationError()
        call = call_for(bound, entry)
        with fence.directory(self._root) as root, fence.directory('ledger', parent=root) as ledger, fence.directory('grants', parent=root) as grants:
            claim = self._store.claim_delegation(cohort=bound.command.cohort, resource=bound.resource,
                command=bound.fingerprint, action=bound.command.action, directory=self._root / 'ledger')
            token = secrets.token_hex(32)
            grant = fence.validate_grant({**claim, 'schema': 1, 'token': token, 'call': call})
            fence._current(ledger, grant)
            fd = fence.write_new(grants, token + '.json', grant)
            os.close(fd)
            # A slow sync cannot renew the window or silently outlive closure.
            fence._current(ledger, grant)
        self._local.frame = {'token': token, 'used': False}
        try:
            yield
        finally:
            self._local.frame = None

    def __call__(self, argv, timeout=20.0, env=None):
        child_env = dict(env or {})
        child_env[fence.TOKEN_ENV] = ''  # Also overrides inherited process/.env tokens.
        if len(argv) >= 3 and argv[2] in WRITES:
            frame = getattr(self._local, 'frame', None)
            if frame is None or frame['used']:
                raise DelegationError()
            frame['used'] = True  # Before any transport/worker error, never refunded.
            child_env[fence.TOKEN_ENV] = frame['token']
        return self._runner(argv, timeout=timeout, env=child_env)
