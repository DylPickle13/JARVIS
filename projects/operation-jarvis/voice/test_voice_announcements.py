"""Offline regressions for announcement configuration and response readiness."""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

VOICE_DIR = Path(__file__).resolve().parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

import voice_lines
import voice_pipeline


class AnnouncementConfigurationTests(unittest.TestCase):
    def test_defaults_and_environment_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = voice_pipeline.VoicePipelineConfig()
        self.assertTrue(config.processing_ack_enabled)
        self.assertEqual(config.processing_ack_text, "Generating your response, sir.")
        self.assertEqual(config.processing_ack_text, voice_lines.PROCESSING_ACK)
        with mock.patch.dict(os.environ, {
                "JARVIS_VOICE_PROCESSING_ACK_ENABLED": "off",
                "JARVIS_VOICE_PROCESSING_ACK_TEXT": " Custom acknowledgement. "}):
            config = voice_pipeline.VoicePipelineConfig()
        self.assertFalse(config.processing_ack_enabled)
        self.assertEqual(config.processing_ack_text, "Custom acknowledgement.")

    def test_steering_uses_configured_ack_and_honours_disabled_or_empty_text(self):
        for enabled, text, expected in (
                (True, "Custom acknowledgement.", ["Custom acknowledgement.", "Final reply."]),
                (False, "Custom acknowledgement.", ["Final reply."]),
                (True, "", ["Final reply."]),
                (True, "   ", ["Final reply."])):
            with self.subTest(enabled=enabled, text=text):
                pipeline = voice_pipeline.VoicePipeline(
                    voice_pipeline.VoicePipelineConfig(
                        processing_ack_enabled=enabled, processing_ack_text=text),
                    response_callback=lambda *_args: "Final reply.")
                paths = []
                playback = mock.Mock()
                synthesized = []
                def synthesize(segment):
                    synthesized.append(segment)
                    return Path("fixture-%s.wav" % len(synthesized))
                # A boundary after the initial generation snapshot reproduces the
                # previously undefined acknowledgement-global path. No sleeps,
                # model inference, files, or speaker operations are involved.
                generations = iter([0])
                with mock.patch.object(pipeline, "_synthesize_segment", side_effect=synthesize), \
                     mock.patch.object(voice_pipeline, "_turn_context_steering_generation",
                         side_effect=lambda _context: next(generations, 1)), \
                     mock.patch.object(voice_pipeline, "_turn_context_steering_tts_delay_seconds",
                         return_value=0):
                    reply, _elapsed = pipeline._complete_with_callback_and_synthesize_streaming(
                        "fixture request", audio_paths=paths,
                        audio_path_callback=playback, turn_context={})
                self.assertEqual(reply, "Final reply.")
                self.assertEqual(synthesized, expected)
                self.assertEqual(len(paths), len(expected))
                self.assertEqual(playback.call_count, len(expected))
                self.assertTrue(all(call.args[1] == 1 for call in playback.call_args_list))


class ReplyReadinessTests(unittest.TestCase):
    def pipeline(self, callback):
        return voice_pipeline.VoicePipeline(
            voice_pipeline.VoicePipelineConfig(stream_tts=False, unload_between_stages=False),
            response_callback=callback)

    def test_completed_reply_is_reported_before_failed_render_and_preserves_exception(self):
        pipeline = self.pipeline(lambda *_args: "Ready, sir.")
        ready = mock.Mock()
        def render(text):
            self.assertEqual(text, "Ready, sir.")
            ready.assert_called_once_with()
            raise OSError("fixture rendering failure")
        with self.assertRaisesRegex(OSError, "fixture rendering failure"):
            pipeline.synthesize_turn(Path("unused"), transcript="fixture", input_seconds=0,
                asr_seconds=0, final_synthesis=render, on_reply_ready=ready)
        ready.assert_called_once_with()

    def test_failed_or_empty_generation_is_not_reported_ready(self):
        for callback, error in (
                (mock.Mock(side_effect=RuntimeError("fixture generation failure")), RuntimeError),
                (lambda *_args: "", voice_pipeline.VoicePipelineNoOutputError)):
            with self.subTest(error=error):
                ready, render = mock.Mock(), mock.Mock()
                with self.assertRaises(error):
                    self.pipeline(callback).synthesize_turn(
                        Path("unused"), transcript="fixture", input_seconds=0,
                        asr_seconds=0, final_synthesis=render, on_reply_ready=ready)
                ready.assert_not_called()
                render.assert_not_called()


class RemovedConnectionGreetingTests(unittest.TestCase):
    def test_connection_greeting_entries_are_absent_from_catalogue(self):
        for name in ("FALLBACK_GREETING", "MAC_STARTUP_GREETING", "QUICK_RETURN_GREETINGS",
                     "GREETING_STATUS_SUFFIXES", "QUICK_RETURN_EXTRA_SUFFIX"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(voice_lines, name))

    def test_connection_greeting_formatter_and_configuration_are_removed(self):
        for name in ("voice_local_now", "parse_voice_greeting_timestamp", "format_contextual_greeting",
                     "JARVIS_VOICE_GREETING_COOLDOWN_MINUTES", "JARVIS_VOICE_GREETING_INCLUDE_STATUS",
                     "JARVIS_VOICE_CONTEXTUAL_GREETING_STATUS_SUFFIXES"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(voice_pipeline, name))


class FixedFailureWordingTests(unittest.TestCase):
    def test_error_notices_keep_their_exact_wording(self):
        self.assertEqual(voice_lines.REQUEST_FAILURE, "I couldn't complete that request, sir.")
        self.assertEqual(voice_lines.RENDER_FAILURE,
            "Your response is ready, sir, but I couldn't speak it.")


if __name__ == "__main__":
    unittest.main()
