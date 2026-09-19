"""Device-only collection/projection; scheduling and selector ownership stay in host.

These callbacks do I/O only through the supplied adapter runner. No work starts
on import. The existing worker limits, timeouts and recovery flag are preserved.
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
from .diagnostics import _safe_error
from .devices import _purifier_id, _purifier_state


def collect_plugs(*, run_cli_json, cli: Path, env: dict[str, str]) -> dict:
    listing = run_cli_json([str(cli), "--json", "plug-list"], timeout=12, env=env)
    plugs_map = (listing.get("plugs") or {}) if isinstance(listing, dict) else {}
    if not isinstance(plugs_map, dict):
        return {"ok": False, "error": "plug-list returned invalid data"}
    # An empty configured list is valid. It is different from a failed list.
    if listing.get("ok") is False and not plugs_map:
        return {"ok": False, "error": "plug-list failed"}
    names = list(plugs_map.keys())
    results: dict[str, dict] = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(len(names), 8)))
    futures = {
        name: pool.submit(
            run_cli_json,
            [str(cli), "--json", "plug-status", name],
            timeout=10,
            env=env,
        )
        for name in names
    }
    try:
        for name, future in futures.items():
            try:
                result = future.result(timeout=11)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": _safe_error(exc)}
            plug = result.get("plug") if isinstance(result, dict) else None
            results[name] = {
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "isOn": plug.get("is_on") if isinstance(plug, dict) else None,
                "host": plug.get("host") if isinstance(plug, dict) else plugs_map.get(name),
                "rssi": plug.get("rssi") if isinstance(plug, dict) else None,
                "alias": plug.get("alias") if isinstance(plug, dict) else None,
                "error": _safe_error(result.get("error")) if isinstance(result, dict) and result.get("error") else None,
            }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
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
