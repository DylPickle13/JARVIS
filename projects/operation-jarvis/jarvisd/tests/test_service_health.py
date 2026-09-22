"""Service health metadata tests: no launchd changes or real subprocesses."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from daemon_loader import load_daemon

ROOT = Path(__file__).resolve().parents[1]
jarvisd = load_daemon("jarvisd_service_health_tests", ROOT / "jarvisd.py")


class ServiceHealthTests(unittest.TestCase):
    periodic = {"label": "com.test.periodic", "executionMode": "periodic",
                "critical": True, "allowedActions": []}

    def status(self, text, code=0, spec=None):
        proc = subprocess.CompletedProcess([], code, stdout=text, stderr="")
        return jarvisd._parse_launchctl_status("periodic", spec or self.periodic, proc)

    def test_periodic_success_is_loaded_but_not_running(self):
        value = self.status("state = not running\nruns = 42\nlast exit code = 0\n")
        self.assertTrue(value["ok"])
        self.assertTrue(value["loaded"])
        self.assertFalse(value["running"])
        self.assertEqual(value["executionMode"], "periodic")
        self.assertEqual(value["lastExitCode"], 0)
        self.assertIsNone(value["lastExitSignal"])
        self.assertTrue(value["critical"])
        self.assertEqual(value["allowedActions"], [])

    def test_running_job_preserves_previous_failure_for_consumers(self):
        value = self.status("state = running\npid = 123\nlast exit code = 2\n")
        self.assertTrue(value["running"])
        self.assertEqual(value["pid"], 123)
        self.assertEqual(value["lastExitCode"], 2)
        self.assertTrue(value["ok"], "status read success is not job success")

    def test_signed_exit_codes_are_not_status_command_return_codes(self):
        for code in (0, 1, 127, 255, -9, -2147483648, 2147483647):
            with self.subTest(code=code):
                self.assertEqual(self.status(f"last exit code = {code}\n")["lastExitCode"], code)

    def test_missing_never_exited_and_malformed_results_stay_unknown(self):
        for text in ("", "last exit code = (never exited)\n", "last exit code = unknown\n",
                     "last exit code = 0 trailing text\n", "last exit code = 9999999999999\n",
                     "last exit code = 2147483648\n", "last exit code = -2147483649\n",
                     "not last exit code = 0\n"):
            with self.subTest(text=text):
                self.assertIsNone(self.status(text)["lastExitCode"])

    def test_termination_signal_cannot_inherit_a_previous_success(self):
        for signal in ("9", "Killed: 9", "Terminated: 15"):
            value = self.status(f"last exit code = 0\nlast terminating signal = {signal}\n")
            self.assertIsNone(value["lastExitCode"])
            self.assertIn(value["lastExitSignal"], (9, 15))
        for unknown in ("SIGKILL", "unknown", "0", "999"):
            value = self.status(f"last exit code = 0\nlast terminating signal = {unknown}\n")
            self.assertIsNone(value["lastExitCode"])
            self.assertIsNone(value["lastExitSignal"])

    def test_unloaded_and_failed_status_cannot_reuse_exit_success(self):
        parsed = self.status("last exit code = 0\n", code=1)
        self.assertFalse(parsed["loaded"])
        self.assertIsNone(parsed["lastExitCode"])
        for stderr, expected_ok in (("Could not find service", True), ("permission denied", False)):
            with self.subTest(stderr=stderr), mock.patch.object(
                jarvisd.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 1, stdout="", stderr=stderr),
            ) as run:
                value = jarvisd._service_status("periodic", self.periodic)
                self.assertEqual(value["ok"], expected_ok)
                self.assertEqual(value["executionMode"], "periodic")
                self.assertIsNone(value.get("lastExitCode"))
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][:2], ["launchctl", "print"])

    def test_unknown_execution_modes_are_not_silently_periodic(self):
        self.assertEqual(jarvisd._service_metadata({})["executionMode"], "continuous")
        for invalid in ("oneshot", "PERIODIC", "", None, [], True):
            self.assertIsNone(jarvisd._service_metadata({"executionMode": invalid})["executionMode"])

    def test_current_configuration_declares_scheduler_periodic_without_control_permission(self):
        services = json.loads((ROOT / "services.json").read_text())["services"]
        self.assertEqual(services["jobs-scheduler"]["executionMode"], "periodic")
        self.assertTrue(services["jobs-scheduler"]["critical"])
        self.assertEqual(services["jobs-scheduler"]["allowedActions"], [])
        self.assertEqual(services["room-audio-server"]["executionMode"], "continuous")


if __name__ == "__main__":
    unittest.main()
