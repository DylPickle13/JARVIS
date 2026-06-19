#!/usr/bin/env python3
"""Connect to configured Google Cast targets.

Set OPERATION_JARVIS_CAST_* environment variables locally or pass --name/--host.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class CastTarget:
    """A known Google Cast target on the local network."""

    alias: str
    name: str
    host: str
    description: str
    location: str = "Unknown"
    cast_type: str = "cast"
    aliases: Tuple[str, ...] = ()


def _cast_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


TV_TARGET = CastTarget(
    alias="tv",
    name=_cast_env("OPERATION_JARVIS_CAST_TV_NAME", "Configured TV Cast target"),
    host=_cast_env("OPERATION_JARVIS_CAST_TV_HOST"),
    description="Configured TV / Chromecast target",
    location=_cast_env("OPERATION_JARVIS_CAST_TV_LOCATION", "Configured location"),
    cast_type="tv",
    aliases=("television", "screen"),
)
SPEAKERS_TARGET = CastTarget(
    alias="speakers",
    name=_cast_env("OPERATION_JARVIS_CAST_SPEAKERS_NAME", "Configured speaker/group Cast target"),
    host=_cast_env("OPERATION_JARVIS_CAST_SPEAKERS_HOST"),
    description="Configured speaker or speaker-group Cast target",
    location=_cast_env("OPERATION_JARVIS_CAST_SPEAKERS_LOCATION", "Configured location"),
    cast_type="group",
    aliases=("speaker", "speaker-group", "speakers-group"),
)
CONFIGURED_TARGETS = (TV_TARGET, SPEAKERS_TARGET)
DEFAULT_DEVICE_ALIAS = "tv"

# Shared defaults for the focused Operation JARVIS Cast scripts.
DEFAULT_CAST_NAME = TV_TARGET.name
DEFAULT_CAST_HOST = TV_TARGET.host
DEFAULT_CAST_PORT = 8009
DEFAULT_DISCOVERY_TIMEOUT = 10.0
DEFAULT_SOCKET_TIMEOUT = 10.0


def normalize_device_key(value: str) -> str:
    """Normalize user-friendly target names/aliases for matching."""
    return re.sub(r"[\s_]+", "-", value.strip().lower())


_TARGET_ALIASES = {}
for _target in CONFIGURED_TARGETS:
    _TARGET_ALIASES[normalize_device_key(_target.alias)] = _target
    _TARGET_ALIASES[normalize_device_key(_target.name)] = _target
    for _alias in _target.aliases:
        _TARGET_ALIASES[normalize_device_key(_alias)] = _target


def iter_targets() -> Tuple[CastTarget, ...]:
    return CONFIGURED_TARGETS


def known_device_names() -> str:
    return ", ".join(target.alias for target in CONFIGURED_TARGETS)


def resolve_target(
    device: Optional[str] = None,
    name: Optional[str] = None,
    host: Optional[str] = None,
) -> CastTarget:
    """Resolve a configured device alias plus optional name/host overrides."""
    requested = device or os.environ.get("OPERATION_JARVIS_CAST_DEVICE") or DEFAULT_DEVICE_ALIAS
    key = normalize_device_key(requested)
    try:
        target = _TARGET_ALIASES[key]
    except KeyError as exc:
        raise ValueError(
            f'Unknown Cast target "{requested}". Known targets: {known_device_names()}.'
        ) from exc

    if name or host:
        return replace(target, name=name or target.name, host=host or target.host)
    return target


def apply_target_defaults(args: argparse.Namespace) -> CastTarget:
    """Populate argparse args.name/args.host from the configured target alias."""
    target = resolve_target(
        device=getattr(args, "device", None),
        name=getattr(args, "name", None),
        host=getattr(args, "host", None),
    )
    args.device = target.alias
    args.name = target.name
    args.host = target.host
    if not args.host:
        env_alias = re.sub(r"[^A-Za-z0-9]+", "_", target.alias).upper()
        raise ValueError(
            f'Cast target "{target.alias}" has no host configured. '
            f'Set OPERATION_JARVIS_CAST_{env_alias}_HOST locally or pass --host.'
        )
    return target


def print_configured_targets() -> None:
    print("Configured Cast targets:")
    for target in CONFIGURED_TARGETS:
        alias_list = ", ".join(target.aliases)
        print(f"  {target.alias}: {target.name} ({target.host})")
        print(f"    location:    {target.location}")
        print(f"    type:        {target.cast_type}")
        print(f"    description: {target.description}")
        if alias_list:
            print(f"    aliases:     {alias_list}")


def check_tcp_port(host: str, port: int, timeout: float) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as exc:
        print(f"TCP check failed for {host}:{port}: {exc}")
        return False


def import_pychromecast():
    """Import pychromecast with a helpful error if the dependency is missing."""
    try:
        import pychromecast  # type: ignore
    except ImportError:
        print(
            "PyChromecast is not installed. From the project root, run:\n"
            "  python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return None
    return pychromecast


def stop_discovery(browser: Any) -> None:
    if browser is None:
        return
    try:
        browser.stop_discovery()
    except AttributeError:
        # Compatibility for older PyChromecast releases.
        try:
            import pychromecast  # type: ignore

            pychromecast.discovery.stop_discovery(browser)
        except Exception:
            pass


def host_matches(cast: Any, host: str) -> bool:
    cast_info = getattr(cast, "cast_info", None)
    return getattr(cast_info, "host", None) == host


def find_cast(
    pychromecast: Any,
    name: str,
    host: str,
    discovery_timeout: float,
    socket_timeout: float,
) -> Tuple[Optional[Any], Optional[Any]]:
    """Find the target Chromecast by exact friendly name, falling back to known host."""
    print(f'Looking for Chromecast named "{name}" at {host}...')

    browser = None
    casts = []

    try:
        casts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[name],
            known_hosts=[host],
            discovery_timeout=discovery_timeout,
            timeout=socket_timeout,
        )
    except Exception as exc:
        print(f"Name-based discovery failed: {exc}")

    if casts:
        return casts[0], browser

    print("No exact friendly-name match found. Trying known-host discovery...")
    stop_discovery(browser)
    browser = None

    try:
        # PyChromecast 13's get_chromecasts() does not expose discovery_timeout;
        # known_hosts keeps the search focused on the supplied IP.
        casts, browser = pychromecast.get_chromecasts(
            known_hosts=[host],
            timeout=socket_timeout,
        )
    except Exception as exc:
        print(f"Known-host discovery failed: {exc}")
        return None, browser

    if not casts:
        return None, browser

    exact_name_matches = [cast for cast in casts if getattr(cast, "name", None) == name]
    if exact_name_matches:
        return exact_name_matches[0], browser

    host_matches_list = [cast for cast in casts if host_matches(cast, host)]
    if host_matches_list:
        return host_matches_list[0], browser

    print("Discovered casts, but none matched the target host/name exactly:")
    for cast in casts:
        cast_info = getattr(cast, "cast_info", None)
        print(
            "  - "
            f"name={getattr(cast, 'name', None)!r}, "
            f"host={getattr(cast_info, 'host', None)!r}, "
            f"uuid={getattr(cast, 'uuid', None)}"
        )
    return casts[0], browser


def print_cast_summary(cast: Any) -> None:
    cast_info = getattr(cast, "cast_info", None)
    status = getattr(cast, "status", None)
    media_status = getattr(getattr(cast, "media_controller", None), "status", None)

    print("\nConnected successfully.")
    print("Cast info:")
    print(f"  name:         {getattr(cast, 'name', None) or getattr(cast_info, 'friendly_name', None)}")
    print(f"  host:         {getattr(cast_info, 'host', None)}")
    print(f"  port:         {getattr(cast_info, 'port', None)}")
    print(f"  uuid:         {getattr(cast, 'uuid', None)}")
    print(f"  model:        {getattr(cast_info, 'model_name', None)}")
    print(f"  manufacturer: {getattr(cast_info, 'manufacturer', None)}")
    print(f"  type:         {getattr(cast_info, 'cast_type', None)}")

    print("\nReceiver status:")
    print(f"  app:          {getattr(status, 'display_name', None)}")
    print(f"  app_id:       {getattr(status, 'app_id', None)}")
    print(f"  volume:       {getattr(status, 'volume_level', None)}")
    print(f"  muted:        {getattr(status, 'volume_muted', None)}")
    print(f"  idle:         {getattr(cast, 'is_idle', None)}")

    print("\nMedia status:")
    print(f"  player_state: {getattr(media_status, 'player_state', None)}")
    print(f"  content_id:   {getattr(media_status, 'content_id', None)}")
    print(f"  content_type: {getattr(media_status, 'content_type', None)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device",
        default=os.environ.get("OPERATION_JARVIS_CAST_DEVICE", DEFAULT_DEVICE_ALIAS),
        help=f"Configured Cast target alias ({known_device_names()})",
    )
    parser.add_argument("--name", default=None, help="Override Chromecast friendly name")
    parser.add_argument("--host", default=None, help="Override Chromecast IP address or hostname")
    parser.add_argument("--port", type=int, default=DEFAULT_CAST_PORT, help="Chromecast Cast V2 TCP port")
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=DEFAULT_DISCOVERY_TIMEOUT,
        help="Seconds to wait for mDNS/known-host discovery",
    )
    parser.add_argument(
        "--socket-timeout",
        type=float,
        default=DEFAULT_SOCKET_TIMEOUT,
        help="Seconds to wait for socket operations",
    )
    parser.add_argument(
        "--skip-tcp-check",
        action="store_true",
        help="Skip the quick TCP reachability check before PyChromecast discovery",
    )
    parser.add_argument("--list-devices", action="store_true", help="List configured Cast targets and exit")
    args = parser.parse_args()

    if args.list_devices:
        print_configured_targets()
        return 0

    try:
        target = apply_target_defaults(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not args.skip_tcp_check:
        print(f"Checking TCP reachability for {args.host}:{args.port}...")
        if check_tcp_port(args.host, args.port, timeout=min(args.socket_timeout, 5.0)):
            print("TCP check passed.")
        else:
            print("Continuing anyway; PyChromecast may still provide more detail.")

    pychromecast = import_pychromecast()
    if pychromecast is None:
        return 2

    browser = None
    cast = None
    try:
        print(f'Using configured target "{target.alias}" ({target.description}).')
        cast, browser = find_cast(
            pychromecast=pychromecast,
            name=args.name,
            host=args.host,
            discovery_timeout=args.discovery_timeout,
            socket_timeout=args.socket_timeout,
        )

        if cast is None:
            print(
                f'Could not find/connect to Chromecast "{args.name}" at {args.host}.\n'
                "Things to check: same network/VLAN, device powered on, mDNS allowed, "
                "and TCP port 8009 reachable."
            )
            return 1

        print("Waiting for Chromecast status...")
        cast.wait(timeout=args.socket_timeout)
        print_cast_summary(cast)
        return 0
    finally:
        if cast is not None:
            try:
                cast.disconnect(timeout=3, blocking=True)
            except Exception:
                pass
        stop_discovery(browser)


if __name__ == "__main__":
    raise SystemExit(main())
