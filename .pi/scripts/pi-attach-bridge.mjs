#!/usr/bin/env node

import { execFile } from "node:child_process";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { constants, createReadStream } from "node:fs";
import { chmod, lstat, mkdir, open, rename, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { basename, dirname, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const MAX_JSON_BYTES = 256 * 1024;
const PICKER_TIMEOUT_MS = 30 * 60 * 1000;
const SELECTION_TTL_MS = 30 * 60 * 1000;
const HARD_MAX_FILES = 100;
const HARD_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
const HARD_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024;

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--descriptor" || key === "--picker") {
      const value = argv[index + 1];
      if (!value) throw new Error(`${key} requires a value.`);
      values[key.slice(2)] = value;
      index += 1;
      continue;
    }
    if (key === "--help" || key === "-h") {
      console.log("Usage: pi-attach-bridge.mjs --descriptor <path> --picker <path>");
      process.exit(0);
    }
    throw new Error(`Unknown argument: ${key}`);
  }
  if (!values.descriptor || !values.picker) throw new Error("--descriptor and --picker are required.");
  return { descriptor: resolve(values.descriptor), picker: resolve(values.picker) };
}

function sendJson(response, status, payload) {
  const body = Buffer.from(`${JSON.stringify(payload)}\n`, "utf8");
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": String(body.length),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

function authorized(request, token) {
  const supplied = Buffer.from(String(request.headers.authorization || ""), "utf8");
  const expected = Buffer.from(`Bearer ${token}`, "utf8");
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

async function readJsonBody(request) {
  const declared = Number(request.headers["content-length"] || 0);
  if (!Number.isSafeInteger(declared) || declared <= 0 || declared > MAX_JSON_BYTES) {
    throw new Error("Invalid JSON request size.");
  }
  const chunks = [];
  let total = 0;
  for await (const rawChunk of request) {
    const chunk = Buffer.from(rawChunk);
    total += chunk.length;
    if (total > MAX_JSON_BYTES || total > declared) throw new Error("JSON request was too large.");
    chunks.push(chunk);
  }
  if (total !== declared) throw new Error("JSON request was incomplete.");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new Error("Invalid JSON request.");
  }
}

function boundedPositiveInteger(value, maximum, label) {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0 || parsed > maximum) throw new Error(`${label} is invalid.`);
  return parsed;
}

function parseLimits(payload) {
  if (!payload || typeof payload !== "object") throw new Error("Attachment limits are missing.");
  return {
    maxFiles: boundedPositiveInteger(payload.maxFiles, HARD_MAX_FILES, "maxFiles"),
    maxFileBytes: boundedPositiveInteger(payload.maxFileBytes, HARD_MAX_FILE_BYTES, "maxFileBytes"),
    maxTotalBytes: boundedPositiveInteger(payload.maxTotalBytes, HARD_MAX_TOTAL_BYTES, "maxTotalBytes"),
  };
}

function sanitizeName(value) {
  const name = basename(String(value || "attachment"))
    .normalize("NFC")
    .replace(/[\u0000-\u001f\u007f]/g, "_")
    .replace(/[\\/:]/g, "_")
    .trim();
  return [...(name || "attachment")].slice(0, 160).join("");
}

function parsePickRequest(payload) {
  if (!payload || payload.version !== 1 || typeof payload !== "object" || !Array.isArray(payload.existing)) {
    throw new Error("Attachment picker request is invalid.");
  }
  const limits = parseLimits(payload.limits);
  if (payload.existing.length > limits.maxFiles) throw new Error("Too many staged attachments were supplied.");
  const seen = new Set();
  let totalBytes = 0;
  const existing = payload.existing.map((item) => {
    if (
      !item ||
      typeof item.id !== "string" ||
      !/^[a-zA-Z0-9._-]{1,128}$/.test(item.id) ||
      seen.has(item.id) ||
      typeof item.name !== "string" ||
      !Number.isSafeInteger(item.sizeBytes) ||
      item.sizeBytes < 0 ||
      item.sizeBytes > limits.maxFileBytes
    ) {
      throw new Error("Staged attachment metadata is invalid.");
    }
    seen.add(item.id);
    totalBytes += item.sizeBytes;
    return { id: item.id, name: sanitizeName(item.name), sizeBytes: item.sizeBytes };
  });
  if (totalBytes > limits.maxTotalBytes) throw new Error("Staged attachments exceed the total size limit.");
  return { version: 1, existing, limits };
}

function parsePickerOutput(stdout, existing) {
  let payload;
  try {
    payload = JSON.parse(stdout);
  } catch {
    throw new Error("The local file picker returned invalid output.");
  }
  if (
    !payload ||
    payload.version !== 1 ||
    typeof payload.cancelled !== "boolean" ||
    !Array.isArray(payload.keepIds) ||
    !Array.isArray(payload.paths)
  ) {
    throw new Error("The local file picker returned an unsupported result.");
  }
  const available = new Set(existing.map((item) => item.id));
  const keepIds = payload.keepIds.filter((id) => typeof id === "string" && available.has(id));
  if (keepIds.length !== payload.keepIds.length || new Set(keepIds).size !== keepIds.length) {
    throw new Error("The local file picker returned invalid staged attachment IDs.");
  }
  const paths = payload.paths.filter((path) => typeof path === "string" && path.length > 0);
  if (paths.length !== payload.paths.length || new Set(paths).size !== paths.length) {
    throw new Error("The local file picker returned invalid or duplicate paths.");
  }
  return { version: 1, cancelled: payload.cancelled, keepIds, paths };
}

async function runPicker(picker, request) {
  const { stdout } = await execFileAsync(picker, [JSON.stringify(request)], {
    encoding: "utf8",
    timeout: PICKER_TIMEOUT_MS,
    maxBuffer: MAX_JSON_BYTES,
  });
  return parsePickerOutput(stdout.trim(), request.existing);
}

async function inspectSelection(paths, existing, keepIds, limits) {
  if (keepIds.length + paths.length > limits.maxFiles) throw new Error(`Stage no more than ${limits.maxFiles} files.`);
  const existingById = new Map(existing.map((item) => [item.id, item]));
  const selected = [];
  let totalBytes = keepIds.reduce((sum, id) => sum + existingById.get(id).sizeBytes, 0);
  for (const path of paths) {
    const info = await lstat(path);
    if (info.isSymbolicLink() || !info.isFile()) throw new Error(`Only regular files can be attached: ${basename(path)}`);
    if (info.size > limits.maxFileBytes) throw new Error(`${basename(path)} exceeds the per-file attachment limit.`);
    totalBytes += info.size;
    if (totalBytes > limits.maxTotalBytes) throw new Error("The selected files exceed the total attachment limit.");
    selected.push({
      id: randomBytes(16).toString("hex"),
      path,
      name: basename(path),
      sizeBytes: info.size,
      device: info.dev,
      inode: info.ino,
      modifiedMs: info.mtimeMs,
      expiresAt: Date.now() + SELECTION_TTL_MS,
    });
  }
  return selected;
}

async function atomicDescriptor(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await chmod(temporary, 0o600);
  await rename(temporary, path);
  await chmod(path, 0o600);
}

const args = parseArguments(process.argv.slice(2));
const token = randomBytes(32).toString("hex");
const selections = new Map();
let pickerActive = false;

const server = createServer(async (request, response) => {
  response.setHeader("connection", "close");
  if (!authorized(request, token)) {
    sendJson(response, 401, { ok: false, error: "Unauthorized." });
    return;
  }

  const requestUrl = new URL(request.url || "/", "http://127.0.0.1");
  try {
    if (request.method === "POST" && requestUrl.pathname === "/v1/pick") {
      if (pickerActive) {
        sendJson(response, 409, { ok: false, error: "The attachment picker is already open." });
        return;
      }
      const pickerRequest = parsePickRequest(await readJsonBody(request));
      pickerActive = true;
      try {
        const result = await runPicker(args.picker, pickerRequest);
        if (result.cancelled) {
          sendJson(response, 200, {
            version: 1,
            cancelled: true,
            keepIds: pickerRequest.existing.map((item) => item.id),
            files: [],
          });
          return;
        }
        const inspected = await inspectSelection(
          result.paths,
          pickerRequest.existing,
          result.keepIds,
          pickerRequest.limits,
        );
        for (const item of inspected) selections.set(item.id, item);
        sendJson(response, 200, {
          version: 1,
          cancelled: false,
          keepIds: result.keepIds,
          files: inspected.map(({ id, name, sizeBytes }) => ({ id, name, sizeBytes })),
        });
      } finally {
        pickerActive = false;
      }
      return;
    }

    if (request.method === "GET" && requestUrl.pathname.startsWith("/v1/files/")) {
      const id = decodeURIComponent(requestUrl.pathname.slice("/v1/files/".length));
      const selected = selections.get(id);
      if (!selected || selected.expiresAt <= Date.now()) {
        selections.delete(id);
        sendJson(response, 404, { ok: false, error: "Attachment selection expired or was not found." });
        return;
      }
      const handle = await open(selected.path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
      const info = await handle.stat();
      if (
        !info.isFile() ||
        info.size !== selected.sizeBytes ||
        info.dev !== selected.device ||
        info.ino !== selected.inode ||
        info.mtimeMs !== selected.modifiedMs
      ) {
        await handle.close();
        sendJson(response, 409, { ok: false, error: "The selected file changed before transfer." });
        return;
      }
      response.writeHead(200, {
        "content-type": "application/octet-stream",
        "content-length": String(info.size),
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
      });
      const stream = createReadStream(selected.path, { fd: handle.fd, autoClose: false, start: 0 });
      let handleClosed = false;
      const closeHandle = () => {
        if (handleClosed) return Promise.resolve();
        handleClosed = true;
        return handle.close().catch(() => undefined);
      };
      stream.once("error", (error) => {
        response.destroy(error);
        void closeHandle();
      });
      stream.once("end", () => void closeHandle());
      stream.once("close", () => void closeHandle());
      response.once("close", () => {
        if (!stream.destroyed) stream.destroy();
      });
      stream.pipe(response);
      return;
    }

    if (request.method === "POST" && requestUrl.pathname === "/v1/release") {
      const payload = await readJsonBody(request);
      if (!payload || !Array.isArray(payload.ids)) throw new Error("Attachment release ids are invalid.");
      for (const id of payload.ids) {
        if (typeof id === "string" && /^[0-9a-f]{32}$/i.test(id)) selections.delete(id);
      }
      sendJson(response, 200, { ok: true });
      return;
    }

    sendJson(response, 404, { ok: false, error: "Not found." });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    sendJson(response, 400, { ok: false, error: message.slice(0, 500) });
  }
});

server.on("clientError", (_error, socket) => socket.destroy());
server.listen(0, "127.0.0.1", async () => {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not determine attachment bridge port.");
  await atomicDescriptor(args.descriptor, {
    version: 1,
    host: "127.0.0.1",
    port: address.port,
    token,
    pid: process.pid,
  });
});

const pruneTimer = setInterval(() => {
  const now = Date.now();
  for (const [id, item] of selections) {
    if (item.expiresAt <= now) selections.delete(id);
  }
}, 60_000);
pruneTimer.unref();

async function shutdown(exitCode = 0) {
  clearInterval(pruneTimer);
  server.close();
  await rm(args.descriptor, { force: true }).catch(() => undefined);
  process.exit(exitCode);
}

process.once("SIGINT", () => void shutdown(130));
process.once("SIGTERM", () => void shutdown(143));
process.once("SIGHUP", () => void shutdown(129));
process.once("uncaughtException", (error) => {
  console.error(error instanceof Error ? error.message : String(error));
  void shutdown(1);
});
process.once("unhandledRejection", (error) => {
  console.error(error instanceof Error ? error.message : String(error));
  void shutdown(1);
});
