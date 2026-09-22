import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPT = Path(__file__).resolve().parents[2] / "jarvis-app/scripts/jarvis-mobile-maintenance.py"
spec = importlib.util.spec_from_file_location("maintenance", SCRIPT)
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.patcher = patch.object(maintenance, "OPERATIONS", self.directory)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.identifier = str(uuid.uuid4())

    def request(self, action="start", identifier=None):
        return maintenance.request(dict(action=action, operationID=identifier or self.identifier))

    @patch.object(maintenance.subprocess, "Popen")
    def test_start_is_detached_and_idempotent(self, spawn):
        first = self.request()
        self.assertEqual(first["state"], "queued")
        self.assertEqual(self.request(), first)
        self.assertEqual(self.request("status"), first)
        self.assertEqual(spawn.call_count, 1)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    @patch.object(maintenance.subprocess, "Popen")
    def test_duplicate_operations_blocked(self, spawn):
        self.request()
        with self.assertRaisesRegex(ValueError, "Another restart"):
            self.request(identifier=str(uuid.uuid4()))
        self.assertEqual(spawn.call_count, 1)

    @patch.object(maintenance.subprocess, "Popen")
    def test_status_never_starts_work(self, spawn):
        self.assertEqual(self.request("status")["state"], "notFound")
        spawn.assert_not_called()

    def test_rejects_arbitrary_commands_and_path_traversal(self):
        for payload in [dict(action="shell", operationID=self.identifier),
                        dict(action="start", operationID="../../tmp"),
                        dict(action="start", operationID=self.identifier, command="anything")]:
            with self.assertRaises(ValueError):
                maintenance.request(payload)

    @patch.object(maintenance.subprocess, "Popen", side_effect=OSError("offline"))
    def test_spawn_failure_persisted(self, spawn):
        self.assertEqual(self.request()["state"], "failed")
        self.assertEqual(self.request("status")["state"], "failed")

    def test_stale_job_is_unknown_not_success_or_automatic_retry(self):
        maintenance.save(self.directory / (self.identifier + ".json"), dict(
            operationID=self.identifier, state="running", completed=3,
            updatedAt=time.time() - 700, message="working"))
        self.assertEqual(self.request("status")["state"], "unknown")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.request(identifier=str(uuid.uuid4()))

    def test_worker_publishes_partial_failure(self):
        path = self.directory / (self.identifier + ".json")
        maintenance.save(path, dict(operationID=self.identifier, state="queued", completed=0))
        fake_script = self.directory / "restart.py"
        fake_script.write_text('def restart_all(progress):\n    progress(3)\n    raise RuntimeError("slot 4 busy")\n')
        with patch.object(maintenance, "SCRIPT", fake_script):
            maintenance.worker(self.identifier)
        result = json.loads(path.read_text())
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["completed"], 3)
        self.assertIn("slot 4 busy", result["message"])

    def test_worker_success(self):
        path = self.directory / (self.identifier + ".json")
        maintenance.save(path, dict(operationID=self.identifier, state="queued", completed=0))
        fake_script = self.directory / "restart.py"
        fake_script.write_text('def restart_all(progress):\n    for i in range(1, 11): progress(i)\n')
        with patch.object(maintenance, "SCRIPT", fake_script):
            maintenance.worker(self.identifier)
        result = json.loads(path.read_text())
        self.assertEqual((result["state"], result["completed"]), ("succeeded", 10))
