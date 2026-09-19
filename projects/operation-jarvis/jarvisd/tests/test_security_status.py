"""Offline CLI fixtures and loopback HTTP only; no installed security config."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from jarvisd_core import security_status as security
from jarvisd_core.control_http import ControlHTTPServer
from test_jarvisd import jarvisd as daemon

PRIVATE = "PRIVATE-token-host-serial-path"


def fixture(model="T100"):
    return {"device": "fixture", "model": model, "result": "read_succeeded",
            "observed_at": "2999-01-01", "name": PRIVATE, "host": PRIVATE,
            "features": {"motion_detected": {"value": False}, "is_open": {"value": False},
                         "battery_low": {"value": False}, "rssi": {"value": -75},
                         "password": {"value": PRIVATE}}}


class ReadTests(unittest.TestCase):
    def test_success_is_allowlisted_and_radio_freshness_unknown(self):
        runner = Mock(return_value=fixture())
        code, body = security.read_status("/private/security", "fixture", runner=runner)
        self.assertEqual(code, 200)
        self.assertIs(body["data"]["motionDetected"], False)
        self.assertIs(body["data"]["batteryLow"], False)
        self.assertEqual(body["data"]["radioFreshness"], "unknown")
        self.assertEqual(body["source"], "hub_snapshot")
        self.assertEqual(body["securityAssessment"], "not_assessed")
        self.assertNotIn(PRIVATE, json.dumps(body))
        self.assertNotIn("2999", body["observedAt"])
        runner.assert_called_once_with(Path("/private/security"), "fixture")

    def test_hub_and_camera_only_expose_read_identity(self):
        for model in ("H200", "C230"):
            code, body = security.read_status("/private/security", "fixture", runner=Mock(return_value=fixture(model)))
            self.assertEqual(code, 200)
            self.assertEqual(body["data"], {})

    def test_contact_missing_and_bad_feature_types_are_unknown(self):
        raw = fixture("T110")
        raw["features"] = {"is_open": {"value": "false"}, "battery_low": {"value": 0},
                           "rssi": {"value": True}}
        _, body = security.read_status("/private/security", "fixture", runner=Mock(return_value=raw))
        for key in ("isOpen", "batteryLow", "rssi"):
            self.assertIsNone(body["data"][key])
        raw["features"] = {}
        _, body = security.read_status("/private/security", "fixture", runner=Mock(return_value=raw))
        self.assertIsNone(body["data"]["isOpen"])

    def test_errored_feature_and_out_of_range_rssi_are_unknown(self):
        raw = fixture()
        raw["features"]["motion_detected"]["status"] = "unknown"
        raw["features"]["rssi"]["value"] = 999
        _, body = security.read_status("/private/security", "fixture", runner=Mock(return_value=raw))
        self.assertIsNone(body["data"]["motionDetected"])
        self.assertIsNone(body["data"]["rssi"])

    def test_disabled_bad_configuration_and_invalid_selectors_do_not_spawn(self):
        for cli, alias, expected in (("", "fixture", 503), ("relative", "fixture", 503),
                ("/private/security", "../secret", 400), ("/private/security", "--env-file", 400),
                ("/private/security", "fixture;reboot", 400), ("/private/security", "", 400)):
            runner = Mock()
            self.assertEqual(security.read_status(cli, alias, runner=runner)[0], expected)
            runner.assert_not_called()

    def test_failures_are_sanitized_and_never_fresh_or_cached(self):
        runner = Mock(side_effect=[fixture(), security.ReadError("device_busy"), RuntimeError(PRIVATE)])
        self.assertEqual(security.read_status("/private/security", "fixture", runner=runner)[0], 200)
        for expected in ("device_busy", "operation_failed"):
            code, body = security.read_status("/private/security", "fixture", runner=runner)
            self.assertEqual(code, 503)
            self.assertEqual(body["errorCode"], expected)
            self.assertIsNone(body["observedAt"])
            self.assertNotIn("data", body)
            self.assertNotIn(PRIVATE, json.dumps(body))
        self.assertEqual(runner.call_count, 3)

    def test_cli_errors_and_bad_identity_fail_closed(self):
        for raw, reason in (({"result": "error", "reason": "sensor_missing_or_ambiguous"}, "sensor_missing_or_ambiguous"),
                ({"result": "error", "reason": PRIVATE}, "operation_failed"),
                (fixture("D235"), "invalid_output"), ({**fixture(), "device": "other"}, "invalid_output"),
                ({**fixture(), "result": "verified"}, "invalid_output"), ([], "invalid_output")):
            code, body = security.read_status("/private/security", "fixture", runner=Mock(return_value=raw))
            self.assertEqual(code, 503)
            self.assertEqual(body["errorCode"], reason)

    def test_concurrent_read_rejected_not_queued(self):
        entered, release = threading.Event(), threading.Event()
        def runner(*args):
            entered.set()
            release.wait(2)
            return fixture()
        thread = threading.Thread(target=security.read_status,
                                  args=("/private/security", "fixture"), kwargs={"runner": runner})
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            other = Mock()
            code, body = security.read_status("/private/security", "fixture", runner=other)
            self.assertEqual(code, 503)
            self.assertEqual(body["errorCode"], "device_busy")
            other.assert_not_called()
        finally:
            release.set()
            thread.join(2)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cli = Path(temp.name) / "security"

    def run_code(self, code):
        self.cli.write_text(f"#!{sys.executable}\n" + code)
        self.cli.chmod(0o700)
        return security.run_cli(self.cli, "fixture")

    def test_existing_cli_argv_and_no_inherited_secrets(self):
        with patch.dict(os.environ, {"TEST_PRIVATE": PRIVATE, "PYTHONPATH": PRIVATE}):
            raw = self.run_code('import sys,os,json\n'
                'assert sys.argv[1:] == ["--json","status","fixture"]\n'
                'assert "TEST_PRIVATE" not in os.environ and "PYTHONPATH" not in os.environ\n'
                'assert sys.stdin.read() == ""\n'
                f'print(json.dumps({fixture()!r}))\n')
        self.assertEqual(raw["result"], "read_succeeded")

    def test_timeout_and_output_limit(self):
        for code, expected in (("import time\ntime.sleep(10)", "timeout"),
                              ("import os\nos.close(1)\nimport time\ntime.sleep(10)", "timeout"),
                              ("import os\nwhile True: os.write(1,b'x'*8192)", "output_limit")):
            with patch.object(security, "TIMEOUT", 0.15), self.assertRaises(security.ReadError) as caught:
                self.run_code(code)
            self.assertEqual(caught.exception.code, expected)

    def test_malformed_output_nonzero_and_cli_error(self):
        for code, expected in (("print('not json')", "invalid_output"),
                ("print('[]')", "invalid_output"),
                (f"import sys\nprint({json.dumps(fixture())!r})\nsys.exit(2)", "worker_failed"),
                ('import sys\nprint(\'{"result":"error","reason":"authentication_failed"}\')\nsys.exit(2)', "authentication_failed")):
            with self.assertRaises(security.ReadError) as caught:
                self.run_code(code)
            self.assertEqual(caught.exception.code, expected)

    def test_missing_executable_and_stderr_never_leak(self):
        with self.assertRaises(security.ReadError) as caught:
            security.run_cli(self.cli, "fixture")
        self.assertEqual(caught.exception.code, "network_or_local_io_error")
        with self.assertRaises(security.ReadError) as caught:
            self.run_code(f"import sys\nprint({PRIVATE!r},file=sys.stderr)\nsys.exit(2)")
        self.assertNotIn(PRIVATE, str(caught.exception))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.read = Mock(return_value=(200, {"ok": True, "securityAssessment": "not_assessed"}))
        for target, name, value in ((daemon, "API_TOKEN", "fixture-api-token"),
                (daemon, "AUTH_MODE", "trusted-network"), (daemon, "SECURITY_CLI", "/private/security"),
                (daemon, "ALLOWED_ORIGINS", set()), (security, "read_status", self.read)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.messages = []
        log = patch.object(daemon.Handler, "log_message", lambda handler, fmt, *args: self.messages.append(fmt % args))
        log.start()
        self.addCleanup(log.stop)
        self.server = ControlHTTPServer(("127.0.0.1", 0), daemon.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, query="device=fixture", token="fixture-api-token", method="GET", origin=None):
        headers = {"x-jarvis-token": token}
        if origin:
            headers["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, "/api/v1/security/status?" + query, headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            conn.close()

    def test_one_authenticated_on_demand_read_and_no_store(self):
        self.read.assert_not_called()
        status, body, headers = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.read.assert_called_once_with("/private/security", "fixture")
        self.assertNotIn("fixture", " ".join(self.messages))

    def test_missing_bad_and_event_tokens_rejected_even_on_trusted_network(self):
        with patch.object(daemon, "EVENT_TOKEN", "fixture-event-token"):
            for token in ("", "wrong", "fixture-event-token"):
                self.assertEqual(self.request(token=token)[0], 401)
        self.read.assert_not_called()

    def test_unconfigured_api_token_and_bad_origin_cannot_read(self):
        with patch.object(daemon, "API_TOKEN", ""):
            self.assertEqual(self.request()[0], 401)
        self.assertEqual(self.request(origin="https://untrusted.example")[0], 403)
        self.read.assert_not_called()

    def test_query_cannot_select_commands_paths_or_multiple_devices(self):
        for query in ("", "device=one&device=two", "device=fixture&command=set", "env=/private",
                      "device=fixture&env-file=/private", "device=fixture&extra="):
            self.assertEqual(self.request(query=query)[0], 400)
        self.read.assert_not_called()

    def test_post_never_calls_reader(self):
        self.assertNotEqual(self.request(method="POST")[0], 200)
        self.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
