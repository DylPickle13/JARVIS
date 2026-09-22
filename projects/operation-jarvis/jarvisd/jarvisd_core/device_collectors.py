"""Device-only collection/projection; scheduling and selector ownership stay in host.

These callbacks do I/O only through the supplied adapter runner. No work starts
on import. The existing worker limits, timeouts and recovery flag are preserved.
"""
from __future__ import annotations

from pathlib import Path
from .diagnostics import _safe_error
from .devices import _purifier_id, _purifier_state


def collect_plugs(*, run_cli_json, cli: Path, env: dict[str, str]) -> dict:
    # One worker/vendor pair instead of list + N worker/vendor pairs. A failed
    # batch never falls back to individual subprocesses or replays any operation.
    listing = run_cli_json([str(cli), "--json", "plug-status-all"], timeout=12, env=env)
    plugs_map = listing.get('plugs') if isinstance(listing, dict) else None
    if (not isinstance(listing, dict) or listing.get('ok') is not True
            or not isinstance(plugs_map, dict) or len(plugs_map) > 64):
        return {'ok': False, 'error': 'Plug collection unavailable'}
    names = list(plugs_map)
    results = {}
    for name, plug in plugs_map.items():
        if not isinstance(name, str) or not isinstance(plug, dict):
            return {'ok': False, 'error': 'Invalid plug collection'}
        valid = plug.get('ok') is True and type(plug.get('is_on')) is bool
        results[name] = {
            'ok': valid, 'isOn': plug.get('is_on') if valid else None,
            'host': plug.get('host'), 'rssi': plug.get('rssi') if valid else None,
            'alias': plug.get('alias') if valid else None,
            'error': None if valid else 'Plug read unavailable',
        }
    successful = [r for r in results.values() if r.get("ok")]
    on_count = sum(1 for result in successful if result.get("isOn") is True)
    return {
        "ok": bool(names == [] or successful),
        "count": len(results),
        "onCount": on_count,
        "plugs": results,
    }


def collect_purifier(*, run_cli_json, cli: Path, env: dict[str, str], retry: bool = False) -> tuple[dict, dict | None]:
    args = [str(cli), "--json", "purifier-status-all"]
    if retry:
        args.append("--retry-cooldown")
    result = run_cli_json(args, timeout=25, env=env)
    incoming = result.get("purifiers") if isinstance(result, dict) else None
    if not isinstance(incoming, dict):
        return {"ok": False, "error": _safe_error(result.get("error") or "Purifier refresh unavailable")}, None
    devices, selectors = {}, {}
    default_id = None
    for cid, entry in incoming.items():
        if not isinstance(cid, str) or not cid or not isinstance(entry, dict):
            continue
        device_id = _purifier_id(cid)
        selectors[device_id] = cid
        data = entry.get("status")
        state = _purifier_state(data) if entry.get("ok") is True and isinstance(data, dict) else {
            "ok": False, "name": entry.get("name"), "error": "Device refresh unavailable"}
        state["deviceID"] = device_id
        devices[device_id] = state
        if entry.get("isDefault") is True:
            default_id = device_id
    return {"ok": True, "devices": devices, "defaultDeviceID": default_id}, selectors
