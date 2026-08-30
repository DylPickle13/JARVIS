# Operation JARVIS Voice Pipeline

Transport-neutral Mac-side speech pipeline used by the Raspberry Pi room-audio endpoint and Watch final-response synthesis.

## Files

- `voice_pipeline.py` — oMLX Whisper ASR, optional direct oMLX chat, injected Pi RPC response callback, text normalization, bounded streaming/chunking, and local Piper synthesis.
- `voice_commands.py` — exact busy-only `stop` control policy.
- `APPEND_SYSTEM.md` — concise spoken-response guidance used by room-audio Pi RPC sessions.
- `test_voice_pipeline.py` — text/chunking/wake-normalization/control regression tests.
- `test_pi_rpc.py` — neutral root Pi RPC regression tests.

The persistent Pi RPC implementation lives at repository root in [`../../../pi_rpc.py`](../../../pi_rpc.py). The active room bridge lives in [`../raspberry-pi/room_audio/room_audio_server.py`](../raspberry-pi/room_audio/room_audio_server.py).

## Pipeline

```text
Raspberry Pi wake-accepted WAV
  → oMLX Whisper ASR
  → neutral persistent Pi RPC session
  → concise final text
  → local Piper JARVIS voice
  → bounded WAV response
```

During an active turn, the Pi client may submit a short candidate through Whisper. Only the exact normalized word `stop` cancels generation/playback; idle speech and longer phrases do not invoke cancellation.

## Configuration

The canonical variables use the `JARVIS_VOICE_*` prefix:

- `JARVIS_VOICE_BASE_URL`, `JARVIS_VOICE_API_KEY`
- `JARVIS_VOICE_ASR_MODEL`, `JARVIS_VOICE_ASR_LANGUAGE`
- `JARVIS_VOICE_LLM_MODEL`, `JARVIS_VOICE_LLM_MAX_TOKENS`, `JARVIS_VOICE_LLM_TEMPERATURE`, `JARVIS_VOICE_LLM_TOP_P`
- `JARVIS_VOICE_TTS_BACKEND=piper`
- `JARVIS_VOICE_TTS_PIPER_REPO_ID`, `JARVIS_VOICE_TTS_PIPER_QUALITY`
- `JARVIS_VOICE_TTS_PIPER_LENGTH_SCALE`, `JARVIS_VOICE_TTS_PIPER_VOLUME`, `JARVIS_VOICE_TTS_PIPER_NOISE_SCALE`, `JARVIS_VOICE_TTS_PIPER_NOISE_W_SCALE`
- `JARVIS_VOICE_TTS_SPEED`, `JARVIS_VOICE_TTS_MAX_CHARS_PER_SEGMENT`, `JARVIS_VOICE_TTS_MAX_SEGMENTS`
- `JARVIS_VOICE_TTS_STRIP_URLS`, `JARVIS_VOICE_TTS_STRIP_CODE`, `JARVIS_VOICE_TTS_STRIP_MARKDOWN`, `JARVIS_VOICE_TTS_STRIP_CHAT_MARKUP`
- `JARVIS_VOICE_ASR_TIMEOUT_SECONDS`, `JARVIS_VOICE_LLM_TIMEOUT_SECONDS`, `JARVIS_VOICE_TTS_TIMEOUT_SECONDS`, `JARVIS_VOICE_MODEL_LOAD_TIMEOUT_SECONDS`
- `JARVIS_VOICE_REQUEST_RETRIES`, `JARVIS_VOICE_REQUEST_RETRY_BACKOFF_SECONDS`, `JARVIS_VOICE_TTS_MAX_BYTES`
- `JARVIS_VOICE_WAKE_WORD`, `JARVIS_VOICE_GREETING_COOLDOWN_MINUTES`, `JARVIS_VOICE_GREETING_INCLUDE_STATUS`

Room-specific overrides use `JARVIS_ROOM_AUDIO_*`; see the [room-audio README](../raspberry-pi/room_audio/README.md).

## Tests

From the repository root:

```bash
export PYTHONPATH="$PWD:$PWD/projects/operation-jarvis/voice"
.venv/bin/python projects/operation-jarvis/voice/test_pi_rpc.py
.venv/bin/python projects/operation-jarvis/voice/test_voice_pipeline.py
.venv/bin/python projects/operation-jarvis/raspberry-pi/room_audio/test_room_audio_interrupt.py
```

These tests do not start the room service, call oMLX, synthesize speech, or touch hardware.
