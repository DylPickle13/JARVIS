#!/usr/bin/env python3
"""Picture-frame CLI: read-only discovery; explicit pairing; writes default to dry-run."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from frame_control import Adb, Controller, DEFAULT_CONFIG, FrameError


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                      help="Config in a dedicated private runtime directory; never commit it")
    root.add_argument("--adb", default="adb", help="Android platform-tools executable")
    root.add_argument("--direct-tcp", action="store_true",
                      help="Use authenticated in-process TCP, not the host ADB server; no discovery")
    root.add_argument("--adb-key", type=Path,
                      help="Existing owner-controlled Mac ADB key; never generated/replaced")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local prerequisites; no device connection")
    commands.add_parser("devices", help="List ADB transports only; never auto-select a target")
    commands.add_parser("capabilities", help="Local control/limitation inventory; no device contact")
    probe = commands.add_parser("probe", help="Read identity and Frameo package candidates from ONE target")
    probe.add_argument("--serial", required=True)
    probe.add_argument("--package")
    pair = commands.add_parser("pair", help="Save inspected identity; refuse to overwrite an existing pairing")
    pair.add_argument("--serial", required=True)
    pair.add_argument("--package", required=True)
    commands.add_parser("status", help="Pinned-device display settings; no photo content")
    commands.add_parser("backlight", help="Read effective backlight/window override; unknown remains unknown")
    commands.add_parser("pending", help="Read local ambiguous-write marker without contacting a device")
    transport = commands.add_parser("use-transport", help="Select an ALREADY connected transport for the SAME device")
    transport.add_argument("--serial", required=True)
    tcp = commands.add_parser("connect-tcp", help="Authenticate ONE LAN target and accept the SAME pinned frame")
    tcp.add_argument("--serial", required=True)
    legacy = commands.add_parser("connect-legacy-lan", help="USB-first: accept UNAUTHENTICATED LAN for ONE pinned frame")
    legacy.add_argument("--serial", required=True)
    legacy.add_argument("--accept-unauthenticated-lan", action="store_true",
                        help="Owner explicitly accepts other reachable LAN clients obtaining debugging access")
    retire = commands.add_parser("wifi-disable", help="Retire wireless ADB over the exact verified USB route")
    retire.add_argument("--usb-serial", help="Explicit original USB serial; never discovers/selects another device")
    commands.add_parser("resolve-pending", help="After physical inspection, acknowledge uncertainty; never replays")
    commands.add_parser("screenshot", help="Explicit private PNG capture to runtime directory")
    commands.add_parser("wake", help="Idempotent Android WAKEUP, not a power toggle")
    commands.add_parser("sleep", help="Android SLEEP, not shutdown/power-off")
    brightness = commands.add_parser("brightness", help="Manual Android brightness setting; range 0..255")
    brightness.add_argument("value", type=int)
    for name in ("next", "previous"):
        navigation = commands.add_parser(name, help="Experimental slideshow swipe; visual acceptance required")
        navigation.add_argument("--slideshow-ready", action="store_true",
                                help="Owner confirms Frameo is showing its slideshow, not a menu")
    wifi = commands.add_parser("wifi-enable", help="USB-only: enable LAN ADB; potentially exposes privileged control")
    wifi.add_argument("--port", type=int, default=5555)
    upload = commands.add_parser("upload", help="Experimental JPEG/PNG transfer into existing DCIM; NOT proof of import")
    upload.add_argument("photo", type=Path)
    upload.add_argument("--import-ready", action="store_true",
                        help="Owner enabled Settings > Manage photos > Transfer from computer on the frame")
    for name in ("pair", "use-transport", "connect-tcp", "connect-legacy-lan", "wifi-disable",
                 "resolve-pending", "screenshot", "wake", "sleep",
                 "brightness", "next", "previous", "wifi-enable", "upload"):
        commands.choices[name].add_argument("--apply", action="store_true",
                                           help="Explicitly apply; omission makes NO ADB calls")
    return root


def execute(args, adb=None):
    owned = adb is None
    if owned:
        direct = args.direct_tcp or args.command == "connect-tcp"
        # Do not read saved state/import optional packages for write dry-runs.
        local_or_discovery = ("doctor", "capabilities", "devices", "probe", "pair", "pending",
                              "resolve-pending", "connect-legacy-lan", "wifi-disable")
        usb_selection = args.command == "use-transport" and ":" not in args.serial
        saved = None
        if (not direct and not usb_selection and args.command not in local_or_discovery and
                getattr(args, "apply", True)):
            saved = Controller(None, args.config).config()
            direct = saved.get("adb_backend") == "direct_tcp"
        if (not direct and args.command == "probe" and args.config.exists()):
            candidate = Controller(None, args.config).config()
            if args.serial == candidate["serial"]:
                saved = candidate
                direct = saved.get("adb_backend") == "direct_tcp"
        if saved and saved.get("adb_backend") == "legacy_lan" and not direct:
            from frame_tcp import LegacyLanAdb
            adb = LegacyLanAdb(args.config.expanduser().absolute().parent / "tcp-deps",
                               saved["legacy_lan_approval"])
        elif direct:
            from frame_tcp import DirectTcpAdb
            adb = DirectTcpAdb(args.config.expanduser().absolute().parent / "tcp-deps", args.adb_key)
        else:
            adb = Adb(args.adb)
    try:
        result = execute_with_adb(args, adb)
        warning = getattr(adb, "security_warning", None)
        if warning and result.get("status") != "dry_run":
            result.update(transport="legacy_lan", adb_authentication="not_provided_by_device",
                          security_warning=warning)
        return result
    finally:
        if owned and callable(getattr(adb, "close", None)):
            adb.close()


def execute_with_adb(args, adb):
    controller = Controller(adb, args.config)
    command = args.command
    if command == "capabilities":
        return {"status": "local_inventory", "device_contacted": False,
                "controls": ["status", "backlight", "screenshot", "upload", "sleep", "wake",
                             "next", "previous", "brightness", "wifi-enable", "wifi-disable",
                             "connect-tcp", "connect-legacy-lan", "use-transport", "pending", "resolve-pending"],
                "first_time_physical_tests_required": ["sleep", "wake", "next", "previous", "JPEG import"],
                "unsupported": ["menu-free visible brightness on the received frame", "photo delete/hide",
                                "captions", "slideshow settings", "select a named imported image", "reboot"],
                "note": "Legacy LAN is a separately scoped owner-accepted risk, not authenticated ADB."}
    if command == "doctor" and args.direct_tcp:
        import importlib.util
        dependencies = args.config.expanduser().absolute().parent / "tcp-deps"
        return {"status": "tcp_prerequisites_only", "python_version": sys.version.split()[0],
                "cryptography_available": importlib.util.find_spec("cryptography") is not None,
                "private_tcp_source_present": (dependencies / "installed.json").is_file(),
                "device_contacted": False, "effective_lan_permission": "not_tested"}
    if command == "doctor":
        executable = shutil.which(args.adb)
        return {"status": "ready_for_usb_commissioning" if executable else "missing_adb",
                "adb_available": bool(executable), "python_version": sys.version.split()[0],
                "device_contacted": False, "frame_compatibility": "not_verified"}
    if command == "devices":
        return {"devices": adb.devices(), "selected": None}
    if command == "probe":
        return adb.probe(args.serial, args.package)
    if command == "pair":
        return controller.pair(args.serial, args.package, apply=args.apply)
    if command == "status":
        return controller.status()
    if command == "backlight":
        return controller.backlight()
    if command == "pending":
        from frame_control import read_json
        return {"pending": read_json(controller.pending_path) if controller.pending_path.exists() else None,
                "device_contacted": False}
    if command == "resolve-pending":
        return controller.resolve_pending(apply=args.apply)
    if command == "use-transport":
        return controller.use_transport(args.serial, apply=args.apply)
    if command == "connect-tcp":
        return controller.connect_tcp(args.serial, apply=args.apply)
    if command == "connect-legacy-lan":
        return controller.connect_legacy_lan(args.serial, apply=args.apply,
                                             accept_risk=args.accept_unauthenticated_lan)
    if command == "wifi-disable":
        return controller.wifi_disable(apply=args.apply, usb_serial=args.usb_serial)
    if command == "screenshot":
        return controller.screenshot(apply=args.apply)
    if command == "upload":
        return controller.upload(args.photo, apply=args.apply, import_ready=args.import_ready)
    value = getattr(args, "value", None) if command != "wifi-enable" else args.port
    return controller.control(command, value=value, apply=args.apply,
                              slideshow_ready=getattr(args, "slideshow_ready", False))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except FrameError as error:
        print(json.dumps({"status": "error", "message": str(error)}))
        return 1
    except OSError:
        print(json.dumps({"status": "error", "message": "Local file operation failed. Check private state; do not replay a write."}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "message": "Inspect pending state before any further write; no automatic retry."}))
        return 130
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
