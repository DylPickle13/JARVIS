import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

// Test the built runtime and the real JARVIS extension, with inert mock tools.
// Override to test the staged/installed coding-agent package, including its core.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const buildFile = join(root, ".pi/runtime/pi-lazy-tools/build.json");
const runtime = process.env.PI_LAZY_TEST_RUNTIME || (existsSync(buildFile)
  ? JSON.parse(readFileSync(buildFile, "utf8")).runtime
  : join(root, ".pi/runtime/pi-lazy-tools/source/packages/coding-agent"));
const requireRuntime = createRequire(join(runtime, "package.json"));
const { createJiti } = requireRuntime("jiti");
const { Type } = await import(pathToFileURL(requireRuntime.resolve("typebox")));
const aiRoot = requireRuntime.resolve.paths("@earendil-works/pi-ai")
  .map((dir) => join(dir, "@earendil-works/pi-ai")).find((dir) => existsSync(join(dir, "package.json")));
const { EventStream } = await import(pathToFileURL(join(aiRoot, "dist/index.js")));
const { splitDeferredTools } = await import(pathToFileURL(join(aiRoot, "dist/utils/deferred-tools.js")));
const sdk = await import(pathToFileURL(join(runtime, process.env.PI_LAZY_TEST_BUNDLED === "1" ? "dist/bundle/index.js" : "dist/index.js")));
const jiti = createJiti(import.meta.url, { interopDefault: true, alias: { typebox: requireRuntime.resolve("typebox") } });
const lazyImport = await jiti.import(join(root, ".pi/extensions/99-lazy-tools.ts"));
const registerLazy = lazyImport.default || lazyImport;
const model = {
  id: "mock", name: "mock", api: "openai-responses", provider: "openai",
  baseUrl: "https://example.invalid", reasoning: false, input: ["text"],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096,
};
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
let nextId = 0;
const call = (name, args = { url: "https://example.invalid" }) => ({ type: "toolCall", id: `call_${++nextId}`, name, arguments: args });
const resultText = (result) => result.content.filter((c) => c.type === "text").map((c) => c.text).join("\n");

async function fixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), "pi-lazy-test-"));
  const executions = [], events = [], requests = [], commands = new Map();
  let api;
  let queued = [];
  const settingsManager = sdk.SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const registerMocks = (pi) => {
    api = pi;
    for (const name of ["browser_open", "browser_status", "reaper_ping", "reaper_lua", "unlisted_tool"]) {
      pi.registerTool({
        name, label: name, description: `Inert ${name} test tool`,
        parameters: Type.Object({ url: Type.String() }),
        executionMode: name === "reaper_ping" ? "sequential" : "parallel",
        async execute(id, args, signal, update) {
          executions.push({ id, name, args, signal });
          if (options.execute) return options.execute({ id, name, args, signal, update });
          return { content: [{ type: "text", text: `actual:${name}` }], details: { original: true } };
        },
      });
    }
    if (options.before) pi.on("tool_call", (e) => options.before(e, pi));
  };
  const lazyFactory = (pi) => {
    // Observe commands without changing production behavior.
    const original = pi.registerCommand.bind(pi);
    pi.registerCommand = (name, command) => { commands.set(name, command); original(name, command); };
    if (options.stock) {
      const { setLazyTools: _omitted, ...stockAPI } = pi;
      registerLazy(stockAPI);
    } else registerLazy(pi);
  };
  const factories = [registerMocks, lazyFactory];
  if (options.after) factories.push((pi) => pi.on("tool_call", (e) => options.after(e, pi)));
  const loader = new sdk.DefaultResourceLoader({ cwd: dir, agentDir: dir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, extensionFactories: factories });
  await loader.reload();
  const { session } = await sdk.createAgentSession({ cwd: dir, agentDir: dir, model, settingsManager,
    sessionManager: sdk.SessionManager.inMemory(), resourceLoader: loader, excludeTools: options.excludeTools });
  await session.bindExtensions({ onError: (error) => { throw new Error(error.error); } });
  session.subscribe((event) => events.push(event));
  session.agent.streamFunction = (_model, context) => {
    requests.push({ tools: context.tools.map((tool) => tool.name), systemPrompt: context.systemPrompt,
      split: splitDeferredTools(context, true), fallback: splitDeferredTools(context, false) });
    const content = queued.length ? queued.shift() : [{ type: "text", text: "done" }];
    const stopReason = content.some((c) => c.type === "toolCall") ? "toolUse" : "stop";
    const message = { role: "assistant", content, api: model.api, provider: model.provider, model: model.id,
      usage, stopReason, timestamp: Date.now() };
    const stream = new EventStream((e) => e.type === "done", (e) => e.message);
    queueMicrotask(() => { stream.push({ type: "done", reason: stopReason, message }); stream.end(message); });
    return stream;
  };
  t.after(async () => { session.dispose(); await rm(dir, { recursive: true, force: true }); });
  return { session, get api() { return api; }, executions, events, requests,
    async run(...batches) {
      queued = batches;
      const before = session.messages.length;
      await session.agent.prompt("test");
      return session.messages.slice(before).filter((m) => m.role === "toolResult");
    },
    async command(name) { await commands.get(name).handler("", { ui: { notify() {} } }); },
  };
}

test("direct hidden call executes once, returns real output/guidance and activates only its group", async (t) => {
  const f = await fixture(t);
  const [result] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 1);
  assert.equal(result.isError, false);
  assert.deepEqual(result.details, { original: true });
  assert.match(resultText(result), /actual:browser_open/);
  assert.match(resultText(result), /Auto-loaded: browser/);
  assert.match(resultText(result), /browser group.*playbook/);
  assert.deepEqual(result.addedToolNames, ["browser_status", "browser_open"]);
  assert(!f.requests[0].tools.includes("browser_open"));
  assert(!f.requests[0].tools.includes("reaper_ping"));
  assert(f.requests[1].tools.includes("browser_open"));
  assert(!f.requests[1].tools.includes("reaper_ping"));
  assert.equal(f.requests[0].systemPrompt, f.requests[1].systemPrompt);
  // Keep Pi's prior-use safeguard: triggering tool is immediate, unused sibling deferred.
  assert(f.requests[1].split.immediate.some((x) => x.name === "browser_open"));
  assert(f.requests[1].split.deferred.has("browser_status"));
  assert.equal(f.requests[1].fallback.deferred.size, 0);
  const [again] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 2);
  assert(!again.addedToolNames?.length);
  assert.doesNotMatch(resultText(again), /Auto-loaded/);
});

test("invalid arguments never execute or activate the group", async (t) => {
  const f = await fixture(t);
  const [result] = await f.run([call("browser_open", { wrong: true })]);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /Validation failed/);
  assert.equal(f.executions.length, 0);
  assert(!f.api.getActiveTools().includes("browser_open"));
});

test("unknown, unlisted, removed and excluded tools remain unavailable", async (t) => {
  const f = await fixture(t, { excludeTools: ["browser_open"] });
  const results = await f.run([call("invented_tool"), call("unlisted_tool"), call("google_maps"), call("browser_open")]);
  assert.equal(results.length, 4);
  assert(results.every((r) => r.isError && /not found/.test(resultText(r))));
  assert.equal(f.executions.length, 0);
  // Even explicit opt-in cannot resurrect an excluded name.
  f.api.setLazyTools(["browser_open"]);
  const [excluded] = await f.run([call("browser_open")]);
  assert.equal(excluded.isError, true);
});

for (const placement of ["before", "after"]) {
  test(`permission guard ${placement} auto-loading still blocks execution`, async (t) => {
    const f = await fixture(t, { [placement]: () => ({ block: true, reason: "permission denied" }) });
    const [result] = await f.run([call("browser_open")]);
    assert.equal(result.isError, true);
    assert.match(resultText(result), /permission denied/);
    assert.equal(f.executions.length, 0);
    if (placement === "after") {
      assert(result.addedToolNames.includes("browser_open"));
      assert.match(resultText(result), /Auto-loaded/);
    } else assert(!result.addedToolNames?.length);
  });
}

test("throwing permission handler fails closed and retains activation metadata", async (t) => {
  const f = await fixture(t, { after: () => { throw new Error("guard failure"); } });
  const [result] = await f.run([call("browser_open")]);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /guard failure/);
  assert(result.addedToolNames.includes("browser_open"));
  assert.equal(f.executions.length, 0);
});

test("parallel sibling calls activate once and preserve result/source ordering", async (t) => {
  const order = [];
  const f = await fixture(t, { execute: async ({ name }) => {
    order.push(`start:${name}`);
    if (name === "browser_open") await new Promise((r) => setTimeout(r, 20));
    order.push(`end:${name}`);
    return { content: [{ type: "text", text: name }], details: {} };
  } });
  const results = await f.run([call("browser_open"), call("browser_status")]);
  assert.deepEqual(results.map((r) => r.toolName), ["browser_open", "browser_status"]);
  assert.equal(results.filter((r) => r.addedToolNames?.length).length, 1);
  assert.equal(results.filter((r) => /Auto-loaded/.test(resultText(r))).length, 1);
  assert.deepEqual(order, ["start:browser_open", "start:browser_status", "end:browser_status", "end:browser_open"]);
});

test("a hidden sequential tool forces the batch to remain sequential", async (t) => {
  const order = [];
  const f = await fixture(t, { execute: async ({ name }) => {
    order.push(`start:${name}`);
    await new Promise((r) => setTimeout(r, 5));
    order.push(`end:${name}`);
    return { content: [{ type: "text", text: name }], details: {} };
  } });
  await f.run([call("browser_open"), call("reaper_ping")]);
  assert.deepEqual(order, ["start:browser_open", "end:browser_open", "start:reaper_ping", "end:reaper_ping"]);
});

test("execution failures keep the error and schema anchor without retrying", async (t) => {
  const f = await fixture(t, { execute: async () => { throw new Error("mock operation failed"); } });
  const [result] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 1);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /mock operation failed/);
  assert.match(resultText(result), /Auto-loaded/);
  assert(result.addedToolNames.includes("browser_open"));
});

test("cancellation after activation prevents execution and retains the anchor", async (t) => {
  let f;
  f = await fixture(t, { after: () => { f.session.agent.abort(); } });
  const [result] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 0);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /Operation aborted/);
  assert(result.addedToolNames.includes("browser_open"));
});

test("reset returns to the lean baseline and the next direct call auto-loads again", async (t) => {
  const f = await fixture(t);
  await f.run([call("browser_open")]);
  await f.command("reset-tools");
  assert(!f.api.getActiveTools().includes("browser_open"));
  const [result] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 2);
  assert.match(resultText(result), /Auto-loaded/);
});

test("explicit loading still anchors unused definitions natively", async (t) => {
  const f = await fixture(t);
  const results = await f.run([call("load_tools", { groups: ["browser"] })], [call("browser_open")]);
  assert.deepEqual(results.map((r) => r.toolName), ["load_tools", "browser_open"]);
  assert(f.requests[1].split.deferred.has("browser_open"));
  assert(f.requests[1].split.deferred.has("browser_status"));
  assert.deepEqual(f.requests[0].split.immediate.map((x) => x.name), f.requests[1].split.immediate.map((x) => x.name));
  assert.equal(f.executions.length, 1);
});

test("disabling the lazy allowlist revokes hidden execution", async (t) => {
  const f = await fixture(t);
  f.api.setLazyTools([]);
  const [result] = await f.run([call("browser_open")]);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /not found/);
  assert.equal(f.executions.length, 0);
});

test("stock-runtime extension fallback keeps explicit loading functional", async (t) => {
  const f = await fixture(t, { stock: true });
  const [hidden] = await f.run([call("browser_open")]);
  assert.equal(hidden.isError, true);
  await f.run([call("load_tools", { groups: ["browser"] })], [call("browser_open")]);
  assert.equal(f.executions.length, 1);
});

test("reload rebuilds the allowlist and resets optional schemas", async (t) => {
  const f = await fixture(t);
  const oldAPI = f.api;
  await f.run([call("browser_open")]);
  await f.session.reload();
  assert.throws(() => oldAPI.setLazyTools(["browser_open"]), /stale|no longer|reload|active/i);
  assert(!f.api.getActiveTools().includes("browser_open"));
  const [result] = await f.run([call("browser_open")]);
  assert.equal(result.isError, false);
  assert.match(resultText(result), /Auto-loaded/);
});

test("environment rollback switch disables implicit calls but not the loader", async (t) => {
  const old = process.env.JARVIS_PI_LAZY_AUTOCALL;
  process.env.JARVIS_PI_LAZY_AUTOCALL = "0";
  let f;
  try { f = await fixture(t); } finally {
    if (old === undefined) delete process.env.JARVIS_PI_LAZY_AUTOCALL;
    else process.env.JARVIS_PI_LAZY_AUTOCALL = old;
  }
  const [hidden] = await f.run([call("browser_open")]);
  assert.equal(hidden.isError, true);
  const results = await f.run([call("load_tools", { groups: ["browser"] })], [call("browser_open")]);
  assert(results.every((r) => !r.isError));
  assert.equal(f.executions.length, 1);
});

test("parallel groups get separate, deterministic activation anchors", async (t) => {
  const f = await fixture(t);
  const results = await f.run([call("browser_open"), call("reaper_lua")]);
  assert.deepEqual(results[0].addedToolNames, ["browser_status", "browser_open"]);
  assert.deepEqual(results[1].addedToolNames, ["reaper_ping", "reaper_lua"]);
  assert(results.every((r) => !r.isError));
});

test("hidden tool streams updates and receives cancellation without retry", async (t) => {
  let f;
  f = await fixture(t, { execute: async ({ signal, update }) => {
    update({ content: [{ type: "text", text: "progress" }], details: {} });
    f.session.agent.abort();
    assert(signal.aborted);
    throw new Error("cancelled in tool");
  } });
  const [result] = await f.run([call("browser_open")]);
  assert.equal(f.executions.length, 1);
  assert.equal(result.isError, true);
  assert.match(resultText(result), /cancelled in tool/);
  assert(result.addedToolNames.includes("browser_open"));
  assert(f.events.some((e) => e.type === "tool_execution_update" && e.toolName === "browser_open"));
});

test("packaged CLI RPC executes a direct hidden call with an offline mock provider", { timeout: 20000 }, async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "pi-lazy-rpc-test-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const extension = join(dir, "offline-extension.ts");
  await writeFile(extension, `
import { EventStream } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import lazy from ${JSON.stringify(join(root, ".pi/extensions/99-lazy-tools.ts"))};
export default function(pi) {
  let requests = 0;
  pi.registerProvider("lazy-offline-test", {
    api: "openai-completions", baseUrl: "https://example.invalid", apiKey: "inert-offline-fixture",
    models: [{ id: "mock", name: "mock", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096 }],
    streamSimple(model, context) {
      const first = ++requests === 1;
      const visible = context.tools.some((tool) => tool.name === "browser_open");
      const badVisibility = first ? visible : !visible;
      const content = badVisibility ? [{ type: "text", text: "BAD_SCHEMA_VISIBILITY" }]
        : first ? [{ type: "toolCall", id: "rpc_direct", name: "browser_open", arguments: { url: "https://example.invalid" } }]
        : [{ type: "text", text: "offline done" }];
      const message = { role: "assistant", content, api: model.api, provider: model.provider, model: model.id,
        usage: ${JSON.stringify(usage)}, stopReason: first && !badVisibility ? "toolUse" : "stop", timestamp: Date.now() };
      const stream = new EventStream((event) => event.type === "done", (event) => event.message);
      queueMicrotask(() => { stream.push({ type: "done", reason: message.stopReason, message }); stream.end(message); });
      return stream;
    }
  });
  pi.registerTool({ name: "browser_open", label: "Mock Browser", description: "Inert offline test",
    parameters: Type.Object({ url: Type.String() }),
    async execute() { return { content: [{ type: "text", text: "RPC_REAL_OUTPUT" }], details: { mock: true } }; }
  });
  lazy(pi);
}
`);
  const child = spawn(process.execPath, [join(runtime, "dist/bundle/cli.js"), "--mode", "rpc", "--no-session",
    "--no-extensions", "--no-skills", "--no-prompt-templates", "--provider", "lazy-offline-test", "--model", "mock", "-e", extension],
  { cwd: dir, env: { PATH: process.env.PATH, HOME: dir, PI_CODING_AGENT_DIR: join(dir, "agent"), PI_OFFLINE: "1",
    PI_TELEMETRY: "0", JARVIS_PI_LAZY_AUTOCALL: "1", TERM: "dumb" }, stdio: ["pipe", "pipe", "pipe"] });
  t.after(() => { if (child.exitCode === null) child.kill("SIGKILL"); });
  let buffer = "", stderr = "";
  const events = [];
  child.stderr.on("data", (data) => { stderr += data.toString(); });
  const done = new Promise((resolveDone, reject) => {
    child.on("error", reject);
    child.stdout.on("data", (data) => {
      buffer += data.toString();
      let end;
      while ((end = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
        try {
          const event = JSON.parse(line);
          events.push(event);
          if (event.type === "agent_end") { child.stdin.end(); resolveDone(); }
          if (event.type === "response" && event.success === false) reject(new Error(JSON.stringify(event)));
        } catch (error) { reject(error); }
      }
    });
    child.on("exit", (code) => { if (!events.some((e) => e.type === "agent_end")) reject(new Error(`RPC exited ${code}: ${stderr}`)); });
  });
  child.stdin.write(`${JSON.stringify({ id: "test", type: "prompt", message: "offline test" })}\n`);
  await done;
  const results = events.filter((e) => e.type === "message_end" && e.message.role === "toolResult").map((e) => e.message);
  assert.equal(results.length, 1, stderr);
  assert.equal(results[0].toolName, "browser_open");
  assert.equal(results[0].isError, false);
  assert.match(resultText(results[0]), /RPC_REAL_OUTPUT/);
  assert.match(resultText(results[0]), /Auto-loaded: browser/);
  assert.deepEqual(results[0].addedToolNames, ["browser_open"]);
  assert(!JSON.stringify(events).includes("BAD_SCHEMA_VISIBILITY"));
});
