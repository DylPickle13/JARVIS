import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, extname, join, resolve, sep } from "node:path";
import { randomUUID } from "node:crypto";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type AspectRatio = "1:1" | "16:9" | "9:16" | "4:3" | "3:4" | "3:2" | "2:3" | "21:9";
type ImageSizePreset = "small" | "standard" | "large";

type GenerateImageParams = {
  prompt: string;
  negativePrompt?: string;
  aspectRatio?: AspectRatio;
  size?: ImageSizePreset;
  steps?: number;
  seed?: number;
  inputImagePath?: string;
  imageStrength?: number;
  filename?: string;
  timeoutSeconds?: number;
  inlineImage?: boolean;
};

type WorkerResult = {
  ok?: boolean;
  error?: string;
  model?: string;
  jobId?: string;
  prompt?: string;
  negativePrompt?: string;
  width?: number;
  height?: number;
  aspectRatio?: AspectRatio;
  size?: ImageSizePreset;
  steps?: number;
  seed?: number;
  mode?: "text-to-image" | "image-to-image";
  imageStrength?: number;
  elapsedSeconds?: number;
  workerPath?: string;
  metadataPath?: string | null;
  sizeBytes?: number;
  stdoutTail?: string;
  stderrTail?: string;
  stage?: string;
};

type RenderState = {
  startedAt?: number;
  endedAt?: number;
  interval?: ReturnType<typeof setInterval>;
};

const MODEL = "mlx-community/Qwen-Image-2512-8bit";
const MACHINE_NAME = "mac-mini-64";
const DEFAULT_NEGATIVE_PROMPT = "blurry, low quality, watermark, distorted, deformed";
const DEFAULT_ASPECT_RATIO: AspectRatio = "16:9";
const DEFAULT_SIZE: ImageSizePreset = "large";
const DEFAULT_STEPS = 30;
const DEFAULT_TIMEOUT_SECONDS = 1200;
const DEFAULT_IMAGE_STRENGTH = 0.4;
const DEFAULT_MAX_INLINE_BYTES = 8 * 1024 * 1024;
const MAX_INLINE_BYTES = positiveInteger(process.env.IMAGE_GENERATION_MAX_INLINE_BYTES, DEFAULT_MAX_INLINE_BYTES);
const DEFAULT_MAX_INPUT_IMAGE_BYTES = 50 * 1024 * 1024;
const MAX_INPUT_IMAGE_BYTES = positiveInteger(process.env.IMAGE_GENERATION_MAX_INPUT_IMAGE_BYTES, DEFAULT_MAX_INPUT_IMAGE_BYTES);
const LOCAL_OUTPUT_DIR = process.env.IMAGE_GENERATION_LOCAL_OUTPUT_DIR || "generated-images";
const INPUT_IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".bmp"]);
const ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"] as const;
const SIZE_PRESETS = ["small", "standard", "large"] as const;
const DIMENSION_PRESETS: Record<ImageSizePreset, Record<AspectRatio, { width: number; height: number }>> = {
  small: {
    "1:1": { width: 768, height: 768 },
    "16:9": { width: 1024, height: 576 },
    "9:16": { width: 576, height: 1024 },
    "4:3": { width: 896, height: 672 },
    "3:4": { width: 672, height: 896 },
    "3:2": { width: 960, height: 640 },
    "2:3": { width: 640, height: 960 },
    "21:9": { width: 1152, height: 512 },
  },
  standard: {
    "1:1": { width: 1024, height: 1024 },
    "16:9": { width: 1344, height: 768 },
    "9:16": { width: 768, height: 1344 },
    "4:3": { width: 1152, height: 864 },
    "3:4": { width: 864, height: 1152 },
    "3:2": { width: 1216, height: 832 },
    "2:3": { width: 832, height: 1216 },
    "21:9": { width: 1536, height: 640 },
  },
  large: {
    "1:1": { width: 1280, height: 1280 },
    "16:9": { width: 1536, height: 864 },
    "9:16": { width: 864, height: 1536 },
    "4:3": { width: 1344, height: 1024 },
    "3:4": { width: 1024, height: 1344 },
    "3:2": { width: 1472, height: 960 },
    "2:3": { width: 960, height: 1472 },
    "21:9": { width: 1792, height: 768 },
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

function parseAspectRatio(value: unknown): AspectRatio {
  const candidate = cleanString(value || DEFAULT_ASPECT_RATIO) as AspectRatio;
  if (!(ASPECT_RATIOS as readonly string[]).includes(candidate)) throw new Error(`aspectRatio must be one of: ${ASPECT_RATIOS.join(", ")}`);
  return candidate;
}

function parseSizePreset(value: unknown): ImageSizePreset {
  const candidate = cleanString(value || DEFAULT_SIZE).toLowerCase() as ImageSizePreset;
  if (!(SIZE_PRESETS as readonly string[]).includes(candidate)) throw new Error(`size must be one of: ${SIZE_PRESETS.join(", ")}`);
  return candidate;
}

function dimensionsFor(aspectRatio: AspectRatio, size: ImageSizePreset): { width: number; height: number } {
  return DIMENSION_PRESETS[size][aspectRatio];
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
  const configured = cleanPath(process.env.MEDIA_GENERATION_DIR || process.env.IMAGE_GENERATION_DIR);
  return resolve(expandLocalPath(configured || join(homedir(), "media-generation")));
}

function imageWorkerPath(baseDir: string): string {
  return join(baseDir, "bin", "image-generate");
}

async function runLocalWorker(
  pi: ExtensionAPI,
  baseDir: string,
  args: string[],
  timeoutMs: number,
  signal?: AbortSignal,
  disableSync = false,
) {
  const executable = imageWorkerPath(baseDir);
  if (!existsSync(executable)) throw new Error(`Local image worker not found: ${executable}`);
  const envArgs = [
    `MEDIA_GENERATION_DIR=${baseDir}`,
    `IMAGE_GENERATION_DIR=${baseDir}`,
    ...(disableSync ? ["JARVIS_GENERATION_SYNC=0"] : []),
    executable,
    ...args,
  ];
  return pi.exec("/usr/bin/env", envArgs, { cwd: baseDir, timeout: timeoutMs, signal });
}

function parseWorkerResult(stdout: string, stderr: string, code: number): WorkerResult {
  const lines = stdout.trim().split(/\n+/).filter(Boolean);
  const candidate = lines[lines.length - 1] || "";
  try {
    return JSON.parse(candidate) as WorkerResult;
  } catch (error: any) {
    throw new Error(`Local image worker did not return JSON (exit ${code}). stdout=${stdout.slice(-2000)} stderr=${stderr.slice(-2000)} parse=${error.message}`);
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

function resultText(result: WorkerResult, localPath: string, metadataLocalPath?: string, inlined?: boolean, cleanedWorkerPaths: string[] = []): string {
  const modeLine = result.mode === "image-to-image"
    ? `Mode: guided image edit${typeof result.imageStrength === "number" ? `, strength ${result.imageStrength}` : ""}`
    : "Mode: text-to-image";
  return [
    "Generated image with Qwen-Image-2512-8bit.",
    modeLine,
    `Local: ${localPath}`,
    result.workerPath ? `Worker staging source deleted after local copy: ${result.workerPath}` : undefined,
    metadataLocalPath ? `Metadata: ${metadataLocalPath}` : undefined,
    cleanedWorkerPaths.length > 0 ? `Local staging cleanup: deleted ${cleanedWorkerPaths.length} file(s).` : undefined,
    `Model: ${MODEL}`, 
    result.aspectRatio ? `Aspect ratio: ${result.aspectRatio}${result.size ? ` (${result.size})` : ""}` : undefined,
    `Seed: ${result.seed ?? "unknown"}`,
    `Steps: ${result.steps ?? "unknown"}`,
    `Size: ${result.width ?? "?"}x${result.height ?? "?"}, ${formatBytes(result.sizeBytes)}`,
    typeof result.elapsedSeconds === "number" ? `Elapsed: ${result.elapsedSeconds.toFixed(1)}s` : undefined,
    inlined ? "Image is attached inline." : `Image not inlined because it exceeds ${formatBytes(MAX_INLINE_BYTES)} or inlineImage=false.`,
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
  if (resolve(source) === resolve(destination)) throw new Error("Worker staging and final image paths must differ.");
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

async function generateImage(pi: ExtensionAPI, params: GenerateImageParams, signal?: AbortSignal, onUpdate?: (partial: any) => void, cwd = process.cwd()) {
  const prompt = cleanPrompt(params.prompt);
  if (!prompt) throw new Error("generate_image requires a non-empty prompt.");
  const negativePrompt = cleanPrompt(params.negativePrompt || DEFAULT_NEGATIVE_PROMPT);
  const aspectRatio = parseAspectRatio(params.aspectRatio);
  const sizePreset = parseSizePreset(params.size);
  const { width, height } = dimensionsFor(aspectRatio, sizePreset);
  const steps = optionalInteger(params.steps, "steps", 1, 50) ?? DEFAULT_STEPS;
  const seed = optionalInteger(params.seed, "seed", 0, 2_147_483_647);
  const timeoutSeconds = optionalInteger(params.timeoutSeconds, "timeoutSeconds", 60, 7200) ?? DEFAULT_TIMEOUT_SECONDS;
  const inlineImage = params.inlineImage !== false;
  const inputImage = resolveInputImagePath(params.inputImagePath, cwd);
  const imageStrength = optionalFloat(params.imageStrength, "imageStrength", 0, 1);
  if (imageStrength !== undefined && !inputImage) throw new Error("imageStrength requires inputImagePath.");
  const resolvedImageStrength = inputImage ? imageStrength ?? DEFAULT_IMAGE_STRENGTH : undefined;

  const baseDir = localBaseDir();
  const jobId = safeSlug(`img-${timestampSlug()}-${randomUUID().slice(0, 8)}`, `img-${Date.now()}`);
  const filename = safeSlug(params.filename, jobId).replace(/\.png$/i, "") + ".png";
  const localOutputDir = resolve(cwd, LOCAL_OUTPUT_DIR);
  const workerInputsDir = join(baseDir, "inputs");
  const workerJobFile = join(workerInputsDir, `${jobId}.json`);
  const workerInputImagePath = inputImage ? join(workerInputsDir, `${jobId}-input${inputImage.extension}`) : undefined;
  const expectedWorkerOutputPath = join(baseDir, "outputs", filename);
  const expectedWorkerMetadataPath = expectedWorkerOutputPath.replace(/\.png$/i, ".metadata.json");
  const cleanupPaths = [workerJobFile, workerInputImagePath, expectedWorkerOutputPath, expectedWorkerMetadataPath, localPidFile(baseDir, jobId)];
  mkdirSync(workerInputsDir, { recursive: true });
  mkdirSync(join(baseDir, "outputs"), { recursive: true });
  mkdirSync(localOutputDir, { recursive: true });

  const job = {
    jobId,
    filename,
    prompt,
    negativePrompt,
    aspectRatio,
    size: sizePreset,
    steps,
    seed,
    timeoutSeconds,
    ...(workerInputImagePath ? { inputImagePath: workerInputImagePath, imageStrength: resolvedImageStrength } : {}),
  };

  onUpdate?.({ content: [{ type: "text" as const, text: `Preparing local image job ${jobId} on ${MACHINE_NAME}...` }] });
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

  const modeText = inputImage ? `guided edit, strength ${resolvedImageStrength}` : "text-to-image";
  onUpdate?.({ content: [{ type: "text" as const, text: `Generating locally with ${MODEL} (${width}x${height}, ${steps} steps, ${modeText})...` }] });
  let workerResult: WorkerResult | undefined;
  try {
    const generation = await runLocalWorker(pi, baseDir, ["--job-file", workerJobFile], (timeoutSeconds + 60) * 1000, signal, true);
    workerResult = parseWorkerResult(generation.stdout, generation.stderr, generation.code);
    if (generation.code !== 0 || generation.killed || workerResult.ok !== true) {
      throw new Error([
        `Local image generation failed on ${MACHINE_NAME}.`,
        workerResult.error ? `error: ${workerResult.error}` : undefined,
        workerResult.stage ? `stage: ${workerResult.stage}` : undefined,
        workerResult.stderrTail ? `stderr: ${workerResult.stderrTail}` : undefined,
        workerResult.stdoutTail ? `stdout: ${workerResult.stdoutTail}` : undefined,
        !workerResult.error && generation.stderr ? `worker stderr: ${generation.stderr}` : undefined,
      ].filter(Boolean).join("\n"));
    }

    const workerOutputPath = cleanPath(workerResult.workerPath);
    if (!workerOutputPath) throw new Error("Local image worker succeeded but did not return workerPath.");
    if (!safeLocalCleanupPaths(baseDir, [workerOutputPath]).includes(resolve(workerOutputPath))) {
      throw new Error(`Local image worker returned an unsafe output path: ${workerOutputPath}`);
    }
    if (!existsSync(workerOutputPath)) throw new Error(`Local image worker output is missing: ${workerOutputPath}`);

    const localPath = join(localOutputDir, basename(workerOutputPath));
    onUpdate?.({ content: [{ type: "text" as const, text: `Copying image locally to ${localPath}...` }] });
    copyLocalOutput(workerOutputPath, localPath);

    let metadataLocalPath: string | undefined;
    const workerMetadataPath = cleanPath(workerResult.metadataPath);
    if (workerMetadataPath && safeLocalCleanupPaths(baseDir, [workerMetadataPath]).includes(resolve(workerMetadataPath)) && existsSync(workerMetadataPath)) {
      metadataLocalPath = localPath.replace(/\.png$/i, ".metadata.json");
      try {
        copyLocalOutput(workerMetadataPath, metadataLocalPath);
      } catch {
        metadataLocalPath = undefined;
      }
    }

    const cleanedWorkerPaths = cleanupLocalFiles(baseDir, [workerOutputPath, workerMetadataPath, ...cleanupPaths]);
    const stat = statSync(localPath);
    const shouldInline = inlineImage && stat.size <= MAX_INLINE_BYTES;
    const content: any[] = [{ type: "text" as const, text: resultText(workerResult, localPath, metadataLocalPath, shouldInline, cleanedWorkerPaths) }];
    if (shouldInline) {
      content.push({ type: "image" as const, data: readFileSync(localPath).toString("base64"), mimeType: "image/png" });
    }

    return {
      content,
      details: {
        ok: true,
        model: MODEL,
        machine: MACHINE_NAME,
        execution: "local",
        jobId,
        localPath,
        metadataLocalPath,
        worker: workerResult,
        inputImagePath: inputImage?.path,
        imageStrength: resolvedImageStrength,
        aspectRatio,
        size: sizePreset,
        cleanedWorkerPaths,
        inlined: shouldInline,
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

export default function registerImageGeneration(pi: ExtensionAPI) {
  pi.registerTool({
    name: "generate_image",
    label: "Generate Image",
    description: `Generate exactly one image locally on mac-mini-64 using the approved headless model ${MODEL}; return the local PNG path and optional inline image. No SSH, hosted models, alternate models, or fallbacks are used.`,
    parameters: Type.Object({
      prompt: Type.String({ description: "Detailed image prompt to render." }),
      negativePrompt: Type.Optional(Type.String({ description: `Optional negative prompt. Defaults to: ${DEFAULT_NEGATIVE_PROMPT}` })),
      aspectRatio: Type.Optional(stringEnum(ASPECT_RATIOS, { description: `Image aspect ratio. Default ${DEFAULT_ASPECT_RATIO}.` })),
      size: Type.Optional(stringEnum(SIZE_PRESETS, { description: `Output size preset. Default ${DEFAULT_SIZE}.` })),
      steps: Type.Optional(Type.Number({ description: `Inference steps, 1-50. Default ${DEFAULT_STEPS}.` })),
      seed: Type.Optional(Type.Number({ description: "Optional seed, 0-2147483647. If omitted, the local worker chooses a random seed." })),
      inputImagePath: Type.Optional(Type.String({ description: "Optional local source image for guided editing. Supported: PNG, JPG/JPEG, WebP, BMP. A temporary local staging copy is deleted after generation." })),
      imageStrength: Type.Optional(Type.Number({ description: `Optional source-image guidance strength, 0-1. Requires inputImagePath. Default ${DEFAULT_IMAGE_STRENGTH}. Higher values preserve more source-image influence.` })),
      filename: Type.Optional(Type.String({ description: "Optional output filename stem or .png filename. Sanitized." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: `Optional generation timeout, 60-7200 seconds. Default ${DEFAULT_TIMEOUT_SECONDS}.` })),
      inlineImage: Type.Optional(Type.Boolean({ description: "Whether to attach the PNG inline to the tool result. Default true; large files are path-only." })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      return generateImage(pi, params as GenerateImageParams, signal, onUpdate, ctx.cwd);
    },
    renderCall(args, theme, context) {
      const state = context.state as RenderState;
      if (context.executionStarted && state.startedAt === undefined) {
        state.startedAt = Date.now();
        state.endedAt = undefined;
      }
      const prompt = cleanString((args as any).prompt).slice(0, 90) || "...";
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(`${theme.fg("toolTitle", "generate_image")} ${theme.fg("muted", MODEL)} ${theme.fg("toolOutput", prompt)}`);
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
      const label = options.isPartial ? theme.fg("toolTitle", "generate_image") : ok ? theme.fg("success", "✓ generated image") : theme.fg("warning", "image generation");
      const footer = elapsedFooter(state, options.isPartial, theme);
      const lines = [label, localPath ? theme.fg("accent", localPath) : undefined, footer].filter(Boolean);
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(lines.join("\n"));
      return text;
    },
  });

  pi.registerCommand("image-health", {
    description: "Check the mac-mini-64 headless image generator health.",
    handler: async (_args, ctx) => {
      const result = await runLocalWorker(pi, localBaseDir(), ["--health"], 30_000, ctx.signal);
      if (result.code !== 0 || result.killed) throw new Error((result.stderr || result.stdout || "Local image health check failed").trim());
      ctx.ui.notify(result.stdout.trim() || "No health output", "info");
    },
  });
}
