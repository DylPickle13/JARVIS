import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import uuid
from unittest import mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import ipaddress
from terminald.siri_new_session import SiriNewSessionRouter, NewSessionError
from terminald import jarvis_terminald as terminald


class SiriRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='siri-router-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.available = {3, 9}
        self.router = SiriNewSessionRouter(self.root/'ipc', self.root/'journal', lambda: {i: i+100 for i in range(1, 10)})
        self.router.descriptor = lambda slot, pid: {'sessionID': slot, 'pid': pid}
        self.router.exchange = self.exchange

    def exchange(self, d, operation, **fields):
        slot = d['sessionID']; self.calls.append((slot, operation))
        if operation == 'probe': return {'available': slot in self.available}
        self.available.discard(slot)
        return {'state': 'sent', 'requestID': fields['requestID']}

    def payload(self, **fields):
        return dict(requestID=str(uuid.uuid4()), prompt='literal prompt', **fields)

    def assertCode(self, code, payload):
        with self.assertRaises(NewSessionError) as caught: self.router.submit(payload)
        self.assertEqual(caught.exception.code, code)

    def test_first_unused_then_nine_and_refuse_without_fallback(self):
        self.assertEqual(self.router.submit(self.payload())['sessionID'], 3)
        self.assertEqual(self.router.submit(self.payload())['sessionID'], 9)
        self.assertCode('no_new_session', self.payload())
        self.assertEqual([s for s, op in self.calls if op == 'submit'], [3, 9])

    def test_no_verified_new_slot_never_submits(self):
        self.available.clear(); self.assertCode('no_new_session', self.payload())
        self.assertFalse(any(op == 'submit' for _, op in self.calls))

    def test_explicit_pre_dispatch_refusal_can_advance_but_timeout_cannot(self):
        original = self.exchange
        def refusing(d, op, **fields):
            if d['sessionID'] == 3 and op == 'submit': return {'state': 'unavailable', 'requestID': fields['requestID']}
            return original(d, op, **fields)
        self.router.exchange = refusing
        self.assertEqual(self.router.submit(self.payload())['sessionID'], 9)
        self.available = {3, 9}; self.calls.clear()
        def ambiguous(d, op, **fields):
            if op == 'submit': raise TimeoutError()
            return original(d, op, **fields)
        self.router.exchange = ambiguous
        self.assertCode('unconfirmed', self.payload())
        self.assertFalse(any(s == 9 for s, _ in self.calls))

    def test_duplicate_request_and_restart_do_not_allocate_twice(self):
        payload = self.payload(); first = self.router.submit(payload)
        self.calls.clear()
        self.assertEqual(self.router.submit(payload), first); self.assertEqual(self.calls, [])
        restarted = SiriNewSessionRouter(self.root/'ipc', self.root/'journal', lambda: self.fail('no reprobe'))
        self.assertEqual(restarted.submit(payload), first)
        self.assertCode('request_conflict', dict(payload, prompt='changed'))
        self.assertNotIn(payload['prompt'], (self.root/'journal'/f"{payload['requestID']}.json").read_text())

    def test_pending_crash_journal_blocks_replay_across_restart(self):
        payload = self.payload()
        self.router.exchange = mock.Mock(side_effect=TimeoutError())
        self.assertCode('no_new_session', payload)
        self.calls.clear(); self.router.exchange = self.exchange
        self.assertCode('unconfirmed', payload); self.assertEqual(self.calls, [])

    def test_busy_allocator_refuses_immediately(self):
        self.router.lock.acquire()
        try: self.assertCode('allocation_busy', self.payload())
        finally: self.router.lock.release()
        self.assertEqual(self.calls, [])

    def test_invalid_controls_bounds_identity_and_client_slot_rejected(self):
        for p in [None, [], self.payload(sessionID=9), {'requestID': True, 'prompt': 'x'},
                  *[dict(requestID=str(uuid.uuid4()), prompt=x) for x in ['', ' ', '\r', '\x85', 'é'*2049]]]:
            self.assertCode('invalid_request', p)
        self.assertEqual(self.calls, [])

    def test_unknown_acknowledgement_never_advances(self):
        original = self.exchange
        for state in ['unconfirmed', 'invalid', 'sent']:
            self.calls.clear()
            def bad(d, op, **fields):
                if op == 'submit': return {'state': state, 'requestID': 'wrong'}
                return original(d, op, **fields)
            self.router.exchange = bad
            self.assertCode('unconfirmed', self.payload())
            self.assertFalse(any(s == 9 for s, _ in self.calls))

    def test_private_descriptor_and_real_ipc_identity_checks(self):
        runtime = self.root/'ipc'; runtime.mkdir(mode=0o700)
        gen = 'a'*32; pid = os.getpid(); path = runtime/f'siri-{pid}-{gen[:8]}.sock'
        listener = socket.socket(socket.AF_UNIX); listener.bind(str(path)); listener.listen(); path.chmod(0o600)
        self.addCleanup(listener.close)
        descriptor = dict(version=1, pid=pid, sessionID=9, generation=gen, socketPath=str(path))
        file = runtime/'slot-9.json'; file.write_text(json.dumps(descriptor)); file.chmod(0o600)
        router = SiriNewSessionRouter(runtime, self.root/'other-journal', lambda: {9: pid})
        self.assertEqual(router.descriptor(9, pid), descriptor)
        self.assertIsNone(router.descriptor(9, pid+1)); self.assertIsNone(router.descriptor(8, pid))
        def reply():
            with listener.accept()[0] as conn:
                data = b''
                while b'\n' not in data: data += conn.recv(4096)
                conn.sendall(json.dumps(dict(version=1, sessionID=9, generation=gen, available=True)).encode()+b'\n')
        thread = threading.Thread(target=reply); thread.start()
        self.assertTrue(router.exchange(descriptor, 'probe')['available']); thread.join()
        file.chmod(0o644); self.assertIsNone(router.descriptor(9, pid)); file.chmod(0o600)
        file.unlink(); file.symlink_to(runtime/'missing.json'); self.assertIsNone(router.descriptor(9, pid))

    def test_http_auth_capacity_and_exact_slot_ack(self):
        service = mock.Mock(session_id=1)
        server = terminald.TerminalHTTPServer(('127.0.0.1', 0), service, 'private-test-token', [ipaddress.ip_network('127.0.0.0/8')])
        server.siri_router = self.router
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/v2/terminal/new-session-prompt'
        def send(token):
            return urlopen(Request(url, data=json.dumps(self.payload()).encode(), headers={'Authorization': 'Bearer '+token}), timeout=3)
        with self.assertRaises(HTTPError) as failure: send('wrong')
        self.assertEqual(failure.exception.code, 401); failure.exception.close(); self.assertEqual(self.calls, [])
        with send('private-test-token') as response: self.assertEqual(json.load(response)['sessionID'], 3)
        self.available.clear()
        with self.assertRaises(HTTPError) as failure: send('private-test-token')
        self.assertEqual(failure.exception.code, 409)
        self.assertEqual(json.loads(failure.exception.read())['code'], 'no_new_session'); failure.exception.close()
        self.available = {9}
        payload = dict(self.payload(), prompt='"' * 4096)
        data = json.dumps(payload).encode()
        self.assertGreater(len(data), 8192)
        with urlopen(Request(url, data=data, headers={'Authorization': 'Bearer private-test-token'}), timeout=3) as response:
            self.assertEqual(json.load(response)['sessionID'], 9)
        service.ensure_session.assert_not_called(); service.send_input.assert_not_called()
