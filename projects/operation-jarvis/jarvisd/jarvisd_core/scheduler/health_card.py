"""Bounded, read-only interpretation of the native System health card evidence.

Consumes /api/v1/health's cached summary and device coverage, not its top-level
`ok` (request success) or on-demand `observations`. No daemon imports or I/O.
Failures and unknown/expired evidence are nonhealthy; valid inactive components
remain neutral. Labels below are fixed: server names/reasons never reach pushes.
"""
from __future__ import annotations

from datetime import datetime
import math

REQUIRED_COMPONENTS = (
    "services", "pi", "network", "plugs", "purifier", "codexQuota", "claudeQuota",
    "security", "devices", "overall",
)
# SystemHealthPresentation's required/excluded coverage and Minecraft-pair rule.
REQUIRED_DEVICES = frozenset((
    "keyboard-watcher", "keyboard", "mouse", "led-strip", "room-audio-mac",
    "hub", "door-sensor", "motion-sensor", "sensor-reader", "front-doorbell",
    "indoor-camera", "room-audio-pi", "family-room-tv", "family-room-speaker",
))
EXCLUDED_DEVICES = frozenset(("iphone-usb", "watch", "master-chief"))
LABELS = {
    "services": "services", "pi": "Pi data", "network": "network data",
    "plugs": "plugs", "purifier": "purifiers", "codexQuota": "Codex usage",
    "claudeQuota": "Claude usage", "security": "sensor reads", "devices": "devices",
    "overall": "backend summary", "sensor-reader": "sensor reader",
    "door-sensor": "door sensor", "motion-sensor": "motion sensor",
    "family-room-tv": "TV Cast", "family-room-speaker": "speaker",
    "hub": "hub", "service:minecraft-server": "Minecraft server",
    "service:minecraft-jarvis-bot": "Minecraft bot",
}


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def evaluate(payload, *, now: float) -> str | None:
    """None only for complete, current healthy card evidence; <=80 safe chars else.

    Unknown/checking is deliberately alertable after the watchdog debounce, not
    described as a physical device outage. Optional *services* may be inactive;
    optional device unknowns remain unknown just as in the app's card.
    """
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return "health request not successful"
    health = payload.get("health")
    if (not isinstance(health, dict) or health.get("scope") != "cached_status_health"
            or type(health.get("healthy")) is not bool):
        return "health summary unavailable"
    components = health.get("components")
    if (not isinstance(components, dict) or not 1 <= len(components) <= 32
            or not set(REQUIRED_COMPONENTS).issubset(components)):
        return "health components incomplete"
    bad = []
    for key, component in components.items():
        label = LABELS.get(key, "service" if key.startswith("service:") else "component")
        if not isinstance(component, dict):
            bad.append(label)
            continue
        state, reason = component.get("state"), component.get("reason")
        if state == "inactive" and reason in ("optional_inactive", "monitoring_disabled"):
            continue
        source, expiry = (timestamp(component.get(k)) for k in ("sourceObservedAt", "validUntil"))
        if (state != "healthy" or reason != "current" or source is None or expiry is None
                or not source <= now <= expiry):
            bad.append(label)
    pair = {"service:minecraft-server", "service:minecraft-jarvis-bot"}
    if pair.intersection(components) and not pair.issubset(components):
        bad.append("Minecraft inventory")
    if health["healthy"] is not True and not bad:
        bad.append("backend summary")

    coverage = payload.get("deviceHealth")
    if (not isinstance(coverage, dict) or type(coverage.get("version")) is not int
            or coverage["version"] != 1 or coverage.get("scope") != "device_check_coverage"
            or not isinstance(coverage.get("devices"), list) or len(coverage["devices"]) > 40):
        bad.append("device coverage")
    else:
        rows = coverage["devices"]
        ids = [row.get("id") for row in rows if isinstance(row, dict)]
        if (len(ids) != len(rows) or any(not isinstance(key, str) for key in ids)
                or len(set(ids)) != len(ids) or not REQUIRED_DEVICES.issubset(ids)):
            bad.append("device inventory")
        else:
            for row in rows:
                key = row["id"]
                if key in EXCLUDED_DEVICES:
                    continue
                source = timestamp(row.get("lastAttemptAt") if row.get("lastAttemptAt") is not None
                                   else row.get("lastSuccessAt"))
                limit = row.get("freshnessLimitSeconds")
                if (row.get("coverage") == "unmonitored" or row.get("state") != "available"
                        or source is None or not number(limit) or limit <= 0
                        or not 0 <= now - source <= limit):
                    bad.append(LABELS.get(key, "device check"))
    if not bad:
        return None
    # Keep persistent incident state compatible and never include raw backend data.
    labels = list(dict.fromkeys(bad))
    return ("health not healthy/current: " + ", ".join(labels[:3])
            + ("; more checks" if len(labels) > 3 else ""))[:80]
