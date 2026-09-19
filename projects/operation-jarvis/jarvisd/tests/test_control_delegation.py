"""Real admission/issuance/worker checkpoint; temporary stores, fake SDK effects."""
import concurrent.futures
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import subprocess
import sys
import unittest
from unittest import mock

import test_device_host as fixtures
from test_device_host import ACCESS, C, P, CID, DEVICE
from jarvisd_core import client_policy as p, control_ledger as g, control_protocol as v
from jarvisd_core import control_delegation as d, control_worker as w, vendor_fence as f
from jarvisd_core.device_worker import build_parser


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HostTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.root = self.fixture.path.parent
        (self.root / 'grants').mkdir(mode=0o700)
        self.effects = []
        self.calls = []
        self.runner = d.DelegatingRunner(store=self.store, runner=self.worker, root=self.root)
        self.host = self.fixture.make_host(runner=self.runner, delegation=self.runner)
        self.fixture.complete(C); self.fixture.complete(P)
        self.api = v.ControlProtocol(self.store, self.host)
        patch = mock.patch.object(f, 'root_directory', return_value=self.root)
        patch.start(); self.addCleanup(patch.stop)

    def args(self, argv):
        return build_parser().parse_args(['--operation-root', '/synthetic', '--project-root', '/synthetic',
                                          '--json', *argv[2:]])

    def worker(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        args = self.args(argv)
        adapter = mock.Mock()
        def effect(actual):
            # Stand-in for SDK checkpoint. Never imports/connects a device SDK.
            with f.permission(d.worker_call(actual)):
                self.effects.append(actual.command)
            return self.fixture.fake_run(argv)
        getattr(adapter, w.legacy.HANDLERS[args.command]).side_effect = effect
        with mock.patch.dict(os.environ, kwargs['env']):
            _, result = w.execute(args, adapter=adapter, emit=mock.Mock())
        return result

    def submit(self, **kwargs):
        body = v._encode(self.fixture.request(**kwargs))
        reply = self.api.handle(method='POST', path=v.COMMAND_PATH, content_type=v.CONTENT_TYPE,
                                body=body, access=ACCESS)
        return json.loads(reply.body)

    def admitted(self, callback, *, command=None):
        command = command or v._command('plug-on', {'plug': 'lamp'})
        bound = self.host.prepare(command, ACCESS)
        window = self.store.issue_window(command.cohort, ACCESS.principal)
        intent = g.Intent(command.cohort, window.incarnation, window.epoch, ACCESS.principal,
            '1' * 32, bound.resource, bound.fingerprint, command.action, window.token)
        entry = self.host._entry(command)
        def run():
            callback(bound, entry, intent)
            return g.DispatchResult(p.Outcome.UNKNOWN)
        self.store.execute_once(intent, lambda: self.host.readiness(bound, ACCESS, window.epoch), run)
        return bound

    def test_real_host_ledger_runner_worker_and_sdk_checkpoint(self):
        result = self.submit()
        self.assertEqual(result['disposition'], p.Outcome.ACKNOWLEDGED.value)
        self.assertEqual(self.effects, ['plug-on'])
        files = sorted((self.root / 'grants').iterdir())
        self.assertEqual({p.suffix for p in files}, {'.json', '.worker', '.mutation'})
        self.assertEqual(len(files), 3)
        self.assertTrue(self.store.pending_resources(C))
        self.assertNotIn(self.calls[0][1]['env'][f.TOKEN_ENV], json.dumps(result))

    def test_purifier_exact_cid_method_and_seconds_conversion(self):
        result = self.submit(action='purifier-set', params={'deviceID': DEVICE, 'setting': 'timer', 'minutes': 7})
        self.assertEqual(result['disposition'], p.Outcome.ACKNOWLEDGED.value)
        grant = json.loads(next((self.root / 'grants').glob('*.json')).read_bytes())
        self.assertEqual(grant['call'], {'cohort': 'purifier', 'target': CID, 'method': 'set_timer',
                                        'args': [420], 'kwargs': {}})
        self.assertEqual(self.effects, ['purifier-set'])

    def test_second_issuer_cannot_delegate_same_active_reservation(self):
        def callback(bound, entry, intent):
            second = d.DelegatingRunner(store=self.store, runner=self.worker, root=self.root)
            with self.runner.scope(bound, entry):
                pass
            with self.assertRaises(g.LedgerError):
                with second.scope(bound, entry):
                    self.fail('duplicate grant')
        self.admitted(callback)
        self.assertEqual(len(list((self.root / 'grants').glob('*.json'))), 1)

    def test_no_delegation_before_after_or_in_another_thread(self):
        command = v._command('plug-on', {'plug': 'lamp'})
        bound, entry = self.host.prepare(command, ACCESS), self.host._entry(command)
        def attempt():
            with self.runner.scope(bound, entry):
                self.fail('outside callback')
        with self.assertRaises(g.LedgerError):
            attempt()
        def callback(*_):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(g.LedgerError):
                    pool.submit(attempt).result(3)
        self.admitted(callback)
        with self.assertRaises(g.LedgerError):
            attempt()
        self.assertEqual(list((self.root / 'grants').iterdir()), [])

    def test_binding_changes_cannot_borrow_current_callback(self):
        def callback(bound, entry, intent):
            wrong = self.host.prepare(v._command('plug-off', {'plug': 'lamp'}), ACCESS)
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(wrong, entry):
                    self.fail('wrong command')
            wrong = self.host.prepare(v._command('plug-on', {'plug': 'tv'}), ACCESS)
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(wrong, self.host._entry(wrong.command)):
                    self.fail('wrong target')
        self.admitted(callback)

    def test_publishing_failure_consumes_delegation_without_refund(self):
        def callback(bound, entry, intent):
            with mock.patch.object(f, 'write_new', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):
                    with self.runner.scope(bound, entry):
                        self.fail('failed publication')
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(bound, entry):
                    self.fail('refunded grant')
        self.admitted(callback)
        self.assertEqual(self.effects, [])
        self.assertTrue(self.store.pending_resources(C))

    def test_random_collision_never_overwrites_or_mints_an_alternate_token(self):
        collision = 'f' * 64
        path = self.root / 'grants' / (collision + '.json')
        path.write_text('retained'); path.chmod(0o600)
        def callback(bound, entry, intent):
            with mock.patch.object(d.secrets, 'token_hex', return_value=collision) as rng:
                with self.assertRaises(FileExistsError):
                    with self.runner.scope(bound, entry):
                        self.fail('collision')
                self.assertEqual(rng.call_count, 1)
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(bound, entry):
                    self.fail('alternate token')
        self.admitted(callback)
        self.assertEqual(path.read_text(), 'retained')

    def test_grant_retains_original_window_start_not_issuance_time(self):
        def callback(bound, entry, intent):
            started = tuple(n - g.TTL_NS for n in self.store._windows[intent.window][1])
            with self.runner.scope(bound, entry):
                grant = json.loads(next((self.root / 'grants').glob('*.json')).read_bytes())
                self.assertEqual((grant['monotonic'], grant['wall']), started)
        self.admitted(callback)

    def test_drain_before_issue_and_during_publication_prevent_dispatch(self):
        def callback(bound, entry, intent):
            original = f.write_new
            def drain(*args):
                fd = original(*args)
                self.store.transition(C, p.Mode.DRAINING)
                return fd
            with mock.patch.object(f, 'write_new', side_effect=drain), self.assertRaises(f.FenceError):
                with self.runner.scope(bound, entry):
                    self.fail('drained grant')
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(bound, entry):
                    self.fail('retry after drain')
        self.admitted(callback)
        self.assertEqual(self.effects, [])

    def test_read_strips_inherited_and_supplied_authority(self):
        called = mock.Mock(return_value={'ok': True})
        runner = d.DelegatingRunner(store=self.store, runner=called, root=self.root)
        with mock.patch.dict(os.environ, {f.TOKEN_ENV: 'e' * 64}):
            runner(['/cli', '--json', 'plug-list'], env={f.TOKEN_ENV: 'f' * 64, 'OTHER': 'retained'})
        self.assertEqual(called.call_args.kwargs['env'], {f.TOKEN_ENV: '', 'OTHER': 'retained'})

    def test_no_scope_no_write_and_transport_failure_no_second_child(self):
        with self.assertRaises(d.DelegationError):
            self.runner(['/cli', '--json', 'plug-on', 'lamp'])
        called = mock.Mock(side_effect=TimeoutError())
        runner = d.DelegatingRunner(store=self.store, runner=called, root=self.root)
        def callback(bound, entry, intent):
            with runner.scope(bound, entry):
                with self.assertRaises(TimeoutError):
                    runner(['/cli', '--json', 'plug-on', 'lamp'])
                with self.assertRaises(d.DelegationError):
                    runner(['/cli', '--json', 'plug-on', 'lamp'])
        self.admitted(callback)
        self.assertEqual(called.call_count, 1)

    def test_worker_direct_call_and_mismatched_operation_never_reach_adapter(self):
        args = self.args(['/cli', '--json', 'plug-on', 'lamp', '--expected-host', '192.0.2.1'])
        adapter = mock.Mock()
        with mock.patch.dict(os.environ, {f.TOKEN_ENV: ''}):
            code, _ = w.execute(args, adapter=adapter, emit=mock.Mock())
        self.assertEqual(code, 1); self.assertEqual(adapter.mock_calls, [])
        def callback(bound, entry, intent):
            with self.runner.scope(bound, entry):
                token = self.runner._local.frame['token']
                args.command = 'plug-off'
                with mock.patch.dict(os.environ, {f.TOKEN_ENV: token}):
                    code, _ = w.execute(args, adapter=adapter, emit=mock.Mock())
                self.assertEqual(code, 1); self.assertEqual(adapter.mock_calls, [])
        self.admitted(callback)

    def test_unspent_token_cannot_outlive_callback_or_restart(self):
        token = []
        def callback(bound, entry, intent):
            with self.runner.scope(bound, entry):
                token.append(self.runner._local.frame['token'])
        bound = self.admitted(callback)
        call = d.call_for(bound, self.host._entry(bound.command))
        for restart in (False, True):
            if restart:
                self.store.close()
                self.store = g.ControlLedger.open(self.fixture.path)
                self.fixture.store = self.store
            with mock.patch.dict(os.environ, {f.TOKEN_ENV: token[0]}), self.assertRaises(f.FenceError):
                with f.permission(call):
                    self.fail('expired callback')

    def test_setting_translation_matches_actual_worker_parser(self):
        from jarvisd_core import commands
        settings = [{'setting': 'power', 'value': x} for x in ('on', 'off', 'toggle')]
        settings += [{'setting': key, 'value': value} for key in ('display', 'child-lock', 'light-detection') for value in ('on', 'off')]
        settings += [{'setting': 'mode', 'value': x} for x in commands.PURIFIER_MODES]
        settings += [{'setting': 'speed', 'level': x} for x in range(1, 5)]
        settings += [{'setting': 'auto-preference', 'value': x, **size} for x in commands.PURIFIER_AUTO_PREFERENCES for size in ({}, {'roomSize': 123})]
        settings += [{'setting': 'timer', 'minutes': 1}, {'setting': 'timer', 'minutes': 1440}, {'setting': 'timer', 'value': 'clear'}]
        for setting in settings:
            with self.subTest(setting=setting):
                params = {'deviceID': DEVICE, **setting}
                bound = self.host.prepare(v._command('purifier-set', params), ACCESS)
                argv = commands.build_command('purifier-set', params, cli=Path('/cli'), selected_purifier=lambda _: CID)
                argv += ['--expected-cid', CID]
                self.assertEqual(d.call_for(bound, self.host._entry(bound.command)), d.worker_call(self.args(argv)))

    def test_revoked_authorization_does_not_publish_or_dispatch(self):
        bound = self.host.prepare(v._command('plug-on', {'plug': 'lamp'}), ACCESS)
        self.fixture.allow = False
        with self.assertRaises(fixtures.HostError):
            self.host.execute(bound)
        self.assertEqual(list((self.root / 'grants').iterdir()), [])
        self.assertEqual(self.calls, [])

    def test_host_refuses_unpaired_delegation_and_runner(self):
        with self.assertRaises(fixtures.HostError):
            self.fixture.make_host(runner=self.fixture.runner, delegation=self.runner)

    def test_expired_window_cannot_be_renewed_by_issuing_a_grant(self):
        def callback(bound, entry, intent):
            expires = self.store._windows[intent.window][1]
            self.store._mono, self.store._wall = lambda: expires[0], lambda: expires[1]
            with self.assertRaises(g.LedgerError):
                with self.runner.scope(bound, entry):
                    self.fail('expired window')
        self.admitted(callback)
        self.assertEqual(list((self.root / 'grants').iterdir()), [])

    def test_forked_callback_cannot_claim_before_inherited_mutex(self):
        def callback(bound, entry, intent):
            read, write = os.pipe()
            self.store._mutex.acquire()
            child = os.fork()
            if child == 0:
                os.close(read)
                try:
                    self.store.claim_delegation(cohort=C, resource=bound.resource,
                        command=bound.fingerprint, action=bound.command.action, directory=self.fixture.path)
                except g.LedgerError as error:
                    os.write(write, error.code.encode())
                    os._exit(0)
                os._exit(2)
            os.close(write)
            self.store._mutex.release()
            try:
                import select
                self.assertTrue(select.select([read], [], [], 3)[0], 'child blocked on inherited mutex')
                self.assertEqual(os.read(read, 100), b'forked-store')
            finally:
                os.close(read)
                os.kill(child, 9) if os.waitpid(child, os.WNOHANG)[0] == 0 else None
                try:
                    os.waitpid(child, 0)
                except ChildProcessError:
                    pass
        self.admitted(callback)

    def test_actual_worker_entry_rejects_direct_write_but_keeps_local_status(self):
        entry = Path(w.__file__).parent.parent / 'control-worker.py'
        prefix = [sys.executable, '-B', str(entry), '--operation-root', str(self.root),
                  '--project-root', str(self.root), '--json']
        env = {'JARVIS_EMIT_EVENTS': '0', f.TOKEN_ENV: ''}
        result = subprocess.run([*prefix, 'plug-on', 'lamp', '--expected-host', '192.0.2.1'],
            env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertNotIn('192.0.2.1', result.stdout + result.stderr)
        result = subprocess.run([*prefix, 'status', '--no-cast'], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['ok'])

    def test_different_ledger_directory_cannot_borrow_store_authority(self):
        other = self.root / 'other'; other.mkdir(mode=0o700)
        g.ControlLedger.initialize(other / 'ledger'); (other / 'grants').mkdir(mode=0o700)
        runner = d.DelegatingRunner(store=self.store, runner=self.worker, root=other)
        def callback(bound, entry, intent):
            with self.assertRaises(g.LedgerError):
                with runner.scope(bound, entry):
                    self.fail('foreign ledger')
        self.admitted(callback)
        self.assertEqual(list((other / 'grants').iterdir()), [])
