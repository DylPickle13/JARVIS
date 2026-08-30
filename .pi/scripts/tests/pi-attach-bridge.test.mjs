import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { request } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const bridgePath = join(projectRoot, ".pi", "scripts", "pi-attach-bridge.mjs");

async function waitForDescriptor(path, child) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`bridge exited early with ${child.exitCode}`);
    try {
      return JSON.parse(await readFile(path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 10));
  }
  throw new Error("timed out waiting for bridge descriptor");
}

function bridgeRequest(descriptor, method, path, payload, token = descriptor.token) {
  const body = payload === undefined ? undefined : Buffer.from(JSON.stringify(payload), "utf8");
  return new Promise((resolvePromise, rejectPromise) => {
    const req = request(
      {
        hostname: descriptor.host,
        port: descriptor.port,
        method,
        path,
        headers: {
          authorization: `Bearer ${token}`,
          ...(body
            ? {
                "content-type": "application/json",
                "content-length": String(body.length),
              }
            : {}),
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.on("end", () =>
          resolvePromise({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }),
        );
      },
    );
    req.once("error", rejectPromise);
    if (body) req.write(body);
    req.end();
  });
}

async function stopChild(child) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolvePromise) => child.once("exit", resolvePromise)),
    new Promise((resolvePromise) => setTimeout(resolvePromise, 2_000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

test("temporary SSH attachment bridge authenticates, picks, streams, releases, and cancels", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-attach-bridge-test-"));
  const descriptorPath = join(directory, "bridge.json");
  const pickerResultPath = join(directory, "picker-result.json");
  const pickerPath = join(directory, "fake-picker");
  const selectedPath = join(directory, "selected file.txt");
  await writeFile(selectedPath, "bridge payload\n", "utf8");
  const pickerRequestPath = join(directory, "picker-request.json");
  await writeFile(
    pickerResultPath,
    JSON.stringify({ version: 1, cancelled: false, keepIds: ["existing-1"], paths: [selectedPath] }),
    "utf8",
  );
  await writeFile(
    pickerPath,
    `#!/bin/zsh\nprint -rn -- "$1" > "$PI_ATTACH_TEST_PICKER_REQUEST_FILE"\ncat "$PI_ATTACH_TEST_PICKER_RESULT_FILE"\n`,
    "utf8",
  );
  await chmod(pickerPath, 0o755);

  const stderr = [];
  const child = spawn(process.execPath, [bridgePath, "--descriptor", descriptorPath, "--picker", pickerPath], {
    env: {
      ...process.env,
      PI_ATTACH_TEST_PICKER_RESULT_FILE: pickerResultPath,
      PI_ATTACH_TEST_PICKER_REQUEST_FILE: pickerRequestPath,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  child.stderr.on("data", (chunk) => stderr.push(Buffer.from(chunk)));

  try {
    const descriptor = await waitForDescriptor(descriptorPath, child);
    assert.equal(descriptor.version, 1);
    assert.match(descriptor.token, /^[0-9a-f]{64}$/);

    const unauthorized = await bridgeRequest(
      descriptor,
      "POST",
      "/v1/pick",
      { version: 1, existing: [], limits: { maxFiles: 2, maxFileBytes: 1024, maxTotalBytes: 2048 } },
      "0".repeat(64),
    );
    assert.equal(unauthorized.status, 401);

    const pickRequest = {
      version: 1,
      existing: [{ id: "existing-1", name: "already staged.txt", sizeBytes: 5 }],
      limits: { maxFiles: 2, maxFileBytes: 1024, maxTotalBytes: 2048 },
    };
    const pickedResponse = await bridgeRequest(descriptor, "POST", "/v1/pick", pickRequest);
    assert.equal(pickedResponse.status, 200, pickedResponse.body.toString("utf8"));
    const picked = JSON.parse(pickedResponse.body.toString("utf8"));
    assert.equal(picked.version, 1);
    assert.equal(picked.cancelled, false);
    assert.deepEqual(picked.keepIds, ["existing-1"]);
    assert.equal(picked.files.length, 1);
    assert.equal(picked.files[0].name, "selected file.txt");
    assert.deepEqual(JSON.parse(await readFile(pickerRequestPath, "utf8")), pickRequest);

    const fileResponse = await bridgeRequest(descriptor, "GET", `/v1/files/${picked.files[0].id}`);
    assert.equal(fileResponse.status, 200);
    assert.equal(fileResponse.body.toString("utf8"), "bridge payload\n");
    assert.equal(Number(fileResponse.headers["content-length"]), fileResponse.body.length);

    const released = await bridgeRequest(descriptor, "POST", "/v1/release", { ids: [picked.files[0].id] });
    assert.equal(released.status, 200);
    const missing = await bridgeRequest(descriptor, "GET", `/v1/files/${picked.files[0].id}`);
    assert.equal(missing.status, 404);

    await writeFile(pickerResultPath, JSON.stringify({ version: 1, cancelled: true, keepIds: [], paths: [] }), "utf8");
    const cancelledResponse = await bridgeRequest(descriptor, "POST", "/v1/pick", pickRequest);
    assert.equal(cancelledResponse.status, 200);
    assert.deepEqual(JSON.parse(cancelledResponse.body.toString("utf8")), {
      version: 1,
      cancelled: true,
      keepIds: ["existing-1"],
      files: [],
    });
  } finally {
    await stopChild(child);
    await rm(directory, { recursive: true, force: true });
  }

  assert.equal(Buffer.concat(stderr).toString("utf8"), "");
});
