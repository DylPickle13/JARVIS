"""Wake gate regression tests; no audio hardware or openWakeWord required."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pi_room_audio_client as client

from pi_room_audio_client import LocalWakeWordDetector, LocalWakeWordGate, WakeClipEndpoint


def detector(predictions):
    result = LocalWakeWordDetector.__new__(LocalWakeWordDetector)
    result._np = SimpleNamespace(int16=object(), frombuffer=lambda data, dtype: data)
    result._model = Mock()
    result._model.predict.side_effect = predictions
    result._buffer = bytearray()
    result._ratecv_state = None
    result._score_streaks = {}
    result._cooldown_until = 0.0
    result._last_score_log_at = 0.0
    result.last_model = result.max_model = ""
    result.last_score = result.max_score = 0.0
    result.threshold = 0.85
    result.consecutive_frames = 2
    result.cooldown_seconds = 2.0
    result.chunk_bytes = 2560
    result.log_scores = False
    return result


def frame(model, now=10.0, chunks=1):
    return model.process_frame(b"\0" * 2560 * chunks, source_rate=16000, now=now)


class DetectorTests(unittest.TestCase):
    def test_isolated_spikes_do_not_trigger(self):
        model = detector([{"jarvis": v} for v in (0.9, 0.3, 0.99, 0.2)])
        self.assertIsNone(frame(model, chunks=4))

    def test_two_adjacent_predictions_trigger(self):
        model = detector([{"jarvis": 0.85}, {"jarvis": 0.91}])
        self.assertIsNone(frame(model))
        self.assertEqual(frame(model)["model"], "jarvis")
        model._model.reset.assert_called_once()

    def test_different_models_cannot_combine_streaks(self):
        model = detector([{"a": 0.9, "b": 0.1}, {"a": 0.1, "b": 0.9}])
        self.assertIsNone(frame(model, chunks=2))

    def test_empty_prediction_breaks_streak(self):
        model = detector([{"jarvis": 0.9}, {}, {"jarvis": 0.9}])
        self.assertIsNone(frame(model, chunks=3))

    def test_reset_discards_partial_streak_and_audio(self):
        model = detector([{"jarvis": 0.9}] * 2)
        frame(model)
        model._buffer.extend(b"\0")
        model.reset_stream()
        self.assertEqual(model._buffer, b"")
        self.assertIsNone(frame(model))

    def test_cooldown_predictions_cannot_prime_next_wake(self):
        model = detector([{"jarvis": 0.9}] * 5)
        self.assertIsNotNone(frame(model, chunks=2))
        self.assertIsNone(frame(model, now=11))
        self.assertIsNone(frame(model, now=12.1))
        self.assertIsNotNone(frame(model, now=12.2))


class WakeClipEndpointTests(unittest.TestCase):
    def test_continuous_noise_cannot_extend_confirmed_wake(self):
        endpoint = WakeClipEndpoint()
        for now in (10, 10.1, 10.2, 10.29):
            self.assertFalse(endpoint.reached(now, confirmed=True, followup=False, busy=False))
        self.assertTrue(endpoint.reached(10.31, confirmed=True, followup=False, busy=False))
        self.assertEqual(endpoint.deadline, 10.3)

    def test_unconfirmed_audio_commands_and_interrupts_keep_normal_vad(self):
        for confirmed, followup, busy in ((False, False, False), (True, True, False),
                                           (True, False, True)):
            endpoint = WakeClipEndpoint()
            for now in (10, 11, 40):
                self.assertFalse(endpoint.reached(now, confirmed=confirmed, followup=followup, busy=busy))
            self.assertIsNone(endpoint.deadline)

    def test_vad_loop_submits_confirmed_wake_without_any_silence(self):
        args = client.build_parser().parse_args([
            '--local-wake-word', '--interrupt-while-busy', '--no-startup-greeting',
            '--rate', '16000', '--vad-frame-ms', '20',
        ])
        clock = [100.0]
        count = [0]
        def read_frame(*unused, **kwargs):
            count[0] += 1
            if count[0] > 100:
                raise AssertionError('wake waited beyond two seconds')
            clock[0] = 100 + count[0] * .02
            return b'\xe8\x03' * 320  # Continuous RMS=1000, never silence.
        model = SimpleNamespace(reset_stream=Mock(), last_score=.9, last_model='jarvis')
        model.process_frame = lambda *a, **kw: {'score': .9, 'model': 'jarvis'} if count[0] == 20 else None
        controller = Mock()
        controller.is_busy.return_value = False
        controller.reserve_followup.return_value = None
        controller.start_turn.side_effect = KeyboardInterrupt
        with patch.object(client, 'create_local_wake_word_detector', return_value=model), \
                patch.object(client, 'RoomAudioTurnController', return_value=controller), \
                patch.object(client, 'start_raw_arecord', return_value=Mock()), \
                patch.object(client, 'read_exact_fd', side_effect=read_frame), \
                patch.object(client.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(client, 'stop_process'), \
                patch.object(client.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                client.run_vad_loop(args)
        controller.start_turn.assert_called_once()
        duration = controller.start_turn.call_args.kwargs['duration_seconds']
        self.assertGreaterEqual(duration, .68)
        self.assertLess(duration, .8)
        self.assertIsNone(controller.start_turn.call_args.kwargs['followup'])

    def test_ineligible_audio_clears_old_deadline(self):
        endpoint = WakeClipEndpoint()
        endpoint.reached(10, confirmed=True, followup=False, busy=False)
        endpoint.reached(11, confirmed=True, followup=True, busy=False)
        self.assertFalse(endpoint.reached(20, confirmed=True, followup=False, busy=False))
        self.assertEqual(endpoint.deadline, 20.3)


class GateTests(unittest.TestCase):
    def test_expiry_and_single_use(self):
        model = Mock()
        model.process_frame.return_value = {"score": 0.9}
        gate = LocalWakeWordGate(model, 3.0)
        self.assertFalse(gate.accepts(0))
        gate.process_frame(b"pcm", source_rate=16000, now=10, busy=False)
        self.assertTrue(gate.accepts(12.9))
        self.assertFalse(gate.accepts(13.1))
        gate.consume()
        self.assertFalse(gate.accepts(12.9))

    def test_busy_suppresses_inference_clears_arm_and_resets_on_both_edges(self):
        model = Mock()
        model.process_frame.return_value = {"score": 0.99}
        gate = LocalWakeWordGate(model, 3.0)
        gate.process_frame(b"pcm", source_rate=16000, now=10, busy=False)
        for now in (11, 12):
            self.assertIsNone(gate.process_frame(b"playback", source_rate=16000, now=now, busy=True))
            self.assertFalse(gate.accepts(now))
        self.assertEqual(model.process_frame.call_count, 1)
        model.reset_stream.assert_called_once()
        model.process_frame.return_value = None
        gate.process_frame(b"idle", source_rate=16000, now=12.5, busy=False)
        self.assertFalse(gate.accepts(12.5))
        self.assertEqual(model.reset_stream.call_count, 2)


if __name__ == "__main__":
    unittest.main()
