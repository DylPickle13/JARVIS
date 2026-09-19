"""Current authentication policy. No environment reads or network activity.

Network trust and token authentication remain distinct modes. Event tokens are
not general control credentials. Fine-grained integration scopes are future work.
"""
from __future__ import annotations

import hmac
import ipaddress


AUTH_MODES = frozenset({"trusted-network", "token"})


def client_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(raw)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return address.ipv4_mapped
        return address
    except ValueError:
        return None


def trusted_networks(raw_cidrs: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(raw.strip(), strict=False)
                 for raw in raw_cidrs.split(",") if raw.strip())


def validate_config(*, mode: str, api_token: str, trusted_cidrs: str, max_json_bytes: int) -> None:
    if mode not in AUTH_MODES:
        raise RuntimeError(f"JARVISD_AUTH_MODE must be one of {sorted(AUTH_MODES)}")
    if max_json_bytes < 1024 or max_json_bytes > 10 * 1024 * 1024:
        raise RuntimeError("JARVISD_MAX_JSON_BODY_BYTES must be between 1024 and 10485760")
    if mode == "token" and not api_token:
        raise RuntimeError("JARVISD_AUTH_MODE=token requires JARVIS_API_TOKEN")
    if mode == "trusted-network" and not trusted_networks(trusted_cidrs):
        raise RuntimeError("trusted-network mode requires at least one trusted CIDR")


def authorized(*, mode: str, address, token: str, scope: str,
               api_token: str, event_token: str, trusted_cidrs: str) -> bool:
    if mode == "trusted-network":
        if address is None:
            return False
        return any(address in network for network in trusted_networks(trusted_cidrs))
    if mode != "token":
        return False
    expected = event_token if scope == "events" and event_token else api_token
    return bool(token and expected and hmac.compare_digest(token, expected))
