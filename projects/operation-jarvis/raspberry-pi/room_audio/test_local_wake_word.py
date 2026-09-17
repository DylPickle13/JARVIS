"""Wake gate regression tests; no audio hardware or openWakeWord required."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pi_room_audio_client import LocalWakeWordDetector, LocalWakeWordGate


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
