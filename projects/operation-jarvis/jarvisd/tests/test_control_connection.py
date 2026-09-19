"""Credential/real HTTP handler/actual CLI tests with temporary stores and fake effects."""
import contextlib
import copy
from dataclasses import replace
from http.server import ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from test_control_ledger import handoff
from test_control_protocol import Host
from test_control_transport import certificate, request_headers
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core import control_identity as a, control_credentials as c, control_cli as cli
from jarvisd_core import control_transport as t, control_http as h

OP = Path(daemon.__file__).parent.parent


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'private'
        self.cert = certificate()

    def provision(self, **kwargs):
        return c.initialize(self.path, certificate=self.cert, cohorts=frozenset(p.Cohort), **kwargs)

    def test_explicit_private_provision_and_roundtrip(self):
        original = self.provision()
        self.assertEqual(original, c.load(self.path))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.path / 'bundle.json').stat().st_mode & 0o777, 0o600)
        self.assertNotIn(original.enrollment.credential.key, repr(original))
        self.assertNotEqual(original.enrollment.principal, original.enrollment.credential.key)
        self.assertNotEqual(original.enrollment.credential.client_id, original.enrollment.credential.key[:32])

    def test_no_reinitialize_overwrite_or_automatic_recovery(self):
        self.provision()
        before = (self.path / 'bundle.json').read_bytes()
        with self.assertRaises(c.CredentialError):
            self.provision()
        self.assertEqual((self.path / 'bundle.json').read_bytes(), before)
        (self.path / 'bundle.json').unlink()
        for action in (lambda: c.load(self.path), self.provision):
            with self.assertRaises(c.CredentialError):
                action()
        self.assertEqual(list(self.path.iterdir()), [])

    def test_source_drift_never_creates_a_bundle(self):
        self.cert = replace(self.cert, sources=())
        with self.assertRaises(c.CredentialError):
            self.provision()
        self.assertFalse(self.path.exists())

    def test_private_modes_links_ownership_and_nonregular_file(self):
        self.provision()
        file = self.path / 'bundle.json'
        for mode in (0o644, 0o660):
            file.chmod(mode)
            with self.assertRaises(c.CredentialError):
                c.load(self.path)
        file.chmod(0o600)
        with mock.patch.object(os, 'geteuid', return_value=os.geteuid() + 1):
            with self.assertRaises(c.CredentialError):
                c.load(self.path)
        self.path.chmod(0o755)
        with self.assertRaises(c.CredentialError):
            c.load(self.path)
        self.path.chmod(0o700)
        link = self.root / 'link'; link.symlink_to(self.path)
        with self.assertRaises(c.CredentialError):
            c.load(link)
        copy_path = self.root / 'hard-link'; os.link(file, copy_path)
        with self.assertRaises(c.CredentialError):
            c.load(self.path)
        copy_path.unlink()
        file.rename(self.path / 'backup')
        file.symlink_to(self.path / 'backup')
        with self.assertRaises(c.CredentialError):
            c.load(self.path)
        file.unlink(); os.mkfifo(file, 0o600)
        with self.assertRaises(c.CredentialError):
            c.load(self.path)

    def test_corrupt_duplicate_unknown_and_oversized_records(self):
        self.provision()
        file = self.path / 'bundle.json'
        original = json.loads(file.read_bytes())
        for raw in (b'{', b'{}', b'x' * (c.MAX_BYTES + 1),
                    json.dumps({**original, 'extra': True}).encode(),
                    json.dumps({**original, 'cohorts': ['plugs', 'plugs']}).encode(),
                    json.dumps({**original, 'key': 'bad'}).encode(),
                    b'{"schema":"x","schema":"y"}'):
            file.write_bytes(raw)
            with self.assertRaises(c.CredentialError):
                c.load(self.path)

    def test_default_target_requires_exact_epoch_identity_and_purifier_scope(self):
        default = c.DefaultTarget('d' * 24, 'e' * 32, 7)
        self.assertEqual(self.provision(default=default).default, default)
        for epoch in (True, 0, 7.0, p.MAX_EPOCH):
            with self.assertRaises(c.CredentialError):
                c.DefaultTarget('d' * 24, 'e' * 32, epoch)

    def test_sync_failure_leaves_closed_incomplete_store_not_new_identity(self):
        with mock.patch.object(os, 'fsync', side_effect=OSError('synthetic sync fault')):
            with self.assertRaises(c.CredentialError):
                self.provision()
        with self.assertRaises(c.CredentialError):
            c.load(self.path)
        with self.assertRaises(c.CredentialError):
            self.provision()

    def test_home_environment_cannot_redirect_private_profile(self):
        original = c.default_directory()
        with mock.patch.dict(os.environ, {'HOME': str(self.root)}):
            self.assertEqual(c.default_directory(), original)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / 'credentials'
        self.bundle = c.initialize(self.private, certificate=certificate(), cohorts=frozenset(p.Cohort))
        store_path = self.root / 'ledger'
        g.ControlLedger.initialize(store_path)
        self.store = g.ControlLedger.open(store_path)
        self.addCleanup(self.store.close)
        handoff(self.store); handoff(self.store, p.Cohort.PURIFIER)
        self.host = Host()
        self.api = v.ControlProtocol(self.store, self.host)
        self.server = h.ControlHTTPServer(('127.0.0.1', 0), daemon.Handler)
        self.server.daemon_threads = True
        self.registry = a.IdentityRegistry(enrollments=(self.bundle.enrollment,), certificate=self.bundle.certificate,
                                           port=self.server.server_port)
        self.endpoint = h.ControlEndpoint(registry=self.registry, api=self.api, input_timeout=.3)
        self.endpoint.install(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.logs = mock.patch.object(daemon.Handler, 'log_message')
        self.logs.start(); self.addCleanup(self.logs.stop)
        self.client = t.ControlClient(self.bundle.enrollment.credential, port=self.server.server_port, timeout=2)
        operation = self.root / 'projects/operation-jarvis'
        operation.mkdir(parents=True)
        shutil.copy2(OP / 'jarvis.py', operation / 'jarvis.py')
        spec = importlib.util.spec_from_file_location('isolated_connection_cli', operation / 'jarvis.py')
        self.legacy = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {}, clear=True):
            spec.loader.exec_module(self.legacy)
        self.router = cli.Router(self.legacy, directory=self.private, port=self.server.server_port)

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(self.legacy, 'emit_event'), \
                mock.patch.object(self.legacy, 'run_smart_plug_command', side_effect=AssertionError('direct plug')) as plug, \
                mock.patch.object(self.legacy, 'run_air_purifier_command', side_effect=AssertionError('direct purifier')) as purifier:
            result = self.legacy.main(['--json', *args], command_router=self.router)
        plug.assert_not_called(); purifier.assert_not_called()
        return result, json.loads(output.getvalue())

    def wire(self, raw):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(('127.0.0.1', self.server.server_port))
            sock.sendall(raw); sock.shutdown(socket.SHUT_WR)
            reply = bytearray()
            while True:
                try:
                    chunk = sock.recv(4096)
                except ConnectionResetError:
                    break  # Unread pipelined bytes are deliberately discarded.
                if not chunk:
                    break
                reply.extend(chunk)
            return bytes(reply)

    def packet(self, body, path=v.WINDOW_PATH):
        headers = request_headers(body, path=path, port=self.server.server_port,
                                  credential=self.bundle.enrollment.credential)
        return (f'POST {path} HTTP/1.1\r\n'.encode() +
            b''.join(f'{k}: {val}\r\n'.encode() for k, val in headers) + b'\r\n' + body)

    def intent(self):
        return self.client.intent(self.client.window(p.Cohort.PLUGS), 'plug-on', {'plug': 'lamp'})

    def test_real_handler_to_ledger_and_cli_receipt(self):
        code, result = self.invoke(['plug-on', 'lamp'])
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertEqual(result['control']['disposition'], p.Outcome.ACKNOWLEDGED.value)
        self.assertEqual(len(self.host.effects), 1)
        self.assertNotIn('plug', result)
        self.assertNotIn(self.bundle.enrollment.credential.key, json.dumps(result))

    def test_real_dispatcher_and_authenticated_final_authorizer(self):
        from test_device_host import HostTests, C
        fixture = HostTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.host = fixture.make_host(authorize=self.registry.authorize)
        fixture.complete(C)
        self.endpoint.api = v.ControlProtocol(fixture.store, fixture.host)
        code, result = self.invoke(['plug-on', 'lamp'])
        self.assertEqual(code, 0, result)
        fixture.runner.assert_called_once()
        self.assertTrue(fixture.rows()[0]['unresolved'])

    def test_live_v1_device_route_fenced_but_read_command_retained(self):
        with mock.patch.object(daemon.Handler, '_authorized', return_value=True), \
                mock.patch.object(daemon, 'dispatch_command', return_value={'ok': True}) as dispatch:
            for action in ('plug-on', 'plug-off', 'plug-toggle', 'purifier-set', 'plug-status'):
                body = json.dumps({'action': action, 'params': {'plug': 'lamp'}}).encode()
                packet = (f'POST /api/v1/command HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
                reply = self.wire(packet)
                self.assertIn(b'200' if action == 'plug-status' else b'409', reply.split(b'\r\n')[0])
            dispatch.assert_called_once_with('plug-status', {'plug': 'lamp'})
        self.assertEqual(self.host.effects, [])

    def test_health_state_and_service_api_survive_device_write_retirement(self):
        with mock.patch.object(daemon.Handler, '_authorized', return_value=True), \
                mock.patch.object(daemon, 'collect_state', return_value={'ok': True, 'subsystems': {}}), \
                mock.patch.object(daemon, '_service_action', return_value={'ok': True}) as service, \
                mock.patch.object(daemon, 'STATE_COORDINATOR'):
            for path in ('/health', '/api/v1/state'):
                reply = self.wire(f'GET {path} HTTP/1.1\r\nConnection: close\r\n\r\n'.encode())
                self.assertIn(b'200', reply.split(b'\r\n')[0])
            body = b'{"action":"status"}'
            reply = self.wire(f'POST /api/v1/services/synthetic HTTP/1.1\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
            self.assertIn(b'200', reply.split(b'\r\n')[0])
            service.assert_called_once_with('synthetic', 'status')
        self.assertEqual(self.host.effects, [])

    def test_no_endpoint_preserves_legacy_write_handler_in_test_only(self):
        # Simulate main()'s never-mounted legacy server, NOT an allowed rollback.
        self.server.control_endpoint = None
        self.server.legacy_device_writes_closed = False
        with mock.patch.object(daemon.Handler, '_authorized', return_value=True), \
                mock.patch.object(daemon, 'dispatch_command', return_value={'ok': True}) as dispatch:
            body = b'{"action":"plug-on","params":{"plug":"lamp"}}'
            reply = self.wire(f'POST /api/v1/command HTTP/1.1\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
            self.assertIn(b'200', reply.split(b'\r\n')[0])
            dispatch.assert_called_once()

    def test_endpoint_loss_does_not_reopen_legacy_writes(self):
        self.server.control_endpoint = None
        with mock.patch.object(daemon.Handler, '_authorized', return_value=True), \
                mock.patch.object(daemon, 'dispatch_command', side_effect=AssertionError('legacy replay')) as dispatch:
            body = b'{"action":"plug-on","params":{"plug":"lamp"}}'
            reply = self.wire(f'POST /api/v1/command HTTP/1.1\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
            self.assertIn(b'409', reply.split(b'\r\n')[0])
            dispatch.assert_not_called()
        with self.assertRaises(ValueError):
            self.endpoint.install(self.server)

    def test_bad_raw_framing_never_reaches_protocol_or_legacy(self):
        body = v._encode({'protocol': v.PROTOCOL, 'cohort': 'plugs'})
        normal = self.packet(body)
        packets = (normal.replace(b'Content-Length:', b'Content-Length: 1\r\nContent-Length:'),
            normal.replace(b'Content-Length:', b'Transfer-Encoding: chunked\r\nContent-Length:'),
            normal.replace(b'Content-Length:', b'Content-Length: 20000\r\nX-Dummy:'),
            normal.replace(b'Content-Length:', b' Content-Length:'),
            normal.replace(b'Connection: close', b'Connection: keep-alive'),
            normal.replace(b'POST ', b'GET ', 1), normal.replace(b'HTTP/1.1', b'HTTP/1.0', 1),
            normal.replace(v.WINDOW_PATH.encode(), (v.WINDOW_PATH + '/').encode(), 1),
            normal.replace(b'\r\n', b'\n'), normal[:-1],
            b'POST /api/v2/control/window HTTP/1.1\r\nX: ' + b'x' * 4097)
        with mock.patch.object(self.api, 'handle', side_effect=AssertionError('framing bypass')) as handle, \
                mock.patch.object(daemon, 'dispatch_command', side_effect=AssertionError('legacy fallback')) as legacy:
            for raw in packets:
                reply = self.wire(raw)
                self.assertNotIn(b' 200 ', reply.split(b'\r\n')[0])
            handle.assert_not_called(); legacy.assert_not_called()

    def test_raw_input_deadline_even_while_body_trickles(self):
        body = v._encode({'protocol': v.PROTOCOL, 'cohort': 'plugs'})
        raw = self.packet(body)
        headers = raw[:raw.index(b'\r\n\r\n') + 4]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2); sock.connect(('127.0.0.1', self.server.server_port)); sock.sendall(headers)
            for byte in body[:8]:
                try:
                    sock.sendall(bytes([byte])); time.sleep(.06)
                except OSError:
                    break
            reply = sock.recv(4096)
            self.assertIn(b'408', reply.split(b'\r\n')[0])
        self.assertEqual(self.host.effects, [])

    def test_pipeline_cannot_execute_a_second_command(self):
        intent = self.intent()
        raw = self.packet(intent._body, v.COMMAND_PATH)
        reply = self.wire(raw + raw)
        self.assertEqual(reply.count(b'HTTP/1.1'), 1)
        self.assertEqual(len(self.host.effects), 1)

    def test_bounded_connections_reject_without_queue(self):
        acquired = [self.endpoint._slots.acquire(False) for _ in range(32)]
        self.assertTrue(all(acquired))
        try:
            with self.assertRaises(t.TransportError):
                self.client.window(p.Cohort.PLUGS)
        finally:
            for _ in acquired:
                self.endpoint._slots.release()
        self.assertEqual(self.host.effects, [])

    def test_connection_limit_rejects_before_creating_another_thread(self):
        taken = [self.server._connections.acquire(False) for _ in range(64)]
        self.assertTrue(all(taken))
        try:
            with mock.patch.object(self.server, 'process_request_thread', side_effect=AssertionError('extra thread')) as thread:
                with self.assertRaises(t.TransportError):
                    self.client.window(p.Cohort.PLUGS)
                thread.assert_not_called()
        finally:
            for _ in taken:
                self.server._connections.release()
        self.assertEqual(self.host.effects, [])

    def test_unknown_reply_exits_nonzero_without_retry(self):
        self.host.outcome = p.Outcome.UNKNOWN
        code, result = self.invoke(['plug-on', 'lamp'])
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertIn('do not retry', result['summary'])
        self.assertEqual(len(self.host.effects), 1)

    def test_reply_loss_after_effect_does_not_fall_back_or_retry(self):
        original = self.endpoint.send
        def send(handler, reply, headers=None):
            if b'"kind":"receipt"' in reply.body:
                return
            return original(handler, reply, headers)
        with mock.patch.object(self.endpoint, 'send', side_effect=send):
            code, result = self.invoke(['plug-on', 'lamp'])
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.host.effects), 1)

    def test_missing_credentials_wrong_source_scope_or_bad_selection_never_falls_back(self):
        original = self.router
        cases = [cli.Router(self.legacy, directory=self.root / 'absent', port=self.server.server_port), original]
        for router in cases:
            self.router = router
            args = ['plug-on', 'lamp'] if router is not original else ['purifier-set', 'power', 'on', '--purifier', 'raw-private-cid']
            code, result = self.invoke(args)
            self.assertEqual(code, 1)
            self.assertFalse(result['ok'])
        self.assertEqual(self.host.effects, [])

    def test_default_purifier_requires_matching_window_epoch(self):
        for epoch in (999, self.store.context(p.Cohort.PURIFIER)[0].epoch):
            default = c.DefaultTarget('d' * 24, self.store.context(p.Cohort.PURIFIER)[1], epoch)
            bundle = replace(self.bundle, default=default)
            with mock.patch.object(c, 'load', return_value=bundle):
                code, result = self.invoke(['purifier-set', 'power', 'off'])
            self.assertEqual(code, 0 if epoch != 999 else 1, result)
        self.assertEqual(len(self.host.effects), 1)

    def test_canonical_purifier_settings_reuse_validator_without_argv_execution(self):
        choices = [(['power', 'on'], {'setting': 'power', 'value': 'on'}),
            (['speed', '--level', '3'], {'setting': 'speed', 'level': 3}),
            (['timer', 'clear'], {'setting': 'timer', 'value': 'clear'}),
            (['timer', '--minutes', '5'], {'setting': 'timer', 'minutes': 5}),
            (['mode', 'sleep'], {'setting': 'mode', 'value': 'sleep'}),
            (['display', '--state', 'off'], {'setting': 'display', 'value': 'off'})]
        for words, expected in choices:
            args = self.legacy.build_parser().parse_args(['purifier-set', *words, '--purifier', 'd' * 24])
            before = copy.copy(vars(args))
            command = cli.operation(self.legacy, args)
            self.assertEqual(dict(command.params), {'deviceID': '0' * 24, **expected})
            self.assertEqual(vars(args), before)
        for words in (['plug-on', '192.0.2.1'], ['plug-on', 'lamp', '--plug-config', '/tmp/other'],
                      ['purifier-set', 'power', 'on', '--level', '3'], ['purifier-set', 'speed', '2', '--level', '3']):
            code, result = self.invoke(words)
            self.assertEqual(code, 1)
        self.assertEqual(self.host.effects, [])

    def test_candidate_blocks_catalogue_mutation_and_documents_stricter_help(self):
        code, result = self.invoke(['plug-save-discovery'])
        self.assertEqual(code, 1)
        self.assertIn('owner maintenance', result['error'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit:
            self.legacy.main(['purifier-set', '--help'], command_router=self.router)
        self.assertEqual(exit.exception.code, 0)
        self.assertIn('Opaque 24-hex deviceID', output.getvalue())
        self.assertEqual(self.host.effects, [])

    def test_pending_receipt_is_not_presented_as_fresh_state(self):
        self.host.outcome = p.Outcome.PENDING
        code, result = self.invoke(['purifier-set', 'power', 'off', '--purifier', 'd' * 24])
        self.assertEqual(code, 0)
        self.assertTrue(result['verificationPending'])
        self.assertNotIn('purifier', result)
        self.assertIn('verification is pending', result['summary'])

    def test_non_device_actions_keep_original_execution_and_exit_contract(self):
        with mock.patch.object(self.legacy, 'handle_status', return_value={'ok': False, 'summary': 'unchanged'}) as status:
            code, result = self.invoke(['status', '--no-cast'])
        self.assertEqual(code, 0)
        status.assert_called_once()
        self.assertFalse(result['ok'])
        self.assertEqual(self.host.effects, [])

    def test_candidate_wrapper_subprocess_with_temp_profile_and_synthetic_endpoint(self):
        operation = Path(self.legacy.__file__).parent
        shutil.copy2(OP / 'control-cli.py', operation / 'control-cli.py')
        (operation / 'jarvisd').symlink_to(OP / 'jarvisd')
        program = '''import runpy,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from jarvisd_core import control_cli
original=control_cli.Router.__init__
directory,port=Path(sys.argv[2]),int(sys.argv[3])
def fixture(self,legacy):
    original(self,legacy,directory=directory,port=port)
control_cli.Router.__init__=fixture
entry=sys.argv[4]
sys.argv=[entry,'--json','plug-on','lamp']
runpy.run_path(entry,run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(OP / 'jarvisd'), str(self.private),
            str(self.server.server_port), str(operation / 'control-cli.py')], capture_output=True, text=True,
            env={'PATH': os.environ['PATH'], 'JARVIS_EMIT_EVENTS': '0'}, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertEqual(len(self.host.effects), 1)


if __name__ == '__main__':
    unittest.main()
