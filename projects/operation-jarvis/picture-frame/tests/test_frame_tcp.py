"""Offline optional TCP tests. No real dependencies, keys, photos or traffic."""
import copy
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frame_control import (AdbError, Controller, FrameError, PNG_SIGNATURE,
                           read_json, save_json)
from frame_cli import execute, parser
from frame_tcp import (ARCHIVE_SHA256, DirectTcpAdb, deadline, load_dependencies)
from install_tcp_deps import install

TARGET = "192.168.1.20:5555"
PACKAGE = "net.frameo.frame"
IDENTITY = {"hardware_serial": "SYNTHETIC", "manufacturer": "TestMaker",
            "model": "TestFrame", "build_fingerprint": "test/frame:1"}
PNG = PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1280, 800) + b"\x08\x02\x00\x00\x00" + b"\x00" * 4


class FakeDevice:
    def __init__(self):
        self.connects = 0
        self.closed = False
        self.commands = []
        self.identity = copy.deepcopy(IDENTITY)
        self.sign = True
        self.request_new_key = False
        self.exit_code = 0
        self.omit_marker = False
        self.timeout = False
        self.push_failed = False
        self.pushes = []

    def connect(self, **kwargs):
        self.connects += 1
        assert len(kwargs["rsa_keys"]) == 1
        if self.sign:
            kwargs["rsa_keys"][0].Sign(b"synthetic challenge")
        if self.request_new_key:
            kwargs["rsa_keys"][0].GetPublicKey()
        return True

    def close(self):
        self.closed = True

    def shell(self, command, **kwargs):
        import shlex
        if self.timeout:
            signal.raise_signal(signal.SIGALRM)
        actual = shlex.split(command)[2].removesuffix(";")
        self.commands.append(actual)
        values = {"getprop ro.serialno": self.identity["hardware_serial"],
                  "getprop ro.product.manufacturer": self.identity["manufacturer"],
                  "getprop ro.product.model": self.identity["model"],
                  "getprop ro.build.fingerprint": self.identity["build_fingerprint"],
                  "getprop ro.adb.secure": "1", "pm list packages": "package:" + PACKAGE,
                  "settings get system screen_brightness": "0",
                  "settings get system screen_brightness_mode": "0",
                  "dumpsys power": "Display Power: state=ON"}
        output = values.get(actual, "readback").encode()
        if self.omit_marker:
            return output
        marker = re.search(r"JARVIS_EXIT_[0-9a-f]{32}", command).group()
        return output + b"\n" + marker.encode() + b":" + str(self.exit_code).encode() + b"\n"

    def exec_out(self, command, **kwargs):
        assert command == "screencap -p" and kwargs["decode"] is False
        self.commands.append(command)
        return PNG

    def push(self, source, target, **kwargs):
        self.pushes.append((source, target))
        if self.push_failed:
            raise RuntimeError("DO_NOT_LEAK_PRIVATE_PATH_OR_KEY")


class TcpTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.key = self.root / "adbkey"
        self.key.write_text("synthetic-not-a-real-key")
        self.key.chmod(0o600)
        Path(str(self.key) + ".pub").write_text("synthetic-public-key")
        self.device = FakeDevice()
        self.factories = []
        self.signer_reads = []

        def factory(host, port, **kwargs):
            self.factories.append((host, port))
            return self.device

        def signer_factory(key):
            self.signer_reads.append(key)
            class Signer:
                def Sign(self, challenge):
                    return b"synthetic signature"
            return Signer()

        self.backend = DirectTcpAdb(self.root / "unused-deps", self.key,
                                    factory=factory, signer_factory=signer_factory)
        self.addCleanup(self.backend.close)
        self.config = self.root / "private/config.json"
        save_json(self.config, {"schema_version": 1, "serial": "USB_TEST",
                                "identity": IDENTITY, "package": PACKAGE})

    def test_constructor_does_not_read_keys_or_create_state(self):
        self.assertEqual(self.factories, [])
        self.assertEqual(self.signer_reads, [])
        self.assertFalse((self.root / "unused-deps").exists())

    def test_public_hostname_usb_and_invalid_targets_never_connect(self):
        for serial in ("8.8.8.8:5555", "frame.local:5555", "USB_TEST", "192.168.1.20:0"):
            with self.subTest(serial=serial), self.assertRaises(FrameError):
                DirectTcpAdb(self.root, self.key, self.backend.factory,
                             self.backend.signer_factory).call(["get-state"], serial=serial)
        self.assertEqual(self.factories, [])
        self.assertEqual(self.signer_reads, [])

    def test_unsupported_commands_and_discovery_never_connect(self):
        for args in (["connect", TARGET], ["tcpip", "5555"], ["pull", "/private"],
                     ["install", "a.apk"], ["exec-out", "cat", "/private"]):
            with self.assertRaises(FrameError):
                self.backend.call(args, serial=TARGET)
        with self.assertRaises(FrameError):
            self.backend.devices()
        self.assertEqual(self.factories, [])

    def test_authentication_once_and_no_host_adb_server(self):
        self.assertEqual(self.backend.call(["get-state"], serial=TARGET), "device")
        self.assertEqual(self.backend.shell(TARGET, "getprop", "ro.serialno"), "SYNTHETIC")
        self.assertEqual(self.device.connects, 1)
        self.assertEqual(self.factories, [("192.168.1.20", 5555)])

    def test_peer_without_rsa_challenge_is_rejected(self):
        self.device.sign = False
        with self.assertRaisesRegex(FrameError, "RSA authentication"):
            self.backend.call(["get-state"], serial=TARGET)
        self.assertTrue(self.device.closed)

    def test_unaccepted_key_does_not_send_new_public_key_request(self):
        self.device.request_new_key = True
        with self.assertRaisesRegex(FrameError, "no new key request"):
            self.backend.call(["get-state"], serial=TARGET)
        self.assertTrue(self.device.closed)

    def test_private_key_symlink_and_shared_permissions_rejected(self):
        self.key.chmod(0o644)
        with self.assertRaises(FrameError):
            self.backend.call(["get-state"], serial=TARGET)
        self.assertEqual(self.factories, [])
        self.key.chmod(0o600)
        link = self.root / "link"
        link.symlink_to(self.key)
        alternate = DirectTcpAdb(self.root, link, self.backend.factory, self.backend.signer_factory)
        with self.assertRaises(FrameError):
            alternate.call(["get-state"], serial=TARGET)
        self.assertEqual(self.factories, [])

    def test_nonzero_remote_exit_fails_and_never_reconnects(self):
        self.device.exit_code = 1
        with self.assertRaises(AdbError):
            self.backend.shell(TARGET, "test", "-d", "/sdcard/DCIM")
        with self.assertRaises(FrameError):
            self.backend.call(["get-state"], serial=TARGET)
        self.assertEqual(self.device.connects, 1)

    def test_missing_remote_exit_marker_fails_closed(self):
        self.device.omit_marker = True
        with self.assertRaises(AdbError):
            self.backend.shell(TARGET, "getprop", "ro.serialno")

    def test_screenshot_bytes_are_unchanged(self):
        self.assertEqual(self.backend.call(["exec-out", "screencap", "-p"],
                                          serial=TARGET, binary=True), PNG)

    def test_total_deadline_is_sanitized_and_no_replay(self):
        self.device.timeout = True
        with self.assertRaisesRegex(AdbError, "deadline"):
            self.backend.shell(TARGET, "dumpsys", "power")
        self.assertTrue(self.device.closed)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        with self.assertRaises(FrameError):
            self.backend.shell(TARGET, "dumpsys", "power")
        self.assertEqual(self.device.connects, 1)

    def test_unsafe_push_path_rejected_before_key_or_network(self):
        staged = self.root / "photo.png"
        staged.write_bytes(PNG)
        staged.chmod(0o600)
        with self.assertRaises(FrameError):
            self.backend.call(["push", str(staged), "/sdcard/other.png"], serial=TARGET)
        self.assertEqual(self.factories, [])

    def test_push_failure_is_sanitized_without_replay(self):
        staged = self.root / "photo.png"
        staged.write_bytes(PNG)
        staged.chmod(0o600)
        self.device.push_failed = True
        destination = "/sdcard/DCIM/jarvis-" + "0" * 64 + ".png.part"
        with self.assertRaises(AdbError) as error:
            self.backend.call(["push", str(staged), destination], serial=TARGET)
        self.assertNotIn("DO_NOT_LEAK", str(error.exception))
        self.assertEqual(len(self.device.pushes), 1)

    def test_session_cannot_switch_targets_or_reopen_after_close(self):
        self.backend.call(["get-state"], serial=TARGET)
        with self.assertRaises(FrameError):
            self.backend.call(["get-state"], serial="192.168.1.21:5555")
        self.assertEqual(len(self.factories), 1)
        with self.assertRaises(FrameError):
            self.backend.call(["get-state"], serial=TARGET)

    def test_acceptance_preserves_identity_and_persists_backend(self):
        controller = Controller(self.backend, self.config)
        result = controller.connect_tcp(TARGET, apply=True)
        self.assertEqual(result["status"], "direct_tcp_selected")
        saved = read_json(self.config)
        self.assertEqual(saved["identity"], IDENTITY)
        self.assertEqual(saved["adb_backend"], "direct_tcp")
        self.assertEqual(saved["serial"], TARGET)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_no_rsa_challenge_keeps_usb_config_and_sends_no_remote_commands(self):
        self.device.sign = False
        with self.assertRaisesRegex(FrameError, "RSA authentication"):
            Controller(self.backend, self.config).connect_tcp(TARGET, apply=True)
        self.assertEqual(read_json(self.config)["serial"], "USB_TEST")
        self.assertNotIn("adb_backend", read_json(self.config))
        self.assertEqual(self.device.commands, [])
        self.assertEqual(self.device.pushes, [])
        self.assertTrue(self.device.closed)

    def test_other_backend_cannot_accept_direct_tcp(self):
        with self.assertRaisesRegex(FrameError, "in-process backend"):
            Controller(None, self.config).connect_tcp(TARGET, apply=True)
        self.assertEqual(read_json(self.config)["serial"], "USB_TEST")

    def test_explicit_usb_selection_restores_platform_tools(self):
        save_json(self.config, {"schema_version": 1, "serial": TARGET,
                                "identity": IDENTITY, "package": PACKAGE,
                                "adb_backend": "direct_tcp"})
        class UsbBackend:
            def probe(self, serial, package):
                assert serial == "USB_TEST"
                return {"identity": IDENTITY}
        with patch("frame_cli.Adb", return_value=UsbBackend()), patch(
                "frame_tcp.DirectTcpAdb", side_effect=AssertionError("No TCP construction")):
            args = parser().parse_args(["--config", str(self.config), "use-transport",
                                        "--serial", "USB_TEST", "--apply"])
            self.assertEqual(execute(args)["status"], "transport_updated")
        self.assertNotIn("adb_backend", read_json(self.config))

    def test_changed_identity_never_selects_tcp_or_writes_device(self):
        self.device.identity["model"] = "NotTheFrame"
        with self.assertRaises(FrameError):
            Controller(self.backend, self.config).connect_tcp(TARGET, apply=True)
        self.assertEqual(read_json(self.config)["serial"], "USB_TEST")
        self.assertFalse((self.config.parent / "pending.json").exists())
        self.assertEqual(self.device.pushes, [])

    def test_pending_write_blocks_tcp_acceptance_before_auth(self):
        save_json(self.config.parent / "pending.json", {"operation": "upload"})
        with self.assertRaises(FrameError):
            Controller(self.backend, self.config).connect_tcp(TARGET, apply=True)
        self.assertEqual(self.factories, [])

    def test_cli_tcp_dry_runs_load_no_dependency_key_or_state(self):
        missing = self.root / "never-created/config.json"
        commands = (["connect-tcp", "--serial", TARGET], ["screenshot"], ["sleep"],
                    ["wake"], ["brightness", "180"], ["upload", str(self.root / "missing.png")])
        with patch("frame_tcp.load_dependencies", side_effect=AssertionError("No imports")):
            for command in commands:
                args = parser().parse_args(["--config", str(missing), "--direct-tcp", *command])
                self.assertEqual(execute(args)["status"], "dry_run")
        self.assertFalse(missing.parent.exists())

    def test_saved_backend_is_selected_and_closed_for_status(self):
        save_json(self.config, {"schema_version": 1, "serial": TARGET,
                                "identity": IDENTITY, "package": PACKAGE,
                                "adb_backend": "direct_tcp"})
        with patch("frame_tcp.DirectTcpAdb", return_value=self.backend) as constructor:
            result = execute(parser().parse_args(["--config", str(self.config), "status"]))
        self.assertTrue(result["identity_matches"])
        constructor.assert_called_once()
        self.assertTrue(self.device.closed)

    def test_direct_tcp_config_cannot_use_usb(self):
        saved = read_json(self.config)
        saved["adb_backend"] = "direct_tcp"
        save_json(self.config, saved)
        with self.assertRaises(FrameError):
            Controller(None, self.config).config()

    def test_dependency_installer_dry_run_never_fetches_or_creates_runtime(self):
        config = self.root / "no-install/config.json"
        result = install(config, fetch=lambda: self.fail("Must not fetch"))
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(config.parent.exists())

    def test_dependency_digest_mismatch_does_not_install(self):
        with patch("install_tcp_deps.importlib.util.find_spec", return_value=object()):
            with self.assertRaisesRegex(FrameError, "digest"):
                install(self.config, apply=True, fetch=lambda: b"untrusted archive")
        self.assertFalse((self.config.parent / "tcp-deps").exists())

    def test_changed_dependency_manifest_fails_before_import(self):
        root = self.config.parent / "tcp-deps"
        root.mkdir(mode=0o700)
        package = root / "adb_shell"
        package.mkdir(mode=0o700)
        source = package / "__init__.py"
        source.write_text("# synthetic\n")
        source.chmod(0o600)
        save_json(root / "installed.json", {"archive_sha256": ARCHIVE_SHA256,
                  "files": {"adb_shell/__init__.py": "0" * 64}})
        with patch("frame_tcp.importlib.import_module", side_effect=AssertionError("Must not import")):
            with self.assertRaises(FrameError):
                load_dependencies(root)

    def test_deadline_does_not_override_an_existing_timer(self):
        signal.setitimer(signal.ITIMER_REAL, 30)
        try:
            with self.assertRaises(FrameError):
                with deadline(1):
                    self.fail("Must not run")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    unittest.main()
