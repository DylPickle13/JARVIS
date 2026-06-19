from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_settings
from .kasa_client import PlugStatus, SmartPlugController, run


def _print_status(status: PlugStatus, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(status.as_dict(), indent=2, sort_keys=True))
        return
    state = "on" if status.is_on else "off" if status.is_on is False else "unknown"
    bits = [
        f"{status.name}: {state}",
        f"host={status.host}",
    ]
    if status.alias:
        bits.append(f"alias={status.alias!r}")
    if status.model:
        bits.append(f"model={status.model}")
    if status.rssi is not None:
        bits.append(f"rssi={status.rssi}")
    print("  ".join(bits))


def _print_many(statuses: dict[str, PlugStatus], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({k: v.as_dict() for k, v in statuses.items()}, indent=2, sort_keys=True))
        return
    if not statuses:
        print("No Kasa devices discovered.")
        return
    for status in statuses.values():
        _print_status(status, as_json=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plugctl",
        description="Control Kasa HS103 smart plugs locally.",
    )
    parser.add_argument("--config", type=Path, help="Path to plugs.json; defaults to ./plugs.json")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="Discover Kasa plugs on the local network")
    sub.add_parser("save-discovery", help="Discover plugs and write plugs.json using their Kasa aliases")
    sub.add_parser("list", help="List configured plugs from plugs.json/.env")

    for command in ("status", "on", "off", "toggle"):
        p = sub.add_parser(command, help=f"{command} a plug")
        p.add_argument("plug", help="Configured plug name or direct IP address")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    controller = SmartPlugController(settings)

    try:
        if args.command == "discover":
            _print_many(run(controller.discover()), args.json)
        elif args.command == "save-discovery":
            statuses = run(controller.save_discovery())
            _print_many(statuses, args.json)
            if not args.json:
                print(f"Saved {len(statuses)} plug(s) to {settings.config_path}")
        elif args.command == "list":
            if args.json:
                print(json.dumps({name: plug.host for name, plug in settings.plugs.items()}, indent=2, sort_keys=True))
            elif not settings.plugs:
                print("No configured plugs yet. Run: plugctl save-discovery")
            else:
                for name, plug in sorted(settings.plugs.items()):
                    print(f"{name}: {plug.host}")
        elif args.command == "status":
            _print_status(run(controller.status(args.plug)), args.json)
        elif args.command == "on":
            _print_status(run(controller.set_power(args.plug, True)), args.json)
        elif args.command == "off":
            _print_status(run(controller.set_power(args.plug, False)), args.json)
        elif args.command == "toggle":
            _print_status(run(controller.toggle(args.plug)), args.json)
        else:
            parser.error(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"plugctl: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
