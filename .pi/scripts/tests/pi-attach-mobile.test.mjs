import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import { copyFile, lstat, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { createConnection } from "node:net";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const globalNodeModules = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const jitiUrl = pathToFileURL(
  join(globalNodeModules, "@earendil-works", "pi-coding-agent", "node_modules", "jiti", "lib", "jiti.mjs"),
).href;
const { createJiti } = await import(jitiUrl);
const jiti = createJiti(import.meta.url, { interopDefault: true });
const core = await jiti.import(join(projectRoot, ".pi", "extensions", "lib", "attach", "core.ts"));
const mobile = await jiti.import(join(projectRoot, ".pi", "extensions", "lib", "attach", "mobile-server.ts"));

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function frame(payload, files = []) {
  const header = Buffer.from(JSON.stringify(payload), "utf8");
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(header.length, 0);
  return Buffer.concat([prefix, header, ...files]);
}

function parseFrame(buffer) {
  assert.ok(buffer.length >= 4);
  const length = buffer.readUInt32BE(0);
  assert.equal(buffer.length, length + 4);
  return JSON.parse(buffer.subarray(4).toString("utf8"));
}

async function socketChunks(socketPath, outboundChunks) {
  const socket = createConnection({ path: socketPath });
  const chunks = [];
  socket.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
  const ended = new Promise((resolvePromise, rejectPromise) => {
    socket.once("end", resolvePromise);
    socket.once("error", rejectPromise);
  });
  await new Promise((resolvePromise, rejectPromise) => {
    socket.once("connect", resolvePromise);
    socket.once("error", rejectPromise);
  });
  for (const chunk of outboundChunks) {
    socket.write(chunk);
    await new Promise((resolvePromise) => setImmediate(resolvePromise));
  }
  socket.end();
  await ended;
  return parseFrame(Buffer.concat(chunks));
}

async function socketRequest(socketPath, payload, files = []) {
  return socketChunks(socketPath, [frame(payload, files)]);
}

async function fixture(options = {}) {
  const directory = await mkdtemp("/tmp/pia-");
  const runtimeDirectory = join(directory, ".pi", "runtime");
  const attachmentsRoot = join(directory, "attachments");
  const store = new core.AttachmentStore(attachmentsRoot, {
    maxFiles: 3,
    maxFileBytes: 1024,
    maxTotalBytes: 2048,
  });
  let revision = 0;
  let staged = [];
  let commitTail = Promise.resolve();
  const hooks = {
    snapshot: async () => {
      staged = await store.load();
      return { revision, limits: store.limits, staged };
    },
    prepare: (candidates) => store.prepareCandidates(candidates),
    commit: (expectedRevision, keepIds, prepared) => {
      const operation = commitTail.then(async () => {
        assert.equal(expectedRevision, revision);
        staged = await store.reconcilePrepared(keepIds, prepared);
        revision += 1;
        return { revision, limits: store.limits, staged };
      });
      commitTail = operation.then(() => undefined, () => undefined);
      return operation;
    },
    discard: (prepared) => store.discardPrepared(prepared),
  };
  const server = await mobile.MobileAttachmentServer.start(hooks, {
    runtimeDirectory,
    requireExactMobileTmux: false,
    mobileSlot: options.mobileSlot,
    operationTimeoutMs: options.operationTimeoutMs ?? 5_000,
  });
  assert.ok(server);
  return { directory, runtimeDirectory, attachmentsRoot, store, server };
}

function snapshotRequest() {
  return {
    version: 1,
    operation: "snapshot",
    requestID: randomUUID(),
  };
}

test("mobile server rejects non-allowlisted slot configuration before publishing", async () => {
  const directory = await mkdtemp("/tmp/pia-invalid-slot-");
  const runtimeDirectory = join(directory, ".pi", "runtime");
  try {
    for (const mobileSlot of [0, 7]) {
      await assert.rejects(
        mobile.MobileAttachmentServer.start(
          {
            snapshot: async () => ({ revision: 0, limits: {}, staged: [] }),
            prepare: async () => [],
            commit: async () => ({ revision: 0, limits: {}, staged: [] }),
            discard: async () => {},
          },
          {
            runtimeDirectory,
            requireExactMobileTmux: false,
            mobileSlot,
          },
        ),
        /slot is invalid/i,
      );
    }
    await assert.rejects(lstat(runtimeDirectory));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("mobile attachment socket snapshots, commits exact bytes, and resolves ambiguous status", async () => {
  const data = await fixture();
  try {
    const descriptorInfo = await stat(data.server.descriptorPath);
    const socketInfo = await lstat(data.server.socketPath);
    assert.equal(descriptorInfo.mode & 0o777, 0o600);
    assert.equal(socketInfo.mode & 0o777, 0o600);
    assert.ok(socketInfo.isSocket());

    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    assert.equal(initial.ok, true);
    assert.equal(initial.revision, 0);
    assert.deepEqual(initial.staged, []);
    assert.deepEqual(initial.limits, { maxFiles: 3, maxFileBytes: 1024, maxTotalBytes: 2048 });

    const bytes = Buffer.from("hello from iPhone\n", "utf8");
    const requestID = randomUUID();
    const committed = await socketRequest(
      data.server.socketPath,
      {
        version: 1,
        operation: "reconcile",
        requestID,
        expectedGeneration: initial.generation,
        expectedRevision: initial.revision,
        keepIds: [],
        files: [{ name: "hello.txt", sizeBytes: bytes.length, sha256: sha256(bytes) }],
      },
      [bytes],
    );
    assert.equal(committed.ok, true);
    assert.equal(committed.revision, 1);
    assert.equal(committed.staged.length, 1);
    assert.equal(committed.staged[0].name, "hello.txt");
    const storedPath = join(data.attachmentsRoot, "hello.txt");
    assert.equal(await readFile(storedPath, "utf8"), "hello from iPhone\n");
    assert.equal((await stat(storedPath)).mode & 0o777, 0o600);

    const status = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      targetRequestID: requestID,
    });
    assert.equal(status.ok, true);
    assert.equal(status.state, "committed");
    assert.equal(status.committedResponse.revision, 1);
  } finally {
    const descriptorPath = data.server.descriptorPath;
    const socketPath = data.server.socketPath;
    await data.server.close();
    await assert.rejects(lstat(descriptorPath), { code: "ENOENT" });
    await assert.rejects(lstat(socketPath), { code: "ENOENT" });
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile attachment socket rejects stale revisions and integrity failures without queue mutation", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const staleBytes = Buffer.from("stale", "utf8");
    const staleID = randomUUID();
    const stale = await socketRequest(
      data.server.socketPath,
      {
        version: 1,
        operation: "reconcile",
        requestID: staleID,
        expectedGeneration: initial.generation,
        expectedRevision: 99,
        keepIds: [],
        files: [{ name: "stale.txt", sizeBytes: staleBytes.length, sha256: sha256(staleBytes) }],
      },
      [staleBytes],
    );
    assert.equal(stale.ok, false);
    assert.match(stale.error, /changed/i);

    const badBytes = Buffer.from("actual", "utf8");
    const badID = randomUUID();
    const bad = await socketRequest(
      data.server.socketPath,
      {
        version: 1,
        operation: "reconcile",
        requestID: badID,
        expectedGeneration: initial.generation,
        expectedRevision: 0,
        keepIds: [],
        files: [{ name: "bad.txt", sizeBytes: badBytes.length, sha256: "0".repeat(64) }],
      },
      [badBytes],
    );
    assert.equal(bad.ok, false);
    assert.match(bad.error, /integrity/i);

    const after = await socketRequest(data.server.socketPath, snapshotRequest());
    assert.equal(after.revision, 0);
    assert.deepEqual(after.staged, []);
    assert.deepEqual(await readdir(data.attachmentsRoot), []);

    for (const targetRequestID of [staleID, badID]) {
      const status = await socketRequest(data.server.socketPath, {
        version: 1,
        operation: "requestStatus",
        requestID: randomUUID(),
        expectedGeneration: initial.generation,
        targetRequestID,
      });
      assert.equal(status.state, "notCommitted");
    }
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile framing accepts fragmented empty files and rejects extra or invalid header bytes", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const request = {
      version: 1,
      operation: "reconcile",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      expectedRevision: initial.revision,
      keepIds: [],
      files: [{ name: "empty.txt", sizeBytes: 0, sha256: sha256(Buffer.alloc(0)) }],
    };
    const requestFrame = frame(request);
    const fragmented = await socketChunks(
      data.server.socketPath,
      [...requestFrame].map((byte) => Buffer.from([byte])),
    );
    assert.equal(fragmented.ok, true);
    assert.equal(fragmented.staged.length, 1);
    assert.equal(await readFile(join(data.attachmentsRoot, "empty.txt"), "utf8"), "");

    const extraRequest = snapshotRequest();
    const extra = await socketChunks(data.server.socketPath, [frame(extraRequest), Buffer.from([0x00])]);
    assert.equal(extra.ok, false);
    assert.match(extra.error, /beyond/i);
    const extraStatus = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: fragmented.generation,
      targetRequestID: extraRequest.requestID,
    });
    assert.equal(extraStatus.state, "unknown", "non-reconcile failures must not evict reconcile outcomes");

    const invalidUtf8Length = Buffer.alloc(4);
    invalidUtf8Length.writeUInt32BE(2, 0);
    const invalidUtf8 = await socketChunks(
      data.server.socketPath,
      [invalidUtf8Length, Buffer.from([0xc3, 0x28])],
    );
    assert.equal(invalidUtf8.ok, false);
    assert.match(invalidUtf8.error, /UTF-8 JSON/i);

    const oversizedLength = Buffer.alloc(4);
    oversizedLength.writeUInt32BE(64 * 1024 + 1, 0);
    const oversized = await socketChunks(data.server.socketPath, [oversizedLength]);
    assert.equal(oversized.ok, false);
    assert.match(oversized.error, /header size/i);
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile framing enforces names, counts, aggregate size, and truncated-body cleanup", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const base = {
      version: 1,
      operation: "reconcile",
      expectedGeneration: initial.generation,
      expectedRevision: initial.revision,
      keepIds: [],
    };

    const unsafeName = await socketRequest(data.server.socketPath, {
      ...base,
      requestID: randomUUID(),
      files: [{ name: "../../escape.txt", sizeBytes: 0, sha256: sha256(Buffer.alloc(0)) }],
    });
    assert.equal(unsafeName.ok, false);
    assert.match(unsafeName.error, /safe form/i);

    const countOverflow = await socketRequest(data.server.socketPath, {
      ...base,
      requestID: randomUUID(),
      files: Array.from({ length: 4 }, (_, index) => ({
        name: `empty-${index}.txt`,
        sizeBytes: 0,
        sha256: sha256(Buffer.alloc(0)),
      })),
    });
    assert.equal(countOverflow.ok, false);
    assert.match(countOverflow.error, /maximum of 3/i);

    const aggregateOverflow = await socketRequest(data.server.socketPath, {
      ...base,
      requestID: randomUUID(),
      files: [1024, 1024, 1].map((sizeBytes, index) => ({
        name: `large-${index}.bin`,
        sizeBytes,
        sha256: "0".repeat(64),
      })),
    });
    assert.equal(aggregateOverflow.ok, false);
    assert.match(aggregateOverflow.error, /total staged/i);

    const truncated = await socketRequest(
      data.server.socketPath,
      {
        ...base,
        requestID: randomUUID(),
        files: [{ name: "truncated.bin", sizeBytes: 5, sha256: sha256(Buffer.from("12345")) }],
      },
      [Buffer.from("12")],
    );
    assert.equal(truncated.ok, false);
    assert.match(truncated.error, /ended before/i);
    assert.deepEqual(await readdir(data.attachmentsRoot), []);
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("duplicate request IDs never import twice and filename collisions never overwrite", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const bytes = Buffer.from("same bytes", "utf8");
    const requestID = randomUUID();
    const request = {
      version: 1,
      operation: "reconcile",
      requestID,
      expectedGeneration: initial.generation,
      expectedRevision: initial.revision,
      keepIds: [],
      files: [{ name: "same.txt", sizeBytes: bytes.length, sha256: sha256(bytes) }],
    };
    const first = await socketRequest(data.server.socketPath, request, [bytes]);
    const duplicate = await socketRequest(data.server.socketPath, request, [bytes]);
    assert.equal(first.ok, true);
    assert.deepEqual(duplicate, first);
    assert.deepEqual(await readdir(data.attachmentsRoot), ["same.txt"]);

    const secondRequest = {
      ...request,
      requestID: randomUUID(),
      expectedRevision: first.revision,
      keepIds: first.staged.map((item) => item.id),
    };
    const second = await socketRequest(data.server.socketPath, secondRequest, [bytes]);
    assert.equal(second.ok, true);
    assert.deepEqual((await readdir(data.attachmentsRoot)).sort(), ["same-2.txt", "same.txt"]);
    assert.equal(await readFile(join(data.attachmentsRoot, "same.txt"), "utf8"), "same bytes");
    assert.equal(await readFile(join(data.attachmentsRoot, "same-2.txt"), "utf8"), "same bytes");
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("concurrent duplicate request IDs cannot downgrade a committed outcome", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const bytes = Buffer.alloc(512, 0x41);
    const requestID = randomUUID();
    const request = {
      version: 1,
      operation: "reconcile",
      requestID,
      expectedGeneration: initial.generation,
      expectedRevision: initial.revision,
      keepIds: [],
      files: [{ name: "race.bin", sizeBytes: bytes.length, sha256: sha256(bytes) }],
    };
    const responses = await Promise.all([
      socketRequest(data.server.socketPath, request, [bytes]),
      socketRequest(data.server.socketPath, request, [bytes]),
    ]);
    assert.ok(responses.some((response) => response.ok === true));
    assert.deepEqual(await readdir(data.attachmentsRoot), ["race.bin"]);
    const status = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      targetRequestID: requestID,
    });
    assert.equal(status.state, "committed");
    assert.equal(status.committedResponse.revision, 1);
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile request outcomes are bounded and old status becomes unknown", async () => {
  const data = await fixture();
  try {
    const initial = await socketRequest(data.server.socketPath, snapshotRequest());
    const protectedRequestID = randomUUID();
    const protectedRejection = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "reconcile",
      requestID: protectedRequestID,
      expectedGeneration: initial.generation,
      expectedRevision: 999,
      keepIds: [],
      files: [],
    });
    assert.equal(protectedRejection.ok, false);

    for (let index = 0; index < 101; index += 1) {
      const malformed = await socketRequest(data.server.socketPath, {
        version: 1,
        operation: "reconcile",
        requestID: randomUUID(),
        expectedGeneration: initial.generation,
        expectedRevision: 0,
        keepIds: [],
      });
      assert.equal(malformed.ok, false);
    }
    const protectedStatus = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      targetRequestID: protectedRequestID,
    });
    assert.equal(
      protectedStatus.state,
      "notCommitted",
      "malformed reconciles must not consume outcome history",
    );

    const requestIDs = [];
    for (let index = 0; index < 101; index += 1) {
      const requestID = randomUUID();
      requestIDs.push(requestID);
      const rejected = await socketRequest(data.server.socketPath, {
        version: 1,
        operation: "reconcile",
        requestID,
        expectedGeneration: initial.generation,
        expectedRevision: 999,
        keepIds: [],
        files: [],
      });
      assert.equal(rejected.ok, false);
    }
    const firstStatus = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      targetRequestID: requestIDs[0],
    });
    const lastStatus = await socketRequest(data.server.socketPath, {
      version: 1,
      operation: "requestStatus",
      requestID: randomUUID(),
      expectedGeneration: initial.generation,
      targetRequestID: requestIDs.at(-1),
    });
    assert.equal(firstStatus.state, "unknown");
    assert.equal(lastStatus.state, "notCommitted");
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile attachment operations have a bounded concurrent connection count", async () => {
  const data = await fixture();
  const held = [];
  try {
    for (let index = 0; index < 4; index += 1) {
      const socket = createConnection({ path: data.server.socketPath });
      socket.on("error", () => undefined);
      await new Promise((resolvePromise, rejectPromise) => {
        socket.once("connect", resolvePromise);
        socket.once("error", rejectPromise);
      });
      held.push(socket);
    }
    const overflow = createConnection({ path: data.server.socketPath });
    overflow.on("error", () => undefined);
    const overflowClosed = new Promise((resolvePromise) => overflow.once("close", resolvePromise));
    await new Promise((resolvePromise, rejectPromise) => {
      overflow.once("connect", resolvePromise);
      overflow.once("error", rejectPromise);
    });
    await overflowClosed;
    assert.equal(overflow.destroyed, true);
  } finally {
    for (const socket of held) socket.destroy();
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("incomplete mobile operations time out without queue mutation", async () => {
  const data = await fixture({ operationTimeoutMs: 50 });
  try {
    const socket = createConnection({ path: data.server.socketPath });
    socket.on("error", () => undefined);
    await new Promise((resolvePromise, rejectPromise) => {
      socket.once("connect", resolvePromise);
      socket.once("error", rejectPromise);
    });
    const started = Date.now();
    socket.write(Buffer.from([0x00]));
    await new Promise((resolvePromise) => socket.once("close", resolvePromise));
    assert.ok(Date.now() - started < 1_000);
    assert.deepEqual(await data.store.load(), []);
    assert.deepEqual(await readdir(data.attachmentsRoot), []);
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("receiver keeps no-argument Slot 1 compatibility and rejects arbitrary arguments", async () => {
  const data = await fixture();
  const receiverRoot = dirname(dirname(data.runtimeDirectory));
  const scriptsDirectory = join(receiverRoot, ".pi", "scripts");
  await mkdir(scriptsDirectory, { recursive: true });
  const copiedReceiver = join(scriptsDirectory, "pi-attach-mobile-receiver.mjs");
  await copyFile(join(projectRoot, ".pi", "scripts", "pi-attach-mobile-receiver.mjs"), copiedReceiver);
  try {
    const descriptor = JSON.parse(await readFile(data.server.descriptorPath, "utf8"));
    assert.equal(descriptor.version, 1);
    assert.equal(descriptor.sessionID, 1);
    assert.match(descriptor.generation, /^[0-9a-f]{32}$/i);
    assert.equal(dirname(resolve(descriptor.socketPath)), resolve(data.runtimeDirectory));
    assert.ok(data.server.legacyDescriptorPath);
    const legacyDescriptor = JSON.parse(await readFile(data.server.legacyDescriptorPath, "utf8"));
    assert.deepEqual(legacyDescriptor, descriptor);

    // A stale scoped descriptor must not block Build 132's bounded Slot 1
    // compatibility path during rollback or process handoff.
    await writeFile(data.server.descriptorPath, "{stale", { mode: 0o600 });
    const child = spawn(process.execPath, [copiedReceiver], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
    child.stderr.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
    child.stdin.end(frame(snapshotRequest()));
    const exitCode = await new Promise((resolvePromise) => child.once("exit", resolvePromise));
    assert.equal(exitCode, 0, Buffer.concat(stderr).toString("utf8"));
    const response = parseFrame(Buffer.concat(stdout));
    assert.equal(response.ok, true);
    assert.equal(response.operation, "snapshot");

    for (const argumentsList of [["unexpected"], ["--slot", "0"], ["--slot", "7"]]) {
      const rejected = spawn(process.execPath, [copiedReceiver, ...argumentsList], {
        stdio: ["ignore", "pipe", "pipe"],
      });
      const rejectedError = [];
      rejected.stderr.on("data", (chunk) => rejectedError.push(Buffer.from(chunk)));
      const rejectedCode = await new Promise((resolvePromise) => rejected.once("exit", resolvePromise));
      assert.equal(rejectedCode, 1);
      assert.match(Buffer.concat(rejectedError).toString("utf8"), /fixed session slot/i);
    }
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("receiver routes Slot 6 only through its scoped descriptor", async () => {
  const data = await fixture({ mobileSlot: 6 });
  const receiverRoot = dirname(dirname(data.runtimeDirectory));
  const scriptsDirectory = join(receiverRoot, ".pi", "scripts");
  await mkdir(scriptsDirectory, { recursive: true });
  const copiedReceiver = join(scriptsDirectory, "pi-attach-mobile-receiver.mjs");
  await copyFile(join(projectRoot, ".pi", "scripts", "pi-attach-mobile-receiver.mjs"), copiedReceiver);
  try {
    const descriptor = JSON.parse(await readFile(data.server.descriptorPath, "utf8"));
    assert.equal(descriptor.sessionID, 6);
    assert.match(data.server.descriptorPath, /pi-attach-mobile-slot-6\.json$/);

    const child = spawn(process.execPath, [copiedReceiver, "--slot", "6"], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
    child.stderr.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
    child.stdin.end(frame(snapshotRequest()));
    const exitCode = await new Promise((resolvePromise) => child.once("exit", resolvePromise));
    assert.equal(exitCode, 0, Buffer.concat(stderr).toString("utf8"));
    assert.equal(parseFrame(Buffer.concat(stdout)).ok, true);

    const wrong = spawn(process.execPath, [copiedReceiver, "--slot", "3"], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    const wrongCode = await new Promise((resolvePromise) => wrong.once("exit", resolvePromise));
    assert.equal(wrongCode, 1);
  } finally {
    await data.server.close();
    await rm(data.directory, { recursive: true, force: true });
  }
});

test("mobile identity gate accepts all six fixed jarvis-mobile sessions only", async () => {
  const directory = await mkdtemp("/tmp/pia-tmux-");
  const socketPath = join(directory, "jarvis-mobile");
  const tmux = "/opt/homebrew/bin/tmux";
  try {
    const observed = [];
    let slotOneProcess;
    for (const [index, sessionName] of [
      "jarvis-ios",
      "jarvis-ios-2",
      "jarvis-ios-3",
      "jarvis-ios-4",
      "jarvis-ios-5",
      "jarvis-ios-6",
    ].entries()) {
      execFileSync(tmux, [
        "-S", socketPath, "new-session", "-d", "-s", sessionName, "sleep 30",
      ]);
      const identity = execFileSync(
        tmux,
        ["-S", socketPath, "display-message", "-p", "-t", `${sessionName}:`, "#{pane_id}|#{pane_pid}"],
        { encoding: "utf8" },
      ).trim();
      const [paneID, panePID] = identity.split("|");
      const environment = { TMUX: `${socketPath},1,0`, TMUX_PANE: paneID };
      const exact = await mobile.exactMobileTmuxIdentity(environment, Number(panePID));
      assert.equal(exact?.slot, index + 1);
      assert.equal(exact?.sessionName, sessionName);
      assert.equal(await mobile.isExactMobileTmuxProcess(environment, Number(panePID)), true);
      assert.equal(await mobile.isExactMobileTmuxProcess(environment, Number(panePID) + 1), false);
      if (index === 0) slotOneProcess = { environment, processId: Number(panePID) };
      observed.push(paneID);
    }
    assert.equal(new Set(observed).size, 6);
    await assert.rejects(
      mobile.MobileAttachmentServer.start(
        {
          snapshot: async () => ({ revision: 0, limits: {}, staged: [] }),
          prepare: async () => [],
          commit: async () => ({ revision: 0, limits: {}, staged: [] }),
          discard: async () => {},
        },
        {
          runtimeDirectory: join(directory, "runtime"),
          environment: slotOneProcess.environment,
          processId: slotOneProcess.processId,
          mobileSlot: 2,
        },
      ),
      /did not match the protected tmux process/i,
    );

    execFileSync(tmux, [
      "-S", socketPath, "new-session", "-d", "-s", "untrusted-mobile", "sleep 30",
    ]);
    const rejected = execFileSync(
      tmux,
      ["-S", socketPath, "display-message", "-p", "-t", "untrusted-mobile:", "#{pane_id}|#{pane_pid}"],
      { encoding: "utf8" },
    ).toString().trim().split("|");
    assert.equal(
      await mobile.isExactMobileTmuxProcess(
        { TMUX: `${socketPath},1,0`, TMUX_PANE: rejected[0] },
        Number(rejected[1]),
      ),
      false,
    );

    execFileSync(tmux, ["-S", socketPath, "kill-server"]);
    execFileSync(tmux, [
      "-S", socketPath, "new-session", "-d", "-s", "preexisting", "sleep 30",
    ]);
    execFileSync(tmux, [
      "-S", socketPath, "new-session", "-d", "-s", "jarvis-ios", "sleep 30",
    ]);
    const replacedSlotOne = execFileSync(
      tmux,
      ["-S", socketPath, "display-message", "-p", "-t", "jarvis-ios:", "#{pane_id}|#{pane_pid}"],
      { encoding: "utf8" },
    ).trim().split("|");
    assert.notEqual(replacedSlotOne[0], "%0");
    assert.equal(
      await mobile.isExactMobileTmuxProcess(
        { TMUX: `${socketPath},1,0`, TMUX_PANE: replacedSlotOne[0] },
        Number(replacedSlotOne[1]),
      ),
      false,
    );
  } finally {
    try {
      execFileSync(tmux, ["-S", socketPath, "kill-server"]);
    } catch {}
    await rm(directory, { recursive: true, force: true });
  }
});

test("closing a superseded endpoint cannot remove the newer descriptor", async () => {
  const directory = await mkdtemp("/tmp/pia-superseded-");
  const runtimeDirectory = join(directory, ".pi", "runtime");
  const hooks = {
    snapshot: async () => ({
      revision: 0,
      limits: { maxFiles: 1, maxFileBytes: 1, maxTotalBytes: 1 },
      staged: [],
    }),
    prepare: async () => [],
    commit: async () => ({
      revision: 1,
      limits: { maxFiles: 1, maxFileBytes: 1, maxTotalBytes: 1 },
      staged: [],
    }),
    discard: async () => undefined,
  };
  const first = await mobile.MobileAttachmentServer.start(hooks, {
    runtimeDirectory,
    requireExactMobileTmux: false,
  });
  const second = await mobile.MobileAttachmentServer.start(hooks, {
    runtimeDirectory,
    requireExactMobileTmux: false,
  });
  assert.ok(first && second);
  try {
    assert.notEqual(first.generation, second.generation);
    await first.close();
    const current = JSON.parse(await readFile(second.descriptorPath, "utf8"));
    assert.equal(current.generation, second.generation);
    assert.equal(current.socketPath, second.socketPath);
    assert.ok((await lstat(second.socketPath)).isSocket());
  } finally {
    await first.close();
    await second.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test("mobile endpoint does not start outside the exact protected tmux identity", async () => {
  const directory = await mkdtemp("/tmp/pia-identity-");
  try {
    assert.equal(await mobile.isExactMobileTmuxProcess({}), false);
    const server = await mobile.MobileAttachmentServer.start(
      {
        snapshot: async () => ({ revision: 0, limits: { maxFiles: 1, maxFileBytes: 1, maxTotalBytes: 1 }, staged: [] }),
        prepare: async () => [],
        commit: async () => ({ revision: 0, limits: { maxFiles: 1, maxFileBytes: 1, maxTotalBytes: 1 }, staged: [] }),
        discard: async () => undefined,
      },
      { runtimeDirectory: directory, environment: {} },
    );
    assert.equal(server, undefined);
    assert.deepEqual(await readdir(directory), []);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
