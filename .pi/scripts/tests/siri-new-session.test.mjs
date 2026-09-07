import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { promisify } from "node:util";
const modules = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const { createJiti } = await import(pathToFileURL(join(modules, "@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti.mjs")));
const jiti = createJiti(import.meta.url, { interopDefault: true });
const { SiriNewSessionGate, hasConversation, validPrompt, startSiriNewSessionServer } = await jiti.import(resolve(import.meta.dirname, "../../extensions/lib/siri-new-session.ts"));

function fixture() {
  const state = { idle: true, promptActive: false, compacting: false, entries: [], draft: "", pending: false };
  const sent = [];
  const gate = new SiriNewSessionGate(() => state.idle && !state.promptActive && !state.compacting && !state.pending && !state.draft && !hasConversation(state.entries), p => sent.push(p));
  return { state, sent, gate };
}

test("only positively empty, idle, undrafted sessions can accept", async () => {
  for (const change of [s => s.idle = false, s => s.promptActive = true, s => s.compacting = true,
    s => s.draft = "unsent", s => s.pending = true,
    ...["user", "assistant"].map(role => s => s.entries.push({ type: "message", message: { role } })),
    ...["compaction", "branch_summary"].map(type => s => s.entries.push({ type }))]) {
    const { state, gate, sent } = fixture(); change(state);
    assert.equal(gate.available(), false);
    assert.equal(await gate.submit("prompt"), "unavailable"); assert.equal(sent.length, 0);
  }
  const gate = new SiriNewSessionGate(() => { throw Error("missing history"); }, () => assert.fail());
  assert.equal(gate.available(), false);
  assert.equal(hasConversation([{ type: "model_change" }]), false);
});

test("claim is atomic; acknowledgement waits for matching actual user message", async () => {
  const { gate, sent } = fixture();
  const first = gate.submit("literal /new is not a command");
  assert.equal(gate.available(), false);
  assert.equal(await gate.submit("second"), "unavailable");
  assert.equal(gate.input({ source: "extension", text: sent[0] }), true);
  assert.equal(gate.input({ source: "extension", text: sent[0] }), false);
  assert.equal(gate.input({ source: "interactive", text: "a competing draft" }), false);
  gate.message({ role: "user", content: [{ type: "text", text: sent[0] }] });
  assert.equal(await first, "sent"); assert.equal(sent.length, 1);
  assert.equal(gate.input({ source: "interactive", text: "ordinary follow-up" }), true);
  assert.equal(gate.available(), false);
});

test("in-flight ordinary input wins even before history or heartbeat updates", async () => {
  const { gate, sent } = fixture();
  assert.equal(gate.input({ source: "interactive", text: "first" }), true);
  assert.equal(await gate.submit("Siri"), "unavailable"); assert.equal(sent.length, 0);
});

test("new history or draft racing the initial probe is refused", async () => {
  const { gate, state, sent } = fixture();
  assert.equal(gate.available(), true);
  state.entries.push({ type: "message", message: { role: "user" } });
  assert.equal(await gate.submit("Siri"), "unavailable"); assert.equal(sent.length, 0);
  const other = fixture(); const pending = other.gate.submit("Siri");
  other.state.draft = "new typing";
  assert.equal(other.gate.input({ source: "extension", text: "Siri" }), false);
  assert.equal(await pending, "unconfirmed");
});

test("failed, timed out and shutdown submissions never free or retry a claim", async () => {
  const { gate, sent } = fixture();
  assert.equal(await gate.submit("Siri", 5), "unconfirmed");
  assert.equal(await gate.submit("again"), "unavailable"); assert.equal(sent.length, 1);
  assert.equal(gate.input({ source: "extension", text: "Siri" }), false, "a timed-out delayed input must not be admitted");
  const other = fixture(); const pending = other.gate.submit("Siri"); other.gate.close();
  assert.equal(await pending, "unconfirmed");
  assert.equal(other.gate.input({ source: "extension", text: "Siri" }), false);
  const broken = new SiriNewSessionGate(() => true, () => { throw Error("failure"); });
  assert.equal(await broken.submit("Siri"), "unconfirmed"); assert.equal(broken.available(), false);
});

test("payload bounds reject controls and count UTF-8 bytes", () => {
  for (const value of [null, "", " ", "a\r", "a\n", "\x7f", "\x85", "é".repeat(2049)]) assert.equal(validPrompt(value), false);
  assert.equal(validPrompt("é".repeat(2048)), true);
});

test("real private IPC validates generation, slot, request and bounded admission", async () => {
  const runtime = await mkdtemp(join(tmpdir(), "siri-ipc-"));
  let gate;
  gate = new SiriNewSessionGate(() => true, prompt => {
    assert.equal(gate.input({ source: "extension", text: prompt }), true);
    queueMicrotask(() => gate.message({ role: "user", content: [{ type: "text", text: prompt }] }));
  });
  const stop = await startSiriNewSessionServer(runtime, 9, gate);
  const descriptor = JSON.parse(await readFile(join(runtime, "slot-9.json"), "utf8"));
  function exchange(payload) {
    return new Promise(resolve => {
      const socket = createConnection(descriptor.socketPath); let data = "";
      socket.on("connect", () => socket.write(JSON.stringify(payload) + "\n"));
      socket.on("data", b => data += b); socket.on("error", () => {});
      socket.on("close", () => resolve(data ? JSON.parse(data) : undefined));
    });
  }
  try {
    assert.equal((await stat(runtime)).mode & 0o777, 0o700);
    assert.equal((await stat(descriptor.socketPath)).mode & 0o777, 0o600);
    const base = { version: 1, generation: descriptor.generation };
    assert.equal((await exchange({ ...base, operation: "probe" })).available, true);
    assert.equal(await exchange({ ...base, generation: "wrong", operation: "submit", requestID: randomUUID(), prompt: "never" }), undefined);
    const requestID = randomUUID();
    const result = await exchange({ ...base, operation: "submit", requestID, prompt: '"'.repeat(4096) });
    assert.equal(result.state, "sent"); assert.equal(result.sessionID, 9); assert.equal(result.requestID, requestID);
    assert.equal((await exchange({ ...base, operation: "probe" })).available, false);
  } finally { await stop(); await rm(runtime, { recursive: true, force: true }); }
});


test("Python allocator to real IPC to registered Pi hooks sends once, then refuses", async () => {
  const { registerSiriNewSession } = await jiti.import(resolve(import.meta.dirname, "../../extensions/04-siri-new-session.ts"));
  const root = await mkdtemp("/tmp/siri-hooks-");
  await mkdir(join(root, ".pi")); await mkdir(join(root, "projects"));
  const handlers = new Map(), entries = [], sent = [];
  let idle = true;
  const ctx = { cwd: root, hasUI: true, isIdle: () => idle, hasPendingMessages: () => false,
    sessionManager: { getEntries: () => entries }, ui: { getEditorText: () => "", setEditorText: () => assert.fail(), notify: () => {} } };
  const admissionSignals = [];
  const pi = {
    events: { emit: (name, data) => { assert.equal(name, "jarvis:siri-admission"); admissionSignals.push(data.pending); } },
    on: (event, hook) => handlers.set(event, hook),
    sendUserMessage: text => {
      sent.push(text);
      const result = handlers.get("input")({ source: "extension", text }, ctx);
      assert.equal(result.action, "continue");
      idle = false;
      const message = { role: "user", content: [{ type: "text", text }] };
      entries.push({ type: "message", message });
      handlers.get("message_start")({ message }, ctx);
    },
  };
  registerSiriNewSession(pi, async () => ({ slot: 9, sessionName: "jarvis-ios-9", paneID: "%8" }));
  await handlers.get("session_start")({}, ctx);
  const app = resolve(import.meta.dirname, "../../../projects/operation-jarvis/jarvis-app");
  const code = `import sys,json,uuid
from terminald.siri_new_session import SiriNewSessionRouter,NewSessionError
router=SiriNewSessionRouter(sys.argv[1],sys.argv[2],lambda:{9:int(sys.argv[3])})
try: print(json.dumps(router.submit(dict(requestID=str(uuid.uuid4()),prompt='first and only'))))
except NewSessionError as e: print(json.dumps(dict(code=e.code)))
`;
  const call = async () => JSON.parse((await promisify(execFile)("python3", ["-c", code, join(root, ".pi/runtime/siri-new"), join(root, "journal"), String(process.pid)], {
    env: { ...process.env, PYTHONPATH: app, PYTHONDONTWRITEBYTECODE: "1" }, timeout: 5000,
  })).stdout);
  try {
    assert.equal((await call()).sessionID, 9);
    idle = true; // ordinary Idle with history is not eligible
    assert.equal((await call()).code, "no_new_session");
    assert.deepEqual(sent, ["first and only"]);
    assert.equal(entries.length, 1);
    assert.deepEqual(admissionSignals, [true, false]);
  } finally { await handlers.get("session_shutdown")(); await rm(root, { recursive: true, force: true }); }
});


test("unexpected message before admission cannot release a delayed Siri input", async () => {
  for (const role of ["user", "assistant"]) {
    const { gate } = fixture();
    const pending = gate.submit("Siri");
    gate.message({ role, content: [{ type: "text", text: "someone else" }] });
    assert.equal(await pending, "unconfirmed");
    assert.equal(gate.input({ source: "extension", text: "Siri" }), false);
    assert.equal(await gate.submit("again"), "unavailable");
  }
});
