#!/usr/bin/env node

import { readFile, realpath } from "node:fs/promises";
import { createConnection } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { lstat } from "node:fs/promises";

const PROTOCOL_VERSION = 1;
const OPERATION_TIMEOUT_MS = 5 * 60 * 1000;
const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(SCRIPT_DIRECTORY, "../..");
const RUNTIME_DIRECTORY = join(PROJECT_ROOT, ".pi", "runtime");
const DESCRIPTOR_PATH = join(RUNTIME_DIRECTORY, "pi-attach-mobile.json");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

if (process.argv.length !== 2) fail("The mobile attachment receiver takes no arguments.");

let descriptor;
try {
  const [runtimeInfo, descriptorInfo, raw] = await Promise.all([
    lstat(RUNTIME_DIRECTORY),
    lstat(DESCRIPTOR_PATH),
    readFile(DESCRIPTOR_PATH, "utf8"),
  ]);
  if (
    runtimeInfo.isSymbolicLink() ||
    !runtimeInfo.isDirectory() ||
    (runtimeInfo.mode & 0o777) !== 0o700 ||
    descriptorInfo.isSymbolicLink() ||
    !descriptorInfo.isFile() ||
    (descriptorInfo.mode & 0o777) !== 0o600 ||
    runtimeInfo.uid !== process.getuid() ||
    descriptorInfo.uid !== process.getuid()
  ) {
    throw new Error("private runtime metadata is invalid");
  }
  descriptor = JSON.parse(raw);
} catch {
  fail("The live iPhone attachment endpoint is unavailable.");
}

if (
  !descriptor ||
  descriptor.version !== PROTOCOL_VERSION ||
  !Number.isSafeInteger(descriptor.pid) ||
  descriptor.pid <= 1 ||
  typeof descriptor.generation !== "string" ||
  !/^[0-9a-f]{32}$/i.test(descriptor.generation) ||
  typeof descriptor.socketPath !== "string" ||
  resolve(descriptor.socketPath) !== descriptor.socketPath ||
  !new RegExp(
    `^pi-attach-mobile-${descriptor.pid}-[0-9a-f]{8}\\.sock$`,
    "i",
  ).test(descriptor.socketPath.split("/").at(-1) || "")
) {
  fail("The live iPhone attachment endpoint is invalid.");
}

try {
  const [canonicalRuntime, canonicalSocketDirectory] = await Promise.all([
    realpath(RUNTIME_DIRECTORY),
    realpath(dirname(descriptor.socketPath)),
  ]);
  if (canonicalRuntime !== canonicalSocketDirectory) {
    throw new Error("socket directory is outside the private runtime");
  }
  process.kill(descriptor.pid, 0);
  const socketInfo = await lstat(descriptor.socketPath);
  if (
    socketInfo.isSymbolicLink() ||
    !socketInfo.isSocket() ||
    socketInfo.uid !== process.getuid() ||
    (socketInfo.mode & 0o777) !== 0o600
  ) {
    throw new Error("private socket metadata is invalid");
  }
} catch {
  fail("The live iPhone attachment endpoint is stale.");
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
