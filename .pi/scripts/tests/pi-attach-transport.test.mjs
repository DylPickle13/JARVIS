import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { connect, createServer as createNetServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const globalNodeModules = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const { createJiti } = await import(
  pathToFileURL(
    join(globalNodeModules, "@earendil-works", "pi-coding-agent", "node_modules", "jiti", "lib", "jiti.mjs"),
  ).href
);
const jiti = createJiti(import.meta.url, { interopDefault: true });
const core = await jiti.import(join(projectRoot, ".pi", "extensions", "lib", "attach", "core.ts"));
const transport = await jiti.import(join(projectRoot, ".pi", "extensions", "lib", "attach", "transport.ts"));
const bridgePath = join(projectRoot, ".pi", "scripts", "pi-attach-bridge.mjs");
const pickerLauncherPath = join(projectRoot, ".pi", "scripts", "pi-attach-picker");
const pickerSourcePath = join(projectRoot, ".pi", "scripts", "pi-attach-picker.swift");

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
  throw new Error("timed out waiting for descriptor");
}

test("shared mobile tmux picker accepts only exclusively local VS Code client ancestries", () => {
  const processes = new Map([
    [101, { parentPID: 201, executable: "/opt/homebrew/bin/tmux" }],
    [102, { parentPID: 202, executable: "/opt/homebrew/bin/tmux" }],
    [201, {
      parentPID: 1,
      executable: "/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper",
    }],
    [202, {
      parentPID: 1,
      executable: "/Applications/Visual Studio Code.app/Contents/MacOS/Code",
    }],
  ]);
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([101, 102], processes),
    true,
  );
  assert.equal(transport.allClientProcessesAreLocalVSCode([], processes), false);
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([101, 101], processes),
    false,
  );
});

test("shared mobile tmux picker fails closed for mixed, SSH, and incomplete client ancestries", () => {
  const processes = new Map([
    [101, { parentPID: 201, executable: "/opt/homebrew/bin/tmux" }],
    [102, { parentPID: 302, executable: "/opt/homebrew/bin/tmux" }],
    [103, { parentPID: 303, executable: "/opt/homebrew/bin/tmux" }],
    [201, {
      parentPID: 1,
      executable: "/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper",
    }],
    [302, { parentPID: 402, executable: "/bin/zsh" }],
    [402, { parentPID: 1, executable: "/usr/libexec/sshd-session" }],
    [303, {
      parentPID: 403,
      executable: "/Users/remote/.vscode-server/bin/node",
    }],
    [403, { parentPID: 1, executable: "/usr/libexec/sshd-session" }],
  ]);
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([101, 102], processes),
    false,
  );
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([102], processes),
    false,
  );
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([103], processes),
    false,
  );
  assert.equal(
    transport.allClientProcessesAreLocalVSCode([999], processes),
    false,
  );
});

async function listenUnixProxy(socketPath, port) {
  const server = createNetServer((client) => {
    const upstream = connect(port, "127.0.0.1");
    client.pipe(upstream).pipe(client);
    const closeBoth = () => {
      client.destroy();
      upstream.destroy();
    };
    client.once("error", closeBoth);
    upstream.once("error", closeBoth);
  });
  await new Promise((resolvePromise, rejectPromise) => {
    server.once("error", rejectPromise);
    server.listen(socketPath, resolvePromise);
  });
  return server;
}

test("native picker transport parses a structured multi-file result without shell path interpolation", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-attach-picker-transport-test-"));
  const pickerPath = join(directory, "picker");
  const paths = [join(directory, "one file.txt"), join(directory, "two & file.png")];
  const existing = [{ id: "staged-1", name: "already.txt", sizeBytes: 10 }];
  const limits = { maxFiles: 3, maxFileBytes: 1024, maxTotalBytes: 2048 };
  await writeFile(
    pickerPath,
    `#!/bin/zsh\nprint -r -- '${JSON.stringify({ version: 1, cancelled: false, keepIds: ["staged-1"], paths })}'\n`,
    "utf8",
  );
  await chmod(pickerPath, 0o755);
  try {
    assert.match(await readFile(pickerLauncherPath, "utf8"), /exec "\$BINARY" "\$@"/);
    const pickerSource = await readFile(pickerSourcePath, "utf8");
    assert.match(pickerSource, /setActivationPolicy\(\.regular\)/, "picker must be foreground-activatable");
    assert.match(pickerSource, /activate\(ignoringOtherApps: true\)/, "picker must activate above the terminal");
    assert.doesNotMatch(pickerSource, /setActivationPolicy\(\.accessory\)/);
    assert.deepEqual(await transport.runNativeAttachmentPicker(pickerPath, existing, limits), {
      version: 1,
      cancelled: false,
      keepIds: ["staged-1"],
      paths,
    });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("extension transport retrieves picker files through a private Unix SSH-forward socket", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-attach-transport-test-"));
  const descriptorPath = join(directory, "bridge.json");
  const pickerPath = join(directory, "picker");
  const selectedPath = join(directory, "transport.txt");
  const socketPath = join(directory, "bridge.sock");
  await writeFile(selectedPath, "through unix forwarding\n", "utf8");
  await writeFile(
    pickerPath,
    `#!/bin/zsh\nprint -r -- '${JSON.stringify({ version: 1, cancelled: false, keepIds: [], paths: [selectedPath] })}'\n`,
    "utf8",
  );
  await chmod(pickerPath, 0o755);

  const child = spawn(process.execPath, [bridgePath, "--descriptor", descriptorPath, "--picker", pickerPath], {
    stdio: ["ignore", "ignore", "pipe"],
  });
  const errors = [];
  child.stderr.on("data", (chunk) => errors.push(Buffer.from(chunk)));
  let proxy;
  try {
    const descriptor = await waitForDescriptor(descriptorPath, child);
    proxy = await listenUnixProxy(socketPath, descriptor.port);
    const limits = { maxFiles: 2, maxFileBytes: 1024, maxTotalBytes: 2048 };
    const picked = await transport.requestSshAttachmentPicker([], limits, {
      PI_ATTACH_BRIDGE_SOCKET: socketPath,
      PI_ATTACH_BRIDGE_TOKEN: descriptor.token,
    });
    assert.equal(picked.cancelled, false);
    assert.deepEqual(picked.keepIds, []);
    assert.equal(picked.candidates.length, 1);
    const store = new core.AttachmentStore(join(directory, "attachments"), limits);
    const staged = await store.stage(picked.candidates, "add");
    await picked.release();
    assert.equal(await readFile(staged[0].path, "utf8"), "through unix forwarding\n");
  } finally {
    if (proxy) await new Promise((resolvePromise) => proxy.close(resolvePromise));
    if (child.exitCode === null) child.kill("SIGTERM");
    await new Promise((resolvePromise) => child.once("exit", resolvePromise));
    await rm(directory, { recursive: true, force: true });
  }
  assert.equal(Buffer.concat(errors).toString("utf8"), "");
});
