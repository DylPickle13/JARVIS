from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import asr_backends


class BackendNameTests(unittest.TestCase):
    def test_normalizes_supported_aliases(self) -> None:
        self.assertEqual(asr_backends.normalize_asr_backend("apple"), "apple-speech")
        self.assertEqual(asr_backends.normalize_asr_backend("dictation_transcriber"), "apple-dictation")
        self.assertEqual(asr_backends.normalize_asr_backend("whisper"), "omlx")
        self.assertEqual(asr_backends.normalize_asr_backend("", allow_empty=True), "")

    def test_rejects_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            asr_backends.normalize_asr_backend("unknown")


class AppleSpeechBackendTests(unittest.TestCase):
    def make_backend(self) -> asr_backends.AppleSpeechASRBackend:
        return asr_backends.AppleSpeechASRBackend(
            asr_backends.AppleSpeechASRSettings(
                helper_path=Path("/tmp/fake-apple-asr"),
                locale="en-CA",
                engine="speech",
                timeout_seconds=9,
                contextual_strings=("Jarvis", "Pickering", "Jarvis"),
            )
        )

    @mock.patch.object(asr_backends.AppleSpeechASRBackend, "_validate_helper")
    @mock.patch("asr_backends.subprocess.run")
    def test_transcribes_with_bounded_context_and_strict_json(
        self,
        run_mock: mock.Mock,
        _validate_mock: mock.Mock,
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"ok": True, "transcript": "  Jarvis,   hello.  "}),
            stderr="",
        )
        backend = self.make_backend()
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            transcript = backend.transcribe(Path(audio.name))

        self.assertEqual(transcript, "Jarvis, hello.")
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:6], ["/tmp/fake-apple-asr", "transcribe", "--engine", "speech", "--locale", "en-CA"])
        self.assertEqual(command.count("--context"), 2)
        self.assertIn("Pickering", command)
        self.assertNotIn("shell", run_mock.call_args.kwargs)

    @mock.patch.object(asr_backends.AppleSpeechASRBackend, "_validate_helper")
    @mock.patch("asr_backends.subprocess.run")
    def test_surfaces_helper_error_json(self, run_mock: mock.Mock, _validate_mock: mock.Mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=json.dumps({"ok": False, "error": "asset missing"}),
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with self.assertRaisesRegex(asr_backends.ASRBackendError, "asset missing"):
                self.make_backend().transcribe(Path(audio.name))

    @mock.patch.object(asr_backends.AppleSpeechASRBackend, "_validate_helper")
    @mock.patch("asr_backends.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="helper", timeout=9))
    def test_converts_timeout_to_backend_error(self, _run_mock: mock.Mock, _validate_mock: mock.Mock) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with self.assertRaisesRegex(asr_backends.ASRBackendError, "timed out"):
                self.make_backend().transcribe(Path(audio.name))

    @mock.patch.object(asr_backends.AppleSpeechASRBackend, "_validate_helper")
    @mock.patch("asr_backends.subprocess.run")
    def test_health_requires_installed_asset(self, run_mock: mock.Mock, _validate_mock: mock.Mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "available": True,
                    "locale": "en_CA",
                    "assetStatus": "supported",
                }
            ),
            stderr="",
        )
        status = self.make_backend().status()
        self.assertFalse(status["available"])
        self.assertEqual(status["assetStatus"], "supported")


if __name__ == "__main__":
    unittest.main()
