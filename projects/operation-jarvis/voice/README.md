# Operation JARVIS Voice Pipeline

The Mac-side speech code for JARVIS. Room audio uses it to transcribe speech and generate spoken replies; the Watch reuses its speech synthesis for completed responses.

## Files

- `voice_pipeline.py`: pluggable ASR routing/fallback, optional direct oMLX chat, injected Pi RPC responses, transcript normalization, and bounded Piper synthesis.
- `asr_backends.py`: strict Apple Speech helper adapter plus the in-process oMLX callback adapter.
- `apple_asr/`: compiled Swift command-line helper using macOS 26 `SpeechAnalyzer`, `SpeechTranscriber`, and `DictationTranscriber`.
- `voice_commands.py`: exact busy-only `stop` control policy.
- `APPEND_SYSTEM.md`: concise spoken-response guidance used by room-audio Pi RPC sessions.
- `test_asr_backends.py`, `test_voice_pipeline.py`, `test_pi_rpc.py`: backend, pipeline, and Pi RPC regression tests.

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

The documented room setup uses Apple `SpeechTranscriber` for ordinary turns and `DictationTranscriber` with short-form/far-field hints for `stop` while JARVIS is busy. Both use Apple ASR without fallback; that setup has no oMLX Whisper model installed. Cancellation requires the exact normalized word `stop`. Idle speech and longer phrases do not cancel a turn.

Apple Speech reads the Pi's completed WAV file, not the Mac microphone. Install Apple's `en-CA` Speech and Dictation assets and reserve the locale before deployment. Transcription stays on-device and accepts the Pi's 48 kHz mono signed-16-bit WAV directly.

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

Swift source is checked in; `.build/` and the compiled helper stay local. Python runs the release helper directly, with a timeout and strict JSON parsing. It does not invoke a shell or compile Swift during a turn.

## Configuration

Voice settings use the `JARVIS_VOICE_*` prefix:

- `JARVIS_VOICE_ASR_BACKEND`: `apple-speech` (code default), `apple-dictation`, or opt-in `omlx`.
- `JARVIS_VOICE_ASR_FALLBACK_BACKEND`: optional fallback used on backend failure or empty output; blank by default.
- `JARVIS_VOICE_INTERRUPT_ASR_BACKEND` / `JARVIS_VOICE_INTERRUPT_ASR_FALLBACK_BACKEND`: control-path settings; defaults are `apple-dictation` with no fallback.
- `JARVIS_VOICE_APPLE_ASR_HELPER`, `JARVIS_VOICE_APPLE_ASR_LOCALE`, `JARVIS_VOICE_APPLE_ASR_TIMEOUT_SECONDS`.
- `JARVIS_VOICE_APPLE_ASR_CONTEXTUAL_STRINGS`: comma/semicolon/pipe/newline-separated short recognition hints, capped at 100.
- `JARVIS_VOICE_BASE_URL`, `JARVIS_VOICE_API_KEY`, `JARVIS_VOICE_ASR_MODEL`, `JARVIS_VOICE_ASR_LANGUAGE`: used only when explicitly opting into the oMLX ASR backend.
- `JARVIS_VOICE_LLM_MODEL`, `JARVIS_VOICE_LLM_MAX_TOKENS`, `JARVIS_VOICE_LLM_TEMPERATURE`, `JARVIS_VOICE_LLM_TOP_P`.
- `JARVIS_VOICE_TTS_BACKEND=piper` and the `JARVIS_VOICE_TTS_PIPER_*` voice controls.
- `JARVIS_VOICE_ASR_TIMEOUT_SECONDS`, `JARVIS_VOICE_LLM_TIMEOUT_SECONDS`, `JARVIS_VOICE_TTS_TIMEOUT_SECONDS`, `JARVIS_VOICE_MODEL_LOAD_TIMEOUT_SECONDS`.

Room-specific ASR overrides use `JARVIS_ROOM_AUDIO_ASR_*`; see the [room-audio README](../raspberry-pi/room_audio/README.md). Warm-up skips oMLX when neither ASR nor direct chat uses it.

## Tests

From the repository root:

```bash
export PYTHONPATH="$PWD:$PWD/projects/operation-jarvis/voice"
.venv/bin/python projects/operation-jarvis/voice/test_asr_backends.py
.venv/bin/python projects/operation-jarvis/voice/test_pi_rpc.py
.venv/bin/python projects/operation-jarvis/voice/test_voice_pipeline.py
.venv/bin/python projects/operation-jarvis/raspberry-pi/room_audio/test_room_audio_interrupt.py
```

These Python tests mock transcription, synthesis, and model calls; they do not use room hardware. Before deployment, also test the native helper with a representative 48 kHz PowerConf recording.
