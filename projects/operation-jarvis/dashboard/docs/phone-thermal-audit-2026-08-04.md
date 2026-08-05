# Dashboard phone thermal audit — 2026-08-04

Scope: the always-on alarm-clock dashboard, with emphasis on browser openWakeWord.

## Findings

1. **ONNX Runtime was free to create up to four WASM inference workers.** The dashboard is cross-origin isolated, so ONNX Runtime Web derives its default as `min(4, ceil(hardwareConcurrency / 2))`. This is useful for latency but expensive for an always-on phone.
2. **The wake inference Promise chain was unbounded.** A device taking longer than the 80 ms audio frame interval could accumulate work indefinitely, remain at maximum CPU, increase memory use, and process stale audio.
3. **The audio path allocated and copied repeatedly.** Each 80 ms frame was cloned crossing the AudioWorklet boundary, cloned again in the engine, and stored as another small ring-buffer allocation.
4. **Backgrounding did not stop voice inference or the microphone.** The visibility handler only restarted a missing engine; it did not suspend or stop an active one.
5. **Normal listening repeatedly rewrote identical voice-card DOM state.** A noisy/auto-gained microphone could trigger this roughly every 700 ms, forcing style work on a visually complex HUD.
6. **Non-voice polling was more frequent than the room display needs.** Display data refreshed every 10 seconds, smart plugs every 5 seconds, indicators every 30 seconds, and the clock timer ran every second.

openWakeWord remains the dominant sustained compute cost. The static CSS has many gradients and shadows, but decorative animation, backdrop blur, camera auto-start, and active SVG filtering were already disabled.

## Changes made

- Default ONNX Runtime Web to **one WASM inference thread**. Override with `?voiceThreads=2` only if phone telemetry reports an overrun.
- Replace the unbounded inference Promise chain with a bounded four-frame queue. Old frames are dropped and model state is reset after an overrun instead of allowing unlimited stale work.
- Emit one 15-second wake performance sample to the dashboard server log, including average frame time, real-time load, dropped frames, and thread count.
- Transfer AudioWorklet frame buffers instead of structured-cloning them, and replace the pre-roll array queue with a fixed circular `Float32Array`.
- Stop microphone capture and inference while the page is hidden, then reuse the already-loaded model sessions when visible again.
- Suspend the wake AudioContext while the server handles STT/LLM/TTS and the phone plays the response.
- Deduplicate voice-card state updates.
- Cache `Intl.DateTimeFormat` instances, align clock updates to minute boundaries, deduplicate uptime writes and layout animation-frame requests, and move dashboard/smart-plug/indicator polling to 30–60 second visibility-aware intervals.
- Move the customized engine into tracked `public/wake-word-engine.js`; only large model/runtime assets remain under ignored `public/vendor/`.

## Validation

```bash
cd projects/operation-jarvis/dashboard
npm run check
```

Rendered smoke test on desktop Chrome:

- model loaded and microphone started,
- one-thread runtime confirmed,
- 15-second sample: **5.1 ms average per 80 ms frame**, **0.06 real-time load**, **0 dropped frames**, **10.6 ms max**,
- voice off/on reused the loaded model instead of loading it again,
- `/wake-word-engine.js` served with the required cross-origin isolation headers.

The dashboard phone was not connected over ADB during this audit, so its post-change CPU and battery temperature still need an on-device soak test. The new client telemetry will report whether one thread keeps up; use two threads only if `wake inference overrun` appears.

## Larger follow-up option

For the largest possible phone-side reduction, stream 16 kHz mono PCM to the Mac mini and run openWakeWord there. That removes ONNX inference from the phone but adds a continuous ~32 KiB/s LAN stream and a server-side streaming endpoint. It is a larger architectural change and should only be pursued if the one-thread bounded client still runs too warm.

An RMS-only inference gate was not enabled by default. Phone AGC and steady room noise can make it ineffective, while an aggressive threshold can miss the start of “Hey Jarvis.”
