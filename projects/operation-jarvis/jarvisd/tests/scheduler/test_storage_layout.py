from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[5]
BACKEND = ROOT / "projects/operation-jarvis/jarvisd/jarvisd_core/scheduler"
spec = importlib.util.spec_from_file_location("scheduler_migrate_storage", BACKEND / "migrate_storage.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class StorageLayoutTests(unittest.TestCase):
    def test_copy_includes_wal_preserves_all_rows_and_is_private(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, target = root / "old.sqlite", root / "private/new.sqlite"
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT, enabled INTEGER)")
                db.execute("CREATE TABLE receipts(event_id TEXT, state TEXT)")
                db.execute("INSERT INTO jobs(prompt,enabled) VALUES('private prompt',0)")
                db.execute("INSERT INTO receipts VALUES('event', 'ambiguous')")
                db.commit()
                self.assertTrue(Path(str(source) + "-wal").exists())
                result = migration.copy_database(source, target)
                self.assertEqual(result["tables"], {"jobs": 1, "receipts": 1, "sqlite_sequence": 1})
                with closing(sqlite3.connect(target)) as copied:
                    self.assertEqual(migration.fingerprint(db), migration.fingerprint(copied))
            self.assertTrue(source.exists())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(ValueError):
                migration.copy_database(source, target)

    def test_invalid_source_leaves_no_destination(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, target = root / "bad.sqlite", root / "new.sqlite"
            source.write_text("not a database")
            with self.assertRaises(sqlite3.DatabaseError):
                migration.copy_database(source, target)
            self.assertFalse(target.exists())
            source.unlink()
            with self.assertRaises(ValueError):
                migration.copy_database(source, target)

    def test_symlinks_and_orphan_sidecars_are_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, target = root / "old.sqlite", root / "new.sqlite"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE sample(id INTEGER)")
            alias = root / "alias.sqlite"
            alias.symlink_to(source)
            with self.assertRaises(ValueError):
                migration.copy_database(alias, target)
            target.symlink_to(root / "missing")
            with self.assertRaises(ValueError):
                migration.copy_database(source, target)
            target.unlink()
            Path(str(target) + "-wal").touch()
            with self.assertRaises(ValueError):
                migration.copy_database(source, target)

    def test_default_state_is_backend_owned_and_package_imports_work(self):
        env = {k: v for k, v in os.environ.items() if k not in {
            "JARVIS_SCHEDULER_DIR", "JARVIS_SCHEDULER_DB_PATH", "JARVIS_SESSION_NOTIFICATIONS_DIR"
        }}
        env["PYTHONPATH"] = str(BACKEND.parents[1])
        result = subprocess.run([sys.executable, "-c", '''
from pathlib import Path
from jarvisd_core.scheduler import runner, session_completion, apns_registration
assert runner.ROOT == Path.cwd()
assert runner.DB_PATH == Path.cwd() / "projects/operation-jarvis/data/scheduler/scheduler.sqlite"
assert runner.SESSION_NOTIFICATIONS_DIR == Path.cwd() / "projects/operation-jarvis/data/session-notifications"
assert apns_registration._load_runner() is runner
runner._provider_configuration()
'''], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backend_cli_uses_explicit_store_outside_project_cwd(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw).resolve() / "scheduler.sqlite"
            env = dict(os.environ, JARVIS_SCHEDULER_DIR=raw,
                       JARVIS_SCHEDULER_DB_PATH=str(target))
            result = subprocess.run([sys.executable, str(BACKEND / "runner.py"), "--json", "status"],
                                    cwd=raw, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(target), result.stdout)
            self.assertTrue(target.is_file())

    def test_retired_pi_scheduler_locations_are_absent(self):
        for relative in (".pi/scheduler", ".pi/runtime/session-notifications"):
            path = ROOT / relative
            self.assertFalse(path.exists(), relative)
            self.assertFalse(path.is_symlink(), relative)

    def test_script_help_is_available_outside_project_cwd(self):
        with tempfile.TemporaryDirectory() as raw:
            result = subprocess.run([sys.executable, str(BACKEND / "runner.py"), "--help"],
                                    cwd=raw, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("run-due", result.stdout)


if __name__ == "__main__":
    unittest.main()
