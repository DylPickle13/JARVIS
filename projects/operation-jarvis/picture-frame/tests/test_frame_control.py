"""Offline tests: no real ADB, USB, LAN, photos, or household controls."""
import copy
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frame_control import (Adb, AdbError, Controller, FrameError, PNG_SIGNATURE,
                           display_state, private_directory, read_json, save_json,
                           validate_package, validate_serial)
from frame_cli import execute, main, parser

SERIAL = "FRAME_USB_123"
PACKAGE = "dk.frameo.frame"
IDENTITY = {"hardware_serial": "HW_FRAME_123", "manufacturer": "TestMaker",
            "model": "TestFrame", "build_fingerprint": "test/frame/build:1"}
PNG = PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1280, 800) + b"\x08\x02\x00\x00\x00" + b"\x00" * 4
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-test-not-a-real-family-photo"


class FakeAdb:
    def __init__(self):
        self.identity = copy.deepcopy(IDENTITY)
        self.package = PACKAGE
        self.brightness = "128"
        self.mode = "1"
        self.power = "Display Power: state=ON\nmWakefulness=Awake"
        self.focus = "mCurrentFocus=Window{123 u0 " + PACKAGE + "/.MainActivity}"
        self.calls = []
        self.mutations = []
        self.fail_action = None
        self.bad_readback = False
        self.remote_exists = False
        self.partial_exists = False
        self.staged_size = 0
        self.bad_size = False
        self.png = PNG

    def probe(self, serial, package=None):
        self.calls.append(("probe", serial, package))
        if package and self.package != package:
            raise FrameError("Wrong package")
        return {"serial": serial, "identity": copy.deepcopy(self.identity),
                "frameo_packages": [self.package]}

    def call(self, args, serial=None, binary=False, timeout=20, **unused):
        self.calls.append(("call", serial, tuple(args)))
        if args == ["exec-out", "screencap", "-p"]:
            return self.png
        if args[0] == "push":
            self.mutations.append("push")
            if self.fail_action == "push":
                raise AdbError("unknown upload")
            self.partial_exists = True
            self.staged_size = Path(args[1]).stat().st_size
            return "1 file pushed"
        if args[0] == "tcpip":
            self.mutations.append("tcpip")
            if self.fail_action == "tcpip":
                raise AdbError("unknown tcpip")
            return "restarting in TCP mode port: " + args[1]
        raise AssertionError(args)

    def shell(self, serial, *args):
        self.calls.append(("shell", serial, tuple(args)))
        if args == ("dumpsys", "power"):
            return self.power
        if args == ("settings", "get", "system", "screen_brightness"):
            return "37" if self.bad_readback else self.brightness
        if args == ("settings", "get", "system", "screen_brightness_mode"):
            return self.mode
        if args == ("dumpsys", "window", "windows"):
            return self.focus
        if args == ("test", "-d", "/sdcard/DCIM"):
            return ""
        if args[:2] == ("sh", "-c"):
            exists = (self.remote_exists or self.partial_exists) if "||" in args[2] else self.partial_exists
            return "exists" if exists else "absent"
        if args[:2] == ("wc", "-c"):
            return str(1 if self.bad_size else self.staged_size) + " " + args[2]
        if args[:2] == ("mv", "-n"):
            self.mutations.append(args)
            if self.fail_action == "rename":
                raise AdbError("unknown rename")
            if not self.remote_exists:
                self.partial_exists = False
                self.remote_exists = True
            return ""
        if args[:2] == ("input", "keyevent"):
            self.mutations.append(args)
            if self.fail_action == "input":
                raise AdbError("unknown input")
            self.power = "Display Power: state=" + ("ON" if args[2] == "224" else "OFF")
            return ""
        if args[:2] == ("input", "swipe"):
            self.mutations.append(args)
            return ""
        if args[:2] == ("settings", "put"):
            self.mutations.append(args)
            if self.fail_action == args[3]:
                raise AdbError("unknown setting")
            if args[3] == "screen_brightness":
                self.brightness = args[4]
            else:
                self.mode = args[4]
            return ""
        raise AssertionError(args)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.fake = FakeAdb()
        self.controller = Controller(self.fake, self.root / "private/config.json")
        self.photo = self.root / "photo.jpg"
        self.photo.write_bytes(JPEG)

    def pair(self):
        self.controller.pair(SERIAL, PACKAGE, apply=True)
        self.fake.calls.clear()

    def test_every_control_dry_run_does_not_contact_device_or_create_runtime(self):
        for action, value in (("wake", None), ("sleep", None), ("brightness", 180),
                              ("next", None), ("previous", None), ("wifi-enable", 5555)):
            self.assertEqual(self.controller.control(action, value)["status"], "dry_run")
        self.controller.pair(SERIAL, PACKAGE)
        self.controller.screenshot()
        self.controller.use_transport("192.168.1.20:5555")
        self.controller.resolve_pending()
        self.controller.upload(self.photo)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.controller.runtime.exists())

    def test_pair_creates_private_pinned_config_and_will_not_overwrite(self):
        self.pair()
        config = read_json(self.controller.config_path)
        self.assertEqual(config["identity"], IDENTITY)
        self.assertEqual(stat.S_IMODE(self.controller.config_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.controller.runtime.stat().st_mode), 0o700)
        with self.assertRaises(FrameError):
            self.controller.pair(SERIAL, PACKAGE, apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_pair_rejects_missing_hardware_identity(self):
        self.fake.identity["hardware_serial"] = "unknown"
        with self.assertRaises(FrameError):
            self.controller.pair(SERIAL, PACKAGE, apply=True)
        self.assertFalse(self.controller.config_path.exists())

    def test_status_reports_android_values_and_no_physical_acceptance(self):
        self.pair()
        result = self.controller.status()
        self.assertTrue(result["screen_on"])
        self.assertEqual(result["android_brightness_setting"], 128)
        self.assertEqual(result["physical_acceptance"], "not_verified")
        self.assertEqual(self.fake.mutations, [])

    def test_each_pinned_identity_field_must_match_before_write(self):
        self.pair()
        for field in IDENTITY:
            with self.subTest(field=field):
                self.fake.identity = {**IDENTITY, field: "different"}
                with self.assertRaises(FrameError):
                    self.controller.control("wake", apply=True)
        self.assertEqual(self.fake.mutations, [])
        self.assertFalse(self.controller.pending_path.exists())

    def test_wrong_package_blocks_write(self):
        self.pair()
        self.fake.package = "other.frameo.app"
        with self.assertRaises(FrameError):
            self.controller.control("sleep", apply=True)
        self.assertEqual(self.fake.mutations, [])

    def test_missing_config_never_auto_selects_device(self):
        with self.assertRaises(FrameError):
            self.controller.control("wake", apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_brightness_validates_range_and_boolean(self):
        for value in (-1, 256, True, "30", None):
            with self.assertRaises(FrameError):
                self.controller.control("brightness", value, apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_brightness_sets_manual_mode_and_verifies_android_settings(self):
        self.pair()
        result = self.controller.control("brightness", 200, apply=True)
        self.assertEqual(result["status"], "android_setting_verified")
        self.assertEqual(self.fake.mode, "0")
        self.assertEqual(self.fake.brightness, "200")
        self.assertFalse(self.controller.pending_path.exists())

    def test_pending_marker_exists_before_first_mutation(self):
        self.pair()
        original = self.fake.shell
        def checked(serial, *args):
            if args[:2] == ("settings", "put"):
                self.assertEqual(read_json(self.controller.pending_path)["operation"], "brightness")
            return original(serial, *args)
        self.fake.shell = checked
        self.controller.control("brightness", 155, apply=True)

    def test_partial_failure_is_durable_and_blocks_later_write_without_device_contact(self):
        self.pair()
        self.fake.fail_action = "screen_brightness"
        with self.assertRaises(AdbError):
            self.controller.control("brightness", 180, apply=True)
        self.assertTrue(self.controller.pending_path.exists())
        self.assertEqual(self.fake.mode, "0")
        calls = len(self.fake.calls)
        with self.assertRaises(FrameError):
            self.controller.control("wake", apply=True)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertIsNotNone(self.controller.status()["pending"])

    def test_readback_mismatch_keeps_pending_marker(self):
        self.pair()
        self.fake.bad_readback = True
        with self.assertRaises(FrameError):
            self.controller.control("brightness", 190, apply=True)
        self.assertTrue(self.controller.pending_path.exists())

    def test_resolve_is_explicit_acknowledgement_without_retry_or_device_contact(self):
        self.pair()
        save_json(self.controller.pending_path, {"operation": "wake", "outcome": "unknown"})
        self.controller.resolve_pending()
        self.assertTrue(self.controller.pending_path.exists())
        result = self.controller.resolve_pending(apply=True)
        self.assertEqual(result["status"], "pending_acknowledged")
        self.assertEqual(self.fake.calls, [])
        self.assertTrue((self.controller.runtime / "last-resolved.json").exists())

    def test_dedicated_wakeup_and_sleep_keys_with_readback(self):
        self.pair()
        for action, key in (("sleep", "223"), ("wake", "224")):
            result = self.controller.control(action, apply=True)
            self.assertEqual(result["status"], "android_state_verified")
            self.assertIn(("input", "keyevent", key), self.fake.mutations)
        self.assertNotIn(("input", "keyevent", "26"), self.fake.mutations)

    def test_navigation_requires_visible_slideshow_and_exact_foreground_app(self):
        self.pair()
        with self.assertRaises(FrameError):
            self.controller.control("next", apply=True)
        self.assertEqual(self.fake.calls, [])
        for focus in ("mCurrentFocus=null", "mCurrentFocus=Window{123 u0 dk.frameo.frame.fake/.Activity}"):
            self.fake.focus = focus
            with self.assertRaises(FrameError):
                self.controller.control("next", apply=True, slideshow_ready=True)
        self.assertEqual(self.fake.mutations, [])

    def test_navigation_uses_current_screenshot_dimensions_and_is_unverified(self):
        self.pair()
        result = self.controller.control("next", apply=True, slideshow_ready=True)
        self.assertEqual(result["status"], "dispatched_unverified")
        self.assertIn(("input", "swipe", 1024, 400, 256, 400, "300"), self.fake.mutations)
        self.assertFalse((self.controller.runtime / "screenshots").exists())
        self.controller.control("previous", apply=True, slideshow_ready=True)
        self.assertIn(("input", "swipe", 256, 400, 1024, 400, "300"), self.fake.mutations)

    def test_invalid_screenshot_does_not_dispatch_navigation(self):
        self.pair()
        self.fake.png = b"invalid"
        with self.assertRaises(FrameError):
            self.controller.control("next", apply=True, slideshow_ready=True)
        self.assertEqual(self.fake.mutations, [])

    def test_screenshot_is_explicit_private_unique_and_targeted(self):
        self.pair()
        one = self.controller.screenshot(apply=True)
        two = self.controller.screenshot(apply=True)
        self.assertNotEqual(one["output"], two["output"])
        self.assertEqual(Path(one["output"]).read_bytes(), PNG)
        self.assertEqual(stat.S_IMODE(Path(one["output"]).stat().st_mode), 0o600)
        self.assertEqual((one["width"], one["height"]), (1280, 800))
        self.assertEqual(self.fake.mutations, [])

    def test_transport_switch_rechecks_identity(self):
        self.pair()
        self.controller.use_transport("192.168.1.20:5555", apply=True)
        self.assertEqual(read_json(self.controller.config_path)["serial"], "192.168.1.20:5555")
        self.fake.identity["hardware_serial"] = "some_other_android"
        with self.assertRaises(FrameError):
            self.controller.use_transport("OTHER_USB", apply=True)
        self.assertEqual(read_json(self.controller.config_path)["serial"], "192.168.1.20:5555")

    def test_wifi_enable_is_explicit_usb_only_and_not_claimed_verified(self):
        self.pair()
        result = self.controller.control("wifi-enable", 5555, apply=True)
        self.assertEqual(result["status"], "dispatched_unverified")
        self.controller.use_transport("192.168.1.20:5555", apply=True)
        with self.assertRaises(FrameError):
            self.controller.control("wifi-enable", 5555, apply=True)
        self.assertEqual(self.fake.mutations.count("tcpip"), 1)

    def test_failed_wifi_enable_keeps_pending_state(self):
        self.pair()
        self.fake.fail_action = "tcpip"
        with self.assertRaises(AdbError):
            self.controller.control("wifi-enable", 5555, apply=True)
        self.assertTrue(self.controller.pending_path.exists())

    def test_upload_requires_explicit_import_ready(self):
        self.pair()
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_upload_uses_hash_name_records_transfer_but_does_not_claim_import(self):
        self.pair()
        result = self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertEqual(result["status"], "transferred_import_unverified")
        pushes = [call for call in self.fake.calls if call[0] == "call" and call[2][0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertTrue(pushes[0][2][2].startswith("/sdcard/DCIM/jarvis-"))
        self.assertNotIn(self.photo.name, pushes[0][2][2])
        self.assertEqual(pushes[0][1], SERIAL)
        self.assertEqual(len(read_json(self.controller.uploads_path)), 1)
        self.assertFalse(any(self.controller.runtime.glob("photo-*")))

    def test_upload_stages_then_size_checks_and_renames_without_clobber(self):
        self.pair()
        self.controller.upload(self.photo, apply=True, import_ready=True)
        push = next(call for call in self.fake.calls if call[0] == "call" and call[2][0] == "push")
        self.assertTrue(push[2][2].endswith(".jpg.part"))
        reads = [call[2] for call in self.fake.calls if call[0] == "shell"]
        count = next(index for index, args in enumerate(reads) if args[:2] == ("wc", "-c"))
        rename = next(index for index, args in enumerate(reads) if args[:2] == ("mv", "-n"))
        self.assertLess(count, rename)
        self.assertFalse(self.fake.partial_exists)

    def test_staged_size_mismatch_blocks_rename_and_preserves_pending(self):
        self.pair()
        self.fake.bad_size = True
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertTrue(self.controller.pending_path.exists())
        self.assertFalse(any(isinstance(action, tuple) and action[0] == "mv" for action in self.fake.mutations))

    def test_failed_rename_is_not_retried(self):
        self.pair()
        self.fake.fail_action = "rename"
        with self.assertRaises(AdbError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertEqual(self.fake.mutations.count("push"), 1)
        self.assertTrue(self.controller.pending_path.exists())

    def test_remote_staging_file_blocks_new_transfer(self):
        self.pair()
        self.fake.partial_exists = True
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertEqual(self.fake.mutations, [])

    def test_duplicate_content_is_not_resent_even_after_frame_consumes_file(self):
        self.pair()
        self.controller.upload(self.photo, apply=True, import_ready=True)
        self.fake.remote_exists = False
        renamed = self.root / "renamed.jpg"
        renamed.write_bytes(JPEG)
        with self.assertRaises(FrameError):
            self.controller.upload(renamed, apply=True, import_ready=True)
        self.assertEqual(self.fake.mutations.count("push"), 1)

    def test_existing_remote_file_is_never_overwritten(self):
        self.pair()
        self.fake.remote_exists = True
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertNotIn("push", self.fake.mutations)

    def test_upload_failure_blocks_replay_and_retains_no_staged_photo(self):
        self.pair()
        self.fake.fail_action = "push"
        with self.assertRaises(AdbError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertTrue(self.controller.pending_path.exists())
        self.assertFalse(self.controller.uploads_path.exists())
        self.assertFalse(any(self.controller.runtime.glob("photo-*")))
        with self.assertRaises(FrameError):
            self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertEqual(self.fake.mutations.count("push"), 1)

    def test_upload_rejects_unsupported_fake_and_oversized_photos(self):
        self.pair()
        for filename, content in (("photo.heic", b"heic"), ("wrong.jpg", PNG), ("wrong.png", JPEG)):
            source = self.root / filename
            source.write_bytes(content)
            with self.assertRaises(FrameError):
                self.controller.upload(source, apply=True, import_ready=True)
        with patch("frame_control.MAX_PHOTO_BYTES", 4):
            with self.assertRaises(FrameError):
                self.controller.upload(self.photo, apply=True, import_ready=True)
        self.assertNotIn("push", self.fake.mutations)
        self.assertFalse(self.controller.pending_path.exists())

    def test_parallel_controller_locks_fail_without_device_contact(self):
        self.pair()
        other = Controller(self.fake, self.controller.config_path)
        with self.controller.lock():
            with self.assertRaises(FrameError):
                other.control("sleep", apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_runtime_will_not_chmod_shared_source_directory(self):
        shared = self.root / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        with self.assertRaises(FrameError):
            private_directory(shared)
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o755)

    def test_corrupt_config_fails_closed_before_device_contact(self):
        self.pair()
        self.controller.config_path.write_text("[]")
        with self.assertRaises(FrameError):
            self.controller.control("wake", apply=True)
        self.assertEqual(self.fake.calls, [])

    def test_corrupt_pending_blocks_write_and_is_not_silently_cleared(self):
        self.pair()
        self.controller.pending_path.write_text("broken")
        with self.assertRaises(FrameError):
            self.controller.control("wake", apply=True)
        with self.assertRaises(FrameError):
            self.controller.resolve_pending(apply=True)
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(self.controller.pending_path.exists())


class AdbAndCliTests(unittest.TestCase):
    def test_serial_validation_blocks_flags_shell_and_non_lan_targets(self):
        for serial in ("", "-e", "USB;reboot", "x y", "8.8.8.8:5555", "127.0.0.1:5555",
                       "frame.local:5555", "192.168.1.2:0", "[::1]:5555", None):
            with self.assertRaises(FrameError, msg=str(serial)):
                validate_serial(serial)
        for serial in (SERIAL, "192.168.1.20:5555", "10.1.2.3:5555"):
            self.assertEqual(validate_serial(serial), serial)

    def test_package_validation_does_not_accept_lookalike_or_injection(self):
        for package in ("com.notframeo.app", "dk.frameo.frame;reboot", "frameo", None):
            with self.assertRaises(FrameError):
                validate_package(package)
        self.assertEqual(validate_package(PACKAGE), PACKAGE)

    def test_adb_uses_explicit_serial_and_android_shell_quoting(self):
        calls = []
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b"ok", b"")
        adb = Adb(runner=runner)
        adb.shell(SERIAL, "input", "text", "x; echo dangerous")
        command, kwargs = calls[0]
        self.assertEqual(command, ["adb", "-s", SERIAL, "shell", "input text 'x; echo dangerous'"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 20)

    def test_timeout_and_failure_are_sanitized_and_not_retried(self):
        for failure in (subprocess.TimeoutExpired("sensitive path", 20),
                        subprocess.CompletedProcess([], 1, b"private photo", b"secret")):
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                if isinstance(failure, Exception):
                    raise failure
                return failure
            with self.assertRaises(AdbError) as error:
                Adb(runner=runner).call(["get-state"], serial=SERIAL)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("secret", str(error.exception))
            self.assertNotIn("sensitive path", str(error.exception))

    def test_devices_only_lists_and_never_selects(self):
        output = b"List of devices attached\nFRAME_USB_123\tdevice product:x\nPHONE\tunauthorized\nOFFLINE\toffline\n"
        adb = Adb(runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, output, b""))
        result = execute(parser().parse_args(["devices"]), adb)
        self.assertIsNone(result["selected"])
        self.assertEqual(len(result["devices"]), 3)

    def test_probe_reads_realistic_properties_and_package_list(self):
        responses = [b"device", b"", b"TestMaker", b"TestFrame", b"test/build", b"BOOT_SERIAL",
                     b"package:com.other.app\npackage:dk.frameo.frame\npackage:com.notframeo.app"]
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, responses.pop(0), b"")
        result = Adb(runner=runner).probe(SERIAL, PACKAGE)
        self.assertEqual(result["identity"]["hardware_serial"], "BOOT_SERIAL")
        self.assertEqual(result["frameo_packages"], [PACKAGE])
        self.assertTrue(all(command[1:3] == ["-s", SERIAL] for command in commands))

    def test_unknown_power_is_unknown_not_off(self):
        for output in ("", "mWakefulness=Dozing", "Display Power: state=DOZE\nmWakefulness=Awake"):
            self.assertIsNone(display_state(output))
        self.assertFalse(display_state("Display Power: state=OFF\nmWakefulness=Awake"))

    def test_parser_dry_run_cli_is_json_without_adb(self):
        with patch("frame_control.subprocess.run", side_effect=AssertionError("No real ADB!")), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["brightness", "180"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry_run")

    def test_missing_adb_doctor_does_not_connect(self):
        with patch("frame_cli.shutil.which", return_value=None):
            result = execute(parser().parse_args(["doctor"]), FakeAdb())
        self.assertEqual(result["status"], "missing_adb")
        self.assertFalse(result["device_contacted"])

    def test_no_arbitrary_shell_or_root_or_delete_command(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            for command in ("shell", "root", "delete", "reboot", "factory-reset"):
                with self.assertRaises(SystemExit):
                    parser().parse_args([command])


if __name__ == "__main__":
    unittest.main()
