from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import os
import sqlite3
import tempfile
import types
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / ".pi" / "scheduler" / "runner.py"


def load_runner(temp: Path):
    old_dir = os.environ.get("JARVIS_SCHEDULER_DIR")
    old_db = os.environ.get("JARVIS_SCHEDULER_DB_PATH")
    os.environ["JARVIS_SCHEDULER_DIR"] = str(temp)
    os.environ["JARVIS_SCHEDULER_DB_PATH"] = str(temp / "scheduler.sqlite")
    try:
        name = f"jarvis_scheduler_test_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old_dir is None:
            os.environ.pop("JARVIS_SCHEDULER_DIR", None)
        else:
            os.environ["JARVIS_SCHEDULER_DIR"] = old_dir
        if old_db is None:
            os.environ.pop("JARVIS_SCHEDULER_DB_PATH", None)
        else:
            os.environ["JARVIS_SCHEDULER_DB_PATH"] = old_db


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp = Path(self.temp_dir.name)
        self.runner = load_runner(self.temp)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def add_direct_job(self, *, name: str = "test-job", prompt: str = "/usr/bin/true") -> str:
        args = argparse.Namespace(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            name=name,
            schedule="1h",
            kind="interval",
            prompt=prompt,
            model=self.runner.DIRECT_STDOUT_MODEL,
            description="test",
        )
        return self.runner.add_job(args)["job"]["id"]

    def test_schema_is_private_and_has_bounded_history_tables(self) -> None:
        with closing(self.runner.connect()) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"jobs", "results", "notification_outbox", "locks"}.issubset(tables))
        self.assertEqual(self.runner.DB_PATH.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.runner.DB_PATH.parent.stat().st_mode & 0o777, 0o700)

    def test_silent_direct_success_updates_health_without_result(self) -> None:
        job_id = self.add_direct_job()
        result = self.runner.run_one(argparse.Namespace(job_id=job_id))["run"]
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["silent"])
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertEqual(job["run_count"], 1)
        self.assertIsNotNone(job["last_silent_success_at"])

    def test_output_success_is_persisted_and_public(self) -> None:
        job_id = self.add_direct_job(prompt="/bin/echo hello-from-job")
        run = self.runner.run_one(argparse.Namespace(job_id=job_id))["run"]
        self.assertFalse(run["silent"])
        payload = self.runner.list_public_results(argparse.Namespace(after=None, limit="10", job_id=None))
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["jobId"], job_id)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["output"], "hello-from-job")
        self.assertEqual(result["id"], run["run_id"])

    def test_failure_is_always_persisted_and_sanitized(self) -> None:
        old_secret = os.environ.get("JARVIS_TEST_API_KEY")
        os.environ["JARVIS_TEST_API_KEY"] = "raw-environment-secret"
        self.addCleanup(
            lambda: os.environ.pop("JARVIS_TEST_API_KEY", None)
            if old_secret is None
            else os.environ.__setitem__("JARVIS_TEST_API_KEY", old_secret)
        )
        job_id = self.add_direct_job(
            prompt="/bin/sh -c 'echo TOKEN=supersecret >&2; echo '\"'\"'{\"api_key\":\"json-secret\"}'\"'\"'; echo raw-environment-secret; echo /Users/example/private; exit 3'"
        )
        run = self.runner.run_one(argparse.Namespace(job_id=job_id))["run"]
        self.assertEqual(run["status"], "error")
        payload = self.runner.list_public_results(argparse.Namespace(after=None, limit="10", job_id=job_id))
        result = payload["results"][0]
        rendered = f"{result['output']}\n{result['error']}"
        self.assertNotIn("supersecret", rendered)
        self.assertNotIn("json-secret", rendered)
        self.assertNotIn("raw-environment-secret", rendered)
        self.assertNotIn("/Users/", rendered)
        self.assertIn("[REDACTED]", rendered)
        self.assertIn("<local-path>", rendered)
        self.assertLessEqual(
            len((result["output"] or "").encode("utf-8")) + len((result["error"] or "").encode("utf-8")),
            self.runner.MAX_RESULT_BYTES,
        )

    def test_result_output_is_utf8_bounded_and_marked(self) -> None:
        job_id = self.add_direct_job()
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.runner.utcnow()
            result = self.runner.persist_completion(
                conn,
                job=job,
                run_id="run_large",
                output_kind="direct",
                started=now,
                finished=now,
                status="success",
                exit_code=0,
                output="é" * 100_000,
                error=None,
            )
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["output"].encode("utf-8")), self.runner.MAX_RESULT_BYTES)
        self.assertTrue(result["output"].endswith("[Output truncated by JARVIS]"))

    def test_history_retention_deletes_oldest_results_and_outbox(self) -> None:
        job_id = self.add_direct_job()
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.runner.utcnow()
            for index in range(self.runner.MAX_RESULTS + 2):
                self.runner.persist_completion(
                    conn,
                    job=job,
                    run_id=f"run_{index}",
                    output_kind="direct",
                    started=now,
                    finished=now,
                    status="success",
                    exit_code=0,
                    output=f"result {index}",
                    error=None,
                )
            rows = conn.execute("SELECT id FROM results ORDER BY sequence").fetchall()
        self.assertEqual(len(rows), self.runner.MAX_RESULTS)
        self.assertEqual(rows[0]["id"], "run_2")

    def test_incremental_results_are_oldest_first_after_cursor(self) -> None:
        job_id = self.add_direct_job()
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.runner.utcnow()
            for index in range(3):
                self.runner.persist_completion(
                    conn,
                    job=job,
                    run_id=f"run_cursor_{index}",
                    output_kind="direct",
                    started=now,
                    finished=now,
                    status="success",
                    exit_code=0,
                    output=str(index),
                    error=None,
                )
        initial = self.runner.list_public_results(argparse.Namespace(after=None, limit="2", job_id=None))
        self.assertEqual([item["output"] for item in initial["results"]], ["2", "1"])
        incremental = self.runner.list_public_results(argparse.Namespace(after="1", limit="2", job_id=None))
        self.assertEqual([item["output"] for item in incremental["results"]], ["1", "2"])

    def test_public_inventory_omits_prompt_model_and_private_identifiers(self) -> None:
        self.add_direct_job(prompt="/bin/echo secret-prompt")
        payload = self.runner.list_public_jobs(argparse.Namespace())
        serialized = __import__("json").dumps(payload)
        self.assertNotIn("secret-prompt", serialized)
        self.assertNotIn("__direct_stdout__", serialized)
        self.assertNotIn("contextId", serialized)

    def test_notification_outbox_stays_empty_before_activation(self) -> None:
        job_id = self.add_direct_job(prompt="/bin/echo ready")
        self.runner.run_one(argparse.Namespace(job_id=job_id))
        with closing(self.runner.connect()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        self.assertEqual(count, 0)

    def notification_registration(self, platform: str, token: str) -> dict:
        return {
            "protocolVersion": 1,
            "action": "register",
            "platform": platform,
            "environment": "development",
            "installationID": str(uuid.uuid4()),
            "deviceToken": token,
        }

    def test_notification_registration_is_private_strict_and_sanitized(self) -> None:
        token = "ab" * 32
        acknowledgement = self.runner.register_notification_device(
            self.notification_registration("iphone", token)
        )
        self.assertTrue(acknowledgement["ok"])
        self.assertNotIn(token, __import__("json").dumps(acknowledgement))
        status = self.runner.notification_status()
        self.assertTrue(status["devices"]["iphone"]["registered"])
        self.assertFalse(status["devices"]["watch"]["registered"])
        self.assertNotIn(token, __import__("json").dumps(status))
        with self.assertRaisesRegex(ValueError, "fields are invalid"):
            self.runner.register_notification_device(
                self.notification_registration("watch", "cd" * 32) | {"jobName": "private"}
            )
        with self.assertRaisesRegex(ValueError, "fields are invalid"):
            registration = self.notification_registration("watch", "cd" * 32)
            registration.pop("deviceToken")
            self.runner.register_notification_device(registration)
        with self.assertRaisesRegex(ValueError, "fields are invalid"):
            deactivation = self.notification_registration("watch", "cd" * 32) | {"action": "deactivate"}
            self.runner.register_notification_device(deactivation)
        with closing(self.runner.connect()) as conn:
            row = conn.execute(
                "SELECT device_token,topic,token_sha256 FROM notification_devices WHERE platform='iphone'"
            ).fetchone()
        self.assertEqual(row["device_token"], token)
        self.assertEqual(row["topic"], "com.operation-jarvis.jarvis")
        self.assertNotEqual(row["token_sha256"], token)
        self.assertEqual(self.runner.DB_PATH.stat().st_mode & 0o777, 0o600)

    def test_activation_requires_both_devices_and_creates_independent_delivery_records(self) -> None:
        class Configuration:
            def validate_for_send(self):
                return None

        self.runner.APNS_PROVIDER_ENABLED = True
        self.runner._provider_configuration = lambda: Configuration()
        self.runner.register_notification_device(self.notification_registration("iphone", "ab" * 32))
        with self.assertRaisesRegex(ValueError, "Both current iPhone and Watch"):
            self.runner.enable_notification_dispatch(argparse.Namespace())
        self.runner.register_notification_device(self.notification_registration("watch", "cd" * 32))
        enabled = self.runner.enable_notification_dispatch(argparse.Namespace())
        self.assertTrue(enabled["dispatchEnabled"])

        job_id = self.add_direct_job()
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.runner.utcnow()
            result = self.runner.persist_completion(
                conn,
                job=job,
                run_id="run_apns_dual",
                output_kind="direct",
                started=now,
                finished=now,
                status="success",
                exit_code=0,
                output="private result remains local",
                error=None,
            )
            deliveries = conn.execute(
                "SELECT platform,status,apns_id FROM notification_deliveries ORDER BY platform"
            ).fetchall()
            outbox = conn.execute("SELECT result_sequence,status FROM notification_outbox").fetchone()
        self.assertEqual([row["platform"] for row in deliveries], ["iphone", "watch"])
        self.assertTrue(all(row["status"] == "pending" for row in deliveries))
        self.assertEqual(len({row["apns_id"] for row in deliveries}), 2)
        self.assertEqual(outbox["result_sequence"], result["sequence"])
        self.assertEqual(outbox["status"], "pending")

    def prepare_dual_notification_delivery(self):
        class Configuration:
            def validate_for_send(self):
                return None

        self.runner.APNS_PROVIDER_ENABLED = True
        self.runner._provider_configuration = lambda: Configuration()
        self.runner.register_notification_device(self.notification_registration("iphone", "ab" * 32))
        self.runner.register_notification_device(self.notification_registration("watch", "cd" * 32))
        self.runner.enable_notification_dispatch(argparse.Namespace())
        job_id = self.add_direct_job()
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            now = self.runner.utcnow()
            self.runner.persist_completion(
                conn,
                job=job,
                run_id=f"run_{uuid.uuid4().hex}",
                output_kind="direct",
                started=now,
                finished=now,
                status="success",
                exit_code=0,
                output="private result remains local",
                error=None,
            )

    def test_definite_retry_then_ambiguous_send_never_retries_again(self) -> None:
        self.prepare_dual_notification_delivery()
        calls = []
        outcomes = [
            types.SimpleNamespace(
                outcome="retry", status_code=429, reason="TooManyRequests",
                retry_after_seconds=1, invalidate_token=False, invalidation_timestamp=None,
            ),
            types.SimpleNamespace(
                outcome="accepted", status_code=200, reason="accepted",
                retry_after_seconds=None, invalidate_token=False, invalidation_timestamp=None,
            ),
            types.SimpleNamespace(
                outcome="ambiguous", status_code=None, reason="transport-error",
                retry_after_seconds=None, invalidate_token=False, invalidation_timestamp=None,
            ),
        ]

        class Provider:
            def __init__(self, configuration):
                pass

            def send_alert(self, **kwargs):
                calls.append(kwargs)
                return outcomes.pop(0)

        old_module = __import__("sys").modules.get("apns_provider")
        __import__("sys").modules["apns_provider"] = types.SimpleNamespace(APNsProvider=Provider)
        self.addCleanup(
            lambda: __import__("sys").modules.pop("apns_provider", None)
            if old_module is None
            else __import__("sys").modules.__setitem__("apns_provider", old_module)
        )

        with closing(self.runner.connect()) as conn:
            first_delivery = conn.execute(
                "SELECT id,apns_id FROM notification_deliveries ORDER BY id LIMIT 1"
            ).fetchone()
            self.runner.drain_notifications(conn)
            conn.execute(
                "UPDATE notification_deliveries SET next_attempt_at=? WHERE id=?",
                (self.runner.iso(self.runner.utcnow()), first_delivery["id"]),
            )
            conn.commit()
            self.runner.drain_notifications(conn)
            self.runner.drain_notifications(conn)
            row = conn.execute(
                "SELECT status,attempt_count,next_attempt_at FROM notification_deliveries WHERE id=?",
                (first_delivery["id"],),
            ).fetchone()
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["apns_id"], first_delivery["apns_id"])
        self.assertEqual(calls[2]["apns_id"], first_delivery["apns_id"])
        self.assertEqual(row["status"], "ambiguous")
        self.assertEqual(row["attempt_count"], 2)
        self.assertIsNone(row["next_attempt_at"])

    def test_provider_authorization_failure_stops_before_second_topic(self) -> None:
        self.prepare_dual_notification_delivery()
        calls = []

        class Provider:
            def __init__(self, configuration):
                pass

            def send_alert(self, **kwargs):
                calls.append(kwargs)
                return types.SimpleNamespace(
                    outcome="failed", status_code=403, reason="Forbidden",
                    retry_after_seconds=None, invalidate_token=False, invalidation_timestamp=None,
                )

        old_module = __import__("sys").modules.get("apns_provider")
        __import__("sys").modules["apns_provider"] = types.SimpleNamespace(APNsProvider=Provider)
        self.addCleanup(
            lambda: __import__("sys").modules.pop("apns_provider", None)
            if old_module is None
            else __import__("sys").modules.__setitem__("apns_provider", old_module)
        )
        with closing(self.runner.connect()) as conn:
            result = self.runner.drain_notifications(conn)
            states = conn.execute(
                "SELECT status FROM notification_deliveries ORDER BY id"
            ).fetchall()
            durable_gate = self.runner._config_value(conn, "apns_dispatch_enabled")
            second_drain = self.runner.drain_notifications(conn)
        self.assertIn("error", result)
        self.assertEqual(len(calls), 1)
        self.assertEqual([row["status"] for row in states], ["failed", "pending"])
        self.assertEqual(durable_gate, "0")
        self.assertFalse(second_drain["enabled"])
        self.assertEqual(len(calls), 1)

    def test_deactivation_is_installation_scoped_and_idempotent(self) -> None:
        registration = self.notification_registration("watch", "ef" * 32)
        self.runner.register_notification_device(registration)
        wrong = registration | {
            "action": "deactivate",
            "installationID": str(uuid.uuid4()),
            "deviceToken": None,
        }
        wrong.pop("deviceToken")
        self.assertFalse(self.runner.register_notification_device(wrong)["changed"])
        correct = registration | {"action": "deactivate"}
        correct.pop("deviceToken")
        self.assertTrue(self.runner.register_notification_device(correct)["changed"])
        self.assertFalse(self.runner.register_notification_device(correct)["changed"])
        self.assertFalse(self.runner.notification_status()["devices"]["watch"]["registered"])
        with closing(self.runner.connect()) as conn:
            self.assertIsNone(
                conn.execute("SELECT device_token FROM notification_devices WHERE platform='watch'").fetchone()
            )

    def test_replacement_and_apns_invalidation_remove_stale_private_tokens(self) -> None:
        registration = self.notification_registration("iphone", "ab" * 32)
        self.runner.register_notification_device(registration)
        with closing(self.runner.connect()) as conn:
            conn.execute(
                "UPDATE notification_devices SET last_accepted_at='2026-09-01T00:00:00Z' WHERE platform='iphone'"
            )
            conn.commit()
        self.runner.register_notification_device(registration)
        with closing(self.runner.connect()) as conn:
            same = conn.execute(
                "SELECT installation_id,last_accepted_at FROM notification_devices WHERE platform='iphone'"
            ).fetchone()
        self.assertEqual(same["installation_id"], registration["installationID"])
        self.assertEqual(same["last_accepted_at"], "2026-09-01T00:00:00Z")

        replacement = registration | {
            "installationID": str(uuid.uuid4()),
            "deviceToken": "cd" * 32,
        }
        self.runner.register_notification_device(replacement)
        with closing(self.runner.connect()) as conn:
            replaced = conn.execute(
                "SELECT installation_id,device_token,last_accepted_at FROM notification_devices WHERE platform='iphone'"
            ).fetchone()
            self.assertEqual(replaced["installation_id"], replacement["installationID"])
            self.assertEqual(replaced["device_token"], replacement["deviceToken"])
            self.assertIsNone(replaced["last_accepted_at"])
            self.runner._invalidate_notification_device(
                conn,
                platform="iphone",
                expected_token=replacement["deviceToken"],
                reason="Unregistered",
                invalidation_timestamp=0,
            )
            self.assertIsNotNone(
                conn.execute("SELECT device_token FROM notification_devices WHERE platform='iphone'").fetchone()
            )
            self.runner._invalidate_notification_device(
                conn,
                platform="iphone",
                expected_token=registration["deviceToken"],
                reason="Unregistered",
                invalidation_timestamp=None,
            )
            self.assertIsNotNone(
                conn.execute("SELECT device_token FROM notification_devices WHERE platform='iphone'").fetchone()
            )
            self.runner._invalidate_notification_device(
                conn,
                platform="iphone",
                expected_token=replacement["deviceToken"],
                reason="Unregistered",
                invalidation_timestamp=None,
            )
            conn.commit()
            self.assertIsNone(
                conn.execute("SELECT device_token FROM notification_devices WHERE platform='iphone'").fetchone()
            )

    def test_legacy_migration_preserves_every_scheduler_field_exactly(self) -> None:
        legacy_path = self.temp / "legacy.sqlite"
        self.runner.LEGACY_DB_PATH = legacy_path
        with closing(sqlite3.connect(legacy_path)) as legacy:
            legacy.executescript(
                """
                CREATE TABLE jobs (
                  id TEXT PRIMARY KEY, name TEXT, schedule TEXT, kind TEXT, prompt TEXT,
                  enabled INTEGER, model TEXT, next_run_at TEXT, last_run_at TEXT,
                  last_status TEXT, run_count INTEGER, created_at TEXT, updated_at TEXT,
                  description TEXT
                );
                CREATE TABLE locks (name TEXT PRIMARY KEY, owner TEXT, acquired_at TEXT);
                """
            )
            legacy.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "job_exact",
                    "exact-job",
                    "30m",
                    "interval",
                    "private prompt retained only in the scheduler",
                    1,
                    "test/model",
                    "2026-08-30T05:30:00Z",
                    "2026-08-30T05:00:00Z",
                    "success",
                    42,
                    "2026-08-01T00:00:00Z",
                    "2026-08-30T05:00:00Z",
                    "private local description",
                ),
            )
            legacy.commit()

        result = self.runner.migrate_legacy(argparse.Namespace())
        verified = self.runner.verify_legacy_migration(argparse.Namespace())

        self.assertTrue(result["ok"])
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["jobs"], 1)
        self.assertEqual(verified["fields"], len(self.runner.MIGRATION_JOB_COLUMNS))
        source = self.runner.legacy_migration_snapshot()
        with closing(self.runner.connect()) as target:
            migrated = self.runner.migration_job_snapshot(target)
        self.assertEqual(migrated, source)

    def test_legacy_migration_refuses_active_work_and_leaves_target_empty(self) -> None:
        legacy_path = self.temp / "legacy-locked.sqlite"
        self.runner.LEGACY_DB_PATH = legacy_path
        with closing(sqlite3.connect(legacy_path)) as legacy:
            legacy.executescript(
                """
                CREATE TABLE jobs (
                  id TEXT PRIMARY KEY, name TEXT, schedule TEXT, kind TEXT, prompt TEXT,
                  enabled INTEGER, model TEXT, next_run_at TEXT, last_run_at TEXT,
                  last_status TEXT, run_count INTEGER, created_at TEXT, updated_at TEXT,
                  description TEXT
                );
                CREATE TABLE locks (name TEXT PRIMARY KEY, owner TEXT, acquired_at TEXT);
                INSERT INTO locks VALUES('run-due','owner','2026-08-30T05:00:00Z');
                """
            )
            legacy.commit()

        with self.assertRaisesRegex(ValueError, "active lock"):
            self.runner.migrate_legacy(argparse.Namespace())
        self.assertFalse(self.runner.DB_PATH.exists())


if __name__ == "__main__":
    unittest.main()
