import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
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

type GenerateImageParams = {
  prompt: string;
  negativePrompt?: string;
  width?: number;
  height?: number;
  steps?: number;
  seed?: number;
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
  steps?: number;
  seed?: number;
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
const DEFAULT_WIDTH = 1024;
const DEFAULT_HEIGHT = 1024;
const DEFAULT_STEPS = 20;
const DEFAULT_TIMEOUT_SECONDS = 1200;
const DEFAULT_MAX_INLINE_BYTES = 8 * 1024 * 1024;
const MAX_INLINE_BYTES = positiveInteger(process.env.IMAGE_GENERATION_MAX_INLINE_BYTES, DEFAULT_MAX_INLINE_BYTES);
const LOCAL_OUTPUT_DIR = process.env.IMAGE_GENERATION_LOCAL_OUTPUT_DIR || "generated-images";

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

function expandLocalPath(value: string): string {
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return value;
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
  const configured = cleanString(process.env.IMAGE_GENERATION_REMOTE_DIR);
  return expandRemotePath(configured || `${host.homeDir}/image-generation`, host.homeDir);
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
  return [
    "Generated image with Qwen-Image-2512-8bit.",
    `Local: ${localPath}`,
    result.remotePath ? `Remote source deleted after copy: ${HOST_ALIAS}:${result.remotePath}` : undefined,
    metadataLocalPath ? `Metadata: ${metadataLocalPath}` : undefined,
    cleanedRemotePaths.length > 0 ? `Remote cleanup: deleted ${cleanedRemotePaths.length} file(s).` : undefined,
    `Model: ${MODEL}`, 
    `Seed: ${result.seed ?? "unknown"}`,
    `Steps: ${result.steps ?? "unknown"}`,
    `Size: ${result.width ?? "?"}x${result.height ?? "?"}, ${formatBytes(result.sizeBytes)}`,
    typeof result.elapsedSeconds === "number" ? `Elapsed: ${result.elapsedSeconds.toFixed(1)}s` : undefined,
    inlined ? "Image is attached inline." : `Image not inlined because it exceeds ${formatBytes(MAX_INLINE_BYTES)} or inlineImage=false.`,
  ].filter(Boolean).join("\n");
}

function safeRemoteCleanupPaths(baseDir: string, paths: Array<string | undefined | null>): string[] {
  const normalizedBase = baseDir.replace(/\/+$/, "");
  const allowedPrefixes = [`${normalizedBase}/outputs/`, `${normalizedBase}/inputs/`];
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

async function generateImage(pi: ExtensionAPI, params: GenerateImageParams, signal?: AbortSignal, onUpdate?: (partial: any) => void, cwd = process.cwd()) {
  const prompt = cleanPrompt(params.prompt);
  if (!prompt) throw new Error("generate_image requires a non-empty prompt.");
  const negativePrompt = cleanPrompt(params.negativePrompt || DEFAULT_NEGATIVE_PROMPT);
  const width = optionalInteger(params.width, "width", 256, 2048) ?? DEFAULT_WIDTH;
  const height = optionalInteger(params.height, "height", 256, 2048) ?? DEFAULT_HEIGHT;
  const steps = optionalInteger(params.steps, "steps", 1, 50) ?? DEFAULT_STEPS;
  const seed = optionalInteger(params.seed, "seed", 0, 2_147_483_647);
  const timeoutSeconds = optionalInteger(params.timeoutSeconds, "timeoutSeconds", 60, 7200) ?? DEFAULT_TIMEOUT_SECONDS;
  const inlineImage = params.inlineImage !== false;

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
  const job = {
    jobId,
    filename,
    prompt,
    negativePrompt,
    width,
    height,
    steps,
    seed,
    timeoutSeconds,
  };
  writeFileSync(localJobFile, JSON.stringify(job, null, 2), "utf8");

  onUpdate?.({ content: [{ type: "text" as const, text: `Preparing ${HOST_ALIAS} image job ${jobId}...` }] });
  await runSsh(pi, host, `mkdir -p ${shellQuote(remoteInputsDir)} ${shellQuote(`${baseDir}/outputs`)} ${shellQuote(`${baseDir}/logs`)}`, 30_000, signal);
  await runScp(pi, host, [localJobFile, remoteSpec(host, remoteJobFile)], 60_000, signal);

  onUpdate?.({ content: [{ type: "text" as const, text: `Generating image on ${HOST_ALIAS} with ${MODEL} (${width}x${height}, ${steps} steps)...` }] });
  const remoteCommand = [
    `export IMAGE_GENERATION_DIR=${shellQuote(baseDir)}`,
    `${shellQuote(`${baseDir}/bin/image-generate`)} --job-file ${shellQuote(remoteJobFile)}`,
  ].join("\n");
  const generation = await pi.exec("ssh", sshArgs(host, remoteCommand), { timeout: (timeoutSeconds + 60) * 1000, signal });
  const remoteResult = parseRemoteResult(generation.stdout, generation.stderr, generation.code);
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

  onUpdate?.({ content: [{ type: "text" as const, text: "Deleting remote image copy from mac-mini-64..." }] });
  const cleanedRemotePaths = await cleanupRemoteFiles(pi, host, baseDir, [remoteResult.remotePath, remoteResult.metadataPath, remoteJobFile], signal);

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
      cleanedRemotePaths,
      inlined: shouldInline,
      sizeBytes: stat.size,
    },
  };
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

export default function registerJarvisImage(pi: ExtensionAPI) {
  pi.registerTool({
    name: "generate_image",
    label: "Generate Image",
    description: `Generate exactly one image on mac-mini-64 using the single approved headless model: ${MODEL}. The tool sends the prompt over SSH, runs mflux/Qwen on the Mini, copies the PNG back locally, and returns the local path plus optional inline PNG. No alternate models or fallback models are available.`,
    promptSnippet: "Generate a local PNG image on mac-mini-64 with Qwen-Image-2512-8bit and copy it back to this project.",
    promptGuidelines: [
      "Use generate_image when sir asks to create, generate, render, or make an image locally.",
      `generate_image uses only ${MODEL}; do not offer or request alternate image models for this tool.`,
      "Keep prompts visually descriptive. Default to 1024x1024 and 20 steps unless sir asks for a specific size or speed/quality tradeoff.",
      "Do not use ComfyUI, browser image tools, Draw Things, or shell commands for ordinary image generation; call generate_image directly.",
    ],
    parameters: Type.Object({
      prompt: Type.String({ description: "Detailed image prompt to render." }),
      negativePrompt: Type.Optional(Type.String({ description: `Optional negative prompt. Defaults to: ${DEFAULT_NEGATIVE_PROMPT}` })),
      width: Type.Optional(Type.Number({ description: `Image width in pixels, 256-2048. Default ${DEFAULT_WIDTH}.` })),
      height: Type.Optional(Type.Number({ description: `Image height in pixels, 256-2048. Default ${DEFAULT_HEIGHT}.` })),
      steps: Type.Optional(Type.Number({ description: `Inference steps, 1-50. Default ${DEFAULT_STEPS}.` })),
      seed: Type.Optional(Type.Number({ description: "Optional seed, 0-2147483647. If omitted, the remote worker chooses a random seed." })),
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
