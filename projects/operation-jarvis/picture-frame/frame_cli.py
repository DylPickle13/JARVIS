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
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local prerequisites; no device connection")
    commands.add_parser("devices", help="List ADB transports only; never auto-select a target")
    probe = commands.add_parser("probe", help="Read identity and Frameo package candidates from ONE target")
    probe.add_argument("--serial", required=True)
    probe.add_argument("--package")
    pair = commands.add_parser("pair", help="Save inspected identity; refuse to overwrite an existing pairing")
    pair.add_argument("--serial", required=True)
    pair.add_argument("--package", required=True)
    commands.add_parser("status", help="Pinned-device display settings; no photo content")
    commands.add_parser("pending", help="Read local ambiguous-write marker without contacting a device")
    transport = commands.add_parser("use-transport", help="Select an ALREADY connected transport for the SAME device")
    transport.add_argument("--serial", required=True)
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
    for name in ("pair", "use-transport", "resolve-pending", "screenshot", "wake", "sleep",
                 "brightness", "next", "previous", "wifi-enable", "upload"):
        commands.choices[name].add_argument("--apply", action="store_true",
                                           help="Explicitly apply; omission makes NO ADB calls")
    return root


def execute(args, adb=None):
    adb = adb or Adb(args.adb)
    controller = Controller(adb, args.config)
    command = args.command
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
    if command == "pending":
        from frame_control import read_json
        return {"pending": read_json(controller.pending_path) if controller.pending_path.exists() else None,
                "device_contacted": False}
    if command == "resolve-pending":
        return controller.resolve_pending(apply=args.apply)
    if command == "use-transport":
        return controller.use_transport(args.serial, apply=args.apply)
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
