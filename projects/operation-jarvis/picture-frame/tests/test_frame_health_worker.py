"""Offline proof that the daemon worker reads only a pinned identity/package."""
import contextlib
import copy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import health_worker
from frame_control import AdbError, Controller, FrameError, save_json
from frame_tcp import LegacyLanAdb

IDENTITY = {'hardware_serial': 'FRAME_HEALTH_TEST', 'manufacturer': 'Test',
            'model': 'Test frame', 'build_fingerprint': 'test-build'}
PACKAGE = 'net.frameo.frame'
TARGET = '192.168.1.99:5555'


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.config = self.root / 'config.json'
        self.lock = self.root / 'controller.lock'
        self.lock.touch(mode=0o600)
        self.value = {'schema_version': 1, 'serial': TARGET, 'usb_serial': 'FRAME_HEALTH_TEST',
            'package': PACKAGE, 'identity': copy.deepcopy(IDENTITY), 'adb_backend': 'legacy_lan',
            'legacy_lan_approval': {'schema_version': 1,
                'policy': 'owner_accepted_unauthenticated_lan_adb', 'accepted': True,
                'serial': TARGET, 'package': PACKAGE, 'identity': copy.deepcopy(IDENTITY),
                'accepted_at_utc': datetime.now(timezone.utc).isoformat()}}
        save_json(self.config, self.value)
        self.calls = []
        self.actual = copy.deepcopy(IDENTITY)
        self.error = None
        case = self
        class Transport:
            def __init__(self, dependencies, approval):
                case.calls.append(('construct', str(dependencies), approval))
            def probe(self, serial, package):
                case.calls.append(('probe', serial, package))
                if case.error: raise case.error
                return {'identity': case.actual}
            def close(self): case.calls.append(('close',))
            def call(self, *args, **kwargs): raise AssertionError('No other ADB command allowed')
        self.transport = Transport

    def check(self):
        with patch('frame_tcp.LegacyLanAdb', self.transport), \
             patch.object(Controller, 'status', side_effect=AssertionError), \
             patch.object(Controller, 'control', side_effect=AssertionError), \
             patch.object(Controller, 'upload', side_effect=AssertionError), \
             patch.object(Controller, 'screenshot', side_effect=AssertionError), \
             patch.object(Controller, '_begin', side_effect=AssertionError), \
             patch.object(Controller, '_finish', side_effect=AssertionError):
            return health_worker.check_frame(self.config)

    def test_dry_run_no_import_config_photo_key_dependency_or_state(self):
        original_import = __import__
        def guard(name, *args, **kwargs):
            if name in ('frame_control', 'frame_tcp') or name.startswith(('adb_shell', 'cryptography')):
                raise AssertionError('Dry-run must not import transport/controller dependencies')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guard), \
             patch('builtins.open', side_effect=AssertionError), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError), \
             patch.object(Path, 'mkdir', side_effect=AssertionError):
            result = health_worker.main([])
        self.assertEqual(result['status'], 'dry_run')
        self.assertFalse(result['device_contacted'])
        self.assertFalse(result['runtime_read'])

    def test_only_identity_package_read_and_no_private_output(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(self.check(), {'ok': True, 'reason': None})
        self.assertEqual([c[0] for c in self.calls], ['construct', 'probe', 'close'])
        self.assertEqual(self.calls[1], ('probe', TARGET, PACKAGE))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_existing_pending_write_is_not_read_cleared_or_replayed(self):
        pending = self.root / 'pending.json'
        pending.write_text('{"operation":"unknown"}')
        pending.chmod(0o600)
        before = pending.read_bytes()
        self.assertEqual(self.check()['ok'], True)
        self.assertEqual(pending.read_bytes(), before)

    def test_identity_mismatch_never_reports_up(self):
        self.actual['hardware_serial'] = 'other'
        self.assertEqual(self.check(), {'ok': None, 'reason': 'identity_unverified'})
        self.assertEqual(self.calls[-1], ('close',))

    def test_transport_failure_unreachable_sanitized_closed_and_not_retried(self):
        self.error = AdbError('private endpoint')
        self.assertEqual(self.check(), {'ok': False, 'reason': 'read_failed'})
        self.assertEqual([c[0] for c in self.calls], ['construct', 'probe', 'close'])

    def test_policy_failure_unknown(self):
        self.error = FrameError('private identity or dependency')
        self.assertEqual(self.check(), {'ok': None, 'reason': 'identity_unverified'})
        self.assertEqual(self.calls[-1], ('close',))

    def test_invalid_consent_and_unsupported_transport_stop_before_network(self):
        for change in ({'legacy_lan_approval': {}}, {'adb_backend': 'direct_tcp'},
                       {'adb_backend': 'platform_tools', 'serial': 'FRAME_USB_TEST'}):
            value = {**self.value, **change}; save_json(self.config, value)
            self.assertIsNone(self.check()['ok'])
            self.assertEqual(self.calls, [])

    def test_missing_shared_or_symlink_state_never_creates_or_repairs_it(self):
        self.lock.unlink()
        self.assertIsNone(self.check()['ok'])
        self.assertFalse(self.lock.exists())
        self.lock.touch(mode=0o600)
        self.config.chmod(0o644)
        self.assertIsNone(self.check()['ok'])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o644)
        self.config.chmod(0o600)
        target = self.root / 'other.json'; self.config.rename(target); self.config.symlink_to(target)
        self.assertIsNone(self.check()['ok'])
        self.assertEqual(self.calls, [])

    def test_busy_is_unknown_without_network_or_quarantine_changes(self):
        with self.lock.open('r') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.check(), {'ok': None, 'reason': 'device_busy'})
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['config.json', 'controller.lock'])

    def test_unexpected_error_is_sanitized_and_closes_transport(self):
        self.error = RuntimeError('private path')
        self.assertEqual(self.check(), {'ok': None, 'reason': 'check_failed'})
        self.assertEqual(self.calls[-1], ('close',))

    def test_cli_rejects_transport_paths_shell_or_controls(self):
        for args in (['--config', '/private/config'], ['--apply'], ['--serial', TARGET],
                     ['--command', 'input tap 1 2']):
            with self.subTest(args=args), contextlib.redirect_stderr(__import__('io').StringIO()):
                with self.assertRaises(SystemExit): health_worker.main(args)


if __name__ == '__main__':
    unittest.main()
