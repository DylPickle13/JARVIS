# JARVIS TTS: pre-render ordinary text, confirm before speaking

Status: **activated with owner approval on mac-mini-64, September 29, 2026, around 5:07 p.m. EDT**. Session 10 was reloaded without changing its PID or conversation. Only the PowerConf and camera room-audio servers were restarted; no client/model restarts or session resets. Runtime capability, server health, high-quality Piper warm-up, and fresh idle client telemetry were verified. A human spoken-turn/acoustic check remains pending.

## Implemented behavior

```text
Session 10 ordinary text deltas
  → buffer complete sentences
  → silently synthesize with the existing high-quality Piper JARVIS voice
  → invalidate audio if that assistant message calls tools or is replaced
  → wait for the successful agent turn to settle
  → match prepared sentences against the actual cleaned final answer
  → reuse matching WAVs and synthesize anything missing
  → deliver the confirmed reply through the existing room playback path
```

No `<speak>` markers, native final-answer phase, model/router change, or cross-turn phrase cache is needed. Thinking and tool-call events are excluded from candidate text. Candidate audio is never passed to a playback consumer.

## Scope

This implements the approved **silent pre-render-and-confirm** optimization. It overlaps TTS computation with text generation, reducing work left after the final answer arrives.

The speaker transport still receives one complete confirmed WAV. Incremental speaker playback, a continuous PCM transport, and reducing leading silence are **not** part of this implementation. Any missing final sentence/fragment must finish rendering before delivery. Both PowerConf and the camera benefit without changing either output adapter, camera producer lifecycle, or room ownership policy.

Short single-sentence replies may have little overlap because their first complete sentence often arrives near the end of generation. Multi-sentence replies provide more opportunity. Speculative commentary costs some CPU even when discarded; work is bounded.

## Implementation

- `.pi/extensions/04-room-audio-session.ts` exports candidates only from the currently admitted voice request in verified Session 10. It forwards ordinary text, starts a new candidate per assistant message, invalidates on tool calls/errors, and retains final commitment at `agent_settled`.
- `.pi/extensions/lib/room-session.ts` retains existing admission, manual-draft, consumed-request, and exact-abort rules. Candidates do not resolve the final-answer promise or escape from manual turns.
- `shared_room_session.py` negotiates `tts-candidates-v1` from the existing private owner descriptor. The additive `prompt_stream` action sends candidate NDJSON frames and one terminal reply, tagged with owner generation and request ID. An old owner receives one legacy prompt; uncertain requests are never replayed.
- `room_tts_prerender.py` has one background TTS worker per voice turn, canonical sentence cleaning, exact final-text reconciliation, per-message invalidation, and cancellation/file cleanup. It reuses only current-candidate WAVs whose speech text matches a final segment, in final-answer order. Voice settings changes invalidate prepared audio.
- `voice_pipeline.py` accepts an optional final-only synthesis callback. It is invoked only after successful completion of the response callback, never while provisional text is being generated. Other callers retain their existing rendering behavior.
- `room_audio_server.py` wires this only into shared Session 10 room turns. Confirmed files remain under the existing room reply cleanup and playback lifecycle. It also fixes cleanup when stop races a newly returned committed result.

## Bounds and failure behavior

Speculation uses at most an 8,192-character candidate prefix, 16 inference attempts per turn, and 8 megabytes of prepared WAV files, plus one in-flight segment bounded by the existing maximum segment size. The final answer is not truncated when these budgets are exhausted; missing audio is rendered normally after confirmation.

Candidate frames are bounded by count, bytes, and socket write-buffer size. A slow/disconnected candidate consumer cannot block Pi's agent loop. Candidate-channel/rendering errors fall back to ordinary final rendering where the terminal reply is still received; loss or identity change of the actual reply fails without resubmitting the prompt.

Stop discards prepared audio and prevents late inference results from being retained. Already-running Piper inference cannot be forcibly interrupted, but its eventual file is deleted. Only the matching still-active Pi request may be aborted; a later interactive request is never aborted because an old audio turn is cancelled.

No new recordings or transcript logs are created. Temporary audio uses the existing Piper WAV mechanism and is deleted after rejection, cancellation, failure, or normal response delivery.

## Configuration and observability

`JARVIS_ROOM_AUDIO_TTS_PRERENDER=1` enables this for shared Session 10 room bridges (the code default); `0` disables it. Other conversation backends are unaffected. Owner capability negotiation prevents requiring a new extension from an old owner.

- `/health`: `ttsPrerenderEnabled` reports server configuration, not proof of live streamed candidates or audible output.
- Successful turn response: `ttsPrerender` contains rendered/reused/discarded segment counts and background render seconds.
- `ttsSeconds` remains post-response rendering/commit latency. Background inference overlaps `llmSeconds`; do not add `renderSeconds` to elapsed time or interpret it as a separate serialized stage.

## Verification

Offline tests exercise real private-socket framing plus the actual room response pipeline using fake WAV synthesis. They cover early rendering without early playback, invalidation, final mismatch, matching in-flight work, trailing fragments, budgets, settings changes, speculative failures, legacy owners, wrong generation, lost streams, cancellation, and committed-file cleanup races. Existing room, ASR, Watch, wake, control, gate, and history behavior is regression-tested.

A silent benchmark used the installed high-quality Piper model with a simulated text stream at 35 milliseconds per word (three runs per reply). Median **post-final conversion/assembly** latency:

| Example reply | Normal rendering | Pre-render + confirmation |
| --- | ---: | ---: |
| 40 characters, two sentences | 300 ms | 96 ms |
| 75 characters, three sentences | 865 ms | 257 ms |
| 147 characters, three sentences | 1,388 ms | 160 ms |

These are controlled text-stream/Piper measurements, **not live LLM or audible end-to-end results**. Speaker startup, existing padding, model contention, and actual token arrival cadence still affect real performance. Temporary benchmark results contain timings only; all generated WAVs were removed.

## Activation and rollback

The approved idle activation completed steps 1–3 below. Session 10 retained PID 56852 and its history path; all ten pane/PID/history identities matched the preflight snapshot. Both servers reported pre-rendering enabled, freshly idle clients, and successful high-quality Piper warm-up without startup tracebacks. No synthetic conversation prompt or speaker playback was triggered. Steps 4–5 still require real spoken-turn validation.

Private agent backups and deployment verification are in `~/Library/Application Support/JARVIS/room-tts-prerender/20260929-170643/`. The saved owner descriptor is evidence only; never restore it over a live owner.

1. During an owner-approved idle window, reload **only Session 10** to load the updated extension. Preserve its PID and conversation; do not reset it.
2. Verify its owner descriptor advertises `tts-candidates-v1` and its existing status/abort path is healthy.
3. Reload only the affected room audio servers (PowerConf server and camera room server). No playback clients, camera service, shared wake worker, or model service need restarting.
4. Verify configured health and real turn reuse counts; acoustically check the same voice, correct final reply, stop during generation/playback, and competing-room ownership.
5. Compare live post-final rendering and total response timings. Disable `JARVIS_ROOM_AUDIO_TTS_PRERENDER` and reload affected servers if speculation causes a net regression. Legacy final-only prompt/playback remains available; never automatically replay a partly completed turn.
