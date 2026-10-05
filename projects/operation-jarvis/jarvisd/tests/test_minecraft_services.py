"""Offline service observations: never invoke live processes, RPCs or Minecraft."""
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
import unittest
from unittest import mock

from daemon_loader import load_daemon
from jarvisd_core import minecraft_services as mc, system_health

DAEMON = load_daemon("jarvisd_minecraft_service_tests")


class MinecraftServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        for file in ("java/current/bin/java", "server/paper.jar", "node/current/bin/node",
                     "jarvis-bot/bot.js", "jarvis-bot/pi-rpc-client.js"):
            path = self.root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.processes = (
            f"10 501 {self.root}/java/current/bin/java -Xmx12G -jar paper.jar nogui\n"
            f"20 501 {self.root}/node/current/bin/node bot.js\n"
            f"30 501 {self.root}/node/current/bin/node pi-rpc-client.js\n")
        self.cwd = (f"p10\nfcwd\nn{self.root}/server\np20\nfcwd\nn{self.root}/jarvis-bot\n"
                    f"p30\nfcwd\nn{self.root}/jarvis-bot\n")
        self.images = (f"p10\nftxt\nn{self.root}/java/current/bin/java\n"
                       f"p20\nftxt\nn{self.root}/node/current/bin/node\n"
                       f"p30\nftxt\nn{self.root}/node/current/bin/node\n")
        self.listeners = "p10\nf10\nn*:25565\np20\nf11\nn127.0.0.1:3100\np30\nf12\nn127.0.0.1:3101\n"
        self.bot = {"ok": True, "username": "jarvis", "spawned": True, "rpcOperation": None}
        self.agent = {"ok": True, "piRunning": True}
        self.commands = []
        self.requests = []

    def command(self, argv, deadline):
        self.commands.append(argv)
        if argv[0] == "/bin/ps":
            return 0, self.processes
        if "cwd" in argv:
            return 0, self.cwd
        if "txt" in argv:
            return 0, self.images
        return (0 if self.listeners else 1), self.listeners

    def health(self, port, method, deadline):
        self.requests.append((port, method))
        return self.bot if port == 3100 else self.agent

    def collect(self, adapters=mc.ADAPTERS):
        return mc.collect_minecraft_services(adapters, self.root, uid=501,
                                             command=self.command, health=self.health)

    def test_both_running_with_one_shared_inventory(self):
        rows = self.collect()
        for row in rows.values():
            self.assertTrue(row["ok"])
            self.assertTrue(row["configured"])
            self.assertTrue(row["running"])
            self.assertTrue(row["ready"])
        self.assertEqual(rows["minecraft-paper"]["pid"], 10)
        self.assertEqual(rows["minecraft-bot"]["pid"], 20)
        self.assertEqual(len(self.commands), 4)
        self.assertEqual(self.requests, [(3100, "POST"), (3101, "GET")])
        self.assertFalse(any("screen" in argv or "/bin/sh" in argv for argv in self.commands))

    def test_stopped_independently_and_no_rpc_when_bot_stopped(self):
        for kind, line, other in (("minecraft-paper", 0, "minecraft-bot"),
                                  ("minecraft-bot", 1, "minecraft-paper")):
            with self.subTest(kind=kind):
                original = self.processes
                self.processes = "\n".join(v for i, v in enumerate(original.splitlines()) if i != line)
                self.requests.clear()
                rows = self.collect()
                self.assertFalse(rows[kind]["running"])
                self.assertTrue(rows[kind]["ok"])
                self.assertTrue(rows[other]["running"])
                if kind == "minecraft-bot":
                    self.assertEqual(self.requests, [])
                self.processes = original

    def test_basename_argv_still_requires_private_mapped_executable(self):
        self.processes = self.processes.replace(str(self.root / "java/current/bin/java"), "java")
        self.processes = self.processes.replace(str(self.root / "node/current/bin/node"), "node")
        self.assertTrue(all(row["ready"] is True for row in self.collect().values()))
        self.images = self.images.replace(str(self.root), "/another/runtime")
        self.assertTrue(all(row["running"] is False for row in self.collect().values()))

    def test_unrelated_multiline_argv_does_not_break_inventory(self):
        self.processes += "99 501 /bin/bash -c unrelated\nmultiline shell command\n"
        self.assertTrue(all(row["ready"] is True for row in self.collect().values()))

    def test_missing_executable_evidence_is_unknown_not_stopped(self):
        self.images = ""
        self.assertTrue(all(row["running"] is None for row in self.collect().values()))

    def test_no_matching_process_does_not_probe_ports_or_health(self):
        self.processes = "1 0 /sbin/launchd\n"
        rows = self.collect()
        self.assertTrue(all(row["running"] is False for row in rows.values()))
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.requests, [])

    def test_wrong_owner_executable_or_cwd_is_not_this_service(self):
        original_processes, original_cwd = self.processes, self.cwd
        for process, cwd in (
            (original_processes.replace("501", "502"), original_cwd),
            (original_processes.replace(str(self.root), "/another/project"), original_cwd),
            (original_processes, original_cwd.replace(str(self.root), "/another/project")),
            (original_processes.replace(" -jar paper.jar", " -jar another.jar").replace(" bot.js", " other.js"), original_cwd),
        ):
            with self.subTest(process=process):
                self.processes, self.cwd = process, cwd
                rows = self.collect()
                self.assertTrue(all(row["running"] is False for row in rows.values()))

    def test_port_owned_by_another_pid_is_not_readiness(self):
        self.listeners = "p99\nf10\nn*:25565\nn127.0.0.1:3100\n"
        rows = self.collect()
        self.assertTrue(all(row["running"] is True for row in rows.values()))
        self.assertTrue(all(row["ready"] is False for row in rows.values()))
        self.assertEqual(self.requests, [])

    def test_absent_listener_is_not_stopped(self):
        self.listeners = ""
        rows = self.collect()
        self.assertTrue(all(row["running"] is True for row in rows.values()))
        self.assertTrue(all(row["ready"] is False for row in rows.values()))

    def test_agent_stopped_disconnected_and_quarantine(self):
        self.agent["piRunning"] = False
        row = self.collect()["minecraft-bot"]
        self.assertTrue(row["running"])
        self.assertFalse(row["ready"])
        self.assertEqual(row["readinessReason"], "agent_unavailable")
        self.bot["spawned"] = False
        self.assertEqual(self.collect()["minecraft-bot"]["readinessReason"], "bot_disconnected")
        self.bot["spawned"] = True
        self.bot["rpcOperation"] = {"quarantined": True, "path": "PRIVATE", "cancelReason": "SECRET"}
        row = self.collect()["minecraft-bot"]
        self.assertEqual(row["readinessReason"], "bot_quarantined")
        self.assertNotIn("PRIVATE", json.dumps(row))
        self.assertNotIn("SECRET", json.dumps(row))

    def test_gateway_without_verified_identity_never_receives_request(self):
        self.processes = "\n".join(self.processes.splitlines()[:2])
        row = self.collect()["minecraft-bot"]
        self.assertEqual(row["readinessReason"], "agent_unavailable")
        self.assertEqual(self.requests, [(3100, "POST")])

    def test_health_timeout_or_malformed_response_is_not_stopped(self):
        for response in ({"ok": True, "username": "jarvis", "spawned": "true"},
                         {"ok": True, "username": "someone-else", "spawned": True}):
            self.bot = response
            rows = self.collect()
            self.assertTrue(rows["minecraft-bot"]["running"])
            self.assertIsNone(rows["minecraft-bot"]["ready"])
            self.assertTrue(rows["minecraft-paper"]["ready"])
        rows = mc.collect_minecraft_services(mc.ADAPTERS, self.root, uid=501,
            command=self.command, health=mock.Mock(side_effect=TimeoutError("PRIVATE")))
        self.assertTrue(rows["minecraft-bot"]["running"])
        self.assertIsNone(rows["minecraft-bot"]["ready"])
        self.assertNotIn("PRIVATE", json.dumps(rows))

    def test_inventory_failure_or_incomplete_cwd_is_unknown_not_stopped(self):
        for command in (mock.Mock(side_effect=TimeoutError("SECRET")),
                        mock.Mock(return_value=(1, "")), mock.Mock(return_value=(0, "malformed"))):
            rows = mc.collect_minecraft_services(mc.ADAPTERS, self.root, command=command)
            self.assertTrue(all(row["ok"] is False and row["running"] is None for row in rows.values()))
            self.assertNotIn("SECRET", json.dumps(rows))
        self.cwd = ""
        self.assertTrue(all(row["running"] is None for row in self.collect().values()))

    def test_duplicate_runtime_is_ambiguous_for_only_that_service(self):
        self.processes += f"21 501 {self.root}/node/current/bin/node bot.js\n"
        self.cwd += f"p21\nfcwd\nn{self.root}/jarvis-bot\n"
        self.images += f"p21\nftxt\nn{self.root}/node/current/bin/node\n"
        rows = self.collect()
        self.assertIsNone(rows["minecraft-bot"]["running"])
        self.assertFalse(rows["minecraft-bot"]["ok"])
        self.assertTrue(rows["minecraft-paper"]["ready"])

    def test_partial_cwd_failure_does_not_hide_unrelated_server(self):
        self.cwd = f"p10\nfcwd\nn{self.root}/server\np30\nfcwd\nn{self.root}/jarvis-bot\n"
        rows = self.collect()
        self.assertTrue(rows["minecraft-paper"]["ready"])
        self.assertFalse(rows["minecraft-bot"]["ok"])
        self.assertIsNone(rows["minecraft-bot"]["running"])

    def test_missing_installation_is_configured_false(self):
        (self.root / "jarvis-bot/bot.js").unlink()
        self.assertFalse(self.collect()["minecraft-bot"]["configured"])

    def test_unknown_adapter_has_no_io(self):
        self.assertEqual(self.collect(["arbitrary-shell"]), {})
        self.assertEqual(self.commands, [])

    def test_sanitized_health_projection(self):
        value = {"ok": True, "running": True, "critical": False, "ready": True}
        self.assertEqual(system_health._service(value)["state"], "healthy")
        value["ready"] = False
        self.assertEqual(system_health._service(value)["reason"], "service_not_ready")
        value["ready"] = None
        self.assertEqual(system_health._service(value)["state"], "unknown")
        value["running"] = False
        self.assertEqual(system_health._service(value)["state"], "inactive")

    def test_command_output_and_elapsed_time_are_bounded(self):
        with mock.patch.object(mc, "MAX_OUTPUT", 64):
            with self.assertRaises(ValueError):
                mc._command([sys.executable, "-c", "print(\"x\" * 1000)"], time.monotonic() + 1)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            mc._command([sys.executable, "-c", "import time; time.sleep(2)"], started + 0.03)
        self.assertLess(time.monotonic() - started, 1)

    def test_total_http_deadline_interrupts_header_wait(self):
        expired = threading.Event()
        connection = mock.Mock()
        connection.sock.shutdown.side_effect = lambda _: expired.set()
        def wait_for_headers():
            self.assertTrue(expired.wait(1), "hard deadline must interrupt getresponse")
            raise TimeoutError()
        connection.getresponse.side_effect = wait_for_headers
        started = time.monotonic()
        with mock.patch.object(mc.http.client, "HTTPConnection", return_value=connection):
            with self.assertRaises(TimeoutError):
                mc._health(3100, "POST", started + 0.03)
        self.assertLess(time.monotonic() - started, 1)
        connection.close.assert_called_once()

    def test_deadline_and_fixed_loopback_health_request(self):
        response = mock.Mock(status=200)
        response.read1.side_effect = [b'{"ok":true,"spawned":true}', b'']
        connection = mock.Mock()
        connection.getresponse.return_value = response
        with mock.patch.object(mc.http.client, "HTTPConnection", return_value=connection) as http:
            mc._health(3100, "POST", mc.time.monotonic() + 1)
        self.assertEqual(http.call_args.args, ("127.0.0.1", 3100))
        connection.request.assert_called_once_with("POST", "/health", body=b"{}",
            headers={"Content-Type": "application/json"})
        connection.close.assert_called_once()
        for status, chunks in ((302, []), (200, [b"x" * (mc.MAX_HEALTH + 1)]),
                               (200, [b"[]", b""]), (200, [b'{"ok":false}', b""])):
            response.status = status
            response.read1.side_effect = chunks
            with mock.patch.object(mc.http.client, "HTTPConnection", return_value=connection):
                with self.assertRaises(ValueError):
                    mc._health(3100, "POST", mc.time.monotonic() + 1)


class MinecraftDaemonWiringTests(unittest.TestCase):
    specs = {"minecraft-server": {"adapter": "minecraft-paper", "critical": False,
              "executionMode": "continuous", "allowedActions": ["start", "stop", "restart"]},
             "minecraft-jarvis-bot": {"adapter": "minecraft-bot", "critical": False}}

    def test_bulk_inventory_and_single_status_use_same_adapter(self):
        observations = {adapter: {"ok": True, "running": False, "configured": True}
                        for adapter in mc.ADAPTERS}
        with mock.patch.object(DAEMON, "collect_minecraft_services", return_value=observations) as collect:
            rows = DAEMON._services_state(self.specs)
            collect.assert_called_once()
            self.assertEqual(rows["minecraft-server"]["allowedActions"], [])
            self.assertFalse(rows["minecraft-jarvis-bot"]["running"])
        with mock.patch.object(DAEMON, "_load_services", return_value=self.specs), \
             mock.patch.object(DAEMON, "collect_minecraft_services", return_value=observations):
            self.assertTrue(DAEMON._service_action("minecraft-server", "status")["ok"])

    def test_every_mutation_rejected_without_probe_or_launchctl(self):
        with mock.patch.object(DAEMON, "_load_services", return_value=self.specs), \
             mock.patch.object(DAEMON, "collect_minecraft_services") as collect, \
             mock.patch.object(DAEMON, "_run_launchctl") as launchctl:
            for name in self.specs:
                for action in ("start", "stop", "restart", "anything"):
                    self.assertFalse(DAEMON._service_action(name, action)["ok"])
            collect.assert_not_called()
            launchctl.assert_not_called()

    def test_unknown_or_malformed_adapter_fails_closed(self):
        for adapter in ("shell", [], None):
            row = DAEMON._services_state({"bad": {"adapter": adapter}})["bad"]
            self.assertFalse(row["ok"])
            self.assertIsNone(row["running"])

    def test_registry_is_optional_continuous_read_only(self):
        specs = json.loads((Path(DAEMON.__file__).parent / "services.json").read_text())["services"]
        for name in self.specs:
            self.assertFalse(specs[name]["critical"])
            self.assertEqual(specs[name]["executionMode"], "continuous")
            self.assertEqual(specs[name]["allowedActions"], [])


if __name__ == "__main__":
    unittest.main()
