"""Offline owner-scoped legacy LAN and complete control-surface tests."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frame_control import (Controller, FrameError, backlight_state, read_json, save_json,
                           tcp_listener_ports, validate_legacy_approval)
from frame_cli import execute, parser
from frame_tcp import LegacyLanAdb
from test_frame_control import FakeAdb
from test_frame_tcp import FakeDevice, IDENTITY, PACKAGE, PNG, TARGET

USB = "FRAME_USB_TEST"
PROC_HEADER = "  sl  local_address rem_address st tx_queue rx_queue\n"


def approval():
    return {"schema_version": 1, "policy": "owner_accepted_unauthenticated_lan_adb",
            "accepted": True, "serial": TARGET, "package": PACKAGE,
            "identity": copy.deepcopy(IDENTITY),
            "accepted_at_utc": datetime.now(timezone.utc).isoformat()}


class UsbAdb(FakeAdb):
    def __init__(self):
        super().__init__()
        self.identity = copy.deepcopy(IDENTITY)
        self.package = PACKAGE
        self.tcp_port = "5555"
        self.persistent_port = ""
        self.usb_calls = 0
        self.bad_usb_reply = False
        self.listener_remains = False
        self.ip = TARGET.rsplit(":", 1)[0]

    def call(self, args, **kwargs):
        if args == ["usb"]:
            self.usb_calls += 1
            self.tcp_port = "0"
            return "unexpected" if self.bad_usb_reply else "restarting in USB mode"
        return super().call(args, **kwargs)

    def shell(self, serial, *args):
        if args == ("ip", "-4", "addr", "show", "wlan0"):
            self.calls.append(("shell", serial, args))
            return "2: wlan0:\n    inet " + self.ip + "/24 brd 192.168.1.255"
        if args == ("getprop", "service.adb.tcp.port"):
            return self.tcp_port
        if args == ("getprop", "persist.adb.tcp.port"):
            return self.persistent_port
        if args[0] == "cat" and args[1] in ("/proc/net/tcp", "/proc/net/tcp6"):
            if self.listener_remains or self.tcp_port == "5555":
                return PROC_HEADER + " 0: 00000000:15B3 00000000:0000 0A 0 0\n"
            return PROC_HEADER
        if args == ("dumpsys", "display"):
            return "Display Power State:\n    mScreenBrightness=75\n"
        return super().shell(serial, *args)


class LegacyDevice(FakeDevice):
    def __init__(self):
        super().__init__()
        self.requires_auth = False
        self.power = "Display Power: state=ON"
        self.brightness = "0"
        self.partial = False
        self.final = False
        self.size = 0
        self.fail_input = False
        self.focus = "mCurrentFocus=Window{123 u0 " + PACKAGE + "/.MainActivity}"

    def connect(self, **kwargs):
        self.connects += 1
        assert kwargs["rsa_keys"] == [], "Legacy transport must not read/send a host key"
        if self.requires_auth:
            raise FrameError("Firmware requires authentication; use the strict authenticated backend")
        return True

    def shell(self, command, **kwargs):
        actual = shlex.split(command)[2].removesuffix(";")
        if actual.startswith("input keyevent"):
            if self.fail_input:
                raise RuntimeError("unknown dispatch")
            self.power = "Display Power: state=" + ("ON" if actual.endswith("224") else "OFF")
        if actual.startswith("settings put system screen_brightness "):
            self.brightness = actual.split()[-1]
        value = None
        if actual == "dumpsys power": value = self.power
        elif actual == "dumpsys display": value = "mScreenBrightness=75"
        elif actual == "dumpsys window windows": value = self.focus
        elif actual == "settings get system screen_brightness": value = self.brightness
        elif actual == "test -d /sdcard/DCIM": value = ""
        elif actual.startswith("wc -c "): value = str(self.size) + " staged"
        elif actual.startswith("mv -n "):
            self.partial = False
            self.final = True
            value = ""
        elif actual.startswith("sh -c "):
            exists = (self.final or self.partial) if "||" in actual else self.partial
            value = "exists" if exists else "absent"
        output = super().shell(command, **kwargs)
        if value is not None:
            match = re.search(rb"\nJARVIS_EXIT_[0-9a-f]{32}:", output)
            return value.encode() + output[match.start():]
        return output

    def push(self, source, target, **kwargs):
        super().push(source, target, **kwargs)
        self.partial = True
        self.size = Path(source).stat().st_size


class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.config = self.root / "private/config.json"
        save_json(self.config, {"schema_version": 1, "serial": USB,
                                "package": PACKAGE, "identity": copy.deepcopy(IDENTITY)})
        self.usb = UsbAdb()
        self.device = LegacyDevice()
        self.factories = []
        self.policy = approval()

        def factory(host, port, **kwargs):
            self.factories.append((host, port))
            return self.device
        self.backend = LegacyLanAdb(self.root / "unused", self.policy, factory=factory)
        self.addCleanup(self.backend.close)

    def select(self):
        candidate = {**read_json(self.config), "serial": TARGET, "usb_serial": USB,
                     "adb_backend": "legacy_lan", "legacy_lan_approval": self.policy}
        save_json(self.config, candidate)

    def test_missing_or_false_approval_blocks_before_socket_or_dependency(self):
        for policy in (None, {}, {**self.policy, "accepted": False}, {**self.policy, "accepted": "true"}):
            backend = LegacyLanAdb(self.root, policy, factory=self.backend.factory)
            with self.assertRaises(FrameError):
                backend.call(["get-state"], serial=TARGET)
        self.assertEqual(self.factories, [])

    def test_scope_binds_each_endpoint_package_and_identity_field(self):
        for field in ("serial", "package", "identity"):
            changed = copy.deepcopy(self.policy)
            changed[field] = "wrong" if field != "identity" else {**IDENTITY, "model": "wrong"}
            with self.assertRaises(FrameError):
                validate_legacy_approval(changed, TARGET, PACKAGE, IDENTITY)
        with self.assertRaises(FrameError):
            self.backend.call(["get-state"], serial="192.168.1.21:5555")
        self.assertEqual(self.factories, [])

    def test_public_and_hostname_endpoint_cannot_be_approved(self):
        for target in ("8.8.8.8:5555", "frame.local:5555"):
            changed = {**self.policy, "serial": target}
            with self.assertRaises(FrameError):
                validate_legacy_approval(changed, target, PACKAGE, IDENTITY)

    def test_caller_cannot_mutate_session_approval(self):
        self.policy["serial"] = "192.168.1.21:5555"
        self.backend.call(["get-state"], serial=TARGET)
        self.assertEqual(self.factories, [("192.168.1.20", 5555)])

    def test_legacy_never_reads_key_and_firmware_auth_change_fails_closed(self):
        self.device.requires_auth = True
        with patch("frame_tcp.owned_path", side_effect=AssertionError("No key path access")):
            with self.assertRaises(FrameError):
                self.backend.call(["get-state"], serial=TARGET)
        self.assertTrue(self.device.closed)
        self.assertEqual(self.device.connects, 1)

    def test_content_and_control_blocked_until_pins_are_verified(self):
        for args, kwargs in ((["shell", "input keyevent 224"], {}),
                             (["exec-out", "screencap", "-p"], {"binary": True})):
            with self.assertRaises(FrameError):
                self.backend.call(args, serial=TARGET, **kwargs)
        self.assertEqual(self.factories, [])
        self.backend.probe(TARGET, PACKAGE)
        self.assertEqual(self.backend.call(["exec-out", "screencap", "-p"],
                                          serial=TARGET, binary=True), PNG)

    def test_each_changed_pin_stops_control(self):
        for field in IDENTITY:
            device = LegacyDevice()
            device.identity[field] = "different"
            backend = LegacyLanAdb(self.root, approval(), factory=lambda *a, **kw: device)
            with self.assertRaises(FrameError):
                backend.probe(TARGET, PACKAGE)
            self.assertTrue(device.closed)
            self.assertFalse(backend.identity_verified)
            self.assertEqual(device.pushes, [])

    def test_probe_cli_uses_exact_saved_legacy_endpoint(self):
        self.select()
        with patch("frame_tcp.LegacyLanAdb", return_value=self.backend):
            result = execute(parser().parse_args(["--config", str(self.config), "probe",
                                                  "--serial", TARGET, "--package", PACKAGE]))
        self.assertEqual(result["identity"], IDENTITY)
        self.assertEqual(result["transport"], "legacy_lan")
        self.assertTrue(self.device.closed)

    def test_status_marker_uses_echo_not_broken_numeric_formatter(self):
        captured = []
        original = self.device.shell
        def shell(command, **kwargs):
            captured.append(command)
            return original(command, **kwargs)
        self.device.shell = shell
        self.backend.probe(TARGET, PACKAGE)
        self.assertTrue(all("%d" not in command and "_jarvis_status=$?" in command
                            for command in captured))

    def test_explicit_usb_selection_revokes_private_legacy_consent(self):
        self.select()
        Controller(self.usb, self.config).use_transport(USB, apply=True)
        saved = read_json(self.config)
        self.assertNotIn("legacy_lan_approval", saved)
        self.assertNotIn("usb_serial", saved)
        self.assertNotIn("adb_backend", saved)

    def test_bad_approval_timestamp_fails_without_network(self):
        policy = {**approval(), "accepted_at_utc": "not a timestamp"}
        backend = LegacyLanAdb(self.root, policy, factory=self.backend.factory)
        with self.assertRaises(FrameError):
            backend.call(["get-state"], serial=TARGET)
        self.assertEqual(self.factories, [])

    def test_live_cli_uses_saved_policy_and_returns_security_warning(self):
        self.select()
        with patch("frame_tcp.LegacyLanAdb", return_value=self.backend):
            result = execute(parser().parse_args(["--config", str(self.config), "status"]))
        self.assertTrue(result["identity_matches"])
        self.assertEqual(result["adb_authentication"], "not_provided_by_device")
        self.assertIn("Other reachable LAN clients", result["security_warning"])
        self.assertTrue(self.device.closed)

    def test_legacy_acceptance_requires_explicit_flag_before_usb_read(self):
        self.usb.calls.clear()
        with self.assertRaises(FrameError):
            Controller(self.usb, self.config).connect_legacy_lan(TARGET, apply=True)
        self.assertEqual(self.usb.calls, [])
        self.assertEqual(read_json(self.config)["serial"], USB)

    def test_usb_first_acceptance_checks_frame_ip_and_preserves_pins(self):
        made = []
        def factory(deps, policy):
            made.append(policy)
            return LegacyLanAdb(deps, policy, factory=self.backend.factory)
        result = Controller(self.usb, self.config).connect_legacy_lan(
            TARGET, apply=True, accept_risk=True, factory=factory)
        self.assertEqual(result["status"], "legacy_lan_selected")
        saved = Controller(None, self.config).config()
        self.assertEqual(saved["usb_serial"], USB)
        self.assertEqual(saved["identity"], IDENTITY)
        self.assertEqual(saved["legacy_lan_approval"], made[0])
        self.assertEqual(saved["adb_backend"], "legacy_lan")

    def test_wrong_device_ip_and_pending_stop_acceptance_before_tcp(self):
        self.usb.ip = "192.168.1.99"
        with self.assertRaises(FrameError):
            Controller(self.usb, self.config).connect_legacy_lan(TARGET, apply=True, accept_risk=True,
                factory=lambda *a: self.fail("No TCP factory"))
        save_json(self.config.parent / "pending.json", {"operation": "sleep"})
        self.usb.calls.clear()
        with self.assertRaises(FrameError):
            Controller(self.usb, self.config).connect_legacy_lan(TARGET, apply=True, accept_risk=True)
        self.assertEqual(self.usb.calls, [])

    def test_bad_saved_policy_never_dispatches(self):
        self.select()
        saved = read_json(self.config)
        saved["identity"]["model"] = "changed"
        save_json(self.config, saved)
        with self.assertRaises(FrameError):
            Controller(self.backend, self.config).status()
        self.assertEqual(self.factories, [])

    def test_legacy_endpoint_change_requires_usb_reacceptance(self):
        self.select()
        with self.assertRaises(FrameError):
            Controller(self.backend, self.config).use_transport("192.168.1.21:5555", apply=True)
        self.assertEqual(self.factories, [])

    def test_all_write_dry_runs_read_no_policy_photo_key_or_network(self):
        missing = self.root / "never-created/config.json"
        commands = (["connect-legacy-lan", "--serial", TARGET], ["wifi-disable"],
                    ["sleep"], ["wake"], ["next"], ["previous"], ["brightness", "100"],
                    ["screenshot"], ["upload", str(self.root / "missing.png")])
        with patch("frame_tcp.load_dependencies", side_effect=AssertionError("No imports")):
            for command in commands:
                result = execute(parser().parse_args(["--config", str(missing), *command]))
                self.assertEqual(result["status"], "dry_run")
        self.assertFalse(missing.parent.exists())

    def test_complete_display_controls_use_same_legacy_pinned_controller(self):
        self.select()
        controller = Controller(self.backend, self.config)
        for action, value in (("sleep", None), ("wake", None), ("brightness", 180),
                              ("next", None), ("previous", None)):
            result = controller.control(action, value=value, apply=True, slideshow_ready=True)
            self.assertNotEqual(result["status"], "dry_run")
            self.assertFalse(controller.pending_path.exists())
        self.assertEqual(self.device.connects, 1)

    def test_unknown_legacy_write_keeps_pending_and_no_replay(self):
        self.select()
        self.device.fail_input = True
        controller = Controller(self.backend, self.config)
        with self.assertRaises(FrameError):
            controller.control("sleep", apply=True)
        self.assertTrue(controller.pending_path.exists())
        calls = self.device.connects
        with self.assertRaises(FrameError):
            controller.control("sleep", apply=True)
        self.assertEqual(self.device.connects, calls)

    def test_legacy_upload_staging_and_dedup_are_preserved(self):
        self.select()
        photo = self.root / "synthetic.png"
        photo.write_bytes(PNG)
        controller = Controller(self.backend, self.config)
        result = controller.upload(photo, apply=True, import_ready=True)
        self.assertEqual(result["status"], "transferred_import_unverified")
        self.assertTrue(self.device.final)
        self.assertFalse(self.device.partial)
        self.assertFalse(controller.pending_path.exists())
        with self.assertRaises(FrameError):
            controller.upload(photo, apply=True, import_ready=True)
        self.assertEqual(len(self.device.pushes), 1)

    def test_navigation_readiness_and_focus_still_gate_dispatch(self):
        self.select()
        controller = Controller(self.backend, self.config)
        with self.assertRaises(FrameError):
            controller.control("next", apply=True)
        self.assertEqual(self.factories, [])
        self.device.focus = "mCurrentFocus=Window{123 u0 other.app/.MainActivity}"
        with self.assertRaises(FrameError):
            controller.control("next", apply=True, slideshow_ready=True)
        self.assertFalse(controller.pending_path.exists())

    def test_backlight_and_local_inventory_are_available(self):
        value = Controller(self.usb, self.config).backlight()
        self.assertEqual(value["effective_backlight"], 75)
        missing = self.root / "no-inventory/config.json"
        inventory = execute(parser().parse_args(["--config", str(missing), "capabilities"]))
        self.assertFalse(inventory["device_contacted"])
        self.assertIn("wifi-disable", inventory["controls"])
        self.assertFalse(missing.parent.exists())

    def test_backlight_ambiguous_missing_and_out_of_range_are_unknown(self):
        self.assertIsNone(backlight_state("", "")["effective_backlight"])
        self.assertIsNone(backlight_state("mScreenBrightness=75\nmScreenBrightness=90", "")["effective_backlight"])
        self.assertIsNone(backlight_state("mScreenBrightness=999", "")["effective_backlight"])
        self.assertEqual(backlight_state("mScreenBrightness=75", "mScreenBrightnessOverrideFromWindowManager=75")
                         ["window_brightness_override"], 75)

    def test_wifi_disable_once_and_revoke_legacy_policy_after_verified_shutdown(self):
        self.select()
        with patch("frame_control.time.sleep"):
            result = Controller(self.usb, self.config).wifi_disable(apply=True)
        self.assertEqual(result["status"], "usb_only_verified")
        self.assertEqual(self.usb.usb_calls, 1)
        saved = read_json(self.config)
        self.assertEqual(saved["serial"], USB)
        self.assertNotIn("legacy_lan_approval", saved)
        self.assertNotIn("adb_backend", saved)
        self.assertFalse((self.config.parent / "pending.json").exists())

    def test_already_disabled_does_not_restart_daemon(self):
        self.usb.tcp_port = "0"
        result = Controller(self.usb, self.config).wifi_disable(apply=True)
        self.assertEqual(result["dispatch_count"], 0)
        self.assertEqual(self.usb.usb_calls, 0)

    def test_retirement_unknown_ack_or_listener_keeps_pending(self):
        for flag in ("bad_usb_reply", "listener_remains"):
            with self.subTest(flag=flag):
                pending = self.config.parent / "pending.json"
                if pending.exists(): pending.unlink()
                self.usb.tcp_port = "5555"
                self.usb.bad_usb_reply = flag == "bad_usb_reply"
                self.usb.listener_remains = flag == "listener_remains"
                with patch("frame_control.time.sleep"), self.assertRaises(FrameError):
                    Controller(self.usb, self.config).wifi_disable(apply=True)
                self.assertTrue(pending.exists())

    def test_cli_wifi_disable_uses_stock_usb_even_with_saved_legacy_policy(self):
        self.select()
        with patch("frame_cli.Adb", return_value=self.usb), patch("frame_control.time.sleep"), patch(
                "frame_tcp.LegacyLanAdb", side_effect=AssertionError("No LAN backend")):
            result = execute(parser().parse_args(["--config", str(self.config), "wifi-disable", "--apply"]))
        self.assertEqual(result["status"], "usb_only_verified")

    def test_listener_parser_validates_ipv4_ipv6_and_ignores_nonlisteners(self):
        raw = PROC_HEADER + "0: 00000000:15B3 00000000:0000 0A 0 0\n1: 00000000:15B4 00000000:0000 01 0 0\n"
        self.assertEqual(tcp_listener_ports(raw), {5555})
        with self.assertRaises(FrameError):
            tcp_listener_ports("unknown malformed output")


if __name__ == "__main__":
    unittest.main()
