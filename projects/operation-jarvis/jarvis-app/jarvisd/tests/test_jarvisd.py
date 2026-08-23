import http.client
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "jarvisd.py"
spec = importlib.util.spec_from_file_location("jarvisd_under_test", MODULE_PATH)
jarvisd = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(jarvisd)


class FakeRequest:
    def __init__(self, address, headers=None):
        self.client_address = (address, 1234)
        self.headers = headers or {}

    def _client_ip(self):
        raw = self.client_address[0]
        return jarvisd.ipaddress.ip_address(raw)


class DaemonUnitTests(unittest.TestCase):
    def test_command_allowlist_rejects_non_string_and_shell_content(self):
        with self.assertRaises(jarvisd.CommandError):
            jarvisd.build_command(["status"], {})
        with self.assertRaises(jarvisd.CommandError):
            jarvisd.build_command("plug-status", {"plug": "lamp; rm -rf /"})
        self.assertEqual(
            jarvisd.build_command("plug-on", {"plug": "family-room-light"})[-2:],
            ["plug-on", "family-room-light"],
        )

    def test_read_collectors_disable_lifecycle_events(self):
        calls = []

        def fake_run(argv, timeout=20.0, env=None):
            calls.append((argv, timeout, env))
            if argv[-1] == "plug-list":
                return {"ok": True, "plugs": {}}
            return {"ok": True, "airPurifier": {"data": {}}}

        with mock.patch.object(jarvisd, "run_cli_json", side_effect=fake_run):
            self.assertTrue(jarvisd._plugs()["ok"])
            self.assertTrue(jarvisd._purifier()["ok"])

        self.assertEqual(len(calls), 2)
        for _argv, _timeout, env in calls:
            self.assertEqual(env, {"JARVIS_EMIT_EVENTS": "0"})

    def test_default_state_contract_excludes_weather(self):
        coordinator = jarvisd.StateCoordinator()
        self.assertNotIn("weather", coordinator.collectors)
        self.assertNotIn("weather", coordinator.DEFAULT_INTERVALS)
        self.assertIn("codexQuota", coordinator.collectors)
        self.assertEqual(coordinator.DEFAULT_INTERVALS["codexQuota"], 300.0)

    def test_codex_quota_failure_does_not_stale_critical_state(self):
        coordinator = jarvisd.StateCoordinator(
            collectors={"core": lambda: {"ok": True}, "codexQuota": jarvisd._codex_quota},
            now=lambda: 100,
        )
        coordinator._records["core"].update({
            "data": {"ok": True, "value": 1},
            "updatedAt": "2026-08-23T17:26:07Z",
            "lastGoodAt": 100,
            "stale": False,
        })
        with mock.patch.object(coordinator, "start"):
            snapshot = coordinator.snapshot()
        self.assertFalse(snapshot["loading"])
        self.assertFalse(snapshot["stale"])
        self.assertTrue(snapshot["subsystems"]["codexQuota"]["stale"])

    def test_codex_quota_contract_is_bounded_and_sanitized(self):
        result = jarvisd._public_codex_quota({
            "ok": True,
            "checked_at": "2026-08-23T17:26:07Z",
            "private_account": "must-not-leak",
            "usage": {
                "plan_type": "prolite",
                "allowed": True,
                "effective_limit_reached": False,
                "weekly": {
                    "used_percent": 69,
                    "remaining_percent": 31,
                    "reset_after_seconds": 360706,
                    "reset_at": 1787866671,
                    "private": "must-not-leak",
                },
                "five_hour": None,
                "primary_limit": {"enforced": False, "status": "temporarily_suspended", "source": "private"},
                "credits": {"balance": "1887.2380505000", "private": "must-not-leak"},
            },
            "models": {"models": [{"id": "private-model"}]},
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["available"])
        self.assertEqual(result["weekly"]["remainingPercent"], 31.0)
        self.assertEqual(result["weekly"]["resetAt"], "2026-08-27T21:37:51Z")
        self.assertEqual(result["creditBalance"], 1887.24)
        encoded = json.dumps(result)
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn("private-model", encoded)
        self.assertNotIn("source", encoded)

    def test_codex_quota_collector_uses_read_only_fixed_command_and_fails_noncritical(self):
        payload = {
            "ok": True,
            "checked_at": "2026-08-23T17:26:07Z",
            "usage": {"weekly": {"remaining_percent": 31}},
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="private stderr")
        with mock.patch.object(jarvisd, "CODEX_QUOTAS_SCRIPT", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            result = jarvisd._codex_quota()
        self.assertTrue(result["available"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], ["codex", "--json"])
        self.assertNotIn("--probe", argv)
        self.assertNotIn("--save", argv)

        completed.returncode = 2
        completed.stdout = "private provider response"
        with mock.patch.object(jarvisd, "CODEX_QUOTAS_SCRIPT", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed):
            unavailable = jarvisd._codex_quota()
        self.assertFalse(unavailable["ok"])
        self.assertFalse(unavailable["available"])
        self.assertNotIn("private provider response", json.dumps(unavailable))

    def test_tailscale_ip_reads_network_extension_interface(self):
        completed = mock.Mock(
            stdout="utun11: flags=8051<UP,POINTOPOINT,RUNNING> mtu 1280\n"
                   "\tinet 100.87.28.34 --> 100.87.28.34 netmask 0xffffffff\n"
        )
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(jarvisd, "TAILSCALE_SOCKET", Path(directory) / "missing.sock"), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            self.assertEqual(jarvisd._tailscale_ip(), "100.87.28.34")
        run.assert_called_once_with(["/sbin/ifconfig"], capture_output=True, text=True, timeout=5)

    def test_tailscale_ip_uses_signed_macos_app_cli(self):
        ifconfig = mock.Mock(stdout="utun0: flags=8051<UP> mtu 1380\n")
        app_cli = mock.Mock(stdout="100.87.28.34\n")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(jarvisd, "TAILSCALE_SOCKET", Path(directory) / "missing.sock"), \
             mock.patch.object(jarvisd, "TAILSCALE_APP_CLI", Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")), \
             mock.patch.object(jarvisd.subprocess, "run", side_effect=[ifconfig, app_cli]) as run:
            self.assertEqual(jarvisd._tailscale_ip(), "100.87.28.34")
        self.assertEqual(
            run.call_args.args[0],
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "ip", "-4"],
        )

    def test_public_command_result_filters_adapter_internals(self):
        result = jarvisd._public_command_result(
            "plug-on",
            {
                "ok": True,
                "operationRoot": "/Users/example/private",
                "summary": "lamp is on",
                "plug": {
                    "name": "lamp",
                    "is_on": True,
                    "host": "192.168.1.10",
                    "alias": "Lamp",
                    "mac": "private-mac",
                },
                "smartPlug": {"command": ["/Users/example/private/tool"]},
            },
        )
        self.assertEqual(result["plug"]["is_on"], True)
        encoded = json.dumps(result)
        self.assertNotIn("operationRoot", encoded)
        self.assertNotIn("smartPlug", encoded)
        self.assertNotIn("private-mac", encoded)
        self.assertNotIn("/Users/", encoded)

        purifier = jarvisd._public_command_result(
            "purifier-status",
            {
                "ok": True,
                "airPurifier": {
                    "command": ["/Users/example/private/purifier-cli"],
                    "data": {"name": "Air Purifier", "mode": "auto", "cid": "private-cid"},
                },
            },
        )
        encoded = json.dumps(purifier)
        self.assertEqual(purifier["airPurifier"]["data"]["mode"], "auto")
        self.assertNotIn("private-cid", encoded)
        self.assertNotIn("/Users/", encoded)

    def test_command_results_update_cached_state_immediately(self):
        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": lambda: {"ok": True}, "purifier": lambda: {"ok": True}}
        )
        with mock.patch.object(coordinator, "start"):
            self.assertTrue(
                coordinator.apply_plug_result(
                    {"name": "lamp", "is_on": True, "host": "192.168.1.10", "alias": "Lamp"}
                )
            )
            snapshot = coordinator.snapshot()
            self.assertTrue(snapshot["subsystems"]["plugs"]["plugs"]["lamp"]["isOn"])
            self.assertFalse(snapshot["subsystems"]["plugs"]["stale"])

            self.assertTrue(
                coordinator.apply_purifier_result(
                    {"is_on": True, "power": "on", "mode": "manual", "fan_set_level": 2}
                )
            )
            snapshot = coordinator.snapshot()
            self.assertEqual(snapshot["subsystems"]["purifier"]["mode"], "manual")
            self.assertEqual(snapshot["subsystems"]["purifier"]["fanSetLevel"], 2)

    def test_pending_purifier_write_stays_stale_until_expected_state(self):
        coordinator = jarvisd.StateCoordinator(collectors={"purifier": lambda: {"ok": True}})
        with mock.patch.object(coordinator, "start"):
            self.assertTrue(
                coordinator.apply_purifier_result(
                    {"is_on": True, "mode": "auto", "verification_pending": True},
                    {"isOn": False},
                )
            )
            snapshot = coordinator.snapshot()
            self.assertTrue(snapshot["subsystems"]["purifier"]["stale"])
            revision = coordinator._records["purifier"]["revision"]

            old_future = jarvisd.concurrent.futures.Future()
            old_future.set_result({"ok": True, "isOn": True, "mode": "auto"})
            coordinator._complete("purifier", old_future, revision)
            self.assertTrue(coordinator.snapshot()["subsystems"]["purifier"]["stale"])

            verified_future = jarvisd.concurrent.futures.Future()
            verified_future.set_result({"ok": True, "isOn": False, "mode": "manual"})
            coordinator._complete("purifier", verified_future, revision)
            verified = coordinator.snapshot()["subsystems"]["purifier"]
            self.assertFalse(verified["stale"])
            self.assertFalse(verified["isOn"])

        self.assertEqual(jarvisd._purifier_expectation({"setting": "mode", "value": "manual"}), {"mode": "manual"})
        self.assertEqual(jarvisd._purifier_expectation({"setting": "speed", "level": 2.0}), {"mode": "manual", "fanLevel": 2})

    def test_event_bridge_targets_only_jarvisd_and_uses_neutral_controls(self):
        adapter_path = Path(__file__).resolve().parents[3] / "jarvis.py"
        adapter_spec = importlib.util.spec_from_file_location("operation_jarvis_adapter", adapter_path)
        adapter = importlib.util.module_from_spec(adapter_spec)
        assert adapter_spec.loader is not None
        adapter_spec.loader.exec_module(adapter)

        with mock.patch.dict(
            os.environ,
            {
                "JARVISD_URL": "http://jarvisd.test:8790",
                "JARVISD_EVENT_TOKEN": "event-secret",
                "JARVIS_EMIT_EVENTS": "1",
            },
            clear=False,
        ):
            self.assertTrue(adapter.events_enabled())
            self.assertEqual(
                adapter._event_targets(),
                [("http://jarvisd.test:8790", "event-secret")],
            )
            with mock.patch.object(adapter, "urlopen") as opener:
                opener.return_value.__enter__.return_value = mock.Mock()
                adapter.emit_event("action.complete", action="plug-on", ok=True, summary="ok")
                self.assertEqual(opener.call_count, 1)
                request = opener.call_args.args[0]
                self.assertEqual(request.full_url, "http://jarvisd.test:8790/api/jarvis/events")

    def test_event_validation_and_bounded_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            store = jarvisd.EventStore(max_events=2, persist_path=path)
            first = store.add({"source": "test", "eventType": "one", "ok": True})
            store.add({"source": "test", "eventType": "two", "ok": True})
            third = store.add({"source": "test", "eventType": "three", "ok": False})
            self.assertEqual([event["seq"] for event in store.list()], [2, 3])
            self.assertEqual(len(path.read_text().splitlines()), 2)
            restored = jarvisd.EventStore(max_events=2, persist_path=path)
            self.assertEqual([event["seq"] for event in restored.list()], [2, 3])
            self.assertEqual(third["seq"], 3)
            with self.assertRaises(jarvisd.EventInputError):
                store.add({"not_allowed": True})
            with self.assertRaises(jarvisd.EventInputError):
                store.add({"source": "test", "artifacts": [1] * 21})

    def test_authentication_modes(self):
        old_mode, old_api, old_event = jarvisd.AUTH_MODE, jarvisd.API_TOKEN, jarvisd.EVENT_TOKEN
        old_cidrs = jarvisd.TRUSTED_CIDRS_RAW
        try:
            jarvisd.AUTH_MODE = "trusted-network"
            jarvisd.TRUSTED_CIDRS_RAW = "127.0.0.0/8,192.168.21.0/24"
            self.assertTrue(jarvisd.Handler._authorized(FakeRequest("127.0.0.1"), "api"))
            self.assertTrue(jarvisd.Handler._authorized(FakeRequest("192.168.21.42"), "api"))
            self.assertFalse(jarvisd.Handler._authorized(FakeRequest("8.8.8.8"), "api"))

            jarvisd.AUTH_MODE = "token"
            jarvisd.API_TOKEN = "api-secret"
            jarvisd.EVENT_TOKEN = "write-secret"
            self.assertFalse(jarvisd.Handler._authorized(FakeRequest("127.0.0.1"), "api"))
            self.assertTrue(jarvisd.Handler._authorized(FakeRequest("8.8.8.8", {"x-jarvis-token": "api-secret"}), "api"))
            self.assertFalse(jarvisd.Handler._authorized(FakeRequest("8.8.8.8", {"x-jarvis-token": "write-secret"}), "api"))
            self.assertTrue(jarvisd.Handler._authorized(FakeRequest("8.8.8.8", {"x-jarvis-token": "write-secret"}), "events"))
            self.assertFalse(jarvisd.Handler._authorized(FakeRequest("8.8.8.8", {"x-jarvis-token": "api-secret"}), "events"))
        finally:
            jarvisd.AUTH_MODE, jarvisd.API_TOKEN, jarvisd.EVENT_TOKEN = old_mode, old_api, old_event
            jarvisd.TRUSTED_CIDRS_RAW = old_cidrs

    def test_state_coordinator_is_single_flight_and_preserves_last_good(self):
        started = threading.Event()
        release = threading.Event()
        calls = 0

        def collector():
            nonlocal calls
            calls += 1
            started.set()
            release.wait(2)
            return {"ok": True, "value": calls}

        coordinator = jarvisd.StateCoordinator(
            collectors={"test": collector}, intervals={"test": 60}, now=time.time
        )
        try:
            coordinator.start()
            self.assertTrue(started.wait(1))
            for _ in range(10):
                coordinator.snapshot()
            self.assertEqual(calls, 1)
            release.set()
            deadline = time.time() + 2
            snapshot = coordinator.snapshot()
            while snapshot["subsystems"]["test"].get("value") != 1 and time.time() < deadline:
                time.sleep(0.02)
                snapshot = coordinator.snapshot()
            self.assertEqual(snapshot["subsystems"]["test"]["value"], 1)
            self.assertFalse(snapshot["subsystems"]["test"]["stale"])
        finally:
            coordinator.stop()

    def test_state_coordinator_keeps_last_good_on_failure(self):
        results = iter([{"ok": True, "value": 7}, {"ok": False, "error": "temporary"}])
        coordinator = jarvisd.StateCoordinator(
            collectors={"test": lambda: next(results)}, intervals={"test": 0.01}
        )
        try:
            coordinator.start()
            deadline = time.time() + 2
            first = coordinator.snapshot()
            while first["subsystems"]["test"].get("value") != 7 and time.time() < deadline:
                time.sleep(0.02)
                first = coordinator.snapshot()
            self.assertEqual(first["subsystems"]["test"]["value"], 7)
            deadline = time.time() + 2
            second = first
            while (not second["subsystems"]["test"].get("stale")) and time.time() < deadline:
                time.sleep(0.02)
                second = coordinator.snapshot()
            self.assertEqual(second["subsystems"]["test"]["value"], 7)
            self.assertTrue(second["subsystems"]["test"]["stale"])
            self.assertEqual(second["subsystems"]["test"]["lastError"], "temporary")
        finally:
            coordinator.stop()

    def test_service_start_bootstraps_unloaded_agent(self):
        old_events = jarvisd.EVENTS
        with tempfile.TemporaryDirectory() as directory:
            jarvisd.EVENTS = jarvisd.EventStore()
            old_launch_dir = jarvisd.LAUNCH_AGENTS_DIR
            jarvisd.LAUNCH_AGENTS_DIR = Path(directory).resolve()
            demo_plist = Path(directory) / "demo.plist"
            demo_plist.touch()
            spec_data = {
                "demo": {
                    "label": "com.example.demo",
                    "plist": str(demo_plist),
                    "description": "test service",
                    "allowedActions": ["start", "stop", "restart"],
                }
            }
            commands = []
            with mock.patch.object(jarvisd, "_load_services", return_value=spec_data), \
                 mock.patch.object(jarvisd, "_service_status", return_value={"ok": True, "loaded": False, "running": False, "pid": None}), \
                 mock.patch.object(jarvisd, "_run_launchctl", side_effect=lambda argv, timeout=15: commands.append(argv) or mock.Mock(returncode=0, stderr="", stdout="")), \
                 mock.patch.object(jarvisd, "_wait_for_service", return_value={"ok": True, "loaded": True, "running": True, "pid": 22}):
                result = jarvisd._service_action("demo", "start")
            self.assertTrue(result["ok"])
            self.assertEqual(commands[0][0], "bootstrap")
            self.assertEqual(commands[1][:2], ["kickstart", "-k"])
            jarvisd.LAUNCH_AGENTS_DIR = old_launch_dir
        jarvisd.EVENTS = old_events

    def test_service_cannot_control_jarvisd(self):
        with mock.patch.object(jarvisd, "_load_services", return_value={"daemon": {"label": "com.operation-jarvis.jarvisd"}}):
            result = jarvisd._service_action("daemon", "stop")
        self.assertFalse(result["ok"])
        self.assertIn("protected", result["error"])

    def test_service_metadata_and_action_allowlist_are_server_enforced(self):
        old_events = jarvisd.EVENTS
        jarvisd.EVENTS = jarvisd.EventStore()
        spec_data = {
            "discord-bot": {
                "label": "com.operation-jarvis.discord-bot",
                "displayName": "JARVIS Discord Bot",
                "description": "Discord runtime",
                "sortOrder": 10,
                "critical": True,
                "allowedActions": [],
            }
        }
        try:
            with mock.patch.object(jarvisd, "_load_services", return_value=spec_data), \
                 mock.patch.object(
                     jarvisd,
                     "_run_launchctl",
                     side_effect=AssertionError("disallowed action reached launchctl"),
                 ):
                result = jarvisd._service_action("discord-bot", "restart")
            self.assertFalse(result["ok"])
            self.assertIn("not allowed", result["error"])
            events = jarvisd.EVENTS.list()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["eventType"], "service.action")

            proc = mock.Mock(returncode=0, stdout="state = running\npid = 123\n", stderr="")
            status = jarvisd._parse_launchctl_status("discord-bot", spec_data["discord-bot"], proc)
            self.assertEqual(status["displayName"], "JARVIS Discord Bot")
            self.assertEqual(status["sortOrder"], 10)
            self.assertTrue(status["critical"])
            self.assertEqual(status["allowedActions"], [])
            self.assertTrue(status["running"])
        finally:
            jarvisd.EVENTS = old_events

    def test_public_scheduled_jobs_recomputes_summary_and_filters_private_fields(self):
        result = jarvisd._public_scheduled_jobs({
            "ok": True,
            "summary": {"total": 999, "enabled": 999},
            "jobs": [{
                "id": "job_abc123",
                "name": "daily-job-search",
                "kind": "cron",
                "schedule": "0 9 * * *",
                "enabled": True,
                "nextRunAt": "2026-08-21T09:00:00Z",
                "lastRunAt": "2026-08-20T09:00:00Z",
                "lastStatus": "success",
                "runCount": 7,
                "description": "Daily search from /Users/example/private/source.md",
                "prompt": "private prompt",
                "model": "private model",
                "discord_thread_id": "private-thread",
                "path": "/Users/example/private",
            }],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"total": 1, "enabled": 1, "running": 0, "errors": 0})
        encoded = json.dumps(result)
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("private model", encoded)
        self.assertNotIn("private-thread", encoded)
        self.assertNotIn("/Users/", encoded)

    def test_scheduled_jobs_runner_is_fixed_bounded_and_fail_closed(self):
        payload = {
            "ok": True,
            "jobs": [{
                "id": "job_demo",
                "name": "demo",
                "kind": "interval",
                "schedule": "5m",
                "enabled": False,
                "nextRunAt": None,
                "lastRunAt": None,
                "lastStatus": None,
                "runCount": 0,
                "description": None,
            }],
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="private stderr")
        with mock.patch.object(jarvisd, "DISCORD_CRON_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            result = jarvisd._scheduled_jobs()
        self.assertTrue(result["ok"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], ["--json", "list-public"])
        self.assertNotIn("private stderr", json.dumps(result))

        completed.stdout = "not-json"
        with mock.patch.object(jarvisd, "DISCORD_CRON_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed):
            failed = jarvisd._scheduled_jobs()
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["jobs"], [])
        self.assertNotIn("not-json", json.dumps(failed))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.old = {
            "AUTH_MODE": jarvisd.AUTH_MODE,
            "API_TOKEN": jarvisd.API_TOKEN,
            "EVENT_TOKEN": jarvisd.EVENT_TOKEN,
            "EVENTS": jarvisd.EVENTS,
            "ALLOWED_ORIGINS": jarvisd.ALLOWED_ORIGINS,
        }
        jarvisd.AUTH_MODE = "token"
        jarvisd.API_TOKEN = "api-secret"
        jarvisd.EVENT_TOKEN = "write-secret"
        jarvisd.ALLOWED_ORIGINS = set()
        jarvisd.EVENTS = jarvisd.EventStore()
        self.server = jarvisd.ThreadingHTTPServer(("127.0.0.1", 0), jarvisd.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        for key, value in self.old.items():
            setattr(jarvisd, key, value)

    def request(self, method, path, body=None, token=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {}
        if token:
            headers["x-jarvis-token"] = token
        if origin:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
        else:
            encoded = None
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        connection.close()
        return result

    def test_token_scope_and_no_wildcard_cors(self):
        status, headers, _ = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")
        status, _, _ = self.request("GET", "/api/v1/services")
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/v1/scheduled-jobs")
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/v1/services", token="write-secret")
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="write-secret")
        self.assertEqual(status, 200)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="api-secret")
        self.assertEqual(status, 401)

    def test_scheduled_jobs_endpoint_returns_sanitized_contract(self):
        response = {
            "ok": True,
            "generatedAt": "2026-08-21T00:00:00Z",
            "summary": {"total": 1, "enabled": 1, "running": 0, "errors": 0},
            "jobs": [{
                "id": "job_demo",
                "name": "demo",
                "kind": "interval",
                "schedule": "5m",
                "enabled": True,
                "nextRunAt": None,
                "lastRunAt": None,
                "lastStatus": None,
                "runCount": 0,
                "description": None,
            }],
        }
        with mock.patch.object(jarvisd, "_scheduled_jobs", return_value=response):
            status, _, body = self.request("GET", "/api/v1/scheduled-jobs", token="api-secret")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["jobs"][0]["id"], "job_demo")

    def test_unsupported_methods_return_json_405(self):
        status, headers, body = self.request("PUT", "/api/v1/state")
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("Allow"), "GET, POST, OPTIONS")
        self.assertIn("method not allowed", body.decode())

    def test_invalid_json_and_shape_are_rejected(self):
        status, _, _ = self.request("POST", "/api/jarvis/events", b"not-json", token="write-secret")
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/jarvis/events", ["array"], token="write-secret")
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"unknown": True}, token="write-secret")
        self.assertEqual(status, 400)
        previous_limit = jarvisd.MAX_JSON_BODY_BYTES
        jarvisd.MAX_JSON_BODY_BYTES = 32
        try:
            status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "x" * 64}, token="write-secret")
            self.assertEqual(status, 413)
        finally:
            jarvisd.MAX_JSON_BODY_BYTES = previous_limit


if __name__ == "__main__":
    unittest.main()
