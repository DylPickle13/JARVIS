"""Bank integration; sessions, inference, HTTP and household playback are mocked."""
import base64
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import room_audio_server as server
from room_audio_followup import WakeFollowups
from phrase_banks import Bundle, RoomBanks, Selector, wav_info
from test_phrase_banks import fixture_bundle


class RoomBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        pin, _ = fixture_bundle(root / 'assets')
        self.bundle = Bundle(root / 'assets', pin)
        self.selector = Selector(root / 'state' / 'selection.sqlite3')
        self.bridge = server.RoomAudioBridge.__new__(server.RoomAudioBridge)
        self.bridge._phrase_banks = RoomBanks(self.bundle, self.selector)
        self.bridge._pipeline = mock.Mock()
        self.bridge._model, self.bridge._thinking = 'fixture', 'off'
        self.bridge._followups = WakeFollowups()
        self.bridge._wake_verifier = mock.Mock()
        self.bridge._wake_verifier.transcribe.return_value = 'hey jarvis'
        self.bridge.control = server.RoomAudioControl()
        self.bridge._jobs_lock = threading.Lock()
        self.bridge._jobs = {}
        self.input = root / 'input.wav'
        self.input.write_bytes(self.bundle.default('wake').audio)
        self.bridge._pipeline.transcribe_audio.return_value = ('fixture', 0.1, 0.01)

    def authorize(self, turn='fixture-turn-0001'):
        return self.bridge._authorize_room_turn(self.input, started=time.monotonic(),
            client_key='fixture-client', wake_ticket='', requested_turn_id=turn, followup_supported=True)

    def test_wake_text_and_audio_are_selected_together_after_verification(self):
        result = self.authorize()
        self.assertTrue(result['accepted'])
        clips = [clip for clip in self.bundle.clips.values() if clip.text == result['ackText']]
        self.assertEqual(len(clips), 1)
        self.assertEqual(result['audioWavBase64'], self.bridge._phrase_banks.audio[clips[0].id])
        self.bridge._pipeline.synthesize_notice.assert_not_called()

    def test_rejected_duplicate_and_cancelled_wake_do_not_consume(self):
        with mock.patch.object(self.selector, 'reserve', wraps=self.selector.reserve) as reserve:
            self.bridge._wake_verifier.transcribe.return_value = 'not the wake phrase'
            self.authorize()
            reserve.assert_not_called()
            self.bridge._wake_verifier.transcribe.return_value = 'hey jarvis'
            self.authorize()
            self.assertFalse(self.authorize()['accepted'])
            self.assertEqual(reserve.call_count, 1)
            with mock.patch.object(self.bridge.control, 'is_cancelled', return_value=True):
                self.assertFalse(self.authorize('fixture-turn-0002')['accepted'])
            self.assertEqual(reserve.call_count, 1)

    def test_disabled_blank_and_custom_processing_configuration(self):
        for enabled, text in [(False, server.voice_lines.PROCESSING_ACK), (True, '   ')]:
            with mock.patch.object(server, 'PROCESSING_ACK_ENABLED', enabled), \
                 mock.patch.object(server, 'PROCESSING_ACK_TEXT', text), \
                 mock.patch.object(self.selector, 'reserve') as reserve:
                self.assertEqual(self.bridge._announcement('processing', 'disabled'), ('', ''))
                self.assertIsNone(self.bridge._processing_ack_path('disabled'))
                reserve.assert_not_called()
        with mock.patch.object(server, 'PROCESSING_ACK_TEXT', 'Custom.'), \
             mock.patch.object(self.bridge, '_synthesize_processing_ack', return_value='custom-audio'):
            self.assertEqual(self.bridge._announcement('processing', 'custom'), ('Custom.', 'custom-audio'))
        self.assertTrue(self.bridge.phrase_bank_status()['enabled'])

    def test_warmup_and_health_do_not_consume_or_synthesize(self):
        with mock.patch.object(self.selector, 'reserve') as reserve:
            self.bridge.warm_processing_ack()
            self.bridge.phrase_bank_status()
        reserve.assert_not_called()
        self.bridge._pipeline.synthesize_notice.assert_not_called()

    def test_arrival_disabled_connection_and_duplicate_are_silent(self):
        self.assertFalse(self.bridge.synthesize_greeting()['greetingEnabled'])
        with mock.patch.object(server, 'ROOM_GREETING_ENABLED', False):
            self.assertFalse(self.bridge.synthesize_greeting(arrival=True, request_key='arrival-1')['greetingEnabled'])
        first = self.bridge.synthesize_greeting(arrival=True, request_key='arrival-1')
        self.assertTrue(first['greetingEnabled'])
        second = self.bridge.synthesize_greeting(arrival=True, request_key='arrival-1')
        self.assertFalse(second['greetingEnabled'])
        self.assertEqual(second['audioWavBase64'], '')
        self.bridge._pipeline.synthesize_notice.assert_not_called()

    def test_arrival_requires_deduplication_id_when_enabled(self):
        with self.assertRaises(ValueError): self.bridge.synthesize_greeting(arrival=True)

    def test_processing_copy_is_raw_unpadded_and_master_survives(self):
        path = self.bridge._processing_ack_path('steering-fixture')
        self.assertAlmostEqual(wav_info(path.read_bytes())['seconds'], 0.1)
        path.unlink()
        self.assertEqual(len(list(self.bundle.root.glob('*.wav'))), 84)
        self.assertIsNone(self.bridge._processing_ack_path('steering-fixture'))
        self.bridge._pipeline.synthesize_notice.assert_not_called()

    def test_duplicate_async_job_does_not_select_ack(self):
        self.bridge._jobs['duplicate-turn'] = {'createdMonotonic': time.monotonic()}
        with mock.patch.object(self.bridge, '_authorize_room_turn', return_value=None), \
             mock.patch.object(self.selector, 'reserve') as reserve:
            with self.assertRaises(ValueError):
                self.bridge.handle_wav_async_ack(self.input, requested_turn_id='duplicate-turn')
        reserve.assert_not_called()

    def test_cancelled_async_request_does_not_select_ack(self):
        with mock.patch.object(self.bridge, '_authorize_room_turn', return_value=None), \
             mock.patch.object(self.bridge.control, 'is_cancelled', return_value=True), \
             mock.patch.object(server.threading, 'Thread') as worker, \
             mock.patch.object(self.selector, 'reserve') as reserve:
            result = self.bridge.handle_wav_async_ack(self.input, requested_turn_id='cancelled-turn')
        reserve.assert_not_called()
        self.assertEqual(result['ackText'], '')
        self.assertEqual(result['audioWavBase64'], '')
        # Thread was mocked: manually remove the owned job copy.
        worker.call_args.kwargs['args'][1].unlink()

    def test_async_text_matches_recording_without_live_synthesis(self):
        with mock.patch.object(self.bridge, '_authorize_room_turn', return_value=None), \
             mock.patch.object(server.threading, 'Thread') as worker:
            result = self.bridge.handle_wav_async_ack(self.input, requested_turn_id='normal-turn')
        clip = next(clip for clip in self.bundle.clips.values() if clip.text == result['ackText'])
        self.assertEqual(result['audioWavBase64'], self.bridge._phrase_banks.audio[clip.id])
        self.bridge._pipeline.synthesize_notice.assert_not_called()
        worker.call_args.kwargs['args'][1].unlink()

    def test_sync_ack_is_cached_and_cleaned_with_final_answer(self):
        final = self.bundle.default('processing').temporary()
        self.bridge._pipeline.synthesize_turn.return_value = SimpleNamespace(audio_paths=[final],
            reply_text='Final.', input_seconds=0, asr_seconds=0, llm_seconds=0, tts_seconds=0, total_seconds=0)
        result = self.bridge._synthesize_accepted_turn(self.input, transcript='fixture', input_seconds=0,
            asr_seconds=0, started_at=time.monotonic(), include_ack=True, turn_id='sync-fixture')
        self.assertTrue(result['ok'])
        self.assertFalse(final.exists())
        self.assertAlmostEqual(wav_info(base64.b64decode(result['audioWavBase64']))['seconds'],
                               0.2 + server.DEFAULT_TTS_LEADING_SILENCE_MS / 1000)
        self.bridge._pipeline.synthesize_notice.assert_not_called()


if __name__ == '__main__':
    unittest.main()
