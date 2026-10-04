# Operation JARVIS Voice Pipeline

The Mac-side speech code for JARVIS. Room audio uses it to transcribe speech and generate spoken replies; the Watch reuses its speech synthesis for completed responses.

## Files

- `voice_pipeline.py`: pluggable ASR routing/fallback, optional direct oMLX chat, injected Pi RPC responses, transcript normalization, and bounded Piper synthesis.
- `voice_lines.py`: side-effect-free catalogue of the remaining room announcements and fixed error notices. Edit named defaults here rather than copying dialogue into callers.
- `phrase_catalogue.json`, `phrase_banks.py`, `render_phrase_banks.py`: opt-in approved-text banks, validated pre-rendered recordings and shared durable selection. See [PHRASE-BANKS.md](PHRASE-BANKS.md); not activated by default.
- `asr_backends.py`: strict Apple Speech helper adapter plus the in-process oMLX callback adapter.
- `apple_asr/`: compiled Swift command-line helper using macOS 26 `SpeechAnalyzer`, `SpeechTranscriber`, and `DictationTranscriber`.
- `voice_commands.py`: exact busy-only `stop` control policy.
- `APPEND_SYSTEM.md`: presentation-only overlay shared by interactive Room Audio Session 10 and standalone room Pi RPC. Core tools, safety, permissions, and local context come from the normal Pi prompt; do not duplicate device instructions here.
- `test_asr_backends.py`, `test_voice_pipeline.py`, `test_pi_rpc.py`: backend, pipeline, and Pi RPC regression tests.

The persistent Pi RPC implementation lives at repository root in [`../../../pi_rpc.py`](../../../pi_rpc.py). The active room bridge lives in [`../room-audio/room_audio_server.py`](../room-audio/room_audio_server.py).

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

Room-specific ASR overrides use `JARVIS_ROOM_AUDIO_ASR_*`; see the [room-audio README](../room-audio/README.md). Warm-up skips oMLX when neither ASR nor direct chat uses it.

### Fixed dialogue and greeting controls

Room dialogue defaults come from `voice_lines.py`; normal assistant answers and
Watch playback still use generated/supplied text. Processing-acknowledgement
environment overrides retain precedence over catalogue defaults.
`JARVIS_VOICE_PROCESSING_ACK_ENABLED` and `JARVIS_VOICE_PROCESSING_ACK_TEXT`
configure neutral-pipeline steering acknowledgements. Room-specific
`JARVIS_ROOM_AUDIO_PROCESSING_ACK_*` values take precedence for the room bridge.
An empty acknowledgement text suppresses it.

Startup, reconnect, quick-return, and time-of-day announcements have been removed.
The client no longer requests or plays connection greetings. Legacy startup and
reconnect CLI flags remain accepted but inert for installed-agent compatibility;
their environment settings, saved startup text/state, and voice greeting cooldown/
status settings are ignored. The legacy `/greeting` endpoint returns a successful
disabled response with no text or audio, even with old text overrides present.

`JARVIS_ROOM_AUDIO_GREETING_ENABLED=0` now disables only the separate arrival
notice. It does not disable the `Yes sir?` wake acknowledgement or processing
acknowledgements. `/health` reports connection greetings unsupported/disabled and
reports arrival support separately as `arrivalGreetingSupported` and
`arrivalGreetingEnabled`.

Failure notices distinguish an incomplete request from a completed response that
could not be rendered. Completion is recorded explicitly; speculative text is not
proof that a response is ready. Error messages intentionally keep their exact
wording and must not participate in announcement variation banks:

- Request failure: “I couldn't complete that request, sir.”
- Speech failure after a completed reply: “Your response is ready, sir, but I couldn't speak it.”

The protected doorbell farewell intentionally remains in
`security/departure-greeting/runtime.py`. Its status output shares that constant;
playback still validates the pre-rendered phrase/WAV/hash. Changing its wording
requires an explicit recording/metadata update, not merely a catalogue edit.
Documentation examples and synthetic test dialogue are not operational canned
responses. Historical farewells in the departure changelog are labelled as such.

## Tests

From the repository root:

```bash
export PYTHONPATH="$PWD:$PWD/projects/operation-jarvis/voice"
.venv/bin/python projects/operation-jarvis/voice/test_asr_backends.py
.venv/bin/python projects/operation-jarvis/voice/test_pi_rpc.py
.venv/bin/python projects/operation-jarvis/voice/test_voice_pipeline.py
.venv/bin/python projects/operation-jarvis/room-audio/test_room_audio_interrupt.py
```

These Python tests mock transcription, synthesis, and model calls; they do not use room hardware. Before deployment, also test the native helper with a representative 48 kHz PowerConf recording.
