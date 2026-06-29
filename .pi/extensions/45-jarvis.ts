import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { truncate } from "./lib/text";

const DEFAULT_JARVIS_ROOT = resolve(process.env.JARVIS_ROOT || process.cwd());
const ACTIONS = [
  "help",
  "status",
  "look",
  "photo",
  "video",
  "video-until",
  "analyze-view",
  "speak",
  "cast-status",
  "cast-volume",
  "cast-mute",
  "cast-stop",
  "cast-youtube",
  "cast-play-url",
  "cast-spotify-devices",
  "cast-spotify",
  "cast-spotify-pause",
  "cast-spotify-next",
  "cast-spotify-previous",
  "cast-spotify-prev",
  "cast-spotify-volume",
  "cast-spotify-queue-add",
  "cast-spotify-add-queue",
  "cast-spotify-queue",
  "cast-spotify-seek",
  "cast-spotify-shuffle",
  "cast-spotify-repeat",
  "plug-list",
  "plug-status",
  "plug-on",
  "plug-off",
  "plug-toggle",
  "plug-discover",
  "plug-save-discovery",
  "purifier-status",
  "purifier-set",
] as const;
const DEVICES = ["tv", "speakers"] as const;
const MUTE_STATES = ["on", "off", "toggle"] as const;
const SMART_PLUG_ACTIONS = ["list", "status", "on", "off", "toggle", "discover", "save-discovery"] as const;
const PURIFIER_SETTINGS = ["power", "mode", "speed", "display", "child-lock", "light-detection", "auto-preference", "timer"] as const;

type JarvisAction = typeof ACTIONS[number];
type SmartPlugAction = typeof SMART_PLUG_ACTIONS[number];
type PurifierSetting = typeof PURIFIER_SETTINGS[number];
type Device = typeof DEVICES[number];

type JarvisParams = {
  action: JarvisAction;
  device?: Device;
  text?: string;
  question?: string;
  prompt?: string;
  condition?: string;
  query?: string;
  url?: string;
  contentType?: string;
  spotifyUri?: string;
  resume?: boolean;
  spotifyDeviceName?: string;
  spotifyDeviceId?: string;
  spotifyType?: "track" | "album" | "playlist" | "artist" | "any";
  spotifyQueueType?: "track" | "episode";
  market?: string;
  position?: string;
  timestamp?: string;
  positionMs?: number;
  repeatState?: "off" | "context" | "track" | "toggle";
  limit?: number;
  spotifyClientId?: string;
  spotifyClientSecret?: string;
  spotifyRefreshToken?: string;
  level?: number;
  state?: "on" | "off" | "toggle";
  quitApp?: boolean;
  enqueue?: boolean;
  noSearch?: boolean;
  noCast?: boolean;
  duration?: number;
  maxDuration?: number;
  interval?: number;
  output?: string;
  timeout?: number;
  dashboardUrl?: string;
  quality?: number;
  castTimeout?: number;
  omlxBaseUrl?: string;
  omlxTimeout?: number;
  model?: string;
  fallbackModel?: string;
  systemPrompt?: string;
  maxTokens?: number;
  temperature?: number;
  imageMaxSide?: number;
  jpegQuality?: number;
  skipModelCheck?: boolean;
  saveFrames?: boolean;
  frameOutputDir?: string;
  voice?: string;
  rate?: number;
  maxChars?: number;
  servePort?: number;
  serveHost?: string;
  postCastServeSeconds?: number;
  plug?: string;
  plugConfig?: string;
  discoveryTarget?: string;
  plugTimeout?: number;
  purifier?: string;
  setting?: PurifierSetting;
  value?: string;
  minutes?: number;
  roomSize?: number;
  purifierTimeout?: number;
};

type SmartPlugParams = {
  action: SmartPlugAction;
  plug?: string;
  plugConfig?: string;
  discoveryTarget?: string;
  timeout?: number;
};

function findOperationJarvisDir(cwd: string): string {
  let current = resolve(cwd);
  while (true) {
    const candidate = join(current, "projects", "operation-jarvis");
    if (existsSync(join(candidate, "jarvis.py"))) return candidate;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return join(DEFAULT_JARVIS_ROOT, "projects", "operation-jarvis");
}

function findProjectRoot(cwd: string): string {
  let current = resolve(cwd);
  while (true) {
    if (existsSync(join(current, ".pi")) && existsSync(join(current, "projects"))) return current;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return DEFAULT_JARVIS_ROOT;
}

function pythonPath(cwd: string): string {
  const root = findProjectRoot(cwd);
  const operationJarvisPython = join(root, "projects", "operation-jarvis", ".venv", "bin", "python");
  if (existsSync(operationJarvisPython)) return operationJarvisPython;
  const rootPython = join(root, ".venv", "bin", "python");
  if (existsSync(rootPython)) return rootPython;
  return "python3";
}

function textFromPayload(payload: any): string {
  if (!payload) return "No Operation JARVIS output.";
  if (payload.action === "help" || payload.guide) {
    return JSON.stringify({ summary: payload.summary, guide: payload.guide }, null, 2);
  }
  if (payload.summary) return String(payload.summary);
  if (payload.answer) return String(payload.answer);
  if (payload.query) return String(payload.query);
  if (payload.stdout) return String(payload.stdout);
  if (payload.error) return `Operation JARVIS error: ${payload.error}`;
  return JSON.stringify(payload, null, 2);
}

function add(args: string[], flag: string, value: string | number | boolean | undefined | null) {
  if (value === undefined || value === null || value === false) return;
  if (value === true) args.push(flag);
  else args.push(flag, String(value));
}

function appendDashboardCameraArgs(args: string[], params: JarvisParams) {
  add(args, "--dashboard-url", params.dashboardUrl);
  add(args, "--timeout", params.timeout);
}


function appendVisionArgs(args: string[], params: JarvisParams) {
  add(args, "--omlx-base-url", params.omlxBaseUrl);
  add(args, "--omlx-timeout", params.omlxTimeout);
  add(args, "--model", params.model);
  if (params.fallbackModel !== undefined) add(args, "--fallback-model", params.fallbackModel);
  add(args, "--system-prompt", params.systemPrompt);
  add(args, "--max-tokens", params.maxTokens);
  add(args, "--temperature", params.temperature);
  add(args, "--image-max-side", params.imageMaxSide);
  add(args, "--jpeg-quality", params.jpegQuality);
  add(args, "--skip-model-check", params.skipModelCheck);
}

function appendSpeakArgs(args: string[], params: JarvisParams) {
  add(args, "--device", params.device ?? "speakers");
  add(args, "--cast-timeout", params.castTimeout);
  add(args, "--voice", params.voice);
  add(args, "--rate", params.rate);
  add(args, "--max-chars", params.maxChars);
  add(args, "--serve-port", params.servePort);
  add(args, "--serve-host", params.serveHost);
  add(args, "--post-cast-serve-seconds", params.postCastServeSeconds);
}

function appendSpotifyControlArgs(args: string[], params: JarvisParams) {
  add(args, "--spotify-client-id", params.spotifyClientId);
  add(args, "--spotify-client-secret", params.spotifyClientSecret);
  add(args, "--spotify-refresh-token", params.spotifyRefreshToken);
  add(args, "--spotify-device-name", params.spotifyDeviceName);
  add(args, "--spotify-device-id", params.spotifyDeviceId);
}

function appendSpotifyArgs(args: string[], params: JarvisParams) {
  appendSpotifyControlArgs(args, params);
  add(args, "--spotify-type", params.spotifyType);
  add(args, "--market", params.market);
}

function appendAnalyzeArgs(args: string[], params: JarvisParams) {
  appendDashboardCameraArgs(args, params);
  appendVisionArgs(args, params);
  add(args, "--duration", params.duration);
  add(args, "--interval", params.interval);
  add(args, "--prompt", params.prompt ?? params.question);
  add(args, "--output", params.output);
  add(args, "--quality", params.quality);
  if (params.saveFrames === false) args.push("--no-save-frames");
  else if (params.saveFrames === true) args.push("--save-frames");
  add(args, "--frame-output-dir", params.frameOutputDir);
}

function appendVideoUntilArgs(args: string[], params: JarvisParams) {
  appendDashboardCameraArgs(args, params);
  appendVisionArgs(args, params);
  add(args, "--max-duration", params.maxDuration);
  add(args, "--interval", params.interval);
  add(args, "--output", params.output);
  add(args, "--quality", params.quality);
}

function appendSmartPlugArgs(args: string[], params: Pick<JarvisParams, "plugConfig" | "discoveryTarget" | "plugTimeout">) {
  add(args, "--plug-config", params.plugConfig);
  add(args, "--discovery-target", params.discoveryTarget);
  add(args, "--plug-timeout", params.plugTimeout);
}

function appendDedicatedSmartPlugArgs(args: string[], params: SmartPlugParams) {
  appendSmartPlugArgs(args, {
    plugConfig: params.plugConfig,
    discoveryTarget: params.discoveryTarget,
    plugTimeout: params.timeout,
  });
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function requireText(value: unknown, name: string): string {
  const text = cleanText(value);
  if (!text) throw new Error(`${name} is required`);
  return text;
}

function normalizeSmartPlugAction(value: unknown): SmartPlugAction | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim().toLowerCase().replace(/[\s_]+/g, "-");
  if ((SMART_PLUG_ACTIONS as readonly string[]).includes(normalized)) return normalized as SmartPlugAction;

  const aliases: Record<string, SmartPlugAction> = {
    devices: "list",
    "list-plugs": "list",
    ls: "list",
    scan: "discover",
    discovery: "discover",
    rescan: "discover",
    check: "status",
    get: "status",
    "get-status": "status",
    state: "status",
    "turn-on": "on",
    "switch-on": "on",
    "power-on": "on",
    enable: "on",
    true: "on",
    "turn-off": "off",
    "switch-off": "off",
    "power-off": "off",
    disable: "off",
    false: "off",
    flip: "toggle",
    switch: "toggle",
    "toggle-power": "toggle",
  };
  return aliases[normalized];
}

function normalizeSmartPlugName(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 1) {
    return `plug-${value}`;
  }
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  if (!text) return undefined;
  const normalized = text.toLowerCase().replace(/[\s_]+/g, "-");
  const match = normalized.match(/^(?:plug|p)?-?(\d+)$/);
  if (match) return `plug-${match[1]}`;
  return normalized;
}

function prepareSmartPlugArguments(args: unknown): unknown {
  if (!args || typeof args !== "object" || Array.isArray(args)) return args;
  const input = args as Record<string, unknown>;
  const next: Record<string, unknown> = { ...input };

  const action = normalizeSmartPlugAction(input.action ?? input.command ?? input.operation);
  if (action) next.action = action;

  const plug = normalizeSmartPlugName(input.plug ?? input.plugName ?? input.name ?? input.device);
  if (plug) next.plug = plug;

  if (next.timeout === undefined && typeof input.plugTimeout === "number") next.timeout = input.plugTimeout;

  delete next.command;
  delete next.operation;
  delete next.plugName;
  delete next.name;
  delete next.device;
  delete next.plugTimeout;
  return next;
}

function buildJarvisArgs(params: JarvisParams): string[] {
  const action = params.action;
  if (action === "help") {
    return ["help"];
  }

  if (action === "status") {
    const args = ["status"];
    appendDashboardCameraArgs(args, params);
    add(args, "--device", params.device ?? "tv");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--no-cast", params.noCast);
    return args;
  }

  if (action === "look" || action === "photo") {
    const args = ["look"];
    appendDashboardCameraArgs(args, params);
    add(args, "--output", params.output);
    add(args, "--quality", params.quality);
    return args;
  }

  if (action === "video") {
    const args = ["video"];
    appendDashboardCameraArgs(args, params);
    add(args, "--duration", params.duration);
    add(args, "--output", params.output);
    return args;
  }

  if (action === "video-until") {
    const condition = requireText(params.condition, "condition");
    const args = ["video-until"];
    appendVideoUntilArgs(args, params);
    args.push(condition);
    return args;
  }

  if (action === "analyze-view") {
    const args = ["analyze-view"];
    appendAnalyzeArgs(args, params);
    return args;
  }


  if (action === "speak") {
    const text = requireText(params.text, "text");
    const args = ["speak"];
    appendSpeakArgs(args, params);
    args.push(text);
    return args;
  }

  if (action === "cast-status") {
    const args = ["cast-status"];
    add(args, "--device", params.device ?? "tv");
    add(args, "--cast-timeout", params.castTimeout);
    return args;
  }

  if (action === "cast-volume") {
    if (params.level === undefined) throw new Error("level is required");
    const args = ["cast-volume", String(params.level)];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    return args;
  }

  if (action === "cast-mute") {
    const args = ["cast-mute", params.state ?? "on"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    return args;
  }

  if (action === "cast-stop") {
    const args = ["cast-stop"];
    add(args, "--device", params.device ?? "tv");
    if (params.quitApp === false) args.push("--media-only");
    else args.push("--quit-app");
    add(args, "--cast-timeout", params.castTimeout);
    return args;
  }

  if (action === "cast-youtube") {
    const query = requireText(params.query, "query");
    const args = ["cast-youtube"];
    add(args, "--device", params.device ?? "tv");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--enqueue", params.enqueue);
    add(args, "--no-search", params.noSearch);
    args.push(query);
    return args;
  }

  if (action === "cast-play-url") {
    const url = requireText(params.url, "url");
    const args = ["cast-play-url"];
    add(args, "--device", params.device ?? "tv");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--type", params.contentType ?? "video/mp4");
    args.push(url);
    return args;
  }

  if (action === "cast-spotify-devices") {
    const args = ["cast-spotify-devices"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    appendSpotifyArgs(args, params);
    return args;
  }

  if (action === "cast-spotify") {
    const query = cleanText(params.query);
    const spotifyUri = cleanText(params.spotifyUri);
    if (!query && !spotifyUri && !params.resume) {
      throw new Error("cast-spotify requires query, spotifyUri, or resume=true");
    }
    const args = ["cast-spotify"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--spotify-uri", spotifyUri || undefined);
    add(args, "--resume", params.resume);
    appendSpotifyArgs(args, params);
    if (query) args.push(query);
    return args;
  }

  if (action === "cast-spotify-pause" || action === "cast-spotify-next" || action === "cast-spotify-previous" || action === "cast-spotify-prev") {
    const command = action === "cast-spotify-prev" ? "cast-spotify-previous" : action;
    const args = [command];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "cast-spotify-volume") {
    if (params.level === undefined) throw new Error("level is required");
    const args = ["cast-spotify-volume", String(params.level)];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "cast-spotify-queue-add" || action === "cast-spotify-add-queue") {
    const query = cleanText(params.query);
    const spotifyUri = cleanText(params.spotifyUri);
    if (!query && !spotifyUri) throw new Error("cast-spotify-queue-add requires query or spotifyUri");
    const args = ["cast-spotify-queue-add"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--spotify-uri", spotifyUri || undefined);
    add(args, "--spotify-queue-type", params.spotifyQueueType);
    add(args, "--market", params.market);
    appendSpotifyControlArgs(args, params);
    if (query) args.push(query);
    return args;
  }

  if (action === "cast-spotify-queue") {
    const args = ["cast-spotify-queue"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    add(args, "--limit", params.limit);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "cast-spotify-seek") {
    const position = cleanText(params.position ?? params.timestamp);
    if (!position && params.positionMs === undefined) throw new Error("cast-spotify-seek requires position/timestamp or positionMs");
    const args = ["cast-spotify-seek"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    if (params.positionMs !== undefined) add(args, "--position-ms", params.positionMs);
    else args.push(position);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "cast-spotify-shuffle") {
    const args = ["cast-spotify-shuffle", params.state ?? "toggle"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "cast-spotify-repeat") {
    const args = ["cast-spotify-repeat", params.repeatState ?? "toggle"];
    add(args, "--device", params.device ?? "speakers");
    add(args, "--cast-timeout", params.castTimeout);
    appendSpotifyControlArgs(args, params);
    return args;
  }

  if (action === "plug-list" || action === "plug-discover" || action === "plug-save-discovery") {
    const args = [action];
    appendSmartPlugArgs(args, params);
    return args;
  }

  if (action === "plug-status" || action === "plug-on" || action === "plug-off" || action === "plug-toggle") {
    const plug = requireText(params.plug, "plug");
    const args: string[] = [action];
    appendSmartPlugArgs(args, params);
    args.push(plug);
    return args;
  }

  if (action === "purifier-status") {
    const args = ["purifier-status"];
    add(args, "--purifier", params.purifier);
    add(args, "--purifier-timeout", params.purifierTimeout);
    return args;
  }

  if (action === "purifier-set") {
    const setting = requireText(params.setting, "setting") as PurifierSetting;
    const args = ["purifier-set"];
    add(args, "--purifier", params.purifier);
    add(args, "--purifier-timeout", params.purifierTimeout);
    add(args, "--state", params.state);
    add(args, "--level", params.level);
    add(args, "--minutes", params.minutes);
    add(args, "--room-size", params.roomSize);
    args.push(setting);
    if (params.value !== undefined && params.value !== null && String(params.value).trim()) {
      args.push(String(params.value).trim());
    }
    return args;
  }

  throw new Error(`Unsupported Operation JARVIS action: ${action}`);
}

function buildDedicatedSmartPlugArgs(params: SmartPlugParams): string[] {
  const action = params.action;
  if (action === "list") {
    const args = ["plug-list"];
    appendDedicatedSmartPlugArgs(args, params);
    return args;
  }
  if (action === "discover") {
    const args = ["plug-discover"];
    appendDedicatedSmartPlugArgs(args, params);
    return args;
  }
  if (action === "save-discovery") {
    const args = ["plug-save-discovery"];
    appendDedicatedSmartPlugArgs(args, params);
    return args;
  }

  const plug = requireText(params.plug, "plug");
  const args = [`plug-${action}`];
  appendDedicatedSmartPlugArgs(args, params);
  args.push(plug);
  return args;
}

function smartPlugTimeoutMs(params: SmartPlugParams): number {
  const timeout = params.timeout ?? 30;
  if (params.action === "discover" || params.action === "save-discovery") {
    return Math.ceil((timeout + 90) * 1000);
  }
  return Math.ceil((timeout + 45) * 1000);
}

function timeoutMs(params: JarvisParams): number {
  const cameraTimeout = params.timeout ?? 40;
  const castTimeout = params.castTimeout ?? (params.action.includes("youtube") ? 90 : 45);
  const postCast = params.postCastServeSeconds ?? 60;
  const duration = params.duration ?? 5;
  const maxDuration = params.maxDuration ?? 60;
  switch (params.action) {
    case "help":
      return 30_000;
    case "status":
    case "cast-status":
    case "cast-volume":
    case "cast-mute":
    case "cast-stop":
    case "cast-play-url":
    case "cast-spotify-devices":
    case "cast-spotify-pause":
    case "cast-spotify-next":
    case "cast-spotify-previous":
    case "cast-spotify-prev":
    case "cast-spotify-volume":
    case "cast-spotify-queue-add":
    case "cast-spotify-add-queue":
    case "cast-spotify-queue":
    case "cast-spotify-seek":
    case "cast-spotify-shuffle":
    case "cast-spotify-repeat":
      return Math.ceil(((params.noCast ? 10 : castTimeout + 30)) * 1000);
    case "cast-youtube":
    case "cast-spotify":
      return Math.ceil((castTimeout + 90) * 1000);
    case "speak":
      return Math.ceil((castTimeout + postCast + 90) * 1000);
    case "look":
    case "photo":
      return Math.ceil((cameraTimeout + 60) * 1000);
    case "video":
      return Math.ceil((cameraTimeout + duration + 120) * 1000);
    case "video-until":
      return Math.ceil((cameraTimeout + maxDuration + 240) * 1000);
    case "analyze-view":
      return Math.ceil((cameraTimeout + (params.duration ?? 3) + 240) * 1000);
    case "plug-list":
    case "plug-status":
    case "plug-on":
    case "plug-off":
    case "plug-toggle":
      return Math.ceil(((params.plugTimeout ?? 30) + 45) * 1000);
    case "plug-discover":
    case "plug-save-discovery":
      return Math.ceil(((params.plugTimeout ?? 30) + 90) * 1000);
    case "purifier-status":
      return Math.ceil(((params.purifierTimeout ?? 150) + 30) * 1000);
    case "purifier-set":
      return Math.ceil(((params.purifierTimeout ?? 150) + 60) * 1000);
    default:
      return 180_000;
  }
}

async function runJarvis(
  pi: ExtensionAPI,
  cwd: string,
  args: string[],
  signal: AbortSignal | undefined,
  timeout: number,
  onUpdate?: (update: any) => void,
) {
  const operationDir = findOperationJarvisDir(cwd);
  const adapterPath = join(operationDir, "jarvis.py");
  if (!existsSync(adapterPath)) {
    throw new Error(`Operation JARVIS adapter not found: ${adapterPath}`);
  }

  onUpdate?.({ content: [{ type: "text", text: "Running Operation JARVIS adapter..." }] });

  const command = ["--json", ...args];
  const python = pythonPath(cwd);
  const result = await pi.exec(python, [adapterPath, ...command], { signal, timeout });
  const raw = (result.stdout.trim() || result.stderr.trim()).trim();
  let payload: any;
  try {
    payload = raw ? JSON.parse(raw) : { ok: result.code === 0 };
  } catch {
    payload = { ok: result.code === 0, stdout: result.stdout.trim(), stderr: result.stderr.trim() };
  }

  if (result.code !== 0 || payload?.ok === false) {
    throw new Error(payload?.error || result.stderr.trim() || result.stdout.trim() || `jarvis.py exited with code ${result.code}`);
  }

  return {
    content: [{ type: "text" as const, text: truncate(textFromPayload(payload)) }],
    details: {
      ok: true,
      adapterPath,
      command: [python, adapterPath, ...command],
      ...payload,
    },
  };
}

export default function registerJarvis(pi: ExtensionAPI) {
  pi.registerTool({
    name: "jarvis",
    label: "Operation JARVIS",
    description: "Operation JARVIS tool loaded on demand with load_tools({ groups: [\"jarvis\"] }) for dashboard phone camera vision, Google Cast speech/media, Spotify Connect control, and local Kasa smart-plug control. Safe guide: action=help. Safe local status: action=status with noCast=true. Required fields: speak text; cast-youtube query; cast-play-url url; cast-volume/cast-spotify-volume level; cast-spotify query/spotifyUri/resume; cast-spotify-queue-add query/spotifyUri; cast-spotify-seek position/positionMs; video duration; video-until condition; plug actions need plug.",
    promptSnippet: "Operation JARVIS (load group `jarvis` first): `jarvis({action:\"help\"})` for guide; dashboard-camera look/video/analyze; Cast speak/status/volume/youtube; Spotify devices/play/pause/next/previous/volume/queue/seek/shuffle/repeat; smart plugs plug-list/status/on/off/toggle.",
    promptGuidelines: [
      "Only use `jarvis` after the `jarvis` tool group has been loaded with load_tools({ groups: [\"jarvis\"] }); then call `jarvis` directly.",
      "Use `jarvis({ action: \"help\" })` if you are unsure of parameters. Safe checks: `status` with `noCast: true`, or `cast-status` for a specific device.",
      "Common dashboard-camera calls: `look`; `analyze-view` with `question`; `video` with `duration`; `video-until` with `condition` and bounded `maxDuration`.",
      "Common Cast calls: `speak` with short `text` on `speakers`; `cast-status`/`cast-stop` on `tv` (`cast-stop` quits the Cast app by default); `cast-volume` with `level` 0..100; `cast-youtube` with `query`; `cast-play-url` with `url`.",
      "Spotify calls: `cast-spotify-devices` lists currently visible Spotify Connect devices; `cast-spotify` plays a `query`/`spotifyUri` or resumes with `resume:true`; `cast-spotify-pause`, `cast-spotify-next`, `cast-spotify-previous`, and `cast-spotify-volume` control playback. `cast-spotify-queue-add` adds a track/episode using `query` or `spotifyUri` plus optional `spotifyQueueType`; `cast-spotify-queue` reads the current queue; `cast-spotify-seek` seeks with `position`/`timestamp` like 1:30 or `positionMs`; `cast-spotify-shuffle` uses `state` on/off/toggle; `cast-spotify-repeat` uses `repeatState` off/context/track/toggle. Spotify credentials are already loaded from local .env when present; do not ask for or expose secrets.",
      "Spotify target guide: use `device:\"tv\"` and `device:\"speakers\"` for configured Cast aliases. Use `spotifyDeviceName` for an explicit Spotify Connect target from local private config or from `cast-spotify-devices`. Prefer names over device IDs because Spotify IDs can change.",
      "Common smart-plug calls: `plug-list`; `plug-status` with `plug`; `plug-on`/`plug-off`/`plug-toggle` with a configured plug name from local private config or from `plug-list`.",
      "Air purifier calls use exactly two actions: `purifier-status` for all read-only status/filter/air-quality info, and `purifier-set` with `setting` for writes. Supported purifier settings: power, mode, speed, display, child-lock, light-detection, auto-preference, timer. Use `value` for string values, `level` for speed, `minutes` for timer, and `state` for on/off/toggle where appropriate. VeSync writes may take up to a minute; wait for the tool result before issuing another purifier command.",
      "Always keep camera recording bounded. Keep spoken output brief; put detailed audit text in Discord.",
    ],
    parameters: Type.Object({
      action: StringEnum(ACTIONS, { description: "Choose one exact action. Use help for a safe machine-readable guide. Common: status, look, video, analyze-view, speak, cast-status, cast-spotify, plug-status, plug-on, plug-off, purifier-status, purifier-set." }),
      device: Type.Optional(StringEnum(DEVICES, { description: "Cast target alias: tv or speakers. Defaults to tv for media/status and speakers for speech/volume/mute/Spotify. Configure the underlying local device names privately." })),
      text: Type.Optional(Type.String({ description: "Required for action=speak. Short text to speak aloud; keep detailed answers in Discord." })),
      question: Type.Optional(Type.String({ description: "Preferred visual question for analyze-view. Use this instead of prompt for normal requests." })),
      prompt: Type.Optional(Type.String({ description: "Advanced explicit VLM prompt. Overrides question when supplied." })),
      condition: Type.Optional(Type.String({ description: "Required for video-until. Visual condition, e.g. 'a person is visible'." })),
      query: Type.Optional(Type.String({ description: "Required for cast-youtube. For cast-spotify, this is a Spotify search query (or URI/URL text). For cast-spotify-queue-add, this is the track/episode search query." })),
      url: Type.Optional(Type.String({ description: "Required for cast-play-url. Direct media URL." })),
      contentType: Type.Optional(Type.String({ description: "cast-play-url MIME type; default video/mp4." })),
      spotifyUri: Type.Optional(Type.String({ description: "cast-spotify: explicit Spotify URI or open.spotify.com URL." })),
      resume: Type.Optional(Type.Boolean({ description: "cast-spotify: resume current Spotify playback when no query/spotifyUri is provided." })),
      spotifyDeviceName: Type.Optional(Type.String({ description: "Spotify Connect device name override for cast-spotify* actions. Use an exact name from local private config or from cast-spotify-devices. Prefer names over IDs." })),
      spotifyDeviceId: Type.Optional(Type.String({ description: "Spotify Connect device id override for cast-spotify* actions. Use only if a name is ambiguous; IDs can change." })),
      spotifyType: Type.Optional(StringEnum(["track", "album", "playlist", "artist", "any"] as const, { description: "cast-spotify search type when query text is used; default track." })),
      spotifyQueueType: Type.Optional(StringEnum(["track", "episode"] as const, { description: "cast-spotify-queue-add search type when query text is used; default track." })),
      market: Type.Optional(Type.String({ description: "cast-spotify/cast-spotify-queue-add: Spotify market code (e.g. CA, US)." })),
      position: Type.Optional(Type.String({ description: "cast-spotify-seek timestamp, e.g. 90, 90s, 1:30, 1:02:03, or 90000ms." })),
      timestamp: Type.Optional(Type.String({ description: "Alias for position in cast-spotify-seek." })),
      positionMs: Type.Optional(Type.Number({ description: "cast-spotify-seek explicit seek position in milliseconds." })),
      repeatState: Type.Optional(StringEnum(["off", "context", "track", "toggle"] as const, { description: "cast-spotify-repeat state; default toggle. context repeats playlist/album, track repeats one item, off disables." })),
      limit: Type.Optional(Type.Number({ description: "cast-spotify-queue maximum queue items to read; default 20." })),
      spotifyClientId: Type.Optional(Type.String({ description: "Optional Spotify app client ID (else SPOTIFY_CLIENT_ID env)." })),
      spotifyClientSecret: Type.Optional(Type.String({ description: "Optional Spotify app client secret (else SPOTIFY_CLIENT_SECRET env)." })),
      spotifyRefreshToken: Type.Optional(Type.String({ description: "Optional Spotify refresh token (else SPOTIFY_REFRESH_TOKEN env)." })),
      level: Type.Optional(Type.Number({ description: "Required for cast-volume and cast-spotify-volume. Volume level 0..100." })),
      state: Type.Optional(StringEnum(MUTE_STATES, { description: "cast-mute state; default on. Also used for cast-spotify-shuffle as on/off/toggle." })),
      quitApp: Type.Optional(Type.Boolean({ description: "cast-stop: quit current Cast app for a stronger stop. Defaults true; set false to stop media only and leave the app open." })),
      enqueue: Type.Optional(Type.Boolean({ description: "YouTube actions: enqueue instead of play now." })),
      noSearch: Type.Optional(Type.Boolean({ description: "YouTube actions: require URL/video ID instead of searching." })),
      noCast: Type.Optional(Type.Boolean({ description: "status: skip Cast device check." })),
      plug: Type.Optional(Type.String({ description: "Smart-plug name or direct IP for plug-status/plug-on/plug-off/plug-toggle. Use a configured alias from private local config or run plug-list first." })),
      plugConfig: Type.Optional(Type.String({ description: "Optional smart-plug plugs.json path override." })),
      discoveryTarget: Type.Optional(Type.String({ description: "Optional Kasa discovery broadcast target, e.g. a LAN broadcast address." })),
      plugTimeout: Type.Optional(Type.Number({ description: "Smart-plug command timeout seconds." })),
      purifier: Type.Optional(Type.String({ description: "Optional VeSync air purifier name/CID/model override. Usually omit; default is configured locally in air-purifier/.env." })),
      setting: Type.Optional(StringEnum(PURIFIER_SETTINGS, { description: "Required for purifier-set. Choose one setting: power, mode, speed, display, child-lock, light-detection, auto-preference, or timer." })),
      value: Type.Optional(Type.String({ description: "purifier-set value. Examples: power on/off/toggle; mode auto/manual/sleep/pet; display on/off; auto-preference default/quiet/efficient; timer clear." })),
      minutes: Type.Optional(Type.Number({ description: "purifier-set setting=timer: timer minutes, 1..1440." })),
      roomSize: Type.Optional(Type.Number({ description: "purifier-set setting=auto-preference: optional room size in square feet." })),
      purifierTimeout: Type.Optional(Type.Number({ description: "Air purifier command timeout seconds; writes can take up to a minute to reflect." })),

      duration: Type.Optional(Type.Number({ description: "Required and >0 for video. Optional analysis duration seconds for analyze-view; default about 3." })),
      maxDuration: Type.Optional(Type.Number({ description: "video-until positive safety cap seconds; default 60. Always bound monitoring." })),
      interval: Type.Optional(Type.Number({ description: "Seconds between VLM checks/analyses." })),
      output: Type.Optional(Type.String({ description: "Output path for copied camera media or analysis logs. strftime tokens are accepted." })),
      timeout: Type.Optional(Type.Number({ description: "Dashboard camera command timeout seconds." })),
      dashboardUrl: Type.Optional(Type.String({ description: "Dashboard base URL; defaults to JARVIS_DASHBOARD_URL or localhost." })),
      quality: Type.Optional(Type.Number({ description: "JPEG snapshot quality from 0.1 to 1.0." })),
      castTimeout: Type.Optional(Type.Number({ description: "Cast command timeout seconds." })),
      omlxBaseUrl: Type.Optional(Type.String({ description: "oMLX/OpenAI-compatible VLM base URL." })),
      omlxTimeout: Type.Optional(Type.Number({ description: "Timeout seconds for each VLM request." })),
      model: Type.Optional(Type.String({ description: "Primary VLM model." })),
      fallbackModel: Type.Optional(Type.String({ description: "Fallback VLM model; empty disables." })),
      systemPrompt: Type.Optional(Type.String({ description: "System prompt for VLM calls." })),
      maxTokens: Type.Optional(Type.Number({ description: "Maximum VLM output tokens." })),
      temperature: Type.Optional(Type.Number({ description: "VLM sampling temperature." })),
      imageMaxSide: Type.Optional(Type.Number({ description: "Resize longest image side before VLM; 0 disables." })),
      jpegQuality: Type.Optional(Type.Number({ description: "JPEG quality for resized/recompressed VLM frames." })),
      skipModelCheck: Type.Optional(Type.Boolean({ description: "Skip initial oMLX /v1/models check." })),
      saveFrames: Type.Optional(Type.Boolean({ description: "analyze actions: save VLM frames; default true." })),
      frameOutputDir: Type.Optional(Type.String({ description: "Directory for saved analysis frames." })),
      voice: Type.Optional(Type.String({ description: "macOS say voice for speech." })),
      rate: Type.Optional(Type.Number({ description: "macOS say speech rate." })),
      maxChars: Type.Optional(Type.Number({ description: "Max spoken characters; 0 disables truncation." })),
      servePort: Type.Optional(Type.Number({ description: "Local HTTP server port for Cast speech audio." })),
      serveHost: Type.Optional(Type.String({ description: "LAN host/IP Chromecast should use for local Cast speech URL." })),
      postCastServeSeconds: Type.Optional(Type.Number({ description: "Seconds to keep local speech server alive after Cast command." })),
    }),
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      const params = rawParams as JarvisParams;
      if (params.duration !== undefined && params.duration <= 0) throw new Error("duration must be greater than 0");
      if (params.maxDuration !== undefined && params.maxDuration <= 0) throw new Error("maxDuration must be greater than 0");
      if (params.interval !== undefined && params.interval <= 0) throw new Error("interval must be greater than 0");
      if (params.level !== undefined && (params.level < 0 || params.level > 100)) throw new Error("level must be between 0 and 100");
      if (params.positionMs !== undefined && params.positionMs < 0) throw new Error("positionMs must be 0 or greater");
      if (params.limit !== undefined && params.limit <= 0) throw new Error("limit must be greater than 0");
      if (params.maxChars !== undefined && params.maxChars < 0) throw new Error("maxChars must be 0 or greater");
      if (params.postCastServeSeconds !== undefined && params.postCastServeSeconds < 0) throw new Error("postCastServeSeconds must be 0 or greater");
      const args = buildJarvisArgs(params);
      return runJarvis(pi, ctx.cwd, args, signal, timeoutMs(params), onUpdate);
    },
    renderCall(args, theme) {
      const action = typeof args.action === "string" ? args.action : "action";
      const detail = typeof args.condition === "string"
        ? args.condition
        : typeof args.question === "string"
          ? args.question
          : typeof args.text === "string"
            ? args.text.slice(0, 40)
            : typeof args.query === "string"
              ? args.query.slice(0, 40)
              : typeof args.plug === "string"
                ? args.plug
                : args.device ?? "";
      return new Text(`${theme.fg("toolTitle", "jarvis")} ${theme.fg("accent", action)} ${theme.fg("dim", detail)}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const action = result.details?.action ?? "done";
      const summary = result.details?.summary ?? result.details?.answer ?? "completed";
      return new Text(`${theme.fg("success", `✓ JARVIS ${action}`)} ${theme.fg("dim", String(summary).slice(0, 80))}`, 0, 0);
    },
  });

  pi.registerTool({
    name: "smart_plug",
    label: "Smart Plug",
    description: "Simple local-only TP-Link Kasa smart-plug control for Operation JARVIS. Normal calls need only action plus a configured plug alias. Use action=list without plug to see configured plugs. Uses the local network, not TP-Link cloud.",
    promptSnippet: "Local smart plugs: smart_plug({ action: 'status'|'on'|'off'|'toggle', plug: '<configured-plug-name>' }); smart_plug({ action: 'list' }).",
    promptGuidelines: [
      "Use smart_plug for local smart-plug power control instead of shell commands when the user asks to check, switch on, switch off, or toggle configured smart plugs.",
      "smart_plug normally needs only `{ action: \"status\"|\"on\"|\"off\"|\"toggle\", plug: \"<configured-plug-name>\" }`; use `{ action: \"list\" }` to see configured plugs.",
      "Map natural phrases to configured plug aliases from local private config before switching power.",
      "After smart_plug on/off/toggle, summarize the resulting plug state briefly.",
    ],
    parameters: Type.Object({
      action: StringEnum(SMART_PLUG_ACTIONS, { description: "Operation. Use list to show plugs; status/on/off/toggle with plug for normal control. discover/save-discovery are maintenance actions." }),
      plug: Type.Optional(Type.String({ description: "Plug name or direct IP. Required for status/on/off/toggle. Use action=list to see configured aliases. Natural phrases with spaces are normalized." })),
      plugConfig: Type.Optional(Type.String({ description: "Advanced: optional smart-plug plugs.json path override." })),
      discoveryTarget: Type.Optional(Type.String({ description: "Advanced: optional Kasa discovery broadcast target, e.g. a LAN broadcast address." })),
      timeout: Type.Optional(Type.Number({ description: "Advanced: smart-plug command timeout seconds; default 30." })),
    }),
    prepareArguments: prepareSmartPlugArguments,
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      const params = rawParams as SmartPlugParams;
      if (params.timeout !== undefined && params.timeout <= 0) throw new Error("timeout must be greater than 0");
      const args = buildDedicatedSmartPlugArgs(params);
      return runJarvis(pi, ctx.cwd, args, signal, smartPlugTimeoutMs(params), onUpdate);
    },
    renderCall(args, theme) {
      const action = typeof args.action === "string" ? args.action : "action";
      const detail = typeof args.plug === "string" ? args.plug : "";
      return new Text(`${theme.fg("toolTitle", "smart_plug")} ${theme.fg("accent", action)} ${theme.fg("dim", detail)}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const summary = result.details?.summary ?? "completed";
      return new Text(`${theme.fg("success", "✓ smart_plug")} ${theme.fg("dim", String(summary).slice(0, 80))}`, 0, 0);
    },
  });
}
