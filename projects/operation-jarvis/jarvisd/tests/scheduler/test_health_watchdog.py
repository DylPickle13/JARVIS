"""Offline health-card, incident and scheduler tests; no live backend/APNs calls."""
from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

if __package__:
    from .test_runner import load_runner
    from .test_health_card import healthy, NOW
else:
    from test_runner import load_runner
    from test_health_card import healthy, NOW

BACKEND = Path(__file__).resolve().parents[2] / "jarvisd_core/scheduler"


def load_watchdog():
    name = f"jarvis_health_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, BACKEND / "health_watchdog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with patch.object(sys, "path", [str(BACKEND), *sys.path]):
        spec.loader.exec_module(module)
    return module


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.watchdog = load_watchdog()
        self.connection = Mock()
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.length = 0
        self.response.read.return_value = json.dumps(healthy()).encode()
        env = patch.dict(self.watchdog.os.environ, {"JARVIS_API_TOKEN": "test-token"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        clock = patch.object(self.watchdog.time, "time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.factory = patch.object(self.watchdog.http.client, "HTTPConnection", return_value=self.connection)
        self.http = self.factory.start()
        self.addCleanup(self.factory.stop)

    def test_healthy_request_is_fixed_local_bounded_and_does_not_use_proxies(self):
        self.assertIsNone(self.watchdog.probe())
        self.http.assert_called_once_with("127.0.0.1", 8790, timeout=5.0)
        self.connection.request.assert_called_once_with("GET", "/api/v1/health",
            headers={"Accept": "application/json", "Connection": "close", "x-jarvis-token": "test-token"})
        self.response.read.assert_called_once_with(128 * 1024 + 1)
        self.connection.close.assert_called_once()

    def test_auth_is_required_without_secret_echo_and_trusted_mode_is_explicit(self):
        for token in ("", "PRIVATE\r\nInjected: header", "x" * 4097, "\u2603"):
            with self.subTest(token_length=len(token)), patch.dict(self.watchdog.os.environ,
                    {"JARVIS_API_TOKEN": token}, clear=True):
                result = self.watchdog.probe()
                self.assertIn("authentication", result)
                self.assertNotIn("PRIVATE", result)
        self.http.assert_not_called()
        with patch.dict(self.watchdog.os.environ, {"JARVISD_AUTH_MODE": "trusted-network"}, clear=True):
            self.assertIsNone(self.watchdog.probe())
        self.connection.request.assert_called_once_with("GET", "/api/v1/health",
            headers={"Accept": "application/json", "Connection": "close"})

    def test_http_200_sensor_failure_and_device_only_failure_are_not_healthy(self):
        value = healthy()
        value["health"]["components"]["security"]["state"] = "unavailable"
        self.response.read.return_value = json.dumps(value).encode()
        self.assertIn("sensor reads", self.watchdog.probe())
        value = healthy()
        next(row for row in value["deviceHealth"]["devices"] if row["id"] == "sensor-reader")["state"] = "unavailable"
        self.response.read.return_value = json.dumps(value).encode()
        self.assertIn("sensor reader", self.watchdog.probe())

    def test_http_failures_and_redirects_are_not_followed(self):
        for status in (301, 401, 404, 500, 503):
            with self.subTest(status=status):
                self.response.status = status
                self.assertEqual(self.watchdog.probe(), f"HTTP {status}")
        self.assertEqual(self.http.call_count, 5)
        self.response.read.assert_not_called()

    def test_invalid_and_oversized_responses_never_include_response_text(self):
        for body, reason in [(b'not JSON: PRIVATE', "invalid JSON"),
                             (b'\xff', "invalid JSON"),
                             (b'{}', "health request not successful"), (b'[]', "health request not successful"),
                             (b'{"ok": 1}', "health request not successful"),
                             (b'{"ok": false, "error": "PRIVATE"}', "health request not successful"),
                             (b'{"ok": true}', "health summary unavailable"),
                             (b'x' * (128 * 1024 + 1), "response too large")]:
            with self.subTest(reason=reason, body=body[:40]):
                self.response.read.return_value = body
                self.assertEqual(self.watchdog.probe(), reason)

    def test_truncated_content_length_is_not_healthy_and_response_is_closed(self):
        self.response.length = 100
        self.assertEqual(self.watchdog.probe(), "incomplete response")
        self.response.close.assert_called_once()

    def test_connection_failures_and_timeouts_are_observations_not_exceptions(self):
        for error, reason in [(ConnectionRefusedError("PRIVATE"), "connection refused"),
                              (TimeoutError("PRIVATE"), "timeout"),
                              (OSError("PRIVATE"), "connection error")]:
            with self.subTest(reason=reason):
                self.connection.connect.side_effect = error
                self.assertEqual(self.watchdog.probe(), reason)
        self.assertEqual(self.connection.close.call_count, 3)

    def test_expired_deadline_cannot_return_a_late_healthy_response(self):
        def timer(_delay, callback):
            result = Mock()
            result.start.side_effect = callback
            return result
        with patch.object(self.watchdog.threading, "Timer", side_effect=timer):
            self.assertEqual(self.watchdog.probe(), "timeout")
        self.connection.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)


class DeadlineTests(unittest.TestCase):
    def test_slow_trickling_headers_and_body_have_total_deadline(self):
        # Isolated ephemeral loopback fixture, never the live service port.
        watchdog = load_watchdog()
        env = patch.dict(watchdog.os.environ, {"JARVIS_API_TOKEN": "test-token"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        for prefix in (b"", b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n"):
            with self.subTest(body=bool(prefix)), closing(socket.socket()) as server:
                server.bind(("127.0.0.1", 0))
                server.listen(1)
                server.settimeout(2)
                stopped = threading.Event()

                def serve():
                    try:
                        client, _ = server.accept()
                        with client:
                            if prefix:
                                client.sendall(prefix)
                            while not stopped.wait(0.02):
                                client.sendall(b"x")
                    except OSError:
                        pass

                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                try:
                    with patch.object(watchdog, "PORT", server.getsockname()[1]), \
                         patch.object(watchdog, "PROBE_TIMEOUT_SECONDS", 0.2):
                        started = time.monotonic()
                        self.assertEqual(watchdog.probe(), "timeout")
                        self.assertLess(time.monotonic() - started, 1.0)
                finally:
                    stopped.set()
                    thread.join(2)
                self.assertFalse(thread.is_alive())


class StateTests(unittest.TestCase):
    def setUp(self):
        self.watchdog = load_watchdog()

    def fail(self, state, seconds, *, wall=None, monotonic=None):
        return self.watchdog.observe(state, "timeout",
            wall=1000000 + seconds if wall is None else wall,
            monotonic=10000 + seconds if monotonic is None else monotonic)

    def test_threshold_is_elapsed_time_not_five_polls(self):
        state = self.watchdog.State()
        for seconds in range(6):
            state, output = self.fail(state, seconds)
            self.assertEqual(output, "")
        # A separate continuous sequence needs only four observations at 100s.
        state = self.watchdog.State()
        for seconds in (0, 100, 200):
            state, output = self.fail(state, seconds)
            self.assertEqual(output, "")
        state, output = self.fail(state, 300)
        self.assertIn("at least 5 minutes", output)
        self.assertTrue(state.alerted)

    def test_gaps_clock_jumps_and_monotonic_reset_rearm_pending_timer(self):
        for wall, monotonic in [(1000600, 10600), (1000360, 10060),
                                (999990, 10060), (1000060, 20),
                                (1000060, 10360)]:
            with self.subTest(wall=wall, monotonic=monotonic):
                state, _ = self.fail(self.watchdog.State(), 0)
                state, output = self.fail(state, 0, wall=wall, monotonic=monotonic)
                self.assertEqual(output, "")
                self.assertEqual(state.first_failure_wall, wall)
                self.assertEqual(state.first_failure_monotonic, monotonic)

    def test_alerted_incident_survives_monitor_gap_and_restart_without_realert(self):
        state = self.watchdog.State()
        for seconds in (0, 100, 200, 300):
            state, _ = self.fail(state, seconds)
        state = self.watchdog.State.decode(state.encode())
        state, output = self.fail(state, 600, monotonic=10)
        self.assertTrue(state.alerted)
        self.assertEqual(output, "")
        state, output = self.watchdog.observe(state, None, wall=1000660, monotonic=70)
        self.assertIn("healthy again", output)
        self.assertFalse(state.alerted)

    def test_state_roundtrip_and_invalid_state_never_silently_clear_alert_latch(self):
        state, _ = self.fail(self.watchdog.State(), 0)
        self.assertEqual(self.watchdog.State.decode(state.encode()), state)
        self.assertEqual(self.watchdog.State.decode(None), self.watchdog.State())
        data = json.loads(state.encode())
        for raw in ("not JSON", "null", "{}", json.dumps(data | {"version": 2}),
                    json.dumps(data | {"version": True}),
                    json.dumps(data | {"last_error": None}),
                    json.dumps(data | {"last_monotonic": -1}),
                    json.dumps(data | {"last_wall": float("nan")}),
                    json.dumps(data | {"alerted": "false"}),
                    json.dumps(data | {"first_failure_wall": None}),
                    json.dumps(data | {"first_failure_monotonic": 99999})):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "state is invalid"):
                self.watchdog.State.decode(raw)

    def test_exclusive_lock_skips_overlap_and_is_private_and_reusable(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "check.lock"
            with self.watchdog.exclusive_check(path) as first:
                self.assertTrue(first)
                with self.watchdog.exclusive_check(path) as second:
                    self.assertFalse(second)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.watchdog.exclusive_check(path) as third:
                self.assertTrue(third)

    def test_lock_releases_on_exception_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "check.lock"
            with self.assertRaises(RuntimeError), self.watchdog.exclusive_check(path):
                raise RuntimeError("fixture")
            with self.watchdog.exclusive_check(path) as acquired:
                self.assertTrue(acquired)
            alias = Path(raw) / "alias"
            alias.symlink_to(path)
            with self.assertRaises(OSError), self.watchdog.exclusive_check(alias):
                pass


class SchedulerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner = load_runner(Path(self.temp.name))
        self.watchdog = load_watchdog()
        self.module_patch = patch.dict(sys.modules, {"health_watchdog": self.watchdog})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.runner.APNS_PROVIDER_ENABLED = True
        self.job_id = self.runner.add_job(argparse.Namespace(
            job_id="job_health_test", name="jarvisd-health", schedule="1m", kind="interval",
            prompt="fixed local health check", model=self.runner.JARVISD_HEALTH_MODEL,
            description="test", category="Maintenance"))["job"]["id"]
        with closing(self.runner.connect()) as conn, conn:
            self.runner._set_config_value(conn, "apns_dispatch_enabled", "1")
        for platform in ("iphone", "watch"):
            self.runner.register_notification_device({
                "protocolVersion": 1, "action": "register", "platform": platform,
                "environment": self.runner.APNS_ENVIRONMENT,
                "installationID": str(uuid.uuid4()), "deviceToken": "ab" * 32,
            })

    def run_check(self, seconds, error="timeout"):
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (self.job_id,)).fetchone()
            with patch.object(self.watchdog, "probe", return_value=error), \
                 patch.object(self.watchdog.time, "time", return_value=1000000 + seconds), \
                 patch.object(self.watchdog.time, "monotonic", return_value=10000 + seconds), \
                 patch.object(self.runner, "build_pi_command", side_effect=AssertionError("No LLM")), \
                 patch.object(self.runner.subprocess, "run", side_effect=AssertionError("No subprocess")):
                return self.runner.run_pi_for_job(conn, job)

    def counts(self):
        with closing(self.runner.connect()) as conn:
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("results", "notification_outbox", "notification_deliveries"))

    def state(self):
        with closing(self.runner.connect()) as conn:
            raw = self.runner._config_value(conn, f"jarvisd-health:{self.job_id}")
        return self.watchdog.State.decode(raw)

    def test_healthy_and_short_failures_are_silent_successful_checks(self):
        for seconds, error in [(0, None), (60, "timeout"), (120, "HTTP 503"), (180, None)]:
            run = self.run_check(seconds, error)
            self.assertEqual(run["status"], "success")
            self.assertTrue(run["silent"])
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertIsNone(self.state().first_failure_wall)
        with closing(self.runner.connect()) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (self.job_id,)).fetchone()
        self.assertEqual(job["run_count"], 4)
        self.assertEqual(job["consecutive_errors"], 0)
        self.assertIsNotNone(job["last_silent_success_at"])

    def test_http_success_unhealthy_card_commits_one_alert_and_one_recovery(self):
        value = healthy()
        value["health"]["components"]["security"]["state"] = "unavailable"
        reason = self.watchdog.evaluate(value, now=NOW)
        for seconds in (0, 60, 120, 180, 240):
            self.assertTrue(self.run_check(seconds, reason)["silent"])
        self.assertFalse(self.run_check(300, reason)["silent"])
        self.assertEqual(self.counts(), (1, 1, 2))
        # A different failure must not cause a duplicate overall incident alert.
        self.assertTrue(self.run_check(360, "health not healthy/current: sensor reader")["silent"])
        self.assertFalse(self.run_check(420, self.watchdog.evaluate(healthy(), now=NOW))["silent"])
        self.assertEqual(self.counts(), (2, 2, 4))
        self.assertTrue(self.run_check(480, None)["silent"])

    def test_outage_alerts_once_then_recovery_once_and_rearms(self):
        for seconds in (0, 60, 120, 180, 240, 299):
            self.assertTrue(self.run_check(seconds)["silent"])
        self.assertFalse(self.run_check(300)["silent"])
        self.assertTrue(self.run_check(360)["silent"])
        self.assertEqual(self.counts(), (1, 1, 2))
        self.assertFalse(self.run_check(420, None)["silent"])
        self.assertTrue(self.run_check(480, None)["silent"])
        self.assertEqual(self.counts(), (2, 2, 4))
        for seconds in (540, 600, 660, 720, 780):
            self.assertTrue(self.run_check(seconds)["silent"])
        self.assertFalse(self.run_check(840)["silent"])
        self.assertEqual(self.counts(), (3, 3, 6))
        with closing(self.runner.connect()) as conn:
            output = [row[0] for row in conn.execute("SELECT output FROM results ORDER BY sequence")]
        self.assertIn("at least 5 minutes", output[0])
        self.assertEqual(output[1], "jarvisd System health is healthy again.")

    def test_fresh_runner_keeps_incident_and_does_not_repeat_alert(self):
        for seconds in (0, 100, 200, 300):
            self.run_check(seconds)
        self.runner = load_runner(Path(self.temp.name))
        self.runner.APNS_PROVIDER_ENABLED = True
        self.assertTrue(self.run_check(360)["silent"])
        self.assertEqual(self.counts(), (1, 1, 2))

    def test_overlap_skips_without_probing_or_changing_state(self):
        self.run_check(0)
        before = self.state()
        with self.watchdog.exclusive_check(self.runner.DB_PATH.parent / "jarvisd-health.lock"):
            result = self.run_check(60)
        self.assertTrue(result["skipped"])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_incident_state_result_and_outbox_commit_or_rollback_together(self):
        for seconds in (0, 100, 200):
            self.run_check(seconds)
        before = self.state()
        original = self.runner.enqueue_notification_for_result

        def fail_after_enqueue(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated persistence failure")

        with patch.object(self.runner, "enqueue_notification_for_result", side_effect=fail_after_enqueue):
            with self.assertRaisesRegex(RuntimeError, "persistence failure"):
                self.run_check(300)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertFalse(self.run_check(300)["silent"])
        self.assertTrue(self.state().alerted)
        self.assertEqual(self.counts(), (1, 1, 2))

    def test_disabled_dispatch_is_not_activated_or_replayed_when_reenabled(self):
        with closing(self.runner.connect()) as conn, conn:
            self.runner._set_config_value(conn, "apns_dispatch_enabled", "0")
        for seconds in (0, 100, 200, 300):
            self.run_check(seconds)
        self.assertEqual(self.counts(), (1, 0, 0))
        with closing(self.runner.connect()) as conn, conn:
            self.assertFalse(self.runner.notification_dispatch_enabled(conn))
            self.runner._set_config_value(conn, "apns_dispatch_enabled", "1")
        self.assertTrue(self.run_check(360)["silent"])
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_corrupt_state_is_checker_error_not_backend_outage_or_state_reset(self):
        key = f"jarvisd-health:{self.job_id}"
        with closing(self.runner.connect()) as conn, conn:
            self.runner._set_config_value(conn, key, "PRIVATE invalid state")
        run = self.run_check(0)
        self.assertEqual(run["status"], "error")
        self.assertNotIn("PRIVATE", run["result"]["error"])
        with closing(self.runner.connect()) as conn:
            self.assertEqual(self.runner._config_value(conn, key), "PRIVATE invalid state")


if __name__ == "__main__":
    unittest.main()
