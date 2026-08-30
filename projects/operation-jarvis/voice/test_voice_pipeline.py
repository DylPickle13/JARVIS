from __future__ import annotations

import sys
import unittest
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

import voice_commands
import voice_pipeline


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
        pipeline = voice_pipeline.OmlxVoicePipeline(
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
