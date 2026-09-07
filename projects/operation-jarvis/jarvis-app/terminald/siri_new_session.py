"""Siri's fail-closed, first-unused-slot allocator. No PTY paste or session creation.

Read-only probes may skip unavailable slots. After any submission starts, no
other slot is tried unless that exact ingress explicitly proves no dispatch.
A private durable request journal prevents replay after terminald restarts.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time

REQUEST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
GENERATION = re.compile(r"^[0-9a-f]{32}$")


class NewSessionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class SiriNewSessionRouter:
    def __init__(self, runtime, journal, identities):
        self.runtime = Path(runtime)
        self.journal = Path(journal)
        self.identities = identities
        self.lock = threading.Lock()

    @staticmethod
    def private_path(path, kind):
        st = path.lstat()
        return kind(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077

    @classmethod
    def read_record(cls, path):
        if not cls.private_path(path, stat.S_ISREG): raise ValueError('unsafe record')
        with path.open('rb') as source: data = source.read(4097)
        if len(data) > 4096: raise ValueError('oversized record')
        record = json.loads(data)
        if not isinstance(record, dict): raise ValueError('invalid record')
        return record

    def descriptor(self, slot, pid):
        try:
            if not self.private_path(self.runtime, stat.S_ISDIR): return None
            path = self.runtime / f"slot-{slot}.json"
            if not self.private_path(path, stat.S_ISREG) or path.stat().st_size > 4096: return None
            d = self.read_record(path)
            if type(d.get('version')) is not int or d['version'] != 1: return None
            if type(d.get('pid')) is not int or d['pid'] != pid: return None
            if type(d.get('sessionID')) is not int or d['sessionID'] != slot: return None
            gen = d.get('generation')
            if not isinstance(gen, str) or not GENERATION.fullmatch(gen): return None
            expected = self.runtime / f"siri-{pid}-{gen[:8]}.sock"
            if d.get('socketPath') != str(expected) or not self.private_path(expected, stat.S_ISSOCK): return None
            return d
        except (OSError, ValueError, TypeError): return None

    @staticmethod
    def exchange(d, operation, **fields):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2.2 if operation == 'submit' else 0.2)
            connection.connect(d['socketPath'])
            connection.sendall((json.dumps(dict(version=1, generation=d['generation'], operation=operation, **fields)) + '\n').encode())
            response = b''
            while b'\n' not in response:
                chunk = connection.recv(4097 - len(response))
                if not chunk: raise ValueError('incomplete response')
                response += chunk
                if len(response) > 4096: raise ValueError('oversized response')
            value = json.loads(response)
            if not isinstance(value, dict): raise ValueError('invalid response')
            if (type(value.get('version')) is not int or value['version'] != 1 or
                type(value.get('sessionID')) is not int or value['sessionID'] != d['sessionID'] or
                value.get('generation') != d['generation']): raise ValueError('identity mismatch')
            return value

    def store(self, path, record, *, create=False):
        data = json.dumps(record, sort_keys=True).encode()
        target = path if create else path.with_suffix('.tmp')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data); output.flush(); os.fsync(output.fileno())
            if not create: os.replace(target, path)
            directory = os.open(self.journal, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        except Exception:
            # A partial claim must remain fail-closed, never be removed for retry.
            raise

    def submit(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'requestID', 'prompt'}:
            raise NewSessionError('invalid_request')
        request_id, prompt = payload['requestID'], payload['prompt']
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id): raise NewSessionError('invalid_request')
        request_id = request_id.lower()
        if (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 4096 or
            any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in prompt)):
            raise NewSessionError('invalid_request')
        if not self.lock.acquire(blocking=False): raise NewSessionError('allocation_busy')
        try:
            self.journal.mkdir(parents=True, mode=0o700, exist_ok=True)
            if not self.private_path(self.journal, stat.S_ISDIR): raise NewSessionError('unconfirmed')
            path = self.journal / (request_id + '.json')
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            if path.exists():
                try:
                    if not self.private_path(path, stat.S_ISREG) or path.stat().st_size > 4096: raise ValueError()
                    old = self.read_record(path)
                    if old.get('digest') != digest: raise NewSessionError('request_conflict')
                    if old.get('state') == 'sent' and type(old.get('sessionID')) is int and 1 <= old['sessionID'] <= 9:
                        return {'ok': True, 'requestID': payload['requestID'], 'sessionID': old['sessionID']}
                except (OSError, ValueError): pass
                raise NewSessionError('unconfirmed')
            # Never evict dedupe evidence and thereby make an old request replayable.
            if sum(1 for _ in self.journal.iterdir()) >= 10000: raise NewSessionError('unconfirmed')
            record = {'digest': digest, 'state': 'pending'}
            self.store(path, record, create=True)
            deadline = time.monotonic() + 2
            identities = self.identities() # read-only exact pane/PID allowlist, never provisions panes
            for slot in range(1, 10):
                if time.monotonic() >= deadline: break
                pid = identities.get(slot)
                if type(pid) is not int or pid <= 1: continue
                d = self.descriptor(slot, pid)
                if not d: continue
                try:
                    probe = self.exchange(d, 'probe')
                    if probe.get('available') is not True: continue
                except (OSError, ValueError, TypeError): continue
                try:
                    result = self.exchange(d, 'submit', requestID=request_id, prompt=prompt)
                    if result.get('requestID') != request_id: raise ValueError('request mismatch')
                    if result.get('state') == 'unavailable': continue # positively no dispatch
                    if result.get('state') != 'sent': raise ValueError('unconfirmed')
                    record.update(state='sent', sessionID=slot)
                    self.store(path, record)
                    return {'ok': True, 'requestID': payload['requestID'], 'sessionID': slot}
                except (OSError, ValueError, TypeError): raise NewSessionError('unconfirmed')
            raise NewSessionError('no_new_session')
        except (OSError, ValueError, TypeError):
            raise NewSessionError('unconfirmed') from None
        finally: self.lock.release()
