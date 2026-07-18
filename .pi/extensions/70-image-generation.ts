import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, extname, join, resolve } from "node:path";
import { randomUUID } from "node:crypto";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type HostConfig = {
  aliases: string[];
  description?: string;
  hostName: string;
  user: string;
  identityFile: string;
  homeDir: string;
  connectTimeoutSeconds?: number;
  shell?: string;
  shellType?: "posix" | "windows-cmd" | "windows-powershell";
};

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

type RemoteResult = {
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
  remotePath?: string;
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
const HOST_ALIAS = (process.env.IMAGE_GENERATION_HOST_ALIAS || "mac-mini-64").trim();
const DEFAULT_HOST_CONFIG_PATH = join(process.cwd(), ".pi", "ssh-hosts.json");
const HOST_CONFIG_PATH = (process.env.IMAGE_GENERATION_SSH_HOSTS_CONFIG || DEFAULT_HOST_CONFIG_PATH).trim();
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

function expandRemotePath(value: string, homeDir: string): string {
  if (value === "~" || value === "$HOME") return homeDir;
  if (value.startsWith("~/")) return `${homeDir}/${value.slice(2)}`;
  if (value.startsWith("$HOME/")) return `${homeDir}/${value.slice(6)}`;
  return value;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
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

function loadHostConfigs(): HostConfig[] {
  if (!existsSync(HOST_CONFIG_PATH)) throw new Error(`SSH host config not found: ${HOST_CONFIG_PATH}`);
  const parsed = JSON.parse(readFileSync(HOST_CONFIG_PATH, "utf8"));
  if (!Array.isArray(parsed)) throw new Error(`SSH host config must be an array: ${HOST_CONFIG_PATH}`);
  return parsed.map((entry: any) => ({
    aliases: Array.isArray(entry.aliases) ? entry.aliases.map(String) : entry.alias ? [String(entry.alias)] : [],
    description: cleanString(entry.description),
    hostName: cleanString(entry.hostName || entry.host),
    user: cleanString(entry.user),
    identityFile: expandLocalPath(cleanString(entry.identityFile || "~/.ssh/id_ed25519")),
    homeDir: cleanString(entry.homeDir) || `/Users/${cleanString(entry.user)}`,
    connectTimeoutSeconds: positiveInteger(entry.connectTimeoutSeconds, 8),
    shell: cleanString(entry.shell) || "bash -lc",
    shellType: cleanString(entry.shellType) === "posix" ? "posix" : "posix",
  }));
}

function resolveHost(): HostConfig {
  const hosts = loadHostConfigs();
  const host = hosts.find((candidate) => candidate.aliases.map((alias) => alias.toLowerCase()).includes(HOST_ALIAS.toLowerCase()));
  if (!host) throw new Error(`Image host alias ${HOST_ALIAS} not found in ${HOST_CONFIG_PATH}`);
  if (!host.hostName || !host.user) throw new Error(`Image host ${HOST_ALIAS} is missing hostName or user`);
  return host;
}

function remoteBaseDir(host: HostConfig): string {
  const configured = cleanString(process.env.MEDIA_GENERATION_REMOTE_DIR || process.env.IMAGE_GENERATION_REMOTE_DIR);
  return expandRemotePath(configured || `${host.homeDir}/media-generation`, host.homeDir);
}

function remoteSpec(host: HostConfig, remotePath: string): string {
  return `${host.user}@${host.hostName}:${remotePath}`;
}

function sshArgs(host: HostConfig, remoteScript: string): string[] {
  return [
    "-i", host.identityFile,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "NumberOfPasswordPrompts=0",
    "-o", `ConnectTimeout=${host.connectTimeoutSeconds ?? 8}`,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=2",
    "-o", "LogLevel=ERROR",
    `${host.user}@${host.hostName}`,
    `${host.shell || "bash -lc"} ${shellQuote(remoteScript)}`,
  ];
}

function scpBaseArgs(host: HostConfig): string[] {
  return [
    "-i", host.identityFile,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "NumberOfPasswordPrompts=0",
    "-o", `ConnectTimeout=${host.connectTimeoutSeconds ?? 8}`,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "LogLevel=ERROR",
  ];
}

async function runSsh(pi: ExtensionAPI, host: HostConfig, script: string, timeoutMs: number, signal?: AbortSignal) {
  const result = await pi.exec("ssh", sshArgs(host, script), { timeout: timeoutMs, signal });
  if (result.code !== 0 || result.killed) {
    throw new Error(`SSH command failed on ${HOST_ALIAS} (code ${result.code}${result.killed ? ", killed" : ""}): ${(result.stderr || result.stdout || "").trim().slice(0, 4000)}`);
  }
  return result;
}

async function runScp(pi: ExtensionAPI, host: HostConfig, args: string[], timeoutMs: number, signal?: AbortSignal) {
  const result = await pi.exec("scp", [...scpBaseArgs(host), ...args], { timeout: timeoutMs, signal });
  if (result.code !== 0 || result.killed) {
    throw new Error(`scp failed (code ${result.code}${result.killed ? ", killed" : ""}): ${(result.stderr || result.stdout || "").trim().slice(0, 4000)}`);
  }
  return result;
}

function parseRemoteResult(stdout: string, stderr: string, code: number): RemoteResult {
  const lines = stdout.trim().split(/\n+/).filter(Boolean);
  const candidate = lines[lines.length - 1] || "";
  try {
    return JSON.parse(candidate) as RemoteResult;
  } catch (error: any) {
    throw new Error(`Remote image worker did not return JSON (exit ${code}). stdout=${stdout.slice(-2000)} stderr=${stderr.slice(-2000)} parse=${error.message}`);
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

function resultText(result: RemoteResult, localPath: string, metadataLocalPath?: string, inlined?: boolean, cleanedRemotePaths: string[] = []): string {
  const modeLine = result.mode === "image-to-image"
    ? `Mode: guided image edit${typeof result.imageStrength === "number" ? `, strength ${result.imageStrength}` : ""}`
    : "Mode: text-to-image";
  return [
    "Generated image with Qwen-Image-2512-8bit.",
    modeLine,
    `Local: ${localPath}`,
    result.remotePath ? `Remote source deleted after copy: ${HOST_ALIAS}:${result.remotePath}` : undefined,
    metadataLocalPath ? `Metadata: ${metadataLocalPath}` : undefined,
    cleanedRemotePaths.length > 0 ? `Remote cleanup: deleted ${cleanedRemotePaths.length} file(s).` : undefined,
    `Model: ${MODEL}`, 
    result.aspectRatio ? `Aspect ratio: ${result.aspectRatio}${result.size ? ` (${result.size})` : ""}` : undefined,
    `Seed: ${result.seed ?? "unknown"}`,
    `Steps: ${result.steps ?? "unknown"}`,
    `Size: ${result.width ?? "?"}x${result.height ?? "?"}, ${formatBytes(result.sizeBytes)}`,
    typeof result.elapsedSeconds === "number" ? `Elapsed: ${result.elapsedSeconds.toFixed(1)}s` : undefined,
    inlined ? "Image is attached inline." : `Image not inlined because it exceeds ${formatBytes(MAX_INLINE_BYTES)} or inlineImage=false.`,
  ].filter(Boolean).join("\n");
}

function safeRemoteCleanupPaths(baseDir: string, paths: Array<string | undefined | null>): string[] {
  const normalizedBase = baseDir.replace(/\/+$/, "");
  const allowedPrefixes = [`${normalizedBase}/outputs/`, `${normalizedBase}/inputs/`, `${normalizedBase}/runtime/pids/`];
  return [...new Set(paths
    .map((path) => cleanString(path))
    .filter((path) => path && allowedPrefixes.some((prefix) => path.startsWith(prefix))))];
}

async function cleanupRemoteFiles(pi: ExtensionAPI, host: HostConfig, baseDir: string, paths: Array<string | undefined | null>, signal?: AbortSignal): Promise<string[]> {
  const safePaths = safeRemoteCleanupPaths(baseDir, paths);
  if (safePaths.length === 0) return [];
  await runSsh(pi, host, `rm -f ${safePaths.map(shellQuote).join(" ")}`, 60_000, signal);
  return safePaths;
}

function remotePidFile(baseDir: string, jobId: string): string {
  return `${baseDir.replace(/\/+$/, "")}/runtime/pids/${jobId}.json`;
}

function remoteCancelScript(baseDir: string, jobId: string, paths: Array<string | undefined | null>): string {
  const pidFile = remotePidFile(baseDir, jobId);
  const safePaths = safeRemoteCleanupPaths(baseDir, [pidFile, ...paths]);
  const searchPatterns = [...new Set([pidFile, jobId, ...paths.map((path) => cleanString(path)).filter(Boolean)])];
  const searchPatternArgs = searchPatterns.map(shellQuote).join(" ");
  const cleanupLine = safePaths.length > 0 ? `rm -f ${safePaths.map(shellQuote).join(" ")} 2>/dev/null || true` : ":";
  return `set +e
PID_FILE=${shellQuote(pidFile)}
JOB_ID=${shellQuote(jobId)}
THIS_PGID="$(ps -o pgid= -p "$$" 2>/dev/null | tr -d ' ')"

kill_one() {
  pid="$1"
  [ -n "$pid" ] || return 0
  [ "$pid" = "$$" ] && return 0
  [ "$pid" = "$PPID" ] && return 0
  case "$pid" in *[!0-9]* ) return 0;; esac
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
  if [ -n "$pgid" ] && [ "$pgid" != "$THIS_PGID" ]; then
    kill -TERM "-$pgid" 2>/dev/null || true
  fi
  kill -TERM "$pid" 2>/dev/null || true
}

kill_one_force() {
  pid="$1"
  [ -n "$pid" ] || return 0
  [ "$pid" = "$$" ] && return 0
  [ "$pid" = "$PPID" ] && return 0
  case "$pid" in *[!0-9]* ) return 0;; esac
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
  if [ -n "$pgid" ] && [ "$pgid" != "$THIS_PGID" ]; then
    kill -KILL "-$pgid" 2>/dev/null || true
  fi
  kill -KILL "$pid" 2>/dev/null || true
}

pid_file_pids() {
  [ -f "$PID_FILE" ] || return 0
  python3 - "$PID_FILE" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    data = {}
for key in ("childPgid", "childPid", "workerPid"):
    value = data.get(key)
    if isinstance(value, int):
        print(value)
    elif isinstance(value, str) and value.isdigit():
        print(value)
PY
}

for pid in $(pid_file_pids); do kill_one "$pid"; done
for pattern in ${searchPatternArgs}; do
  [ -n "$pattern" ] || continue
  pgrep -f "$pattern" 2>/dev/null | while IFS= read -r pid; do kill_one "$pid"; done
done
sleep 2
for pid in $(pid_file_pids); do kill_one_force "$pid"; done
for pattern in ${searchPatternArgs}; do
  [ -n "$pattern" ] || continue
  pgrep -f "$pattern" 2>/dev/null | while IFS= read -r pid; do kill_one_force "$pid"; done
done
${cleanupLine}`;
}

async function cancelRemoteImageJob(pi: ExtensionAPI, host: HostConfig, baseDir: string, jobId: string, paths: Array<string | undefined | null>): Promise<void> {
  try {
    await runSsh(pi, host, remoteCancelScript(baseDir, jobId, paths), 30_000);
  } catch {
    // Cancellation is best-effort and must not mask the original abort/error.
  }
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

  const host = resolveHost();
  const baseDir = remoteBaseDir(host);
  const jobId = safeSlug(`img-${timestampSlug()}-${randomUUID().slice(0, 8)}`, `img-${Date.now()}`);
  const filename = safeSlug(params.filename, jobId).replace(/\.png$/i, "") + ".png";
  const localRuntimeDir = resolve(cwd, ".pi", "runtime", "image-generation");
  const localJobsDir = join(localRuntimeDir, "jobs");
  const localOutputDir = resolve(cwd, LOCAL_OUTPUT_DIR);
  mkdirSync(localJobsDir, { recursive: true });
  mkdirSync(localOutputDir, { recursive: true });

  const localJobFile = join(localJobsDir, `${jobId}.json`);
  const remoteInputsDir = `${baseDir}/inputs`;
  const remoteJobFile = `${remoteInputsDir}/${jobId}.json`;
  const remoteInputImagePath = inputImage ? `${remoteInputsDir}/${jobId}-input${inputImage.extension}` : undefined;
  const expectedRemoteOutputPath = `${baseDir}/outputs/${filename}`;
  const expectedRemoteMetadataPath = expectedRemoteOutputPath.replace(/\.png$/i, ".metadata.json");
  const remoteCancelPaths = [remoteJobFile, remoteInputImagePath, expectedRemoteOutputPath, expectedRemoteMetadataPath];
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
    ...(remoteInputImagePath ? { inputImagePath: remoteInputImagePath, imageStrength: resolvedImageStrength } : {}),
  };
  writeFileSync(localJobFile, JSON.stringify(job, null, 2), "utf8");

  onUpdate?.({ content: [{ type: "text" as const, text: `Preparing ${HOST_ALIAS} image job ${jobId}...` }] });
  await runSsh(pi, host, `mkdir -p ${shellQuote(remoteInputsDir)} ${shellQuote(`${baseDir}/outputs`)}`, 30_000, signal);
  try {
    try {
      if (inputImage && remoteInputImagePath) {
        onUpdate?.({ content: [{ type: "text" as const, text: `Uploading source image (${formatBytes(inputImage.sizeBytes)}) to ${HOST_ALIAS}...` }] });
        await runScp(pi, host, [inputImage.path, remoteSpec(host, remoteInputImagePath)], 120_000, signal);
      }
      await runScp(pi, host, [localJobFile, remoteSpec(host, remoteJobFile)], 60_000, signal);
    } finally {
      try {
        rmSync(localJobFile, { force: true });
      } catch {
        // Best-effort local prompt/job cleanup.
      }
    }
  } catch (error) {
    try {
      await cleanupRemoteFiles(pi, host, baseDir, [remoteJobFile, remoteInputImagePath], signal?.aborted ? undefined : signal);
    } catch {
      // Best-effort upload-stage cleanup only; preserve the original error.
    }
    throw error;
  }

  const modeText = inputImage ? `guided edit, strength ${resolvedImageStrength}` : "text-to-image";
  onUpdate?.({ content: [{ type: "text" as const, text: `Generating image on ${HOST_ALIAS} with ${MODEL} (${width}x${height}, ${steps} steps, ${modeText})...` }] });
  const remoteCommand = [
    `export MEDIA_GENERATION_DIR=${shellQuote(baseDir)}`,
    `export IMAGE_GENERATION_DIR=${shellQuote(baseDir)}`,
    "export JARVIS_GENERATION_SYNC=0",
    `${shellQuote(`${baseDir}/bin/image-generate`)} --job-file ${shellQuote(remoteJobFile)}`,
  ].join("\n");
  let remoteResult: RemoteResult | undefined;
  let cancelPromise: Promise<void> | undefined;
  const startRemoteCancel = () => {
    cancelPromise ??= cancelRemoteImageJob(pi, host, baseDir, jobId, remoteCancelPaths);
    return cancelPromise;
  };
  const abortHandler = () => { void startRemoteCancel(); };
  if (signal?.aborted) abortHandler();
  else signal?.addEventListener("abort", abortHandler, { once: true });
  try {
    const generation = await pi.exec("ssh", sshArgs(host, remoteCommand), { timeout: (timeoutSeconds + 60) * 1000, signal });
    remoteResult = parseRemoteResult(generation.stdout, generation.stderr, generation.code);
    if (generation.code !== 0 || generation.killed || remoteResult.ok !== true) {
      throw new Error([
        `Image generation failed on ${HOST_ALIAS}.`,
        remoteResult.error ? `error: ${remoteResult.error}` : undefined,
        remoteResult.stage ? `stage: ${(remoteResult as any).stage}` : undefined,
        remoteResult.stderrTail ? `stderr: ${remoteResult.stderrTail}` : undefined,
        remoteResult.stdoutTail ? `stdout: ${remoteResult.stdoutTail}` : undefined,
        !remoteResult.error && generation.stderr ? `ssh stderr: ${generation.stderr}` : undefined,
      ].filter(Boolean).join("\n"));
    }
    if (!remoteResult.remotePath) throw new Error("Remote worker succeeded but did not return remotePath.");

    const localPath = join(localOutputDir, basename(remoteResult.remotePath));
    onUpdate?.({ content: [{ type: "text" as const, text: `Copying image back to ${localPath}...` }] });
    await runScp(pi, host, [remoteSpec(host, remoteResult.remotePath), localPath], 120_000, signal);

    let metadataLocalPath: string | undefined;
    if (remoteResult.metadataPath) {
      metadataLocalPath = localPath.replace(/\.png$/i, ".metadata.json");
      try {
        await runScp(pi, host, [remoteSpec(host, remoteResult.metadataPath), metadataLocalPath], 60_000, signal);
      } catch {
        metadataLocalPath = undefined;
      }
    }

    onUpdate?.({ content: [{ type: "text" as const, text: "Deleting remote image inputs and outputs from mac-mini-64..." }] });
    const cleanedRemotePaths = await cleanupRemoteFiles(pi, host, baseDir, [remoteResult.remotePath, remoteResult.metadataPath, remoteJobFile, remoteInputImagePath, remotePidFile(baseDir, jobId)], signal?.aborted ? undefined : signal);

    const stat = statSync(localPath);
    const shouldInline = inlineImage && stat.size <= MAX_INLINE_BYTES;
    const content: any[] = [{ type: "text" as const, text: resultText(remoteResult, localPath, metadataLocalPath, shouldInline, cleanedRemotePaths) }];
    if (shouldInline) {
      content.push({ type: "image" as const, data: readFileSync(localPath).toString("base64"), mimeType: "image/png" });
    }

    return {
      content,
      details: {
        ok: true,
        model: MODEL,
        host: HOST_ALIAS,
        jobId,
        localPath,
        metadataLocalPath,
        remote: remoteResult,
        inputImagePath: inputImage?.path,
        imageStrength: resolvedImageStrength,
        aspectRatio,
        size: sizePreset,
        cleanedRemotePaths,
        inlined: shouldInline,
        sizeBytes: stat.size,
      },
    };
  } catch (error) {
    if (signal?.aborted) await startRemoteCancel();
    try {
      await cleanupRemoteFiles(pi, host, baseDir, [remoteResult?.remotePath, remoteResult?.metadataPath, ...remoteCancelPaths, remotePidFile(baseDir, jobId)], signal?.aborted ? undefined : signal);
    } catch {
      // Best-effort cleanup only; preserve the original generation/copy error.
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", abortHandler);
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
    description: `Generate exactly one image on mac-mini-64 using the single approved headless model: ${MODEL}. The tool sends the prompt, and optionally a local source image for guided image-to-image editing, over SSH; runs mflux/Qwen on the Mini; copies the PNG back locally; and returns the local path plus optional inline PNG. No alternate models or fallback models are available.`,
    parameters: Type.Object({
      prompt: Type.String({ description: "Detailed image prompt to render." }),
      negativePrompt: Type.Optional(Type.String({ description: `Optional negative prompt. Defaults to: ${DEFAULT_NEGATIVE_PROMPT}` })),
      aspectRatio: Type.Optional(stringEnum(ASPECT_RATIOS, { description: `Image aspect ratio. Default ${DEFAULT_ASPECT_RATIO}.` })),
      size: Type.Optional(stringEnum(SIZE_PRESETS, { description: `Output size preset. Default ${DEFAULT_SIZE}.` })),
      steps: Type.Optional(Type.Number({ description: `Inference steps, 1-50. Default ${DEFAULT_STEPS}.` })),
      seed: Type.Optional(Type.Number({ description: "Optional seed, 0-2147483647. If omitted, the remote worker chooses a random seed." })),
      inputImagePath: Type.Optional(Type.String({ description: "Optional local source image path for guided image-to-image editing. Supported: PNG, JPG/JPEG, WebP, BMP. The source is copied to mac-mini-64 temporarily and deleted after generation." })),
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
      const host = resolveHost();
      const baseDir = remoteBaseDir(host);
      const result = await runSsh(pi, host, `${shellQuote(`${baseDir}/bin/image-generate`)} --health`, 30_000, ctx.signal);
      ctx.ui.notify(result.stdout.trim() || "No health output", "info");
    },
  });
}
