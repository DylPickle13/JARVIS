# Operation JARVIS Voice Pipeline

Transport-neutral Mac-side speech pipeline used by the Raspberry Pi room-audio endpoint and Watch final-response synthesis.

## Files

- `voice_pipeline.py` — pluggable ASR routing/fallback, optional direct oMLX chat, injected Pi RPC responses, transcript normalization, and bounded Piper synthesis.
- `asr_backends.py` — strict Apple Speech helper adapter plus the in-process oMLX callback adapter.
- `apple_asr/` — compiled Swift command-line helper using macOS 26 `SpeechAnalyzer`, `SpeechTranscriber`, and `DictationTranscriber`.
- `voice_commands.py` — exact busy-only `stop` control policy.
- `APPEND_SYSTEM.md` — concise spoken-response guidance used by room-audio Pi RPC sessions.
- `test_asr_backends.py`, `test_voice_pipeline.py`, `test_pi_rpc.py` — backend, pipeline, and Pi RPC regression tests.

The persistent Pi RPC implementation lives at repository root in [`../../../pi_rpc.py`](../../../pi_rpc.py). The active room bridge lives in [`../raspberry-pi/room_audio/room_audio_server.py`](../raspberry-pi/room_audio/room_audio_server.py).

## Pipeline

```text
Raspberry Pi wake-accepted WAV
  → selected ASR backend (Apple Speech or oMLX Whisper)
  → optional ASR fallback
  → neutral persistent Pi RPC session
  → concise final text
  → local Piper JARVIS voice
  → bounded WAV response
```

The current room rollout uses Apple `SpeechTranscriber` for ordinary turns and Apple `DictationTranscriber` with short-form/far-field hints for the busy-only `stop` path. Each route retains oMLX Whisper as its failure/empty-output fallback. Only an exact normalized `stop` cancels generation/playback; idle speech and longer phrases do not invoke cancellation.

Apple Speech reads the completed WAV already captured by the Pi; it does not capture the Mac microphone. Apple’s `en-CA` Speech and Dictation assets are installed and the locale is reserved before deployment; inference remains on-device. The Pi’s 48 kHz mono signed-16-bit WAV format is accepted directly.

## Build and provision Apple Speech

Requires macOS 26 and Xcode/Swift 26 tooling:

```bash
projects/operation-jarvis/voice/apple_asr/build.sh

HELPER=projects/operation-jarvis/voice/apple_asr/.build/release/jarvis-apple-asr
"$HELPER" install-assets --engine speech --locale en-CA
"$HELPER" install-assets --engine dictation --locale en-CA
"$HELPER" health --engine speech --locale en-CA
"$HELPER" health --engine dictation --locale en-CA
```

The Swift source is committed; `.build/` and its compiled binary are local generated artifacts. The Python adapter executes the release helper directly with a bounded timeout and strict JSON—never through a shell and never by compiling Swift during a turn.

## Configuration

Canonical variables use the `JARVIS_VOICE_*` prefix:

- `JARVIS_VOICE_ASR_BACKEND` — `omlx` (code default), `apple-speech`, or `apple-dictation`.
- `JARVIS_VOICE_ASR_FALLBACK_BACKEND` — optional fallback used on backend failure or empty output.
- `JARVIS_VOICE_INTERRUPT_ASR_BACKEND` / `JARVIS_VOICE_INTERRUPT_ASR_FALLBACK_BACKEND` — optional control-path overrides.
- `JARVIS_VOICE_APPLE_ASR_HELPER`, `JARVIS_VOICE_APPLE_ASR_LOCALE`, `JARVIS_VOICE_APPLE_ASR_TIMEOUT_SECONDS`.
- `JARVIS_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS` — comma/semicolon/pipe/newline-separated short recognition hints, capped at 100.
- `JARVIS_VOICE_BASE_URL`, `JARVIS_VOICE_API_KEY`, `JARVIS_VOICE_ASR_MODEL`, `JARVIS_VOICE_ASR_LANGUAGE` — oMLX primary/fallback settings.
- `JARVIS_VOICE_LLM_MODEL`, `JARVIS_VOICE_LLM_MAX_TOKENS`, `JARVIS_VOICE_LLM_TEMPERATURE`, `JARVIS_VOICE_LLM_TOP_P`.
- `JARVIS_VOICE_TTS_BACKEND=piper` and the `JARVIS_VOICE_TTS_PIPER_*` voice controls.
- `JARVIS_VOICE_ASR_TIMEOUT_SECONDS`, `JARVIS_VOICE_LLM_TIMEOUT_SECONDS`, `JARVIS_VOICE_TTS_TIMEOUT_SECONDS`, `JARVIS_VOICE_MODEL_LOAD_TIMEOUT_SECONDS`.

Room-specific ASR overrides use `JARVIS_ROOM_AUDIO_ASR_*`; see the [room-audio README](../raspberry-pi/room_audio/README.md). When neither a configured ASR route nor direct chat uses oMLX, pipeline warm-up skips the oMLX model server completely.

## Tests

From the repository root:

```bash
export PYTHONPATH="$PWD:$PWD/projects/operation-jarvis/voice"
.venv/bin/python projects/operation-jarvis/voice/test_asr_backends.py
.venv/bin/python projects/operation-jarvis/voice/test_pi_rpc.py
.venv/bin/python projects/operation-jarvis/voice/test_voice_pipeline.py
.venv/bin/python projects/operation-jarvis/raspberry-pi/room_audio/test_room_audio_interrupt.py
```

The Python tests mock ASR/TTS/model calls and do not touch room hardware. A native smoke test should additionally transcribe a representative 48 kHz PowerConf WAV before deployment.
