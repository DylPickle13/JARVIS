import { WakeWordEngine } from '/vendor/openwakeword/WakeWordEngine.js';

const voiceCard = document.querySelector('#dashboard-voice-card');
const voiceDetailEl = document.querySelector('#dashboard-voice-detail');
const voiceIconEl = document.querySelector('#dashboard-voice-icon');
const voiceAudioEl = document.querySelector('#dashboard-voice-audio');

const toneClasses = ['tone-cyan', 'tone-green', 'tone-violet', 'tone-pink', 'tone-amber', 'tone-orange', 'tone-blue', 'tone-indigo', 'tone-silver'];
const urlParams = new URLSearchParams(window.location.search);
const VOICE_SAMPLE_RATE = 16_000;
const WAKE_FRAME_SIZE = 1_280;
const DEFAULT_SILENCE_RMS = 0.007;
const AUDIO_UNLOCK_TIMEOUT_MS = 800;
const SILENT_WAV_DATA_URL = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=';

const voiceConfig = {
  threshold: clampNumber(urlParams.get('voiceThreshold'), 0.1, 0.99, 0.36),
  gain: clampNumber(urlParams.get('voiceGain'), 0.2, 6, 1.85),
  silenceRms: clampNumber(urlParams.get('voiceSilenceRms'), 0.002, 0.08, DEFAULT_SILENCE_RMS),
  silenceMs: clampNumber(urlParams.get('voiceSilenceMs'), 400, 2500, 1000),
  minMs: clampNumber(urlParams.get('voiceMinMs'), 500, 5000, 1300),
  maxMs: clampNumber(urlParams.get('voiceMaxMs'), 2500, 30000, 10000),
  preRollMs: clampNumber(urlParams.get('voicePreRollMs'), 0, 3000, 1400),
  debug: ['1', 'true', 'yes'].includes(String(urlParams.get('voiceDebug') || '').toLowerCase()),
  autoArm: !['0', 'false', 'no', 'off'].includes(String(urlParams.get('voiceAutoArm') || '1').toLowerCase())
};

let modeEnabled = false;
let wakeEngine = null;
let wakeStartPromise = null;
let wakeUnsubscribers = [];
let ringChunks = [];
let ringSampleCount = 0;
let recording = null;
let turnInFlight = false;
let lastRecordingUiAt = 0;
let activeAudioObjectUrl = '';
let pendingMicStream = null;
let lastMicActivityUiAt = 0;
let lastWakeScoreUiAt = 0;
let lastWakeScoreReportAt = 0;
let bestWakeScore = 0;
let reportedMicAudio = false;
let reportedWakeRuntime = false;

function clampNumber(value, min, max, fallback) {
  if (value === null || value === undefined || value === '') return fallback;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, numeric));
}

function waitMs(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, ms)));
}

function shortText(value = '', max = 64) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trim()}…`;
}

function normalizeVoiceError(error, fallback = 'Dashboard voice failed') {
  const rawMessage = String(error?.message || error?.name || fallback || '').trim();
  const rawName = String(error?.name || '').trim();
  const message = rawMessage || fallback;
  if (/permission denied|notallowederror|permission dismissed|denied/i.test(`${rawName} ${message}`)) {
    return 'Mic permission denied — allow microphone for this dashboard site.';
  }
  if (/notfounderror|devicesnotfounderror|no input device/i.test(`${rawName} ${message}`)) {
    return 'No phone microphone was found.';
  }
  if (/notreadableerror|trackstarterror|could not start/i.test(`${rawName} ${message}`)) {
    return 'Phone microphone is busy in another app.';
  }
  if (/secure isolated page|cross.?origin|sharedarraybuffer/i.test(`${rawName} ${message}`)) {
    return 'Secure isolated page required — hard refresh the dashboard.';
  }
  return message;
}

function reportVoiceClientEvent(level, message, detail = '') {
  const payload = {
    level,
    message: shortText(message, 220),
    detail: shortText(detail, 220),
    state: voiceCard?.dataset?.state || '',
    secureContext: Boolean(window.isSecureContext),
    crossOriginIsolated: Boolean(window.crossOriginIsolated),
    userAgent: navigator.userAgent || '',
    at: new Date().toISOString()
  };
  fetch('/api/jarvis/dashboard-voice/client-event', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
    cache: 'no-store'
  }).catch(() => {});
}

function setVoiceState(state, detail = '') {
  if (!voiceCard) return;
  const labels = {
    off: 'Dashboard voice off',
    arming: 'Arming dashboard voice',
    listening: 'Dashboard voice listening',
    wake: 'Wake word detected',
    recording: 'Recording dashboard voice command',
    processing: 'Processing dashboard voice command',
    speaking: 'Playing JARVIS response on phone',
    error: 'Dashboard voice error'
  };
  const tones = {
    off: 'tone-silver',
    arming: 'tone-amber',
    listening: 'tone-blue',
    wake: 'tone-amber',
    recording: 'tone-green',
    processing: 'tone-amber',
    speaking: 'tone-cyan',
    error: 'tone-orange'
  };
  const defaults = {
    off: 'Tap to arm',
    arming: 'Starting',
    listening: 'Listening',
    wake: 'Wake detected',
    recording: 'Recording',
    processing: 'Thinking',
    speaking: 'Speaking',
    error: 'Error'
  };
  const label = labels[state] || labels.off;
  const displayDetail = detail || defaults[state] || defaults.off;

  voiceCard.dataset.state = state;
  voiceCard.classList.remove(...toneClasses);
  voiceCard.classList.add(tones[state] || 'tone-silver');
  voiceCard.setAttribute('aria-pressed', modeEnabled ? 'true' : 'false');
  voiceCard.setAttribute('aria-busy', ['arming', 'processing'].includes(state) ? 'true' : 'false');
  voiceCard.setAttribute('aria-label', `${label}. ${displayDetail}`);
  voiceCard.title = `${label}. ${displayDetail}`;

  if (voiceDetailEl) voiceDetailEl.textContent = displayDetail;
  if (voiceIconEl) voiceIconEl.setAttribute('aria-label', label);
}

function rms(samples) {
  if (!samples?.length) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = samples[i] || 0;
    sum += sample * sample;
  }
  return Math.sqrt(sum / samples.length);
}

function rememberRingChunk(samples) {
  const copy = samples instanceof Float32Array ? new Float32Array(samples) : Float32Array.from(samples || []);
  if (!copy.length) return;
  ringChunks.push(copy);
  ringSampleCount += copy.length;
  const maxSamples = Math.round(VOICE_SAMPLE_RATE * voiceConfig.preRollMs / 1000);
  while (ringSampleCount > maxSamples && ringChunks.length > 0) {
    const removed = ringChunks.shift();
    ringSampleCount -= removed?.length || 0;
  }
}

function flattenChunks(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + (chunk?.length || 0), 0);
  const output = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    if (!chunk?.length) continue;
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

function wavBlobFromFloat32(samples, sampleRate = VOICE_SAMPLE_RATE) {
  const bytesPerSample = 2;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i] || 0));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

function writeAscii(view, offset, value) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

function base64ToBlob(base64, contentType = 'audio/wav') {
  const binary = window.atob(base64);
  const arrays = [];
  const chunkSize = 8192;
  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let i = 0; i < slice.length; i += 1) bytes[i] = slice.charCodeAt(i);
    arrays.push(bytes);
  }
  return new Blob(arrays, { type: contentType || 'audio/wav' });
}

function stopPendingMicStream() {
  if (!pendingMicStream) return;
  for (const track of pendingMicStream.getTracks?.() || []) track.stop();
  pendingMicStream = null;
}

async function requestPhoneMicStream() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('This browser does not expose microphone capture.');
  }
  if (pendingMicStream?.active) return pendingMicStream;
  setVoiceState('arming', 'Starting');
  pendingMicStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: true
    }
  });
  return pendingMicStream;
}

async function unlockPhoneAudio() {
  if (!voiceAudioEl) return;
  try {
    voiceAudioEl.muted = true;
    voiceAudioEl.src = SILENT_WAV_DATA_URL;
    const playPromise = Promise.resolve(voiceAudioEl.play()).catch(() => {});
    await Promise.race([playPromise, waitMs(AUDIO_UNLOCK_TIMEOUT_MS)]);
    voiceAudioEl.pause();
    voiceAudioEl.currentTime = 0;
  } catch {
    // iOS/Android may still accept later audio because this function runs inside
    // the user's tap handler. If the silent probe fails, the real playback path
    // will surface the actionable error.
  } finally {
    voiceAudioEl.muted = false;
    voiceAudioEl.removeAttribute('src');
    voiceAudioEl.load?.();
  }
}

async function playBase64Audio(base64, contentType = 'audio/wav', detail = 'Speaking') {
  if (!base64 || !voiceAudioEl || !modeEnabled) return;
  if (activeAudioObjectUrl) {
    URL.revokeObjectURL(activeAudioObjectUrl);
    activeAudioObjectUrl = '';
  }
  const blob = base64ToBlob(base64, contentType || 'audio/wav');
  activeAudioObjectUrl = URL.createObjectURL(blob);
  setVoiceState('speaking', detail);
  voiceAudioEl.src = activeAudioObjectUrl;
  voiceAudioEl.currentTime = 0;
  await new Promise((resolve, reject) => {
    const cleanup = () => {
      voiceAudioEl.removeEventListener('ended', onEnded);
      voiceAudioEl.removeEventListener('error', onError);
    };
    const onEnded = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error('Phone audio playback failed.'));
    };
    voiceAudioEl.addEventListener('ended', onEnded, { once: true });
    voiceAudioEl.addEventListener('error', onError, { once: true });
    voiceAudioEl.play().catch((error) => {
      cleanup();
      reject(error);
    });
  });
  if (activeAudioObjectUrl) {
    URL.revokeObjectURL(activeAudioObjectUrl);
    activeAudioObjectUrl = '';
  }
}

function handleAudioChunk(event) {
  const samples = event?.samples;
  if (!samples?.length) return;
  if (turnInFlight && !recording) return;
  const level = rms(samples);
  const now = Date.now();
  rememberRingChunk(samples);

  if (!recording && modeEnabled && !turnInFlight && level >= voiceConfig.silenceRms && now - lastMicActivityUiAt > 700) {
    lastMicActivityUiAt = now;
    setVoiceState('listening', 'Listening');
    if (!reportedMicAudio) {
      reportedMicAudio = true;
      reportVoiceClientEvent('warn', `mic audio detected rms=${level.toFixed(4)}`, 'audio heartbeat');
    }
  }

  if (!recording) return;

  const copy = samples instanceof Float32Array ? new Float32Array(samples) : Float32Array.from(samples);
  recording.chunks.push(copy);
  recording.sampleCount += copy.length;
  if (level >= voiceConfig.silenceRms) recording.lastVoiceAt = now;

  const elapsedMs = Math.round(recording.sampleCount / recording.sampleRate * 1000);
  if (now - lastRecordingUiAt > 350) {
    lastRecordingUiAt = now;
    setVoiceState('recording', 'Recording');
  }

  const quietForMs = now - recording.lastVoiceAt;
  const canStopForSilence = elapsedMs >= voiceConfig.minMs && quietForMs >= voiceConfig.silenceMs;
  const hitMax = elapsedMs >= voiceConfig.maxMs;
  if ((canStopForSilence || hitMax) && !recording.finalizing) {
    recording.finalizing = true;
    void finalizeRecording(hitMax ? 'max-duration' : 'silence');
  }
}

function handleWakeScore(event = {}) {
  if (!modeEnabled || turnInFlight || recording) return;
  const score = Number(event.score || 0);
  if (!Number.isFinite(score)) return;
  bestWakeScore = Math.max(bestWakeScore, score);
  const now = Date.now();
  if (score >= 0.18 && now - lastWakeScoreUiAt > 450) {
    lastWakeScoreUiAt = now;
    setVoiceState('listening', 'Listening');
  }
  if (score >= Math.max(0.2, voiceConfig.threshold - 0.08) && now - lastWakeScoreReportAt > 1500) {
    lastWakeScoreReportAt = now;
    reportVoiceClientEvent('warn', `wake score ${score.toFixed(3)} threshold=${voiceConfig.threshold.toFixed(3)}`, event.isSpeechActive ? 'speech active' : 'speech inactive');
  }
}

function handleWakeDetected(event = {}) {
  if (!modeEnabled || turnInFlight || recording) return;
  const score = Number(event.score || 0);
  recording = {
    chunks: ringChunks.map((chunk) => new Float32Array(chunk)),
    sampleRate: VOICE_SAMPLE_RATE,
    sampleCount: ringSampleCount,
    startedAt: Date.now(),
    lastVoiceAt: Date.now(),
    finalizing: false,
    wakeScore: Number.isFinite(score) ? score : 0
  };
  lastRecordingUiAt = 0;
  wakeEngine?.setDetectionPaused?.(true);
  reportVoiceClientEvent('warn', `wake detected score=${recording.wakeScore.toFixed(3)}`, event.isSpeechActive ? 'speech active' : 'speech inactive');
  setVoiceState('wake', 'Wake detected');
}

async function finalizeRecording(reason) {
  const current = recording;
  recording = null;
  if (!current || turnInFlight) return;
  turnInFlight = true;
  setVoiceState('processing', 'Thinking');

  try {
    wakeEngine?.setDetectionPaused?.(true);
    const samples = flattenChunks(current.chunks);
    const durationMs = samples.length / current.sampleRate * 1000;
    if (durationMs < 500) throw new Error('No usable speech was captured.');
    const wavBlob = wavBlobFromFloat32(samples, current.sampleRate);
    const turn = await submitDashboardVoiceTurn(wavBlob, { durationMs, reason, wakeScore: current.wakeScore });
    await handleTurnResponse(turn);
  } catch (error) {
    console.error('[dashboard-voice] turn failed', error);
    const message = normalizeVoiceError(error, 'Voice turn failed');
    reportVoiceClientEvent('error', message, 'turn failed');
    setVoiceState('error', shortText(message, 86));
    await waitMs(1800);
  } finally {
    turnInFlight = false;
    ringChunks = [];
    ringSampleCount = 0;
    if (modeEnabled) {
      if (wakeEngine) {
        wakeEngine.setDetectionPaused?.(false, { reset: true });
        setVoiceState('listening', 'Listening');
      } else {
        await startWakeListening().catch((error) => {
          modeEnabled = false;
          setVoiceState('error', shortText(error?.message || 'Wake restart failed', 86));
        });
      }
    } else {
      setVoiceState('off');
    }
  }
}

async function submitDashboardVoiceTurn(wavBlob, meta = {}) {
  setVoiceState('processing', 'Thinking');
  const response = await fetch('/api/jarvis/dashboard-voice/turn', {
    method: 'POST',
    headers: {
      'content-type': 'audio/wav',
      'x-jarvis-dashboard-voice-source': 'dashboard-phone',
      'x-jarvis-dashboard-voice-duration-ms': String(Math.round(meta.durationMs || 0)),
      'x-jarvis-dashboard-voice-wake-score': String(meta.wakeScore || 0)
    },
    body: wavBlob,
    cache: 'no-store'
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Dashboard voice HTTP ${response.status}`);
  }
  return payload;
}

async function handleTurnResponse(turn) {
  if (turn.transcript) {
    setVoiceState('processing', 'Thinking');
  }

  let finalPromise = Promise.resolve(turn);
  if (turn.pending && turn.turnId) {
    finalPromise = pollTurnResult(turn.turnId, turn.pollAfterSeconds);
  }

  if (turn.audioWavBase64) {
    await playBase64Audio(turn.audioWavBase64, turn.audioContentType, 'Speaking');
  }

  const final = await finalPromise;
  if (!final || final.pending) throw new Error('Dashboard voice turn did not finish.');
  if (final.ok === false) throw new Error(final.error || 'Dashboard voice turn failed.');
  if (final.audioWavBase64) {
    await playBase64Audio(final.audioWavBase64, final.audioContentType, 'Speaking');
  } else if (final.replyText) {
    setVoiceState('speaking', 'Speaking');
    await waitMs(1400);
  } else if (final.accepted === false) {
    setVoiceState('error', shortText(final.reason || 'No response audio produced', 86));
    await waitMs(1400);
  }
}

async function pollTurnResult(turnId, firstDelaySeconds = 0.35) {
  const deadline = Date.now() + 120_000;
  let delaySeconds = clampNumber(firstDelaySeconds, 0.05, 3, 0.35);
  while (Date.now() < deadline && modeEnabled) {
    await waitMs(delaySeconds * 1000);
    const response = await fetch(`/api/jarvis/dashboard-voice/turn-result?id=${encodeURIComponent(turnId)}`, { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `Turn poll HTTP ${response.status}`);
    if (!payload.pending) return payload;
    setVoiceState('processing', 'Thinking');
    delaySeconds = clampNumber(payload.pollAfterSeconds, 0.1, 3, 0.5);
  }
  throw new Error('Timed out waiting for JARVIS response.');
}

async function startWakeListening() {
  if (!voiceCard || !modeEnabled) return null;
  if (wakeEngine) {
    setVoiceState('listening');
    return wakeEngine;
  }
  if (wakeStartPromise) return wakeStartPromise;

  wakeStartPromise = (async () => {
    if (!window.isSecureContext) {
      throw new Error('Microphone requires HTTPS or a trusted local origin.');
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('This browser does not expose microphone capture.');
    }
    if (!window.AudioWorkletNode) {
      throw new Error('AudioWorklet is required for wake-word mode.');
    }
    if (!window.crossOriginIsolated) {
      throw new Error('Wake model requires a secure isolated page. Hard refresh the dashboard.');
    }

    setVoiceState('arming', 'Starting');
    const engine = new WakeWordEngine({
      baseAssetUrl: '/vendor/openwakeword/models',
      ortWasmPath: '/vendor/onnxruntime-web/',
      keywords: ['hey_jarvis'],
      detectionThreshold: voiceConfig.threshold,
      cooldownMs: 3500,
      useVad: false,
      debug: voiceConfig.debug
    });

    wakeUnsubscribers = [
      engine.on('ready', () => setVoiceState('arming', 'Starting')),
      engine.on('started', (runtime = {}) => {
        if (!reportedWakeRuntime) {
          reportedWakeRuntime = true;
          reportVoiceClientEvent('warn', `wake runtime ready context=${runtime.audioContextSampleRate || 0} source=${runtime.sourceSampleRate || 0} target=${runtime.targetSampleRate || 0}`, runtime.state || 'started');
        }
      }),
      engine.on('speech-start', () => {
        if (modeEnabled && !recording && !turnInFlight) setVoiceState('listening', 'Listening');
      }),
      engine.on('speech-end', () => {
        if (modeEnabled && !recording && !turnInFlight) setVoiceState('listening');
      }),
      engine.on('score', handleWakeScore),
      engine.on('detect', handleWakeDetected),
      engine.on('audio-chunk', handleAudioChunk),
      engine.on('error', (error) => {
        console.error('[dashboard-voice] wake engine error', error);
        const message = normalizeVoiceError(error, 'Wake engine error');
        reportVoiceClientEvent('error', message, 'wake engine error');
        if (modeEnabled) setVoiceState('error', shortText(message, 86));
      })
    ];

    const wakeLoadStartedAt = performance.now();
    await engine.load();
    reportVoiceClientEvent('warn', `wake model loaded ${Math.round(performance.now() - wakeLoadStartedAt)}ms`, 'startup timing');
    if (!modeEnabled) {
      for (const unsubscribe of wakeUnsubscribers) unsubscribe?.();
      wakeUnsubscribers = [];
      stopPendingMicStream();
      return null;
    }
    const mediaStream = pendingMicStream;
    pendingMicStream = null;
    const wakeStartStartedAt = performance.now();
    await engine.start({ gain: voiceConfig.gain, mediaStream });
    reportVoiceClientEvent('warn', `wake audio started ${Math.round(performance.now() - wakeStartStartedAt)}ms`, 'startup timing');
    wakeEngine = engine;
    ringChunks = [];
    ringSampleCount = 0;
    bestWakeScore = 0;
    lastMicActivityUiAt = 0;
    lastWakeScoreUiAt = 0;
    lastWakeScoreReportAt = 0;
    setVoiceState('listening', 'Listening');
    return engine;
  })().finally(() => {
    wakeStartPromise = null;
  });

  return wakeStartPromise;
}

async function stopWakeListening({ keepEnabled = false } = {}) {
  const engine = wakeEngine;
  wakeEngine = null;
  for (const unsubscribe of wakeUnsubscribers) unsubscribe?.();
  wakeUnsubscribers = [];
  if (engine) await engine.stop().catch(() => {});
  if (!keepEnabled) {
    ringChunks = [];
    ringSampleCount = 0;
  }
  stopPendingMicStream();
  bestWakeScore = 0;
}

async function armVoiceMode({ auto = false } = {}) {
  if (!voiceCard || modeEnabled) return;
  modeEnabled = true;
  setVoiceState('arming', 'Starting');
  try {
    const micPromise = requestPhoneMicStream();
    void unlockPhoneAudio();
    await micPromise;
    await startWakeListening();
    if (auto) reportVoiceClientEvent('warn', 'voice auto-armed', 'dashboard load');
  } catch (error) {
    console.error('[dashboard-voice] failed to arm', error);
    const message = normalizeVoiceError(error, 'Could not arm dashboard voice');
    reportVoiceClientEvent('error', message, auto ? 'auto-arm failed' : 'failed to arm');
    modeEnabled = false;
    await stopWakeListening();
    stopPendingMicStream();
    setVoiceState('error', shortText(message, 86));
  }
}

async function toggleVoiceMode() {
  if (!voiceCard) return;
  if (modeEnabled) {
    modeEnabled = false;
    recording = null;
    await stopWakeListening();
    if (voiceAudioEl) {
      voiceAudioEl.pause();
      voiceAudioEl.removeAttribute('src');
      voiceAudioEl.load?.();
    }
    setVoiceState('off');
    return;
  }

  await armVoiceMode();
}

voiceCard?.addEventListener('click', () => {
  void toggleVoiceMode();
});

window.addEventListener('pagehide', () => {
  modeEnabled = false;
  stopPendingMicStream();
  void stopWakeListening();
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden || !modeEnabled || turnInFlight || recording) return;
  if (!wakeEngine && !wakeStartPromise) void startWakeListening();
});

setVoiceState(window.isSecureContext ? 'off' : 'error', window.isSecureContext ? 'Starting' : 'Secure origin required');

if (voiceConfig.autoArm && window.isSecureContext) {
  window.setTimeout(() => {
    if (!document.hidden && !modeEnabled) void armVoiceMode({ auto: true });
  }, 350);
}
