import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import watch_control as control


class Launchd:
    def __init__(self):
        self.loaded = True
        self.is_disabled = False
        self.calls = []
        self.fail = None
        self.identity = str(control.ROOT / 'watch.py')
        self.legacy_flags = False

    def run(self, argv, **_kwargs):
        args = argv[1:]
        self.calls.append(args)
        action = args[0]
        if action == self.fail:
            return subprocess.CompletedProcess(argv, 1, '', 'private diagnostic')
        output = ''
        if action == 'print':
            if not self.loaded:
                return subprocess.CompletedProcess(argv, 113, '', 'Could not find service')
            output = f'arguments = {{ {self.identity} --watch }}\n\tpid = 4123\n'
        elif action == 'print-disabled':
            flag = ('true' if self.is_disabled else 'false') if self.legacy_flags else (
                'disabled' if self.is_disabled else 'enabled')
            output = f'"{control.LABEL}" => {flag}\n'
        elif action == 'enable':
            self.is_disabled = False
        elif action == 'disable':
            self.is_disabled = True
        elif action == 'bootstrap':
            self.loaded = True
        elif action == 'bootout':
            self.loaded = False
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(argv, 0, output, '')


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.plist = root / 'watch.plist'
        self.plist.write_bytes(plistlib.dumps({
            'Label': control.LABEL,
            'ProgramArguments': [sys.executable, str(control.ROOT / 'watch.py'), '--watch'],
        }))
        self.runtime = root / 'runtime'
        self.launchd = Launchd()
        patches = [patch.object(control.sys, 'platform', 'darwin'),
                   patch.object(control, 'PLIST', self.plist),
                   patch.object(control.cycle, 'RUNTIME', self.runtime),
                   patch.object(control.subprocess, 'run', side_effect=self.launchd.run),
                   patch.object(control, 'alive', side_effect=lambda pid: self.launchd.loaded)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def actions(self):
        return [call[0] for call in self.launchd.calls]

    def test_disable_unloads_and_persistently_disables(self):
        self.assertEqual(control.control(False), 'stopped')
        self.assertFalse(self.launchd.loaded)
        self.assertTrue(self.launchd.is_disabled)
        self.assertLess(self.actions().index('disable'), self.actions().index('bootout'))
        self.assertEqual(self.actions().count('bootout'), 1)

    def test_repeated_disable_is_safe_without_bootout_replay(self):
        control.control(False)
        control.control(False)
        self.assertEqual(self.actions().count('bootout'), 1)
        self.assertNotIn('bootstrap', self.actions())

    def test_enable_uses_existing_plist_and_starts_once(self):
        self.launchd.loaded = False
        self.launchd.is_disabled = True
        self.assertEqual(control.control(True), 'running')
        bootstrap = next(c for c in self.launchd.calls if c[0] == 'bootstrap')
        self.assertEqual(bootstrap[-1], str(self.plist))
        control.control(True)
        self.assertEqual(self.actions().count('bootstrap'), 1)
        self.assertNotIn('kickstart', self.actions())

    def test_legacy_boolean_disable_flags(self):
        self.launchd.legacy_flags = True
        self.assertEqual(control.control(False), 'stopped')

    def test_unknown_status_does_not_change_lifecycle(self):
        self.launchd.fail = 'print'
        with self.assertRaises(control.ControlError):
            control.control(False)
        self.assertEqual(self.actions(), ['print'])

    def test_wrong_loaded_identity_is_never_unloaded(self):
        self.launchd.identity = '/unrelated/other.py'
        with self.assertRaisesRegex(control.ControlError, 'identity mismatch'):
            control.control(False)
        self.assertEqual(self.actions(), ['print'])

    def test_wrong_plist_is_not_replaced_or_executed(self):
        before = plistlib.dumps({'Label': 'unrelated', 'ProgramArguments': []})
        self.plist.write_bytes(before)
        with self.assertRaisesRegex(control.ControlError, 'identity mismatch'):
            control.control(True)
        self.assertEqual(self.plist.read_bytes(), before)
        self.assertEqual(self.actions(), [])

    def test_failed_stop_is_not_retried_or_claimed(self):
        self.launchd.fail = 'bootout'
        with self.assertRaises(control.ControlError):
            control.control(False)
        self.assertEqual(self.actions().count('bootout'), 1)
        self.assertTrue(self.launchd.loaded)
        self.assertTrue(self.launchd.is_disabled)

    def test_failed_start_is_not_retried(self):
        self.launchd.loaded = False
        self.launchd.fail = 'bootstrap'
        with self.assertRaises(control.ControlError):
            control.control(True)
        self.assertEqual(self.actions().count('bootstrap'), 1)

    def test_process_must_exit_before_stop_success(self):
        with patch.object(control, 'alive', return_value=True), patch.object(
                control.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(control.ControlError, 'has not exited'):
                control.control(False)
        self.assertEqual(self.actions().count('bootout'), 1)

    def test_uncertainty_state_is_never_cleared(self):
        store = control.cycle.Store(self.runtime)
        store.save('display-state.json', {'pending': True, 'fault': True})
        before = (self.runtime / 'display-state.json').read_bytes()
        control.control(False)
        control.control(True)
        self.assertEqual((self.runtime / 'display-state.json').read_bytes(), before)

    def test_non_macos_host_refuses(self):
        with patch.object(control.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(control.ControlError, 'macOS'):
                control.control(False)
        self.assertEqual(self.actions(), [])
