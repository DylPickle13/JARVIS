"""Offline regressions; inference, household audio, and sessions are mocked."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import wave

from types import SimpleNamespace

import room_audio_server as server
import pi_room_audio_client as client
from voice_pipeline import VoicePipeline, VoicePipelineConfig


def write_wav(path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32)
    return path


class RoomGreetingTests(unittest.TestCase):
    def make_bridge(self):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._pipeline = mock.Mock()
        bridge._pipeline.asr_status.return_value = {}
        bridge._model, bridge._thinking = "fixture", "off"
        return bridge

    def test_master_switch_disables_arrival_without_synthesis(self):
        bridge = self.make_bridge()
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", False):
            for arrival in (False, True):
                result = bridge.synthesize_greeting(arrival=arrival)
                self.assertFalse(result["greetingEnabled"])
                self.assertEqual(result["greetingText"], "")
                self.assertEqual(result["audioWavBase64"], "")
        bridge._pipeline.synthesize_notice.assert_not_called()

    def test_retired_startup_override_cannot_replace_fixed_arrival_phrase(self):
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", True), \
             mock.patch.dict(server.os.environ, {"JARVIS_ROOM_AUDIO_GREETING_TEXT": "Custom startup."}):
            self.assertEqual(server.select_room_greeting(), "")
            self.assertEqual(server.select_room_greeting(arrival=True), "Welcome back, sir")

    def test_startup_is_silent_even_with_legacy_enable_flags_and_saved_override(self):
        bridge = self.make_bridge()
        for enabled in (False, True):
            with self.subTest(arrivals_enabled=enabled), \
                 mock.patch.object(server, "ROOM_GREETING_ENABLED", enabled), \
                 mock.patch.dict(server.os.environ, {
                     "JARVIS_ROOM_AUDIO_STARTUP_GREETING": "1",
                     "JARVIS_ROOM_AUDIO_GREETING_ON_RECONNECT": "1",
                     "JARVIS_ROOM_AUDIO_GREETING_TEXT": "Custom startup.",
                     "JARVIS_VOICE_GREETING_COOLDOWN_MINUTES": "10",
                     "JARVIS_VOICE_GREETING_INCLUDE_STATUS": "1"}):
                result = bridge.synthesize_greeting()
                self.assertTrue(result["ok"])
                self.assertFalse(result["greetingEnabled"])
                self.assertEqual(result["greetingText"], "")
                self.assertEqual(result["audioWavBase64"], "")
        bridge._pipeline.synthesize_notice.assert_not_called()
        for name in ("ROOM_GREETING_TEXT", "ROOM_GREETING_STATE_PATH", "ROOM_GREETING_LOCK",
                     "_load_room_greeting_state_unlocked", "_save_room_greeting_state_unlocked"):
            self.assertFalse(hasattr(server, name))

    def test_arrival_synthesis_remains_enabled(self):
        bridge = self.make_bridge()
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "arrival.wav")
            bridge._pipeline.synthesize_notice.return_value = path
            with mock.patch.object(server, "ROOM_GREETING_ENABLED", True):
                result = bridge.synthesize_greeting(arrival=True)
            self.assertTrue(result["greetingEnabled"])
            self.assertEqual(result["greetingText"], "Welcome back, sir")
            self.assertTrue(result["audioWavBase64"])
            bridge._pipeline.synthesize_notice.assert_called_once_with("Welcome back, sir")
            self.assertFalse(path.exists())

    def test_disabled_arrivals_do_not_disable_wake_acknowledgement(self):
        bridge = self.make_bridge()
        bridge._ack_lock = threading.Lock()
        bridge._wake_ack_audio_b64 = None
        with tempfile.TemporaryDirectory() as directory:
            path = write_wav(Path(directory) / "notice.wav")
            bridge._pipeline.synthesize_notice.return_value = path
            with mock.patch.object(server, "ROOM_GREETING_ENABLED", False):
                self.assertTrue(bridge._synthesize_wake_ack())
            bridge._pipeline.synthesize_notice.assert_called_once_with("Yes sir?")
            self.assertFalse(path.exists())

    def test_legacy_greeting_http_response_is_silent(self):
        bridge = self.make_bridge()
        handler = server.RoomAudioHandler.__new__(server.RoomAudioHandler)
        handler.server = SimpleNamespace(bridge=bridge, token="fixture")
        handler.path = "/greeting"
        handler.headers = {"x-jarvis-room-token": "fixture"}
        handler._send_json = mock.Mock()
        with mock.patch.object(server, "ROOM_GREETING_ENABLED", True):
            handler.do_GET()
        handler._send_json.assert_called_once_with({
            "ok": True, "greetingEnabled": False, "greetingText": "",
            "audioWavBase64": "", "audioContentType": ""})
        bridge._pipeline.synthesize_notice.assert_not_called()

    def test_health_reports_removed_connection_greetings_and_separate_arrivals(self):
        handler = server.RoomAudioHandler.__new__(server.RoomAudioHandler)
        handler.server = SimpleNamespace(bridge=self.make_bridge(), token="fixture")
        handler.path = "/health"
        handler._send_json = mock.Mock()
        for enabled in (False, True):
            with self.subTest(arrivals_enabled=enabled), \
                 mock.patch.object(server, "ROOM_GREETING_ENABLED", enabled):
                handler._send_json.reset_mock()
                handler.do_GET()
                result = handler._send_json.call_args.args[0]
                self.assertFalse(result["greetingSupported"])
                self.assertFalse(result["greetingEnabled"])
                self.assertFalse(result["greetingTextOverride"])
                self.assertTrue(result["arrivalGreetingSupported"])
                self.assertEqual(result["arrivalGreetingEnabled"], enabled)

    def test_room_ack_configuration_is_forwarded_to_pipeline(self):
        with mock.patch.dict(server.os.environ, {"JARVIS_ROOM_AUDIO_SHARED_SESSION": ""}), \
             mock.patch.object(server.pi_rpc, "PiRpcSession"), \
             mock.patch.object(server, "PROCESSING_ACK_ENABLED", False), \
             mock.patch.object(server, "PROCESSING_ACK_TEXT", "Room-specific acknowledgement."):
            bridge = server.RoomAudioBridge()
        self.assertFalse(bridge._pipeline.config.processing_ack_enabled)
        self.assertEqual(bridge._pipeline.config.processing_ack_text,
            "Room-specific acknowledgement.")


class SilentConnectionClientTests(unittest.TestCase):
    def test_legacy_cli_and_environment_opt_ins_are_accepted_but_inert(self):
        with mock.patch.dict(client.os.environ, {
                "JARVIS_ROOM_AUDIO_STARTUP_GREETING": "1",
                "JARVIS_ROOM_AUDIO_GREETING_ON_RECONNECT": "1",
                "JARVIS_ROOM_AUDIO_GREETING_TIMEOUT_SECONDS": "not-used"}):
            for flags in ([], ["--startup-greeting", "--greeting-on-reconnect", "--greeting-timeout", "5"],
                          ["--no-startup-greeting", "--no-greeting-on-reconnect"]):
                with self.subTest(flags=flags):
                    args = client.build_parser().parse_args(flags)
                    self.assertFalse(args.startup_greeting)
                    self.assertFalse(args.greeting_on_reconnect)

    def test_startup_and_capture_recovery_never_request_or_play_a_greeting(self):
        for interrupts in (False, True):
            with self.subTest(interrupts=interrupts):
                args = client.build_parser().parse_args([
                    "--rate", "16000", "--no-local-wake-word", "--bluetooth-mac", "",
                    "--startup-greeting", "--greeting-on-reconnect"])
                # Even a caller carrying old positive namespace values cannot
                # restore the removed branches.
                args.startup_greeting = args.greeting_on_reconnect = True
                args.interrupt_while_busy = interrupts
                controller = mock.Mock()
                controller.is_busy.return_value = False
                controller.reserve_followup.return_value = None
                pcm = b"\0\0" * 320
                with mock.patch.object(client, "create_local_wake_word_detector", return_value=None), \
                     mock.patch.object(client, "RoomAudioTurnController", return_value=controller), \
                     mock.patch.object(client, "start_raw_arecord", return_value=mock.Mock()) as capture, \
                     mock.patch.object(client, "read_exact_fd",
                         side_effect=[pcm, TimeoutError("fixture capture stalled"), pcm, KeyboardInterrupt]), \
                     mock.patch.object(client, "stop_process"), \
                     mock.patch.object(client.time, "sleep"), \
                     mock.patch.object(client.urllib.request, "urlopen") as request, \
                     mock.patch.object(client, "play_response_audio") as playback:
                    with self.assertRaises(KeyboardInterrupt):
                        client.run_vad_loop(args)
                self.assertEqual(capture.call_count, 2)
                request.assert_not_called()
                playback.assert_not_called()
                controller.play_greeting.assert_not_called()

    def test_connection_greeting_playback_helpers_are_removed(self):
        self.assertFalse(hasattr(client, "get_greeting"))
        self.assertFalse(hasattr(client, "play_room_greeting"))
        self.assertFalse(hasattr(client.RoomAudioTurnController, "play_greeting"))


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
