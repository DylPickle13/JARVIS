import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmod, lstat, mkdir, open, readFile, rename, rm } from "node:fs/promises";
import { createServer, type Server, type Socket } from "node:net";
import { basename, join, resolve } from "node:path";
import { promisify, TextDecoder } from "node:util";

import {
  ATTACHMENT_DIRECTORY_MODE,
  ATTACHMENT_FILE_MODE,
  sanitizeAttachmentName,
  type AttachmentCandidate,
  type AttachmentLimits,
  type PreparedAttachment,
  type StagedAttachment,
} from "./core.ts";

const execFileAsync = promisify(execFile);

export const MOBILE_ATTACHMENT_PROTOCOL_VERSION = 1;
export const MOBILE_ATTACHMENT_HEADER_LIMIT = 64 * 1024;
export const MOBILE_ATTACHMENT_RESPONSE_LIMIT = 64 * 1024;
export const MOBILE_ATTACHMENT_OPERATION_TIMEOUT_MS = 5 * 60 * 1000;
const OUTCOME_LIMIT = 100;
const MAX_CONCURRENT_OPERATIONS = 4;
const HARD_MAX_FILES = 100;
const HARD_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
const HARD_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024;
const REQUEST_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const GENERATION_PATTERN = /^[0-9a-f]{32}$/i;
const STAGED_ID_PATTERN = /^[0-9a-f-]{1,128}$/i;
const HEX_64_PATTERN = /^[0-9a-f]{64}$/i;

export type MobileAttachmentSnapshot = {
  revision: number;
  limits: AttachmentLimits;
  staged: StagedAttachment[];
};

export type MobileAttachmentHooks = {
  snapshot: () => Promise<MobileAttachmentSnapshot>;
  prepare: (candidates: AttachmentCandidate[]) => Promise<PreparedAttachment[]>;
  commit: (
    expectedRevision: number,
    keepIds: string[],
    prepared: PreparedAttachment[],
  ) => Promise<MobileAttachmentSnapshot>;
  discard: (prepared: PreparedAttachment[]) => Promise<void>;
};

export type MobileAttachmentServerOptions = {
  runtimeDirectory: string;
  environment?: NodeJS.ProcessEnv;
  processId?: number;
  mobileSlot?: number;
  requireExactMobileTmux?: boolean;
  identityCheck?: (
    environment: NodeJS.ProcessEnv,
    processId: number,
  ) => Promise<boolean>;
  operationTimeoutMs?: number;
};

type MobileFileHeader = {
  name: string;
  sizeBytes: number;
  sha256: string;
};

type MobileRequest = {
  version: number;
  operation: "snapshot" | "reconcile" | "requestStatus";
  requestID: string;
  expectedGeneration?: string;
  expectedRevision?: number;
  keepIds?: string[];
  files?: MobileFileHeader[];
  targetRequestID?: string;
};

type MobileOutcome = {
  state: "committed" | "notCommitted";
  response?: Record<string, unknown>;
};

type ParsedReconcileMetadata = {
  expectedGeneration: string;
  expectedRevision: number;
  keepIds: string[];
  files: MobileFileHeader[];
};

function boundedPositiveInteger(
  value: unknown,
  maximum: number,
  label: string,
): number {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0 || parsed > maximum) {
    throw new Error(`${label} is invalid.`);
  }
  return parsed;
}

function validateLimits(value: AttachmentLimits): AttachmentLimits {
  return {
    maxFiles: boundedPositiveInteger(value.maxFiles, HARD_MAX_FILES, "maxFiles"),
    maxFileBytes: boundedPositiveInteger(
      value.maxFileBytes,
      HARD_MAX_FILE_BYTES,
      "maxFileBytes",
    ),
    maxTotalBytes: boundedPositiveInteger(
      value.maxTotalBytes,
      HARD_MAX_TOTAL_BYTES,
      "maxTotalBytes",
    ),
  };
}

function publicErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  return raw
    .replace(/\/(?:Users|private|tmp|opt|var)\/[^\s"']+/gi, "[private path]")
    .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, "Bearer [redacted]")
    .slice(0, 500) || "Attachment operation failed.";
}

function frameJson(payload: Record<string, unknown>): Buffer {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  if (body.length === 0 || body.length > MOBILE_ATTACHMENT_RESPONSE_LIMIT) {
    throw new Error("Attachment response exceeded its bounded size.");
  }
  const prefix = Buffer.allocUnsafe(4);
  prefix.writeUInt32BE(body.length, 0);
  return Buffer.concat([prefix, body]);
}

class SocketByteReader {
  private readonly iterator: AsyncIterator<Buffer | Uint8Array>;
  private buffered = Buffer.alloc(0);
  private ended = false;

  constructor(socket: Socket) {
    this.iterator = socket[Symbol.asyncIterator]();
  }

  private async fill(): Promise<void> {
    if (this.ended) return;
    const next = await this.iterator.next();
    if (next.done) {
      this.ended = true;
      return;
    }
    const chunk = Buffer.from(next.value);
    if (chunk.length > 0) this.buffered = Buffer.concat([this.buffered, chunk]);
  }

  async readExact(length: number): Promise<Buffer> {
    if (!Number.isSafeInteger(length) || length < 0) {
      throw new Error("Attachment frame length is invalid.");
    }
    while (this.buffered.length < length && !this.ended) await this.fill();
    if (this.buffered.length < length) {
      throw new Error("Attachment request ended before its declared length.");
    }
    const result = this.buffered.subarray(0, length);
    this.buffered = this.buffered.subarray(length);
    return result;
  }

  async *readBody(length: number): AsyncGenerator<Uint8Array> {
    let remaining = length;
    while (remaining > 0) {
      if (this.buffered.length === 0) await this.fill();
      if (this.buffered.length === 0 && this.ended) {
        throw new Error("Attachment body ended before its declared length.");
      }
      const count = Math.min(remaining, this.buffered.length);
      const chunk = this.buffered.subarray(0, count);
      this.buffered = this.buffered.subarray(count);
      remaining -= count;
      if (chunk.length > 0) yield chunk;
    }
  }

  async expectEnd(): Promise<void> {
    if (this.buffered.length > 0) {
      throw new Error("Attachment request included bytes beyond its declared files.");
    }
    while (!this.ended) {
      await this.fill();
      if (this.buffered.length > 0) {
        throw new Error("Attachment request included bytes beyond its declared files.");
      }
    }
  }
}

async function readRequest(reader: SocketByteReader): Promise<MobileRequest> {
  const lengthBytes = await reader.readExact(4);
  const length = lengthBytes.readUInt32BE(0);
  if (length <= 0 || length > MOBILE_ATTACHMENT_HEADER_LIMIT) {
    throw new Error("Attachment request header size is invalid.");
  }
  const bytes = await reader.readExact(length);
  let value: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    value = JSON.parse(text);
  } catch {
    throw new Error("Attachment request header is invalid UTF-8 JSON.");
  }
  if (!value || typeof value !== "object") {
    throw new Error("Attachment request header is missing.");
  }
  const request = value as Partial<MobileRequest>;
  if (
    request.version !== MOBILE_ATTACHMENT_PROTOCOL_VERSION ||
    !["snapshot", "reconcile", "requestStatus"].includes(
      String(request.operation),
    ) ||
    typeof request.requestID !== "string" ||
    !REQUEST_ID_PATTERN.test(request.requestID)
  ) {
    throw new Error("Attachment request header is unsupported.");
  }
  return request as MobileRequest;
}

function publicStaged(item: StagedAttachment): Record<string, unknown> {
  return {
    id: item.id,
    name: item.displayName,
    sizeBytes: item.sizeBytes,
    sha256: item.sha256,
    mimeType: item.mimeType,
  };
}

function snapshotResponse(
  requestID: string,
  generation: string,
  snapshot: MobileAttachmentSnapshot,
  operation: string,
): Record<string, unknown> {
  return {
    version: MOBILE_ATTACHMENT_PROTOCOL_VERSION,
    ok: true,
    operation,
    requestID,
    generation,
    revision: snapshot.revision,
    limits: validateLimits(snapshot.limits),
    staged: snapshot.staged.map(publicStaged),
  };
}

function validateReconcileMetadata(
  request: MobileRequest,
  snapshot: MobileAttachmentSnapshot,
): ParsedReconcileMetadata {
  if (
    typeof request.expectedGeneration !== "string" ||
    !GENERATION_PATTERN.test(request.expectedGeneration) ||
    !Number.isSafeInteger(request.expectedRevision) ||
    (request.expectedRevision as number) < 0 ||
    !Array.isArray(request.keepIds) ||
    request.keepIds.some(
      (id) => typeof id !== "string" || !STAGED_ID_PATTERN.test(id),
    ) ||
    new Set(request.keepIds).size !== request.keepIds.length ||
    !Array.isArray(request.files) ||
    request.targetRequestID !== undefined
  ) {
    throw new Error("Attachment reconcile metadata is invalid.");
  }

  const limits = validateLimits(snapshot.limits);
  if (request.keepIds.length + request.files.length > limits.maxFiles) {
    throw new Error(`A maximum of ${limits.maxFiles} attachments may be staged at once.`);
  }

  let newFileBytes = 0;
  const files = request.files.map((raw): MobileFileHeader => {
    if (
      !raw ||
      typeof raw.name !== "string" ||
      typeof raw.sha256 !== "string" ||
      !HEX_64_PATTERN.test(raw.sha256) ||
      !Number.isSafeInteger(raw.sizeBytes) ||
      raw.sizeBytes < 0 ||
      raw.sizeBytes > limits.maxFileBytes
    ) {
      throw new Error("Attachment file metadata is invalid.");
    }
    const name = sanitizeAttachmentName(raw.name);
    if (name !== raw.name) {
      throw new Error("Attachment file name is not in its canonical safe form.");
    }
    newFileBytes += raw.sizeBytes;
    return { name, sizeBytes: raw.sizeBytes, sha256: raw.sha256.toLowerCase() };
  });
  if (newFileBytes > limits.maxTotalBytes) {
    throw new Error("The selected files exceed the total staged-attachment limit.");
  }
  return {
    expectedGeneration: request.expectedGeneration,
    expectedRevision: request.expectedRevision as number,
    keepIds: request.keepIds,
    files,
  };
}

function parseReconcileState(
  metadata: ParsedReconcileMetadata,
  generation: string,
  snapshot: MobileAttachmentSnapshot,
): { expectedRevision: number; keepIds: string[]; files: MobileFileHeader[] } {
  if (metadata.expectedGeneration !== generation) {
    throw new Error("The live Pi attachment generation changed. Refresh the selection.");
  }
  if (metadata.expectedRevision !== snapshot.revision) {
    throw new Error("The staged attachments changed. Refresh the selection.");
  }

  const limits = validateLimits(snapshot.limits);
  const existing = new Map(snapshot.staged.map((item) => [item.id, item]));
  let totalBytes = metadata.files.reduce((sum, file) => sum + file.sizeBytes, 0);
  for (const id of metadata.keepIds) {
    const item = existing.get(id);
    if (!item) throw new Error("Attachment reconcile retained an unknown item.");
    totalBytes += item.sizeBytes;
  }
  if (totalBytes > limits.maxTotalBytes) {
    throw new Error("The selected files exceed the total staged-attachment limit.");
  }
  return {
    expectedRevision: metadata.expectedRevision,
    keepIds: metadata.keepIds,
    files: metadata.files,
  };
}

function candidatesForFiles(
  files: MobileFileHeader[],
  reader: SocketByteReader,
): AttachmentCandidate[] {
  return files.map((file) => {
    let opened = false;
    return {
      name: file.name,
      sizeBytes: file.sizeBytes,
      openStream: () => {
        if (opened) throw new Error("Attachment body stream was opened more than once.");
        opened = true;
        return reader.readBody(file.sizeBytes);
      },
    };
  });
}

async function secureRuntimeDirectory(path: string): Promise<void> {
  await mkdir(path, { recursive: true, mode: ATTACHMENT_DIRECTORY_MODE });
  const info = await lstat(path);
  if (info.isSymbolicLink() || !info.isDirectory()) {
    throw new Error("Private attachment runtime directory is invalid.");
  }
  await chmod(path, ATTACHMENT_DIRECTORY_MODE);
}

async function atomicDescriptor(
  path: string,
  value: Record<string, unknown>,
): Promise<void> {
  const temporary = `${path}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
  const handle = await open(temporary, "wx", ATTACHMENT_FILE_MODE);
  try {
    await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
    await handle.sync();
    await handle.close();
    await chmod(temporary, ATTACHMENT_FILE_MODE);
    await rename(temporary, path);
  } catch (error) {
    await handle.close().catch(() => undefined);
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}

export type ExactMobileTmuxIdentity = {
  slot: 1 | 2 | 3 | 4 | 5 | 6;
  sessionName: string;
  paneID: string;
};

const MOBILE_TMUX_SESSIONS = new Map<string, 1 | 2 | 3 | 4 | 5 | 6>([
  ["jarvis-ios", 1],
  ["jarvis-ios-2", 2],
  ["jarvis-ios-3", 3],
  ["jarvis-ios-4", 4],
  ["jarvis-ios-5", 5],
  ["jarvis-ios-6", 6],
]);

export async function exactMobileTmuxIdentity(
  environment: NodeJS.ProcessEnv = process.env,
  processId = process.pid,
): Promise<ExactMobileTmuxIdentity | undefined> {
  const rawTmux = environment.TMUX?.trim() || "";
  const pane = environment.TMUX_PANE?.trim() || "";
  if (!rawTmux || !/^%[0-9]+$/.test(pane)) return undefined;
  const socketPath = rawTmux.split(",", 1)[0];
  if (!socketPath || basename(socketPath) !== "jarvis-mobile") return undefined;
  try {
    const { stdout } = await execFileAsync(
      "/opt/homebrew/bin/tmux",
      [
        "-S",
        socketPath,
        "display-message",
        "-p",
        "-t",
        pane,
        "#{session_name}|#{window_index}|#{pane_index}|#{pane_id}|#{pane_pid}",
      ],
      { encoding: "utf8", timeout: 2_000, maxBuffer: 4_096 },
    );
    const [sessionName, windowIndex, paneIndex, paneID, panePID] = stdout.trim().split("|");
    const slot = MOBILE_TMUX_SESSIONS.get(sessionName);
    if (
      slot === undefined ||
      windowIndex !== "0" ||
      paneIndex !== "0" ||
      paneID !== pane ||
      (slot === 1 && paneID !== "%0") ||
      Number(panePID) !== processId
    ) return undefined;
    return { slot, sessionName, paneID };
  } catch {
    return undefined;
  }
}

export async function isExactMobileTmuxProcess(
  environment: NodeJS.ProcessEnv = process.env,
  processId = process.pid,
): Promise<boolean> {
  return (await exactMobileTmuxIdentity(environment, processId)) !== undefined;
}

export class MobileAttachmentServer {
  readonly generation: string;
  readonly slot: 1 | 2 | 3 | 4 | 5 | 6;
  readonly descriptorPath: string;
  readonly legacyDescriptorPath?: string;
  readonly socketPath: string;

  private readonly server: Server;
  private readonly hooks: MobileAttachmentHooks;
  private readonly operationTimeoutMs: number;
  private readonly outcomes = new Map<string, MobileOutcome>();
  private readonly sockets = new Set<Socket>();
  private readonly operations = new Set<Promise<void>>();
  private closed = false;

  private constructor(
    server: Server,
    hooks: MobileAttachmentHooks,
    runtimeDirectory: string,
    processId: number,
    slot: 1 | 2 | 3 | 4 | 5 | 6,
    operationTimeoutMs: number,
  ) {
    this.server = server;
    this.hooks = hooks;
    this.operationTimeoutMs = operationTimeoutMs;
    this.generation = randomBytes(16).toString("hex");
    this.slot = slot;
    this.descriptorPath = join(runtimeDirectory, `pi-attach-mobile-slot-${slot}.json`);
    // Build 132's no-argument receiver remains a Slot 1 compatibility path.
    this.legacyDescriptorPath = slot === 1
      ? join(runtimeDirectory, "pi-attach-mobile.json")
      : undefined;
    this.socketPath = join(
      runtimeDirectory,
      `pi-attach-mobile-${processId}-${this.generation.slice(0, 8)}.sock`,
    );
  }

  static async start(
    hooks: MobileAttachmentHooks,
    options: MobileAttachmentServerOptions,
  ): Promise<MobileAttachmentServer | undefined> {
    const environment = options.environment ?? process.env;
    const processId = options.processId ?? process.pid;
    if (!Number.isSafeInteger(processId) || processId <= 1) {
      throw new Error("The mobile attachment process identifier is invalid.");
    }
    const requireIdentity = options.requireExactMobileTmux ?? true;
    const identity = await exactMobileTmuxIdentity(environment, processId);
    if (requireIdentity) {
      const identityCheck = options.identityCheck;
      if (identityCheck) {
        if (!(await identityCheck(environment, processId))) return undefined;
      } else if (!identity) {
        return undefined;
      }
    }
    const rawSlot = options.mobileSlot ?? identity?.slot ?? 1;
    if (!Number.isSafeInteger(rawSlot) || rawSlot < 1 || rawSlot > 6) {
      throw new Error("The mobile attachment slot is invalid.");
    }
    const slot = rawSlot as 1 | 2 | 3 | 4 | 5 | 6;
    if (identity && identity.slot !== slot) {
      throw new Error("The mobile attachment slot did not match the protected tmux process.");
    }

    const runtimeDirectory = resolve(options.runtimeDirectory);
    await secureRuntimeDirectory(runtimeDirectory);
    const operationTimeoutMs = boundedPositiveInteger(
      options.operationTimeoutMs ?? MOBILE_ATTACHMENT_OPERATION_TIMEOUT_MS,
      MOBILE_ATTACHMENT_OPERATION_TIMEOUT_MS,
      "operationTimeoutMs",
    );
    const server = createServer({ allowHalfOpen: true });
    const instance = new MobileAttachmentServer(
      server,
      hooks,
      runtimeDirectory,
      processId,
      slot,
      operationTimeoutMs,
    );
    await rm(instance.socketPath, { force: true });
    server.on("connection", (socket) => instance.accept(socket));
    server.on("error", () => undefined);
    await new Promise<void>((resolvePromise, rejectPromise) => {
      const onError = (error: Error) => {
        server.off("listening", onListening);
        rejectPromise(error);
      };
      const onListening = () => {
        server.off("error", onError);
        resolvePromise();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen(instance.socketPath);
    });
    try {
      await chmod(instance.socketPath, ATTACHMENT_FILE_MODE);
      const descriptor = {
        version: MOBILE_ATTACHMENT_PROTOCOL_VERSION,
        sessionID: slot,
        generation: instance.generation,
        pid: processId,
        socketPath: instance.socketPath,
      };
      await atomicDescriptor(instance.descriptorPath, descriptor);
      if (instance.legacyDescriptorPath) {
        await atomicDescriptor(instance.legacyDescriptorPath, descriptor);
      }
      return instance;
    } catch (error) {
      for (const socket of instance.sockets) socket.destroy();
      await new Promise<void>((resolvePromise) => {
        server.close(() => resolvePromise());
      }).catch(() => undefined);
      await instance.removeOwnedDescriptor(instance.descriptorPath);
      if (instance.legacyDescriptorPath) {
        await instance.removeOwnedDescriptor(instance.legacyDescriptorPath);
      }
      await rm(instance.socketPath, { force: true }).catch(() => undefined);
      throw error;
    }
  }

  private remember(requestID: string, outcome: MobileOutcome): void {
    if (
      this.outcomes.get(requestID)?.state === "committed" &&
      outcome.state !== "committed"
    ) {
      return;
    }
    this.outcomes.delete(requestID);
    this.outcomes.set(requestID, outcome);
    while (this.outcomes.size > OUTCOME_LIMIT) {
      const oldest = this.outcomes.keys().next().value;
      if (typeof oldest !== "string") break;
      this.outcomes.delete(oldest);
    }
  }

  private accept(socket: Socket): void {
    const operation = this.handle(socket).catch(() => {
      socket.destroy();
    });
    this.operations.add(operation);
    void operation.finally(() => {
      this.operations.delete(operation);
    });
  }

  private async handle(socket: Socket): Promise<void> {
    if (this.closed || this.operations.size >= MAX_CONCURRENT_OPERATIONS) {
      socket.destroy();
      return;
    }
    this.sockets.add(socket);
    let expired = false;
    const expiresAt = Date.now() + this.operationTimeoutMs;
    const deadline = setTimeout(() => {
      expired = true;
      socket.destroy();
    }, this.operationTimeoutMs);
    socket.once("close", () => {
      clearTimeout(deadline);
      this.sockets.delete(socket);
    });
    socket.setNoDelay(true);
    const reader = new SocketByteReader(socket);
    let requestID = "";
    let prepared: PreparedAttachment[] = [];
    let committed = false;
    let tracksOutcome = false;
    try {
      const request = await readRequest(reader);
      requestID = request.requestID;

      if (request.operation === "snapshot") {
        if (
          request.expectedGeneration !== undefined ||
          request.expectedRevision !== undefined ||
          request.keepIds !== undefined ||
          request.files !== undefined ||
          request.targetRequestID !== undefined
        ) {
          throw new Error("Attachment snapshot request metadata is invalid.");
        }
        await reader.expectEnd();
        const snapshot = await this.hooks.snapshot();
        socket.end(frameJson(snapshotResponse(
          request.requestID,
          this.generation,
          snapshot,
          "snapshot",
        )));
        return;
      }

      if (request.operation === "requestStatus") {
        await reader.expectEnd();
        if (
          request.expectedGeneration !== this.generation ||
          typeof request.targetRequestID !== "string" ||
          !REQUEST_ID_PATTERN.test(request.targetRequestID) ||
          request.expectedRevision !== undefined ||
          request.keepIds !== undefined ||
          request.files !== undefined
        ) {
          throw new Error("Attachment status request is invalid or stale.");
        }
        const outcome = this.outcomes.get(request.targetRequestID);
        socket.end(frameJson({
          version: MOBILE_ATTACHMENT_PROTOCOL_VERSION,
          ok: true,
          operation: "requestStatus",
          requestID: request.requestID,
          targetRequestID: request.targetRequestID,
          generation: this.generation,
          state: outcome?.state ?? "unknown",
          ...(outcome?.response ? { committedResponse: outcome.response } : {}),
        }));
        return;
      }

      const before = await this.hooks.snapshot();
      const metadata = validateReconcileMetadata(request, before);
      tracksOutcome = true;
      const prior = this.outcomes.get(request.requestID);
      if (prior?.state === "committed" && prior.response) {
        socket.end(frameJson(prior.response));
        return;
      }

      const reconcile = parseReconcileState(metadata, this.generation, before);
      const candidates = candidatesForFiles(reconcile.files, reader);
      prepared = await this.hooks.prepare(candidates);
      if (prepared.length !== reconcile.files.length) {
        throw new Error("Attachment preparation returned an invalid result.");
      }
      for (let index = 0; index < prepared.length; index += 1) {
        const expected = reconcile.files[index];
        const actual = prepared[index];
        if (
          actual.sizeBytes !== expected.sizeBytes ||
          actual.sha256.toLowerCase() !== expected.sha256
        ) {
          throw new Error(`${expected.name} failed attachment integrity verification.`);
        }
      }
      await reader.expectEnd();
      if (expired || Date.now() >= expiresAt || this.closed || socket.destroyed) {
        throw new Error("Attachment operation timed out or was cancelled.");
      }
      const after = await this.hooks.commit(
        reconcile.expectedRevision,
        reconcile.keepIds,
        prepared,
      );
      prepared = [];
      committed = true;
      const response = snapshotResponse(
        request.requestID,
        this.generation,
        after,
        "reconcile",
      );
      this.remember(request.requestID, { state: "committed", response });
      socket.end(frameJson(response));
    } catch (error) {
      if (prepared.length > 0) {
        await this.hooks.discard(prepared).catch(() => undefined);
      }
      if (requestID && tracksOutcome && !committed) {
        this.remember(requestID, { state: "notCommitted" });
      }
      const response = {
        version: MOBILE_ATTACHMENT_PROTOCOL_VERSION,
        ok: false,
        operation: "error",
        requestID: requestID || undefined,
        generation: this.generation,
        code: "attachment_failed",
        error: publicErrorMessage(error),
      };
      if (!socket.destroyed) socket.end(frameJson(response));
    }
  }

  private async removeOwnedDescriptor(path: string): Promise<void> {
    try {
      const descriptor = JSON.parse(await readFile(path, "utf8"));
      if (
        descriptor?.generation === this.generation &&
        descriptor?.socketPath === this.socketPath &&
        (descriptor?.sessionID === undefined || descriptor?.sessionID === this.slot)
      ) {
        await rm(path, { force: true });
      }
    } catch {
      // A missing, malformed, or newer descriptor is not owned by this instance.
    }
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    for (const socket of this.sockets) socket.destroy();
    await new Promise<void>((resolvePromise) => {
      this.server.close(() => resolvePromise());
    }).catch(() => undefined);
    await Promise.allSettled([...this.operations]);
    await this.removeOwnedDescriptor(this.descriptorPath);
    if (this.legacyDescriptorPath) {
      await this.removeOwnedDescriptor(this.legacyDescriptorPath);
    }
    await rm(this.socketPath, { force: true }).catch(() => undefined);
  }
}
