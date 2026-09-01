from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".pi" / "scheduler" / "apns_registration.py"


class APNsRegistrationBoundaryTests(unittest.TestCase):
    def run_helper(self, payload: dict, temp: Path):
        environment = os.environ.copy()
        environment.update(
            {
                "JARVIS_SCHEDULER_DIR": str(temp),
                "JARVIS_SCHEDULER_DB_PATH": str(temp / "scheduler.sqlite"),
                "JARVIS_APNS_ENVIRONMENT": "development",
            }
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            cwd=ROOT,
            env=environment,
            timeout=10,
            check=False,
        )

    def test_fixed_boundary_accepts_one_private_registration_without_echoing_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            token = "ab" * 32
            completed = self.run_helper(
                {
                    "protocolVersion": 1,
                    "action": "register",
                    "platform": "iphone",
                    "environment": "development",
                    "installationID": str(uuid.uuid4()),
                    "deviceToken": token,
                },
                temp,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            response = json.loads(completed.stdout)
            self.assertTrue(response["ok"])
            self.assertEqual(response["platform"], "iphone")
            self.assertNotIn(token, completed.stdout.decode("utf-8"))
            self.assertEqual(completed.stderr, b"")
            self.assertEqual((temp / "scheduler.sqlite").stat().st_mode & 0o777, 0o600)

    def test_invalid_registration_never_echoes_submitted_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            token = "ab" * 32
            completed = self.run_helper(
                {
                    "protocolVersion": 1,
                    "action": "register",
                    "platform": "widget",
                    "environment": "development",
                    "installationID": str(uuid.uuid4()),
                    "deviceToken": token,
                },
                temp,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, b"")
            self.assertNotIn(token, completed.stderr.decode("utf-8"))
            self.assertFalse(json.loads(completed.stderr)["ok"])


if __name__ == "__main__":
    unittest.main()
