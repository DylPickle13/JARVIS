import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawn, type ChildProcess } from "node:child_process";
import { Buffer } from "node:buffer";
import { envValue, findAncestorFile, parseDotEnv } from "./lib/env";

const STATUS_ID = "live-dictation";
const DEFAULT_OMLX_BASE_URL = "http://192.168.21.30:8000";
const DEFAULT_OMLX_MODEL = "whisper-large-v3-turbo-asr-4bit";
const DEFAULT_INPUT_DEVICE = "PowerConf";
const DEFAULT_FFMPEG = "/opt/homebrew/bin/ffmpeg";
const SAMPLE_RATE = 16_000;
const CHANNELS = 1;
const BITS_PER_SAMPLE = 16;
const BYTES_PER_SAMPLE = BITS_PER_SAMPLE / 8;
const PREVIEW_INTERVAL_MS = 1_200;
const DUPLICATE_F1_GUARD_MS = 600;
const PREVIEW_TIMEOUT_MS = 30_000;
const FINAL_TIMEOUT_MS = 90_000;
const MIN_AUDIO_MS = 600;
const MIN_RMS_DBFS = -50;

interface DictationConfig {
  apiKey: string;
  baseUrl: string;
  ffmpeg: string;
  inputDevice: string;
  language: string;
  model: string;
  previewIntervalMs: number;
}

interface ActiveDictation {
  audioChunks: Buffer[];
  audioBytes: number;
  baseEditorText: string;
  config: DictationConfig;
  context: ExtensionContext;
  ffmpeg: ChildProcess;
  ffmpegError: string;
  ffmpegExited: Promise<void>;
  lastTranscript: string;
  peak: number;
  previewAbort?: AbortController;
  previewInFlight?: Promise<void>;
  previewPending: boolean;
  sampleCarry?: number;
  sampleCount: number;
  startedAt: number;
  stopping: boolean;
  sumSquares: number;
  timer: ReturnType<typeof setInterval>;
}

function positiveInteger(raw: string, fallback: number): number {
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "").replace(/\/v1$/i, "");
}

function resolveConfig(cwd: string): DictationConfig {
  const dotenv = parseDotEnv(findAncestorFile(cwd, ".env"));
  return {
    apiKey: envValue("PI_DICTATE_OMLX_API_KEY", cwd, dotenv) || envValue("OMLX_API_KEY", cwd, dotenv) || "local",
    baseUrl: normalizeBaseUrl(
      envValue("PI_DICTATE_OMLX_BASE_URL", cwd, dotenv) ||
        envValue("OMLX_BASE_URL", cwd, dotenv) ||
        envValue("DISCORD_VOICE_BASE_URL", cwd, dotenv) ||
        DEFAULT_OMLX_BASE_URL,
    ),
    ffmpeg: envValue("PI_DICTATE_FFMPEG", cwd, dotenv) || DEFAULT_FFMPEG,
    inputDevice: envValue("PI_DICTATE_INPUT_DEVICE", cwd, dotenv) || DEFAULT_INPUT_DEVICE,
    language: envValue("PI_DICTATE_LANGUAGE", cwd, dotenv) || "en",
    model: envValue("PI_DICTATE_OMLX_MODEL", cwd, dotenv) || DEFAULT_OMLX_MODEL,
    previewIntervalMs: positiveInteger(envValue("PI_DICTATE_PREVIEW_INTERVAL_MS", cwd, dotenv), PREVIEW_INTERVAL_MS),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function normalizeTranscript(raw: string): string {
  return raw.replace(/\r\n/g, "\n").replace(/\s+/g, " ").trim();
}

function renderEditorText(base: string, transcript: string): string {
  if (!transcript) return base;
  if (!base || /\s$/.test(base)) return `${base}${transcript}`;
  return `${base} ${transcript}`;
}

function pcmToWav(pcm: Buffer): Buffer {
  const header = Buffer.alloc(44);
  const byteRate = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE;
  const blockAlign = CHANNELS * BYTES_PER_SAMPLE;

  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8, "ascii");
  header.write("fmt ", 12, "ascii");
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(CHANNELS, 22);
  header.writeUInt32LE(SAMPLE_RATE, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(BITS_PER_SAMPLE, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

function appendAudio(session: ActiveDictation, chunk: Buffer): void {
  if (!chunk.length) return;
  session.audioChunks.push(Buffer.from(chunk));
  session.audioBytes += chunk.length;

  let offset = 0;
  if (session.sampleCarry !== undefined) {
    const sample = (session.sampleCarry | (chunk[0] << 8)) << 16 >> 16;
    const normalized = sample / 32768;
    session.sumSquares += normalized * normalized;
    session.peak = Math.max(session.peak, Math.abs(normalized));
    session.sampleCount += 1;
    session.sampleCarry = undefined;
    offset = 1;
  }

  for (; offset + 1 < chunk.length; offset += 2) {
    const sample = chunk.readInt16LE(offset) / 32768;
    session.sumSquares += sample * sample;
    session.peak = Math.max(session.peak, Math.abs(sample));
    session.sampleCount += 1;
  }
  if (offset < chunk.length) session.sampleCarry = chunk[offset];
}

function audioDurationMs(session: ActiveDictation): number {
  return (session.sampleCount / SAMPLE_RATE) * 1000;
}

function rmsDbfs(session: ActiveDictation): number {
  if (!session.sampleCount) return Number.NEGATIVE_INFINITY;
  const rms = Math.sqrt(session.sumSquares / session.sampleCount);
  return 20 * Math.log10(Math.max(rms, 1e-12));
}

function peakDbfs(session: ActiveDictation): number {
  return 20 * Math.log10(Math.max(session.peak, 1e-12));
}

function hasSpeechLevel(session: ActiveDictation): boolean {
  return audioDurationMs(session) >= MIN_AUDIO_MS && rmsDbfs(session) >= MIN_RMS_DBFS;
}

function snapshotPcm(session: ActiveDictation): Buffer {
  return Buffer.concat(session.audioChunks, session.audioBytes - (session.audioBytes % BYTES_PER_SAMPLE));
}

async function transcribeAudio(
  pcm: Buffer,
  config: DictationConfig,
  timeoutMs: number,
  controller: AbortController,
): Promise<string> {
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const wav = pcmToWav(pcm);
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array(wav)], { type: "audio/wav" }), "dictation.wav");
    form.append("model", config.model);
    form.append("language", config.language);
    form.append("response_format", "json");

    const response = await fetch(`${config.baseUrl}/v1/audio/transcriptions`, {
      method: "POST",
      headers: config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : undefined,
      body: form,
      signal: controller.signal,
    });
    const raw = await response.text();
    if (!response.ok) throw new Error(`oMLX transcription failed (${response.status}): ${raw.slice(0, 500)}`);

    let payload: any;
    try {
      payload = JSON.parse(raw);
    } catch {
      throw new Error(`oMLX transcription returned invalid JSON: ${raw.slice(0, 500)}`);
    }
    return normalizeTranscript(typeof payload?.text === "string" ? payload.text : "");
  } finally {
    clearTimeout(timeout);
  }
}

function applyTranscript(session: ActiveDictation, transcript: string): void {
  if (!transcript || transcript === session.lastTranscript) return;
  session.lastTranscript = transcript;
  session.context.ui.setEditorText(renderEditorText(session.baseEditorText, transcript));
}

function setListeningStatus(session: ActiveDictation): void {
  session.context.ui.setStatus(STATUS_ID, session.context.ui.theme.fg("accent", "🎙 listening · live"));
}

async function requestPreview(session: ActiveDictation): Promise<void> {
  if (session.stopping || !hasSpeechLevel(session)) return;
  if (session.previewInFlight) {
    session.previewPending = true;
    return;
  }

  session.previewPending = false;
  const pcm = snapshotPcm(session);
  const controller = new AbortController();
  session.previewAbort = controller;
  session.context.ui.setStatus(STATUS_ID, session.context.ui.theme.fg("accent", "🎙 listening · transcribing"));

  const request = (async () => {
    try {
      const transcript = await transcribeAudio(pcm, session.config, PREVIEW_TIMEOUT_MS, controller);
      if (!session.stopping) applyTranscript(session, transcript);
    } catch (error) {
      if (!isAbortError(error) && !session.stopping) {
        session.context.ui.setStatus(STATUS_ID, session.context.ui.theme.fg("warning", "🎙 listening · oMLX retry"));
      }
    } finally {
      if (session.previewAbort === controller) session.previewAbort = undefined;
      if (!session.stopping) setListeningStatus(session);
    }
  })();

  session.previewInFlight = request;
  await request;
  if (session.previewInFlight === request) session.previewInFlight = undefined;

  if (session.previewPending && !session.stopping) {
    session.previewPending = false;
    void requestPreview(session);
  }
}

function recorderArgs(inputDevice: string): string[] {
  return [
    "-hide_banner",
    "-loglevel",
    "error",
    "-f",
    "avfoundation",
    "-i",
    `:${inputDevice}`,
    "-vn",
    "-ac",
    String(CHANNELS),
    "-ar",
    String(SAMPLE_RATE),
    "-acodec",
    "pcm_s16le",
    "-f",
    "s16le",
    "pipe:1",
  ];
}

async function waitForSpawn(child: ChildProcess): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const onSpawn = () => {
      cleanup();
      resolve();
    };
    const onError = (error: Error) => {
      cleanup();
      reject(error);
    };
    const cleanup = () => {
      child.off("spawn", onSpawn);
      child.off("error", onError);
    };
    child.once("spawn", onSpawn);
    child.once("error", onError);
  });
}

function waitForExit(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => child.once("exit", () => resolve()));
}

async function stopRecorder(session: ActiveDictation): Promise<void> {
  if (session.ffmpeg.exitCode === null && session.ffmpeg.signalCode === null) session.ffmpeg.kill("SIGINT");
  await Promise.race([
    session.ffmpegExited,
    new Promise<void>((resolve) => setTimeout(resolve, 2_000)),
  ]);
  if (session.ffmpeg.exitCode === null && session.ffmpeg.signalCode === null) {
    session.ffmpeg.kill("SIGTERM");
    await session.ffmpegExited;
  }
}

export default function registerLiveDictation(pi: ExtensionAPI): void {
  let active: ActiveDictation | undefined;
  let starting = false;

  function cleanup(session: ActiveDictation): void {
    clearInterval(session.timer);
    session.previewAbort?.abort();
    if (session.ffmpeg.exitCode === null && session.ffmpeg.signalCode === null) session.ffmpeg.kill("SIGTERM");
    if (active === session) active = undefined;
    session.context.ui.setStatus(STATUS_ID, undefined);
  }

  async function start(ctx: ExtensionContext): Promise<void> {
    if (process.platform !== "darwin") {
      ctx.ui.notify("PowerConf live dictation is available only on macOS.", "error");
      return;
    }

    const config = resolveConfig(ctx.cwd);
    const child = spawn(config.ffmpeg, recorderArgs(config.inputDevice), {
      stdio: ["ignore", "pipe", "pipe"],
    });

    try {
      await waitForSpawn(child);
    } catch (error) {
      ctx.ui.notify(`Could not start microphone capture: ${errorMessage(error)}`, "error");
      return;
    }

    let resolveExited!: () => void;
    const ffmpegExited = new Promise<void>((resolve) => {
      resolveExited = resolve;
    });
    const session: ActiveDictation = {
      audioChunks: [],
      audioBytes: 0,
      baseEditorText: ctx.ui.getEditorText(),
      config,
      context: ctx,
      ffmpeg: child,
      ffmpegError: "",
      ffmpegExited,
      lastTranscript: "",
      peak: 0,
      previewPending: false,
      sampleCount: 0,
      startedAt: Date.now(),
      stopping: false,
      sumSquares: 0,
      timer: undefined as unknown as ReturnType<typeof setInterval>,
    };
    active = session;

    child.stdout?.on("data", (chunk: Buffer) => appendAudio(session, chunk));
    child.stderr?.on("data", (chunk: Buffer) => {
      session.ffmpegError = `${session.ffmpegError}${chunk.toString("utf8")}`.slice(-2_000);
    });
    child.once("exit", () => {
      resolveExited();
      if (active === session && !session.stopping) {
        const details = session.ffmpegError.trim() || "microphone recorder exited unexpectedly";
        cleanup(session);
        ctx.ui.notify(`Dictation stopped: ${details}`, "error");
      }
    });

    if (child.exitCode !== null || child.signalCode !== null) {
      resolveExited();
      const details = session.ffmpegError.trim() || "microphone recorder exited before capture started";
      cleanup(session);
      ctx.ui.notify(`Dictation stopped: ${details}`, "error");
      return;
    }

    session.timer = setInterval(() => void requestPreview(session), config.previewIntervalMs);
    setListeningStatus(session);
  }

  async function stop(session: ActiveDictation): Promise<void> {
    session.stopping = true;
    clearInterval(session.timer);
    session.previewAbort?.abort();
    session.context.ui.setStatus(STATUS_ID, session.context.ui.theme.fg("accent", "🎙 finalizing"));

    try {
      await stopRecorder(session);
      await session.previewInFlight;

      if (!hasSpeechLevel(session)) {
        session.context.ui.notify(
          `No speech detected (RMS ${rmsDbfs(session).toFixed(1)} dBFS, peak ${peakDbfs(session).toFixed(1)} dBFS).`,
          "warning",
        );
        return;
      }

      const controller = new AbortController();
      session.previewAbort = controller;
      const transcript = await transcribeAudio(snapshotPcm(session), session.config, FINAL_TIMEOUT_MS, controller);
      if (!transcript) {
        session.context.ui.notify("No speech was recognized.", "warning");
        return;
      }
      applyTranscript(session, transcript);
    } catch (error) {
      if (!isAbortError(error)) session.context.ui.notify(`Dictation failed: ${errorMessage(error)}`, "error");
    } finally {
      cleanup(session);
    }
  }

  pi.registerShortcut("f1", {
    description: "Start or finish live PowerConf dictation through oMLX Whisper",
    handler: async (ctx) => {
      if (!active) {
        if (starting) return;
        starting = true;
        try {
          await start(ctx);
        } finally {
          starting = false;
        }
        return;
      }
      if (Date.now() - active.startedAt < DUPLICATE_F1_GUARD_MS) return;
      await stop(active);
    },
  });

  pi.on("session_shutdown", async () => {
    if (!active) return;
    const session = active;
    session.stopping = true;
    cleanup(session);
    await waitForExit(session.ffmpeg);
  });
}
