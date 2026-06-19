# Operation JARVIS Voice

Live Discord voice-call subsystem for Operation JARVIS.

**Local/private operations note:** this README intentionally contains local model choices, channel names, and operational tuning. Keep it private; do not publish without review.

The main root `discord_bot.py` loads `projects/operation-jarvis/voice/discord_voice.py` directly so one Discord bot process handles text channels, voice-channel text chat, and the `jarvis` voice channel. `discord_voice_bot.py` remains available as a standalone runner for isolated testing.

## Quick runbook

The main JARVIS bot already loads this voice subsystem. Do **not** run the standalone voice bot with the same Discord token while the main bot is running.

Root bot path:

```bash
cd /path/to/JARVIS
source .venv/bin/activate
python discord_bot.py
```

Standalone isolated test path only:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/voice
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with a test token/settings, then:
python discord_voice_bot.py
```

Smoke checks before blaming Discord receive:

- `ffmpeg` is on `PATH`.
- oMLX ASR model is visible at `DISCORD_VOICE_BASE_URL`.
- Piper/JARVIS TTS backend can synthesize a short phrase.
- openWakeWord dependency/model loads without fallback unless intentionally configured.

## Machine dependencies

When live voice is configured to use the OMLX-64 response model, the confirmed configured host endpoint is `<host-name> at `<private-lan-ip>` with SSH user `<ssh-user>`, key `~/.ssh/jarvis_dashboard_host`, and Pi harness SSH alias `minecraft-mac-mini`. OMLX-64 API defaults elsewhere in the repo use `http://<voice-model-host>:8000/v1`.

The room-audio Raspberry Pi endpoint used by the companion room mic/speaker stack is `raspberrypi` at `<private-lan-ip>`, SSH user `pi`, key `~/.ssh/jarvis_dashboard_host`.

## What it does

When enabled in the main bot:

1. Watches for non-bot users in the configured Discord voice channel, default `jarvis`.
2. Joins the channel using `discord-ext-voice-recv` and plays a short JARVIS greeting.
3. Receives Discord PCM audio and segments utterances after short silences.
4. Runs an upstream local openWakeWord acoustic gate, default model `hey_jarvis`, before Whisper.
5. Sends only locally wake-accepted utterances through oMLX Whisper ASR.
6. Applies the transcript wake-word confirmation gate, default `jarvis`, `arvis`, `charvis`, `travis`, `darvish`, or `charmavis`.
7. Sends the transcript into a persistent Pi RPC session for that voice channel.
8. Feeds Pi final/tool deltas to local Piper JARVIS TTS in sentence-sized chunks while Pi is still generating, then plays each generated WAV back into Discord as soon as it is ready.

Current main-bot stack:

```text
Discord PCM → openWakeWord acoustic gate → Whisper large-v3-turbo ASR → transcript wake confirmation → Pi RPC session using DISCORD_VOICE_PI_MODEL → Piper JARVIS TTS → Discord playback
```

Recommended installed models:

- ASR in oMLX: `mlx-community/whisper-large-v3-turbo-asr-4bit`
- Pi response model: configured by `DISCORD_VOICE_PI_MODEL`, currently `omlx-64/Qwen3.6-35B-A3B-6bit` with `DISCORD_PI_THINKING=xhigh`; set it empty to fall back to root `DISCORD_PI_MODEL`, or use `/jarvis model` in the voice channel text chat to change the voice LLM session.
- Local TTS: Piper JARVIS model from `jgkawell/jarvis`, quality `high`

The standalone `discord_voice_bot.py` still uses the direct oMLX chat path configured by `DISCORD_VOICE_LLM_MODEL`; the main bot injects a Pi RPC response callback instead. In main-bot voice mode, joining the voice channel starts a fresh Pi session, all wake-word prompts during that shared voice-channel connection stay in that one Pi session, and disconnecting ends/stops it.

Voice-channel text chat mirrors wake-word turns as regular chat-style messages: normal turns use `The user said:` followed by a Discord block quote of the transcript, steering turns use `Steering said:` followed by the steering transcript, then the assistant response streams live in the voice channel text chat using the same edit/update flow as normal text channels. The same `/jarvis` slash commands are enabled in the voice channel text chat; `/jarvis model` targets the voice Pi session/model used by the ASR → LLM → TTS pipeline.

## Files

- `discord_voice.py` — Discord voice receive/buffering/playback plus reusable oMLX ASR and Piper TTS pipeline; the main bot injects Pi RPC for the response step.
- `discord_voice_bot.py` — minimal standalone Discord runner for voice-only testing.
- `APPEND_SYSTEM.md` — voice-only Pi append-system prompt used by the main Discord bot for live voice sessions; normal text channels do not receive this prompt.
- `config.py` — local `.env`, typed environment-variable, path, and logging helpers for standalone use.
- `.env.example` — voice configuration template.
- `requirements.txt` — voice-specific Python dependencies.

The old `projects/voice-control/` copy has been removed. This directory is the canonical implementation location.

## Setup for standalone testing

```bash
cd /path/to/JARVIS/projects/operation-jarvis/voice
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with DISCORD_BOT_TOKEN and voice/oMLX settings
python discord_voice_bot.py
```

External runtime requirements:

- `ffmpeg` on `PATH` for Discord playback.
- Piper TTS Python dependencies for the local JARVIS voice.
- oMLX server reachable at `DISCORD_VOICE_BASE_URL`.
- openWakeWord/ONNX Runtime for the local acoustic wake gate (`pip install -r requirements.txt`).
- The configured ASR model installed in oMLX. For the standalone runner, the configured voice LLM must also be installed in oMLX.

Do not run this standalone voice bot and the main JARVIS bot with the same Discord token at the same time. The main bot already loads this voice manager for `jarvis`.

## Key settings

- `DISCORD_BOT_TOKEN`: required Discord bot token.
- `DISCORD_VOICE_ENABLED`: enable/disable the standalone voice listener.
- `DISCORD_VOICE_CHANNEL_NAME`: voice channel to auto-join when a non-bot user is present.
- `DISCORD_VOICE_STATUS_TEXT_CHANNEL_NAME`: optional text/voice channel for status messages.
- `DISCORD_VOICE_JOIN_WHEN_EMPTY`: defaults to `0`; starts listening when a human is present, matching the original working voice-receive behavior and avoiding stale empty-channel voice receive state.
- `DISCORD_VOICE_CONTEXTUAL_GREETINGS`: defaults to `1`; join greetings use Toronto local time and a small persisted reconnect history instead of only random static phrases.
- `DISCORD_VOICE_GREETING_COOLDOWN_MINUTES`: defaults to `10`; if JARVIS rejoins the same voice channel within this window, he uses a “back already” style greeting.
- `DISCORD_VOICE_GREETING_INCLUDE_STATUS`: defaults to `1`; appends a short suffix such as `JARVIS online.` or `Systems are online.`.
- `DISCORD_VOICE_GREETING_STATE_PATH`: optional state file override; defaults to `projects/operation-jarvis/data/voice_greeting_state.json`.
- `DISCORD_VOICE_PRELOAD_ON_JOIN`: load required oMLX models when the bot joins; also validates the selected TTS backend. In the main bot, the voice response model is owned by the Pi RPC session, not this preload step.
- `DISCORD_VOICE_BASE_URL`: oMLX/OpenAI-compatible base URL. Use `OMLX_API_KEY` for shared bearer auth or `DISCORD_VOICE_API_KEY` as a voice-specific override.
- `DISCORD_VOICE_ASR_MODEL`, `DISCORD_VOICE_ASR_LANGUAGE`: configured oMLX ASR model/language. `DISCORD_VOICE_PI_MODEL` is the voice-only Pi LLM override used by the main bot and defaults/templates to `omlx-64/Qwen3.6-35B-A3B-6bit`; set it empty to fall back to root `DISCORD_PI_MODEL`. `DISCORD_VOICE_LLM_MODEL` only applies to the standalone direct-oMLX runner. `DISCORD_PI_MODEL_OPTIONS` controls the model IDs exposed in the `/jarvis model` panel for easy swapping.
- `DISCORD_VOICE_LLM_MAX_TOKENS`, `DISCORD_VOICE_LLM_TEMPERATURE`, `DISCORD_VOICE_LLM_TOP_P`, `DISCORD_VOICE_LLM_DISABLE_THINKING`, `DISCORD_VOICE_HISTORY_TURNS`, `DISCORD_VOICE_SYSTEM_PROMPT`: standalone direct-oMLX runner response controls. Main-bot live voice uses Pi RPC plus `APPEND_SYSTEM.md` instead.
- `DISCORD_VOICE_TTS_BACKEND`: must be `piper`.
- `DISCORD_VOICE_TTS_PIPER_REPO_ID`, `DISCORD_VOICE_TTS_PIPER_QUALITY`, `DISCORD_VOICE_TTS_PIPER_LENGTH_SCALE`, `DISCORD_VOICE_TTS_PIPER_VOLUME`, `DISCORD_VOICE_TTS_PIPER_NOISE_SCALE`, `DISCORD_VOICE_TTS_PIPER_NOISE_W_SCALE`: Piper JARVIS voice selection/tuning. Quality is `medium` or `high`.
- `DISCORD_VOICE_STREAM_TTS`: defaults to `1`; streams TTS chunks while the LLM is still generating.
- `DISCORD_VOICE_STREAM_START_WORDS`: defaults to `0`; waits for the first complete sentence before TTS starts. Set above zero to start after that many words instead.
- `DISCORD_VOICE_WAKE_WORD`: defaults to `jarvis,arvis,charvis,travis,darvish,charmavis`; comma/semicolon/pipe-separated wake words are accepted. The local openWakeWord gate runs before ASR, then the bot transcribes only wake-accepted utterances and generates/speaks a response when any configured wake word appears in the transcript. Non-`jarvis` wake-word aliases are normalized to `jarvis` before the transcript is sent to the voice LLM. Set empty to disable the wake gate. If another wake-word utterance arrives while JARVIS is generating/speaking, it steers the active Pi task and TTS resets to the post-steer answer.
- `DISCORD_VOICE_LOCAL_WAKE_WORD_ENABLED`: defaults to `1`; uses openWakeWord locally before oMLX Whisper so non-wake speech is dropped before ASR. The stock `DISCORD_VOICE_OPENWAKEWORD_MODEL=hey_jarvis` expects the spoken phrase “hey Jarvis”.
- `DISCORD_VOICE_LOCAL_WAKE_WORD_FALLBACK_TO_ASR`: defaults to `0`; when local wake is enabled, openWakeWord install/model problems block voice ASR instead of silently falling back to the old always-ASR path. Set to `1` only for emergency fallback.
- `DISCORD_VOICE_OPENWAKEWORD_MODEL`, `DISCORD_VOICE_OPENWAKEWORD_INFERENCE`, `DISCORD_VOICE_OPENWAKEWORD_MODEL_DIR`, `DISCORD_VOICE_OPENWAKEWORD_AUTO_DOWNLOAD`: openWakeWord model and runtime controls. On the Mac voice host the default inference backend is `onnx`.
- `DISCORD_VOICE_LOCAL_WAKE_WORD_THRESHOLD`, `DISCORD_VOICE_LOCAL_WAKE_WORD_COOLDOWN_SECONDS`, `DISCORD_VOICE_LOCAL_WAKE_WORD_ARM_SECONDS`, `DISCORD_VOICE_LOCAL_WAKE_WORD_CHUNK_MS`, `DISCORD_VOICE_LOCAL_WAKE_WORD_LOG_SCORES`: acoustic wake-word tuning. Threshold defaults to `0.5`, matching the room-audio Pi service; set score logging to `1` temporarily when tuning threshold.
- `DISCORD_VOICE_TRUST_LOCAL_WAKE_WORD`: defaults to `0`; keeps ASR transcript wake-word confirmation after acoustic detection. Set to `1` only if you want an acoustic “hey Jarvis” hit to allow a follow-up command inside the arm window even when Whisper does not transcribe the wake phrase.
- `DISCORD_VOICE_SILENCE_SECONDS`, `DISCORD_VOICE_MONITOR_INTERVAL_SECONDS`, `DISCORD_VOICE_MIN_UTTERANCE_SECONDS`, `DISCORD_VOICE_MAX_UTTERANCE_SECONDS`, `DISCORD_VOICE_QUEUE_MAX_SIZE`, `DISCORD_VOICE_INGEST_QUEUE_MAX_FRAMES`: utterance segmentation and queue controls. Defaults keep Discord voice aligned with room audio: `1.0s` silence before finalizing, `0.5s` minimum utterance, `30s` max; raw receive frames are queued before local wake scoring so Discord voice heartbeats are not blocked by ONNX inference.
- `DISCORD_VOICE_PREPROCESS_AUDIO`, `DISCORD_VOICE_SILENCE_RMS_THRESHOLD`, `DISCORD_VOICE_MIN_VOICED_MS`: local voice/noise gate before ASR.
- `DISCORD_VOICE_PREROLL_MS`: defaults to `500`; prepends a short rolling buffer of quiet pre-gate audio when speech starts so ASR does not lose soft first syllables. `DISCORD_VOICE_SILENCE_PADDING_MS` also defaults to `500` so preprocessing preserves that pre-roll.
- `DISCORD_VOICE_INPUT_SAMPLE_RATE`, `DISCORD_VOICE_INPUT_MIN_SECONDS`, `DISCORD_VOICE_MONO_MODE`, `DISCORD_VOICE_NORMALIZE_TARGET_PEAK`, `DISCORD_VOICE_NORMALIZE_TARGET_RMS`, `DISCORD_VOICE_NORMALIZE_MAX_GAIN`: ASR input resampling, channel selection, padding, and level normalization.
- `DISCORD_VOICE_TTS_SPEED`, `DISCORD_VOICE_TTS_MAX_CHARS_PER_SEGMENT`, `DISCORD_VOICE_TTS_MAX_SEGMENTS`: global TTS speed, chunk size, and optional spoken-segment cap.
- `DISCORD_VOICE_TTS_STRIP_URLS`, `DISCORD_VOICE_TTS_STRIP_CODE`, `DISCORD_VOICE_TTS_STRIP_MARKDOWN`, `DISCORD_VOICE_TTS_STRIP_DISCORD_MARKUP`: default to `1`; silently remove those forms before TTS, without saying placeholders like “link”.
- `DISCORD_VOICE_SPEAK_PI_THINKING`: the checked-in templates set this to `0`; in main-bot Pi RPC mode, thinking deltas are not spoken. If unset, the main bot code default is enabled.
- `DISCORD_VOICE_SPEAK_TOOL_CALLS`: defaults/templates to `0`; set to `1` to have live voice TTS speak short JARVIS-style, tool-specific narration when a tool starts, and a tool-specific failure line if it fails.
- `APPEND_SYSTEM.md`: voice-only Pi append-system prompt for live voice sessions. Edit this Markdown file to change JARVIS voice behavior/personality without changing code. Normal text channels do not receive it.
- `DISCORD_VOICE_PROCESSING_ACK_ENABLED`: defaults to `1`; set to `0`/`false`/`no`/`off` to disable the processing acknowledgement.
- `DISCORD_VOICE_PROCESSING_ACK_TEXT`: defaults to `Generating your response, sir.`; when enabled, TTS says this only after the wake word is found in the ASR transcript, before Pi response generation.
- `DISCORD_VOICE_STEERING_TTS_DELAY_SECONDS`: defaults to `2.0`; after a wake-word steering interruption—or a no-longer-steerable response that is cut over into the next voice turn—pauses briefly before TTS resumes so stale audio can clear.
- `DISCORD_VOICE_STATUS_DIAGNOSTICS`: defaults/templates to `1`; posts concise per-utterance tuning diagnostics. Set to `0` once tuning is stable.
- `DISCORD_VOICE_DROP_WHILE_BUSY`, `DISCORD_VOICE_SUPPRESS_RECV_CRYPTO_ERRORS`: feedback/backlog prevention and optional suppression of known receive crypto noise.
- `DISCORD_VOICE_ASR_TIMEOUT_SECONDS`, `DISCORD_VOICE_LLM_TIMEOUT_SECONDS`, `DISCORD_VOICE_TTS_TIMEOUT_SECONDS`, `DISCORD_VOICE_MODEL_LOAD_TIMEOUT_SECONDS`: stage-specific timeouts.
- `DISCORD_VOICE_TTS_MAX_BYTES`: maximum TTS response download size.
- `DISCORD_VOICE_UNLOAD_BETWEEN_STAGES`: defaults to `0` so preloaded models stay hot.
- `DISCORD_VOICE_REQUIRE_CONFIGURED_MODELS`: defaults to `1`; fail warm-up if configured oMLX models are not visible.
- `DISCORD_VOICE_REQUEST_RETRIES`, `DISCORD_VOICE_REQUEST_RETRY_BACKOFF_SECONDS`: retries for transient oMLX transport failures.

## Documentation maintenance

This README is intentionally detailed and configuration-heavy. When adding large new groups of environment variables, prefer moving the exhaustive reference into a dedicated `docs/config.md` and keeping this file focused on architecture, runbook, safety, and common tuning.

See `.env.example` for the full set of tuning knobs.
