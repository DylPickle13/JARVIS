"""Checkpoint prototype tests. Temporary ledger/grants, no SDK/device access.

The fixture mints synthetic grant files INSIDE a real ledger callback. This is
not a production grant issuer, handoff owner, or evidence of installed fencing.
"""
import concurrent.futures
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_control_ledger import handoff, intent_for, ready, RESOURCE
from jarvisd_core import client_policy as p, control_ledger as g, vendor_fence as f


class FenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'owner'
        self.root.mkdir(mode=0o700)
        self.grants = self.root / 'grants'
        self.grants.mkdir(mode=0o700)
        self.ledger = self.root / 'ledger'
        g.ControlLedger.initialize(self.ledger)
        self.store = g.ControlLedger.open(self.ledger)
        self.addCleanup(lambda: self.store.close())
        handoff(self.store)
        self.token = 'e' * 64
        self.call = {'cohort': 'plugs', 'target': '192.0.2.10', 'action': 'plug-on', 'on': True}
        self.effects = []
        self.patch = mock.patch.object(f, 'root_directory', return_value=self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        env = mock.patch.dict(os.environ, {f.TOKEN_ENV: self.token})
        env.start(); self.addCleanup(env.stop)

    def mint(self, changes=None):
        # Deliberately test-only: a production issuer must obtain a one-use grant
        # from the still-active callback, rather than mint from a disk snapshot.
        record = json.loads((self.ledger / 'record.json').read_bytes())
        row = record['records'][-1]
        grant = {k: v for k, v in row.items() if k not in ('outcome', 'unresolved')}
        grant.update(schema=1, token=self.token, monotonic=time.monotonic_ns(), wall=time.time_ns(), call=self.call)
        grant.update(changes or {})
        with f.directory(self.grants) as directory:
            fd = f.write_new(directory, self.token + '.json', grant)
            os.close(fd)
        return grant

    def invoke(self, *, call=None, phase='mutation', desired=None):
        with f.permission(self.call if call is None else call, phase=phase, desired=desired):
            self.effects.append(phase)

    def execute(self, callback):
        intent = intent_for(self.store)
        def operation():
            callback()
            return g.DispatchResult(p.Outcome.ACKNOWLEDGED if self.effects else p.Outcome.UNKNOWN)
        return self.store.execute_once(intent, lambda: ready(intent), operation)

    def test_valid_reserved_grant_consumes_once_and_preserves_uncertainty(self):
        def action():
            grant = self.mint()
            self.invoke(desired={'isOn': True})
            with self.assertRaises(f.FenceError):
                self.invoke()
            used = json.loads((self.grants / (self.token + '.mutation')).read_bytes())
            self.assertEqual(used['grant'], f.fingerprint(grant))
            self.assertEqual(used['desired'], {'isOn': True})
        self.execute(action)
        self.assertEqual(self.effects, ['mutation'])
        self.assertEqual(self.store.pending_resources(p.Cohort.PLUGS), {RESOURCE})

    def test_worker_and_sdk_checkpoints_are_independently_one_use(self):
        def action():
            self.mint()
            with f.permission(self.call, phase='worker'):
                self.invoke()
                with self.assertRaises(f.FenceError):
                    self.invoke(phase='worker')
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, ['mutation'])

    def test_concurrent_consumers_have_one_winner(self):
        def action():
            self.mint()
            def attempt(_):
                try:
                    self.invoke()
                    return True
                except f.FenceError:
                    return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(attempt, range(24))), 1)
        self.execute(action)
        self.assertEqual(self.effects, ['mutation'])

    def child(self, *, crash=False):
        script = '''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from jarvisd_core import vendor_fence as f
f.root_directory = lambda: Path(sys.argv[2])  # Test fixture only, no production switch.
try:
    with f.permission(json.loads(sys.argv[3])):
        if sys.argv[4] == 'crash':
            os._exit(9)
except f.FenceError:
    sys.exit(42)
'''
        return subprocess.run([sys.executable, '-B', '-c', script, str(Path(f.__file__).parent.parent),
            str(self.root), json.dumps(self.call), 'crash' if crash else 'normal'],
            env={f.TOKEN_ENV: self.token}, capture_output=True, timeout=10).returncode

    def test_separate_processes_cannot_reuse_the_same_grant(self):
        def action():
            self.mint()
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda _: self.child(), range(6)))
            self.assertEqual(sorted(results), [0, 42, 42, 42, 42, 42])
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)

    def test_process_death_releases_lease_but_does_not_refund(self):
        def action():
            self.mint()
            self.assertEqual(self.child(crash=True), 9)
            with self.assertRaises(f.FenceError):
                self.invoke()
            fd = os.open(self.grants / (self.token + '.mutation'), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        self.execute(action)
        self.assertEqual(self.store.pending_resources(p.Cohort.PLUGS), {RESOURCE})

    def test_used_marker_holds_kernel_lease_until_guard_exits(self):
        def action():
            self.mint()
            with f.permission(self.call):
                fd = os.open(self.grants / (self.token + '.mutation'), os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)
            fd = os.open(self.grants / (self.token + '.mutation'), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        self.execute(action)

    def test_cancellation_and_sdk_exception_never_refund_or_reclassify(self):
        def action():
            self.mint()
            error = KeyboardInterrupt('synthetic cancellation')
            with self.assertRaises(KeyboardInterrupt) as caught:
                with f.permission(self.call):
                    raise error
            self.assertIs(caught.exception, error)
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_sdk_value_error_is_not_relabelled_as_prewrite_rejection(self):
        def action():
            self.mint()
            error = ValueError('synthetic SDK failure after submission')
            with self.assertRaises(ValueError) as caught:
                with f.permission(self.call):
                    raise error
            self.assertIs(caught.exception, error)
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)

    def test_missing_store_token_or_grant_never_falls_back_or_creates_state(self):
        for token in ('', '../escape', 'A' * 64, 'f' * 64):
            with mock.patch.dict(os.environ, {f.TOKEN_ENV: token}), self.assertRaises(f.FenceError):
                self.invoke()
        absent = self.root / 'absent'
        with mock.patch.object(f, 'root_directory', return_value=absent), self.assertRaises(f.FenceError):
            self.invoke()
        self.assertFalse(absent.exists())
        self.assertEqual(list(self.grants.iterdir()), [])
        self.assertEqual(self.effects, [])

    def test_exact_target_action_payload_and_types_are_bound(self):
        def action():
            self.mint()
            for change in ({'target': '192.0.2.11'}, {'action': 'plug-off'}, {'on': 1},
                           {'on': False}, {'extra': True}, {'cohort': 'purifier'}):
                with self.subTest(change=change), self.assertRaises(f.FenceError):
                    self.invoke(call={**self.call, **change})
            self.assertFalse((self.grants / (self.token + '.mutation')).exists())
            self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, ['mutation'])

    def test_grant_cannot_outlive_callback_even_without_consumption(self):
        self.execute(self.mint)
        with self.assertRaises(f.FenceError):
            self.invoke()
        self.assertEqual(self.effects, [])

    def test_restart_and_new_epoch_do_not_revive_unused_grant(self):
        self.execute(self.mint)
        self.store.close()
        self.store = g.ControlLedger.open(self.ledger)
        handoff(self.store)
        with self.assertRaises(f.FenceError):
            self.invoke()
        self.assertEqual(self.store.pending_resources(p.Cohort.PLUGS), {RESOURCE})

    def test_owner_lock_must_be_held_not_merely_present(self):
        def action():
            self.mint()
            fcntl.flock(self.store._lfd, fcntl.LOCK_UN)  # Test-only owner-death simulation.
            try:
                with self.assertRaises(f.FenceError):
                    self.invoke()
            finally:
                fcntl.flock(self.store._lfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_drain_closes_grant_before_effect(self):
        def action():
            self.mint()
            self.store.transition(p.Cohort.PLUGS, p.Mode.DRAINING)
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_closure_between_consumption_and_final_check_never_refunds(self):
        def action():
            self.mint()
            original = f.write_new
            def close(*args):
                fd = original(*args)
                self.store.transition(p.Cohort.PLUGS, p.Mode.DRAINING)
                return fd
            with mock.patch.object(f, 'write_new', side_effect=close), self.assertRaises(f.FenceError):
                self.invoke()
            self.assertTrue((self.grants / (self.token + '.mutation')).exists())
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_expiry_future_time_and_clock_skew_fail_closed(self):
        def action():
            grant = self.mint()
            for mono, wall in ((f.TTL_NS, f.TTL_NS), (-1, 0), (0, -1), (0, f.SKEW_NS + 1)):
                with self.subTest(mono=mono, wall=wall), \
                        mock.patch.object(f.time, 'monotonic_ns', return_value=grant['monotonic'] + mono), \
                        mock.patch.object(f.time, 'time_ns', return_value=grant['wall'] + wall), \
                        self.assertRaises(f.FenceError):
                    self.invoke()
            self.assertFalse((self.grants / (self.token + '.mutation')).exists())
        self.execute(action)

    def test_file_sync_failure_keeps_consumed_name_without_effect(self):
        def action():
            self.mint()
            with mock.patch.object(f, 'sync', side_effect=OSError('synthetic')), self.assertRaises(f.FenceError):
                self.invoke()
            self.assertTrue((self.grants / (self.token + '.mutation')).exists())
            with self.assertRaises(f.FenceError):
                self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_private_modes_links_duplicate_keys_and_oversize_are_rejected(self):
        def action():
            self.mint()
            path = self.grants / (self.token + '.json')
            original = path.read_bytes()
            path.chmod(0o644)
            with self.assertRaises(f.FenceError):
                self.invoke()
            path.chmod(0o600)
            link = self.grants / 'extra-link'
            os.link(path, link)
            with self.assertRaises(f.FenceError):
                self.invoke()
            link.unlink()
            for raw in (b'{"schema":1,"schema":1}', b'{' + b' ' * f.MAX_GRANT + b'}', b'{}', b'{"x":NaN}'):
                path.write_bytes(raw)
                with self.assertRaises(f.FenceError):
                    self.invoke()
            path.write_bytes(original)
            path.rename(link)
            path.symlink_to(link)
            with self.assertRaises(f.FenceError):
                self.invoke()
            path.unlink(); link.rename(path)
            self.invoke()
        self.execute(action)
        self.assertEqual(self.effects, ['mutation'])

    def test_record_corruption_never_becomes_authority(self):
        def action():
            self.mint()
            path = self.ledger / 'record.json'
            original = path.read_bytes()
            record = json.loads(original)
            changes = [lambda r: r.update(revision=True), lambda r: r['records'].append(copy.deepcopy(r['records'][0])),
                lambda r: r['cohorts']['purifier'].update(extra=True),
                lambda r: r['records'][0].update(epoch=True), lambda r: r['records'][0].update(unresolved=1),
                lambda r: r['records'][0].update(action='purifier-set'),
                lambda r: r['records'][0].update(extra=True), lambda r: r['records'][0].update(client='f' * 64)]
            try:
                for change in changes:
                    changed = copy.deepcopy(record); change(changed)
                    path.write_bytes(f.encode(changed))
                    with self.assertRaises(f.FenceError):
                        self.invoke()
            finally:
                path.write_bytes(original)  # Temporary fixture only; NEVER a runtime rollback technique.
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_parent_directory_replacement_is_detected_after_consumption(self):
        def action():
            self.mint()
            original = f.write_new
            moved = self.root / 'old-grants'
            def replace(*args):
                fd = original(*args)
                self.grants.rename(moved)
                self.grants.mkdir(mode=0o700)
                return fd
            with mock.patch.object(f, 'write_new', side_effect=replace), self.assertRaises(f.FenceError):
                self.invoke()
            self.assertTrue((moved / (self.token + '.mutation')).exists())
        self.execute(action)
        self.assertEqual(self.effects, [])

    def test_import_is_pure_and_catalogue_mutation_has_no_bypass(self):
        spec = importlib.util.spec_from_file_location('_isolated_fence', f.__file__)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(os, 'open', side_effect=AssertionError('import file IO')), \
                mock.patch.object(socket, 'socket', side_effect=AssertionError('import network')):
            spec.loader.exec_module(module)
        with self.assertRaises(module.FenceError):
            module.reject_catalogue_change()
        with mock.patch.dict(os.environ, {'HOME': '/not-an-owner', 'JARVIS_CONTROL_ROOT': '/not-an-owner'}):
            self.assertNotIn('/not-an-owner', str(module.root_directory()))


if __name__ == '__main__':
    unittest.main()
