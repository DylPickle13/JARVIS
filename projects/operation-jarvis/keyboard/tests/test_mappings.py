"""Offline checks for the portable Razer application shortcuts; no input/HID access."""

import json
from pathlib import Path
import unittest


MAPPINGS = Path(__file__).resolve().parents[1] / "mappings"


class RazerApplicationMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads((MAPPINGS / "razer-app-launchers.json").read_text())
        cls.rules = document["rules"]
        cls.manipulators = cls.rules[0]["manipulators"]
        cls.by_button = {
            m["from"]["pointing_button"]: m for m in cls.manipulators
        }

    def test_exactly_one_rule_and_three_buttons(self):
        self.assertEqual(len(self.rules), 1)
        self.assertEqual(len(self.manipulators), 3)
        self.assertEqual(set(self.by_button), {"button3", "button4", "button5"})

    def test_button4_launches_or_focuses_spotify(self):
        self.assertEqual(
            self.by_button["button4"]["to"],
            [{"shell_command": "/usr/bin/open -b com.spotify.client"}],
        )

    def test_button5_launches_or_focuses_chrome(self):
        self.assertEqual(
            self.by_button["button5"]["to"],
            [{"shell_command": "/usr/bin/open -b com.google.Chrome"}],
        )

    def test_wheel_click_remains_disabled(self):
        self.assertEqual(self.by_button["button3"]["to"], [{"key_code": "vk_none"}])

    def test_only_exact_razer_pointing_device_matches(self):
        for manipulator in self.manipulators:
            with self.subTest(button=manipulator["from"]["pointing_button"]):
                self.assertEqual(manipulator["type"], "basic")
                self.assertEqual(
                    manipulator["conditions"],
                    [{"type": "device_if", "identifiers": [
                        {"vendor_id": 5426, "product_id": 152, "is_pointing_device": True}
                    ]}],
                )

    def test_actions_work_with_optional_modifiers(self):
        for button, manipulator in self.by_button.items():
            with self.subTest(button=button):
                self.assertEqual(
                    manipulator["from"],
                    {"pointing_button": button, "modifiers": {"optional": ["any"]}},
                )


if __name__ == "__main__":
    unittest.main()
