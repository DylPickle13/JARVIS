"""Closed recovery role against staged files, temporary history and loopback HTTP."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest import mock

from test_jarvisd import jarvisd as daemon
from test_vendor_staging import staging
from test_control_ledger import handoff, intent_for, ready
from jarvisd_core import control_closed as closed, control_ledger as g, client_policy as p
from jarvisd_core.control_http import ControlHTTPServer


class ClosedRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(os.environ.get('JARVIS_TEST_VENDOR_ROOT', str(Path(daemon.__file__).parent.parent)))
        self.stage = self.root / 'stage'
        self.pins = staging.stage(source, self.stage)
        self.owner = self.root / 'owner'; self.owner.mkdir(mode=0o700)
        self.original_server = object()
        self.host = types.SimpleNamespace(OPERATION_ROOT=self.stage,
            ThreadingHTTPServer=self.original_server, main=lambda: 0)

    def history(self):
        path = self.owner / 'ledger'
        g.ControlLedger.initialize(path)
        store = g.ControlLedger.open(path)
        handoff(store)
        intent = intent_for(store)
        store.execute_once(intent, lambda: ready(intent), lambda: g.DispatchResult(p.Outcome.ACKNOWLEDGED))
        store.close()
        return json.loads((path / 'record.json').read_bytes())

    def test_closed_role_advances_epoch_retains_history_and_holds_owner(self):
        before = self.history()
        def serve():
            self.assertIs(self.host.ThreadingHTTPServer, ControlHTTPServer)
            record = json.loads((self.owner / 'ledger/record.json').read_bytes())
            self.assertTrue(all(c['mode'] == 'closed' for c in record['cohorts'].values()))
            self.assertNotEqual(before['incarnation'], record['incarnation'])
            self.assertEqual(before['records'], record['records'])
            with self.assertRaises(g.LedgerError):
                g.ControlLedger.open(self.owner / 'ledger')
            return 0
        self.host.main = serve
        self.assertEqual(closed.run_closed(self.host, pins=self.pins, root=self.owner), 0)
        self.assertIs(self.host.ThreadingHTTPServer, self.original_server)
        with g.ControlLedger.open(self.owner / 'ledger') as store:
            self.assertTrue(store.pending_resources(p.Cohort.PLUGS))

    def test_missing_history_is_not_recreated_for_status_role(self):
        self.assertEqual(closed.run_closed(self.host, pins=self.pins, root=self.owner), 0)
        self.assertFalse((self.owner / 'ledger').exists())

    def test_busy_or_corrupt_history_refuses_without_running_server(self):
        self.history()
        self.host.main = mock.Mock()
        with g.ControlLedger.open(self.owner / 'ledger'):
            with self.assertRaises(closed.ClosedRoleError):
                closed.run_closed(self.host, pins=self.pins, root=self.owner)
        self.host.main.assert_not_called()
        path = self.owner / 'ledger/record.json'; path.write_text('corrupt')
        with self.assertRaises(closed.ClosedRoleError):
            closed.run_closed(self.host, pins=self.pins, root=self.owner)
        self.assertEqual(path.read_text(), 'corrupt')
        self.host.main.assert_not_called()

    def test_sdk_drift_or_missing_helper_never_selects_old_vendor_files(self):
        self.host.main = mock.Mock()
        target = self.stage / 'smart-plug/smart_plug/vendor_fence.py'
        target.write_bytes(target.read_bytes() + b'\n# drift\n')
        with self.assertRaises(closed.ClosedRoleError):
            closed.run_closed(self.host, pins=self.pins, root=self.owner)
        self.host.main.assert_not_called()
        self.assertFalse((self.owner / 'ledger').exists())
        with self.assertRaises(closed.ClosedRoleError):
            closed.verify_fences(self.stage, {k: v for k, v in self.pins.items() if 'vendor_fence' not in k})

    def test_manifest_cannot_bless_unfenced_wrappers_by_rehashing_them(self):
        source = Path(os.environ.get('JARVIS_TEST_VENDOR_ROOT', str(Path(daemon.__file__).parent.parent)))
        relative = 'smart-plug/smart_plug/kasa_client.py'
        (self.stage / relative).write_bytes((source / relative).read_bytes())
        changed = {**self.pins, relative: closed.source_digest(self.stage / relative)}
        with self.assertRaises(closed.ClosedRoleError):
            closed.verify_fences(self.stage, changed)

    def test_manifest_is_private_bounded_and_never_recomputed(self):
        path = self.root / 'pins.json'
        path.write_text(json.dumps({'schema': 1, 'files': self.pins})); path.chmod(0o600)
        self.assertEqual(closed.load_pins(path), self.pins)
        path.chmod(0o644)
        with self.assertRaises(closed.ClosedRoleError):
            closed.load_pins(path)
        path.chmod(0o600); path.write_bytes(b' ' * 16385)
        with self.assertRaises(closed.ClosedRoleError):
            closed.load_pins(path)
        path.write_text('{"schema":1,"schema":1,"files":{}}')
        with self.assertRaises(closed.ClosedRoleError):
            closed.load_pins(path)

    def test_server_failure_releases_closed_store_without_restoring_history(self):
        before = self.history()
        self.host.main = mock.Mock(side_effect=RuntimeError('synthetic server failure'))
        with self.assertRaises(RuntimeError):
            closed.run_closed(self.host, pins=self.pins, root=self.owner)
        self.assertIs(self.host.ThreadingHTTPServer, self.original_server)
        after = json.loads((self.owner / 'ledger/record.json').read_bytes())
        self.assertGreater(after['revision'], before['revision'])
        self.assertEqual(after['records'], before['records'])
        with g.ControlLedger.open(self.owner / 'ledger'):
            pass

    def test_actual_closed_handler_rejects_device_write_before_dispatch(self):
        def serve():
            server = self.host.ThreadingHTTPServer(('127.0.0.1', 0), daemon.Handler)
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            try:
                with mock.patch.object(daemon.Handler, '_auth_or_respond', return_value=True), \
                        mock.patch.object(daemon.Handler, 'log_message'), \
                        mock.patch.object(daemon, 'dispatch_command', side_effect=AssertionError('write dispatched')):
                    body = json.dumps({'action': 'plug-on', 'params': {'plug': 'fixture'}})
                    connection.request('POST', '/api/v1/command', body, {'Content-Type': 'application/json'})
                    reply = connection.getresponse()
                    self.assertEqual(reply.status, 409); reply.read()
                    connection.request('GET', '/health')
                    reply = connection.getresponse()
                    self.assertEqual(reply.status, 200); reply.read()
            finally:
                connection.close(); server.shutdown(); server.server_close(); thread.join(2)
            return 0
        self.host.main = serve
        self.assertEqual(closed.run_closed(self.host, pins=self.pins, root=self.owner), 0)
