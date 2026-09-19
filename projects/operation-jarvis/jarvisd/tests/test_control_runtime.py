"""Explicit runtime with real HTTP/auth/ledger/worker checks and fake effects."""
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

import test_device_host as fixtures
from test_jarvisd import jarvisd as daemon
from test_control_transport import certificate
from test_vendor_staging import staging
from jarvisd_core import control_credentials as c, client_policy as p, control_transport as t
from jarvisd_core import control_worker as worker, control_delegation as delegation, vendor_fence as fence
from jarvisd_core.control_http import ControlHTTPServer
from jarvisd_core.control_runtime import ControlRuntime, RuntimeErrorClosed
from jarvisd_core.device_transport import DeviceAdapterRunner
from jarvisd_core.events import EventStore


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.HostTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.path.parent
        (self.root / 'grants').mkdir(mode=0o700)
        source = Path(os.environ.get('JARVIS_TEST_VENDOR_ROOT', str(Path(daemon.__file__).parent.parent)))
        self.operation = self.root / 'operation'
        self.pins = staging.stage(source, self.operation)
        self.bundle = c.initialize(self.root / 'credentials', certificate=certificate(), cohorts=frozenset(p.Cohort))
        self.server = ControlHTTPServer(('127.0.0.1', 0), daemon.Handler)
        self.addCleanup(self.server.server_close)
        self.effect = mock.Mock()
        self.gate = threading.Event(); self.gate.set()
        self.entered = threading.Event()
        self.adapter = DeviceAdapterRunner(cli=Path('/synthetic/cli'),
            worker=Path(daemon.__file__).parent / 'control-worker.py', python=sys.executable,
            operation_root=self.operation, project_root=self.root, run=self.run_worker)
        self.runtime = self.make_runtime()
        self.addCleanup(self.cleanup_runtime)
        patch = mock.patch.object(fence, 'root_directory', return_value=self.root)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(daemon.Handler, 'log_message')
        patch.start(); self.addCleanup(patch.stop)
        self.thread = None

    def make_runtime(self, **changes):
        args = dict(store=self.f.store, bundle=self.bundle, catalogue=self.f.catalogue,
            state=self.f.state, admission=self.f.admission, adapter=self.adapter,
            purifier_wait_seconds=15, vendor_pins=self.pins, root=self.root, port=self.server.server_port)
        args.update(changes)
        return ControlRuntime(**args)

    def cleanup_runtime(self):
        self.gate.set()
        if self.thread is not None:
            self.server.shutdown(); self.thread.join(3)
        self.runtime.close()

    def run_worker(self, argv, **kwargs):
        args = worker.legacy.build_parser().parse_args(argv[3:])
        adapter = mock.Mock()
        def invoke(actual):
            with fence.permission(delegation.worker_call(actual)):
                self.effect(); self.entered.set()
                if not self.gate.wait(3):
                    raise TimeoutError('synthetic blocked worker')
            return self.f.fake_run([str(self.adapter.cli), '--json', args.command, getattr(args, 'plug', '')])
        getattr(adapter, worker.legacy.HANDLERS[args.command]).side_effect = invoke
        with mock.patch.dict(os.environ, kwargs['env']):
            _, result = worker.execute(args, adapter=adapter, emit=mock.Mock())
        return result

    def start(self):
        self.runtime.install(self.server)
        self.f.complete(fixtures.C); self.f.complete(fixtures.P)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        return t.ControlClient(self.bundle.enrollment.credential, port=self.server.server_port, timeout=5)

    def test_full_runtime_authenticated_command_and_scheduled_readback(self):
        client = self.start()
        intent = client.intent(client.window(fixtures.C), 'plug-on', {'plug': 'lamp'})
        self.assertEqual(client.submit(intent), p.Outcome.ACKNOWLEDGED)
        self.effect.assert_called_once()
        self.assertTrue(self.f.rows()[0]['unresolved'])
        self.f.complete(fixtures.C)  # Existing pre-ticket/periodic read cannot clear it.
        for _ in range(30):
            if self.runtime.readbacks.snapshot()['reading']:
                break
            time.sleep(.02)
        self.assertEqual(self.runtime.readbacks.snapshot()['reading'], 1)
        self.f.plugs['lamp']['isOn'] = True; self.f.complete(fixtures.C)
        for _ in range(30):
            if self.runtime.readbacks.snapshot()['reconciled']:
                break
            time.sleep(.02)
        self.assertFalse(self.f.rows()[0]['unresolved'])
        self.assertTrue(self.server.legacy_device_writes_closed)
        self.effect.assert_called_once()

    def test_close_drains_revokes_and_preserves_history(self):
        client = self.start()
        intent = client.intent(client.window(fixtures.C), 'plug-on', {'plug': 'lamp'})
        self.assertEqual(client.submit(intent), p.Outcome.ACKNOWLEDGED)
        self.runtime.close()
        record = json.loads((self.f.path / 'record.json').read_bytes())
        self.assertEqual(record['cohorts']['plugs']['mode'], 'draining')
        self.assertTrue(record['records'][0]['unresolved'])
        self.assertTrue(self.server.legacy_device_writes_closed)
        self.assertIsNone(self.f.store._lfd)
        with self.assertRaises(t.TransportError):
            client.window(fixtures.C)

    def test_elapsed_shutdown_timeout_does_not_release_active_store(self):
        client = self.start()
        intent = client.intent(client.window(fixtures.C), 'plug-on', {'plug': 'lamp'})
        self.gate.clear()
        results = []
        thread = threading.Thread(target=lambda: results.append(client.submit(intent)))
        thread.start()
        try:
            self.assertTrue(self.entered.wait(2))
            with self.assertRaisesRegex(RuntimeErrorClosed, 'still-active'):
                self.runtime.close(timeout=0)
            self.assertIsNotNone(self.f.store._lfd)
            self.assertEqual(self.f.store.active_count(), 1)
            self.assertIs(self.f.store.snapshot(fixtures.C).mode, p.Mode.DRAINING)
        finally:
            self.gate.set(); thread.join(3)
        self.runtime.close()
        self.effect.assert_called_once()
        self.assertTrue(self.f.rows()[0]['unresolved'])

    def test_runtime_cannot_activate_closed_or_draining_store(self):
        self.f.store.transition(fixtures.C, p.Mode.DRAINING)
        with self.assertRaises(Exception):
            self.make_runtime()
        self.assertIs(self.f.store.snapshot(fixtures.C).mode, p.Mode.DRAINING)
        self.assertEqual(self.f.rows(), [])

    def test_wrong_worker_or_store_layout_is_refused(self):
        wrong = DeviceAdapterRunner(cli=self.adapter.cli, worker=Path('/legacy/device-worker.py'),
            python=sys.executable, operation_root=self.root, project_root=self.root, run=self.run_worker)
        with self.assertRaises(RuntimeErrorClosed):
            self.make_runtime(adapter=wrong)
        with self.assertRaises(RuntimeErrorClosed):
            self.make_runtime(root=self.root / 'other')

    def test_runtime_requires_actual_mandatory_vendor_fences(self):
        target = self.operation / 'smart-plug/smart_plug/kasa_client.py'
        target.write_bytes(target.read_bytes() + b'\n# drift\n')
        with self.assertRaises(Exception):
            self.make_runtime()
        with self.assertRaises(Exception):
            self.runtime.install(self.server)
        self.assertFalse(self.runtime._installed)
        self.effect.assert_not_called()

    def test_reinstall_and_wrong_server_port_are_refused(self):
        other = ControlHTTPServer(('127.0.0.1', 0), daemon.Handler)
        try:
            with self.assertRaises(RuntimeErrorClosed):
                self.runtime.install(other)
        finally:
            other.server_close()
        self.runtime.install(self.server)
        with self.assertRaises(RuntimeErrorClosed):
            self.runtime.install(self.server)

    def test_readback_loop_failure_closes_admission_without_replay(self):
        with mock.patch.object(self.runtime.readbacks, 'tick', side_effect=RuntimeError('synthetic failure')):
            self.runtime.install(self.server)
            for _ in range(30):
                if self.runtime._draining:
                    break
                time.sleep(.02)
        self.assertTrue(self.runtime._draining)
        self.assertIs(self.f.store.snapshot(fixtures.C).mode, p.Mode.DRAINING)
        self.effect.assert_not_called()

    def test_failed_readback_thread_start_revokes_and_can_close_cleanly(self):
        with mock.patch.object(threading.Thread, 'start', side_effect=RuntimeError('synthetic start failure')):
            with self.assertRaises(RuntimeError):
                self.runtime.install(self.server)
        self.assertTrue(self.server.legacy_device_writes_closed)
        self.assertTrue(self.runtime._draining)
        self.assertIs(self.f.store.snapshot(fixtures.C).mode, p.Mode.DRAINING)
        self.runtime.close()
        self.assertTrue(self.runtime._closed)

    def test_actual_main_explicit_runtime_install_and_cleanup(self):
        with mock.patch.object(daemon, 'EVENTS_FILE', self.root / 'events.jsonl'), \
                mock.patch.object(daemon, 'EVENTS', EventStore()), \
                mock.patch.object(daemon, 'validate_config'), \
                mock.patch.object(daemon, 'configure_bounded_stderr', return_value=None), \
                mock.patch.object(daemon, 'STATE_COORDINATOR'), \
                mock.patch.object(daemon, 'OMLX_COORDINATOR'), \
                mock.patch.object(daemon, 'ControlHTTPServer', return_value=self.server), \
                mock.patch.object(self.server, 'serve_forever', side_effect=KeyboardInterrupt), \
                mock.patch.object(daemon.sys, 'stderr', io.StringIO()):
            self.assertEqual(daemon.main(control_factory=lambda server: self.runtime), 0)
        self.assertTrue(self.runtime._closed)
        self.assertTrue(self.server.legacy_device_writes_closed)

    def test_main_failed_composition_closes_server_and_collectors(self):
        def fail(server):
            raise RuntimeError('synthetic invalid owner composition')
        with mock.patch.object(daemon, 'EVENTS_FILE', self.root / 'events.jsonl'), \
                mock.patch.object(daemon, 'EVENTS', EventStore()), \
                mock.patch.object(daemon, 'validate_config'), \
                mock.patch.object(daemon, 'configure_bounded_stderr', return_value=None), \
                mock.patch.object(daemon, 'STATE_COORDINATOR') as state, \
                mock.patch.object(daemon, 'OMLX_COORDINATOR'), \
                mock.patch.object(daemon, 'ControlHTTPServer', return_value=self.server), \
                mock.patch.object(self.server, 'server_close') as close, \
                mock.patch.object(self.server, 'serve_forever') as serve, \
                mock.patch.object(daemon.sys, 'stderr', io.StringIO()):
            with self.assertRaises(RuntimeError):
                daemon.main(control_factory=fail)
            serve.assert_not_called(); close.assert_called_once(); state.stop.assert_called_once()
        self.assertTrue(self.server.legacy_device_writes_closed)
