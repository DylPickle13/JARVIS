"""Scoped display binary selection; no hosted agents or production sockets."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import backend
import core
import desktop
import install
import tmux_runtime


class ScopedTmuxTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patch = mock.patch.object(tmux_runtime, 'ROOT', str(self.root))
        patch.start()
        self.addCleanup(patch.stop)
        self.binary = self.root / 'bin/tmux'

    def create_binary(self):
        self.binary.parent.mkdir()
        self.binary.write_text('#!/bin/sh\nexit 0\n')
        self.binary.chmod(0o700)

    def test_unbundled_platform_keeps_system_tmux_and_socket(self):
        self.assertEqual(tmux_runtime.command('private-test'), ['tmux', '-L', 'private-test'])

    def test_bundle_is_absolute_and_does_not_modify_path(self):
        self.create_binary()
        path = os.environ.get('PATH')
        self.assertEqual(tmux_runtime.command('private-test'),
                         [str(self.binary), '-L', 'private-test'])
        self.assertEqual(os.environ.get('PATH'), path)

    def test_bad_bundle_fails_instead_of_silently_using_old_tmux(self):
        self.create_binary()
        self.binary.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'regular executable'):
            tmux_runtime.executable()

    def test_bundle_directory_is_rejected(self):
        self.binary.mkdir(parents=True)
        with self.assertRaises(RuntimeError):
            tmux_runtime.executable()

    def test_symlink_and_broken_symlink_are_rejected(self):
        self.binary.parent.mkdir()
        for target in ('/usr/bin/true', str(self.root / 'missing')):
            with self.subTest(target=target):
                self.binary.symlink_to(target)
                with self.assertRaises(RuntimeError):
                    tmux_runtime.executable()
                self.binary.unlink()

    def test_workspace_commands_use_scoped_binary(self):
        self.create_binary()
        result = mock.Mock(returncode=0)
        with mock.patch.object(core.subprocess, 'run', return_value=result) as run:
            self.assertIs(core.tmux('list-sessions'), result)
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [str(self.binary), '-L', core.SOCKET])
        self.assertEqual(args[-1], 'list-sessions')

    def test_startup_probe_uses_scoped_binary(self):
        self.create_binary()
        with mock.patch.object(core.sys, 'platform', 'darwin'), \
                mock.patch.object(core, 'recover_closed_displays'), \
                mock.patch.object(core.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            core.prepare_workspace()
        self.assertEqual(run.call_args.args[0],
                         [str(self.binary), '-L', core.SOCKET, 'list-sessions'])

    def test_attach_retains_vscode_capability_and_viewer_target(self):
        self.create_binary()
        self.assertEqual(desktop.viewer_attach_command('viewer-test', {'TERM_PROGRAM': 'vscode'}),
                         [str(self.binary), '-L', desktop.SOCKET, '-T', 'hyperlinks',
                          'attach-session', '-t', '=viewer-test'])

    def test_hosted_attachment_is_never_routed_to_display_bundle(self):
        self.create_binary()
        command = backend.Backend(mode='local').attachment(9)
        self.assertEqual(command[:3], ['/opt/homebrew/bin/tmux', '-L', 'jarvis-mobile'])
        self.assertNotIn(str(self.binary), command)
        self.assertEqual(command[-1], '=jarvis-ios-9')

    def test_full_installer_ships_runtime_selector(self):
        self.assertIn('tmux_runtime.py', install.FILES)


if __name__ == '__main__':
    unittest.main()
