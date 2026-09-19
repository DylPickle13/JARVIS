"""Local synthetic peers only: real sockets/MACs/ledger; never physical devices."""
import concurrent.futures
from dataclasses import replace
import gc
from http.server import BaseHTTPRequestHandler
import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from test_control_protocol import Host
from test_control_ledger import handoff
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core import control_identity as a, control_transport as t

CREDENTIAL = a.Credential('1' * 32, '2' * 64)  # Synthetic, never installed.
ENROLLMENT = a.Enrollment(CREDENTIAL, 'a' * 64, frozenset(p.Cohort))


def certificate():
    # TEST-ONLY enrollment after reading the current fixture/runtime. Production
    # must load an independently retained reviewed artifact, not self-certify.
    return a.TransportCertificate(a.PROFILE, tuple(sys.version_info[:3]),
        tuple((str(path), a.digest(path.read_bytes())) for path in a.certificate_sources()))


def request_headers(body, *, path=v.WINDOW_PATH, port=8790, credential=CREDENTIAL, nonce='3' * 64):
    return [('Host', f'127.0.0.1:{port}'), ('Content-Type', v.CONTENT_TYPE),
        ('Content-Length', str(len(body))), ('Connection', 'close'),
        ('X-Jarvis-Control-Client', credential.client_id), ('X-Jarvis-Control-Nonce', nonce),
        ('X-Jarvis-Control-Proof', a.request_proof(credential.key, port=port,
            client=credential.client_id, nonce=nonce, path=path, body=body))]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        server = self.server
        body = self.rfile.read(int(self.headers['Content-Length']))
        server.requests.append((self.path, list(self.headers.raw_items()), body))
        try:
            context = server.registry.authenticate(peer=self.client_address[0], method='POST',
                path=self.path, headers=list(self.headers.raw_items()), body=body)
        except a.IdentityError:
            self.send_response(401)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        reply = server.api.handle(method='POST', path=self.path, content_type=v.CONTENT_TYPE,
                                  body=body, access=context.access)
        reply = server.change_reply(self.path, reply)
        wire = (f'HTTP/1.1 {reply.status} Test\r\n'.encode() +
                b''.join(f'{key}: {value}\r\n'.encode() for key, value in
                         server.registry.response_headers(context, reply)) + b'\r\n' + reply.body)
        wire = server.change_wire(self.path, wire)
        server.replies.append(wire)
        if wire:
            if server.trickle and self.path == v.COMMAND_PATH:
                for byte in wire:
                    try:
                        self.connection.sendall(bytes([byte]))
                    except OSError:
                        break
                    time.sleep(.01)
            else:
                self.connection.sendall(wire)
        self.close_connection = True


class Peer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, api):
        super().__init__(('127.0.0.1', 0), Handler)
        self.registry = a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=certificate(),
                                           port=self.server_address[1])
        self.api, self.requests, self.replies = api, [], []
        self.trickle = False
        self.change_reply = lambda path, reply: reply
        self.change_wire = lambda path, wire: wire
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown(); self.server_close(); self.thread.join(2)

    def client(self, **kwargs):
        return t.ControlClient(CREDENTIAL, port=self.server_address[1], timeout=kwargs.get('timeout', 2))


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.cert = certificate()
        self.registry = a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=self.cert)
        self.body = v._encode({'protocol': v.PROTOCOL, 'cohort': 'plugs'})
        self.headers = request_headers(self.body)

    def authenticate(self, **changes):
        args = dict(peer='127.0.0.1', method='POST', path=v.WINDOW_PATH,
                    headers=self.headers, body=self.body)
        args.update(changes)
        return self.registry.authenticate(**args)

    def test_scoped_authenticated_identity_not_a_caller_flag(self):
        context = self.authenticate()
        self.assertEqual(context.access.principal, ENROLLMENT.principal)
        command = v._command('plug-on', {'plug': 'lamp'})
        with mock.patch.object(a, 'source_digest', side_effect=AssertionError('IO in fast authorization')):
            self.assertTrue(self.registry.authorize(context.access, command))
            self.assertFalse(self.registry.authorize(replace(context.access), command))
        self.assertNotIn(CREDENTIAL.key, repr(CREDENTIAL))
        self.assertNotIn(CREDENTIAL.key, repr(ENROLLMENT))
        self.assertNotIn(CREDENTIAL.key, repr(context))

    def test_request_mac_binds_client_nonce_path_port_and_exact_body(self):
        for changes in ({'body': self.body + b' '}, {'path': v.COMMAND_PATH}, {'method': 'GET'},
                        {'path': v.WINDOW_PATH + '/'}, {'path': v.WINDOW_PATH + '?x=1'}):
            with self.subTest(changes=changes), self.assertRaises(a.IdentityError):
                self.authenticate(**changes)
        for key, value in (('Host', '127.0.0.1:8791'), ('X-Jarvis-Control-Nonce', '4' * 64),
                           ('X-Jarvis-Control-Client', '5' * 32), ('X-Jarvis-Control-Proof', '0' * 64),
                           ('Content-Length', '0' + str(len(self.body))), ('Connection', 'keep-alive')):
            changed = [(k, value if k == key else val) for k, val in self.headers]
            with self.subTest(key=key), self.assertRaises(a.IdentityError):
                self.authenticate(headers=changed)

    def test_no_lan_mapped_loopback_proxy_origin_or_legacy_auth(self):
        for peer in ('192.0.2.1', '::1', '::ffff:127.0.0.1', '127.0.0.2', 'localhost', None):
            with self.subTest(peer=peer), self.assertRaises(a.IdentityError):
                self.authenticate(peer=peer)
        for name in ('Authorization', 'X-Jarvis-Token', 'Origin', 'Cookie', 'Forwarded',
                     'X-Forwarded-For', 'Transfer-Encoding', 'Expect', 'Host'):
            with self.subTest(name=name), self.assertRaises(a.IdentityError):
                self.authenticate(headers=[*self.headers, (name, 'injected')])

    def test_duplicate_bad_and_oversized_headers(self):
        for headers in ([*self.headers[:-1], ('host', '127.0.0.1:8790')],
                        [*self.headers[:-1], ('X-Jarvis-Control-Proof', 'a\r\nb')],
                        [*self.headers[:-1], ('X-Jarvis-Control-Proof', 'a' * 257)],
                        [*self.headers[:-1], ('X-Jarvis-Control-Proof', 3)],
                        [*self.headers[:-1], None]):
            with self.subTest(headers=headers), self.assertRaises(a.IdentityError):
                self.authenticate(headers=headers)
        with self.assertRaises(a.IdentityError):
            self.authenticate(body=b'x' * (v.MAX_BODY + 1))

    def test_revocation_invalidates_already_prepared_access(self):
        context = self.authenticate()
        command = v._command('plug-on', {'plug': 'lamp'})
        self.assertTrue(self.registry.authorize(context.access, command))
        self.registry.revoke(CREDENTIAL.client_id)
        self.assertFalse(self.registry.authorize(context.access, command))
        with self.assertRaises(a.IdentityError):
            self.authenticate()

    def test_scope_and_key_rotation_keep_principal_separate_from_key(self):
        enrollment = replace(ENROLLMENT, cohorts=frozenset({p.Cohort.PLUGS}),
                             credential=a.Credential(CREDENTIAL.client_id, '9' * 64))
        self.registry = a.IdentityRegistry(enrollments=(enrollment,), certificate=self.cert)
        with self.assertRaises(a.IdentityError):
            self.authenticate()
        context = self.authenticate(headers=request_headers(self.body, credential=enrollment.credential))
        self.assertEqual(context.access.principal, ENROLLMENT.principal)
        self.assertTrue(self.registry.authorize(context.access, v._command('plug-on', {'plug': 'lamp'})))
        self.assertFalse(self.registry.authorize(context.access,
            v._command('purifier-set', {'deviceID': 'd' * 24, 'setting': 'power', 'value': 'on'})))

    def test_source_version_profile_and_missing_certificate_fail_closed(self):
        for cert in (replace(self.cert, sources=()), replace(self.cert, python_version=(0, 0, 0)),
                     replace(self.cert, profile='other'),
                     replace(self.cert, sources=tuple((name, '0' * 64) for name, _ in self.cert.sources))):
            with self.subTest(cert=cert):
                self.registry = a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=cert)
                with self.assertRaises(a.IdentityError):
                    self.authenticate()
        with self.assertRaises(a.IdentityError):
            a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=None)
        self.registry = a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=self.cert)
        with mock.patch.object(a, 'source_digest', side_effect=OSError('unavailable')):
            with self.assertRaises(a.IdentityError):
                self.authenticate()

    def test_source_checks_refuse_links_nonregular_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            regular = root / 'source'
            regular.write_bytes(b'reviewed bytes')
            self.assertEqual(a.source_digest(regular), a.digest(regular.read_bytes()))
            link = root / 'link'; link.symlink_to(regular)
            fifo = root / 'fifo'; os.mkfifo(fifo)
            for path in (link, fifo, root):
                with self.subTest(path=path), self.assertRaises((a.IdentityError, OSError)):
                    a.source_digest(path)
            with regular.open('wb') as file:
                file.truncate(128 * 1024 * 1024 + 1)
            with self.assertRaises(a.IdentityError):
                a.source_digest(regular)

    def test_identity_bookkeeping_does_not_retain_discarded_requests(self):
        context = self.authenticate()
        self.assertEqual(len(self.registry._issued), 1)
        del context
        gc.collect()
        self.assertEqual(len(self.registry._issued), 0)

    def test_reply_seal_must_belong_to_registry(self):
        other = a.IdentityRegistry(enrollments=(ENROLLMENT,), certificate=self.cert)
        with self.assertRaises(a.IdentityError):
            other.response_headers(self.authenticate(), v._error(409, 'duplicate-intent'))

    def test_enrollment_and_transport_configuration_are_closed(self):
        for bad in (True, 0, 65536, '8790'):
            with self.subTest(port=bad), self.assertRaises(t.TransportError):
                t.ControlClient(CREDENTIAL, port=bad)
        for bad in (True, 0, -1, 121, float('nan'), float('inf'), '1'):
            with self.subTest(timeout=bad), self.assertRaises(t.TransportError):
                t.ControlClient(CREDENTIAL, timeout=bad)
        for cid, key in (('x', CREDENTIAL.key), (CREDENTIAL.client_id, 'secret\r\nheader'),
                         (CREDENTIAL.client_id, 'A' * 64)):
            with self.assertRaises(a.IdentityError):
                a.Credential(cid, key)
        with self.assertRaises(a.IdentityError):
            a.IdentityRegistry(enrollments=(ENROLLMENT, ENROLLMENT), certificate=self.cert)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'ledger'
        g.ControlLedger.initialize(path)
        self.store = g.ControlLedger.open(path)
        self.addCleanup(self.store.close)
        handoff(self.store)
        self.host = Host()
        self.peer = Peer(v.ControlProtocol(self.store, self.host))
        self.addCleanup(self.peer.close)
        self.client = self.peer.client()

    def intent(self):
        return self.client.intent(self.client.window(p.Cohort.PLUGS), 'plug-on', {'plug': 'lamp'})

    def test_authenticated_window_and_single_receipt(self):
        intent = self.intent()
        self.assertEqual(self.client.submit(intent), p.Outcome.ACKNOWLEDGED)
        self.assertEqual(len(self.host.effects), 1)
        self.assertEqual([r[0] for r in self.peer.requests], [v.WINDOW_PATH, v.COMMAND_PATH])
        transmitted = repr(self.peer.requests) + repr(self.peer.replies)
        self.assertNotIn(CREDENTIAL.key, transmitted)
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)
        self.assertEqual(len(self.peer.requests), 2)

    def test_real_dispatcher_coordinator_and_final_authorization(self):
        from test_device_host import HostTests, C
        fixture = HostTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.host = fixture.make_host(authorize=self.peer.registry.authorize)
        fixture.complete(C)
        self.peer.api = v.ControlProtocol(fixture.store, fixture.host)
        self.assertEqual(self.client.submit(self.intent()), p.Outcome.ACKNOWLEDGED)
        fixture.runner.assert_called_once()
        self.assertEqual(fixture.runner.call_args.args[0][-2:], ['--expected-host', '192.0.2.1'])
        self.assertTrue(fixture.rows()[0]['unresolved'])

    def test_lost_reply_after_effect_never_replays_and_ledger_rejects_deliberate_duplicate(self):
        intent = self.intent()
        self.peer.change_wire = lambda path, wire: b''
        self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        self.assertEqual(len(self.host.effects), 1)
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)
        self.peer.change_wire = lambda path, wire: wire
        # Adversarial duplicate, NOT client recovery. No second device effect.
        reply = self.client._transport.exchange(v.COMMAND_PATH, intent._body)
        self.assertEqual(reply.status, 409)
        self.assertEqual(json.loads(reply.body)['code'], 'duplicate-intent')
        self.assertEqual(len(self.host.effects), 1)

    def test_duplicate_rejection_preserves_original_unknown_outcome(self):
        intent = self.intent()
        self.host.outcome = p.Outcome.UNKNOWN
        self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        reply = self.client._transport.exchange(v.COMMAND_PATH, intent._body)
        self.assertEqual(json.loads(reply.body)['priorDisposition'], p.Outcome.UNKNOWN.value)
        self.assertEqual(v.classify_receipt(intent.request, status=reply.status,
            content_type=v.CONTENT_TYPE, body=reply.body, intended_peer=True,
            single_submission=True), p.Outcome.UNKNOWN)

    def test_concurrent_claims_have_one_submission(self):
        intent = self.intent()
        def submit(_):
            try:
                return self.client.submit(intent)
            except t.TransportError:
                return 'consumed'
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(8)))
        self.assertEqual(results.count(p.Outcome.ACKNOWLEDGED), 1)
        self.assertEqual(results.count('consumed'), 7)
        self.assertEqual(len(self.host.effects), 1)

    def test_wrong_client_consumes_budget_before_transport(self):
        intent = self.intent()
        with self.assertRaises(t.TransportError):
            self.peer.client().submit(intent)
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)
        self.assertEqual(len(self.peer.requests), 1)

    def test_cancellation_closes_socket_and_keeps_intent_consumed(self):
        intent = self.intent()
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.sendall.side_effect = KeyboardInterrupt()
        with mock.patch.object(socket, 'socket', return_value=sock):
            with self.assertRaises(KeyboardInterrupt):
                self.client.submit(intent)
        sock.connect.assert_called_once(); sock.sendall.assert_called_once()
        sock.__exit__.assert_called_once()
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)
        self.assertEqual(len(self.peer.requests), 1)

    def test_partial_send_failure_never_reconnects(self):
        intent = self.intent()
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.sendall.side_effect = OSError('synthetic partial send')
        with mock.patch.object(socket, 'socket', return_value=sock) as create:
            self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        create.assert_called_once(); sock.connect.assert_called_once(); sock.sendall.assert_called_once()
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)

    def test_connect_failure_never_tries_another_address(self):
        intent = self.intent()
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.connect.side_effect = ConnectionRefusedError('synthetic unavailable peer')
        with mock.patch.object(socket, 'socket', return_value=sock) as create:
            self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        create.assert_called_once(); sock.connect.assert_called_once_with(('127.0.0.1', self.peer.server_address[1]))
        sock.sendall.assert_not_called()
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)

    def test_no_dns_proxy_or_environment_endpoint_selection(self):
        with mock.patch.dict('os.environ', {'HTTP_PROXY': 'http://192.0.2.1:9999',
                'HTTPS_PROXY': 'http://192.0.2.2:9999', 'JARVISD_URL': 'http://192.0.2.3:9999'}), \
                mock.patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS')):
            self.assertEqual(self.client.submit(self.intent()), p.Outcome.ACKNOWLEDGED)

    def test_authenticated_redirects_never_follow(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                intent = self.intent()
                self.peer.change_reply = lambda path, reply, s=status: replace(reply, status=s) if path == v.COMMAND_PATH else reply
                count = len(self.peer.requests)
                self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
                self.assertEqual(len(self.peer.requests), count + 1)
        self.assertEqual(len(self.host.effects), 1)  # Later new intents remain quarantined.

    def test_authentication_error_rate_limit_and_server_error_never_retry(self):
        for status in (401, 403, 429, 500, 503):
            with self.subTest(status=status):
                intent = self.intent()
                self.peer.change_reply = lambda path, reply, s=status: v._error(s, 'synthetic') if path == v.COMMAND_PATH else reply
                count = len(self.peer.requests)
                self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
                self.assertEqual(len(self.peer.requests), count + 1)

    def test_tampered_body_status_or_proof_are_not_authenticated(self):
        variants = (lambda wire: wire.replace(b'acknowledged', b'xcknowledged'),
                    lambda wire: wire.replace(b'HTTP/1.1 200', b'HTTP/1.1 201'),
                    lambda wire: wire.replace(b'X-Jarvis-Control-Proof: ', b'X-Jarvis-Control-Proof: 0'))
        for transform in variants:
            with self.subTest(transform=transform):
                intent = self.intent()
                # Supply a synthetic signed ACK even once the resource is quarantined;
                # this isolates client proof checks from the ledger's duplicate fence.
                req = intent.request
                self.peer.change_reply = lambda path, reply: v._reply(200, kind='receipt',
                    requestID=req.request_id, incarnation=req.incarnation, epoch=req.epoch,
                    action=req.command.action, requestDigest=req.fingerprint,
                    disposition=p.Outcome.ACKNOWLEDGED.value) if path == v.COMMAND_PATH else reply
                self.peer.change_wire = lambda path, wire: transform(wire) if path == v.COMMAND_PATH else wire
                self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)

    def test_reply_proof_is_bound_to_fresh_challenge_and_request(self):
        first = self.client._transport.exchange(v.WINDOW_PATH,
            v._encode({'protocol': v.PROTOCOL, 'cohort': 'plugs'}))
        self.assertEqual(first.status, 200)
        captured = self.peer.replies[-1]
        self.peer.change_wire = lambda path, wire: captured
        with self.assertRaises(t.TransportError):
            self.client.window(p.Cohort.PLUGS)

    def test_wrong_intended_request_digest_stays_unknown_even_with_authentic_peer(self):
        intent = self.intent()
        def change(path, reply):
            data = json.loads(reply.body)
            if path == v.COMMAND_PATH:
                data['requestDigest'] = '0' * 64
            return replace(reply, body=v._encode(data))
        self.peer.change_reply = change
        self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)

    def test_malformed_framing_partial_and_oversized_replies_stay_unknown(self):
        variants = (
            lambda wire: wire[:-1], lambda wire: wire + b'x',
            lambda wire: wire.replace(b'Content-Length:', b'Content-Length: 2\r\nContent-Length:'),
            lambda wire: wire.replace(b'Content-Length:', b'Transfer-Encoding: chunked\r\nContent-Length:'),
            lambda wire: wire.replace(b'Content-Length:', b' content-Length:'),
            lambda wire: wire.replace(b'Content-Length:', b'Content-Length: 999999\r\nX-Ignored:'),
            lambda wire: wire.replace(b'Cache-Control: no-store', b'Cache-Control: public'),
            lambda wire: wire.replace(b'Connection: close', b'Connection: keep-alive'),
            lambda wire: b'HTTP/1.1 100 Continue\r\n\r\n' + wire,
            lambda wire: b'HTTP/1.1 200 OK\r\nX: ' + b'a' * (t.MAX_HEADER + 1),
            lambda wire: b'HTTP/1.1 200 OK\r\n' + b'X-a: x\r\n' * 34 + wire[wire.index(b'Content-Type:'):],
        )
        for transform in variants:
            with self.subTest(transform=transform):
                intent = self.intent()
                self.peer.change_wire = lambda path, wire: transform(wire) if path == v.COMMAND_PATH else wire
                count = len(self.peer.requests)
                self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
                self.assertEqual(len(self.peer.requests), count + 1)

    def test_invalid_window_data_never_enables_submission(self):
        mutations = ({'epoch': True}, {'maxAgeMs': 25000.0}, {'maxAgeMs': 50000}, {'window': 'bad'},
                     {'cohort': 'purifier'}, {'incarnation': 'BAD'}, {'kind': 'receipt'}, {'extra': True})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.peer.change_reply = lambda path, reply: replace(reply,
                    body=v._encode({**json.loads(reply.body), **mutation}))
                with self.assertRaises(t.TransportError):
                    self.client.window(p.Cohort.PLUGS)
        self.assertEqual(self.host.effects, [])

    def test_duplicate_json_window_and_old_v1_body_are_not_protocol_evidence(self):
        for body in (b'{"protocol":"jarvis-control/2","protocol":"jarvis-control/2"}',
                     b'{"ok":true}', b'{"protocol":"jarvis-control/2","epoch":NaN}'):
            self.peer.change_reply = lambda path, reply: replace(reply, body=body)
            with self.assertRaises(t.TransportError):
                self.client.window(p.Cohort.PLUGS)

    def test_foreign_expired_or_mismatched_window_fails_before_submission(self):
        window = self.client.window(p.Cohort.PLUGS)
        for item in (replace(window, owner=object()), replace(window, received=window.received - 26),
                     replace(window, received=time.monotonic() + 30)):
            with self.assertRaises(t.TransportError):
                self.client.intent(item, 'plug-on', {'plug': 'lamp'})
        with self.assertRaises(t.TransportError):
            self.client.intent(window, 'purifier-set', {'deviceID': 'd' * 24, 'setting': 'power', 'value': 'off'})
        self.assertEqual(len(self.peer.requests), 1)

    def test_transport_never_accepts_v1_alias_or_arbitrary_path(self):
        for path in ('/api/v1/command', v.COMMAND_PATH + '/', v.COMMAND_PATH + '?x=1', 'http://other/'):
            with self.assertRaises(t.TransportError):
                self.client._transport.exchange(path, b'{}')
        self.assertEqual(self.peer.requests, [])

    def test_delayed_reply_does_not_refund_intent(self):
        intent = self.intent()
        self.client._transport._timeout = .05
        def delay(path, wire):
            if path == v.COMMAND_PATH:
                time.sleep(.1)
                return b''
            return wire
        self.peer.change_wire = delay
        self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)

    def test_budget_expires_even_when_peer_trickles(self):
        intent = self.intent()
        self.client._transport._timeout = .1
        self.peer.trickle = True
        started = time.monotonic()
        self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
        self.assertLess(time.monotonic() - started, .8)
        self.assertEqual(len(self.peer.requests), 2)
        with self.assertRaises(t.TransportError):
            self.client.submit(intent)

    def test_window_and_command_share_one_invocation_deadline(self):
        clock = [100.0]
        def advance(path, wire):
            clock[0] = 109.0 if path == v.WINDOW_PATH else 111.0
            return wire
        self.peer.change_wire = advance
        with mock.patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]):
            client = self.peer.client(timeout=10)
            intent = client.intent(client.window(p.Cohort.PLUGS), 'plug-on', {'plug': 'lamp'})
            self.assertEqual(client._deadline, 110.0)
            self.assertEqual(client.submit(intent), p.Outcome.UNKNOWN)
            with self.assertRaises(t.TransportError):
                client.submit(intent)
        self.assertEqual(len(self.host.effects), 1)
        self.assertEqual([r[0] for r in self.peer.requests], [v.WINDOW_PATH, v.COMMAND_PATH])

    def test_expiry_between_metadata_and_submission_consumes_without_connecting(self):
        intent = self.intent()
        self.client._deadline = time.monotonic() - 1
        with mock.patch.object(t.socket, 'socket', side_effect=AssertionError('late socket')):
            self.assertEqual(self.client.submit(intent), p.Outcome.UNKNOWN)
            with self.assertRaises(t.TransportError):
                self.client.submit(intent)
        self.assertEqual(self.host.effects, [])
        self.assertEqual(len(self.peer.requests), 1)

    def test_absolute_caller_deadline_is_not_renewed_by_construction(self):
        with mock.patch.object(t.time, 'monotonic', return_value=100.0):
            client = t.ControlClient(CREDENTIAL, timeout=60, deadline=101.0)
            self.assertEqual(client._deadline, 101.0)
            capped = t.ControlClient(CREDENTIAL, timeout=60, deadline=1000.0)
            self.assertEqual(capped._deadline, 160.0)
        with mock.patch.object(t.time, 'monotonic', return_value=101.0), \
                mock.patch.object(t.socket, 'socket', side_effect=AssertionError('late socket')):
            with self.assertRaises(t.TransportError):
                client.window(p.Cohort.PLUGS)

    def test_invalid_deadlines_fail_before_socket_creation(self):
        with mock.patch.object(t.socket, 'socket', side_effect=AssertionError('invalid deadline socket')):
            for deadline in (True, '100', float('inf'), float('-inf'), float('nan')):
                with self.subTest(deadline=deadline):
                    with self.assertRaises(t.TransportError):
                        t.ControlClient(CREDENTIAL, deadline=deadline)
                    with self.assertRaises(t.TransportError):
                        self.client._transport.exchange(v.WINDOW_PATH, b'{}', deadline=deadline)

    def test_import_purity_and_no_production_wiring(self):
        for module in (a, t):
            spec = importlib.util.spec_from_file_location('jarvisd_core._isolated_control', module.__file__)
            isolated = importlib.util.module_from_spec(spec)
            with mock.patch.dict(sys.modules, {spec.name: isolated}), \
                    mock.patch.object(socket, 'socket', side_effect=AssertionError('network on import')), \
                    mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('IO on import')), \
                    mock.patch.object(Path, 'write_bytes', side_effect=AssertionError('IO on import')):
                spec.loader.exec_module(isolated)
        root = Path(daemon.__file__).parent
        for path in (root / 'jarvisd.py', root.parent / 'jarvis.py'):
            self.assertNotIn('control_transport', path.read_text())
            self.assertNotIn('control_identity', path.read_text())


if __name__ == '__main__':
    unittest.main()
