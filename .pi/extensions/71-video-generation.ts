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

type VideoAspectRatio = "16:9" | "9:16" | "1:1" | "4:3" | "3:4";
type VideoSizePreset = "small" | "standard" | "large";

type GenerateVideoParams = {
  prompt: string;
  negativePrompt?: string;
  aspectRatio?: VideoAspectRatio;
  size?: VideoSizePreset;
  seconds?: number;
  durationSeconds?: number;
  fps?: number;
  steps?: number;
  guidance?: number;
  seed?: number;
  inputImagePath?: string;
  filename?: string;
  timeoutSeconds?: number;
};

type RemoteVideoResult = {
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
  guidance?: number;
  seed?: number;
  mode?: "text-to-video" | "image-to-video";
  elapsedSeconds?: number;
  remotePath?: string;
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

const VIDEO_MODEL = "AbstractFramework/wan2.2-ti2v-5b-diffusers-8bit";
const HOST_ALIAS = (process.env.VIDEO_GENERATION_HOST_ALIAS || process.env.IMAGE_GENERATION_HOST_ALIAS || "mac-mini-64").trim();
const DEFAULT_HOST_CONFIG_PATH = join(process.cwd(), ".pi", "ssh-hosts.json");
const HOST_CONFIG_PATH = (process.env.VIDEO_GENERATION_SSH_HOSTS_CONFIG || process.env.IMAGE_GENERATION_SSH_HOSTS_CONFIG || DEFAULT_HOST_CONFIG_PATH).trim();
const DEFAULT_ASPECT_RATIO: VideoAspectRatio = "16:9";
const DEFAULT_SIZE: VideoSizePreset = "large";
const DEFAULT_DURATION_SECONDS = 4;
const DEFAULT_FPS = 24;
const MAX_INTERNAL_FRAMES = 121;
const DEFAULT_STEPS = 20;
const DEFAULT_GUIDANCE = 5;
const DEFAULT_TIMEOUT_SECONDS = 7200;
const DEFAULT_MAX_INPUT_IMAGE_BYTES = 50 * 1024 * 1024;
const MAX_INPUT_IMAGE_BYTES = positiveInteger(process.env.VIDEO_GENERATION_MAX_INPUT_IMAGE_BYTES, DEFAULT_MAX_INPUT_IMAGE_BYTES);
const LOCAL_OUTPUT_DIR = process.env.VIDEO_GENERATION_LOCAL_OUTPUT_DIR || "generated-videos";
const INPUT_IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".bmp"]);
const ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"] as const;
const SIZE_PRESETS = ["small", "standard", "large"] as const;
const DIMENSION_PRESETS: Record<VideoSizePreset, Record<VideoAspectRatio, { width: number; height: number }>> = {
  small: {
    "16:9": { width: 448, height: 256 },
    "9:16": { width: 256, height: 448 },
    "1:1": { width: 384, height: 384 },
    "4:3": { width: 512, height: 384 },
    "3:4": { width: 384, height: 512 },
  },
  standard: {
    "16:9": { width: 832, height: 480 },
    "9:16": { width: 480, height: 832 },
    "1:1": { width: 512, height: 512 },
    "4:3": { width: 768, height: 576 },
    "3:4": { width: 576, height: 768 },
  },
  large: {
    "16:9": { width: 1280, height: 704 },
    "9:16": { width: 704, height: 1280 },
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

function nearestWanFrameCount(target: number): number {
  const min = 5;
  const bounded = Math.max(min, Math.min(MAX_INTERNAL_FRAMES, Math.round(target)));
  if (bounded % 4 === 1) return bounded;
  const up = bounded + ((1 - bounded) % 4 + 4) % 4;
  const down = bounded - ((bounded - 1) % 4 + 4) % 4;
  return up <= MAX_INTERNAL_FRAMES ? Math.max(min, up) : Math.max(min, down);
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
  if (!host) throw new Error(`Video host alias ${HOST_ALIAS} not found in ${HOST_CONFIG_PATH}`);
  if (!host.hostName || !host.user) throw new Error(`Video host ${HOST_ALIAS} is missing hostName or user`);
  return host;
}

function remoteBaseDir(host: HostConfig): string {
  const configured = cleanString(process.env.MEDIA_GENERATION_REMOTE_DIR || process.env.VIDEO_GENERATION_REMOTE_DIR || process.env.IMAGE_GENERATION_REMOTE_DIR);
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

function parseRemoteResult(stdout: string, stderr: string, code: number): RemoteVideoResult {
  const lines = stdout.trim().split(/\n+/).filter(Boolean);
  const candidate = lines[lines.length - 1] || "";
  try {
    return JSON.parse(candidate) as RemoteVideoResult;
  } catch (error: any) {
    throw new Error(`Remote video worker did not return JSON (exit ${code}). stdout=${stdout.slice(-2000)} stderr=${stderr.slice(-2000)} parse=${error.message}`);
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

function resultText(result: RemoteVideoResult, localPath: string, metadataLocalPath?: string, cleanedRemotePaths: string[] = []): string {
  const modeLine = result.mode === "image-to-video" ? "Mode: image-to-video" : "Mode: text-to-video";
  return [
    "Generated video with local Wan2.2 TI2V-5B via MLX-Gen.",
    modeLine,
    `Local: ${localPath}`,
    result.remotePath ? `Remote source deleted after copy: ${HOST_ALIAS}:${result.remotePath}` : undefined,
    metadataLocalPath ? `Metadata: ${metadataLocalPath}` : undefined,
    cleanedRemotePaths.length > 0 ? `Remote cleanup: deleted ${cleanedRemotePaths.length} file(s).` : undefined,
    `Model: ${VIDEO_MODEL}`,
    result.aspectRatio ? `Aspect ratio: ${result.aspectRatio}${result.size ? ` (${result.size})` : ""}` : undefined,
    `Seed: ${result.seed ?? "unknown"}`,
    `Steps: ${result.steps ?? "unknown"}`,
    typeof result.guidance === "number" ? `Guidance: ${result.guidance}` : undefined,
    `Frames/FPS: ${result.frames ?? "?"}/${result.fps ?? "?"}`,
    typeof result.durationSeconds === "number" ? `Duration: ${result.durationSeconds.toFixed(2)}s` : undefined,
    `Size: ${result.width ?? "?"}x${result.height ?? "?"}, ${formatBytes(result.sizeBytes)}`,
    typeof result.elapsedSeconds === "number" ? `Elapsed: ${result.elapsedSeconds.toFixed(1)}s` : undefined,
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

async function cancelRemoteVideoJob(pi: ExtensionAPI, host: HostConfig, baseDir: string, jobId: string, paths: Array<string | undefined | null>): Promise<void> {
  try {
    await runSsh(pi, host, remoteCancelScript(baseDir, jobId, paths), 30_000);
  } catch {
    // Cancellation is best-effort and must not mask the original abort/error.
  }
}

async function generateVideo(pi: ExtensionAPI, params: GenerateVideoParams, signal?: AbortSignal, onUpdate?: (partial: any) => void, cwd = process.cwd()) {
  const prompt = cleanPrompt(params.prompt);
  if (!prompt) throw new Error("generate_video requires a non-empty prompt.");
  const negativePrompt = cleanPrompt(params.negativePrompt || "");
  const aspectRatio = parseAspectRatio(params.aspectRatio);
  const sizePreset = parseSizePreset(params.size);
  const { width, height } = dimensionsFor(aspectRatio, sizePreset);
  const fps = optionalInteger(params.fps, "fps", 1, 24) ?? DEFAULT_FPS;
  const seconds = optionalFloat(params.seconds ?? params.durationSeconds, "seconds", 0.5, 15) ?? DEFAULT_DURATION_SECONDS;
  const requestedFrames = seconds * fps;
  if (requestedFrames > MAX_INTERNAL_FRAMES) {
    throw new Error(`seconds at ${fps} fps would require ${requestedFrames.toFixed(1)} frames; max is ${MAX_INTERNAL_FRAMES} frames (~${(MAX_INTERNAL_FRAMES / fps).toFixed(2)}s at ${fps} fps). Lower seconds or fps.`);
  }
  const frames = nearestWanFrameCount(requestedFrames);
  const resolvedDurationSeconds = frames / fps;
  const steps = optionalInteger(params.steps, "steps", 1, 60) ?? DEFAULT_STEPS;
  const guidance = optionalFloat(params.guidance, "guidance", 0, 20) ?? DEFAULT_GUIDANCE;
  const seed = optionalInteger(params.seed, "seed", 0, 2_147_483_647);
  const timeoutSeconds = optionalInteger(params.timeoutSeconds, "timeoutSeconds", 60, 14400) ?? DEFAULT_TIMEOUT_SECONDS;
  const inputImage = resolveInputImagePath(params.inputImagePath, cwd);

  const host = resolveHost();
  const baseDir = remoteBaseDir(host);
  const jobId = safeSlug(`vid-${timestampSlug()}-${randomUUID().slice(0, 8)}`, `vid-${Date.now()}`);
  const filename = safeSlug(params.filename, jobId).replace(/\.mp4$/i, "") + ".mp4";
  const localRuntimeDir = resolve(cwd, ".pi", "runtime", "video-generation");
  const localJobsDir = join(localRuntimeDir, "jobs");
  const localOutputDir = resolve(cwd, LOCAL_OUTPUT_DIR);
  mkdirSync(localJobsDir, { recursive: true });
  mkdirSync(localOutputDir, { recursive: true });

  const localJobFile = join(localJobsDir, `${jobId}.json`);
  const remoteInputsDir = `${baseDir}/inputs`;
  const remoteJobFile = `${remoteInputsDir}/${jobId}.json`;
  const remoteInputImagePath = inputImage ? `${remoteInputsDir}/${jobId}-input${inputImage.extension}` : undefined;
  const expectedRemoteOutputPath = `${baseDir}/outputs/videos/${filename}`;
  const expectedRemoteMetadataPath = expectedRemoteOutputPath.replace(/\.mp4$/i, ".metadata.json");
  const remoteCancelPaths = [remoteJobFile, remoteInputImagePath, expectedRemoteOutputPath, expectedRemoteMetadataPath];
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
    guidance,
    seed,
    timeoutSeconds,
    ...(remoteInputImagePath ? { inputImagePath: remoteInputImagePath } : {}),
  };
  writeFileSync(localJobFile, JSON.stringify(job, null, 2), "utf8");

  onUpdate?.({ content: [{ type: "text" as const, text: `Preparing ${HOST_ALIAS} video job ${jobId}...` }] });
  await runSsh(pi, host, `mkdir -p ${shellQuote(remoteInputsDir)} ${shellQuote(`${baseDir}/outputs/videos`)}`, 30_000, signal);
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

  const modeText = inputImage ? "image-to-video" : "text-to-video";
  onUpdate?.({ content: [{ type: "text" as const, text: `Generating video on ${HOST_ALIAS} with ${VIDEO_MODEL} (${width}x${height}, ${frames} frames @ ${fps} fps, ${steps} steps, ${modeText})...` }] });
  const remoteCommand = [
    `export MEDIA_GENERATION_DIR=${shellQuote(baseDir)}`,
    `export IMAGE_GENERATION_DIR=${shellQuote(baseDir)}`,
    "export JARVIS_GENERATION_SYNC=0",
    `${shellQuote(`${baseDir}/bin/video-generate`)} --job-file ${shellQuote(remoteJobFile)}`,
  ].join("\n");
  let remoteResult: RemoteVideoResult | undefined;
  let cancelPromise: Promise<void> | undefined;
  const startRemoteCancel = () => {
    cancelPromise ??= cancelRemoteVideoJob(pi, host, baseDir, jobId, remoteCancelPaths);
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
        `Video generation failed on ${HOST_ALIAS}.`,
        remoteResult.error ? `error: ${remoteResult.error}` : undefined,
        remoteResult.stage ? `stage: ${(remoteResult as any).stage}` : undefined,
        remoteResult.downloadCommand ? `download: ${remoteResult.downloadCommand}` : undefined,
        remoteResult.stderrTail ? `stderr: ${remoteResult.stderrTail}` : undefined,
        remoteResult.stdoutTail ? `stdout: ${remoteResult.stdoutTail}` : undefined,
        !remoteResult.error && generation.stderr ? `ssh stderr: ${generation.stderr}` : undefined,
      ].filter(Boolean).join("\n"));
    }
    const remoteOutputPath = remoteResult.remotePath;
    if (!remoteOutputPath) throw new Error("Remote worker succeeded but did not return remotePath.");

    const localPath = join(localOutputDir, basename(remoteOutputPath));
    onUpdate?.({ content: [{ type: "text" as const, text: `Copying video back to ${localPath}...` }] });
    await runScp(pi, host, [remoteSpec(host, remoteOutputPath), localPath], 600_000, signal);

    let metadataLocalPath: string | undefined;
    if (remoteResult.metadataPath) {
      metadataLocalPath = localPath.replace(/\.mp4$/i, ".metadata.json");
      try {
        await runScp(pi, host, [remoteSpec(host, remoteResult.metadataPath), metadataLocalPath], 60_000, signal);
      } catch {
        metadataLocalPath = undefined;
      }
    }

    onUpdate?.({ content: [{ type: "text" as const, text: "Deleting remote video inputs and outputs from mac-mini-64..." }] });
    const cleanedRemotePaths = await cleanupRemoteFiles(pi, host, baseDir, [remoteOutputPath, remoteResult.metadataPath, remoteJobFile, remoteInputImagePath, remotePidFile(baseDir, jobId)], signal?.aborted ? undefined : signal);

    const stat = statSync(localPath);
    return {
      content: [{ type: "text" as const, text: resultText(remoteResult, localPath, metadataLocalPath, cleanedRemotePaths) }],
      details: {
        ok: true,
        model: VIDEO_MODEL,
        host: HOST_ALIAS,
        jobId,
        localPath,
        metadataLocalPath,
        remote: remoteResult,
        inputImagePath: inputImage?.path,
        aspectRatio,
        size: sizePreset,
        frames,
        fps,
        durationSeconds: resolvedDurationSeconds,
        cleanedRemotePaths,
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

export default function registerVideoGeneration(pi: ExtensionAPI) {
  pi.registerTool({
    name: "generate_video",
    label: "Generate Video",
    description: `Generate exactly one short local MP4 on mac-mini-64 using the approved headless video model: ${VIDEO_MODEL}. The tool sends the prompt, and optionally a local source image for first-frame image-to-video, over SSH; runs MLX-Gen/Wan on the Mini; copies the MP4 back locally; and returns the local path. No hosted video models or fallback models are used.`,
    promptSnippet: "Generate a local MP4 video, or first-frame image-to-video clip from a local source image, on mac-mini-64 with Wan2.2 TI2V-5B and copy it back to this project.",
    promptGuidelines: [
      "Use generate_video when sir asks to create, generate, render, or make a video locally.",
      `generate_video uses only ${VIDEO_MODEL}; do not offer or request alternate video models for this tool.`,
      `Default to the high-quality profile: aspectRatio ${DEFAULT_ASPECT_RATIO}, size ${DEFAULT_SIZE}, ${DEFAULT_DURATION_SECONDS}s, ${DEFAULT_FPS} fps, and ${DEFAULT_STEPS} steps unless sir asks for a specific speed/quality tradeoff.`,
      "For image-to-video, provide inputImagePath with a local PNG/JPEG/WebP/BMP and describe the desired camera motion or subject motion in prompt.",
      "Use seconds, not frames. The worker converts seconds to Wan's required 4n+1 frame count internally and caps at 121 internal frames.",
      "Large default videos can take a long time on the Mac mini; use small or standard only when sir asks for faster previews.",
      "Do not use browser video tools, ComfyUI, or shell commands for ordinary local video generation; call generate_video directly.",
    ],
    parameters: Type.Object({
      prompt: Type.String({ description: "Detailed video prompt to render." }),
      negativePrompt: Type.Optional(Type.String({ description: "Optional negative prompt. Blank by default, using the model route defaults where applicable." })),
      aspectRatio: Type.Optional(stringEnum(ASPECT_RATIOS, { description: `Video aspect ratio. Default ${DEFAULT_ASPECT_RATIO}.` })),
      size: Type.Optional(stringEnum(SIZE_PRESETS, { description: `Output size preset. Default ${DEFAULT_SIZE}; small/standard are faster preview modes.` })),
      seconds: Type.Optional(Type.Number({ description: `Requested duration in seconds, 0.5-15. Default ${DEFAULT_DURATION_SECONDS}. The worker converts seconds to Wan's 4n+1 internal frame count and caps at ${MAX_INTERNAL_FRAMES} frames; at 24 fps the practical max is about 5 seconds.` })),
      fps: Type.Optional(Type.Number({ description: `Frames per second, 1-24. Default ${DEFAULT_FPS}.` })),
      steps: Type.Optional(Type.Number({ description: `Inference steps, 1-60. Default ${DEFAULT_STEPS}.` })),
      guidance: Type.Optional(Type.Number({ description: `Guidance scale, 0-20. Default ${DEFAULT_GUIDANCE}.` })),
      seed: Type.Optional(Type.Number({ description: "Optional seed, 0-2147483647. If omitted, the remote worker chooses a random seed." })),
      inputImagePath: Type.Optional(Type.String({ description: "Optional local source image path for image-to-video. Supported: PNG, JPG/JPEG, WebP, BMP. The source is copied to mac-mini-64 temporarily and deleted after generation." })),
      filename: Type.Optional(Type.String({ description: "Optional output filename stem or .mp4 filename. Sanitized." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: `Optional generation timeout, 60-14400 seconds. Default ${DEFAULT_TIMEOUT_SECONDS}.` })),
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
      const host = resolveHost();
      const baseDir = remoteBaseDir(host);
      const result = await runSsh(pi, host, `${shellQuote(`${baseDir}/bin/video-generate`)} --health`, 30_000, ctx.signal);
      ctx.ui.notify(result.stdout.trim() || "No health output", "info");
    },
  });

  pi.registerCommand("video-download-model", {
    description: "Download/cache the approved mac-mini-64 local video model.",
    handler: async (_args, ctx) => {
      const host = resolveHost();
      const baseDir = remoteBaseDir(host);
      const result = await runSsh(pi, host, `${shellQuote(`${baseDir}/bin/video-generate`)} --download-model`, 7_500_000, ctx.signal);
      ctx.ui.notify(result.stdout.trim() || "No download output", "info");
    },
  });
}
