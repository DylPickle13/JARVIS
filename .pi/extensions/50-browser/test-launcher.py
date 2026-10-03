#!/usr/bin/env python3
"""Unit tests only: subprocess.run is mocked; Chrome is never opened."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).with_name('launch-extension-in-automation-window.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
URL = 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html?token=unit-test-token'


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        (self.home/'.jarvis').mkdir()
        self.identity = self.home/'.jarvis/extension-window.json'
        self.identity.write_text(json.dumps({'windowId': 71, 'connectionTabId': 72}))
        self.home_patch = patch.object(Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.args_patch = patch.object(launcher.sys, 'argv', ['launcher', URL])
        self.args_patch.start()
        self.addCleanup(self.args_patch.stop)

    def allow_once(self, **overrides):
        now = time.time()
        ticket = {'windowId': 71, 'issuedAt': now, 'expiresAt': now + 60, **overrides}
        path = self.home / '.jarvis' / launcher.ALLOWANCE
        path.write_text(json.dumps(ticket))
        path.chmod(0o600)
        return path

    def test_publishes_complete_generation_atomically_with_private_permissions(self):
        self.allow_once()
        replace = launcher.os.replace
        snapshots = []

        def publish(source, target):
            if target == self.identity:
                snapshots.append(json.loads(self.identity.read_text()))
            self.assertEqual(Path(source).stat().st_mode & 0o777, 0o600)
            replace(source, target)

        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='71,83,99,com.example.editor\n')) as run, patch.object(launcher.os, 'replace', side_effect=publish):
            self.assertEqual(launcher.main(), 0)
        args = run.call_args.args[0]
        self.assertEqual(args[-1], '71', 'reuse only the recorded window, not a title/URL search')
        self.assertTrue(args[-2].endswith('#jarvis-automation-anchor-v2'))
        self.assertEqual(snapshots, [{'windowId': 71, 'connectionTabId': 72}])
        self.assertEqual(json.loads(self.identity.read_text())['connectionTabId'], 83)
        self.assertEqual(list((self.home/'.jarvis').glob('extension-window-*')), [])

    def test_launcher_error_keeps_previous_identity_and_does_not_print_tokens(self):
        self.allow_once()
        output = io.StringIO()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=URL)), contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(json.loads(self.identity.read_text())['connectionTabId'], 72)

    def test_untrusted_url_never_reaches_applescript(self):
        with patch.object(launcher.sys, 'argv', ['launcher', 'https://example.com']), patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.main(), 2)
            run.assert_not_called()

    def test_default_blocks_before_any_chrome_or_foreground_access(self):
        output = io.StringIO()
        with patch.object(launcher.subprocess, 'run') as run, contextlib.redirect_stderr(output):
            self.assertEqual(launcher.main(), launcher.BLOCKED)
            run.assert_not_called()
        self.assertIn('Background-only policy', output.getvalue())
        self.assertNotIn(URL, output.getvalue())
        self.assertEqual(json.loads(self.identity.read_text())['connectionTabId'], 72)

    def test_invalid_recorded_window_never_creates_or_adopts_a_window(self):
        for identity in ('{"windowId":"71"}', '{"windowId":true}', '{"windowId":0}', '{}', 'null', 'broken'):
            self.identity.write_text(identity)
            self.allow_once()
            with patch.object(launcher.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(launcher.main(), launcher.BLOCKED)
                run.assert_not_called()
        self.assertNotIn('make new window', launcher.SCRIPT)
        self.assertIn('manual placement required', launcher.SCRIPT)

    def test_expired_future_wrong_window_and_malformed_allowances_are_denied(self):
        now = time.time()
        for overrides in ({'expiresAt': now - 1}, {'issuedAt': now + 10}, {'expiresAt': now + 120}, {'windowId': 99}, {'windowId': True}, {'expiresAt': 'tomorrow'}, {'issuedAt': None}):
            path = self.allow_once(**overrides)
            self.assertFalse(launcher.consume_allowance(path.parent, 71))
            self.assertFalse(path.exists())
        for content in ('null', '[]', 'broken'):
            path = self.allow_once()
            path.write_text(content)
            self.assertFalse(launcher.consume_allowance(path.parent, 71))

    def test_allowance_is_one_use_even_after_launcher_failure(self):
        path = self.allow_once()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main(), 1)
            self.assertEqual(launcher.main(), launcher.BLOCKED)
            self.assertEqual(run.call_count, 1)
        self.assertFalse(path.exists())

    def test_timeout_does_not_leak_url_or_allow_replay(self):
        self.allow_once()
        output = io.StringIO()
        error = launcher.subprocess.TimeoutExpired(['osascript', URL], 30)
        with patch.object(launcher.subprocess, 'run', side_effect=error) as run, contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            self.assertEqual(launcher.main(), 1)
            self.assertEqual(launcher.main(), launcher.BLOCKED)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn(URL, output.getvalue())
        self.assertEqual(json.loads(self.identity.read_text())['connectionTabId'], 72)

    def test_unexpected_window_result_never_replaces_recorded_identity(self):
        self.allow_once()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='99,83,99,com.example.editor')):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(json.loads(self.identity.read_text())['windowId'], 71)

    def test_insecure_or_symlink_allowance_is_denied(self):
        path = self.allow_once()
        path.chmod(0o644)
        self.assertFalse(launcher.consume_allowance(path.parent, 71))
        target = self.home / 'untrusted-ticket'
        target.write_text('{}')
        path.symlink_to(target)
        self.assertFalse(launcher.consume_allowance(path.parent, 71))
        self.assertTrue(target.exists())

    def test_explicit_supervised_authorization_is_short_lived_and_private(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.authorize_once(['--allow-once', '--window-id', '71', '--acknowledge-focus-change']), 0)
        path = self.home / '.jarvis' / launcher.ALLOWANCE
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(launcher.consume_allowance(path.parent, 71))
        self.assertFalse(launcher.consume_allowance(path.parent, 71))

    def test_authorization_requires_acknowledgment_and_matching_identity(self):
        for args in (['--allow-once', '--window-id', '71'], ['--allow-once', '--window-id', '99', '--acknowledge-focus-change']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                launcher.authorize_once(args)
        self.assertFalse((self.home / '.jarvis' / launcher.ALLOWANCE).exists())


if __name__ == '__main__':
    unittest.main()
