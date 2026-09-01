import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const globalNodeModules = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const { createJiti } = await import(
  pathToFileURL(
    join(globalNodeModules, "@earendil-works", "pi-coding-agent", "node_modules", "jiti", "lib", "jiti.mjs"),
  ).href,
);
const jiti = createJiti(import.meta.url, { interopDefault: true });
const imported = await jiti.import(
  join(projectRoot, ".pi", "extensions", "46-local-pi-session-status.ts"),
);
const registerLocalPiSessionStatus = imported.default || imported;

async function statusPayload(root) {
  const dir = join(root, ".pi", "runtime", "local-pi-sessions");
  const files = (await readdir(dir)).filter((name) => name.endsWith(".json"));
  assert.equal(files.length, 1);
  return JSON.parse(await readFile(join(dir, files[0]), "utf8"));
}

test("local Pi lifecycle remains running until settled and reports prompts and compaction", async () => {
  const root = await mkdtemp(join(tmpdir(), "jarvis-pi-lifecycle-"));
  await mkdir(join(root, ".pi"), { recursive: true });
  await mkdir(join(root, "projects"), { recursive: true });

  const handlers = new Map();
  const pi = {
    on(name, handler) {
      const current = handlers.get(name) || [];
      current.push(handler);
      handlers.set(name, current);
    },
  };
  registerLocalPiSessionStatus(pi);

  let idle = true;
  const ctx = {
    cwd: root,
    isIdle: () => idle,
    sessionManager: {
      getSessionFile: () => join(root, "session.jsonl"),
    },
  };
  const emit = async (name, event = {}) => {
    for (const handler of handlers.get(name) || []) await handler(event, ctx);
  };

  try {
    await emit("session_start", { reason: "resume" });
    assert.equal((await statusPayload(root)).version, 2);
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    idle = false;
    await emit("agent_start");
    assert.equal((await statusPayload(root)).lifecycle, "running");

    await emit("agent_end");
    assert.equal((await statusPayload(root)).lifecycle, "running");
    assert.equal((await statusPayload(root)).reason, "agent-end-awaiting-settle");

    await emit("ui_prompt_start", { kind: "confirm" });
    assert.equal((await statusPayload(root)).lifecycle, "waiting");

    await emit("ui_prompt_end", { kind: "confirm" });
    assert.equal((await statusPayload(root)).lifecycle, "running");

    await emit("session_before_compact", { reason: "threshold" });
    assert.equal((await statusPayload(root)).lifecycle, "compacting");

    await emit("session_compact", { reason: "threshold" });
    assert.equal((await statusPayload(root)).lifecycle, "running");

    idle = true;
    await emit("agent_settled");
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    await emit("ui_prompt_start", { kind: "select" });
    assert.equal((await statusPayload(root)).lifecycle, "waiting");
    await emit("ui_prompt_end", { kind: "select" });
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    await emit("session_before_compact", { reason: "manual" });
    assert.equal((await statusPayload(root)).lifecycle, "compacting");
    await emit("session_compact_failed", { reason: "manual", aborted: true });
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    await emit("session_shutdown", { reason: "quit" });
    const remaining = await readdir(join(root, ".pi", "runtime", "local-pi-sessions"));
    assert.deepEqual(remaining, []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
