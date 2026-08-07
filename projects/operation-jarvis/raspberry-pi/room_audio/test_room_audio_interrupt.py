#!/usr/bin/env python3
from __future__ import annotations

import threading
import time
import unittest

import room_audio_server


class _FakeSession:
    def __init__(self) -> None:
        self.abort_calls = 0

    def abort_active(self) -> bool:
        self.abort_calls += 1
        return True


class InterruptCommandTests(unittest.TestCase):
    def test_accepts_only_exact_stop(self) -> None:
        for transcript in ("stop", "Stop.", " STOP! "):
            with self.subTest(transcript=transcript):
                self.assertEqual(room_audio_server.parse_interrupt_command(transcript), "stop")

    def test_rejects_longer_or_negated_phrases(self) -> None:
        for transcript in ("don't stop", "do not stop", "bus stop", "stopwatch", "stop stop", ""):
            with self.subTest(transcript=transcript):
                self.assertEqual(room_audio_server.parse_interrupt_command(transcript), "")


class TurnCancellationTests(unittest.TestCase):
    def make_bridge(self, *, active: bool) -> tuple[room_audio_server.RoomAudioBridge, threading.Event, _FakeSession]:
        bridge = room_audio_server.RoomAudioBridge.__new__(room_audio_server.RoomAudioBridge)
        cancel_event = threading.Event()
        turn_id = "12345678"
        bridge._jobs_lock = threading.Lock()
        bridge._jobs = {
            turn_id: {
                "status": "running",
                "pending": True,
                "transcript": "Jarvis, explain something",
                "normalizedTranscript": "Jarvis, explain something",
                "createdMonotonic": time.monotonic(),
                "startedMonotonic": time.monotonic(),
                "cancelEvent": cancel_event,
            }
        }
        bridge._active_pi_turn_lock = threading.Lock()
        bridge._active_pi_turn_id = turn_id if active else ""
        session = _FakeSession()
        bridge._session = session
        return bridge, cancel_event, session

    def test_cancel_marks_job_and_aborts_active_generation(self) -> None:
        bridge, cancel_event, session = self.make_bridge(active=True)
        result = bridge.cancel_turn("12345678")
        self.assertIsNotNone(result)
        self.assertTrue(cancel_event.is_set())
        self.assertEqual(bridge._jobs["12345678"]["status"], "cancelled")
        self.assertFalse(bridge._jobs["12345678"]["pending"])
        self.assertEqual(bridge._jobs["12345678"]["response"]["audioWavBase64"], "")
        self.assertTrue(result["abortSent"])
        self.assertGreaterEqual(session.abort_calls, 1)

    def test_cancel_completed_or_tts_turn_does_not_abort_other_generation(self) -> None:
        bridge, cancel_event, session = self.make_bridge(active=False)
        result = bridge.cancel_turn("12345678")
        self.assertIsNotNone(result)
        self.assertTrue(cancel_event.is_set())
        self.assertFalse(result["generationWasActive"])
        self.assertEqual(session.abort_calls, 0)

    def test_unknown_turn_is_not_cancelled(self) -> None:
        bridge, _, session = self.make_bridge(active=False)
        self.assertIsNone(bridge.cancel_turn("missing00"))
        self.assertEqual(session.abort_calls, 0)


if __name__ == "__main__":
    unittest.main()
