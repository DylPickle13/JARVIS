import importlib.util
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backup', Path(__file__).with_name('restic_backup.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'source'
        self.root.mkdir()
        self.policy = json.loads((b.HERE / 'policy.json').read_text())
        (self.root / 'projects/projects-drive-backup').mkdir(parents=True)
        (self.root / 'projects/projects-drive-backup/policy.json').write_text(json.dumps(self.policy))
        (self.root / 'projects/operation-jarvis/jarvisd/jarvisd_core/scheduler').mkdir(parents=True)
        (self.root / 'projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py').write_text('# fixture\n')
        (self.root / 'projects/operation-jarvis/data/scheduler').mkdir(parents=True)
        (self.root / 'README.md').write_text('restore fixture\n')
        (self.root / '.env').write_text('TEST=not-a-real-secret\n')
        self.dbpath = self.root / 'projects/operation-jarvis/data/scheduler/scheduler.sqlite'
        self.db = sqlite3.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE records(value TEXT)')
        self.db.execute("INSERT INTO records VALUES ('committed-in-wal')")
        self.db.commit()
        self.password = self.base / 'password'
        self.password.write_text('test-only-password')
        self.password.chmod(0o600)
        self.config = self.base / 'config.json'
        self.config.write_text(json.dumps({
            'source': str(self.root), 'state_dir': str(self.base / 'state'),
            'repository': str(self.base / 'repository'),
            'password_file': str(self.password), 'rclone_config': str(self.base / 'rclone.conf'),
            'host': 'test-host', 'restic': shutil.which('restic') or '/opt/homebrew/bin/restic'
        }))

    def test_policy_keeps_unique_data_and_secrets(self):
        for path in ['.env', 'projects/temp/analysis.py', 'projects/laya-model/models/custom.safetensors',
                     'projects/foo/building-notes.md', '.git', '.pi/runtime/pi-lazy-tools/source']:
            self.assertFalse(b.excluded(Path(path), self.policy), path)
        for path in ['projects/foo/.venv', 'projects/foo/.build',
                     'projects/operation-jarvis/keyboard/karabiner/upstream/src/apps/SettingsWindow/build',
                     'projects/temp/assessment/.runtime', 'projects/foo/node_modules']:
            self.assertTrue(b.excluded(Path(path), self.policy), path)

    def test_inventory_prunes_and_does_not_follow_symlinks(self):
        generated = self.root / 'projects/.venv'
        generated.mkdir()
        (generated / 'huge').write_bytes(b'x' * 10000)
        (self.root / 'projects/outside').symlink_to(self.base, target_is_directory=True)
        omitted, databases, total, count = b.inventory(self.root, self.policy)
        self.assertIn(generated, omitted)
        self.assertIn(self.dbpath, databases)
        self.assertLess(count, 20)

    def test_sqlite_backup_captures_wal(self):
        target = self.base / 'copy.sqlite'
        b.snapshot_database(self.dbpath, target, time.monotonic() + 10)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute('SELECT value FROM records').fetchone()[0], 'committed-in-wal')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_missing_source_and_public_password_rejected(self):
        backup = b.Backup(self.config, 60)
        self.password.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'owner-only'):
            backup.validate_source()
        self.password.chmod(0o600)
        (self.root / '.env').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Required source missing'):
            backup.validate_source()

    def test_local_overlap_is_not_silent_success(self):
        backup = b.Backup(self.config, 60)
        with backup.locked():
            with self.assertRaisesRegex(RuntimeError, 'Another backup'):
                with b.Backup(self.config, 60).locked():
                    pass

    def test_ambient_repository_and_remote_overrides_are_removed(self):
        with patch.dict(os.environ, {'RESTIC_REPOSITORY': 'wrong', 'RESTIC_PASSWORD': 'wrong',
                                     'RCLONE_DRIVE_ROOT_FOLDER_ID': 'wrong'}):
            backup = b.Backup(self.config, 60)
        self.assertEqual(backup.env['RESTIC_REPOSITORY'], str(self.base / 'repository'))
        self.assertNotIn('RESTIC_PASSWORD', backup.env)
        self.assertNotIn('RCLONE_DRIVE_ROOT_FOLDER_ID', backup.env)

    def test_nightly_skips_recent_maintenance(self):
        backup = b.Backup(self.config, 60)
        backup.record(last_maintenance_at=b.utcnow())
        with patch.object(backup, 'backup') as upload, patch.object(backup, 'maintain') as maintain:
            backup.nightly()
            upload.assert_called_once()
            maintain.assert_not_called()

    def test_nightly_runs_missing_or_overdue_maintenance_after_backup(self):
        backup = b.Backup(self.config, 60)
        overdue = (b.datetime.now(b.timezone.utc) - timedelta(days=8)).isoformat()
        for last in (None, overdue):
            backup.record(last_maintenance_at=last)
            calls = []
            with patch.object(backup, 'backup', side_effect=lambda: calls.append('backup')), \
                 patch.object(backup, 'maintain', side_effect=lambda: calls.append('maintenance')):
                backup.nightly()
            self.assertEqual(calls, ['backup', 'maintenance'])

    def test_nightly_failure_never_runs_maintenance(self):
        backup = b.Backup(self.config, 60)
        with patch.object(backup, 'backup', side_effect=RuntimeError('backup failed')), \
             patch.object(backup, 'maintain') as maintain:
            with self.assertRaisesRegex(RuntimeError, 'backup failed'):
                backup.nightly()
            maintain.assert_not_called()

    def test_nightly_propagates_maintenance_failure_for_retry(self):
        backup = b.Backup(self.config, 60)
        with patch.object(backup, 'backup'), \
             patch.object(backup, 'maintain', side_effect=RuntimeError('maintenance failed')):
            with self.assertRaisesRegex(RuntimeError, 'maintenance failed'):
                backup.nightly()
        self.assertNotIn('last_maintenance_at', backup.load_state())

    def test_failed_maintenance_check_cannot_prune(self):
        backup = b.Backup(self.config, 60)
        with patch.object(backup, 'verified_snapshot', return_value='fixture'), \
             patch.object(backup, 'health'), \
             patch.object(backup, 'run', side_effect=RuntimeError('integrity failure')) as run:
            with self.assertRaisesRegex(RuntimeError, 'integrity failure'):
                backup.maintain()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'check')

    def test_health_fails_without_backup_or_when_stale(self):
        backup = b.Backup(self.config, 60)
        with self.assertRaisesRegex(RuntimeError, 'No successful'):
            backup.health(silent=True)
        backup.record(last_success_at='2020-01-01T00:00:00+00:00')
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            backup.health(silent=True)

    def test_failure_never_marks_success_or_prunes(self):
        backup = b.Backup(self.config, 60)
        with backup.locked(), patch.object(backup, 'run', side_effect=RuntimeError('exit 3')) as run:
            with self.assertRaisesRegex(RuntimeError, 'exit 3'):
                backup.backup()
            self.assertEqual(run.call_count, 1)
        self.assertNotIn('last_success_at', backup.load_state())

    @unittest.skipUnless(shutil.which('restic'), 'restic required for integration test')
    def test_local_repository_end_to_end(self):
        backup = b.Backup(self.config, 120)
        generated = self.root / 'projects/[fixture]/.venv'
        generated.mkdir(parents=True)
        (generated / 'exclude-me.txt').write_text('reproducible dependency')
        with backup.locked():
            backup.run(['init'])
            backup.backup()
            first = backup.load_state()['snapshot_id']
            self.assertTrue(first)
            # Verify from snapshot manifest, not the now-modified live source.
            (self.root / 'README.md').write_text('changed live file\n')
            backup.verify(first)
            backup.backup()
            snapshots = backup.snapshots()
            self.assertEqual(len(snapshots), 2)
            listing = backup.run(['ls', backup.load_state()['snapshot_id']])
            self.assertIn(str(self.root / '.env'), listing)
            self.assertNotIn('exclude-me.txt', listing)
            self.assertNotIn(str(self.dbpath), listing)
            self.assertIn(str(backup.stage / 'projects/operation-jarvis/data/scheduler/scheduler.sqlite'), listing)
            backup.maintain(dry_run=True)
            self.assertEqual(len(backup.snapshots()), 2)
            backup.maintain()
            self.assertEqual(len(backup.snapshots()), 2)
            backup.health(silent=True)


if __name__ == '__main__':
    os.umask(0o077)
    unittest.main()
