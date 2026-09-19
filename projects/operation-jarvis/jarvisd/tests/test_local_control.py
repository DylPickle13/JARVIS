"""Minimal deployment route: real loopback HTTP, fake dispatch, no device IO."""
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from jarvisd_core import local_control as local
from jarvisd_core.control_http import ControlHTTPServer
from jarvisd_core.devices import _purifier_id

spec = importlib.util.spec_from_file_location('local_cli_legacy', Path(daemon.__file__).parent.parent / 'jarvis.py')
legacy = importlib.util.module_from_spec(spec); spec.loader.exec_module(legacy)


class LocalControlTests(unittest.TestCase):
    def setUp(self):
        self.token = 'a' * 64
        self.effect = mock.Mock(return_value={'ok': True, 'summary': 'synthetic accepted'})
        self.patch = mock.patch.object(daemon, 'dispatch_command', self.effect); self.patch.start()
        self.addCleanup(self.patch.stop)
        self.log = mock.patch.object(daemon.Handler, 'log_message'); self.log.start(); self.addCleanup(self.log.stop)
        self.server = ControlHTTPServer(('127.0.0.1', 0), daemon.Handler)
        self.server.local_control_token = self.token
        self.server.native_request_lock = threading.Lock()
        self.server.native_request_ids = set()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start(); self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def exchange(self, method='POST', body=None, **kwargs):
        return local.exchange(method, body, port=self.server.server_port, token=kwargs.get('token', self.token))

    def native(self, request_id='c'*32, action='plug-on'):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request('POST', '/api/v1/device-command', json.dumps({'action': action, 'params': {'plug': 'fixture'}}),
            {'Content-Type': 'application/json', 'x-jarvis-request-id': request_id})
        response = c.getresponse(); status = response.status; data = json.loads(response.read()); c.close()
        return status, data

    def test_native_write_uses_same_dispatcher_and_consumes_duplicate(self):
        with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True):
            self.assertEqual(self.native()[0], 200)
            self.assertEqual(self.native(action='plug-off')[0], 409)
        self.effect.assert_called_once_with('plug-on', {'plug': 'fixture'})

    def test_native_missing_auth_never_dispatches(self):
        with mock.patch.object(daemon.Handler, '_authorized', return_value=False):
            self.assertIn(self.native()[0], (401, 403))
        self.effect.assert_not_called()
        self.assertFalse(self.server.native_request_ids)

    def test_native_invalid_id_and_full_capacity_do_not_dispatch(self):
        with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True):
            self.assertEqual(self.native('bad')[0], 400)
            self.server.native_request_ids = {str(x) for x in range(4096)}
            self.assertEqual(self.native()[0], 503)
        self.effect.assert_not_called()

    def test_native_failed_dispatch_does_not_refund_request(self):
        self.effect.side_effect = RuntimeError('synthetic lost outcome')
        with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True):
            self.assertEqual(self.native()[0], 503)
            self.assertEqual(self.native()[0], 409)
        self.effect.assert_called_once()

    def test_native_repeated_concurrent_id_has_one_winner(self):
        with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.native()[0], range(4)))
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.effect.assert_called_once()

    def test_authenticated_probe_does_not_dispatch(self):
        result = self.exchange('GET')
        self.assertTrue(result['legacyDeviceWritesDisabled']); self.assertFalse(result['durableOwnership'])
        self.effect.assert_not_called()

    def test_one_authenticated_command(self):
        result = self.exchange(body={'action': 'plug-on', 'params': {'plug': 'fixture'}})
        self.assertTrue(result['ok']); self.effect.assert_called_once_with('plug-on', {'plug': 'fixture'})

    def test_bad_key_and_unknown_commands_never_dispatch(self):
        self.assertFalse(self.exchange(body={'action': 'plug-on', 'params': {'plug': 'fixture'}}, token='b'*64)['ok'])
        self.assertFalse(self.exchange(body={'action': 'shell', 'params': {}})['ok'])
        self.effect.assert_not_called()

    def test_legacy_device_write_closed_but_legacy_read_preserved(self):
        with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True):
            for action, expected in [('plug-on', 409), ('status', 200)]:
                c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
                c.request('POST', '/api/v1/command', json.dumps({'action': action, 'params': {'plug': 'fixture'}}), {'Content-Type': 'application/json'})
                response = c.getresponse(); self.assertEqual(response.status, expected); response.read(); c.close()
        self.effect.assert_called_once_with('status', {'plug': 'fixture'})

    def test_origin_forwarding_and_duplicate_auth_are_rejected(self):
        for name, value in [('Origin', 'http://localhost'), ('X-Forwarded-For', '127.0.0.1'), ('Authorization', 'Bearer '+self.token)]:
            c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
            c.putrequest('GET', local.PATH); c.putheader('Authorization', 'Bearer '+self.token); c.putheader(name, value); c.endheaders()
            response = c.getresponse(); self.assertEqual(response.status, 401); response.read(); c.close()
        self.effect.assert_not_called()

    def test_remote_address_rejected_even_with_key(self):
        request = mock.Mock(server=self.server, client_address=('192.0.2.1', 42))
        request.headers = http.client.parse_headers(io.BytesIO(('Authorization: Bearer '+self.token+'\r\n\r\n').encode()))
        self.assertFalse(local.authorized(request))

    def test_strict_command_validation(self):
        for body in [{'action': 'plug-on', 'params': {'plug': 'fixture', 'host': '192.0.2.1'}},
                     {'action': 'purifier-set', 'params': {'setting': 'speed', 'level': True}},
                     {'action': 'plug-on', 'params': {'plug': 'fixture'}, 'extra': True}]:
            self.assertFalse(self.exchange(body=body)['ok'])
        self.effect.assert_not_called()

    def test_default_and_unique_purifier_binding(self):
        key = _purifier_id('synthetic-cid')
        snapshot = lambda: {'subsystems': {'purifier': {'devices': {key: {'name': 'Fixture purifier'}}}}}
        for selector in (key, 'synthetic-cid', 'Fixture purifier'):
            action, params = local.validated({'action': 'purifier-set', 'params': {'setting': 'power', 'value': 'on', 'selector': selector}}, snapshot)
            self.assertEqual(params['deviceID'], key)
        _, params = local.validated({'action': 'purifier-set', 'params': {'setting': 'power', 'value': 'on'}}, snapshot)
        self.assertNotIn('deviceID', params)
        with self.assertRaises(ValueError):
            local.validated({'action': 'purifier-set', 'params': {'setting': 'power', 'value': 'on', 'selector': 'missing'}}, snapshot)

    def test_private_credentials_missing_modes_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/'token'; root.chmod(0o700)
            with self.assertRaises(ValueError): local.read_token(path)
            path.write_text(self.token); path.chmod(0o600)
            self.assertEqual(local.read_token(path), self.token)
            path.chmod(0o644)
            with self.assertRaises(ValueError): local.read_token(path)
            path.chmod(0o600); link = root/'link'; link.symlink_to(path)
            with self.assertRaises(ValueError): local.read_token(link)

    def test_actual_cli_parser_and_exit_contract_no_vendor_fallback(self):
        with mock.patch.object(legacy, 'emit_event'), mock.patch.object(local, 'exchange', return_value={'ok': True, 'summary': 'synthetic'}) as exchange, mock.patch.object(legacy, 'run', side_effect=AssertionError('vendor fallback'), create=True), mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(legacy.main(['--json', 'plug-on', 'fixture'], command_router=local.Router(legacy)), 0)
            self.assertTrue(json.loads(output.getvalue())['ok'])
            exchange.assert_called_once_with('POST', {'action': 'plug-on', 'params': {'plug': 'fixture'}})
        with mock.patch.object(legacy, 'emit_event'), mock.patch.object(local, 'exchange', side_effect=ValueError('unavailable')), mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(legacy.main(['--json', 'plug-on', 'fixture'], command_router=local.Router(legacy)), 1)
            self.assertFalse(json.loads(output.getvalue())['ok'])

    def test_cli_purifier_settings_and_nondevice_passthrough(self):
        for words in [['power', 'toggle'], ['mode', 'pet'], ['speed', '--level', '3'], ['timer', 'clear'], ['auto-preference', 'quiet', '--room-size', '600']]:
            args = legacy.build_parser().parse_args(['purifier-set', *words])
            with mock.patch.object(local, 'exchange', return_value={'ok': True}) as exchange:
                local.Router(legacy)(args)
                self.assertNotIn('deviceID', exchange.call_args.args[1]['params'])
        args = legacy.build_parser().parse_args(['status', '--no-cast'])
        with mock.patch.object(local, 'exchange') as exchange:
            self.assertIsNone(local.Router(legacy)(args)); exchange.assert_not_called()

    def test_lost_reply_has_one_request_and_no_reconnect(self):
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(2); listener.settimeout(.2)
        calls = []
        def peer():
            c, _ = listener.accept(); c.settimeout(2)
            data = b''
            while b'\r\n\r\n' not in data: data += c.recv(4096)
            calls.append(data); c.close()
            try:
                c, _ = listener.accept(); calls.append(b'retry'); c.close()
            except socket.timeout: pass
        thread = threading.Thread(target=peer); thread.start()
        try:
            with self.assertRaisesRegex(ValueError, 'unknown'):
                local.exchange('POST', {'action': 'plug-on', 'params': {'plug': 'fixture'}}, port=listener.getsockname()[1], token=self.token)
            thread.join(3); self.assertEqual(len(calls), 1)
        finally: listener.close()

    def test_redirect_is_not_followed(self):
        with mock.patch.object(daemon.Handler, 'do_POST', lambda h: (setattr(h, 'request_id', 'test'), h._send(307, {}, {'Location': local.PATH}))):
            with self.assertRaisesRegex(ValueError, 'unknown'):
                self.exchange(body={'action': 'plug-on', 'params': {'plug': 'fixture'}})
        self.effect.assert_not_called()
