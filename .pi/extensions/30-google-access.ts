import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { findAncestorFile, parseDotEnvFile } from "./lib/env";
import { truncate } from "./lib/text";

const ACTIONS = [
  "status",
  "services",
  "help",
  "schema",
  "call",
  "calendar_events",
  "drive_download_folder",
  "raw",
  "auth",
  "api",
] as const;
function StringEnum(values: readonly string[], options?: Record<string, unknown>) {
  return Type.Union(values.map((value) => Type.Literal(value)), options);
}

function firstNonEmptyLine(pathValue: string | undefined): string | undefined {
  if (!pathValue) return undefined;
  const path = resolve(pathValue.replace(/^~(?=\/|$)/, process.env.HOME ?? ""));
  if (!existsSync(path)) return undefined;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const candidate = line.trim();
    if (candidate) return candidate;
  }
  return undefined;
}

function loadGoogleEnv(cwd: string): { envPath?: string; apiKey?: string; apiKeySource?: string; dotenv: Record<string, string> } {
  const envPath = findAncestorFile(cwd, ".env");
  const dotenv = parseDotEnvFile(envPath);

  for (const [key, value] of Object.entries(dotenv)) {
    if (key.startsWith("GOOGLE_") && value && !process.env[key]) {
      process.env[key] = value;
    }
  }

  let apiKey = (process.env.GOOGLE_API_KEY || dotenv.GOOGLE_API_KEY || "").trim();
  let apiKeySource = apiKey ? "GOOGLE_API_KEY" : undefined;
  if (!apiKey) {
    const apiKeyFile = (
      process.env.GOOGLE_API_KEY_FILE ||
      process.env.GOOGLE_API_KEY_PATH ||
      dotenv.GOOGLE_API_KEY_FILE ||
      dotenv.GOOGLE_API_KEY_PATH ||
      ""
    ).trim();
    const fileKey = firstNonEmptyLine(apiKeyFile);
    if (fileKey) {
      apiKey = fileKey;
      apiKeySource = apiKeyFile;
      if (!process.env.GOOGLE_API_KEY) process.env.GOOGLE_API_KEY = fileKey;
    }
  }

  return { envPath, apiKey: apiKey || undefined, apiKeySource, dotenv };
}

function redactText(text: string, secrets: Array<string | undefined>): string {
  let redacted = text;
  for (const secret of secrets) {
    if (!secret || secret.length < 6) continue;
    redacted = redacted.split(secret).join("<redacted>");
  }
  redacted = redacted.replace(/("(?:key|apiKey|api_key|developerKey|access_token|refresh_token|token|client_secret)"\s*:\s*")[^"]+(")/gi, "$1<redacted>$2");
  redacted = redacted.replace(/((?:key|api_key|apiKey|developerKey|access_token|refresh_token|token|client_secret)=)[^&\s]+/gi, "$1<redacted>");
  return redacted;
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_/@%+=:,./-]+$/.test(value)) return value;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function shellJoin(args: string[]): string {
  return args.map(shellQuote).join(" ");
}

function splitShellWords(input: string): string[] {
  const words: string[] = [];
  let current = "";
  let quote: "'" | '"' | undefined;
  let escaping = false;

  for (const char of input) {
    if (escaping) {
      current += char;
      escaping = false;
      continue;
    }
    if (char === "\\" && quote !== "'") {
      escaping = true;
      continue;
    }
    if (quote) {
      if (char === quote) quote = undefined;
      else current += char;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (current) {
        words.push(current);
        current = "";
      }
      continue;
    }
    current += char;
  }
  if (escaping) current += "\\";
  if (quote) throw new Error("Unclosed quote in command string");
  if (current) words.push(current);
  return words;
}

function normalizeParts(value: any): string[] {
  if (Array.isArray(value)) return value.map((part) => String(part)).filter((part) => part.length > 0);
  if (typeof value === "string" && value.trim()) {
    const trimmed = value.trim();
    if (trimmed.includes(" ")) return splitShellWords(trimmed);
    if (trimmed.includes(".")) return trimmed.split(".").filter(Boolean);
    return [trimmed];
  }
  return [];
}

function buildWorkspacePath(params: any): string[] {
  const explicitPath = normalizeParts(params.path);
  if (explicitPath.length) return explicitPath;

  const parts: string[] = [];
  if (params.service) parts.push(String(params.service));
  parts.push(...normalizeParts(params.resources));
  if (!params.resources) parts.push(...normalizeParts(params.resource));
  parts.push(...normalizeParts(params.subresources));
  if (!params.subresources) parts.push(...normalizeParts(params.subresource));
  if (params.method) parts.push(String(params.method));
  return parts.filter(Boolean);
}

function appendJsonFlag(args: string[], flag: string, value: any): void {
  if (value === undefined || value === null || value === "") return;
  if (typeof value === "string") {
    args.push(flag, value);
    return;
  }
  args.push(flag, JSON.stringify(value));
}

function appendWorkspaceCommonFlags(args: string[], params: any, cwd: string): void {
  if (params.format) args.push("--format", String(params.format));
  if (params.apiVersion) args.push("--api-version", String(params.apiVersion));
  if (params.sanitize) args.push("--sanitize", String(params.sanitize));
  if (params.pageAll) args.push("--page-all");
  if (params.pageLimit !== undefined) args.push("--page-limit", String(params.pageLimit));
  if (params.pageDelay !== undefined) args.push("--page-delay", String(params.pageDelay));
  if (params.dryRun) args.push("--dry-run");
  if (params.upload) args.push("--upload", resolvePath(cwd, String(params.upload)));
  if (params.uploadContentType) args.push("--upload-content-type", String(params.uploadContentType));
  const outputPath = params.output ?? params.out;
  if (outputPath) {
    const resolved = resolvePath(cwd, String(outputPath));
    mkdirSync(dirname(resolved), { recursive: true });
    args.push("--output", resolved);
  }
  if (params.rawFlags) args.push(...splitShellWords(String(params.rawFlags)));
}

function resolvePath(cwd: string, pathValue: string): string {
  if (pathValue.startsWith("~")) return resolve(pathValue.replace(/^~(?=\/|$)/, process.env.HOME ?? ""));
  return resolve(cwd, pathValue);
}

function isCalendarEventsListPath(path: string[]): boolean {
  return path.length >= 3 && path[0] === "calendar" && path[1] === "events" && path[2] === "list";
}

function toRfc3339(value: any, boundary: "start" | "end"): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const text = String(value).trim();
  if (!text) return undefined;

  const dateOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    const year = Number(dateOnly[1]);
    const month = Number(dateOnly[2]) - 1;
    const day = Number(dateOnly[3]);
    const date =
      boundary === "start"
        ? new Date(year, month, day, 0, 0, 0, 0)
        : new Date(year, month, day, 23, 59, 59, 999);
    return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  return parsed.toISOString();
}

function calendarRangeForWhen(whenValue: any): { timeMin?: string; timeMax?: string } {
  const when = String(whenValue ?? "").trim().toLowerCase();
  if (!when) return {};

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);

  if (when === "today") return { timeMin: todayStart.toISOString(), timeMax: todayEnd.toISOString() };
  if (when === "tomorrow") {
    const tomorrowStart = new Date(todayStart);
    tomorrowStart.setDate(tomorrowStart.getDate() + 1);
    const tomorrowEnd = new Date(todayEnd);
    tomorrowEnd.setDate(tomorrowEnd.getDate() + 1);
    return { timeMin: tomorrowStart.toISOString(), timeMax: tomorrowEnd.toISOString() };
  }
  if (when === "week" || when === "next7d" || when === "next-7d" || when === "next_7_days") {
    const weekEnd = new Date(now);
    weekEnd.setDate(weekEnd.getDate() + 7);
    return { timeMin: now.toISOString(), timeMax: weekEnd.toISOString() };
  }
  if (when === "upcoming" || when === "next") {
    return { timeMin: now.toISOString() };
  }

  return {};
}

function withCalendarEventsDefaults(path: string[], params: any, mergedParams: Record<string, any>): Record<string, any> {
  if (!isCalendarEventsListPath(path)) return mergedParams;

  const output: Record<string, any> = { ...mergedParams };

  if (output.calendarId === undefined && params.calendarId !== undefined) output.calendarId = params.calendarId;
  if (output.calendarId === undefined) output.calendarId = "primary";

  if (output.timeZone === undefined && params.timeZone !== undefined) output.timeZone = params.timeZone;
  if (output.q === undefined && params.q !== undefined) output.q = params.q;
  if (output.maxResults === undefined && params.maxResults !== undefined) output.maxResults = params.maxResults;
  if (output.singleEvents === undefined && params.singleEvents !== undefined) output.singleEvents = params.singleEvents;
  if (output.orderBy === undefined && params.orderBy !== undefined) output.orderBy = params.orderBy;

  if (output.timeMin !== undefined) output.timeMin = toRfc3339(output.timeMin, "start") ?? output.timeMin;
  if (output.timeMax !== undefined) output.timeMax = toRfc3339(output.timeMax, "end") ?? output.timeMax;

  if (output.timeMin === undefined) {
    const topLevelTimeMin = toRfc3339(params.timeMin ?? params.start, "start");
    if (topLevelTimeMin !== undefined) output.timeMin = topLevelTimeMin;
  }
  if (output.timeMax === undefined) {
    const topLevelTimeMax = toRfc3339(params.timeMax ?? params.end, "end");
    if (topLevelTimeMax !== undefined) output.timeMax = topLevelTimeMax;
  }

  if (output.timeMin === undefined && output.timeMax === undefined) {
    const quickRange = calendarRangeForWhen(params.when);
    if (quickRange.timeMin !== undefined) output.timeMin = quickRange.timeMin;
    if (quickRange.timeMax !== undefined) output.timeMax = quickRange.timeMax;
  }

  if (output.timeMin === undefined && output.timeMax === undefined) output.timeMin = new Date().toISOString();
  if (output.singleEvents === undefined) output.singleEvents = true;
  if (output.orderBy === undefined && output.singleEvents !== false) output.orderBy = "startTime";
  if (output.maxResults === undefined) output.maxResults = 25;

  return output;
}

function buildWorkspaceArgs(params: any, cwd: string): { action: string; args: string[] } {
  let action = String(params.action || "").trim().toLowerCase();
  if (!action || action === "api") {
    if (params.command || params.args) action = "raw";
    else if (params.target || params.schema) action = "schema";
    else if (params.path || params.service || params.method) action = "call";
    else if (params.calendarId !== undefined || params.when !== undefined || params.timeMin !== undefined || params.timeMax !== undefined || params.start !== undefined || params.end !== undefined) action = "calendar_events";
    else action = "services";
  }

  if (action === "status") return { action, args: ["--help"] };
  if (action === "services") return { action, args: ["--help"] };

  if (action === "help") {
    const path = buildWorkspacePath(params);
    const args = path.length ? path : ["--help"];
    if (args.at(-1) !== "--help") args.push("--help");
    return { action, args };
  }

  if (action === "schema") {
    const target = String(params.target || params.schema || buildWorkspacePath(params).join(".")).trim();
    if (!target) throw new Error("workspace schema requires target, e.g. drive.files.list");
    const args = ["schema", target];
    if (params.resolveRefs) args.push("--resolve-refs");
    return { action, args };
  }

  if (action === "auth") {
    const args = ["auth"];
    const authAction = params.authAction ?? params.subcommand ?? params.method;
    if (authAction) args.push(String(authAction));
    if (Array.isArray(params.scopes) && params.scopes.length) args.push("--scopes", params.scopes.map(String).join(","));
    else if (typeof params.scopes === "string" && params.scopes.trim()) args.push("--scopes", params.scopes.trim());
    if (Array.isArray(params.positional)) args.push(...params.positional.map(String));
    if (params.rawFlags) args.push(...splitShellWords(String(params.rawFlags)));
    return { action, args };
  }

  let args: string[];
  if (action === "raw") {
    if (Array.isArray(params.args)) args = params.args.map(String).filter(Boolean);
    else if (params.command) args = splitShellWords(String(params.command));
    else throw new Error("workspace raw requires args or command");
    if (args[0] === "gws") args = args.slice(1);
  } else if (action === "call") {
    args = buildWorkspacePath(params);
    if (args.length < 2) throw new Error("workspace call requires path or service/resource/method, e.g. ['drive','files','list']");
  } else if (action === "calendar_events") {
    args = ["calendar", "events", "list"];
  } else {
    throw new Error(`Unsupported workspace action: ${action}`);
  }

  if (Array.isArray(params.positional)) args.push(...params.positional.map(String));

  const hasStructuredParams = params.params && typeof params.params === "object" && !Array.isArray(params.params);
  let mergedParams = { ...(params.fields ? { fields: params.fields } : {}), ...(hasStructuredParams ? params.params : {}) };
  mergedParams = withCalendarEventsDefaults(args, params, mergedParams);

  if (params.params && !hasStructuredParams) appendJsonFlag(args, "--params", params.params);
  else appendJsonFlag(args, "--params", Object.keys(mergedParams).length ? mergedParams : undefined);

  appendJsonFlag(args, "--json", params.json ?? params.body);
  appendWorkspaceCommonFlags(args, params, cwd);
  return { action, args };
}

function gwsExecutable(): string {
  const candidates = [process.env.GOOGLE_WORKSPACE_CLI_BIN, process.env.GWS_BIN, "/opt/homebrew/bin/gws", "/usr/local/bin/gws"];
  for (const candidate of candidates) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return "gws";
}

function formatMaybeJson(text: string, pretty: boolean): string {
  const trimmed = text.trim();
  if (!pretty || !trimmed) return trimmed;
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return trimmed;
  }
}

const DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder";
const DRIVE_GOOGLE_APPS_PREFIX = "application/vnd.google-apps.";
const DRIVE_EXPORTS: Record<string, [string, string]> = {
  "application/vnd.google-apps.document": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"],
  "application/vnd.google-apps.spreadsheet": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"],
  "application/vnd.google-apps.presentation": ["application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"],
  "application/vnd.google-apps.drawing": ["image/png", ".png"],
  "application/vnd.google-apps.script": ["application/vnd.google-apps.script+json", ".json"],
};

type DriveDownloadItem = {
  id: string;
  name: string;
  mimeType: string;
  modifiedTime?: string;
  size?: string;
  webViewLink?: string;
  rel?: string;
  localPath?: string;
};

function safeDriveName(name: string): string {
  const cleaned = String(name || "unnamed").replace(/\//g, "_").replace(/\0/g, "");
  if (!cleaned || cleaned === "." || cleaned === "..") return `_${cleaned || "unnamed"}`;
  return cleaned;
}

function escapeDriveQueryString(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function isPathWithin(parent: string, child: string): boolean {
  const rel = relative(resolve(parent), resolve(child));
  return rel === "" || (!!rel && !rel.startsWith("..") && !rel.startsWith("/") && !rel.startsWith("\\"));
}

function outputArgForCwd(cwd: string, pathValue: string): string {
  const rel = relative(resolve(cwd), resolve(pathValue));
  return rel || ".";
}

function uniqueRelPath(baseRel: string, id: string, used: Set<string>): string {
  if (!used.has(baseRel)) {
    used.add(baseRel);
    return baseRel;
  }
  let candidate = `${baseRel} (${id})`;
  let n = 2;
  while (used.has(candidate)) {
    candidate = `${baseRel} (${id}-${n})`;
    n += 1;
  }
  used.add(candidate);
  return candidate;
}

function uniqueLocalPath(pathValue: string): string {
  if (!existsSync(pathValue)) return pathValue;
  const dir = dirname(pathValue);
  const base = pathValue.slice(dir.length + 1);
  let candidate = join(dir, `${base}.duplicate`);
  let n = 2;
  while (existsSync(candidate)) {
    candidate = join(dir, `${base}.duplicate-${n}`);
    n += 1;
  }
  return candidate;
}

function setFileModifiedTime(pathValue: string, modifiedTime: string | undefined): void {
  if (!modifiedTime) return;
  const time = new Date(modifiedTime);
  if (Number.isNaN(time.getTime())) return;
  try {
    utimesSync(pathValue, time, time);
  } catch {
    // Best-effort metadata preservation only.
  }
}

function parseJsonOutput(text: string, label: string): any {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed || "{}");
  } catch (error: any) {
    throw new Error(`Could not parse ${label} as JSON: ${String(error?.message ?? error)}\n${truncate(trimmed, 2000)}`);
  }
}

async function execGwsForDrive(pi: ExtensionAPI, cwd: string, args: string[], envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal) {
  const result = await pi.exec(gwsExecutable(), args, { signal, cwd, timeout: Math.max(1, timeoutSeconds) * 1000 });
  const stdout = redactText(result.stdout ?? "", [envStatus.apiKey]);
  const stderr = redactText(result.stderr ?? "", [envStatus.apiKey]);
  if (result.code !== 0) {
    const commandText = shellJoin(["gws", ...args.map((arg) => redactText(arg, [envStatus.apiKey]))]);
    throw new Error(`gws failed (exit ${result.code}): ${commandText}\n${truncate(stderr || stdout || "No output", 4000)}`);
  }
  return { stdout, stderr };
}

async function gwsJsonForDrive(pi: ExtensionAPI, cwd: string, args: string[], envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<any> {
  const { stdout } = await execGwsForDrive(pi, cwd, args, envStatus, timeoutSeconds, signal);
  return parseJsonOutput(stdout, shellJoin(["gws", ...args]));
}

async function getDriveFolderMetadata(pi: ExtensionAPI, cwd: string, folderId: string, envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<DriveDownloadItem> {
  const params = {
    fileId: folderId,
    fields: "id,name,mimeType,modifiedTime,webViewLink",
    supportsAllDrives: true,
  };
  const metadata = await gwsJsonForDrive(pi, cwd, ["drive", "files", "get", "--params", JSON.stringify(params)], envStatus, timeoutSeconds, signal);
  if (metadata.mimeType !== DRIVE_FOLDER_MIME) throw new Error(`Drive file ${folderId} is not a folder (mimeType=${metadata.mimeType ?? "unknown"})`);
  return metadata;
}

async function findDriveFolderByExactName(pi: ExtensionAPI, cwd: string, folderName: string, envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<DriveDownloadItem> {
  const params = {
    q: `name = '${escapeDriveQueryString(folderName)}' and mimeType = '${DRIVE_FOLDER_MIME}' and trashed = false`,
    spaces: "drive",
    fields: "files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress)),nextPageToken",
    pageSize: 10,
    supportsAllDrives: true,
    includeItemsFromAllDrives: true,
  };
  const data = await gwsJsonForDrive(pi, cwd, ["drive", "files", "list", "--params", JSON.stringify(params)], envStatus, timeoutSeconds, signal);
  const files = Array.isArray(data.files) ? data.files : [];
  if (!files.length) throw new Error(`No non-trashed Drive folder found with exact name ${JSON.stringify(folderName)}`);
  if (files.length > 1) {
    const matches = files.map((file: any) => `${file.name} (${file.id})`).join(", ");
    throw new Error(`Multiple Drive folders found with exact name ${JSON.stringify(folderName)}; rerun with folderId. Matches: ${matches}`);
  }
  return files[0];
}

async function listDriveChildren(pi: ExtensionAPI, cwd: string, folderId: string, envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<DriveDownloadItem[]> {
  const files: DriveDownloadItem[] = [];
  let pageToken: string | undefined;
  do {
    const params: Record<string, any> = {
      q: `'${folderId}' in parents and trashed = false`,
      spaces: "drive",
      fields: "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
      pageSize: 1000,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    };
    if (pageToken) params.pageToken = pageToken;
    const data = await gwsJsonForDrive(pi, cwd, ["drive", "files", "list", "--params", JSON.stringify(params)], envStatus, timeoutSeconds, signal);
    if (Array.isArray(data.files)) files.push(...data.files);
    pageToken = data.nextPageToken;
  } while (pageToken);
  return files;
}

async function collectDriveFolder(pi: ExtensionAPI, cwd: string, folderId: string, parentRel: string, rows: DriveDownloadItem[], usedPaths: Set<string>, envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<void> {
  const children = await listDriveChildren(pi, cwd, folderId, envStatus, timeoutSeconds, signal);
  children.sort((a, b) => Number(a.mimeType !== DRIVE_FOLDER_MIME) - Number(b.mimeType !== DRIVE_FOLDER_MIME) || safeDriveName(a.name).localeCompare(safeDriveName(b.name)));
  for (const child of children) {
    const baseRel = parentRel ? `${parentRel}/${safeDriveName(child.name)}` : safeDriveName(child.name);
    child.rel = uniqueRelPath(baseRel, child.id, usedPaths);
    rows.push(child);
    if (child.mimeType === DRIVE_FOLDER_MIME) {
      await collectDriveFolder(pi, cwd, child.id, child.rel, rows, usedPaths, envStatus, timeoutSeconds, signal);
    }
  }
}

async function downloadDriveItem(pi: ExtensionAPI, cwd: string, destination: string, item: DriveDownloadItem, envStatus: ReturnType<typeof loadGoogleEnv>, timeoutSeconds: number, signal?: AbortSignal): Promise<string> {
  if (!item.rel) throw new Error(`Internal error: Drive item ${item.id} has no relative path`);
  const rawOutputPath = resolve(destination, item.rel);
  mkdirSync(dirname(rawOutputPath), { recursive: true });

  let outputPath = rawOutputPath;
  if (item.mimeType?.startsWith(DRIVE_GOOGLE_APPS_PREFIX) && item.mimeType !== DRIVE_FOLDER_MIME) {
    const [exportMime, ext] = DRIVE_EXPORTS[item.mimeType] ?? ["application/pdf", ".pdf"];
    if (!outputPath.toLowerCase().endsWith(ext.toLowerCase())) outputPath = `${outputPath}${ext}`;
    outputPath = uniqueLocalPath(outputPath);
    const params = { fileId: item.id, mimeType: exportMime };
    if (exportMime.includes("json")) {
      const { stdout } = await execGwsForDrive(pi, cwd, ["drive", "files", "export", "--params", JSON.stringify(params)], envStatus, timeoutSeconds, signal);
      writeFileSync(outputPath, stdout, "utf8");
    } else {
      await execGwsForDrive(pi, cwd, ["drive", "files", "export", "--params", JSON.stringify(params), "--output", outputArgForCwd(cwd, outputPath)], envStatus, timeoutSeconds, signal);
    }
  } else if (item.mimeType === "application/json") {
    // gws treats JSON media responses as normal API JSON and prints them to stdout even when --output is supplied.
    // Capture stdout and write the file ourselves so Drive JSON files are not silently skipped.
    outputPath = uniqueLocalPath(outputPath);
    const params = { fileId: item.id, alt: "media", supportsAllDrives: true };
    const { stdout } = await execGwsForDrive(pi, cwd, ["drive", "files", "get", "--params", JSON.stringify(params)], envStatus, timeoutSeconds, signal);
    writeFileSync(outputPath, stdout, "utf8");
  } else {
    outputPath = uniqueLocalPath(outputPath);
    const params = { fileId: item.id, alt: "media", supportsAllDrives: true };
    await execGwsForDrive(pi, cwd, ["drive", "files", "get", "--params", JSON.stringify(params), "--output", outputArgForCwd(cwd, outputPath)], envStatus, timeoutSeconds, signal);
  }

  setFileModifiedTime(outputPath, item.modifiedTime);
  item.localPath = outputArgForCwd(cwd, outputPath);
  return outputPath;
}

async function runDriveDownloadFolder(pi: ExtensionAPI, cwd: string, params: any, signal?: AbortSignal, onUpdate?: (update: any) => void) {
  const envStatus = loadGoogleEnv(cwd);
  const requestedTimeout = Number(params.timeout ?? 300);
  const timeoutSeconds = Number.isFinite(requestedTimeout) && requestedTimeout > 0 ? requestedTimeout : 300;
  const folderId = String(params.folderId ?? params.fileId ?? params.id ?? "").trim();
  const folderName = String(params.folderName ?? params.name ?? "").trim();

  try {
    if (!folderId && !folderName) throw new Error("drive_download_folder requires folderId (preferred) or exact folderName/name");
    const folder = folderId
      ? await getDriveFolderMetadata(pi, cwd, folderId, envStatus, timeoutSeconds, signal)
      : await findDriveFolderByExactName(pi, cwd, folderName, envStatus, timeoutSeconds, signal);

    const destinationInput = String(params.destination ?? params.dest ?? params.output ?? folder.name).trim();
    if (!destinationInput) throw new Error("drive_download_folder destination resolved to an empty path");
    const destination = resolvePath(cwd, destinationInput);
    if (!isPathWithin(cwd, destination)) {
      throw new Error(`Destination must be inside the current working directory because gws --output rejects outside paths. cwd=${cwd}; destination=${destination}`);
    }
    if (resolve(destination) === resolve(cwd)) {
      throw new Error("Destination must be a child directory of the current working directory; refusing to use or overwrite the project root.");
    }

    const dryRun = Boolean(params.dryRun);
    if (existsSync(destination)) {
      if (params.overwrite) {
        if (!dryRun) rmSync(destination, { recursive: true, force: true });
      } else if (readdirSync(destination).length) {
        throw new Error(`Destination exists and is not empty: ${destination}. Pass overwrite:true to replace it.`);
      }
    }
    if (!dryRun) mkdirSync(destination, { recursive: true });

    onUpdate?.({ content: [{ type: "text", text: `Listing Drive folder ${folder.name} (${folder.id}) recursively${dryRun ? " for dry run" : ""}...` }] });
    const rows: DriveDownloadItem[] = [];
    await collectDriveFolder(pi, cwd, folder.id, "", rows, new Set<string>(), envStatus, timeoutSeconds, signal);
    const folders = rows.filter((row) => row.mimeType === DRIVE_FOLDER_MIME);
    const files = rows.filter((row) => row.mimeType !== DRIVE_FOLDER_MIME);

    if (dryRun) {
      const relativeDestination = outputArgForCwd(cwd, destination);
      return {
        content: [
          {
            type: "text" as const,
            text: `Google Workspace drive_download_folder dry run succeeded.\nWould download ${files.length} files and create ${folders.length} folders from ${folder.name} (${folder.id}) to ${relativeDestination}. No local files were written.`,
          },
        ],
        details: {
          ok: true,
          product: "workspace",
          action: "drive_download_folder",
          dryRun: true,
          folder,
          destination: relativeDestination,
          fileCount: files.length,
          folderCount: folders.length,
          manifest: Boolean(params.manifest),
        },
      };
    }

    for (const folderItem of folders) mkdirSync(resolve(destination, folderItem.rel ?? safeDriveName(folderItem.name)), { recursive: true });

    onUpdate?.({ content: [{ type: "text", text: `Downloading ${files.length} files from ${folder.name} to ${outputArgForCwd(cwd, destination)}...` }] });
    for (let index = 0; index < files.length; index += 1) {
      await downloadDriveItem(pi, cwd, destination, files[index], envStatus, timeoutSeconds, signal);
      if ((index + 1) % 10 === 0 || index + 1 === files.length) {
        onUpdate?.({ content: [{ type: "text", text: `Downloaded ${index + 1}/${files.length} files from ${folder.name}` }] });
      }
    }

    if (params.manifest) {
      const manifestPath = resolve(destination, ".drive-download-manifest.json");
      writeFileSync(manifestPath, JSON.stringify({ sourceFolder: folder, downloadedAt: new Date().toISOString(), folderCount: folders.length, fileCount: files.length, items: rows }, null, 2), "utf8");
    }

    const relativeDestination = outputArgForCwd(cwd, destination);
    return {
      content: [
        {
          type: "text" as const,
          text: `Google Workspace drive_download_folder succeeded.\nDownloaded ${files.length} files and ${folders.length} folders from ${folder.name} (${folder.id}) to ${relativeDestination}.`,
        },
      ],
      details: {
        ok: true,
        product: "workspace",
        action: "drive_download_folder",
        dryRun: false,
        folder,
        destination: relativeDestination,
        fileCount: files.length,
        folderCount: folders.length,
        manifest: Boolean(params.manifest),
      },
    };
  } catch (error: any) {
    return {
      content: [
        {
          type: "text" as const,
          text: `Google Workspace drive_download_folder failed.\n\n${redactText(String(error?.message ?? error), [envStatus.apiKey])}`,
        },
      ],
      details: { ok: false, product: "workspace", action: "drive_download_folder", error: redactText(String(error?.message ?? error), [envStatus.apiKey]) },
    };
  }
}

async function runWorkspace(pi: ExtensionAPI, cwd: string, params: any, signal?: AbortSignal, onUpdate?: (update: any) => void) {
  const envStatus = loadGoogleEnv(cwd);
  const { action, args } = buildWorkspaceArgs(params, cwd);
  const executable = gwsExecutable();
  const commandText = shellJoin(["gws", ...args.map((arg) => redactText(arg, [envStatus.apiKey]))]);
  onUpdate?.({ content: [{ type: "text", text: `Running Google Workspace: ${commandText}` }] });

  try {
    const timeout = Math.max(1, Number(params.timeout ?? 300)) * 1000;
    const result = await pi.exec(executable, args, { signal, cwd, timeout });
    const stdout = redactText(result.stdout.trim(), [envStatus.apiKey]);
    const stderr = redactText(result.stderr.trim(), [envStatus.apiKey]);
    const rawOutput = stdout || stderr || (result.code === 0 ? "OK" : "No output");
    const formattedOutput = formatMaybeJson(rawOutput, Boolean(params.pretty));
    const ok = result.code === 0;
    const text = ok
      ? `Google Workspace ${action} succeeded.\nCommand: ${commandText}\n\n${truncate(formattedOutput, 20_000)}`
      : `Google Workspace ${action} failed (exit ${result.code}).\nCommand: ${commandText}\n\n${truncate(formattedOutput, 20_000)}`;

    return {
      content: [{ type: "text" as const, text }],
      details: {
        ok,
        product: "workspace",
        action,
        command: [executable, ...args].map((arg) => redactText(arg, [envStatus.apiKey])),
        code: result.code,
        stdout,
        stderr,
        apiKeyLoaded: Boolean(envStatus.apiKey),
        apiKeySource: envStatus.apiKeySource,
        envPath: envStatus.envPath,
      },
    };
  } catch (error: any) {
    return {
      content: [
        {
          type: "text" as const,
          text: `Google Workspace ${action} failed before execution.\nCommand: ${commandText}\n\n${redactText(String(error?.message ?? error), [envStatus.apiKey])}`,
        },
      ],
      details: {
        ok: false,
        product: "workspace",
        action,
        command: [executable, ...args].map((arg) => redactText(arg, [envStatus.apiKey])),
        error: redactText(String(error?.message ?? error), [envStatus.apiKey]),
        apiKeyLoaded: Boolean(envStatus.apiKey),
        apiKeySource: envStatus.apiKeySource,
        envPath: envStatus.envPath,
      },
    };
  }
}

async function executeGoogleWorkspace(pi: ExtensionAPI, cwd: string, params: any, signal?: AbortSignal, onUpdate?: (update: any) => void) {
  const action = String(params.action ?? "").trim().toLowerCase();
  if (action === "drive_download_folder") return runDriveDownloadFolder(pi, cwd, { ...params, product: "workspace" }, signal, onUpdate);
  return runWorkspace(pi, cwd, { ...params, product: "workspace" }, signal, onUpdate);
}

const GOOGLE_TOOL_DESCRIPTION =
  "Google Workspace via the gws CLI for Drive/Gmail/Docs/Sheets/Calendar.";
const GOOGLE_TOOL_PARAMETERS = Type.Object({
  product: Type.Optional(Type.Literal("workspace", { description: "Workspace product selector." })),
  action: Type.Optional(StringEnum(ACTIONS, { description: "status/services/help/schema/call/calendar_events/drive_download_folder/raw/auth/api." })),
  path: Type.Optional(Type.Array(Type.String(), { description: "gws path, e.g. ['drive','files','list']." })),
  service: Type.Optional(Type.String({ description: "Workspace service." })),
  resource: Type.Optional(Type.String({ description: "API resource." })),
  resources: Type.Optional(Type.Array(Type.String(), { description: "Workspace resource path." })),
  subresource: Type.Optional(Type.String({ description: "Workspace subresource." })),
  subresources: Type.Optional(Type.Array(Type.String(), { description: "Workspace subresources." })),
  method: Type.Optional(Type.String({ description: "Workspace API method." })),
  target: Type.Optional(Type.String({ description: "Schema target, e.g. drive.files.list." })),
  params: Type.Optional(Type.Record(Type.String(), Type.Any(), { description: "Query/path params; no API keys." })),
  calendarId: Type.Optional(Type.String({ description: "Calendar ID; default primary." })),
  when: Type.Optional(Type.String({ description: "Calendar shortcut window." })),
  timeMin: Type.Optional(Type.String({ description: "Start time/date." })),
  timeMax: Type.Optional(Type.String({ description: "End time/date." })),
  start: Type.Optional(Type.String({ description: "Alias for timeMin." })),
  end: Type.Optional(Type.String({ description: "Alias for timeMax." })),
  timeZone: Type.Optional(Type.String({ description: "Response timezone." })),
  q: Type.Optional(Type.String({ description: "Search/free-text query." })),
  singleEvents: Type.Optional(Type.Boolean({ description: "Expand recurring events." })),
  orderBy: Type.Optional(Type.String({ description: "Order by field." })),
  body: Type.Optional(Type.Any({ description: "Workspace request body." })),
  json: Type.Optional(Type.Any({ description: "Alias for body." })),
  maxResults: Type.Optional(Type.Number({ description: "Calendar max results or Workspace parameter shortcut." })),
  pageAll: Type.Optional(Type.Boolean({ description: "Auto-paginate." })),
  pageLimit: Type.Optional(Type.Number({ description: "Workspace page limit." })),
  pageDelay: Type.Optional(Type.Number({ description: "Page delay ms." })),
  format: Type.Optional(StringEnum(["json", "table", "yaml", "csv"] as const, { description: "Workspace format." })),
  fields: Type.Optional(Type.String({ description: "Partial fields." })),
  upload: Type.Optional(Type.String({ description: "Upload path." })),
  uploadContentType: Type.Optional(Type.String({ description: "Upload MIME." })),
  output: Type.Optional(Type.String({ description: "Output path." })),
  folderId: Type.Optional(Type.String({ description: "Drive folder ID for action:'drive_download_folder'." })),
  fileId: Type.Optional(Type.String({ description: "Drive file/folder ID alias; folder ID for action:'drive_download_folder'." })),
  id: Type.Optional(Type.String({ description: "Drive item ID alias; folder ID for action:'drive_download_folder'." })),
  folderName: Type.Optional(Type.String({ description: "Exact Drive folder name for action:'drive_download_folder' when folderId is unavailable." })),
  name: Type.Optional(Type.String({ description: "Exact Drive folder name alias for action:'drive_download_folder'." })),
  destination: Type.Optional(Type.String({ description: "Local destination path under the current working directory for action:'drive_download_folder'." })),
  dest: Type.Optional(Type.String({ description: "Alias for destination." })),
  overwrite: Type.Optional(Type.Boolean({ description: "For action:'drive_download_folder', replace an existing non-empty local destination." })),
  manifest: Type.Optional(Type.Boolean({ description: "For action:'drive_download_folder', write .drive-download-manifest.json in the destination." })),
  args: Type.Optional(Type.Array(Type.String(), { description: "Raw gws args." })),
  command: Type.Optional(Type.String({ description: "Raw gws command." })),
  authAction: Type.Optional(Type.String({ description: "Auth subcommand." })),
  scopes: Type.Optional(Type.Union([Type.String(), Type.Array(Type.String())], { description: "Auth scopes." })),
  resolveRefs: Type.Optional(Type.Boolean({ description: "Resolve schema refs." })),
  apiVersion: Type.Optional(Type.String({ description: "API version." })),
  sanitize: Type.Optional(Type.String({ description: "gws sanitize option." })),
  dryRun: Type.Optional(Type.Boolean({ description: "Dry run; for action:'drive_download_folder', list/count recursively without writing local files or deleting existing destinations." })),
  rawFlags: Type.Optional(Type.String({ description: "Extra gws flags." })),
  timeout: Type.Optional(Type.Number({ description: "Timeout sec." })),
  pretty: Type.Optional(Type.Boolean({ description: "Pretty JSON." })),
});

function registerGoogleTool(pi: ExtensionAPI, toolName: string, label: string) {
  pi.registerTool({
    name: toolName,
    label,
    description: GOOGLE_TOOL_DESCRIPTION,
    parameters: GOOGLE_TOOL_PARAMETERS,
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      return executeGoogleWorkspace(pi, ctx.cwd, params, signal, onUpdate);
    },
  });
}

function registerGoogleCommand(pi: ExtensionAPI, commandName: string, description: string) {
  pi.registerCommand(commandName, {
    description,
    handler: async (args, ctx) => {
      const trimmed = args.trim();
      try {
        if (!trimmed || trimmed === "status") {
          const envStatus = loadGoogleEnv(ctx.cwd);
          const status = `google_workspace: gws=${gwsExecutable()}; .env=${envStatus.envPath ?? "not found"}`;
          ctx.ui.notify(status, "info");
          return;
        }

        const words = splitShellWords(trimmed);
        const product = words.shift()?.toLowerCase();
        if (product === "workspace" || product === "gws") {
          const result = await executeGoogleWorkspace(pi, ctx.cwd, { product: "workspace", action: "raw", args: words });
          ctx.ui.notify(String(result.content?.[0]?.text ?? "Done").slice(0, 4000), result.details?.ok === false ? "error" : "info");
          return;
        }
        ctx.ui.notify("Usage: /google_workspace status | workspace <gws args...>", "warning");
      } catch (error: any) {
        ctx.ui.notify(`google_workspace error: ${String(error?.message ?? error)}`, "error");
      }
    },
  });
}

export default function registerGoogleWorkspace(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    loadGoogleEnv(ctx.cwd);
  });

  registerGoogleTool(pi, "google_workspace", "Google Workspace");

  registerGoogleCommand(
    pi,
    "google_workspace",
    "Run the Google Workspace helper. Examples: /google_workspace status | /google_workspace workspace drive files list --params '{\"pageSize\":2}' | /google_workspace workspace calendar events list --params '{\"calendarId\":\"primary\",\"timeMin\":\"2026-05-11T00:00:00Z\"}' | google_workspace action:'drive_download_folder' folderId:'...' destination:'projects/name'"
  );
}
