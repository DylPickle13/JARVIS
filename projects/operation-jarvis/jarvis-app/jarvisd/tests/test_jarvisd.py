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
            spec_data = {
                "demo": {
                    "label": "com.example.demo",
                    "plist": str(Path(directory) / "demo.plist"),
                    "description": "test service",
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
        status, _, _ = self.request("GET", "/api/v1/services", token="write-secret")
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="write-secret")
        self.assertEqual(status, 200)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="api-secret")
        self.assertEqual(status, 401)

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
