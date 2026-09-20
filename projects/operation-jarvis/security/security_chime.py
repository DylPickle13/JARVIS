"""Experimental D100C CLI: unique discovery, identity-first TPAP, bounded actions."""
import asyncio
from contextlib import ExitStack
import json
import os
import shutil
import subprocess

import security_cli as cli


def add_parser(sub):
    p = sub.add_parser('chime', help='Experimental local D100C status/preset controls')
    actions = p.add_subparsers(dest='chime_operation', required=True)
    for name in ('status', 'capabilities', 'ring', 'stop'):
        cmd = actions.add_parser(name)
        if name in ('ring', 'stop'):
            cmd.add_argument('--confirm', action='store_true')
        if name == 'ring':
            cmd.add_argument('--tone', choices=('1','2','3','4','5','6'), default='1')
            cmd.add_argument('--volume', type=int, choices=range(1,4), default=1,
                             help='Low test volume override; no persistent write')
            cmd.add_argument('--seconds', type=int, choices=range(1,6), default=1)


def validate(args):
    operation = args.chime_operation
    if operation not in ('status', 'capabilities', 'ring', 'stop'):
        raise cli.ControlError('unsupported_chime_command')
    if operation in ('ring', 'stop') and getattr(args, 'confirm', False) is not True:
        raise cli.ControlError('confirmation_required')
    if operation == 'ring' and (args.tone not in ('1','2','3','4','5','6') or
            type(args.volume) is not int or not 1 <= args.volume <= 3 or
            type(args.seconds) is not int or not 1 <= args.seconds <= 5):
        raise cli.ControlError('invalid_chime_ring')


def discovery_host(responses):
    matches = {}
    for data in responses:
        result = data.get('discovery_response', {}).get('result', {})
        scheme = result.get('mgt_encrypt_schm', {})
        tpap = result.get('tpap', {})
        if (str(result.get('device_model', '')).split('(')[0] == 'D100C' and
                result.get('device_type') == 'SMART.TAPOCHIME' and
                scheme.get('encrypt_type') == 'TPAP' and
                tpap.get('pake') == [2] and tpap.get('tls') == 0 and
                scheme.get('http_port') == 80):
            host = data.get('meta', {}).get('ip')
            cli.Settings(host=host)
            if host:
                matches[host] = True
    if len(matches) != 1:
        raise cli.ControlError('chime_missing_ambiguous_or_unsupported')
    return next(iter(matches))


async def discover():
    from kasa import Discover
    responses = []
    devices = await asyncio.wait_for(Discover.discover(
        discovery_timeout=3, on_discovered_raw=responses.append), 8)
    try:
        return discovery_host(responses)
    finally:
        for device in devices.values():
            await device.disconnect()


def invoke(args, host, settings):
    node = shutil.which('node')
    if not node or not (cli.ROOT/'private-notes/chime-tpap-v2/node_modules/@noble/curves/nist.js').is_file():
        raise cli.ControlError('chime_dependency_unavailable')
    request = {'operation':args.chime_operation, 'confirm':getattr(args,'confirm',False),
               'host':host,'username':settings.username,'password':settings.password}
    for field in ('tone','volume','seconds'):
        if hasattr(args,field):
            request[field] = getattr(args,field)
    writing = args.chime_operation in ('ring','stop')
    try:
        proc = subprocess.run([node,str(cli.ROOT/'security_chime_worker.mjs')],
            input=json.dumps(request), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=30,
            env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR') if k in os.environ})
        if len(proc.stdout)>65536:
            raise ValueError()
        result = json.loads(proc.stdout)
        if not isinstance(result,dict):
            raise ValueError()
        if proc.returncode or result.get('result')=='error':
            allowed={'confirmation_required','invalid_chime_ring','chime_transport_integrity_failed',
                     'chime_response_sequence_mismatch','chime_request_rejected','device_identity_mismatch',
                     'chime_tones_unavailable','chime_config_unavailable','chime_ring_preflight_failed',
                     'chime_action_outcome_unknown','chime_timeout','chime_read_failed'}
            reason=result.get('reason')
            raise cli.ControlError(reason if reason in allowed else 'chime_read_failed')
        expected = {'ring':'chime_ring_acknowledged','stop':'chime_stop_acknowledged'}.get(
            args.chime_operation, 'read_succeeded')
        if (result.get('result') != expected or result.get('model') != 'D100C' or
                result.get('authenticated') is not True):
            raise ValueError()
        return result
    except (subprocess.TimeoutExpired, ValueError, OSError):
        raise cli.ControlError('chime_action_outcome_unknown' if writing else 'chime_read_failed') from None


def execute_chime(args, adapter=None):
    adapter = adapter or cli
    try:
        validate(args)  # Gate audible/control actions before discovery or credentials.
        with ExitStack() as locks:
            locks.enter_context(adapter.device_lock('hub'))
            locks.enter_context(adapter.device_lock('front-doorbell'))
            locks.enter_context(adapter.device_lock('chime-tpap-probe'))
            host = asyncio.run(discover())
            settings = adapter.load_settings(args.env_file)
            if not settings.username or not settings.password:
                raise cli.ControlError('missing_credentials')
            return invoke(args,host,settings)
    except cli.ControlError as exc:
        raise adapter.ControlError(str(exc)) from None
    except (TimeoutError, OSError):
        raise adapter.ControlError('chime_read_failed') from None
