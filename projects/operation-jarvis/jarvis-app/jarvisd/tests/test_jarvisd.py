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
    def test_bounded_log_writer_rotates_and_keeps_private_permissions(self):
        with tempfile.TemporaryDirectory() as raw:
            log_path = Path(raw) / "private" / "jarvisd.log"
            writer = jarvisd.BoundedLogWriter(log_path, max_bytes=256, backup_count=2)
            try:
                for index in range(40):
                    writer.write(f"entry-{index:02d}-" + ("x" * 32) + "\n")
                writer.flush()
            finally:
                writer.close()

            logs = sorted(log_path.parent.glob("jarvisd.log*"))
            self.assertGreater(len(logs), 1)
            self.assertLessEqual(len(logs), 3)
            self.assertEqual(log_path.parent.stat().st_mode & 0o777, 0o700)
            for path in logs:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertLessEqual(path.stat().st_size, 256)
            self.assertIn("entry-39", log_path.read_text(encoding="utf-8"))

    def test_routine_request_log_gate_reports_suppressed_count(self):
        now = [100.0]
        gate = jarvisd.RoutineRequestLogGate(10, clock=lambda: now[0])

        self.assertEqual(gate.record("127.0.0.1", "/health"), (True, 0))
        self.assertEqual(gate.record("127.0.0.1", "/health"), (False, 0))
        self.assertEqual(gate.record("127.0.0.1", "/health"), (False, 0))
        now[0] += 10
        self.assertEqual(gate.record("127.0.0.1", "/health"), (True, 2))

    def test_request_logging_coalesces_only_plain_successful_reads(self):
        handler = object.__new__(jarvisd.Handler)
        handler.command = "GET"
        handler.path = "/health"
        handler.requestline = "GET /health HTTP/1.1"
        handler.client_address = ("127.0.0.1", 1234)
        messages = []
        handler.log_message = lambda fmt, *args: messages.append(fmt % args)
        gate = jarvisd.RoutineRequestLogGate(60, clock=lambda: 100.0)

        with mock.patch.object(jarvisd, "ROUTINE_REQUEST_LOG_GATE", gate):
            handler.log_request(200)
            handler.log_request(200)
            self.assertEqual(len(messages), 1)

            handler.path = "/api/v1/state?refresh=codexQuota"
            handler.requestline = "GET /api/v1/state?refresh=codexQuota HTTP/1.1"
            handler.log_request(200)
            self.assertEqual(len(messages), 2)

            handler.path = "/health"
            handler.requestline = "GET /health HTTP/1.1"
            handler.log_request(401)
            self.assertEqual(len(messages), 3)

            handler.command = "POST"
            handler.log_request(200)
            self.assertEqual(len(messages), 4)

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

    def test_explicit_project_root_wins_over_global_pi_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            source = home / "Library" / "artifact" / "source" / "jarvisd"
            project = home / "JARVIS"
            source.mkdir(parents=True)
            project.mkdir()
            (home / ".pi").mkdir()

            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("JARVISD_JARVIS_ROOT", None)
                resolved = jarvisd._resolve_jarvis_root(
                    source_dir=source,
                    project_root=project,
                    project_root_is_explicit=True,
                )
            self.assertEqual(resolved, project)

    def test_mobile_pi_session_states_use_fresh_lifecycle(self):
        now = jarvisd.dt.datetime(2026, 8, 31, 20, 0, tzinfo=jarvisd.dt.timezone.utc)
        completed = jarvisd.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "jarvis-ios\t0\t111\n"
                "jarvis-ios-2\t1\t222\n"
                "jarvis-ios-3\t0\t333\n"
                "jarvis-ios-4\t0\t444\n"
                "jarvis-ios-5\t0\t555\n"
                "jarvis-ios-6\t0\t666\n"
                "unrelated\t0\t777\n"
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as raw:
            status_dir = Path(raw)
            for pid, lifecycle in (
                (111, "running"),
                (222, "waiting"),
                (333, "idle"),
                (444, "waiting"),
                (555, "compacting"),
            ):
                (status_dir / f"{pid}-session.json").write_text(
                    json.dumps({
                        "version": 2,
                        "source": "pi-extension-local-session-status",
                        "pid": pid,
                        "lifecycle": lifecycle,
                        "updatedAt": now.isoformat().replace("+00:00", "Z"),
                    }),
                    encoding="utf-8",
                )
            with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir), \
                 mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
                states = jarvisd._mobile_pi_session_states(now=now)

        self.assertEqual(
            states,
            [
                {"sessionID": 1, "lifecycle": "running", "active": True},
                {"sessionID": 2, "lifecycle": "offline", "active": False},
                {"sessionID": 3, "lifecycle": "idle", "active": False},
                {"sessionID": 4, "lifecycle": "waiting", "active": True},
                {"sessionID": 5, "lifecycle": "compacting", "active": True},
                {"sessionID": 6, "lifecycle": "unknown", "active": None},
            ],
        )
        run.assert_called_once_with(
            [
                "/opt/homebrew/bin/tmux",
                "-L",
                "jarvis-mobile",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{pane_dead}\t#{pane_pid}",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

    def test_fresh_local_pi_lifecycle_accepts_v1_during_manual_reload_rollout(self):
        now = jarvisd.dt.datetime(2026, 8, 31, 20, 0, tzinfo=jarvisd.dt.timezone.utc)
        with tempfile.TemporaryDirectory() as raw:
            status_dir = Path(raw)
            for pid, active in ((111, True), (222, False)):
                (status_dir / f"{pid}-session.json").write_text(
                    json.dumps({
                        "version": 1,
                        "source": "pi-extension-local-session-status",
                        "pid": pid,
                        "active": active,
                        "updatedAt": now.isoformat().replace("+00:00", "Z"),
                    }),
                    encoding="utf-8",
                )
            (status_dir / "333-session.json").write_text(
                json.dumps({
                    "version": 2,
                    "source": "pi-extension-local-session-status",
                    "pid": 333,
                    "lifecycle": "invented",
                    "updatedAt": now.isoformat().replace("+00:00", "Z"),
                }),
                encoding="utf-8",
            )
            with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir):
                self.assertEqual(jarvisd._fresh_local_pi_lifecycle(111, now=now), "running")
                self.assertEqual(jarvisd._fresh_local_pi_lifecycle(222, now=now), "idle")
                self.assertIsNone(jarvisd._fresh_local_pi_lifecycle(333, now=now))

    def test_mobile_pi_session_states_fail_closed_for_stale_or_missing_activity(self):
        now = jarvisd.dt.datetime(2026, 8, 31, 20, 0, tzinfo=jarvisd.dt.timezone.utc)
        completed = jarvisd.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="jarvis-ios\t0\t111\njarvis-ios-3\t0\t333\njarvis-ios-6\t0\t666\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as raw:
            status_dir = Path(raw)
            stale = now - jarvisd.dt.timedelta(seconds=jarvisd.MOBILE_PI_STATUS_MAX_AGE_SECONDS + 1)
            (status_dir / "111-session.json").write_text(
                json.dumps({
                    "version": 2,
                    "source": "pi-extension-local-session-status",
                    "pid": 111,
                    "lifecycle": "running",
                    "updatedAt": stale.isoformat().replace("+00:00", "Z"),
                }),
                encoding="utf-8",
            )
            with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir), \
                 mock.patch.object(jarvisd.subprocess, "run", return_value=completed):
                self.assertEqual(
                    jarvisd._mobile_pi_session_states(now=now),
                    [
                        {"sessionID": 1, "lifecycle": "unknown", "active": None},
                        {"sessionID": 2, "lifecycle": "offline", "active": False},
                        {"sessionID": 3, "lifecycle": "unknown", "active": None},
                        {"sessionID": 4, "lifecycle": "offline", "active": False},
                        {"sessionID": 5, "lifecycle": "offline", "active": False},
                        {"sessionID": 6, "lifecycle": "unknown", "active": None},
                    ],
                )

    def test_mobile_pi_session_states_fail_closed_when_probe_is_unavailable(self):
        unknown = [
            {"sessionID": 1, "lifecycle": "unknown", "active": None},
            {"sessionID": 2, "lifecycle": "unknown", "active": None},
            {"sessionID": 3, "lifecycle": "unknown", "active": None},
            {"sessionID": 4, "lifecycle": "unknown", "active": None},
            {"sessionID": 5, "lifecycle": "unknown", "active": None},
            {"sessionID": 6, "lifecycle": "unknown", "active": None},
        ]
        with mock.patch.object(
            jarvisd.subprocess,
            "run",
            side_effect=jarvisd.subprocess.TimeoutExpired(cmd="tmux", timeout=2),
        ):
            self.assertEqual(jarvisd._mobile_pi_session_states(), unknown)

        no_server = jarvisd.subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with mock.patch.object(jarvisd.subprocess, "run", return_value=no_server):
            self.assertEqual(jarvisd._mobile_pi_session_states(), unknown)

    def test_pi_sessions_includes_fixed_mobile_session_states(self):
        expected = [
            {"sessionID": 1, "lifecycle": "running", "active": True},
            {"sessionID": 2, "lifecycle": "idle", "active": False},
            {"sessionID": 3, "lifecycle": "waiting", "active": True},
            {"sessionID": 4, "lifecycle": "offline", "active": False},
            {"sessionID": 5, "lifecycle": "compacting", "active": True},
            {"sessionID": 6, "lifecycle": "unknown", "active": None},
        ]
        with mock.patch.object(jarvisd, "_mobile_pi_session_states", return_value=expected):
            result = jarvisd._pi_sessions()
        self.assertEqual(result["mobileSessions"], expected)

    def test_pi_sessions_counts_v2_running_waiting_and_compacting_as_active(self):
        with tempfile.TemporaryDirectory() as raw:
            status_dir = Path(raw)
            for index, lifecycle in enumerate(
                ("idle", "running", "waiting", "compacting", "invented"),
                start=1,
            ):
                (status_dir / f"{index}.json").write_text(
                    json.dumps({"version": 2, "lifecycle": lifecycle}),
                    encoding="utf-8",
                )
            with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir), \
                 mock.patch.object(jarvisd, "PI_RPC_SESSIONS", status_dir / "missing.json"), \
                 mock.patch.object(jarvisd, "_mobile_pi_session_states", return_value=[]):
                result = jarvisd._pi_sessions()
        self.assertEqual(result["localTotal"], 5)
        self.assertEqual(result["localActive"], 3)
        self.assertEqual(result["active"], 3)

    def test_default_state_contract_excludes_weather(self):
        coordinator = jarvisd.StateCoordinator()
        self.assertNotIn("weather", coordinator.collectors)
        self.assertNotIn("weather", coordinator.DEFAULT_INTERVALS)
        self.assertIn("codexQuota", coordinator.collectors)
        self.assertEqual(coordinator.DEFAULT_INTERVALS["codexQuota"], 60.0)
        self.assertEqual(coordinator.DEFAULT_IDLE_INTERVALS["plugs"], 10.0)
        self.assertEqual(coordinator.DEFAULT_IDLE_INTERVALS["purifier"], 45.0)
        self.assertEqual(coordinator.DEFAULT_IDLE_INTERVALS["codexQuota"], 300.0)
        self.assertEqual(coordinator.DEFAULT_FRESHNESS_LIMITS["plugs"], 30.0)
        self.assertEqual(coordinator.DEFAULT_FRESHNESS_LIMITS["purifier"], 90.0)
        self.assertEqual(coordinator.DEFAULT_ACTIVATION_WAIT_SECONDS, 0.0)

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
                    "data": {
                        "name": "Air Purifier",
                        "mode": "sleep",
                        "verification_pending": True,
                        "cid": "private-cid",
                    },
                },
            },
        )
        encoded = json.dumps(purifier)
        self.assertEqual(purifier["airPurifier"]["data"]["mode"], "sleep")
        self.assertTrue(purifier["airPurifier"]["data"]["verification_pending"])
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
                    {"is_on": True, "mode": "sleep", "verification_pending": True},
                    {"mode": "auto"},
                )
            )
            snapshot = coordinator.snapshot()
            pending = snapshot["subsystems"]["purifier"]
            self.assertTrue(pending["stale"])
            self.assertTrue(pending["verificationPending"])
            self.assertEqual(pending["pendingCommand"], {"setting": "mode", "value": "auto"})
            revision = coordinator._records["purifier"]["revision"]

            old_future = jarvisd.concurrent.futures.Future()
            old_future.set_result({"ok": True, "isOn": True, "mode": "sleep"})
            coordinator._complete("purifier", old_future, revision)
            pending = coordinator.snapshot()["subsystems"]["purifier"]
            self.assertTrue(pending["stale"])
            self.assertTrue(pending["verificationPending"])

            verified_future = jarvisd.concurrent.futures.Future()
            verified_future.set_result({"ok": True, "isOn": True, "mode": "auto"})
            coordinator._complete("purifier", verified_future, revision)
            verified = coordinator.snapshot()["subsystems"]["purifier"]
            self.assertFalse(verified["stale"])
            self.assertFalse(verified["verificationPending"])
            self.assertNotIn("pendingCommand", verified)
            self.assertEqual(verified["mode"], "auto")

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

    def test_state_coordinator_uses_active_idle_and_pending_intervals(self):
        clock = [100.0]
        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": lambda: {"ok": True}},
            intervals={"plugs": 10},
            idle_intervals={"plugs": 120},
            active_lease_seconds=5,
            now=lambda: clock[0],
        )

        with coordinator._lock:
            self.assertEqual(coordinator._interval_locked("plugs", clock[0]), 10)
            clock[0] = 106.0
            self.assertEqual(coordinator._interval_locked("plugs", clock[0]), 120)
            coordinator._records["plugs"]["pending"] = {"expected": {}}
            self.assertEqual(coordinator._interval_locked("plugs", clock[0]), 10)

    def test_idle_activation_refreshes_old_controls_before_returning(self):
        now = time.time
        calls = {"plugs": 0, "purifier": 0}

        def collect(name):
            calls[name] += 1
            return {"ok": True, "source": name}

        coordinator = jarvisd.StateCoordinator(
            collectors={
                "plugs": lambda: collect("plugs"),
                "purifier": lambda: collect("purifier"),
            },
            intervals={"plugs": 10, "purifier": 45},
            idle_intervals={"plugs": 120, "purifier": 180},
            active_lease_seconds=5,
            activation_wait_seconds=1,
            now=now,
        )
        old = now() - 300
        for record in coordinator._records.values():
            record.update({
                "data": {"ok": True, "source": "old"},
                "lastGoodAt": old,
                "updatedAt": "2026-08-28T00:00:00Z",
                "stale": False,
                "nextDue": now() + 300,
            })
        coordinator._active_until = 0
        try:
            coordinator.activate_client()
            snapshot = coordinator.snapshot()
            self.assertEqual(calls, {"plugs": 1, "purifier": 1})
            self.assertEqual(snapshot["subsystems"]["plugs"]["source"], "plugs")
            self.assertEqual(snapshot["subsystems"]["purifier"]["source"], "purifier")
            self.assertFalse(snapshot["subsystems"]["plugs"]["stale"])
            self.assertFalse(snapshot["subsystems"]["purifier"]["stale"])
        finally:
            coordinator.stop()

    def test_idle_activation_failure_keeps_last_good_control_state_stale(self):
        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": lambda: {"ok": False, "error": "offline"}},
            intervals={"plugs": 10},
            idle_intervals={"plugs": 120},
            active_lease_seconds=5,
            activation_wait_seconds=1,
        )
        coordinator._records["plugs"].update({
            "data": {"ok": True, "value": "last-good"},
            "lastGoodAt": time.time() - 300,
            "updatedAt": "2026-08-28T00:00:00Z",
            "stale": False,
            "nextDue": time.time() + 300,
        })
        coordinator._active_until = 0
        try:
            coordinator.activate_client()
            state = coordinator.snapshot()["subsystems"]["plugs"]
            self.assertEqual(state["value"], "last-good")
            self.assertTrue(state["stale"])
            self.assertEqual(state["lastError"], "offline")
        finally:
            coordinator.stop()

    def test_idle_activation_timeout_returns_old_control_state_as_stale(self):
        started = threading.Event()
        release = threading.Event()

        def slow_collector():
            started.set()
            release.wait(1)
            return {"ok": True, "value": "fresh"}

        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": slow_collector},
            intervals={"plugs": 10},
            idle_intervals={"plugs": 120},
            active_lease_seconds=5,
            activation_wait_seconds=0.05,
        )
        coordinator._records["plugs"].update({
            "data": {"ok": True, "value": "old"},
            "lastGoodAt": time.time() - 300,
            "updatedAt": "2026-08-28T00:00:00Z",
            "stale": False,
            "nextDue": time.time() + 300,
        })
        coordinator._active_until = 0
        try:
            started_at = time.monotonic()
            coordinator.activate_client()
            elapsed = time.monotonic() - started_at
            state = coordinator.snapshot()["subsystems"]["plugs"]
            self.assertLess(elapsed, 0.3)
            self.assertTrue(started.is_set())
            self.assertEqual(state["value"], "old")
            self.assertTrue(state["stale"])
            self.assertTrue(state["refreshing"])
        finally:
            release.set()
            coordinator.stop()

    def test_request_refresh_wakes_event_driven_scheduler_immediately(self):
        collected = threading.Event()
        coordinator = jarvisd.StateCoordinator(
            collectors={"test": lambda: collected.set() or {"ok": True}},
            intervals={"test": 60},
        )
        coordinator._records["test"]["nextDue"] = time.time() + 60
        try:
            coordinator.start()
            time.sleep(0.05)
            self.assertFalse(collected.is_set())
            coordinator.request_refresh("test")
            self.assertTrue(collected.wait(1))
        finally:
            coordinator.stop()

    def test_collect_state_renews_client_activity(self):
        snapshot = {"ok": True}
        with mock.patch.object(jarvisd.STATE_COORDINATOR, "snapshot", return_value=snapshot) as read:
            self.assertEqual(jarvisd.collect_state(), snapshot)
        read.assert_called_once_with(client_active=True)

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

    def test_recent_control_failure_keeps_usable_last_good_until_freshness_expiry(self):
        clock = [100.0]
        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": lambda: {"ok": True}},
            freshness_limits={"plugs": 30},
            now=lambda: clock[0],
        )
        coordinator._records["plugs"].update({
            "data": {"ok": True, "value": "confirmed"},
            "lastGoodAt": 90.0,
            "updatedAt": "2026-09-01T00:00:00Z",
            "stale": False,
        })
        failed = jarvisd.concurrent.futures.Future()
        failed.set_result({"ok": False, "error": "temporary"})
        coordinator._complete("plugs", failed, coordinator._records["plugs"]["revision"])

        recent = coordinator.snapshot()["subsystems"]["plugs"]
        self.assertEqual(recent["value"], "confirmed")
        self.assertFalse(recent["stale"])
        self.assertEqual(recent["lastError"], "temporary")

        clock[0] = 121.0
        expired = coordinator.snapshot()["subsystems"]["plugs"]
        self.assertTrue(expired["stale"])

    def test_partial_plug_failure_retains_and_expires_only_that_devices_last_good(self):
        clock = [100.0]
        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": lambda: {"ok": True}},
            freshness_limits={"plugs": 30},
            now=lambda: clock[0],
        )
        coordinator._records["plugs"].update({
            "data": {
                "ok": True,
                "count": 2,
                "onCount": 2,
                "plugs": {
                    "lamp": {"ok": True, "isOn": True},
                    "tv": {"ok": True, "isOn": True},
                },
            },
            "lastGoodAt": 90.0,
            "itemLastGoodAt": {"lamp": 90.0, "tv": 90.0},
            "updatedAt": "2026-09-01T00:00:00Z",
            "stale": False,
        })
        partial = jarvisd.concurrent.futures.Future()
        partial.set_result({
            "ok": True,
            "count": 2,
            "onCount": 0,
            "plugs": {
                "lamp": {"ok": True, "isOn": False},
                "tv": {"ok": False, "isOn": None, "error": "temporary"},
            },
        })
        coordinator._complete("plugs", partial, coordinator._records["plugs"]["revision"])

        recent = coordinator.snapshot()["subsystems"]["plugs"]
        self.assertFalse(recent["stale"])
        self.assertFalse(recent["plugs"]["lamp"]["isOn"])
        self.assertFalse(recent["plugs"]["lamp"]["stale"])
        self.assertTrue(recent["plugs"]["tv"]["isOn"])
        self.assertFalse(recent["plugs"]["tv"]["stale"])
        self.assertEqual(recent["plugs"]["tv"]["error"], "temporary")
        self.assertIn("tv: temporary", recent["lastError"])

        clock[0] = 126.0
        partially_expired = coordinator.snapshot()["subsystems"]["plugs"]
        self.assertFalse(partially_expired["stale"])
        self.assertFalse(partially_expired["plugs"]["lamp"]["stale"])
        self.assertTrue(partially_expired["plugs"]["tv"]["stale"])

        clock[0] = 131.0
        fully_expired = coordinator.snapshot()["subsystems"]["plugs"]
        self.assertTrue(fully_expired["stale"])

    def test_recent_control_activation_returns_immediately_and_refreshes_in_background(self):
        started = threading.Event()
        release = threading.Event()

        def collector():
            started.set()
            release.wait(1)
            return {"ok": True, "value": "new"}

        coordinator = jarvisd.StateCoordinator(
            collectors={"plugs": collector},
            freshness_limits={"plugs": 30},
            active_lease_seconds=5,
            activation_wait_seconds=1,
        )
        coordinator._records["plugs"].update({
            "data": {"ok": True, "value": "recent"},
            "lastGoodAt": time.time() - 10,
            "updatedAt": "2026-09-01T00:00:00Z",
            "stale": False,
            "nextDue": time.time() + 300,
        })
        coordinator._active_until = 0
        try:
            started_at = time.monotonic()
            coordinator.activate_client()
            elapsed = time.monotonic() - started_at
            self.assertLess(elapsed, 0.3)
            self.assertTrue(started.wait(0.3))
            state = coordinator.snapshot()["subsystems"]["plugs"]
            self.assertEqual(state["value"], "recent")
            self.assertFalse(state["stale"])
            self.assertTrue(state["refreshing"])
        finally:
            release.set()
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
            "scheduled-jobs-runner": {
                "label": "com.jarvis.pi-scheduler",
                "displayName": "Scheduled Jobs Runner",
                "description": "Private scheduler runtime",
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
                result = jarvisd._service_action("scheduled-jobs-runner", "restart")
            self.assertFalse(result["ok"])
            self.assertIn("not allowed", result["error"])
            events = jarvisd.EVENTS.list()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["eventType"], "service.action")

            proc = mock.Mock(returncode=0, stdout="state = running\npid = 123\n", stderr="")
            status = jarvisd._parse_launchctl_status("scheduled-jobs-runner", spec_data["scheduled-jobs-runner"], proc)
            self.assertEqual(status["displayName"], "Scheduled Jobs Runner")
            self.assertEqual(status["sortOrder"], 10)
            self.assertTrue(status["critical"])
            self.assertEqual(status["allowedActions"], [])
            self.assertTrue(status["running"])
        finally:
            jarvisd.EVENTS = old_events

    def test_notification_status_is_strict_sanitized_and_fixed_command(self):
        payload = {
            "ok": True,
            "providerConfigured": True,
            "dispatchEnabled": False,
            "environment": "development",
            "devices": {
                "iphone": {"registered": True, "registeredAt": "2026-09-01T00:00:00Z", "lastAcceptedAt": None},
                "watch": {"registered": False, "registeredAt": None, "lastAcceptedAt": None},
            },
            "pendingCount": 2,
            "failedCount": 1,
            "ambiguousCount": 0,
            "lastOutcome": "pending",
            "lastAttemptAt": "2026-09-01T00:01:00Z",
            "lastAcceptedAt": None,
            "error": "bounded public error",
            "deviceToken": "ab" * 32,
            "privatePath": "/Users/example/private",
        }
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="private stderr")
        with mock.patch.object(jarvisd, "SCHEDULER_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            result = jarvisd._notification_status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["devices"]["iphone"]["registered"], True)
        self.assertNotIn("deviceToken", result)
        self.assertNotIn("privatePath", result)
        self.assertEqual(run.call_args.args[0][-2:], ["--json", "notification-status"])

        payload["devices"]["watch"]["deviceToken"] = "cd" * 32
        # Nested extra fields are ignored by an explicit public reconstruction.
        self.assertNotIn("deviceToken", json.dumps(jarvisd._public_notification_status(payload)))
        payload["pendingCount"] = -1
        with self.assertRaisesRegex(ValueError, "count"):
            jarvisd._public_notification_status(payload)

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
                "privateDeliveryId": "private-delivery",
                "path": "/Users/example/private",
            }],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"total": 1, "enabled": 1, "running": 0, "errors": 0})
        encoded = json.dumps(result)
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("private model", encoded)
        self.assertNotIn("private-delivery", encoded)
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
        with mock.patch.object(jarvisd, "SCHEDULER_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            result = jarvisd._scheduled_jobs()
        self.assertTrue(result["ok"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], ["--json", "list-public"])
        self.assertNotIn("private stderr", json.dumps(result))

        completed.stdout = "not-json"
        with mock.patch.object(jarvisd, "SCHEDULER_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed):
            failed = jarvisd._scheduled_jobs()
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["jobs"], [])
        self.assertNotIn("not-json", json.dumps(failed))

    def test_scheduled_job_results_are_bounded_sanitized_and_private(self):
        payload = {
            "ok": True,
            "results": [{
                "sequence": 7,
                "id": "run_20260830T010000Z_abcd1234",
                "jobId": "job_demo",
                "jobName": "demo",
                "status": "error",
                "outputKind": "direct",
                "startedAt": "2026-08-30T01:00:00Z",
                "finishedAt": "2026-08-30T01:00:02Z",
                "durationSeconds": 2.0,
                "exitCode": 1,
                "title": "demo failed",
                "summary": "TOKEN=supersecret from /Users/example/private/file",
                "output": "Bearer abcdefghijklmnop; see /tmp/private-output and https://example.com/result",
                "error": '{"api_key":"private-key-value"}',
                "truncated": False,
                "prompt": "private prompt",
                "model": "private model",
            }],
            "hasMore": False,
            "nextAfter": 7,
        }
        result = jarvisd._public_scheduled_job_results(payload, requested_limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["nextAfter"], 7)
        encoded = json.dumps(result)
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("private model", encoded)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn("/tmp/", encoded)
        self.assertNotIn("supersecret", encoded)
        self.assertNotIn("abcdefghijklmnop", encoded)
        self.assertNotIn("private-key-value", encoded)
        self.assertIn("[REDACTED]", encoded)
        self.assertIn("https://example.com/result", encoded)

        payload["results"][0]["output"] = "a" * jarvisd.MAX_SCHEDULED_JOB_RESULT_BYTES
        payload["results"][0]["error"] = "b"
        with self.assertRaisesRegex(ValueError, "aggregate byte limit"):
            jarvisd._public_scheduled_job_results(payload, requested_limit=10)

    def test_scheduled_job_result_runner_uses_only_bounded_fixed_arguments(self):
        payload = {"ok": True, "results": [], "hasMore": False, "nextAfter": 12}
        completed = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="private stderr")
        with mock.patch.object(jarvisd, "SCHEDULER_RUNNER", Path(__file__)), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=completed) as run:
            result = jarvisd._scheduled_job_results(after=12, limit=25, job_id="job_demo")
        self.assertTrue(result["ok"])
        argv = run.call_args.args[0]
        self.assertEqual(
            argv[-7:],
            ["list-results-public", "--limit", "25", "--after", "12", "--job-id", "job_demo"],
        )
        self.assertNotIn("private stderr", json.dumps(result))


class SigningRenewalUnitTests(unittest.TestCase):
    def test_signing_status_is_bounded_sanitized_and_hides_pid(self):
        payload = {
            "ok": True,
            "phase": "building",
            "running": True,
            "message": "Building /Users/private/source now",
            "expiresAt": "2026-09-03T03:00:00Z",
            "pid": os.getpid(),
        }
        with mock.patch.object(jarvisd, "SIGNING_RENEWAL_SCRIPT", MODULE_PATH):
            status = jarvisd._signing_renewal_status(payload)
        self.assertTrue(status["running"])
        self.assertEqual(status["phase"], "building")
        self.assertNotIn("/Users/", status["message"])
        self.assertNotIn("pid", status)
        self.assertIsNone(status["failedPhase"])

    def test_signing_status_exposes_only_a_fixed_failed_step(self):
        with mock.patch.object(jarvisd, "SIGNING_RENEWAL_SCRIPT", MODULE_PATH):
            failed = jarvisd._signing_renewal_status({
                "ok": False,
                "phase": "failed",
                "failedPhase": "installingWatch",
                "running": False,
            })
            rejected = jarvisd._signing_renewal_status({
                "ok": False,
                "phase": "failed",
                "failedPhase": "/Users/private/arbitrary-step",
                "running": False,
            })
        self.assertEqual(failed["failedPhase"], "installingWatch")
        self.assertIsNone(rejected["failedPhase"])

    def test_interrupted_signing_status_retains_the_active_step(self):
        with mock.patch.object(jarvisd, "SIGNING_RENEWAL_SCRIPT", MODULE_PATH):
            status = jarvisd._signing_renewal_status({
                "ok": True,
                "phase": "verifying",
                "running": True,
                "pid": 2_147_483_647,
            })
        self.assertFalse(status["running"])
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["failedPhase"], "verifying")

    def test_signing_start_runs_only_the_fixed_script_without_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts" / "renew-free-signing.sh"
            script.parent.mkdir()
            script.write_text("#!/bin/sh\n", encoding="utf-8")
            script.chmod(0o700)
            process = mock.Mock(pid=1234)
            with mock.patch.object(jarvisd, "SIGNING_RENEWAL_SCRIPT", script), \
                 mock.patch.object(jarvisd, "SIGNING_RENEWAL_STATUS_FILE", root / "missing.json"), \
                 mock.patch.object(jarvisd, "SIGNING_RENEWAL_LOG_DIR", root / "logs"), \
                 mock.patch.object(jarvisd.subprocess, "Popen", return_value=process) as popen:
                started, result = jarvisd._start_signing_renewal()
            self.assertTrue(started)
            self.assertTrue(result["running"])
            self.assertEqual(popen.call_args.args[0], [str(script)])
            self.assertNotIn("shell", popen.call_args.kwargs)


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
        status, _, _ = self.request("GET", "/api/v1/scheduled-job-results")
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/v1/services", token="write-secret")
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="write-secret")
        self.assertEqual(status, 200)
        status, _, _ = self.request("POST", "/api/jarvis/events", {"source": "test"}, token="api-secret")
        self.assertEqual(status, 401)

    def test_state_can_request_authenticated_read_only_codex_refresh(self):
        snapshot = {"ok": True}
        with mock.patch.object(jarvisd.STATE_COORDINATOR, "request_refresh") as refresh, \
             mock.patch.object(jarvisd, "collect_state", return_value=snapshot):
            status, _, body = self.request(
                "GET",
                "/api/v1/state?refresh=codexQuota",
                token="api-secret",
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), snapshot)
        refresh.assert_called_once_with("codexQuota")

        with mock.patch.object(jarvisd.STATE_COORDINATOR, "request_refresh") as unauthenticated:
            status, _, _ = self.request("GET", "/api/v1/state?refresh=codexQuota")
        self.assertEqual(status, 401)
        unauthenticated.assert_not_called()

    def test_signing_endpoints_require_auth_and_expose_only_fixed_action(self):
        public_status = {
            "ok": True,
            "available": True,
            "phase": "idle",
            "running": False,
            "message": "Ready.",
        }
        status, _, _ = self.request("GET", "/api/v1/signing/status")
        self.assertEqual(status, 401)
        with mock.patch.object(jarvisd, "_signing_renewal_status", return_value=public_status):
            status, _, body = self.request("GET", "/api/v1/signing/status", token="api-secret")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["phase"], "idle")

        queued = public_status | {"phase": "queued", "running": True}
        with mock.patch.object(jarvisd, "_start_signing_renewal", return_value=(True, queued)) as start:
            status, _, body = self.request("POST", "/api/v1/signing/renew", token="api-secret")
        self.assertEqual(status, 202)
        self.assertTrue(json.loads(body)["running"])
        start.assert_called_once_with()

        with mock.patch.object(jarvisd, "_start_signing_renewal") as rejected:
            status, _, body = self.request(
                "POST",
                "/api/v1/signing/renew",
                {"command": "arbitrary"},
                token="api-secret",
            )
        self.assertEqual(status, 400)
        self.assertIn("does not accept", body.decode())
        rejected.assert_not_called()

    def test_notification_status_endpoint_is_authenticated_and_read_only(self):
        response = jarvisd._notification_status_unavailable()
        with mock.patch.object(jarvisd, "_notification_status", return_value=response) as status_call:
            status, _, body = self.request("GET", "/api/v1/notification-status", token="api-secret")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["ok"])
        status_call.assert_called_once_with()

        status, _, _ = self.request("GET", "/api/v1/notification-status")
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

    def test_scheduled_job_results_endpoint_validates_cursor_limit_and_job(self):
        response = {
            "ok": True,
            "generatedAt": "2026-08-30T00:00:00Z",
            "results": [],
            "hasMore": False,
            "nextAfter": 9,
        }
        with mock.patch.object(jarvisd, "_scheduled_job_results", return_value=response) as results:
            status, _, body = self.request(
                "GET",
                "/api/v1/scheduled-job-results?after=9&limit=25&jobId=job_demo",
                token="api-secret",
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["nextAfter"], 9)
        results.assert_called_once_with(after=9, limit=25, job_id="job_demo")

        for path in (
            "/api/v1/scheduled-job-results?after=-1",
            "/api/v1/scheduled-job-results?limit=0",
            "/api/v1/scheduled-job-results?limit=101",
            "/api/v1/scheduled-job-results?jobId=../../private",
            "/api/v1/scheduled-job-results?after=not-a-number",
        ):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path, token="api-secret")
                self.assertEqual(status, 400)

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
