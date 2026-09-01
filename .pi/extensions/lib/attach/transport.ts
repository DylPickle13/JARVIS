import { execFile } from "node:child_process";
import { request as httpRequest, type IncomingMessage, type RequestOptions } from "node:http";
import { basename, resolve } from "node:path";
import { promisify } from "node:util";

import type { AttachmentCandidate, AttachmentLimits } from "./core.ts";
import { sanitizeAttachmentName } from "./core.ts";

const execFileAsync = promisify(execFile);
const JSON_RESPONSE_LIMIT = 256 * 1024;
const PICKER_TIMEOUT_MS = 30 * 60 * 1000;
const TRANSFER_TIMEOUT_MS = 5 * 60 * 1000;

export type PickerExistingAttachment = {
  id: string;
  name: string;
  sizeBytes: number;
};

type NativePickerResult = {
  version: 1;
  cancelled: boolean;
  keepIds: string[];
  paths: string[];
};

type BridgeFile = {
  id: string;
  name: string;
  sizeBytes: number;
};

type BridgePickerResult = {
  version: 1;
  cancelled: boolean;
  keepIds: string[];
  files: BridgeFile[];
};

export type PickedAttachmentCandidates = {
  cancelled: boolean;
  keepIds: string[];
  candidates: AttachmentCandidate[];
  release: () => Promise<void>;
};

export function sshAttachmentBridgeConfigured(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.PI_ATTACH_BRIDGE_SOCKET?.trim() && env.PI_ATTACH_BRIDGE_TOKEN?.trim());
}

export function looksLikeSshSession(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.SSH_CONNECTION?.trim() || env.SSH_CLIENT?.trim() || env.SSH_TTY?.trim());
}

export type ProcessAncestryEntry = {
  parentPID: number;
  executable: string;
};

const LOCAL_VSCODE_EXECUTABLE_PREFIX =
  "/Applications/Visual Studio Code.app/Contents/";
const MOBILE_TMUX_SESSIONS = new Set([
  "jarvis-ios",
  "jarvis-ios-2",
  "jarvis-ios-3",
  "jarvis-ios-4",
  "jarvis-ios-5",
  "jarvis-ios-6",
]);
const MAX_TMUX_CLIENTS = 16;
const MAX_PROCESS_ANCESTORS = 32;

export function allClientProcessesAreLocalVSCode(
  clientPIDs: number[],
  processes: Map<number, ProcessAncestryEntry>,
): boolean {
  if (
    clientPIDs.length === 0 ||
    clientPIDs.length > MAX_TMUX_CLIENTS ||
    new Set(clientPIDs).size !== clientPIDs.length
  ) return false;

  return clientPIDs.every((clientPID) => {
    let currentPID = clientPID;
    const visited = new Set<number>();
    for (let depth = 0; depth < MAX_PROCESS_ANCESTORS; depth += 1) {
      if (currentPID <= 1 || visited.has(currentPID)) return false;
      visited.add(currentPID);
      const process = processes.get(currentPID);
      if (!process) return false;
      if (process.executable.startsWith(LOCAL_VSCODE_EXECUTABLE_PREFIX)) {
        return true;
      }
      currentPID = process.parentPID;
    }
    return false;
  });
}

function parseProcessTable(stdout: string): Map<number, ProcessAncestryEntry> {
  const processes = new Map<number, ProcessAncestryEntry>();
  for (const line of stdout.split("\n")) {
    const match = line.match(/^\s*([0-9]+)\s+([0-9]+)\s+(.+?)\s*$/);
    if (!match) continue;
    const pid = Number(match[1]);
    const parentPID = Number(match[2]);
    if (!Number.isSafeInteger(pid) || !Number.isSafeInteger(parentPID)) continue;
    processes.set(pid, { parentPID, executable: match[3] });
  }
  return processes;
}

export async function exactMobileTmuxHasOnlyLocalVSCodeClients(
  identity: { sessionName: string },
  env: NodeJS.ProcessEnv = process.env,
): Promise<boolean> {
  if (
    process.platform !== "darwin" ||
    !MOBILE_TMUX_SESSIONS.has(identity.sessionName)
  ) return false;
  const socketPath = env.TMUX?.trim().split(",", 1)[0] || "";
  if (!socketPath.startsWith("/") || basename(socketPath) !== "jarvis-mobile") {
    return false;
  }

  const listClients = () =>
    execFileAsync(
      "/opt/homebrew/bin/tmux",
      [
        "-S",
        socketPath,
        "list-clients",
        "-t",
        `=${identity.sessionName}`,
        "-F",
        "#{client_pid}|#{session_name}",
      ],
      { encoding: "utf8", timeout: 2_000, maxBuffer: 8_192 },
    );

  try {
    const { stdout: clientsBefore } = await listClients();
    const { stdout: processesOutput } = await execFileAsync(
      "/bin/ps",
      ["-axo", "pid=,ppid=,comm="],
      { encoding: "utf8", timeout: 2_000, maxBuffer: 512 * 1024 },
    );
    const { stdout: clientsAfter } = await listClients();
    if (clientsBefore.trim() !== clientsAfter.trim()) return false;
    const lines = clientsAfter.trim().split("\n").filter(Boolean);
    if (lines.length === 0 || lines.length > MAX_TMUX_CLIENTS) return false;
    const clientPIDs: number[] = [];
    for (const line of lines) {
      const [rawPID, sessionName, ...extra] = line.split("|");
      const pid = Number(rawPID);
      if (
        extra.length > 0 ||
        sessionName !== identity.sessionName ||
        !Number.isSafeInteger(pid) ||
        pid <= 1
      ) return false;
      clientPIDs.push(pid);
    }
    return allClientProcessesAreLocalVSCode(
      clientPIDs,
      parseProcessTable(processesOutput),
    );
  } catch {
    return false;
  }
}

function validateKeepIds(value: unknown, existing: PickerExistingAttachment[], source: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${source} returned invalid staged attachment IDs.`);
  }
  const ids = value as string[];
  const available = new Set(existing.map((item) => item.id));
  if (new Set(ids).size !== ids.length || ids.some((id) => !available.has(id))) {
    throw new Error(`${source} returned unknown or duplicate staged attachment IDs.`);
  }
  return ids;
}

function parseNativePickerResult(stdout: string, existing: PickerExistingAttachment[]): NativePickerResult {
  let payload: unknown;
  try {
    payload = JSON.parse(stdout);
  } catch {
    throw new Error("The native attachment picker returned invalid output.");
  }
  if (!payload || typeof payload !== "object") throw new Error("The native attachment picker returned no result.");
  const result = payload as Partial<NativePickerResult>;
  if (result.version !== 1 || typeof result.cancelled !== "boolean" || !Array.isArray(result.paths)) {
    throw new Error("The native attachment picker returned an unsupported result.");
  }
  const paths = result.paths.filter((item): item is string => typeof item === "string" && item.length > 0);
  if (paths.length !== result.paths.length) throw new Error("The native attachment picker returned invalid file paths.");
  return {
    version: 1,
    cancelled: result.cancelled,
    keepIds: validateKeepIds(result.keepIds, existing, "The native attachment picker"),
    paths,
  };
}

export async function runNativeAttachmentPicker(
  pickerPath: string,
  existing: PickerExistingAttachment[],
  limits: AttachmentLimits,
): Promise<NativePickerResult> {
  if (process.platform !== "darwin") {
    throw new Error("The native /attach picker currently supports macOS only.");
  }
  const request = JSON.stringify({ version: 1, existing, limits });
  const { stdout } = await execFileAsync(resolve(pickerPath), [request], {
    encoding: "utf8",
    timeout: PICKER_TIMEOUT_MS,
    maxBuffer: JSON_RESPONSE_LIMIT,
  });
  const result = parseNativePickerResult(stdout.trim(), existing);
  if (!result.cancelled && result.keepIds.length + result.paths.length > limits.maxFiles) {
    throw new Error("The native attachment picker selected too many files.");
  }
  return result;
}

function bridgeConfiguration(env: NodeJS.ProcessEnv = process.env): { socketPath: string; token: string } {
  const socketPath = env.PI_ATTACH_BRIDGE_SOCKET?.trim() || "";
  const token = env.PI_ATTACH_BRIDGE_TOKEN?.trim() || "";
  if (!socketPath || !token) throw new Error("This SSH session does not have an attachment picker bridge.");
  if (!socketPath.startsWith("/") || socketPath.includes("\0")) throw new Error("The SSH attachment bridge socket is invalid.");
  if (!/^[0-9a-f]{64}$/i.test(token)) throw new Error("The SSH attachment bridge token is invalid.");
  return { socketPath, token };
}

function requestOptions(
  config: { socketPath: string; token: string },
  method: string,
  path: string,
  body?: Buffer,
): RequestOptions {
  return {
    socketPath: config.socketPath,
    method,
    path,
    headers: {
      authorization: `Bearer ${config.token}`,
      accept: "application/json",
      ...(body
        ? {
            "content-type": "application/json",
            "content-length": String(body.length),
          }
        : {}),
    },
  };
}

async function responseError(response: IncomingMessage): Promise<Error> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const rawChunk of response) {
    const chunk = Buffer.from(rawChunk);
    total += chunk.length;
    if (total <= JSON_RESPONSE_LIMIT) chunks.push(chunk);
  }
  let detail = "";
  try {
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (typeof payload?.error === "string") detail = payload.error;
  } catch {
    // The status text below is sufficient for non-JSON failures.
  }
  return new Error(detail || `SSH attachment bridge returned HTTP ${response.statusCode || "error"}.`);
}

function openBridgeRequest(
  options: RequestOptions,
  body: Buffer | undefined,
  timeoutMs: number,
): Promise<IncomingMessage> {
  return new Promise((resolvePromise, rejectPromise) => {
    const request = httpRequest(options, (response) => resolvePromise(response));
    request.setTimeout(timeoutMs, () => request.destroy(new Error("SSH attachment bridge request timed out.")));
    request.once("error", rejectPromise);
    if (body) request.write(body);
    request.end();
  });
}

async function requestBridgeJson<T>(
  config: { socketPath: string; token: string },
  method: string,
  path: string,
  payload?: unknown,
): Promise<T> {
  const body = payload === undefined ? undefined : Buffer.from(JSON.stringify(payload), "utf8");
  const response = await openBridgeRequest(requestOptions(config, method, path, body), body, PICKER_TIMEOUT_MS);
  if (response.statusCode !== 200) throw await responseError(response);
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const rawChunk of response) {
    const chunk = Buffer.from(rawChunk);
    total += chunk.length;
    if (total > JSON_RESPONSE_LIMIT) throw new Error("SSH attachment bridge response was too large.");
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as T;
  } catch {
    throw new Error("SSH attachment bridge returned invalid JSON.");
  }
}

async function openBridgeFile(
  config: { socketPath: string; token: string },
  file: BridgeFile,
): Promise<AsyncIterable<Uint8Array>> {
  const response = await openBridgeRequest(
    requestOptions(config, "GET", `/v1/files/${encodeURIComponent(file.id)}`),
    undefined,
    TRANSFER_TIMEOUT_MS,
  );
  if (response.statusCode !== 200) throw await responseError(response);
  const declaredLength = Number(response.headers["content-length"]);
  if (!Number.isSafeInteger(declaredLength) || declaredLength !== file.sizeBytes) {
    response.destroy();
    throw new Error(`${sanitizeAttachmentName(file.name)} changed size before transfer.`);
  }
  response.setTimeout(TRANSFER_TIMEOUT_MS, () => response.destroy(new Error("Attachment transfer timed out.")));
  return response;
}

function validateBridgePickerResult(
  value: unknown,
  existing: PickerExistingAttachment[],
  limits: AttachmentLimits,
): BridgePickerResult {
  if (!value || typeof value !== "object") throw new Error("SSH attachment bridge returned no picker result.");
  const payload = value as Partial<BridgePickerResult>;
  if (payload.version !== 1 || typeof payload.cancelled !== "boolean" || !Array.isArray(payload.files)) {
    throw new Error("SSH attachment bridge returned an unsupported picker result.");
  }
  const keepIds = validateKeepIds(payload.keepIds, existing, "SSH attachment bridge");
  if (keepIds.length + payload.files.length > limits.maxFiles) {
    throw new Error("SSH attachment bridge selected too many files.");
  }
  const existingById = new Map(existing.map((item) => [item.id, item]));
  const fileIds = new Set<string>();
  let totalBytes = keepIds.reduce((sum, id) => sum + (existingById.get(id)?.sizeBytes || 0), 0);
  const files: BridgeFile[] = payload.files.map((item) => {
    if (
      !item ||
      typeof item.id !== "string" ||
      !/^[0-9a-f]{32}$/i.test(item.id) ||
      fileIds.has(item.id.toLowerCase()) ||
      typeof item.name !== "string" ||
      basename(item.name) !== item.name ||
      !Number.isSafeInteger(item.sizeBytes) ||
      item.sizeBytes < 0 ||
      item.sizeBytes > limits.maxFileBytes
    ) {
      throw new Error("SSH attachment bridge returned invalid file metadata.");
    }
    fileIds.add(item.id.toLowerCase());
    totalBytes += item.sizeBytes;
    return { id: item.id, name: sanitizeAttachmentName(item.name), sizeBytes: item.sizeBytes };
  });
  if (totalBytes > limits.maxTotalBytes) throw new Error("SSH attachment bridge selection exceeds the total size limit.");
  return { version: 1, cancelled: payload.cancelled, keepIds, files };
}

export async function requestSshAttachmentPicker(
  existing: PickerExistingAttachment[],
  limits: AttachmentLimits,
  env: NodeJS.ProcessEnv = process.env,
): Promise<PickedAttachmentCandidates> {
  const config = bridgeConfiguration(env);
  const rawResult = await requestBridgeJson<unknown>(config, "POST", "/v1/pick", { version: 1, existing, limits });
  const result = validateBridgePickerResult(rawResult, existing, limits);
  const ids = result.files.map((file) => file.id);
  let released = false;
  const release = async () => {
    if (released || ids.length === 0) return;
    released = true;
    await requestBridgeJson(config, "POST", "/v1/release", { ids }).catch(() => undefined);
  };
  return {
    cancelled: result.cancelled,
    keepIds: result.keepIds,
    candidates: result.files.map((file) => ({
      name: file.name,
      sizeBytes: file.sizeBytes,
      openStream: () => openBridgeFile(config, file),
    })),
    release,
  };
}
