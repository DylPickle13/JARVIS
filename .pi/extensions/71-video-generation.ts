import { copyFileSync, existsSync, mkdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, extname, join, resolve, sep } from "node:path";
import { randomUUID } from "node:crypto";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type VideoAspectRatio = "16:9" | "9:16" | "1:1" | "4:3" | "3:4";
type VideoSizePreset = "small" | "standard" | "large";
type VideoPipeline = "distilled" | "two-stage" | "two-stages-hq" | "one-stage";

type GenerateVideoParams = {
  prompt: string;
  negativePrompt?: string;
  aspectRatio?: VideoAspectRatio;
  size?: VideoSizePreset;
  seconds?: number;
  durationSeconds?: number;
  fps?: number;
  steps?: number;
  cfgScale?: number;
  guidance?: number; // legacy alias for cfgScale
  pipeline?: VideoPipeline;
  lowRam?: boolean;
  enhancePrompt?: boolean;
  seed?: number;
  inputImagePath?: string;
  filename?: string;
  timeoutSeconds?: number;
};

type WorkerVideoResult = {
  ok?: boolean;
  error?: string;
  model?: string;
  jobId?: string;
  width?: number;
  height?: number;
  aspectRatio?: VideoAspectRatio;
  size?: VideoSizePreset;
  frames?: number;
  fps?: number;
  durationSeconds?: number;
  steps?: number;
  cfgScale?: number;
  guidance?: number; // legacy alias for cfgScale
  pipeline?: VideoPipeline;
  lowRam?: boolean;
  enhancePrompt?: boolean;
  supportsAudio?: boolean;
  hasAudio?: boolean;
  audioSampleRate?: number;
  audioChannels?: string;
  seed?: number;
  mode?: "text-to-video" | "image-to-video" | "text-to-audio-video" | "image-to-audio-video";
  elapsedSeconds?: number;
  workerPath?: string;
  metadataPath?: string | null;
  sizeBytes?: number;
  stdoutTail?: string;
  stderrTail?: string;
  stage?: string;
  downloadCommand?: string;
};

type RenderState = {
  startedAt?: number;
  endedAt?: number;
  interval?: ReturnType<typeof setInterval>;
};

const VIDEO_MODEL = "dgrauet/ltx-2.3-mlx-q8";
const MACHINE_NAME = "mac-mini-64";
const DEFAULT_ASPECT_RATIO: VideoAspectRatio = "16:9";
const DEFAULT_SIZE: VideoSizePreset = "standard";
const DEFAULT_DURATION_SECONDS = 4;
const DEFAULT_FPS = 24;
const LTX_FRAME_COUNTS = [33, 65, 97, 129] as const;
const MAX_INTERNAL_FRAMES = 129;
const DEFAULT_STEPS = 30;
const DEFAULT_CFG_SCALE = 3;
const DEFAULT_PIPELINE: VideoPipeline = "two-stage";
const DEFAULT_LOW_RAM = true;
const DEFAULT_TIMEOUT_SECONDS = 10800;
const DEFAULT_MAX_INPUT_IMAGE_BYTES = 50 * 1024 * 1024;
const MAX_INPUT_IMAGE_BYTES = positiveInteger(process.env.VIDEO_GENERATION_MAX_INPUT_IMAGE_BYTES, DEFAULT_MAX_INPUT_IMAGE_BYTES);
const LOCAL_OUTPUT_DIR = process.env.VIDEO_GENERATION_LOCAL_OUTPUT_DIR || "generated-videos";
const INPUT_IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".bmp"]);
const ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"] as const;
const SIZE_PRESETS = ["small", "standard", "large"] as const;
const DIMENSION_PRESETS: Record<VideoSizePreset, Record<VideoAspectRatio, { width: number; height: number }>> = {
  small: {
    "16:9": { width: 512, height: 320 },
    "9:16": { width: 320, height: 512 },
    "1:1": { width: 384, height: 384 },
    "4:3": { width: 512, height: 384 },
    "3:4": { width: 384, height: 512 },
  },
  standard: {
    "16:9": { width: 768, height: 448 },
    "9:16": { width: 448, height: 768 },
    "1:1": { width: 512, height: 512 },
    "4:3": { width: 768, height: 576 },
    "3:4": { width: 576, height: 768 },
  },
  large: {
    "16:9": { width: 1024, height: 576 },
    "9:16": { width: 576, height: 1024 },
    "1:1": { width: 704, height: 704 },
    "4:3": { width: 1024, height: 768 },
    "3:4": { width: 768, height: 1024 },
  },
};

function cleanString(value: unknown): string {
  return String(value ?? "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanPrompt(value: unknown): string {
  return String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .trim();
}

function cleanPath(value: unknown): string {
  return String(value ?? "")
    .replace(/[\u0000-\u001F\u007F]/g, "")
    .trim();
}

function positiveInteger(value: unknown, fallback: number): number {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.round(parsed);
}

function optionalInteger(value: unknown, field: string, min: number, max: number): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${field} must be a finite number`);
  const rounded = Math.round(parsed);
  if (rounded < min || rounded > max) throw new Error(`${field} must be between ${min} and ${max}`);
  return rounded;
}

function optionalFloat(value: unknown, field: string, min: number, max: number): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${field} must be a finite number`);
  if (parsed < min || parsed > max) throw new Error(`${field} must be between ${min} and ${max}`);
  return parsed;
}

function parseAspectRatio(value: unknown): VideoAspectRatio {
  const candidate = cleanString(value || DEFAULT_ASPECT_RATIO) as VideoAspectRatio;
  if (!(ASPECT_RATIOS as readonly string[]).includes(candidate)) throw new Error(`aspectRatio must be one of: ${ASPECT_RATIOS.join(", ")}`);
  return candidate;
}

function parseSizePreset(value: unknown): VideoSizePreset {
  const candidate = cleanString(value || DEFAULT_SIZE).toLowerCase() as VideoSizePreset;
  if (!(SIZE_PRESETS as readonly string[]).includes(candidate)) throw new Error(`size must be one of: ${SIZE_PRESETS.join(", ")}`);
  return candidate;
}

function dimensionsFor(aspectRatio: VideoAspectRatio, size: VideoSizePreset): { width: number; height: number } {
  return DIMENSION_PRESETS[size][aspectRatio];
}

function nearestLtxFrameCount(target: number): number {
  const rounded = Math.round(target);
  return LTX_FRAME_COUNTS.reduce((best, candidate) => {
    const bestScore = Math.abs(best - rounded) + (best < rounded ? 0.1 : 0);
    const candidateScore = Math.abs(candidate - rounded) + (candidate < rounded ? 0.1 : 0);
    return candidateScore < bestScore ? candidate : best;
  }, LTX_FRAME_COUNTS[0]);
}

function parsePipeline(value: unknown): VideoPipeline {
  const candidate = cleanString(value || DEFAULT_PIPELINE).toLowerCase();
  const aliases: Record<string, VideoPipeline> = { quality: "two-stage", hq: "two-stages-hq", preview: "distilled", fast: "distilled", default: DEFAULT_PIPELINE };
  const resolved = (aliases[candidate] || candidate) as VideoPipeline;
  if (!["distilled", "two-stage", "two-stages-hq", "one-stage"].includes(resolved)) throw new Error("pipeline must be one of: distilled, two-stage, two-stages-hq, one-stage");
  return resolved;
}

function stringEnum(values: readonly string[], options?: Record<string, unknown>) {
  return Type.Union(values.map((value) => Type.Literal(value)) as any, options as any);
}

function expandLocalPath(value: string): string {
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return value;
}

function resolveInputImagePath(value: unknown, cwd: string): { path: string; sizeBytes: number; extension: string } | undefined {
  const requested = cleanPath(value);
  if (!requested) return undefined;
  const localPath = resolve(cwd, expandLocalPath(requested));
  if (!existsSync(localPath)) throw new Error(`inputImagePath does not exist: ${localPath}`);
  const stat = statSync(localPath);
  if (!stat.isFile()) throw new Error(`inputImagePath must be a file: ${localPath}`);
  if (stat.size > MAX_INPUT_IMAGE_BYTES) throw new Error(`inputImagePath is too large: ${formatBytes(stat.size)}; max ${formatBytes(MAX_INPUT_IMAGE_BYTES)}`);
  const extension = extname(localPath).toLowerCase();
  if (!INPUT_IMAGE_EXTENSIONS.has(extension)) throw new Error(`inputImagePath must be one of: ${[...INPUT_IMAGE_EXTENSIONS].join(", ")}`);
  return { path: localPath, sizeBytes: stat.size, extension };
}

function safeSlug(value: unknown, fallback: string): string {
  const slug = cleanString(value || fallback)
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "")
    .slice(0, 80);
  return slug || fallback;
}

function timestampSlug(): string {
  const date = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function localBaseDir(): string {
  const configured = cleanPath(process.env.MEDIA_GENERATION_DIR || process.env.VIDEO_GENERATION_DIR || process.env.IMAGE_GENERATION_DIR);
  return resolve(expandLocalPath(configured || join(homedir(), "media-generation")));
}

function videoWorkerPath(baseDir: string): string {
  return join(baseDir, "bin", "video-generate");
}

async function runLocalWorker(
  pi: ExtensionAPI,
  baseDir: string,
  args: string[],
  timeoutMs: number,
  signal?: AbortSignal,
  disableSync = false,
) {
  const executable = videoWorkerPath(baseDir);
  if (!existsSync(executable)) throw new Error(`Local video worker not found: ${executable}`);
  const envArgs = [
    `MEDIA_GENERATION_DIR=${baseDir}`,
    `IMAGE_GENERATION_DIR=${baseDir}`,
    ...(disableSync ? ["JARVIS_GENERATION_SYNC=0"] : []),
    executable,
    ...args,
  ];
  return pi.exec("/usr/bin/env", envArgs, { cwd: baseDir, timeout: timeoutMs, signal });
}

function parseWorkerResult(stdout: string, stderr: string, code: number): WorkerVideoResult {
  const lines = stdout.trim().split(/\n+/).filter(Boolean);
  const candidate = lines[lines.length - 1] || "";
  try {
    return JSON.parse(candidate) as WorkerVideoResult;
  } catch (error: any) {
    throw new Error(`Local video worker did not return JSON (exit ${code}). stdout=${stdout.slice(-2000)} stderr=${stderr.slice(-2000)} parse=${error.message}`);
  }
}

function formatBytes(bytes: number | undefined): string {
  if (!Number.isFinite(bytes)) return "unknown size";
  const units = ["B", "KB", "MB", "GB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function resultText(result: WorkerVideoResult, localPath: string, metadataLocalPath?: string, cleanedWorkerPaths: string[] = []): string {
  const modeLine = result.mode === "image-to-audio-video" ? "Mode: image-to-audio-video" : "Mode: text-to-audio-video";
  return [
    "Generated audio-video with local LTX-2.3 Q8 via MLX.",
    modeLine,
    `Local: ${localPath}`,
    result.workerPath ? `Worker staging source deleted after local copy: ${result.workerPath}` : undefined,
    metadataLocalPath ? `Metadata: ${metadataLocalPath}` : undefined,
    cleanedWorkerPaths.length > 0 ? `Local staging cleanup: deleted ${cleanedWorkerPaths.length} file(s).` : undefined,
    `Model: ${VIDEO_MODEL}`,
    result.pipeline ? `Pipeline: ${result.pipeline}` : undefined,
    result.aspectRatio ? `Aspect ratio: ${result.aspectRatio}${result.size ? ` (${result.size})` : ""}` : undefined,
    `Seed: ${result.seed ?? "unknown"}`,
    `Steps: ${result.steps ?? "unknown"}`,
    typeof result.cfgScale === "number" ? `CFG: ${result.cfgScale}` : undefined,
    `Frames/FPS: ${result.frames ?? "?"}/${result.fps ?? "?"}`,
    typeof result.durationSeconds === "number" ? `Duration: ${result.durationSeconds.toFixed(2)}s` : undefined,
    result.hasAudio ? `Audio: ${result.audioSampleRate ?? "?"} Hz ${result.audioChannels ?? ""}` : "Audio: not detected",
    `Size: ${result.width ?? "?"}x${result.height ?? "?"}, ${formatBytes(result.sizeBytes)}`,
    typeof result.elapsedSeconds === "number" ? `Elapsed: ${result.elapsedSeconds.toFixed(1)}s` : undefined,
  ].filter(Boolean).join("\n");
}

function safeLocalCleanupPaths(baseDir: string, paths: Array<string | undefined | null>): string[] {
  const normalizedBase = resolve(baseDir);
  const allowedPrefixes = ["outputs", "inputs", join("runtime", "pids")].map((part) => `${resolve(normalizedBase, part)}${sep}`);
  return [...new Set(paths
    .map((path) => cleanPath(path))
    .filter(Boolean)
    .map((path) => resolve(path))
    .filter((path) => allowedPrefixes.some((prefix) => path.startsWith(prefix))))];
}

function copyLocalOutput(source: string, destination: string): void {
  if (resolve(source) === resolve(destination)) throw new Error("Worker staging and final video paths must differ.");
  const temporary = `${destination}.${randomUUID().slice(0, 8)}.tmp`;
  try {
    copyFileSync(source, temporary);
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}

function cleanupLocalFiles(baseDir: string, paths: Array<string | undefined | null>): string[] {
  const safePaths = safeLocalCleanupPaths(baseDir, paths);
  for (const path of safePaths) rmSync(path, { force: true });
  return safePaths;
}

function localPidFile(baseDir: string, jobId: string): string {
  return join(baseDir, "runtime", "pids", `${jobId}.json`);
}

async function generateVideo(pi: ExtensionAPI, params: GenerateVideoParams, signal?: AbortSignal, onUpdate?: (partial: any) => void, cwd = process.cwd()) {
  const prompt = cleanPrompt(params.prompt);
  if (!prompt) throw new Error("generate_video requires a non-empty prompt.");
  const negativePrompt = cleanPrompt(params.negativePrompt || "");
  const aspectRatio = parseAspectRatio(params.aspectRatio);
  const sizePreset = parseSizePreset(params.size);
  const { width, height } = dimensionsFor(aspectRatio, sizePreset);
  const fps = optionalInteger(params.fps, "fps", 1, 24) ?? DEFAULT_FPS;
  const seconds = optionalFloat(params.seconds ?? params.durationSeconds, "seconds", 0.5, 5.375) ?? DEFAULT_DURATION_SECONDS;
  const requestedFrames = seconds * fps;
  if (requestedFrames > MAX_INTERNAL_FRAMES) {
    throw new Error(`seconds at ${fps} fps would require ${requestedFrames.toFixed(1)} frames; max is ${MAX_INTERNAL_FRAMES} frames (~${(MAX_INTERNAL_FRAMES / fps).toFixed(2)}s at ${fps} fps). Lower seconds or fps.`);
  }
  const frames = nearestLtxFrameCount(requestedFrames);
  const resolvedDurationSeconds = frames / fps;
  const steps = optionalInteger(params.steps, "steps", 1, 60) ?? DEFAULT_STEPS;
  const cfgScale = optionalFloat(params.cfgScale ?? params.guidance, "cfgScale", 0, 20) ?? DEFAULT_CFG_SCALE;
  const pipeline = parsePipeline(params.pipeline);
  const lowRam = params.lowRam !== false;
  const enhancePrompt = params.enhancePrompt === true;
  const seed = optionalInteger(params.seed, "seed", 0, 2_147_483_647);
  const timeoutSeconds = optionalInteger(params.timeoutSeconds, "timeoutSeconds", 60, 21600) ?? DEFAULT_TIMEOUT_SECONDS;
  const inputImage = resolveInputImagePath(params.inputImagePath, cwd);

  const baseDir = localBaseDir();
  const jobId = safeSlug(`vid-${timestampSlug()}-${randomUUID().slice(0, 8)}`, `vid-${Date.now()}`);
  const filename = safeSlug(params.filename, jobId).replace(/\.mp4$/i, "") + ".mp4";
  const localOutputDir = resolve(cwd, LOCAL_OUTPUT_DIR);
  const workerInputsDir = join(baseDir, "inputs");
  const workerJobFile = join(workerInputsDir, `${jobId}.json`);
  const workerInputImagePath = inputImage ? join(workerInputsDir, `${jobId}-input${inputImage.extension}`) : undefined;
  const expectedWorkerOutputPath = join(baseDir, "outputs", "videos", filename);
  const expectedWorkerMetadataPath = expectedWorkerOutputPath.replace(/\.mp4$/i, ".metadata.json");
  const cleanupPaths = [workerJobFile, workerInputImagePath, expectedWorkerOutputPath, expectedWorkerMetadataPath, localPidFile(baseDir, jobId)];
  mkdirSync(workerInputsDir, { recursive: true });
  mkdirSync(join(baseDir, "outputs", "videos"), { recursive: true });
  mkdirSync(localOutputDir, { recursive: true });

  const job = {
    jobId,
    filename,
    model: VIDEO_MODEL,
    prompt,
    negativePrompt,
    aspectRatio,
    size: sizePreset,
    seconds,
    fps,
    steps,
    cfgScale,
    pipeline,
    lowRam,
    enhancePrompt,
    seed,
    timeoutSeconds,
    ...(workerInputImagePath ? { inputImagePath: workerInputImagePath } : {}),
  };

  onUpdate?.({ content: [{ type: "text" as const, text: `Preparing local video job ${jobId} on ${MACHINE_NAME}...` }] });
  try {
    if (inputImage && workerInputImagePath) {
      onUpdate?.({ content: [{ type: "text" as const, text: `Staging source image locally (${formatBytes(inputImage.sizeBytes)})...` }] });
      copyFileSync(inputImage.path, workerInputImagePath);
    }
    writeFileSync(workerJobFile, JSON.stringify(job, null, 2), "utf8");
  } catch (error) {
    cleanupLocalFiles(baseDir, [workerJobFile, workerInputImagePath]);
    throw error;
  }

  const modeText = inputImage ? "image-to-audio-video" : "text-to-audio-video";
  onUpdate?.({ content: [{ type: "text" as const, text: `Generating locally with ${VIDEO_MODEL} (${width}x${height}, ${frames} frames @ ${fps} fps, ${steps} steps, ${pipeline}, ${modeText})...` }] });
  let workerResult: WorkerVideoResult | undefined;
  try {
    const generation = await runLocalWorker(pi, baseDir, ["--job-file", workerJobFile], (timeoutSeconds + 60) * 1000, signal, true);
    workerResult = parseWorkerResult(generation.stdout, generation.stderr, generation.code);
    if (generation.code !== 0 || generation.killed || workerResult.ok !== true) {
      throw new Error([
        `Local video generation failed on ${MACHINE_NAME}.`,
        workerResult.error ? `error: ${workerResult.error}` : undefined,
        workerResult.stage ? `stage: ${workerResult.stage}` : undefined,
        workerResult.downloadCommand ? `download: ${workerResult.downloadCommand}` : undefined,
        workerResult.stderrTail ? `stderr: ${workerResult.stderrTail}` : undefined,
        workerResult.stdoutTail ? `stdout: ${workerResult.stdoutTail}` : undefined,
        !workerResult.error && generation.stderr ? `worker stderr: ${generation.stderr}` : undefined,
      ].filter(Boolean).join("\n"));
    }

    const workerOutputPath = cleanPath(workerResult.workerPath);
    if (!workerOutputPath) throw new Error("Local video worker succeeded but did not return workerPath.");
    if (!safeLocalCleanupPaths(baseDir, [workerOutputPath]).includes(resolve(workerOutputPath))) {
      throw new Error(`Local video worker returned an unsafe output path: ${workerOutputPath}`);
    }
    if (!existsSync(workerOutputPath)) throw new Error(`Local video worker output is missing: ${workerOutputPath}`);

    const localPath = join(localOutputDir, basename(workerOutputPath));
    onUpdate?.({ content: [{ type: "text" as const, text: `Copying video locally to ${localPath}...` }] });
    copyLocalOutput(workerOutputPath, localPath);

    let metadataLocalPath: string | undefined;
    const workerMetadataPath = cleanPath(workerResult.metadataPath);
    if (workerMetadataPath && safeLocalCleanupPaths(baseDir, [workerMetadataPath]).includes(resolve(workerMetadataPath)) && existsSync(workerMetadataPath)) {
      metadataLocalPath = localPath.replace(/\.mp4$/i, ".metadata.json");
      try {
        copyLocalOutput(workerMetadataPath, metadataLocalPath);
      } catch {
        metadataLocalPath = undefined;
      }
    }

    const cleanedWorkerPaths = cleanupLocalFiles(baseDir, [workerOutputPath, workerMetadataPath, ...cleanupPaths]);
    const stat = statSync(localPath);
    return {
      content: [{ type: "text" as const, text: resultText(workerResult, localPath, metadataLocalPath, cleanedWorkerPaths) }],
      details: {
        ok: true,
        model: VIDEO_MODEL,
        machine: MACHINE_NAME,
        execution: "local",
        jobId,
        localPath,
        metadataLocalPath,
        worker: workerResult,
        inputImagePath: inputImage?.path,
        aspectRatio,
        size: sizePreset,
        frames,
        fps,
        durationSeconds: resolvedDurationSeconds,
        pipeline,
        cfgScale,
        hasAudio: workerResult.hasAudio,
        cleanedWorkerPaths,
        sizeBytes: stat.size,
      },
    };
  } catch (error) {
    cleanupLocalFiles(baseDir, [workerResult?.workerPath, workerResult?.metadataPath, ...cleanupPaths]);
    throw error;
  }
}

function formatDuration(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function elapsedFooter(state: RenderState, isPartial: boolean, theme: any): string {
  if (state.startedAt === undefined) return "";
  const label = isPartial ? "Elapsed" : "Took";
  const endTime = state.endedAt ?? Date.now();
  return theme.fg("muted", `${label} ${formatDuration(Math.max(0, endTime - state.startedAt))}`);
}

export default function registerVideoGeneration(pi: ExtensionAPI) {
  pi.registerTool({
    name: "generate_video",
    label: "Generate Video",
    description: `Generate exactly one short audio-video MP4 locally on mac-mini-64 using the approved headless LTX-2.3 Q8 MLX model ${VIDEO_MODEL}. No SSH, hosted models, alternate models, or fallbacks are used.`,
    parameters: Type.Object({
      prompt: Type.String({ description: "Detailed video prompt to render." }),
      negativePrompt: Type.Optional(Type.String({ description: "Legacy optional negative prompt; LTX worker currently ignores this field." })),
      aspectRatio: Type.Optional(stringEnum(ASPECT_RATIOS, { description: `Video aspect ratio. Default ${DEFAULT_ASPECT_RATIO}.` })),
      size: Type.Optional(stringEnum(SIZE_PRESETS, { description: `Output size preset. Default ${DEFAULT_SIZE}; small/standard are faster preview modes.` })),
      seconds: Type.Optional(Type.Number({ description: `Requested duration in seconds, 0.5-5.375. Default ${DEFAULT_DURATION_SECONDS}. The worker converts seconds to LTX frame counts 33/65/97/129; at 24 fps max is about 5.375 seconds.` })),
      fps: Type.Optional(Type.Number({ description: `Frames per second, 1-24. Default ${DEFAULT_FPS}.` })),
      steps: Type.Optional(Type.Number({ description: `Stage-1/one-stage inference steps, 1-60. Default ${DEFAULT_STEPS}.` })),
      pipeline: Type.Optional(stringEnum(["distilled", "two-stage", "two-stages-hq", "one-stage"], { description: `LTX pipeline. Default ${DEFAULT_PIPELINE}; distilled is fastest, two-stages-hq is slowest/highest quality.` })),
      cfgScale: Type.Optional(Type.Number({ description: `CFG scale, 0-20. Default ${DEFAULT_CFG_SCALE}.` })),
      lowRam: Type.Optional(Type.Boolean({ description: `Use ltx-2-mlx low-RAM block streaming. Default ${DEFAULT_LOW_RAM}.` })),
      enhancePrompt: Type.Optional(Type.Boolean({ description: "Use Gemma prompt enhancement before generation. Default false." })),
      seed: Type.Optional(Type.Number({ description: "Optional seed, 0-2147483647. If omitted, the local worker chooses a random seed." })),
      inputImagePath: Type.Optional(Type.String({ description: "Optional local source image for image-to-video. Supported: PNG, JPG/JPEG, WebP, BMP. A temporary local staging copy is deleted after generation." })),
      filename: Type.Optional(Type.String({ description: "Optional output filename stem or .mp4 filename. Sanitized." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: `Optional generation timeout, 60-21600 seconds. Default ${DEFAULT_TIMEOUT_SECONDS}.` })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      return generateVideo(pi, params as GenerateVideoParams, signal, onUpdate, ctx.cwd);
    },
    renderCall(args, theme, context) {
      const state = context.state as RenderState;
      if (context.executionStarted && state.startedAt === undefined) {
        state.startedAt = Date.now();
        state.endedAt = undefined;
      }
      const prompt = cleanString((args as any).prompt).slice(0, 90) || "...";
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(`${theme.fg("toolTitle", "generate_video")} ${theme.fg("muted", VIDEO_MODEL)} ${theme.fg("toolOutput", prompt)}`);
      return text;
    },
    renderResult(result, options, theme, context) {
      const state = context.state as RenderState;
      if (state.startedAt !== undefined && options.isPartial && !state.interval) {
        state.interval = setInterval(() => context.invalidate(), 1000);
      }
      if (!options.isPartial || context.isError) {
        state.endedAt ??= Date.now();
        if (state.interval) {
          clearInterval(state.interval);
          state.interval = undefined;
        }
      }
      const localPath = result.details?.localPath ? String(result.details.localPath) : "";
      const ok = result.details?.ok === true;
      const label = options.isPartial ? theme.fg("toolTitle", "generate_video") : ok ? theme.fg("success", "✓ generated video") : theme.fg("warning", "video generation");
      const footer = elapsedFooter(state, options.isPartial, theme);
      const lines = [label, localPath ? theme.fg("accent", localPath) : undefined, footer].filter(Boolean);
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(lines.join("\n"));
      return text;
    },
  });

  pi.registerCommand("video-health", {
    description: "Check the mac-mini-64 headless video generator health.",
    handler: async (_args, ctx) => {
      const result = await runLocalWorker(pi, localBaseDir(), ["--health"], 30_000, ctx.signal);
      if (result.code !== 0 || result.killed) throw new Error((result.stderr || result.stdout || "Local video health check failed").trim());
      ctx.ui.notify(result.stdout.trim() || "No health output", "info");
    },
  });

  pi.registerCommand("video-download-model", {
    description: "Download/cache the approved mac-mini-64 local video model.",
    handler: async (_args, ctx) => {
      const result = await runLocalWorker(pi, localBaseDir(), ["--download-model"], 7_500_000, ctx.signal);
      if (result.code !== 0 || result.killed) throw new Error((result.stderr || result.stdout || "Local video model download failed").trim());
      ctx.ui.notify(result.stdout.trim() || "No download output", "info");
    },
  });
}
