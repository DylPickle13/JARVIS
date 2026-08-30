from __future__ import annotations

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

VOICE_DIR = Path(__file__).resolve().parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

import voice_commands
import voice_pipeline


class _FakeASRBackend:
    def __init__(self, name: str, *, transcript: str = "", error: Exception | None = None) -> None:
        self.name = name
        self.transcript = transcript
        self.error = error
        self.calls: list[Path] = []
        self.warm_calls = 0

    def transcribe(self, audio_path: Path) -> str:
        self.calls.append(audio_path)
        if self.error is not None:
            raise self.error
        return self.transcript

    def warm_up(self) -> dict[str, object]:
        self.warm_calls += 1
        if self.error is not None:
            raise self.error
        return {"ok": True, "backend": self.name, "available": True}

    def status(self) -> dict[str, object]:
        return {"ok": self.error is None, "backend": self.name, "available": self.error is None}


class FinalResponseSpeechTests(unittest.TestCase):
    def test_final_response_tables_and_long_sections_are_chunked_without_truncation(self) -> None:
        response = """Here's the weather for tomorrow:

| | |
|---|---|
| **Condition** | Cloudy |
| **High** | 24°C |
| **Wind** | NW 20 km/h, becoming light early afternoon |
| **UV Index** | 5 (moderate) |

It'll be cloudy but mild — no rain expected. Dress in layers tonight.
"""
        pipeline = voice_pipeline.VoicePipeline(
            voice_pipeline.VoicePipelineConfig(max_tts_segments=0, max_tts_chars_per_segment=80)
        )
        cleaned = pipeline._clean_text_for_tts(response)
        segments = pipeline._split_for_tts(cleaned)
        self.assertTrue(segments)
        self.assertTrue(all(0 < len(segment) <= 80 for segment in segments))
        self.assertEqual(" ".join(segments), " ".join(cleaned.split()))
        self.assertIn("Condition: Cloudy.", cleaned)
        self.assertIn("becoming light early afternoon", cleaned)
        self.assertIn("UV Index: 5 (moderate).", cleaned)
        self.assertIn("no rain expected", cleaned)
        self.assertIn("Dress in layers tonight", cleaned)

    def test_unbroken_text_is_split_without_dropping_characters(self) -> None:
        text = "x" * 201
        chunks = voice_pipeline._bounded_tts_chunks(text, 80)
        self.assertEqual([len(chunk) for chunk in chunks], [80, 80, 41])
        self.assertEqual("".join(chunks), text)

    def test_wake_word_aliases_are_normalized_for_local_voice(self) -> None:
        self.assertEqual(voice_pipeline.normalize_voice_transcript_wake_words("Travis turn on the light"), "jarvis turn on the light")


class ASRRoutingTests(unittest.TestCase):
    def test_code_defaults_are_apple_only(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            pipeline = voice_pipeline.VoicePipeline(
                voice_pipeline.VoicePipelineConfig(),
                response_callback=lambda *_args: "unused",
            )

        self.assertEqual(pipeline._asr_backend, "apple-speech")
        self.assertEqual(pipeline._asr_fallback_backend, "")
        self.assertEqual(pipeline._interrupt_asr_backend, "apple-dictation")
        self.assertEqual(pipeline._interrupt_asr_fallback_backend, "")
        self.assertEqual(
            pipeline.configured_asr_backends,
            ("apple-speech", "apple-dictation"),
        )
        self.assertEqual(pipeline.configured_models, ())

    def make_wav(self) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 1600)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def make_pipeline(
        self,
        *,
        primary: str = "apple-speech",
        fallback: str = "",
        interrupt: str = "",
        interrupt_fallback: str = "",
    ) -> voice_pipeline.VoicePipeline:
        config = voice_pipeline.VoicePipelineConfig(
            asr_backend=primary,
            asr_fallback_backend=fallback,
            interrupt_asr_backend=interrupt,
            interrupt_asr_fallback_backend=interrupt_fallback,
            unload_between_stages=False,
        )
        return voice_pipeline.VoicePipeline(config, response_callback=lambda *_args: "unused")

    def test_apple_only_pi_rpc_pipeline_has_no_omlx_models(self) -> None:
        pipeline = self.make_pipeline()
        self.assertEqual(pipeline.configured_asr_backends, ("apple-speech",))
        self.assertEqual(pipeline.configured_models, ())

    def test_falls_back_to_omlx_when_apple_fails(self) -> None:
        pipeline = self.make_pipeline(fallback="omlx")
        apple = _FakeASRBackend("apple-speech", error=RuntimeError("helper offline"))
        omlx = _FakeASRBackend("omlx", transcript="Fallback transcript")
        pipeline._asr_backends.update({"apple-speech": apple, "omlx": omlx})
        wav_path = self.make_wav()

        transcript, input_seconds, asr_seconds = pipeline.transcribe_audio(wav_path)

        self.assertEqual(transcript, "Fallback transcript")
        self.assertAlmostEqual(input_seconds, 0.1)
        self.assertGreaterEqual(asr_seconds, 0.0)
        self.assertEqual(apple.calls, [wav_path])
        self.assertEqual(omlx.calls, [wav_path])

    def test_empty_primary_transcript_uses_fallback(self) -> None:
        pipeline = self.make_pipeline(fallback="omlx")
        apple = _FakeASRBackend("apple-speech", transcript="")
        omlx = _FakeASRBackend("omlx", transcript="Heard by Whisper")
        pipeline._asr_backends.update({"apple-speech": apple, "omlx": omlx})

        transcript, _, _ = pipeline.transcribe_audio(self.make_wav())

        self.assertEqual(transcript, "Heard by Whisper")

    def test_interrupt_uses_apple_dictation_without_calling_turn_or_fallback_asr(self) -> None:
        pipeline = self.make_pipeline(
            fallback="omlx",
            interrupt="apple-dictation",
            interrupt_fallback="omlx",
        )
        speech = _FakeASRBackend("apple-speech", transcript="normal turn")
        dictation = _FakeASRBackend("apple-dictation", transcript="Stop.")
        omlx = _FakeASRBackend("omlx", transcript="stop")
        pipeline._asr_backends.update(
            {"apple-speech": speech, "apple-dictation": dictation, "omlx": omlx}
        )
        wav_path = self.make_wav()

        transcript, _, _ = pipeline.transcribe_audio(wav_path, purpose="interrupt")

        self.assertEqual(transcript, "Stop.")
        self.assertEqual(speech.calls, [])
        self.assertEqual(dictation.calls, [wav_path])
        self.assertEqual(omlx.calls, [])

    def test_interrupt_falls_back_to_omlx_when_apple_dictation_is_empty(self) -> None:
        pipeline = self.make_pipeline(
            fallback="omlx",
            interrupt="apple-dictation",
            interrupt_fallback="omlx",
        )
        dictation = _FakeASRBackend("apple-dictation", transcript="")
        omlx = _FakeASRBackend("omlx", transcript="stop")
        pipeline._asr_backends.update({"apple-dictation": dictation, "omlx": omlx})
        wav_path = self.make_wav()

        transcript, _, _ = pipeline.transcribe_audio(wav_path, purpose="interrupt")

        self.assertEqual(transcript, "stop")
        self.assertEqual(dictation.calls, [wav_path])
        self.assertEqual(omlx.calls, [wav_path])

    def test_status_reports_distinct_apple_dictation_interrupt_health(self) -> None:
        pipeline = self.make_pipeline(
            fallback="omlx",
            interrupt="apple-dictation",
            interrupt_fallback="omlx",
        )
        speech = _FakeASRBackend("apple-speech", transcript="normal turn")
        dictation = _FakeASRBackend("apple-dictation", transcript="stop")
        pipeline._asr_backends.update({"apple-speech": speech, "apple-dictation": dictation})

        status = pipeline.asr_status()

        self.assertEqual(status["backend"], "apple-speech")
        self.assertEqual(status["fallbackBackend"], "omlx")
        self.assertEqual(status["interruptBackend"], "apple-dictation")
        self.assertEqual(status["interruptFallbackBackend"], "omlx")
        self.assertEqual(
            status["interrupt"],
            {
                "ok": True,
                "backend": "apple-dictation",
                "available": True,
                "fallbackBackend": "omlx",
            },
        )

    def test_warm_up_skips_omlx_when_no_omlx_stage_is_configured(self) -> None:
        pipeline = self.make_pipeline()
        apple = _FakeASRBackend("apple-speech", transcript="ready")
        pipeline._asr_backends["apple-speech"] = apple
        pipeline._validate_tts_backend = lambda: None
        pipeline._request = lambda *_args, **_kwargs: self.fail("warm-up must not contact oMLX")

        pipeline.warm_up()

        self.assertEqual(apple.warm_calls, 1)


class InterruptCommandTests(unittest.TestCase):
    def test_accepts_only_exact_normalized_stop(self) -> None:
        for transcript in ("stop", "Stop.", " STOP! "):
            with self.subTest(transcript=transcript):
                self.assertEqual(voice_commands.parse_voice_interrupt_command(transcript, busy=True), "stop")

    def test_rejects_longer_and_negated_phrases(self) -> None:
        for transcript in ("don't stop", "do not stop", "bus stop", "stop stop", "stopwatch", ""):
            with self.subTest(transcript=transcript):
                self.assertEqual(voice_commands.parse_voice_interrupt_command(transcript, busy=True), "")

    def test_rejects_bare_stop_while_idle(self) -> None:
        self.assertEqual(voice_commands.parse_voice_interrupt_command("stop", busy=False), "")


if __name__ == "__main__":
    unittest.main()
