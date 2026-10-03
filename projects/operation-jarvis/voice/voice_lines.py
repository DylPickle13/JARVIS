"""Canonical room-voice defaults; no configuration, inference, or playback.

Environment overrides remain the callers' responsibility. The protected
outdoor-doorbell farewell deliberately stays in departure-greeting/runtime.py,
where playback validates its fixed phrase and pre-rendered WAV/hash metadata.
"""

WAKE_ACK = "Yes sir?"
PROCESSING_ACK = "Generating your response, sir."
ARRIVAL_GREETING = "Welcome back, sir"
# Failure notices intentionally stay fixed; do not include them in variation banks.
REQUEST_FAILURE = "I couldn't complete that request, sir."
RENDER_FAILURE = "Your response is ready, sir, but I couldn't speak it."
