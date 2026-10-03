"""Offline regressions; inference, household audio, and sessions are mocked."""
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import wave
from zoneinfo import ZoneInfo

import room_audio_server as server
from voice_pipeline import VoicePipeline, VoicePipelineConfig


def write_wav(path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32)
    return path


class RoomGreetingTests(unittest.TestCase):
    def test_master_switch_disables_startup_and_arrival_without_synthesis(self):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._pipeline = mock.Mock()
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", False):
            for arrival in (False, True):
                result = bridge.synthesize_greeting(arrival=arrival)
                self.assertFalse(result["greetingEnabled"])
                self.assertEqual(result["greetingText"], "")
                self.assertEqual(result["audioWavBase64"], "")
        bridge._pipeline.synthesize_notice.assert_not_called()

    def test_startup_override_does_not_replace_fixed_arrival_phrase(self):
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", True), \
             mock.patch.object(server, "ROOM_GREETING_TEXT", "Custom startup."):
            self.assertEqual(server.select_room_greeting(), "Custom startup.")
            self.assertEqual(server.select_room_greeting(arrival=True), "Welcome back, sir")

    def test_disabled_greetings_do_not_disable_wake_acknowledgement(self):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._pipeline = mock.Mock()
        bridge._ack_lock = threading.Lock()
        bridge._wake_ack_audio_b64 = None
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "notice.wav")
            bridge._pipeline.synthesize_notice.return_value = path
            with mock.patch.object(server, "ROOM_GREETING_ENABLED", False):
                self.assertTrue(bridge._synthesize_wake_ack())
            bridge._pipeline.synthesize_notice.assert_called_once_with("Yes sir?")
            self.assertFalse(path.exists())

    def test_default_startup_is_neutral_and_preserves_connection_bookkeeping(self):
        now = datetime(2026, 10, 3, 10, tzinfo=ZoneInfo("America/Toronto"))
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", True), \
             mock.patch.object(server, "ROOM_GREETING_TEXT", ""), \
             mock.patch.object(server.voice_pipeline, "voice_local_now", return_value=now), \
             mock.patch.object(server, "_load_room_greeting_state_unlocked", return_value={}), \
             mock.patch.object(server, "_save_room_greeting_state_unlocked") as save, \
             mock.patch.object(server.voice_pipeline.random, "choice") as choose:
            self.assertEqual(server.select_room_greeting(), "JARVIS online. At your service, sir.")
        save.assert_called_once_with({"last_connected_at": now.isoformat()})
        choose.assert_not_called()

    def test_room_ack_configuration_is_forwarded_to_pipeline(self):
        with mock.patch.dict(server.os.environ, {"JARVIS_ROOM_AUDIO_SHARED_SESSION": ""}), \
             mock.patch.object(server.pi_rpc, "PiRpcSession"), \
             mock.patch.object(server, "PROCESSING_ACK_ENABLED", False), \
             mock.patch.object(server, "PROCESSING_ACK_TEXT", "Room-specific acknowledgement."):
            bridge = server.RoomAudioBridge()
        self.assertFalse(bridge._pipeline.config.processing_ack_enabled)
        self.assertEqual(bridge._pipeline.config.processing_ack_text,
            "Room-specific acknowledgement.")


class FailureAnnouncementTests(unittest.TestCase):
    def make_bridge(self, callback, render):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._pipeline = VoicePipeline(
            VoicePipelineConfig(stream_tts=False, unload_between_stages=False),
            response_callback=callback)
        bridge._pipeline._synthesize_segment = render
        bridge._jobs_lock = threading.Lock()
        bridge._jobs = {"fixture-turn": {}}
        bridge._prune_jobs_locked = mock.Mock()
        bridge._tts_prerender_enabled = False
        return bridge

    def test_failures_distinguish_completed_reply_from_incomplete_request(self):
        for stage, expected in (
                ("generation", "I couldn't complete that request, sir."),
                ("empty", "I couldn't complete that request, sir."),
                ("render", "Your response is ready, sir, but I couldn't speak it.")):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                if stage == "generation":
                    callback = mock.Mock(side_effect=RuntimeError("fixture generation failure"))
                else:
                    callback = mock.Mock(return_value="" if stage == "empty" else "Ready, sir.")
                render = mock.Mock(side_effect=OSError("fixture rendering failure"))
                bridge = self.make_bridge(callback, render)
                wav = Path(directory) / "input.wav"
                wav.write_bytes(b"unused fixture")
                notice = write_wav(Path(directory) / "notice.wav")
                bridge._pipeline.synthesize_notice = mock.Mock(return_value=notice)
                with self.assertLogs(server.LOGGER.name, level="ERROR"):
                    bridge._finish_async_turn("fixture-turn", wav, "fixture", 0, 0,
                        time.monotonic(), threading.Event())
                bridge._pipeline.synthesize_notice.assert_called_once_with(expected)
                result = bridge._jobs["fixture-turn"]["response"]
                self.assertEqual(result["status"], "error")
                self.assertFalse(result["ok"])
                self.assertTrue(result["audioWavBase64"])
                self.assertFalse(wav.exists())
                self.assertFalse(notice.exists())
                if stage != "render":
                    render.assert_not_called()

    def test_cancellation_after_reply_ready_does_not_announce_a_failure(self):
        cancel = threading.Event()
        def generate(*_args):
            cancel.set()
            return "Ready, sir."
        with tempfile.TemporaryDirectory() as directory:
            output = write_wav(Path(directory) / "reply.wav")
            bridge = self.make_bridge(generate, mock.Mock(return_value=output))
            bridge._pipeline.synthesize_notice = mock.Mock()
            wav = Path(directory) / "input.wav"
            wav.write_bytes(b"unused fixture")
            bridge._finish_async_turn("fixture-turn", wav, "fixture", 0, 0,
                time.monotonic(), cancel)
            self.assertEqual(bridge._jobs["fixture-turn"]["response"]["status"], "cancelled")
            bridge._pipeline.synthesize_notice.assert_not_called()
            self.assertFalse(output.exists())
            self.assertFalse(wav.exists())


if __name__ == "__main__":
    unittest.main()
