"""Offline regression checks for the opt-in Clef migration smoke client."""

import copy
import importlib.util
import json
import pathlib
import struct
import subprocess
import sys
import unittest
import zlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "smoke-clef-omlx.py"
SPEC = importlib.util.spec_from_file_location("smoke_clef_omlx", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class SmokeClientTests(unittest.TestCase):
    def setUp(self):
        self.answers = json.loads((smoke.FIXTURES / "baseline.json").read_text())[
            "checks"
        ][0]["answers"]
        self.response = {
            "model": "clef",
            "answers": copy.deepcopy(self.answers),
            "usage": {"input_tokens": 307, "output_tokens": 0},
        }

    def test_baseline_validates_and_matches(self):
        smoke.validate_answers(self.response, "clef")
        self.assertEqual(smoke.compare_baseline(self.answers, self.answers), 0)

    def test_probability_drift_is_rejected(self):
        other = copy.deepcopy(self.answers)
        other["outage"]["noul"] -= 0.02
        with self.assertRaises(AssertionError):
            smoke.compare_baseline(other, self.answers)

    def test_nonfinite_probabilities_are_rejected(self):
        self.response["answers"]["department"]["probabilities"]["technical"] = float(
            "nan"
        )
        with self.assertRaises(AssertionError):
            smoke.validate_answers(self.response, "clef")

    def test_identity_and_usage_are_checked(self):
        with self.assertRaises(AssertionError):
            smoke.validate_answers(self.response, "wrong-model")
        self.response["usage"]["output_tokens"] = 1
        with self.assertRaises(AssertionError):
            smoke.validate_answers(self.response, "clef")

    def test_rejects_non_base_urls_before_credentials_or_network(self):
        for url in (
            "http://127.0.0.1:8000?unused=1",
            "http://127.0.0.1:8000#unused",
            "http://127.0.0.1:8000/v1",
            "http://localhost:8000",
            "https://127.0.0.1:8000",
        ):
            with self.subTest(url=url):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--url",
                        url,
                        "--settings",
                        "/nonexistent/omlx-smoke-test-settings.json",
                        "--report",
                        "/tmp/clef-smoke-unused-report.json",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("loopback HTTP base URL", result.stderr)

    def test_red_png_is_valid_without_imaging_dependencies(self):
        png = smoke.red_png(4)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        offset, chunks = 8, {}
        while offset < len(png):
            length = struct.unpack(">I", png[offset : offset + 4])[0]
            kind = png[offset + 4 : offset + 8]
            data = png[offset + 8 : offset + 8 + length]
            crc = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])[
                0
            ]
            self.assertEqual(crc, zlib.crc32(kind + data))
            chunks[kind] = data
            offset += 12 + length
        self.assertEqual(struct.unpack(">II", chunks[b"IHDR"][:8]), (4, 4))
        self.assertEqual(
            zlib.decompress(chunks[b"IDAT"]), (b"\x00" + b"\xff\x00\x00" * 4) * 4
        )
        self.assertIn(b"IEND", chunks)


if __name__ == "__main__":
    unittest.main()
