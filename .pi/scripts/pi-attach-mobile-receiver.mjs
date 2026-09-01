#!/usr/bin/env node

import { lstat, readFile, realpath } from "node:fs/promises";
import { createConnection } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROTOCOL_VERSION = 1;
const OPERATION_TIMEOUT_MS = 5 * 60 * 1000;
const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(SCRIPT_DIRECTORY, "../..");
const RUNTIME_DIRECTORY = join(PROJECT_ROOT, ".pi", "runtime");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

const argumentsList = process.argv.slice(2);
let sessionID = 1;
if (argumentsList.length !== 0) {
  if (
    argumentsList.length !== 2 ||
    argumentsList[0] !== "--slot" ||
    !/^[1-6]$/.test(argumentsList[1])
  ) fail("The mobile attachment receiver accepts only a fixed session slot.");
  sessionID = Number(argumentsList[1]);
}

const descriptorPaths = [join(RUNTIME_DIRECTORY, `pi-attach-mobile-slot-${sessionID}.json`)];
// Build 132 and the surviving pre-slot Pi process publish this Slot 1 path.
if (sessionID === 1) descriptorPaths.push(join(RUNTIME_DIRECTORY, "pi-attach-mobile.json"));

async function readDescriptor() {
  const runtimeInfo = await lstat(RUNTIME_DIRECTORY);
  if (
    runtimeInfo.isSymbolicLink() ||
    !runtimeInfo.isDirectory() ||
    (runtimeInfo.mode & 0o777) !== 0o700 ||
    runtimeInfo.uid !== process.getuid()
  ) throw new Error("private runtime metadata is invalid");
  const canonicalRuntime = await realpath(RUNTIME_DIRECTORY);

  for (const path of descriptorPaths) {
    try {
      const [descriptorInfo, raw] = await Promise.all([
        lstat(path),
        readFile(path, "utf8"),
      ]);
      if (
        descriptorInfo.isSymbolicLink() ||
        !descriptorInfo.isFile() ||
        (descriptorInfo.mode & 0o777) !== 0o600 ||
        descriptorInfo.uid !== process.getuid()
      ) continue;
      const value = JSON.parse(raw);
      if (value?.sessionID !== undefined && value.sessionID !== sessionID) continue;
      if (value?.sessionID === undefined && sessionID !== 1) continue;
      if (
        value?.version !== PROTOCOL_VERSION ||
        !Number.isSafeInteger(value.pid) ||
        value.pid <= 1 ||
        typeof value.generation !== "string" ||
        !/^[0-9a-f]{32}$/i.test(value.generation) ||
        typeof value.socketPath !== "string" ||
        resolve(value.socketPath) !== value.socketPath ||
        !new RegExp(
          `^pi-attach-mobile-${value.pid}-[0-9a-f]{8}\\.sock$`,
          "i",
        ).test(value.socketPath.split("/").at(-1) || "")
      ) continue;
      if (await realpath(dirname(value.socketPath)) !== canonicalRuntime) continue;
      process.kill(value.pid, 0);
      const socketInfo = await lstat(value.socketPath);
      if (
        socketInfo.isSymbolicLink() ||
        !socketInfo.isSocket() ||
        socketInfo.uid !== process.getuid() ||
        (socketInfo.mode & 0o777) !== 0o600
      ) continue;
      return value;
    } catch {
      // Try the bounded Slot 1 legacy path only; other slots have no fallback.
    }
  }
  throw new Error("no matching live descriptor");
}

let descriptor;
try {
  descriptor = await readDescriptor();
} catch {
  fail("The live iPhone attachment endpoint is unavailable.");
}

const socket = createConnection({ path: descriptor.socketPath });
let completed = false;
const deadline = setTimeout(
  () => finish(1, "The iPhone attachment operation timed out."),
  OPERATION_TIMEOUT_MS,
);

function finish(code, message) {
  if (completed) return;
  completed = true;
  clearTimeout(deadline);
  if (message) process.stderr.write(`${message}\n`);
  if (!socket.destroyed) socket.destroy();
  process.exit(code);
}

socket.once("error", () => finish(1, "The live iPhone attachment endpoint failed."));
socket.once("connect", () => {
  process.stdin.on("error", () => finish(1, "The iPhone attachment request failed."));
  process.stdout.on("error", () => finish(1));
  process.stdin.pipe(socket, { end: false });
  process.stdin.once("end", () => socket.end());
  socket.pipe(process.stdout, { end: false });
});
socket.once("end", () => {
  process.stdout.end(() => finish(0));
});
socket.once("close", (hadError) => {
  if (!completed && hadError) finish(1, "The live iPhone attachment endpoint closed unexpectedly.");
});
