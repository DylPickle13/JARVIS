from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import DEFAULT_ENV_PATH, load_settings
from .vesync_client import (
    AirPurifierController,
    AirPurifierError,
    PurifierStatus,
    dependency_status,
    run,
    statuses_to_dict,
)

ON_OFF = ("on", "off")
MODES = ("manual", "auto", "sleep", "pet")
AUTO_PREFERENCES = ("default", "efficient", "quiet")


def _state_to_bool(value: str) -> bool:
    clean = value.strip().lower()
    if clean == "on":
        return True
    if clean == "off":
        return False
    raise ValueError(f"expected 'on' or 'off', got {value!r}")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_status(status: PurifierStatus, as_json: bool = False) -> None:
    payload = status.as_dict()
    if as_json:
        _print_json(payload)
        return

    bits = [
        f"{status.name or '<unnamed purifier>'}",
        f"model={status.model or 'unknown'}",
        f"power={payload.get('power')}",
        f"mode={payload.get('mode')}",
        f"fan={payload.get('fan_level')}",
    ]
    if payload.get("pm25") is not None:
        bits.append(f"pm2.5={payload.get('pm25')}")
    if payload.get("filter_life") is not None:
        bits.append(f"filter={payload.get('filter_life')}%")
    if payload.get("verification_pending"):
        bits.append("verification=pending")
    if status.cid:
        bits.append(f"cid={status.cid}")
    print("  ".join(bits))


def _print_many(statuses: dict[str, PurifierStatus], as_json: bool = False) -> None:
    if as_json:
        _print_json(statuses_to_dict(statuses))
        return
    if not statuses:
        print("No VeSync air purifiers discovered.")
        return
    for status in statuses.values():
        _print_status(status, as_json=False)


def _print_filter(status: PurifierStatus, as_json: bool = False) -> None:
    payload = status.as_dict()
    filtered = {
        "name": payload["name"],
        "model": payload["model"],
        "filter_life": payload["filter_life"],
    }
    if as_json:
        _print_json(filtered)
        return
    print(f"{filtered['name']}: filter life {filtered['filter_life']}%")


def _doctor_payload() -> dict[str, Any]:
    settings = load_settings()
    deps = dependency_status()
    return {
        "ok": bool(deps.python_ok and deps.pyvesync_installed),
        "env_path": str(DEFAULT_ENV_PATH),
        "credentials_configured": settings.has_credentials,
        "default_device": settings.default_device,
        "country_code": settings.country_code,
        "time_zone": settings.time_zone,
        "write_wait_seconds": settings.write_wait_seconds,
        "dependencies": deps.as_dict(),
        "notes": [
            "Pair the purifier in the VeSync app before running list/status/control commands.",
            "This subsystem is available through Operation JARVIS purifier-status/purifier-set tools.",
        ],
    }


def _print_doctor(as_json: bool = False) -> None:
    payload = _doctor_payload()
    if as_json:
        _print_json(payload)
        return
    print(f"Python: {payload['dependencies']['python_version']} ({'ok' if payload['dependencies']['python_ok'] else 'requires >=3.11'})")
    if payload["dependencies"]["pyvesync_installed"]:
        print(f"pyvesync: {payload['dependencies']['pyvesync_version']}")
    else:
        print(f"pyvesync: missing ({payload['dependencies']['pyvesync_error']})")
    print(f"credentials: {'configured' if payload['credentials_configured'] else 'missing'}")
    print(f"country: {payload['country_code']}  timezone: {payload['time_zone']}")
    print(f"write wait: {payload['write_wait_seconds']}s")
    print(f"default device: {payload['default_device'] or '<first discovered purifier>'}")
    print(f"env file: {payload['env_path']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purifierctl",
        description="Control VeSync/Levoit air purifiers for Operation JARVIS.",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check local setup without contacting VeSync")
    sub.add_parser("list", help="List VeSync air purifiers on the account")

    status = sub.add_parser("status", help="Show purifier status")
    status.add_argument("device", nargs="?", help="Device name, CID, or model; defaults to configured/first purifier")

    filter_cmd = sub.add_parser("filter", help="Show purifier filter life")
    filter_cmd.add_argument("device", nargs="?", help="Device name, CID, or model")

    for command in ("on", "off", "toggle"):
        p = sub.add_parser(command, help=f"Turn purifier {command}" if command != "toggle" else "Toggle purifier power")
        p.add_argument("device", nargs="?", help="Device name, CID, or model")

    mode = sub.add_parser("mode", help="Set purifier mode")
    mode.add_argument("mode", choices=MODES)
    mode.add_argument("device", nargs="?", help="Device name, CID, or model")

    speed = sub.add_parser("speed", help="Set manual fan speed, 1-4 for Vital 200S")
    speed.add_argument("level", type=int)
    speed.add_argument("device", nargs="?", help="Device name, CID, or model")

    display = sub.add_parser("display", help="Set display on/off")
    display.add_argument("state", choices=ON_OFF)
    display.add_argument("device", nargs="?", help="Device name, CID, or model")

    child_lock = sub.add_parser("child-lock", help="Set child/display lock on/off")
    child_lock.add_argument("state", choices=ON_OFF)
    child_lock.add_argument("device", nargs="?", help="Device name, CID, or model")

    light_detection = sub.add_parser("light-detection", help="Set light-detection mode on/off")
    light_detection.add_argument("state", choices=ON_OFF)
    light_detection.add_argument("device", nargs="?", help="Device name, CID, or model")

    auto_preference = sub.add_parser("auto-preference", help="Set auto mode preference")
    auto_preference.add_argument("preference", choices=AUTO_PREFERENCES)
    auto_preference.add_argument("device", nargs="?", help="Device name, CID, or model")
    auto_preference.add_argument("--room-size", type=int, default=600, help="Room size in square feet; default 600")

    timer = sub.add_parser("timer", help="Set power-off timer in minutes")
    timer.add_argument("minutes", type=int)
    timer.add_argument("device", nargs="?", help="Device name, CID, or model")

    clear_timer = sub.add_parser("clear-timer", help="Clear purifier timer")
    clear_timer.add_argument("device", nargs="?", help="Device name, CID, or model")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        _print_doctor(args.json)
        return 0

    settings = load_settings()
    controller = AirPurifierController(settings)

    try:
        if args.command == "list":
            _print_many(run(controller.list()), args.json)
        elif args.command == "status":
            _print_status(run(controller.status(args.device)), args.json)
        elif args.command == "filter":
            _print_filter(run(controller.status(args.device)), args.json)
        elif args.command == "on":
            _print_status(run(controller.set_power(True, args.device)), args.json)
        elif args.command == "off":
            _print_status(run(controller.set_power(False, args.device)), args.json)
        elif args.command == "toggle":
            _print_status(run(controller.toggle(args.device)), args.json)
        elif args.command == "mode":
            _print_status(run(controller.set_mode(args.mode, args.device)), args.json)
        elif args.command == "speed":
            _print_status(run(controller.set_speed(args.level, args.device)), args.json)
        elif args.command == "display":
            _print_status(run(controller.set_display(_state_to_bool(args.state), args.device)), args.json)
        elif args.command == "child-lock":
            _print_status(run(controller.set_child_lock(_state_to_bool(args.state), args.device)), args.json)
        elif args.command == "light-detection":
            _print_status(run(controller.set_light_detection(_state_to_bool(args.state), args.device)), args.json)
        elif args.command == "auto-preference":
            _print_status(run(controller.set_auto_preference(args.preference, args.room_size, args.device)), args.json)
        elif args.command == "timer":
            _print_status(run(controller.set_timer(args.minutes, args.device)), args.json)
        elif args.command == "clear-timer":
            _print_status(run(controller.clear_timer(args.device)), args.json)
        else:
            parser.error(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except AirPurifierError as exc:
        print(f"purifierctl: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"purifierctl: unexpected error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
