"""Shared deterministic control policy for every Operation JARVIS voice adapter.

Audio capture, VAD, and playback remain transport-specific to the Raspberry Pi
room endpoint. The adapter sends busy-only candidates through Apple Dictation,
then uses this module for the final control decision.
"""

from __future__ import annotations

import re

STOP_COMMAND = "stop"


def normalize_voice_control_transcript(transcript: str) -> str:
    """Normalize an ASR transcript for exact control-command matching."""
    return re.sub(r"[^a-z]+", " ", (transcript or "").casefold()).strip()


def parse_voice_interrupt_command(transcript: str, *, busy: bool) -> str:
    """Return an exact voice control command, only while its adapter is busy."""
    if not busy:
        return ""
    normalized = normalize_voice_control_transcript(transcript)
    return STOP_COMMAND if normalized == STOP_COMMAND else ""
