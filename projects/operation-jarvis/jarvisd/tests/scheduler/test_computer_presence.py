"""Offline lifecycle integration tests: temp database and mocked launchd adapter."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

if __package__:
    from .test_runner import load_runner
else:
    from test_runner import load_runner


class ComputerPresenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner = load_runner(Path(self.temp.name))
        self.job_id = self.runner.COMPUTER_PRESENCE_JOB_ID
        self.add_job(self.job_id, 'Computer presence')

    def add_job(self, job_id, name):
        self.runner.add_job(argparse.Namespace(
            job_id=job_id, name=name, schedule='1m', kind='interval',
            prompt='/usr/bin/true', model=self.runner.DIRECT_STDOUT_MODEL, description='test',
        ))

    def job(self):
        with closing(self.runner.connect()) as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (self.job_id,)).fetchone()
            return dict(row) if row else None

    def assert_lock_released(self):
        with closing(self.runner.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM locks WHERE name='computer-presence-control'").fetchone()[0], 0)

    def test_disable_by_name_stops_both_and_persists_schedule_first(self):
        def stop(enabled):
            self.assertFalse(enabled)
            self.assertFalse(self.job()['enabled'])
        with patch.object(self.runner, 'set_computer_presence_controller', side_effect=stop) as helper:
            result = self.runner.set_enabled(argparse.Namespace(job_id='Computer presence'), False)
        helper.assert_called_once_with(False)
        self.assertFalse(result['job']['enabled'])
        self.assertIn('and its controller (stopped)', result['message'])
        self.assert_lock_released()

    def test_enable_starts_controller_before_enabling_schedule(self):
        with patch.object(self.runner, 'set_computer_presence_controller'):
            self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), False)
        def start(enabled):
            self.assertTrue(enabled)
            self.assertFalse(self.job()['enabled'])
        with patch.object(self.runner, 'set_computer_presence_controller', side_effect=start) as helper:
            result = self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), True)
        helper.assert_called_once_with(True)
        self.assertTrue(result['job']['enabled'])
        self.assertIn('controller (running)', result['message'])
        self.assert_lock_released()

    def test_already_disabled_still_reconciles_controller(self):
        with patch.object(self.runner, 'set_computer_presence_controller') as helper:
            self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), False)
            self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), False)
        self.assertEqual(helper.call_count, 2)
        self.assertFalse(self.job()['enabled'])

    def test_controller_failure_keeps_schedule_disabled_and_does_not_replay(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                with patch.object(self.runner, 'set_computer_presence_controller', side_effect=RuntimeError('not verified')) as helper:
                    with self.assertRaisesRegex(RuntimeError, 'not verified'):
                        self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), enabled)
                helper.assert_called_once_with(enabled)
                self.assertFalse(self.job()['enabled'])
                self.assert_lock_released()

    def test_other_jobs_and_renamed_lookalikes_never_touch_controller(self):
        self.add_job('job_other', 'Other')
        with closing(self.runner.connect()) as conn, conn:
            conn.execute("UPDATE jobs SET name='Renamed presence' WHERE id=?", (self.job_id,))
            conn.execute("UPDATE jobs SET name='Computer presence' WHERE id='job_other'")
        with patch.object(self.runner, 'set_computer_presence_controller') as helper:
            self.runner.set_enabled(argparse.Namespace(job_id='Computer presence'), False)
            self.runner.set_enabled(argparse.Namespace(job_id='job_other'), True)
        helper.assert_not_called()
        self.assertTrue(self.job()['enabled'])

    def test_named_lock_serializes_lifecycle_changes(self):
        with closing(self.runner.connect()) as conn:
            owner = self.runner.acquire_lock(conn, 'computer-presence-control')
            try:
                with patch.object(self.runner, 'set_computer_presence_controller') as helper:
                    with self.assertRaisesRegex(RuntimeError, 'in progress'):
                        self.runner.set_enabled(argparse.Namespace(job_id=self.job_id), False)
                    helper.assert_not_called()
                self.assertTrue(self.job()['enabled'])
            finally:
                self.runner.release_lock(conn, 'computer-presence-control', owner)

    def test_remove_stops_controller_before_deleting_job(self):
        with patch.object(self.runner, 'set_computer_presence_controller') as helper:
            self.runner.remove_job(argparse.Namespace(job_id=self.job_id))
        helper.assert_called_once_with(False)
        self.assertIsNone(self.job())
        self.assert_lock_released()

    def test_failed_remove_keeps_disabled_job(self):
        with patch.object(self.runner, 'set_computer_presence_controller', side_effect=RuntimeError('not verified')):
            with self.assertRaises(RuntimeError):
                self.runner.remove_job(argparse.Namespace(job_id=self.job_id))
        self.assertFalse(self.job()['enabled'])
        self.assert_lock_released()

    def test_fixed_controller_subprocess_has_no_shell_or_raw_error_leak(self):
        for enabled, expected in ((False, 'stopped'), (True, 'running')):
            result = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'controller': expected}), '')
            with patch.object(self.runner.subprocess, 'run', return_value=result) as command:
                self.runner.set_computer_presence_controller(enabled)
            args, kwargs = command.call_args
            self.assertEqual(args[0], [self.runner.sys.executable,
                str(self.runner.ROOT / 'projects/operation-jarvis/keyboard/watch_control.py'),
                'enable' if enabled else 'disable'])
            self.assertNotIn('shell', kwargs)
        for output in ('not JSON: SECRET', '{"ok":false,"error":"SECRET"}', '{"ok":true,"controller":"running"}'):
            result = subprocess.CompletedProcess([], 0, output, 'SECRET')
            with patch.object(self.runner.subprocess, 'run', return_value=result) as command:
                with self.assertRaises(RuntimeError) as error:
                    self.runner.set_computer_presence_controller(False)
            self.assertNotIn('SECRET', str(error.exception))
            command.assert_called_once()
