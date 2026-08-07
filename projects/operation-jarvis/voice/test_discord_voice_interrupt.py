from __future__ import annotations

import array
import math
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

VOICE_DIR = Path(__file__).resolve().parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

import discord_voice
import voice_commands


class _FakePipeline:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.cancel_calls = 0

    def transcribe_audio(self, _path: Path) -> tuple[str, float, float]:
        return self.transcript, 1.0, 0.01

    def cancel_active_response(self) -> bool:
        self.cancel_calls += 1
        return False


class _FakeManager:
    def __init__(self, transcript: str) -> None:
        self.pipeline = _FakePipeline(transcript)
        self.cancel_calls = 0
        self.cancel_callback = self.cancel
        self.steering_callback = None

    def cancel(self, _turn_context: object | None) -> bool:
        self.cancel_calls += 1
        return True


class _FakeVoiceClient:
    def __init__(self) -> None:
        self.playing = True
        self.stop_calls = 0

    def is_playing(self) -> bool:
        return self.playing

    def is_paused(self) -> bool:
        return False

    def stop(self) -> None:
        self.stop_calls += 1
        self.playing = False


def _test_pcm(seconds: float = 0.6) -> bytes:
    frames = int(discord_voice.DISCORD_PCM_SAMPLE_RATE * seconds)
    samples = array.array("h")
    for index in range(frames):
        value = int(4_000 * math.sin(2 * math.pi * 220 * index / discord_voice.DISCORD_PCM_SAMPLE_RATE))
        samples.extend((value, value))
    return samples.tobytes()


def _make_conversation(transcript: str) -> tuple[discord_voice._JarvisVoiceConversation, _FakeManager, _FakeVoiceClient]:
    conversation = discord_voice._JarvisVoiceConversation.__new__(discord_voice._JarvisVoiceConversation)
    manager = _FakeManager(transcript)
    voice_client = _FakeVoiceClient()
    conversation.manager = manager
    conversation.voice_client = voice_client
    conversation._stopped = False
    conversation._interrupt_requested = False
    conversation._interrupt_in_progress = False
    conversation._processing_utterance = True
    conversation._active_pipeline_task = None
    conversation._active_turn_context = object()
    conversation._steering_tts_generation = 0
    conversation._steering_tts_resume_at = 0.0
    conversation._queued_turn_cutover_generation = 0
    conversation._warmup_task = None
    conversation._send_status_message = AsyncMock()
    conversation._send_voice_diagnostic = AsyncMock()
    return conversation, manager, voice_client


def _make_utterance() -> discord_voice._VoiceUtterance:
    now = time.monotonic()
    return discord_voice._VoiceUtterance(
        member="test member",  # type: ignore[arg-type]
        pcm=_test_pcm(),
        duration_seconds=0.6,
        voiced_ms=600.0,
        max_rms=4_000,
        stats=discord_voice._VoiceBufferStats(),
        queued_at=now,
        last_packet_at=now,
        last_voice_at=now,
        busy_interrupt_candidate=True,
    )


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


class BusyStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_stop_cancels_generation_and_playback_silently(self) -> None:
        conversation, manager, voice_client = _make_conversation("Stop!")

        await conversation._handle_interrupt_candidate(_make_utterance())

        self.assertTrue(conversation._interrupt_requested)
        self.assertEqual(manager.cancel_calls, 1)
        self.assertEqual(manager.pipeline.cancel_calls, 1)
        self.assertEqual(voice_client.stop_calls, 1)
        conversation._send_status_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
