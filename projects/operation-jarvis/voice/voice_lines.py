"""Canonical room-voice defaults; no configuration, inference, or playback.

Environment overrides remain the callers' responsibility. The protected
outdoor-doorbell farewell deliberately stays in departure-greeting/runtime.py,
where playback validates its fixed phrase and pre-rendered WAV/hash metadata.
"""

WAKE_ACK = "Yes sir?"
PROCESSING_ACK = "Generating your response, sir."
FALLBACK_GREETING = "JARVIS online. At your service, sir."
ARRIVAL_GREETING = "Welcome back, sir"
MAC_STARTUP_GREETING = "The Mac room speaker is online, sir."
REQUEST_FAILURE = "I couldn't complete that request, sir."
RENDER_FAILURE = "Your response is ready, sir, but I couldn't speak it."

QUICK_RETURN_GREETINGS = (
    "Back already, sir?",
    "Returned so soon, sir?",
    "Welcome back, sir. That was quick.",
)
MORNING_GREETINGS = ("Good morning, sir.", "Morning, sir.")
AFTERNOON_GREETINGS = ("Good afternoon, sir.", "Afternoon, sir.")
EVENING_GREETINGS = ("Good evening, sir.", "Evening, sir.")
LATE_NIGHT_GREETINGS = ("You're up late, sir.", "Late night, sir.")
GREETING_STATUS_SUFFIXES = (
    "JARVIS online.",
    "Systems are online.",
    "Voice link established.",
    "At your service.",
)
QUICK_RETURN_EXTRA_SUFFIX = "I'll pretend not to judge."
