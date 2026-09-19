"""Candidate CLI routing through the authenticated v2 client, never vendor fallback.

Used by explicit control-cli.py, not the unchanged default jarvis-cli/Pi launcher.
Reuses the existing argument validator, but does not call a vendor write handler.
"""
import argparse
import copy
import re
import time

from . import client_policy as policy, control_protocol as protocol
from . import control_credentials as credentials
from .control_transport import ControlClient, TransportError

WRITES = frozenset({'plug-on', 'plug-off', 'plug-toggle', 'purifier-set'})


class CLIError(ValueError):
    pass


def operation(legacy, args):
    """Return a canonical operation, or None for unchanged non-device-write paths."""
    action = args.command
    if action not in WRITES:
        return None
    if action.startswith('plug-'):
        if (args.plug_config is not None or args.discovery_target is not None
                or args.plug_timeout != legacy.DEFAULT_SMART_PLUG_TIMEOUT):
            raise CLIError('v2 writes do not accept vendor configuration, discovery or timeout overrides')
        name = args.plug.strip().lower()
        if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', name):
            raise CLIError('v2 plug writes require a configured alias, not a direct address')
        return protocol._command(action, {'plug': name})
    if args.purifier_timeout != legacy.DEFAULT_AIR_PURIFIER_TIMEOUT:
        raise CLIError('v2 writes do not accept vendor timeout overrides')
    # Existing pure helper validates aliases, speed/timer bounds and convenience
    # fields. Its returned argv is NEVER executed and contains no private selector.
    setting = legacy._canon_purifier_setting(args.setting)
    allowed = {'power': {'state'}, 'display': {'state'}, 'child-lock': {'state'},
        'light-detection': {'state'}, 'speed': {'level'}, 'timer': {'minutes'},
        'auto-preference': {'room_size'}, 'mode': set()}.get(setting, set())
    provided = {key for key in ('state', 'level', 'minutes', 'room_size') if getattr(args, key, None) is not None}
    if provided - allowed or (args.value and provided & {'state', 'level', 'minutes'}):
        raise CLIError('Conflicting or irrelevant setting arguments')
    sanitized = copy.copy(args)
    sanitized.purifier = None
    words = legacy._purifier_set_cli_args(sanitized)
    params = {'deviceID': '0' * 24, 'setting': setting}
    if setting == 'power':
        params['value'] = words[0]
    elif setting == 'speed':
        params['level'] = int(words[1])
    elif setting == 'timer':
        params.update({'value': 'clear'} if words[0] == 'clear-timer' else {'minutes': int(words[1])})
    else:
        params['value'] = words[1]
        if setting == 'auto-preference' and len(words) > 2:
            params['roomSize'] = int(words[3])
    return protocol._command(action, params)


class Router:
    def __init__(self, legacy, *, directory=None, port=8790):
        self._legacy = legacy
        self._directory = credentials.default_directory() if directory is None else directory
        self._port = port  # Trusted constructor seam for loopback tests, not a CLI/env option.

    @staticmethod
    def configure_parser(parser):
        parser.epilog = ('Candidate v2 entry: device writes require private credentials and the authenticated backend. '
                         'No direct fallback. Default jarvis-cli/Pi routing has not switched yet.')
        choices = next(action.choices for action in parser._actions if isinstance(action, argparse._SubParsersAction))
        for name in WRITES:
            choices[name].epilog = parser.epilog
            for action in choices[name]._actions:
                if action.dest == 'plug':
                    action.help = 'Configured plug alias only; direct IP writes are disabled'
                elif action.dest == 'purifier':
                    action.help = 'Opaque 24-hex deviceID; omitted uses only an explicitly epoch-bound provisioned default'
                elif action.dest in ('plug_config', 'discovery_target', 'plug_timeout', 'purifier_timeout'):
                    action.help = 'Legacy option; non-default overrides are rejected for v2 writes'

    def __call__(self, args):
        if args.command == 'plug-save-discovery':
            raise CLIError('Catalogue changes require owner maintenance; this v2 entry does not save discovery.')
        if args.command not in WRITES:
            return None
        deadline = time.monotonic() + 60.0
        try:
            command = operation(self._legacy, args)
        except Exception:
            raise CLIError('Invalid v2 device arguments; use configured plug aliases and canonical settings. No direct fallback.') from None
        try:
            bundle = credentials.load(self._directory)
            # Pin the client as well as the server; a changed/missing reviewed
            # stack cannot quietly gain authority using retained credentials.
            if not bundle.certificate.valid() or command.cohort not in bundle.enrollment.cohorts:
                raise credentials.CredentialError('not-approved')
        except Exception:
            raise CLIError('Private v2 client credentials or reviewed sources unavailable. No direct fallback.') from None
        params = dict(command.params)
        if command.cohort is policy.Cohort.PURIFIER:
            selector = args.purifier
            if selector is not None:
                if not protocol._hex(selector, protocol._DEVICE_ID):
                    raise CLIError('v2 purifier selection requires an explicit opaque deviceID; name/model/CID fallback is disabled.')
                params['deviceID'] = selector
            elif bundle.default is None:
                raise CLIError('No epoch-bound default purifier is provisioned; specify an opaque deviceID.')
            else:
                params['deviceID'] = bundle.default.device_id
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CLIError('Control invocation expired before submission. No automatic retry or direct fallback.')
        client = ControlClient(bundle.enrollment.credential, port=self._port, timeout=60.0, deadline=deadline)
        try:
            window = client.window(command.cohort)
            if (command.cohort is policy.Cohort.PURIFIER and args.purifier is None
                    and (window.incarnation, window.epoch) != (bundle.default.incarnation, bundle.default.epoch)):
                raise CLIError('Default purifier binding belongs to another ownership epoch; owner revalidation required.')
            intent = client.intent(window, command.action, params)
        except TransportError:
            raise CLIError('Authenticated v2 control window unavailable. No command retry or direct fallback.') from None
        outcome = client.submit(intent)
        acknowledged = outcome in (policy.Outcome.ACKNOWLEDGED, policy.Outcome.PENDING)
        summary = ('Backend acknowledged the command; this receipt is not a fresh device reading.'
            if outcome is policy.Outcome.ACKNOWLEDGED else
            'Backend accepted the command; verification is pending.' if outcome is policy.Outcome.PENDING else
            'Command delivery is unknown. Inspect device state; do not retry automatically.')
        result = {'ok': acknowledged, 'action': args.command, 'summary': summary,
            'verificationPending': outcome is policy.Outcome.PENDING,
            'control': {'protocol': protocol.PROTOCOL, 'disposition': outcome.value,
                        'requestID': intent.request.request_id, 'requestDigest': intent.request.fingerprint}}
        if not acknowledged:
            result['error'] = summary
        return result
