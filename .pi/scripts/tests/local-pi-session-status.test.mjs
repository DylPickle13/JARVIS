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

test("local Pi lifecycle remains running until settled without a separate Waiting mode", async () => {
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
      getEntries: () => [{ type: "message", message: { role: "user" } }],
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

    await emit("agent_end", { messages: [] });
    assert.equal((await statusPayload(root)).lifecycle, "running");
    assert.equal((await statusPayload(root)).reason, "agent-end-awaiting-settle");

    await emit("ui_prompt_start", { kind: "confirm" });
    assert.equal((await statusPayload(root)).lifecycle, "running");

    await emit("ui_prompt_end", { kind: "confirm" });
    assert.equal((await statusPayload(root)).lifecycle, "running");

    await emit("session_before_compact", { reason: "threshold" });
    assert.equal((await statusPayload(root)).lifecycle, "compacting");

    await emit("session_compact", { reason: "threshold" });
    assert.equal((await statusPayload(root)).lifecycle, "running");

    // Compaction may finish before its busy flag clears, with no later
    // agent_settled signal. Heartbeat must reconcile without requiring a run.
    idle = true;
    await new Promise((resolve) => setTimeout(resolve, 2150));
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    idle = false;
    await emit("agent_start");
    await emit("session_before_compact", { reason: "overflow", willRetry: true });
    await emit("session_compact", { reason: "overflow", willRetry: true });
    await new Promise((resolve) => setTimeout(resolve, 2150));
    assert.equal((await statusPayload(root)).lifecycle, "running", "automatic continuation stays busy");

    idle = true;
    await emit("agent_settled");
    assert.equal((await statusPayload(root)).lifecycle, "idle");

    await emit("ui_prompt_start", { kind: "select" });
    assert.equal((await statusPayload(root)).lifecycle, "running");
    await new Promise((resolve) => setTimeout(resolve, 2150));
    assert.equal((await statusPayload(root)).lifecycle, "running", "open prompt must keep restart-all blocked");
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
    await emit("session_shutdown");
    await rm(root, { recursive: true, force: true });
  }
});

async function withSession(run) {
  const root = await mkdtemp(join(tmpdir(), "jarvis-pi-new-status-"));
  await mkdir(join(root, ".pi"), { recursive: true });
  await mkdir(join(root, "projects"));
  const handlers = new Map();
  registerLocalPiSessionStatus({ on: (name, handler) => handlers.set(name, handler) });
  const state = { idle: true, entries: [], failHistory: false, sessionFile: "" };
  const ctx = {
    cwd: root,
    isIdle: () => state.idle,
    sessionManager: {
      getSessionFile: () => state.sessionFile,
      getEntries: () => {
        if (state.failHistory) throw new Error("history unavailable");
        return state.entries;
      },
    },
  };
  const emit = async (name, event = {}) => handlers.get(name)?.(event, ctx);
  try { await run({ state, emit, payload: () => statusPayload(root) }); }
  finally {
    await emit("session_shutdown");
    await rm(root, { recursive: true, force: true });
  }
}

test("new/resumed metadata-only sessions are New; conversation evidence is Idle", async () => {
  await withSession(async ({ state, emit, payload }) => {
    for (const [entries, expected] of [
      [[], "new"],
      [[{ type: "model_change" }, { type: "thinking_level_change" }, { type: "custom" }], "new"],
      [[{ type: "message", message: { role: "user", content: "" } }], "idle"],
      [[{ type: "message", message: { role: "assistant", stopReason: "error" } }], "idle"],
      [[{ type: "compaction" }], "idle"],
      [[{ type: "branch_summary" }], "idle"],
    ]) {
      state.entries = entries;
      await emit("session_start", { reason: "resume" });
      assert.equal((await payload()).lifecycle, expected);
      assert.equal((await payload()).hasConversation, expected !== "new");
    }
    // A new session must not inherit the prior conversation's positive flag.
    state.entries = [];
    await emit("session_start", { reason: "new" });
    assert.equal((await payload()).lifecycle, "new");
  });
});

test("first prompt and failed/cancelled response never revert an ephemeral session to New", async () => {
  await withSession(async ({ state, emit, payload }) => {
    await emit("session_start", { reason: "new" });
    assert.equal((await payload()).lifecycle, "new");
    await emit("message_start", { message: { role: "user", content: "test" } });
    assert.equal((await payload()).lifecycle, "idle");
    state.idle = false;
    await emit("agent_start");
    assert.equal((await payload()).lifecycle, "running");
    await emit("message_start", { message: { role: "assistant" } });
    await emit("agent_end", { messages: [{ role: "assistant", stopReason: "aborted" }] });
    state.idle = true;
    await emit("agent_settled");
    assert.equal((await payload()).lifecycle, "idle");
    assert.equal((await payload()).hasConversation, true);
    assert.equal((await payload()).sessionFile, "");
  });
});

test("busy and compacting override New; unresolved history is Unknown rather than New", async () => {
  await withSession(async ({ state, emit, payload }) => {
    state.failHistory = true;
    await emit("session_start");
    assert.equal((await payload()).lifecycle, "unknown");
    assert.equal((await payload()).hasConversation, null);
    state.failHistory = false;
    state.entries = null;
    await emit("agent_settled");
    assert.equal((await payload()).lifecycle, "unknown");
    state.entries = [];
    await emit("agent_settled");
    assert.equal((await payload()).lifecycle, "new");
    await emit("ui_prompt_start");
    assert.equal((await payload()).lifecycle, "running");
    await emit("ui_prompt_end");
    assert.equal((await payload()).lifecycle, "new");
    state.idle = false;
    await emit("agent_start");
    assert.equal((await payload()).lifecycle, "running");
    await emit("session_before_compact");
    assert.equal((await payload()).lifecycle, "compacting");
    state.idle = true;
    await emit("session_compact_failed");
    assert.equal((await payload()).lifecycle, "new");
  });
});

test("heartbeat reconciles imported conversation history without a new prompt", async () => {
  await withSession(async ({ state, emit, payload }) => {
    await emit("session_start");
    assert.equal((await payload()).lifecycle, "new");
    state.entries = [{ type: "message", message: { role: "assistant" } }];
    await new Promise((resolve) => setTimeout(resolve, 2150));
    assert.equal((await payload()).lifecycle, "idle");
  });
});
