"""Internal adapters against synthetic vendor processes and legacy CLI fixtures.

Never loads host configuration, SDKs, or devices. The public CLI is evaluated
only from a synthetic checkout, with vendor execution replaced by mocks.
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_jarvisd import jarvisd as d
from jarvisd_core import device_translation, device_worker
from jarvisd_core.commands import CommandError
from jarvisd_core.device_collectors import collect_plugs, collect_purifier
from jarvisd_core.device_transport import DeviceAdapterRunner
from jarvisd_core.device_vendor import DeviceVendorAdapter

DAEMON = Path(__file__).resolve().parents[1]
LEGACY = DAEMON.parent / "jarvis.py"


class AdapterFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.op = self.root / "projects/operation-jarvis"
        self.op.mkdir(parents=True)
        for directory in ("smart-plug/.venv/bin", "air-purifier"):
            (self.op / directory).mkdir(parents=True)
        (self.op / "smart-plug/.venv/bin/python").touch()
        (self.op / "air-purifier/purifier-cli").touch()
        self.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
        self.adapter = DeviceVendorAdapter(operation_root=self.op, project_root=self.root, env={}, run=self.run)
        self.prefix = ["--operation-root", str(self.op), "--project-root", str(self.root), "--json"]

    def bound_words(self, words):
        words = list(words)
        if words[0] in {"plug-on", "plug-off", "plug-toggle"} and "--expected-host" not in words:
            words += ["--expected-host", "192.0.2.1"]
        if words[0] == "purifier-set" and "--expected-cid" not in words:
            if "--purifier" not in words:
                words += ["--purifier", "synthetic-cid"]
            words += ["--expected-cid", words[words.index("--purifier") + 1]]
        return words

    def args(self, *words):
        return device_worker.build_parser().parse_args([*self.prefix, *self.bound_words(words)])

    def legacy(self):
        path = self.op / "jarvis.py"
        shutil.copyfile(LEGACY, path)
        spec = importlib.util.spec_from_file_location("synthetic_legacy_cli", path)
        module = importlib.util.module_from_spec(spec)
        # All inferred env paths and optional Cast imports belong to this fake checkout.
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "path", []):
            spec.loader.exec_module(module)
        return module


class LegacyParityTests(AdapterFixture):
    def test_local_system_status_matches_legacy_without_subprocess_calls(self):
        legacy = self.legacy()
        for preferred in (None, self.root / ".venv/bin/python", self.op / ".venv/bin/python"):
            if preferred is not None:
                preferred.parent.mkdir(parents=True, exist_ok=True)
                preferred.touch()
            args = legacy.build_parser().parse_args(["status", "--no-cast"])
            old = legacy.handle_status(args)
            new = self.adapter.handle_local_status(self.args("status", "--no-cast"))
            self.assertEqual(new, old)
        self.run.assert_not_called()

    def test_translation_functions_are_structurally_identical_to_legacy(self):
        old = {n.name: n for n in ast.parse(LEGACY.read_text()).body if isinstance(n, ast.FunctionDef)}
        new = ast.parse(Path(device_translation.__file__).read_text())
        for node in new.body:
            if isinstance(node, ast.FunctionDef):
                self.assertEqual(ast.dump(node), ast.dump(old[node.name]), node.name)

    def compare(self, words, data):
        legacy = self.legacy()
        old_args = legacy.build_parser().parse_args(["--json", *words])
        new_args = self.args(*words)
        completed = subprocess.CompletedProcess([], 0, json.dumps(data), "vendor diagnostic")
        self.run.return_value = completed
        with mock.patch.object(legacy.subprocess, "run", return_value=completed) as old_run, \
             mock.patch.dict(os.environ, {}, clear=True):
            old = old_args.func(old_args)
            new = getattr(self.adapter, device_worker.HANDLERS[new_args.command])(new_args)
        def without_binding(value):
            if isinstance(value, dict):
                return {key: without_binding(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                result, skip = [], False
                for item in value:
                    if skip:
                        skip = False
                    elif isinstance(item, str) and item in {"--expected-host", "--expected-cid"}:
                        skip = True
                    else:
                        result.append(without_binding(item))
                return type(value)(result)
            return value
        self.assertEqual(without_binding(new), old)
        self.assertEqual(without_binding(self.run.call_args.args), old_run.call_args.args)
        old_kwargs = dict(old_run.call_args.kwargs)
        old_kwargs.setdefault("env", {})  # Legacy purifier inherited this synthetic empty environment.
        self.assertEqual(self.run.call_args.kwargs, old_kwargs)
        self.assertEqual(self.run.call_count, 1)
        self.run.reset_mock()
        return new

    def test_all_plug_actions_preserve_argv_environment_and_payload(self):
        for action in ("plug-status", "plug-on", "plug-off", "plug-toggle"):
            with self.subTest(action=action):
                self.compare([action, "lamp"], {"name": "lamp", "host": "192.0.2.1", "is_on": True})
        self.compare(["plug-list"], {"lamp": "192.0.2.1"})

    def test_all_purifier_settings_and_selected_identity_preserve_argv_and_payload(self):
        settings = [("power", "on"), ("power", "off"), ("power", "toggle"), ("mode", "auto"),
                    ("mode", "sleep"), ("speed", "--level", "2"), ("display", "off"),
                    ("child-lock", "on"), ("light-detection", "off"),
                    ("auto-preference", "efficient", "--room-size", "500"),
                    ("timer", "--minutes", "60"), ("timer", "clear")]
        for setting, *values in settings:
            with self.subTest(setting=setting, values=values):
                self.compare(["purifier-set", setting, "--purifier", "synthetic-cid", *values],
                             {"cid": "synthetic-cid", "name": "Fixture", "is_on": True,
                              "verification_pending": True, "write_accepted": True})

    def test_purifier_single_batch_partial_failure_and_recovery(self):
        self.compare(["purifier-status"], {"cid": "a", "name": "Fixture", "is_on": True})
        self.compare(["purifier-status", "--purifier", "a", "--retry-cooldown"], {"cid": "a"})
        data = {"a": {"ok": True, "isDefault": True, "status": {"cid": "a", "name": "First"}},
                "b": {"ok": False, "name": "Second", "error": "failed"}}
        self.compare(["purifier-status-all"], data)
        self.compare(["purifier-status-all", "--retry-cooldown"], data)

    def test_vendor_exit_error_and_non_json_semantics_match_legacy(self):
        legacy = self.legacy()
        for action, payload, code in (("plug-status", "bad", 1), ("purifier-status", '{"error":"failed"}', 1),
                                      ("plug-status", "non-json", 0), ("purifier-status", "[]", 0)):
            words = [action, "lamp"] if action.startswith("plug") else [action]
            args = self.args(*words)
            result = subprocess.CompletedProcess([], code, payload, "diagnostic")
            self.run.return_value = result
            with self.subTest(action=action, code=code), mock.patch.object(legacy.subprocess, "run", return_value=result):
                old_args = legacy.build_parser().parse_args(words)
                if code:
                    with self.assertRaises(Exception) as old:
                        old_args.func(old_args)
                    with self.assertRaises(Exception) as new:
                        getattr(self.adapter, device_worker.HANDLERS[action])(args)
                    self.assertEqual(str(new.exception), str(old.exception))
                else:
                    self.assertEqual(getattr(self.adapter, device_worker.HANDLERS[action])(args), old_args.func(old_args))

    def test_invalid_setting_values_never_execute_vendor(self):
        for words in (("power",), ("speed", "--level", "5"), ("timer", "--minutes", "0"),
                      ("display", "toggle"), ("mode", "invalid")):
            with self.subTest(words=words):
                code, payload = device_worker.execute(self.args("purifier-set", *words), adapter=self.adapter, emit=mock.Mock())
                self.assertEqual(code, 1)
                self.assertFalse(payload["ok"])
        self.run.assert_not_called()

    def test_purifier_wait_and_environment_are_forwarded_explicitly(self):
        self.adapter.env = {"JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS": "15", "SYNTHETIC": "yes"}
        self.adapter.run_air_purifier_command(["status"], timeout=150)
        self.assertEqual(self.run.call_args.kwargs["env"], self.adapter.env)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 150)
        self.assertNotIn("start_new_session", self.run.call_args.kwargs)

    def test_plug_environment_overrides_are_preserved_without_mutating_parent(self):
        self.adapter.env = {"KASA_TIMEOUT": "17", "PYTHONDONTWRITEBYTECODE": "0", "SYNTHETIC": "yes"}
        self.adapter.run_smart_plug_command(["status", "lamp"], timeout=30)
        self.assertEqual(self.run.call_args.kwargs["env"], self.adapter.env)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 40)


class WorkerLifecycleTests(AdapterFixture):
    def test_private_parser_excludes_discovery_paths_shell_and_write_recovery(self):
        invalid = [["plug-discover"], ["plug-save-discovery"], ["purifier-list"], ["status"],
                   ["security-disarm"], ["cast-status"], ["plug-list", "--plug-config", "/tmp/x"],
                   ["plug-on", "lamp", "--discovery-target", "192.0.2.255"],
                   ["purifier-set", "power", "on", "--retry-cooldown"],
                   ["purifier-status-all", "--retry"], ["plug-list", "--plug-timeout", "999"]]
        for words in invalid:
            with self.subTest(words=words), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.args(*words)
        self.run.assert_not_called()

    def test_worker_write_requires_identity_binding(self):
        for words in (["plug-on", "lamp"], ["plug-off", "lamp"], ["plug-toggle", "lamp"],
                      ["purifier-set", "power", "on", "--purifier", "a"]):
            with self.subTest(words=words), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                device_worker.build_parser().parse_args([*self.prefix, *words])
        self.run.assert_not_called()

    def test_private_cid_is_removed_from_vendor_failures_and_events(self):
        cid = "synthetic-private-identifier"
        self.run.side_effect = RuntimeError(f"failed for --expected-cid {cid}")
        emit = mock.Mock()
        code, result = device_worker.execute(self.args("purifier-set", "power", "on", "--purifier", cid),
                                             adapter=self.adapter, emit=emit)
        self.assertEqual(code, 1)
        self.assertNotIn(cid, json.dumps(result))
        self.assertNotIn(cid, str(emit.call_args_list))
        self.assertIn("[private device]", result["error"])

    def test_worker_mismatched_purifier_binding_rejects_before_vendor_call(self):
        args = self.args("purifier-set", "power", "on", "--purifier", "a", "--expected-cid", "b")
        code, result = device_worker.execute(args, adapter=self.adapter, emit=mock.Mock())
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.run.assert_not_called()

    def test_environment_is_loaded_explicitly_with_legacy_precedence(self):
        (self.root / ".env").write_text("export SHARED='project'\nEXISTING=override\n# note\n")
        (self.op / ".env").write_text('SHARED=operation\nONLY_OPERATION="yes"\n')
        env = {"EXISTING": "process"}
        device_worker.load_environment(self.root, self.op, env)
        self.assertEqual(env, {"EXISTING": "process", "SHARED": "project", "ONLY_OPERATION": "yes"})

    def test_success_events_preserve_source_action_and_result_contract(self):
        emit = mock.Mock()
        code, payload = device_worker.execute(self.args("plug-list"), adapter=self.adapter, emit=emit)
        self.assertEqual(code, 0)
        self.assertEqual(payload["operationRoot"], str(self.op))
        self.assertEqual([c.args[0] for c in emit.call_args_list], ["action.start", "action.complete"])
        self.assertEqual(emit.call_args.kwargs["data"], {"device": None})
        self.run.assert_called_once()

    def test_timeout_failure_and_cancel_each_invoke_adapter_once(self):
        for error, code in ((subprocess.TimeoutExpired(["synthetic"], 5), 124),
                            (RuntimeError("ambiguous"), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(error=type(error)):
                self.run.reset_mock()
                self.run.side_effect = error
                emit = mock.Mock()
                result_code, payload = device_worker.execute(self.args("plug-on", "lamp"), adapter=self.adapter, emit=emit)
                self.assertEqual(result_code, code)
                self.assertFalse(payload["ok"])
                self.run.assert_called_once()
                self.assertEqual([c.args[0] for c in emit.call_args_list], ["action.start", "action.error"])

    def test_collector_event_suppression_and_empty_sink_do_no_network_io(self):
        for env in ({"JARVIS_EMIT_EVENTS": "0"}, {"JARVIS_EMIT_EVENTS": "false"}, {"JARVISD_URL": ""}):
            open_url = mock.Mock()
            device_worker.LifecycleBridge(env, open_url=open_url)("action.start", action="plug-list")
            open_url.assert_not_called()

    def test_event_token_is_preferred_and_existing_ingest_endpoint_retained(self):
        open_url = mock.MagicMock()
        bridge = device_worker.LifecycleBridge({"JARVISD_URL": "http://127.0.0.1:9999/",
                                               "JARVISD_EVENT_TOKEN": "fixture-event", "JARVIS_API_TOKEN": "fixture-api"},
                                              open_url=open_url)
        bridge("action.start", action="plug-on", summary="Starting plug-on.")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9999/api/jarvis/events")
        self.assertEqual(request.get_header("X-jarvis-token"), "fixture-event")
        payload = json.loads(request.data)
        self.assertEqual(payload["source"], "operation-jarvis")
        self.assertEqual(payload["action"], "plug-on")
        self.assertNotIn("fixture-event", request.data.decode())
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 2.0})

    def test_event_failure_never_retries_or_fails_device_action(self):
        open_url = mock.Mock(side_effect=OSError("offline"))
        emit = device_worker.LifecycleBridge({}, open_url=open_url)
        code, _ = device_worker.execute(self.args("plug-on", "lamp"), adapter=self.adapter, emit=emit)
        self.assertEqual(code, 0)
        self.run.assert_called_once()
        self.assertEqual(open_url.call_count, 2)  # start and completion, not retries


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.run = mock.Mock(return_value={"ok": True})
        self.runner = DeviceAdapterRunner(cli=Path("/operation/jarvis-cli"), worker=Path("/frozen/device-worker.py"),
            python="/fixed/python", operation_root=Path("/operation"), project_root=Path("/project"), run=self.run)

    def test_every_device_action_uses_private_worker_with_fixed_roots(self):
        for action in device_worker.HANDLERS:
            with self.subTest(action=action):
                self.run.reset_mock()
                tail = [action, "--no-cast"] if action == "status" else [action]
                self.runner(["/operation/jarvis-cli", "--json", *tail], timeout=10, env={"JARVIS_EMIT_EVENTS": "0"})
                self.run.assert_called_once_with([*self.runner.worker_prefix(), *tail], timeout=10, env={"JARVIS_EMIT_EVENTS": "0"})
                self.assertNotIn("/operation/jarvis-cli", self.run.call_args.args[0])

    def test_only_exact_local_system_status_uses_worker_without_legacy_bridge(self):
        argv = ["/operation/jarvis-cli", "--json", "status", "--no-cast"]
        self.runner(argv, timeout=30)
        self.run.assert_called_once_with([*self.runner.worker_prefix(), "status", "--no-cast"], timeout=30, env=None)
        for argv in (["/other", "--json", "plug-on"], ["/operation/jarvis-cli", "--json", "status"],
                     ["/operation/jarvis-cli", "--json", "cast-status"], ["/operation/jarvis-cli", "--json", "plug-save-discovery"]):
            with self.subTest(argv=argv), self.assertRaises(CommandError):
                self.runner(argv)
        self.assertEqual(self.run.call_count, 1)

    def test_failed_worker_never_falls_back_to_public_cli(self):
        for result in ({"ok": False, "error": "missing worker"}, {"ok": False, "error": "timed out"}):
            self.run.reset_mock()
            self.run.return_value = result
            self.assertEqual(self.runner(["/operation/jarvis-cli", "--json", "plug-on", "lamp"]), result)
            self.run.assert_called_once()
        self.run.side_effect = OSError("worker unavailable")
        self.run.reset_mock()
        with self.assertRaises(OSError):
            self.runner(["/operation/jarvis-cli", "--json", "plug-on", "lamp"])
        self.run.assert_called_once()

    def test_outer_timeout_kills_worker_process_group_without_replay(self):
        proc = mock.Mock(pid=424242, returncode=-9)
        proc.communicate.side_effect = [subprocess.TimeoutExpired("fixture", 0.5), ("", "diagnostic")]
        with mock.patch.object(d.subprocess, "Popen", return_value=proc) as popen, \
             mock.patch.object(d.os, "killpg") as kill:
            result = d.run_device_adapter([str(d.JARVIS_CLI), "--json", "plug-on", "lamp"], timeout=0.5)
        self.assertFalse(result["ok"])
        popen.assert_called_once()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        kill.assert_called_once_with(proc.pid, d.signal.SIGKILL)
        self.assertEqual(proc.communicate.call_args_list, [mock.call(timeout=0.5), mock.call()])

    def test_daemon_wires_dispatch_and_both_collectors_to_private_transport(self):
        with mock.patch.object(d, "run_cli_json", return_value={"ok": True, "plugs": {}, "purifiers": {}}) as run:
            d._plugs()
            d._purifier(retry=True)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:3], [sys.executable, "-B", str(d.DEVICE_WORKER)])
            self.assertEqual(call.kwargs["env"], {"JARVIS_EMIT_EVENTS": "0"})
        self.assertEqual(run.call_args.args[0][-2:], ["purifier-status-all", "--retry-cooldown"])


class CollectorTests(unittest.TestCase):
    def test_empty_failed_and_invalid_plug_catalogue_remain_distinct(self):
        for listing, expected in (({"ok": True, "plugs": {}}, True), ({"ok": False}, False),
                                  ({"ok": True, "plugs": ["invalid"]}, False)):
            run = mock.Mock(return_value=listing)
            result = collect_plugs(run_cli_json=run, cli=Path("/fixed"), env={})
            self.assertEqual(result["ok"], expected)
            run.assert_called_once()

    def test_plug_partial_failure_keeps_peer_and_configured_host(self):
        def run(argv, **kwargs):
            if argv[-1] == "plug-list":
                return {"ok": True, "plugs": {"a": "192.0.2.1", "b": "192.0.2.2"}}
            if argv[-1] == "a":
                return {"ok": True, "plug": {"host": "192.0.2.1", "is_on": True}}
            raise TimeoutError("fixture timeout")
        result = collect_plugs(run_cli_json=run, cli=Path("/fixed"), env={})
        self.assertTrue(result["ok"])
        self.assertEqual(result["onCount"], 1)
        self.assertEqual(result["plugs"]["b"]["host"], "192.0.2.2")
        self.assertFalse(result["plugs"]["b"]["ok"])

    def test_purifier_failure_does_not_replace_private_selectors(self):
        result, selectors = collect_purifier(run_cli_json=mock.Mock(return_value={"ok": False, "error": "offline"}),
                                             cli=Path("/fixed"), env={})
        self.assertFalse(result["ok"])
        self.assertIsNone(selectors)
        result, selectors = collect_purifier(run_cli_json=mock.Mock(return_value={"ok": True, "purifiers": {}}),
                                             cli=Path("/fixed"), env={})
        self.assertTrue(result["ok"])
        self.assertEqual(selectors, {})

    def test_partial_purifier_batch_has_private_selectors_but_public_opaque_ids(self):
        raw = {"a": {"ok": True, "isDefault": True, "status": {"cid": "a", "is_on": True}},
               "b": {"ok": False, "name": "Fixture", "error": "private diagnostic"}}
        result, selectors = collect_purifier(run_cli_json=mock.Mock(return_value={"purifiers": raw}), cli=Path("/fixed"), env={})
        self.assertEqual(set(selectors.values()), {"a", "b"})
        self.assertNotIn("private diagnostic", json.dumps(result))
        self.assertTrue(result["devices"][result["defaultDeviceID"]]["ok"])
        self.assertEqual(set(result["devices"]), {d._purifier_id("a"), d._purifier_id("b")})
        self.assertTrue(all(len(key) == 24 for key in result["devices"]))


class FrozenWorkerTests(AdapterFixture):
    def frozen(self):
        frozen = self.root / "artifact"
        frozen.mkdir()
        shutil.copyfile(DAEMON / "device-worker.py", frozen / "device-worker.py")
        shutil.copytree(DAEMON / "jarvisd_core", frozen / "jarvisd_core", ignore=shutil.ignore_patterns("__pycache__"))
        # Poison public entry points. They must never be imported or invoked.
        (self.op / "jarvis.py").write_text("raise RuntimeError('PUBLIC CLI MUST NOT RUN')\n")
        (self.op / "jarvis-cli").write_text("#!/bin/sh\nexit 99\n")
        (self.op / "jarvis-cli").chmod(0o700)
        return frozen

    def fake_vendor(self, path, payload):
        path.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\np=Path({str(self.root / 'vendor-calls')!r})\nwith p.open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\nprint({json.dumps(payload)!r})\n")
        path.chmod(0o700)

    def test_frozen_worker_runs_fake_plug_and_purifier_without_public_cli(self):
        frozen = self.frozen()
        self.fake_vendor(self.op / "smart-plug/.venv/bin/python", {"name": "lamp", "host": "192.0.2.1", "is_on": True})
        self.fake_vendor(self.op / "air-purifier/purifier-cli", {"cid": "fixture", "is_on": True, "verification_pending": True})
        for words in (["plug-on", "lamp"], ["purifier-set", "power", "--purifier", "fixture", "on"]):
            result = subprocess.run([sys.executable, "-B", str(frozen / "device-worker.py"), *self.prefix, *self.bound_words(words)],
                cwd=self.root, env={"JARVIS_EMIT_EVENTS": "0", "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = json.loads(result.stdout)
            self.assertTrue(body["ok"])
            self.assertNotIn("PUBLIC CLI", result.stdout)
        calls = [json.loads(line) for line in (self.root / "vendor-calls").read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][-4:], ["on", "lamp", "--expected-host", "192.0.2.1"])
        self.assertEqual(calls[1], ["--json", "--expected-cid", "fixture", "on", "fixture"])
        self.assertEqual(list(frozen.rglob("__pycache__")), [])

    def test_frozen_system_status_never_imports_cli_or_executes_vendor(self):
        frozen = self.frozen()
        result = subprocess.run([sys.executable, "-B", str(frozen / "device-worker.py"), *self.prefix,
                                 "status", "--no-cast"], cwd=self.root,
                                env={"JARVIS_EMIT_EVENTS": "0"}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "status")
        self.assertIn("Cast status was skipped", body["summary"])
        self.assertFalse((self.root / "vendor-calls").exists())

    def test_public_result_never_exposes_worker_argv_or_raw_selector(self):
        raw = {"ok": True, "purifier": {"cid": "fixture-private-cid", "is_on": True},
               "airPurifier": {"command": ["/private/vendor", "fixture-private-cid"],
                               "data": {"cid": "fixture-private-cid", "is_on": True}}}
        result = d._public_command_result("purifier-set", raw)
        self.assertNotIn("fixture-private-cid", json.dumps(result))
        self.assertNotIn("/private/vendor", json.dumps(result))
        self.assertTrue(result["airPurifier"]["data"]["is_on"])

    def test_invalid_worker_invocation_exits_before_configuration_or_vendor_work(self):
        frozen = self.frozen()
        (self.op / ".env").write_text("not valid configuration but must never be loaded\n")
        result = subprocess.run([sys.executable, "-B", str(frozen / "device-worker.py"), *self.prefix, "plug-save-discovery"],
            cwd=self.root, env={}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "vendor-calls").exists())

    def test_new_modules_import_without_io_or_vendor_dependencies(self):
        frozen = self.frozen()
        script = '''
import builtins, importlib, pathlib, socket, subprocess, sys
from unittest import mock
sys.path.insert(0, sys.argv[1])
def denied(*a, **k): raise AssertionError('import-time I/O')
with mock.patch.object(pathlib.Path, 'read_text', denied), mock.patch.object(pathlib.Path, 'exists', denied), \\
     mock.patch.object(subprocess, 'Popen', denied), mock.patch.object(socket, 'socket', denied):
 for name in ('device_collectors','device_translation','device_vendor','device_worker','device_transport'):
  importlib.import_module('jarvisd_core.'+name)
assert not any(x in sys.modules for x in ('jarvis','kasa','pyvesync'))
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(frozen)], cwd=self.root, env={},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
