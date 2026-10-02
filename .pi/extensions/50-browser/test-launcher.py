#!/usr/bin/env python3
"""Unit tests only: subprocess.run is mocked; Chrome is never opened."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
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

    def test_publishes_complete_generation_atomically_with_private_permissions(self):
        replace = launcher.os.replace
        snapshots = []

        def publish(source, target):
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
        output = io.StringIO()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=URL)), contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(json.loads(self.identity.read_text())['connectionTabId'], 72)

    def test_untrusted_url_never_reaches_applescript(self):
        with patch.object(launcher.sys, 'argv', ['launcher', 'https://example.com']), patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.main(), 2)
            run.assert_not_called()

    def test_invalid_recorded_window_requests_new_window_instead_of_adopting_another(self):
        self.identity.write_text('{"windowId":"71"}')
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='90,91,99,com.example.editor')) as run:
            self.assertEqual(launcher.main(), 0)
        self.assertEqual(run.call_args.args[0][-1], '0')


if __name__ == '__main__':
    unittest.main()
