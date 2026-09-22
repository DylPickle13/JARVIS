"""Temporary private DBs and fake notification transport only."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from jarvisd_core.monitor_store import MonitorStore
from jarvisd_core.monitor_worker import MonitorWorker, notify_local


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'monitor' / 'history.sqlite3'
        self.now = [0.0]
        self.notify = Mock(return_value=True)
        self.store = MonitorStore(self.path, ('security/fixture',), clock=lambda: self.now[0], notifier=self.notify)
        self.addCleanup(lambda: self.store.close())

    def sample(self, at, available):
        self.now[0] = at
        self.store.observe({'security/fixture': available})

    def test_sustained_failure_one_alert_and_recovery(self):
        for at in (0, 60):
            self.sample(at, False)
        self.assertEqual(self.store.history(), [])
        self.sample(120, False)
        self.sample(180, False)
        self.assertEqual(len(self.store.history()), 1)
        self.notify.assert_called_once_with('unavailable')
        self.sample(240, True)
        self.assertEqual([r['kind'] for r in self.store.history()], ['recovered', 'unavailable'])
        self.assertEqual(self.notify.call_count, 2)
        self.assertFalse(self.store.status()['security/fixture']['incidentOpen'])

    def test_transient_recovery_duplicate_checks_and_minimum_duration(self):
        self.sample(0, True)
        for at in (30, 31, 32, 60, 90, 120):
            self.sample(at, False)
        self.assertEqual(self.store.history(), [])  # first failure at 30, only 90s sustained
        self.sample(150, True)
        self.assertEqual(self.store.history(), [])
        self.notify.assert_not_called()

    def test_expiry_and_dashboard_reads_do_not_generate_events(self):
        self.sample(0, True)
        self.assertEqual(self.store.status()['security/fixture']['availability'], 'available')
        self.now[0] = 91
        self.assertEqual(self.store.status()['security/fixture']['availability'], 'unavailable')
        self.assertEqual(self.store.history(), [])

    def test_restart_never_replays_notification_and_success_recovers(self):
        for at in (0, 60, 120):
            self.sample(at, False)
        self.store.close()
        self.store = MonitorStore(self.path, ('security/fixture',), clock=lambda: self.now[0], notifier=self.notify)
        self.assertEqual(self.store.status()['security/fixture']['availability'], 'unavailable')
        for at in (180, 240, 300):
            self.sample(at, False)
        self.assertEqual(len(self.store.history()), 1)
        self.assertEqual(self.notify.call_count, 1)
        self.sample(360, True)
        self.assertEqual(self.notify.call_count, 2)

    def test_private_modes_and_bounded_history(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.path.parent).st_mode & 0o777, 0o700)
        self.store.notifier = None
        for cycle in range(505):
            for offset in (0, 60, 120):
                self.sample(cycle * 240 + offset, False)
            self.sample(cycle * 240 + 180, True)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM history').fetchone()[0], 1000)
        self.assertLess(self.path.stat().st_size, 4 * 1024 * 1024)

    def test_delivery_failure_no_replay_and_sanitized(self):
        self.notify.side_effect = RuntimeError('PRIVATE')
        for at in (0, 60, 120, 180):
            self.sample(at, False)
        self.assertEqual(self.store.history()[0]['notification'], 'failed')
        self.assertNotIn('PRIVATE', str(self.store.history()))
        self.assertEqual(self.notify.call_count, 1)

    def test_worker_storage_errors_are_contained(self):
        store = Mock()
        store.observe.side_effect = RuntimeError('PRIVATE')
        worker = MonitorWorker(store, lambda: {})
        worker.tick()
        self.assertFalse(worker.storage_available)
        store.observe.side_effect = None
        worker.tick()
        self.assertTrue(worker.storage_available)

    def test_fixed_notification_text_and_no_shell(self):
        with patch('jarvisd_core.monitor_worker.subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertTrue(notify_local('unavailable'))
            self.assertEqual(run.call_args.args[0][0], '/usr/bin/osascript')
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
        with self.assertRaises(KeyError):
            notify_local('arbitrary command')
