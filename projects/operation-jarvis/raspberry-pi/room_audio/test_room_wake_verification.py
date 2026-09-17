"""Independent Mac wake verification must precede every ordinary turn side effect."""
import base64
import io
import wave
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import room_audio_server as server


class WakePhraseTests(unittest.TestCase):
    def test_exact_leading_phrase_with_case_and_punctuation(self):
        for text in ("Hey Jarvis", "HEY, JARVIS! Turn on the light.", '“Hey Jarvis,” what time is it?'):
            with self.subTest(text=text):
                self.assertTrue(server.has_verified_wake_phrase(text))

    def test_no_aliases_substrings_or_mid_sentence_mentions(self):
        for text in ("", "Jarvis", "Hey Travis turn on the light", "Hey Jarvison",
                     "They said hey Jarvis", "Don't say hey Jarvis", "Hey, how are you?",
                     "hey jarvis2", "hey järvis", "heyjarvis", "hey charvis"):
            with self.subTest(text=text):
                self.assertFalse(server.has_verified_wake_phrase(text))


class WakeVerificationTests(unittest.TestCase):
    def make_bridge(self, transcript):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._wake_verifier = Mock()
        bridge._wake_verifier.transcribe.return_value = transcript
        bridge._pipeline = Mock()
        bridge._pipeline.transcribe_audio.return_value = ("What time is it", 3.0, 0.1)
        bridge._followups = server.WakeFollowups()
        bridge._synthesize_wake_ack = Mock(return_value="yes-sir-audio")
        bridge._synthesize_processing_ack = Mock(return_value="ack")
        bridge._synthesize_accepted_turn = Mock(return_value={"accepted": True})
        bridge._jobs_lock = threading.Lock()
        bridge._jobs = {}
        bridge._prune_jobs_locked = Mock()
        bridge._model = "test"
        bridge._thinking = "off"
        return bridge

    def test_rejection_is_silent_and_cannot_be_bypassed_by_client_flag(self):
        for method in ("handle_wav", "handle_wav_async_ack"):
            for require in (True, False):
                with self.subTest(method=method, require=require):
                    bridge = self.make_bridge("Turn the television up")
                    result = getattr(bridge, method)(Path("unused.wav"), require_wake_word=require)
                    self.assertTrue(result["ok"])
                    self.assertFalse(result["accepted"])
                    self.assertFalse(result["pending"])
                    self.assertEqual(result["audioWavBase64"], "")
                    self.assertEqual(result["reason"], "wake_phrase_not_verified")
                    self.assertNotIn("transcript", result)
                    bridge._pipeline.transcribe_audio.assert_not_called()
                    bridge._synthesize_processing_ack.assert_not_called()
                    bridge._synthesize_accepted_turn.assert_not_called()
                    self.assertEqual(bridge._jobs, {})

    def test_verifier_failure_fails_closed(self):
        for method in ("handle_wav", "handle_wav_async_ack"):
            bridge = self.make_bridge("")
            bridge._wake_verifier.transcribe.side_effect = RuntimeError("helper unavailable")
            result = getattr(bridge, method)(Path("unused.wav"))
            self.assertEqual(result["reason"], "wake_verification_unavailable")
            bridge._pipeline.transcribe_audio.assert_not_called()
            bridge._synthesize_processing_ack.assert_not_called()
            bridge._synthesize_accepted_turn.assert_not_called()

    def claimed_ticket(self, bridge):
        ticket = bridge._followups.issue("peer/client", "wake-turn-123")
        self.assertTrue(bridge._followups.transition(ticket, "peer/client", "ready"))
        self.assertTrue(bridge._followups.transition(ticket, "peer/client", "claim"))
        return ticket

    def test_wake_never_executes_command_even_with_extra_words(self):
        for method in ("handle_wav", "handle_wav_async_ack"):
            for text in ("Hey Jarvis", "Hey Jarvis turn on the light"):
                bridge = self.make_bridge(text)
                result = getattr(bridge, method)(Path("unused.wav"), client_key="peer/client",
                    requested_turn_id="wake-turn-123", followup_supported=True)
                self.assertEqual(result["status"], "awaiting_command")
                self.assertEqual(result["ackText"], "Yes sir?")
                self.assertFalse(result["pending"])
                self.assertTrue(result["wakeTicket"])
                bridge._pipeline.transcribe_audio.assert_not_called()
                bridge._synthesize_processing_ack.assert_not_called()
                bridge._synthesize_accepted_turn.assert_not_called()
                self.assertEqual(bridge._jobs, {})

    def test_legacy_client_cannot_execute_one_shot(self):
        bridge = self.make_bridge("Hey Jarvis turn on the light")
        result = bridge.handle_wav(Path("unused.wav"), require_wake_word=False)
        self.assertEqual(result["reason"], "two_part_client_required")
        bridge._pipeline.transcribe_audio.assert_not_called()

    def test_authorized_sync_command_skips_wake_asr_and_consumes_ticket(self):
        bridge = self.make_bridge("unused")
        ticket = self.claimed_ticket(bridge)
        result = bridge.handle_wav(Path("unused.wav"), client_key="peer/client", wake_ticket=ticket)
        self.assertTrue(result["accepted"])
        bridge._wake_verifier.transcribe.assert_not_called()
        bridge._pipeline.transcribe_audio.assert_called_once()
        bridge._synthesize_accepted_turn.assert_called_once()
        replay = bridge.handle_wav(Path("unused.wav"), client_key="peer/client", wake_ticket=ticket)
        self.assertEqual(replay["reason"], "invalid_wake_authorization")
        bridge._pipeline.transcribe_audio.assert_called_once()

    def test_authorized_async_command_asr_precedes_processing_ack_and_job(self):
        bridge = self.make_bridge("unused")
        ticket = self.claimed_ticket(bridge)
        calls = Mock()
        calls.attach_mock(bridge._pipeline.transcribe_audio, "transcribe")
        calls.attach_mock(bridge._synthesize_processing_ack, "ack")
        with tempfile.TemporaryDirectory() as directory, patch.object(server.threading, "Thread") as thread:
            wav = Path(directory) / "input.wav"
            wav.write_bytes(b"test")
            with patch.object(server, "PROCESSING_ACK_ENABLED", True), patch.object(server, "PROCESSING_ACK_TEXT", "Generating your response, sir."):
                result = bridge.handle_wav_async_ack(wav, client_key="peer/client", wake_ticket=ticket)
            self.assertTrue(result["accepted"])
            self.assertTrue(result["pending"])
            self.assertEqual(result["ackText"], "Generating your response, sir.")
            self.assertEqual([c[0] for c in calls.mock_calls], ["transcribe", "ack"])
            bridge._wake_verifier.transcribe.assert_not_called()
            thread.return_value.start.assert_called_once()
            thread.call_args.kwargs["args"][1].unlink()

    def test_unclaimed_or_wrong_client_ticket_does_not_run_asr(self):
        bridge = self.make_bridge("unused")
        ticket = bridge._followups.issue("peer/client", "wake-turn-123")
        for client in ("peer/client", "peer/other", "other-peer/client"):
            response = bridge.handle_wav(Path("unused.wav"), client_key=client, wake_ticket=ticket)
            self.assertEqual(response["reason"], "invalid_wake_authorization")
        bridge._pipeline.transcribe_audio.assert_not_called()
        bridge._wake_verifier.transcribe.assert_not_called()

    def test_nevermind_followup_cancels_without_ack_or_generation(self):
        for method in ("handle_wav", "handle_wav_async_ack"):
            for text in ("Never mind.", "Nevermind", "NEVER MIND!", " never   mind "):
                with self.subTest(method=method, text=text):
                    bridge = self.make_bridge("unused")
                    ticket = self.claimed_ticket(bridge)
                    bridge._pipeline.transcribe_audio.return_value = (text, .5, .1)
                    result = getattr(bridge, method)(Path("unused.wav"), client_key="peer/client", wake_ticket=ticket)
                    self.assertEqual(result["status"], "cancelled")
                    self.assertFalse(result["pending"])
                    self.assertEqual(result["audioWavBase64"], "")
                    self.assertEqual(result["ackText"], "")
                    bridge._synthesize_processing_ack.assert_not_called()
                    bridge._synthesize_accepted_turn.assert_not_called()
                    self.assertFalse(bridge._followups.consume(ticket, "peer/client"))
                    self.assertEqual(bridge._jobs, {})

    def test_only_exact_nevermind_is_followup_cancellation(self):
        for text in ("stop", "cancel", "cancel my timer", "never mind the weather, turn on the light",
                     "don't say never mind", "never mind please", "neverminder", "never mind2", ""):
            with self.subTest(text=text):
                self.assertFalse(server.is_followup_cancellation(text))
        for text in ("stop", "cancel", "never mind the weather, turn on the light"):
            bridge = self.make_bridge("unused")
            ticket = self.claimed_ticket(bridge)
            bridge._pipeline.transcribe_audio.return_value = (text, .5, .1)
            result = bridge.handle_wav(Path("unused.wav"), client_key="peer/client", wake_ticket=ticket)
            self.assertTrue(result["accepted"])
            bridge._synthesize_accepted_turn.assert_called_once()

    def test_stop_during_yes_sir_revokes_pending_authorization(self):
        bridge = self.make_bridge("unused")
        ticket = bridge._followups.issue("peer/client", "wake-turn-123")
        bridge._pipeline.transcribe_audio.return_value = ("stop", .5, .1)
        result = bridge.handle_interrupt_wav("wake-turn-123", Path("unused.wav"), client_busy=True)
        self.assertTrue(result["recognized"])
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(bridge._followups.transition(ticket, "peer/client", "ready"))

    def test_wake_ack_padding_preserves_first_sample_and_is_cached(self):
        bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        bridge._ack_lock = threading.Lock()
        bridge._wake_ack_audio_b64 = None
        bridge._pipeline = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yes.wav"
            pcm = b"\xe8\x03" * 1600
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(pcm)
            bridge._pipeline.synthesize_notice.return_value = path
            with patch.object(server, "WAKE_ACK_LEADING_SILENCE_MS", 450):
                audio = bridge._synthesize_wake_ack()
                self.assertEqual(bridge._synthesize_wake_ack(), audio)
            with wave.open(io.BytesIO(base64.b64decode(audio)), "rb") as wav:
                self.assertEqual(wav.getnframes(), 7200 + 1600)
                self.assertEqual(wav.readframes(7200), b"\0" * 14400)
                self.assertEqual(wav.readframes(1600), pcm)
            bridge._pipeline.synthesize_notice.assert_called_once_with("Yes sir?")
            self.assertFalse(path.exists())

    def test_verifier_configuration_has_no_hints_or_network_fallback(self):
        with patch.object(server.pi_rpc, "PiRpcSession"), patch.object(server.voice_pipeline, "VoicePipeline"):
            bridge = server.RoomAudioBridge()
        self.assertEqual(bridge._wake_verifier.name, "apple-dictation")
        self.assertEqual(bridge._wake_verifier.settings.contextual_strings, ())


if __name__ == "__main__":
    unittest.main()
