"""Offline parity cases for SystemHealthPresentation + DeviceHealthCheck."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "jarvisd_core/scheduler/health_card.py"
spec = importlib.util.spec_from_file_location("health_card_fixture", PATH)
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)
NOW = 1792290000.0


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def healthy(now=NOW):
    component = {"state": "healthy", "reason": "current",
                 "sourceObservedAt": stamp(now-2), "validUntil": stamp(now+28)}
    return {"ok": True, "health": {"scope": "cached_status_health", "healthy": True,
        "components": {key: deepcopy(component) for key in card.REQUIRED_COMPONENTS}},
        "deviceHealth": {"version": 1, "scope": "device_check_coverage", "devices": [
            {"id": key, "state": "available", "coverage": "background",
             "lastAttemptAt": stamp(now-2), "freshnessLimitSeconds": 120}
            for key in sorted(card.REQUIRED_DEVICES)]}}


class HealthCardTests(unittest.TestCase):
    def test_current_healthy_card_and_ignored_on_demand_read_errors(self):
        value = healthy()
        value["observations"] = {"/api/v1/omlx": {"availability": "unavailable"}}
        self.assertIsNone(card.evaluate(value, now=NOW))

    def test_ok_true_is_not_health_and_sensor_fault_is_detected(self):
        value = healthy()
        value["health"]["healthy"] = False
        value["health"]["components"]["security"]["state"] = "unavailable"
        self.assertIn("sensor reads", card.evaluate(value, now=NOW))
        self.assertIsNotNone(card.evaluate({"ok": True}, now=NOW))

    def test_healthy_aggregate_does_not_hide_failed_reader_or_sensor(self):
        for key in ("sensor-reader", "motion-sensor"):
            value = healthy()
            next(row for row in value["deviceHealth"]["devices"] if row["id"] == key)["state"] = "unavailable"
            self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_cast_is_diagnostic_only_even_failed_expired_unmonitored_or_absent(self):
        for key in ("family-room-tv", "family-room-speaker"):
            self.assertNotIn(key, card.REQUIRED_DEVICES)
            for state in ("unavailable", "unknown", "available"):
                value = healthy()
                value["deviceHealth"]["devices"].append({
                    "id": key, "state": state, "coverage": "unmonitored",
                    "lastAttemptAt": stamp(NOW-9999), "freshnessLimitSeconds": 150})
                self.assertIsNone(card.evaluate(value, now=NOW))
        self.assertIsNone(card.evaluate(healthy(), now=NOW))

    def test_each_component_can_make_card_nonhealthy(self):
        for key in card.REQUIRED_COMPONENTS:
            for state in ("unknown", "degraded", "unavailable", "checking", "PRIVATE"):
                with self.subTest(key=key, state=state):
                    value = healthy()
                    value["health"]["components"][key]["state"] = state
                    self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_current_healthy_flags_cannot_hide_expired_future_or_missing_evidence(self):
        for patch in ({"sourceObservedAt": stamp(NOW+10)}, {"validUntil": stamp(NOW-1)},
                      {"sourceObservedAt": "bad"}, {"validUntil": None}, {"reason": "PRIVATE"}):
            value = healthy()
            value["health"]["components"]["overall"].update(patch)
            self.assertIsNotNone(card.evaluate(value, now=NOW))
        for patch in ({"lastAttemptAt": stamp(NOW-121)}, {"lastAttemptAt": stamp(NOW+1)},
                      {"freshnessLimitSeconds": True}, {"freshnessLimitSeconds": float('nan')},
                      {"freshnessLimitSeconds": 0}, {"coverage": "unmonitored"},
                      {"state": "unknown"}):
            value = healthy()
            value["deviceHealth"]["devices"][0].update(patch)
            self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_devices_use_success_timestamp_fallback_only_without_attempt(self):
        value = healthy()
        row = value["deviceHealth"]["devices"][0]
        row["lastSuccessAt"] = row.pop("lastAttemptAt")
        self.assertIsNone(card.evaluate(value, now=NOW))
        row["lastAttemptAt"] = "bad"
        self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_optional_inactive_services_and_disabled_sensor_monitoring_are_neutral(self):
        value = healthy()
        value["health"]["components"].update({
            "service:minecraft-server": deepcopy(value["health"]["components"]["services"]),
            "service:minecraft-jarvis-bot": {"state": "inactive", "reason": "optional_inactive"},
            "security": {"state": "inactive", "reason": "monitoring_disabled"}})
        self.assertIsNone(card.evaluate(value, now=NOW))
        del value["health"]["components"]["service:minecraft-server"]
        self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_excluded_devices_do_not_affect_card_optional_unknown_devices_do(self):
        value = healthy()
        for key in card.EXCLUDED_DEVICES:
            value["deviceHealth"]["devices"].append({"id": key, "state": "unknown"})
        self.assertIsNone(card.evaluate(value, now=NOW))
        value["deviceHealth"]["devices"].append({"id": "headset", "state": "unknown", "expectation": "optional"})
        self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_incomplete_malformed_unsupported_coverage_never_green(self):
        for replacement in (None, {}, {"version": True}, {"version": 2},
                            {"version": 1, "scope": "device_check_coverage", "devices": []}):
            value = healthy(); value["deviceHealth"] = replacement
            self.assertIsNotNone(card.evaluate(value, now=NOW))
        for row in (None, {}, {"id": []}, {"id": 1}):
            value = healthy(); value["deviceHealth"]["devices"].append(row)
            self.assertIsNotNone(card.evaluate(value, now=NOW))
        value = healthy(); value["deviceHealth"]["devices"].append(value["deviceHealth"]["devices"][0])
        self.assertIsNotNone(card.evaluate(value, now=NOW))
        value = healthy(); del value["health"]["components"]["pi"]
        self.assertIsNotNone(card.evaluate(value, now=NOW))
        for flag in (None, 1, "true", False):
            value = healthy(); value["health"]["healthy"] = flag
            self.assertIsNotNone(card.evaluate(value, now=NOW))

    def test_unknown_backend_strings_are_never_notification_content(self):
        value = healthy()
        value["health"]["components"]["service:PRIVATE"] = {"state": "unavailable", "reason": "SECRET"}
        value["deviceHealth"]["devices"].append({"id": "PASSWORD", "name": "PRIVATE", "state": "unavailable"})
        result = card.evaluate(value, now=NOW)
        self.assertLessEqual(len(result), 80)
        for secret in ("PRIVATE", "SECRET", "PASSWORD"):
            self.assertNotIn(secret, result)

    def test_sensor_failure_then_actual_recovery(self):
        value = healthy()
        baseline = deepcopy(value)
        value["health"]["healthy"] = False
        value["health"]["components"]["security"].update(state="unavailable", reason="sensor_read_failed")
        for row in value["deviceHealth"]["devices"]:
            if row["id"] in {"door-sensor", "motion-sensor", "sensor-reader"}:
                row["state"] = "unavailable"
        self.assertIsNotNone(card.evaluate(value, now=NOW))
        self.assertIsNone(card.evaluate(baseline, now=NOW))
