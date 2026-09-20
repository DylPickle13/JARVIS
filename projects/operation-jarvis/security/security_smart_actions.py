"""Experimental explicit Tapo CLOUD Smart Actions commands; no polling or retries.

Read/rename were commissioned. Other mutations are source-derived and must be
validated with an owner-approved disposable rule before routine use.
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import string
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid

import security_cli as cli

OPERATIONS = ('list', 'show', 'describe', 'create', 'update', 'rename', 'enable', 'disable', 'delete', 'execute')
WRITES = set(OPERATIONS) - {'list', 'show', 'describe'}
MAX_BYTES = 262144
PRIVATE = cli.ROOT / 'private-notes/smart-actions'
STORAGE = cli.ROOT / 'private-smart-actions'
SIGNING_HASH = 'ea75db01e999b4a85a1b2d54934249963de8724f976eb44b5982056d43a41b92'
CA_HASH = 'c7c1018adafb8da473ac847ab64ab84afd872733d9ad8b6f225e4d5f915810e3'
APP = 'TP-Link_Tapo_Android'


class SmartError(Exception):
    pass


def add_parser(sub):
    p = sub.add_parser('smart-actions', help='Explicit TP-Link CLOUD shortcuts/automations (experimental)')
    actions = p.add_subparsers(dest='smart_operation', required=True)
    for name in OPERATIONS:
        cmd = actions.add_parser(name)
        if name not in ('list', 'create'):
            cmd.add_argument('ref', help='Opaque reference from smart-actions list')
        if name in WRITES:
            cmd.add_argument('--confirm', action='store_true')
            if name != 'create':
                cmd.add_argument('--revision', required=True, help='Exact revision from the most recent list/show')
        if name in ('create', 'update'):
            cmd.add_argument('--file', required=True, help='Owner-only JSON rule file; show saves an editable private copy')
            cmd.add_argument('--allow-active', action='store_true', help='Approve writing an enabled rule; it may trigger actions')
        if name == 'rename':
            cmd.add_argument('--name', required=True)
            cmd.add_argument('--allow-active', action='store_true', help='Approve saving an enabled rule')
        if name == 'execute':
            cmd.add_argument('--allow-actions', action='store_true', help='Approve real device actions; shortcuts only')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def revision(rule):
    return hashlib.sha256(canonical(rule)).hexdigest()


def reference(rule):
    return hashlib.sha256(rule['id'].encode()).hexdigest()[:16]


def valid_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value.encode()) > 64 or
            any(unicodedata.category(c).startswith('C') for c in value)):
        raise SmartError('invalid_smart_name')


def validate_rule(rule, creating=False):
    if not isinstance(rule, dict):
        raise SmartError('invalid_smart_rule')
    valid_name(rule.get('name'))
    if creating:
        if 'id' in rule:
            raise SmartError('create_rule_must_omit_id')
    elif not isinstance(rule.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', rule['id']):
        raise SmartError('invalid_smart_id')
    if (type(rule.get('enabled')) is not bool or not isinstance(rule.get('triggerSetting'), dict) or
            type(rule['triggerSetting'].get('isManual')) is not bool or
            not isinstance(rule.get('actionSetting'), dict)):
        raise SmartError('invalid_smart_rule')
    if len(canonical(rule)) > MAX_BYTES:
        raise SmartError('smart_rule_too_large')


def summary(rule):
    return {'ref': reference(rule), 'revision': revision(rule), 'name': rule['name'],
            'kind': 'shortcut' if rule['triggerSetting']['isManual'] else 'automation',
            'enabled': rule['enabled']}


def describe_rule(rule):
    """Bounded configuration projection, never raw IDs, names, locations or RPCs.

    Trigger combination codes and firmware service semantics are intentionally not
    interpreted. This describes fields, not verified real-world behaviour.
    """
    triggers = rule['triggerSetting'].get('things', [])
    actions = rule['actionSetting'].get('things', [])
    if not isinstance(triggers, list) or not isinstance(actions, list):
        raise SmartError('unsupported_smart_description')
    if len(triggers) > 32 or len(actions) > 32:
        raise SmartError('unsupported_smart_description')
    def model(item):
        return item.get('model') if item.get('model') in ('H200', 'C230', 'D235', 'T100', 'T110') else 'unknown'
    trigger_rows = []
    for item in triggers:
        if not isinstance(item, dict):
            raise SmartError('unsupported_smart_description')
        event = item.get('event', {})
        event = event.get('name') if isinstance(event, dict) else None
        trigger_rows.append({'model': model(item), 'event': event if event in ('open', 'close', 'motion') else 'unknown'})
    action_rows = []
    for item in actions:
        if not isinstance(item, dict):
            raise SmartError('unsupported_smart_description')
        row = {'model': model(item), 'effect': 'unverified_device_action'}
        service = item.get('service', {})
        params = service.get('inputParams', {}) if isinstance(service, dict) else {}
        if row['model'] == 'H200' and isinstance(params, dict):
            duration, tone, volume = params.get('duration'), params.get('type'), params.get('volume')
            if type(duration) is int and 0 <= duration <= 3600:
                row['configured_duration_seconds'] = duration
            if isinstance(tone, str) and re.fullmatch(r'Alarm [0-9]{1,2}', tone):
                row['configured_alarm_tone'] = tone
            if isinstance(volume, str) and re.fullmatch(r'[0-9]{1,3}', volume):
                row['configured_volume_raw'] = volume
        action_rows.append(row)
    period = rule.get('effectivePeriod', {})
    all_day = True if isinstance(period, dict) and period.get('periodType') == 'ALL_DAY' else None
    return {'rule': summary(rule), 'configuration': {
        'triggers': trigger_rows, 'actions': action_rows,
        'all_day': all_day, 'trigger_combination': 'not_interpreted',
        'description_scope': 'partial_allowlisted_fields',
        'physical_behavior': 'not_verified',
        'warning': 'Enabling may cause physical actions immediately or on later triggers. Disabling does not stop an already sounding alarm.'}}


def private_read(path, limit=MAX_BYTES):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077 or info.st_size > limit):
            raise SmartError('private_file_permissions_or_size')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise SmartError('private_file_too_large')
        return data
    finally:
        os.close(fd)


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SmartError('duplicate_json_key')
            result[key] = value
        return result
    def invalid(_):
        raise SmartError('nonfinite_json_value')
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def snapshot(value, category):
    STORAGE.mkdir(mode=0o700, exist_ok=True)
    info = STORAGE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SmartError('private_storage_permissions')
    path = STORAGE / (category + '-' + uuid.uuid4().hex + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(canonical(value))
        f.flush()
        os.fsync(f.fileno())
    return str(path.relative_to(cli.ROOT))


def validate_request(req):
    op = req.get('operation')
    if op not in OPERATIONS:
        raise SmartError('unsupported_smart_operation')
    if op in WRITES and req.get('confirm') is not True:
        raise SmartError('confirmation_required')
    if op not in ('list', 'create') and not re.fullmatch('[0-9a-f]{16}', req.get('ref', '')):
        raise SmartError('invalid_smart_reference')
    if op in WRITES - {'create'} and not re.fullmatch('[0-9a-f]{64}', req.get('revision', '')):
        raise SmartError('smart_revision_required')
    if op == 'execute' and req.get('allow_actions') is not True:
        raise SmartError('physical_actions_confirmation_required')
    if op == 'rename':
        valid_name(req.get('name'))
    if op in ('create', 'update'):
        validate_rule(req.get('rule'), creating=op == 'create')
        if req['rule']['enabled'] and req.get('allow_active') is not True:
            raise SmartError('active_rule_confirmation_required')


def target(rules, ref):
    matches = [r for r in rules if reference(r) == ref]
    if len(matches) != 1:
        raise SmartError('smart_missing_or_ambiguous')
    return matches[0]


def plan(req, rules):
    op = req['operation']
    before = None
    if op == 'create':
        after = copy.deepcopy(req['rule'])
        # App source generates eight base62 characters from UUID chunks.
        after['id'] = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        if any(r['id'] == after['id'] for r in rules):
            raise SmartError('smart_id_collision')
    else:
        before = target(rules, req['ref'])
        if revision(before) != req['revision']:
            raise SmartError('smart_revision_conflict')
        after = copy.deepcopy(before)
        if op == 'update':
            after = copy.deepcopy(req['rule'])
            if after['id'] != before['id']:
                raise SmartError('smart_id_change_refused')
            if before['enabled'] and req.get('allow_active') is not True:
                raise SmartError('active_rule_confirmation_required')
        elif op == 'rename':
            if before['enabled'] and req.get('allow_active') is not True:
                raise SmartError('active_rule_confirmation_required')
            after['name'] = req['name']
        elif op in ('enable', 'disable'):
            after['enabled'] = op == 'enable'
        elif op == 'delete':
            after = None
        elif op == 'execute':
            if before['triggerSetting']['isManual'] is not True:
                raise SmartError('execute_requires_shortcut')
    return before, after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SmartError('cloud_redirect_refused')


def cloud_code(value):
    if not isinstance(value, dict):
        raise SmartError('invalid_cloud_response')
    code = value.get('error_code', value.get('errorCode', 0))
    nested = value.get('result')
    if isinstance(nested, dict) and str(nested.get('errorCode', 0)) != '0':
        code = nested['errorCode']
    try:
        return int(code)
    except (ValueError, TypeError):
        raise SmartError('invalid_cloud_response') from None


class Cloud:
    """Single account session. TLS verified, redirects/proxies/retries disabled."""
    def __init__(self):
        signing = private_read(PRIVATE / 'reference-signing.py')
        ca = private_read(PRIVATE / 'tplink-ca-chain.pem')
        if hashlib.sha256(signing).hexdigest() != SIGNING_HASH or hashlib.sha256(ca).hexdigest() != CA_HASH:
            raise SmartError('smart_cloud_dependency_integrity_failed')
        keys = {}
        for node in ast.parse(signing).body:
            if isinstance(node, ast.Assign):
                for name in node.targets:
                    if isinstance(name, ast.Name) and name.id in ('TAPO_ACCESS_KEY', 'TAPO_SECRET_KEY'):
                        keys[name.id] = ast.literal_eval(node.value)
        if len(keys) != 2 or any(not isinstance(v, str) for v in keys.values()):
            raise SmartError('smart_cloud_dependency_invalid')
        self.keys = keys
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=ca.decode('ascii'))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                  urllib.request.HTTPSHandler(context=context))
        self.term = str(uuid.uuid4())
        self.token = None
        self.endpoint = None
        self.requests = 0
        self.write_started = False

    def close(self):
        self.token = None
        self.keys.clear()

    @staticmethod
    def base(url, domain):
        p = urllib.parse.urlsplit(url)
        if (p.scheme != 'https' or not p.hostname or not p.hostname.endswith('.' + domain) or
                p.username or p.password or p.port not in (None, 443) or p.path not in ('', '/') or p.query or p.fragment):
            raise SmartError('unexpected_cloud_endpoint')
        return url.rstrip('/')

    def send(self, method, url, headers, body=None):
        self.requests += 1
        if self.requests > 14:
            raise SmartError('cloud_request_limit')
        data = json.dumps(body, allow_nan=False).encode() if body is not None else None
        if data is not None and len(data) > MAX_BYTES:
            raise SmartError('cloud_request_too_large')
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with self.opener.open(req, timeout=8) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise SmartError('cloud_response_too_large')
        result = parse_json(payload) if payload else {}
        if cloud_code(result) != 0:
            code = cloud_code(result)
            reason = {-20601: 'cloud_authentication_failed', -20675: 'cloud_account_locked',
                      -20677: 'cloud_mfa_required'}.get(code, 'cloud_request_rejected')
            raise SmartError(reason)
        return result

    def rpc(self, path, body, token=None):
        if path not in ('/api/v2/account/login', '/') or (path == '/' and body.get('method') != 'getAppServiceUrl'):
            raise SmartError('unsupported_cloud_rpc')
        data = json.dumps(body, allow_nan=False).encode()
        md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4())
        signature = hmac.new(self.keys['TAPO_SECRET_KEY'].encode(),
                            f'{md5}\n{timestamp}\n{nonce}\n{path}'.encode(), hashlib.sha1).hexdigest()
        headers = {'Content-Type': 'application/json', 'Content-MD5': md5,
                   'X-Authorization': f'Timestamp={timestamp}, Nonce={nonce}, AccessKey={self.keys["TAPO_ACCESS_KEY"]}, Signature={signature}'}
        query = {'appName': APP, 'appVer': '3.4.451', 'netType': 'wifi', 'termID': self.term,
                 'ospf': 'Android 14', 'brand': 'TPLINK', 'locale': 'en_US',
                 'model': 'Pixel', 'termName': 'Pixel', 'termMeta': 'Pixel'}
        if token:
            query['token'] = token
        return self.send('POST', 'https://n-wap-gw.tplinkcloud.com' + path + '?' + urllib.parse.urlencode(query), headers, body)

    def login(self, username, password):
        r = self.rpc('/api/v2/account/login', {'appType': APP, 'appVersion': '3.4.451',
            'cloudPassword': password, 'cloudUserName': username, 'platform': 'Android',
            'refreshTokenNeeded': False, 'supportBindAccount': False, 'terminalUUID': self.term,
            'terminalName': 'JARVIS Smart Actions', 'terminalMeta': 'JARVIS'})
        result = r.get('result', {})
        if result.get('MFAProcessId'):
            raise SmartError('cloud_mfa_required')
        self.token = result.get('token')
        if not isinstance(self.token, str) or not self.token:
            raise SmartError('cloud_token_unavailable')
        r = self.rpc('/', {'method': 'getAppServiceUrl', 'params': {'serviceIds': ['nbu.iot-app-server.app']}}, self.token)
        self.endpoint = self.base(r['result']['serviceUrls']['nbu.iot-app-server.app'], 'tplinknbu.com')

    def api(self, method, path, body=None):
        read = method == 'GET' and body is None and re.fullmatch(r'/v1/smarts\?page=[0-4]&pageSize=20', path)
        write = ((method == 'PUT' and path == '/v1/smarts' and isinstance(body, dict)) or
                 (method == 'DELETE' and re.fullmatch(r'/v1/smarts/[A-Za-z0-9_-]{1,128}', path) and body is None) or
                 (method == 'POST' and re.fullmatch(r'/v1/smarts/[A-Za-z0-9_-]{1,128}/exec', path) and body is None))
        if not self.token or not self.endpoint or not (read or write):
            raise SmartError('unsupported_smart_endpoint')
        if write:
            if self.write_started:
                raise SmartError('second_write_refused')
            self.write_started = True  # Set before sending; any subsequent failure is ambiguous.
        headers = {'Authorization': 'ut|' + self.token, 'Content-Type': 'application/json',
            'x-app-name': APP, 'x-app-version': '3.4.451', 'x-term-id': self.term,
            'x-ospf': 'Android 14', 'x-locale': 'en_US', 'x-net-type': 'wifi',
            'app-cid': f'app:{APP}:{self.term}'}
        return self.send(method, self.endpoint + path, headers, body)

    def listing(self):
        rows = []
        total = None
        for page in range(5):
            r = self.api('GET', f'/v1/smarts?page={page}&pageSize=20')
            count = r.get('total')
            data = r.get('data')
            if (type(count) is not int or not 0 <= count <= 100 or
                    not isinstance(data, list) or len(data) > 20 or r.get('page') != page or
                    (total is not None and count != total)):
                raise SmartError('smart_listing_incomplete_or_changed')
            total = count
            for rule in data:
                validate_rule(rule)
            rows.extend(data)
            if len({r['id'] for r in rows}) != len(rows):
                raise SmartError('smart_listing_duplicate')
            if len(rows) == total:
                return rows
            if not data or len(rows) > total:
                break
        raise SmartError('smart_listing_incomplete_or_changed')


def run(req, cloud):
    validate_request(req)
    op = req['operation']
    rules = cloud.listing()
    if op == 'list':
        return {'result': 'read_succeeded', 'source': 'tapo_cloud', 'rules': [summary(r) for r in rules]}
    if op == 'describe':
        return {'result': 'read_succeeded', 'source': 'tapo_cloud', **describe_rule(target(rules, req['ref']))}
    if op == 'show':
        rule = target(rules, req['ref'])
        path = snapshot(rule, 'rule')
        return {'result': 'read_succeeded', 'rule': summary(rule), 'private_file': path}
    before, after = plan(req, rules)
    if before == after and op != 'execute':
        return {'result': 'unchanged', 'rule': summary(before), 'writes_attempted': 0}
    backup = snapshot({'operation': op, 'before': before, 'requested': after}, 'before-write')
    try:
        if op == 'delete':
            cloud.api('DELETE', '/v1/smarts/' + urllib.parse.quote(before['id'], safe=''))
        elif op == 'execute':
            cloud.api('POST', '/v1/smarts/' + urllib.parse.quote(before['id'], safe='') + '/exec')
            return {'result': 'execution_acknowledged', 'physical_outcome': 'not_verified',
                    'private_backup': backup, 'writes_attempted': 1}
        else:
            cloud.api('PUT', '/v1/smarts', after)
        actual = cloud.listing()
        wanted = after['id'] if after else before['id']
        matches = [r for r in actual if r['id'] == wanted]
        matched = not matches if op == 'delete' else matches == [after]
        # Exact full-rule verification; other rules must also be unchanged.
        others_before = {r['id']: r for r in rules if r['id'] != wanted}
        others_after = {r['id']: r for r in actual if r['id'] != wanted}
        if not matched or others_before != others_after:
            raise SmartError('smart_write_readback_mismatch')
        return {'result': 'write_verified', 'operation': op, 'rule': summary(after) if after else None,
                'private_backup': backup, 'writes_attempted': 1}
    except BaseException:
        # Do not replay, blindly restore, or leak URLs/tokens from exception text.
        return {'result': 'write_outcome_unknown', 'outcome': 'unknown',
                'private_backup': backup, 'writes_attempted': 1, 'automatic_retry': False}


def execute_smart_actions(args, adapter=None):
    adapter = adapter or cli
    req = {'operation': args.smart_operation}
    for name in ('confirm', 'ref', 'revision', 'name', 'allow_active', 'allow_actions'):
        if hasattr(args, name):
            req[name] = getattr(args, name)
    try:
        # Confirmation before private file access, credentials, subprocess, or network.
        if req['operation'] in WRITES and req.get('confirm') is not True:
            raise SmartError('confirmation_required')
        if hasattr(args, 'file'):
            req['rule'] = parse_json(private_read(args.file))
        validate_request(req)
        with adapter.device_lock('tapo-smart-actions'):
            account = parse_json(private_read(PRIVATE / 'account.json', 4096))
            username = account.get('username')
            if not isinstance(username, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', username):
                raise SmartError('cloud_account_configuration_invalid')
            settings = adapter.load_settings(Path(args.env_file))
            if not settings.password:
                raise SmartError('cloud_password_unavailable')
            req.update(username=username, password=settings.password)
            try:
                proc = subprocess.run([sys.executable, str(cli.ROOT / 'security_smart_actions.py'), '--worker'],
                    input=json.dumps(req), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=110, env={k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ})
                if len(proc.stdout) > MAX_BYTES or proc.returncode:
                    raise ValueError()
                result = parse_json(proc.stdout)
                if not isinstance(result, dict) or result.get('result') not in (
                        'read_succeeded', 'unchanged', 'write_verified', 'execution_acknowledged', 'write_outcome_unknown', 'error'):
                    raise ValueError()
                return result
            except (subprocess.TimeoutExpired, ValueError, KeyboardInterrupt):
                if req['operation'] in WRITES:
                    return {'result': 'write_outcome_unknown', 'outcome': 'unknown', 'automatic_retry': False,
                            'recovery_directory': str(STORAGE.relative_to(cli.ROOT))}
                raise SmartError('smart_cloud_read_failed') from None
    except SmartError as exc:
        raise adapter.ControlError(str(exc)) from None


def worker():
    import logging
    logging.disable(logging.CRITICAL)
    cloud = None
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 16385)
        if len(data) > MAX_BYTES + 16384:
            raise SmartError('smart_request_too_large')
        req = parse_json(data)
        validate_request(req)
        cloud = Cloud()
        cloud.login(req.pop('username'), req.pop('password'))
        result = run(req, cloud)
    except SmartError as exc:
        result = {'result': 'error', 'reason': str(exc)}
    except BaseException:
        result = {'result': 'error', 'reason': 'smart_cloud_request_failed'}
    finally:
        if cloud:
            cloud.close()
    print(json.dumps(result))


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        worker()
    else:
        raise SystemExit('Use ./security smart-actions --help')
