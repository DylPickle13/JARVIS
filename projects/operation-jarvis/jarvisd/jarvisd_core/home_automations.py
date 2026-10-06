"""Closed Home controls, durable no-replay receipts and bounded cloud reads.

No cloud I/O on import or in snapshot reads. Only list/enable/disable of the
privately pinned Barn door automation are permitted. Never login or execute.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time

from . import automatic_voice as policy

CONTROLS = frozenset({'automatic-voice', 'barn-door'})
MAX_REQUESTS = 512


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def validated(value, request_id):
    if (type(value) is not dict or set(value) != {'control', 'enabled', 'revision', 'confirmed', 'requestID'}
            or type(value['control']) is not str or value['control'] not in CONTROLS or type(value['enabled']) is not bool
            or type(value['confirmed']) is not bool or type(value['revision']) is not str
            or not re.fullmatch(r'[0-9a-f]{32}' if value['control'] == 'automatic-voice' else r'[0-9a-f]{64}', value['revision'])
            or type(value['requestID']) is not str or not policy.HEX.fullmatch(value['requestID'])
            or value['requestID'] != request_id):
        raise policy.PolicyError('Invalid Home automation command.')
    if value['control'] == 'barn-door' and value['enabled'] and not value['confirmed']:
        raise policy.PolicyError('Confirm enabling Barn Door Protocol first.')
    return value


class HomeAutomations:
    def __init__(self, root, security_cli, *, runner=None, now=time.time):
        self.root = Path(root)
        self.security_cli = Path(security_cli) if security_cli else None
        if self.security_cli is not None and not self.security_cli.is_absolute():
            raise policy.PolicyError('Smart Actions launcher must be an absolute trusted path.')
        self.runner = runner or self._run
        self.now = now
        self.boot = secrets.token_hex(16)
        self.lock = threading.RLock()
        self.cloud = None
        self.cloud_at = None
        self.cloud_error = None
        self.reading = False
        self.next_read = 0
        self.workers = {}
        self.closed = False

    def _run(self, args):
        if self.security_cli is None:
            raise policy.PolicyError('Smart Actions capability not configured.')
        result = subprocess.run([str(self.security_cli), '--json', 'smart-actions', *args],
                                capture_output=True, timeout=115, check=False)
        if len(result.stdout) > 262144:
            raise ValueError('Oversized cloud response')
        value = json.loads(result.stdout)
        if type(value) is not dict:
            raise ValueError('Invalid cloud response')
        return value

    def _binding(self):
        value = policy.read_json(self.root, 'binding.json')
        if (set(value) != {'version', 'barnDoorRef'} or type(value['version']) is not int
                or value['version'] != 1 or type(value['barnDoorRef']) is not str
                or not re.fullmatch(r'[0-9a-f]{16}', value['barnDoorRef'])):
            raise policy.PolicyError('Barn Door binding unavailable.')
        return value['barnDoorRef']

    def _ledger(self):
        value = policy.read_json(self.root, 'requests.json')
        if (set(value) != {'version', 'requests'} or type(value['version']) is not int or value['version'] != 1
                or type(value['requests']) is not dict or len(value['requests']) > MAX_REQUESTS):
            raise policy.PolicyError('Automation receipts unavailable.')
        for key, row in value['requests'].items():
            if (not policy.HEX.fullmatch(key) or type(row) is not dict
                    or set(row) != {'control', 'enabled', 'revision', 'confirmed', 'requestID', 'owner', 'at', 'status'}
                    or row.get('requestID') != key or type(row.get('control')) is not str
                    or row.get('control') not in CONTROLS or type(row.get('enabled')) is not bool
                    or type(row.get('confirmed')) is not bool or type(row.get('revision')) is not str
                    or not re.fullmatch(r'[0-9a-f]{32}' if row['control'] == 'automatic-voice' else r'[0-9a-f]{64}', row['revision'])
                    or type(row.get('status')) is not str
                    or row.get('status') not in {'pending', 'verified', 'unknown', 'rejected'}
                    or not isinstance(row.get('owner'), str) or type(row.get('at')) not in (int, float)
                    or not math.isfinite(row['at'])):
                raise policy.PolicyError('Automation receipts unavailable.')
        return value

    def _receipt(self, row):
        status = row['status']
        if status == 'pending' and (row['owner'] != self.boot or row['control'] not in self.workers
                or not self.workers[row['control']].is_alive()):
            status = 'unknown'  # Interrupted execution is consumed, never restarted.
        return {'requestID': row['requestID'], 'control': row['control'], 'enabled': row['enabled'],
                'status': status}

    def _last_operation(self, ledger, control):
        rows = [row for row in ledger['requests'].values() if row['control'] == control]
        return self._receipt(max(rows, key=lambda row: row['at'])) if rows else None

    def refresh(self):
        with self.lock:
            if (self.closed or self.security_cli is None or self.reading
                    or self.now() < self.next_read or 'barn-door' in self.workers):
                return
            try:
                ref = self._binding()
            except (OSError, ValueError, TypeError):
                return
            self.reading = True
            self.next_read = self.now() + 60  # Shared budget; no cloud call per UI poll.
            thread = threading.Thread(target=self._read, args=(ref,), name='jarvis-home-read', daemon=True)
            try:
                thread.start()
            except Exception:
                self.reading = False
                self.cloud_error = 'Cloud read unavailable.'

    def _read(self, ref):
        try:
            value = self.runner(['list'])
            rows = value.get('rules')
            if value.get('result') != 'read_succeeded' or type(rows) is not list or len(rows) > 100:
                raise ValueError('Cloud session or read unavailable')
            matches = [row for row in rows if type(row) is dict and row.get('ref') == ref]
            if (len(matches) != 1 or matches[0].get('kind') != 'automation'
                    or matches[0].get('name', '').casefold() != 'barn door protocol'
                    or type(matches[0].get('enabled')) is not bool
                    or not isinstance(matches[0].get('revision'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', matches[0]['revision'])):
                raise ValueError('Pinned rule missing or changed')
            with self.lock:
                self.cloud = {'enabled': matches[0]['enabled'], 'revision': matches[0]['revision']}
                self.cloud_at = self.now()
                self.cloud_error = None
        except Exception:
            with self.lock:
                self.cloud_error = 'Cloud rule unavailable; refresh or explicitly renew the cloud session.'
        finally:
            with self.lock:
                self.reading = False

    def snapshot(self, *, active=False):
        if active:
            self.refresh()
        with self.lock:
            at = self.now()
            voice = policy.current(self.root, legacy=False)
            try:
                ledger = self._ledger()
                voice_op = self._last_operation(ledger, 'automatic-voice')
                barn_op = self._last_operation(ledger, 'barn-door')
                binding = self._binding()
            except (OSError, ValueError, TypeError):
                return {'automaticVoice': {'available': False}, 'barnDoor': {'available': False}}
            fresh = (self.cloud is not None and self.cloud_at is not None
                     and 0 <= at - self.cloud_at <= 90 and self.cloud_error is None)
            return {'automaticVoice': {
                'available': voice is not None, 'enabled': voice.enabled if voice else None,
                'revision': voice.revision if voice else None, 'observedAt': stamp(at),
                'validUntil': stamp(at + 30), 'operation': voice_op,
                'blocked': any(row['control'] == 'automatic-voice' and row['status'] == 'pending'
                    for row in ledger['requests'].values())},
                'barnDoor': {'available': bool(binding) and self.security_cli is not None, 'enabled': self.cloud['enabled'] if fresh else None,
                'revision': self.cloud['revision'] if fresh else None,
                'observedAt': stamp(self.cloud_at) if self.cloud_at is not None else None,
                'validUntil': stamp(self.cloud_at + 90) if fresh else None,
                'refreshing': self.reading, 'error': self.cloud_error, 'operation': barn_op,
                'blocked': any(row['control'] == 'barn-door' and row['status'] == 'pending'
                    for row in ledger['requests'].values())}}

    def submit(self, command, request_id):
        command = validated(command, request_id)
        with self.lock, policy.locked(self.root):
            if self.closed:
                raise policy.PolicyError('Home controls are shutting down; no change sent.')
            ledger = self._ledger()
            existing = ledger['requests'].get(request_id)
            if existing is not None:
                if any(existing.get(key) != command[key] for key in command):
                    raise policy.PolicyError('Request identity already used for a different command.')
                return self._result(existing)
            control = command['control']
            if control in self.workers or any(row['control'] == control and row['status'] == 'pending'
                    for row in ledger['requests'].values()):
                raise policy.PolicyError('This control is changing or interrupted; inspect before another change.')
            if len(ledger['requests']) >= MAX_REQUESTS:
                raise policy.PolicyError('Automation receipt capacity reached; no change sent.')
            if control == 'automatic-voice':
                value = policy.current(self.root, legacy=False)
                if value is None or value.revision != command['revision']:
                    raise policy.PolicyError('Automatic Voice changed or is unavailable; refresh first.')
            else:
                self._binding()
                if self.security_cli is None:
                    raise policy.PolicyError('Smart Actions capability unavailable; no change sent.')
                if (self.reading or self.cloud is None or self.cloud_at is None or self.cloud_error
                        or not 0 <= self.now() - self.cloud_at <= 90
                        or self.cloud['revision'] != command['revision']):
                    raise policy.PolicyError('Fresh Barn Door configuration required; refresh first.')
            row = {**command, 'owner': self.boot, 'at': self.now(), 'status': 'pending'}
            ledger['requests'][request_id] = row
            policy.save_json(self.root, 'requests.json', ledger)  # Consume before every possible change.
            if control == 'automatic-voice':
                try:
                    policy.set_enabled(self.root, command['enabled'], command['revision'])
                    row['status'] = 'verified'
                except Exception:
                    row['status'] = 'unknown'
                policy.save_json(self.root, 'requests.json', ledger)
            elif self.cloud['enabled'] == command['enabled']:
                row['status'] = 'verified'
                policy.save_json(self.root, 'requests.json', ledger)
            else:
                self.cloud_at = None  # No stale enabled-state authorizes another change.
                thread = threading.Thread(target=self._write, args=(copy.deepcopy(row),),
                                          name='jarvis-home-write', daemon=True)
                self.workers[control] = thread
                try:
                    thread.start()
                except Exception:
                    self.workers.pop(control, None)
                    row['status'] = 'unknown'
                    policy.save_json(self.root, 'requests.json', ledger)
            return self._result(row)

    def _result(self, row):
        receipt = self._receipt(row)
        return {'ok': receipt['status'] in {'pending', 'verified'}, 'action': 'home-automation-set',
                'homeAutomation': receipt,
                'error': None if receipt['status'] in {'pending', 'verified'} else
                'Outcome unconfirmed. Inspect current configuration; never resend automatically.'}

    def _write(self, row):
        status = 'unknown'
        rule = None
        try:
            ref = self._binding()
            value = self.runner(['enable' if row['enabled'] else 'disable', ref,
                                 '--revision', row['revision'], '--confirm'])
            candidate = value.get('rule')
            if (value.get('result') in {'write_verified', 'unchanged'} and type(candidate) is dict
                    and candidate.get('ref') == ref and candidate.get('kind') == 'automation'
                    and candidate.get('enabled') is row['enabled']
                    and isinstance(candidate.get('revision'), str)
                    and re.fullmatch(r'[0-9a-f]{64}', candidate['revision'])):
                status, rule = 'verified', candidate
            elif value.get('result') == 'error' and value.get('writes_attempted') == 0:
                status = 'rejected'
        except Exception:
            pass  # A timeout/interruption can follow a delivered mutation. Never replay.
        with self.lock:
            try:
                with policy.locked(self.root):
                    ledger = self._ledger()
                    ledger['requests'][row['requestID']]['status'] = status
                    policy.save_json(self.root, 'requests.json', ledger)
            except Exception:
                status = 'unknown'
            if status == 'verified' and rule is not None:
                self.cloud = {'enabled': rule['enabled'], 'revision': rule['revision']}
                self.cloud_at, self.cloud_error = self.now(), None
            else:
                self.cloud_at = None
                self.cloud_error = 'Change unconfirmed. Inspect configuration; do not retry automatically.'
            self.next_read = 0
            self.workers.pop('barn-door', None)

    def close(self):
        with self.lock:
            self.closed = True
        # Never terminate/replay an in-flight cloud mutation at shutdown.
