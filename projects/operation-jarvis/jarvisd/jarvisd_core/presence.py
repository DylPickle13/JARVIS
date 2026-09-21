"""Read-only, private presence snapshots. No import-time I/O."""
import json
import math
import time
from pathlib import Path


def runtime_dir():
    return Path.home() / "Library/Application Support/JARVIS/presence"


def unknown(reason="listener-unavailable", zone="basement"):
    return {"subject": "dylan", "zone": zone, "state": "unknown",
            "stale": True, "ageSeconds": None, "sources": [], "reason": reason}


def read_status(path=None, now=None, zone="basement"):
    now = time.time() if now is None else now
    try:
        path = Path(path) if path else runtime_dir() / "state.json"
        if path.stat().st_size > 16384:
            return unknown(zone=zone)
        data = json.loads(path.read_text())
        stamp = data["updatedAt"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            return unknown(zone=zone)
        age = now - stamp
        if not 0 <= age <= 15:
            return unknown("listener-stale", zone)
        state = data["state"]
        if state not in ("nearby", "away", "unknown"):
            return unknown(zone=zone)
        sources = data.get("sources", [])
        if not isinstance(sources, list) or any(s not in ("watch", "iphone") for s in sources):
            return unknown(zone=zone)
        reason = data.get("reason", "not-ready" if state == "unknown" else "ble-proximity")
        if reason not in ("ble-proximity", "not-ready", "not-enrolled", "awaiting-placement", "listener-unavailable"):
            return unknown(zone=zone)
        return {"subject": "dylan", "zone": zone, "state": state,
                "stale": state == "unknown", "ageSeconds": round(age, 1),
                "sources": sources, "reason": reason}
    except (OSError, ValueError, KeyError, TypeError):
        return unknown(zone=zone)


def read_living_room():
    return read_status(runtime_dir() / "living-room.json", zone="living room")
