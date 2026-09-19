"""Shared infrastructure contracts, independent of real devices/services."""
import dataclasses
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_jarvisd import jarvisd as d
from jarvisd_core import auth, commands
from jarvisd_core.events import EventInputError, EventStore
from jarvisd_core.http_input import RequestInputError, read_json


class AuthenticationTests(unittest.TestCase):
    def test_ip_normalization_and_invalid_addresses(self):
        self.assertEqual(auth.client_ip("::ffff:127.0.0.1"), auth.client_ip("127.0.0.1"))
        self.assertIsNone(auth.client_ip("not-an-address"))
        self.assertIsNone(auth.client_ip(""))

    def test_network_policy_uses_address_not_token(self):
        kwargs = dict(mode="trusted-network", scope="api", api_token="api", event_token="event",
                      trusted_cidrs="127.0.0.0/8, ::1/128", token="api")
        for address, expected in (("127.0.0.1", True), ("::1", True), ("203.0.113.1", False)):
            with self.subTest(address=address):
                self.assertEqual(auth.authorized(address=auth.client_ip(address), **kwargs), expected)
        self.assertFalse(auth.authorized(address=None, **kwargs))

    def test_event_credentials_do_not_authorize_api(self):
        kwargs = dict(mode="token", address=auth.client_ip("127.0.0.1"),
                      api_token="api", event_token="event", trusted_cidrs="127.0.0.0/8")
        for scope, token, expected in (("api", "api", True), ("api", "event", False),
                                      ("events", "event", True), ("events", "api", False),
                                      ("api", "", False)):
            with self.subTest(scope=scope, token=token):
                self.assertEqual(auth.authorized(scope=scope, token=token, **kwargs), expected)

    def test_unconfigured_event_token_preserves_api_fallback(self):
        self.assertTrue(auth.authorized(mode="token", address=None, token="api", scope="events",
                                        api_token="api", event_token="", trusted_cidrs=""))

    def test_invalid_mode_fails_closed_even_with_matching_token(self):
        self.assertFalse(auth.authorized(mode="unknown", address=None, token="api", scope="api",
                                         api_token="api", event_token="", trusted_cidrs=""))

    def test_unsafe_configuration_is_rejected(self):
        good = dict(mode="token", api_token="api", trusted_cidrs="127.0.0.0/8", max_json_bytes=65536)
        auth.validate_config(**good)
        for changes in ({"mode": "unknown"}, {"api_token": ""}, {"max_json_bytes": 1023},
                        {"max_json_bytes": 10485761}, {"mode": "trusted-network", "trusted_cidrs": ""},
                        {"mode": "trusted-network", "trusted_cidrs": "invalid"}):
            with self.subTest(changes=changes), self.assertRaises((RuntimeError, ValueError)):
                auth.validate_config(**{**good, **changes})


class InputTests(unittest.TestCase):
    def test_json_object_decodes(self):
        raw = '{"name":"é"}'.encode()
        self.assertEqual(read_json(io.BytesIO(raw), str(len(raw)), max_bytes=100), {"name": "é"})

    def test_invalid_framing_and_json_preserve_http_statuses(self):
        cases = [(None, b"", 411), ("x", b"", 400), ("0", b"", 400), ("-1", b"", 400),
                 ("200", b"", 413), ("2", b"{", 400), ("1", b"\xff", 400),
                 ("1", b"{", 400), ("2", b"[]", 400), ("4", b"null", 400)]
        for length, raw, status in cases:
            with self.subTest(length=length, raw=raw), self.assertRaises(RequestInputError) as caught:
                read_json(io.BytesIO(raw), length, max_bytes=100)
            self.assertEqual(caught.exception.status, status)

    def test_oversize_is_rejected_without_reading_and_closes_http_connection(self):
        stream = mock.Mock()
        with self.assertRaises(RequestInputError):
            read_json(stream, "101", max_bytes=100)
        stream.read.assert_not_called()
        handler = object.__new__(d.Handler)
        handler.headers = {"Content-Length": "101"}
        handler.rfile = stream
        handler.close_connection = False
        with mock.patch.object(d, "MAX_JSON_BODY_BYTES", 100), self.assertRaises(RequestInputError):
            handler._read_json()
        self.assertTrue(handler.close_connection)


class CommandCatalogTests(unittest.TestCase):
    def setUp(self):
        self.resolver = mock.Mock(return_value="private-selector")

    def build(self, action, params=None):
        return commands.build_command(action, params, cli=Path("/fixed/jarvis-cli"),
                                      selected_purifier=self.resolver)

    def test_exact_legacy_allowlist_has_closed_immutable_descriptors(self):
        self.assertEqual(set(commands.COMMANDS), {
            "status", "plug-list", "plug-status", "plug-on", "plug-off", "plug-toggle",
            "purifier-status", "purifier-set",
        })
        self.assertEqual({spec.action for spec in commands.COMMANDS.values() if spec.effect == "write"},
                         {"plug-on", "plug-off", "plug-toggle", "purifier-set"})
        for action, spec in commands.COMMANDS.items():
            self.assertEqual(action, spec.action)
            self.assertEqual(spec.timeout_seconds, 30)
            self.assertFalse(spec.replay_allowed)
        with self.assertRaises(TypeError):
            commands.COMMANDS["shell"] = commands.COMMANDS["status"]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            commands.COMMANDS["status"].effect = "write"

    def test_read_and_plug_argv_are_unchanged(self):
        cases = [("status", None, ["status", "--no-cast"]),
                 ("plug-list", {}, ["plug-list"]),
                 ("purifier-status", {}, ["purifier-status"])]
        cases += [(action, {"plug": " lamp "}, [action, "lamp"])
                  for action in ("plug-status", "plug-on", "plug-off", "plug-toggle")]
        for action, params, expected in cases:
            with self.subTest(action=action):
                self.assertEqual(self.build(action, params), ["/fixed/jarvis-cli", "--json", *expected])
        self.resolver.assert_not_called()

    def test_selected_purifier_is_resolved_explicitly(self):
        self.assertEqual(self.build("purifier-set", {"deviceID": "opaque-id", "setting": "speed", "level": 2}),
                         ["/fixed/jarvis-cli", "--json", "purifier-set", "speed", "--purifier",
                          "private-selector", "--level", "2"])
        self.resolver.assert_called_once_with("opaque-id")

    def test_default_purifier_does_not_resolve_a_selected_device(self):
        self.assertEqual(self.build("purifier-set", {"setting": "mode", "value": "auto"})[-3:],
                         ["purifier-set", "mode", "auto"])
        self.resolver.assert_not_called()

    def test_validation_rejects_unknown_actions_injection_and_bad_types(self):
        cases = [("cast-status", {}), ("security-disarm", {}), (["status"], {}),
                 ("status", []), ("plug-on", {"plug": "lamp; false"}),
                 ("purifier-set", {"setting": "unknown"}),
                 ("purifier-set", {"setting": "speed", "level": True}),
                 ("purifier-set", {"setting": "speed", "level": 5}),
                 ("purifier-set", {"setting": "mode", "value": "unknown"}),
                 ("purifier-set", {"setting": "timer", "minutes": 0})]
        for action, params in cases:
            with self.subTest(action=action, params=params), self.assertRaises(commands.CommandError):
                self.build(action, params)

    def test_unknown_selected_device_never_falls_back_to_default(self):
        self.resolver.side_effect = commands.CommandError("unknown device")
        with self.assertRaises(commands.CommandError):
            self.build("purifier-set", {"deviceID": "missing", "setting": "power", "value": "on"})

    def handler(self, action="plug-on"):
        handler = object.__new__(d.Handler)
        handler.server = mock.Mock(control_endpoint=None)
        handler.path = "/api/v1/command"
        handler._auth_or_respond = mock.Mock(return_value=True)
        handler._read_json = mock.Mock(return_value={"action": action, "params": {"plug": "lamp"}})
        handler._send = mock.Mock()
        return handler

    def test_ambiguous_adapter_failure_is_attempted_once_never_replayed(self):
        handler = self.handler()
        with mock.patch.object(d, "run_cli_json", return_value={"ok": False, "error": "timed out"}) as run, \
             mock.patch.object(d, "STATE_COORDINATOR") as state:
            item = {"ok": True, "stale": False, "isOn": False, "host": "192.0.2.1"}
            state.snapshot.return_value = {"subsystems": {"plugs": {"plugs": {"lamp": item}}}}
            state.begin_device_write.return_value = (item, ("lamp",))
            handler.do_POST()
        run.assert_called_once_with([
            sys.executable, "-B", str(d.DEVICE_WORKER),
            "--operation-root", str(d.OPERATION_ROOT), "--project-root", str(d.PROJECT_ROOT),
            "--json", "plug-on", "lamp", "--expected-host", "192.0.2.1"], timeout=30.0, env=None)
        state.apply_plug_result.assert_not_called()
        self.assertEqual(handler._send.call_args.args[0], 200)
        self.assertFalse(handler._send.call_args.args[1]["ok"])

    def test_invalid_or_unauthenticated_commands_never_reach_adapter(self):
        for authenticated, action in ((True, "shell"), (False, "plug-on")):
            handler = self.handler(action)
            handler._auth_or_respond.return_value = authenticated
            with mock.patch.object(d, "run_cli_json") as run:
                handler.do_POST()
            run.assert_not_called()
            if not authenticated:
                handler._read_json.assert_not_called()


class EventLifecycleTests(unittest.TestCase):
    def test_event_limits_are_instance_local(self):
        small = EventStore(max_json_bytes=32)
        large = EventStore(max_json_bytes=1000)
        payload = {"summary": "x" * 100}
        with self.assertRaises(EventInputError):
            small.add(payload)
        self.assertEqual(large.add(payload)["seq"], 1)
        self.assertEqual(small.list(), [])

    def test_in_memory_store_does_not_create_runtime_directories(self):
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected I/O")):
            store = EventStore()
            store.add({"summary": "test"})
            self.assertEqual(len(store.list()), 1)

    def test_main_initializes_persistence_after_validation_before_serving(self):
        with tempfile.TemporaryDirectory() as raw:
            event_file = Path(raw) / "events.jsonl"
            event_file.write_text('{"seq":42,"summary":"retained"}\n')
            server = mock.Mock()
            server.serve_forever.side_effect = KeyboardInterrupt
            with mock.patch.object(d, "EVENTS_FILE", event_file), \
                 mock.patch.object(d, "EVENTS", EventStore()), \
                 mock.patch.object(d, "configure_bounded_stderr", return_value=None), \
                 mock.patch.object(d, "validate_config"), \
                 mock.patch.object(d, "STATE_COORDINATOR"), \
                 mock.patch.object(d, "OMLX_COORDINATOR"), \
                 mock.patch.object(d, "ThreadingHTTPServer", return_value=server), \
                 mock.patch.object(d.sys, "stderr", io.StringIO()):
                self.assertEqual(d.main(), 0)
                self.assertEqual(d.EVENTS.add({"summary": "next"})["seq"], 43)
            self.assertEqual(json.loads(event_file.read_text().splitlines()[-1])["seq"], 43)
            server.server_close.assert_called_once()

    def test_failed_config_never_initializes_persistence_or_collectors(self):
        with mock.patch.object(d, "validate_config", side_effect=RuntimeError("invalid")), \
             mock.patch.object(d, "EventStore") as store, \
             mock.patch.object(d, "STATE_COORDINATOR") as coordinator, \
             self.assertRaises(RuntimeError):
            d.main()
        store.assert_not_called()
        coordinator.start.assert_not_called()

    def test_core_imports_do_not_read_config_write_files_spawn_or_connect(self):
        root = Path(__file__).resolve().parents[1]
        code = '''
import os, sys, socket, subprocess, threading
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
with mock.patch.object(Path, 'open', side_effect=AssertionError('filesystem I/O')), \\
     mock.patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir')), \\
     mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('spawn')), \\
     mock.patch.object(socket, 'socket', side_effect=AssertionError('network')), \\
     mock.patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')):
    from jarvisd_core import auth, commands, config, diagnostics, events, http_input, logging, state, devices, admission, control
print('core imports are side-effect-free')
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)],
                                capture_output=True, text=True, timeout=10, env={})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("side-effect-free", result.stdout)


if __name__ == "__main__":
    unittest.main()
