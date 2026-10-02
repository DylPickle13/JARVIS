import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const runtime = process.env.PI_CODEMODE_TEST_RUNTIME || '/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent';
const sdk = await import(pathToFileURL(join(runtime, 'dist/bundle/index.js')));
const requireRuntime = createRequire(join(runtime, 'package.json'));
const { createJiti } = requireRuntime('jiti');
const { Type } = await import(pathToFileURL(requireRuntime.resolve('typebox')));
const { EventStream } = await import(pathToFileURL(join(runtime, 'node_modules/@earendil-works/pi-ai/dist/index.js')));
const jiti = createJiti(import.meta.url, { interopDefault: true, alias: { typebox: requireRuntime.resolve('typebox') } });
const lazyModule = await jiti.import(join(root, '.pi/extensions/99-lazy-tools.ts'));
const slimModule = await jiti.import(join(root, '.pi/extensions/98-slim-provider-payload.ts'));
const registerLazy = lazyModule.default || lazyModule;
const registerSlim = slimModule.default || slimModule;
let nextId = 0;
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const resultText = r => r.content.filter(c => c.type === 'text').map(c => c.text).join('\n');

async function fixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'pi-codemode-test-'));
  let api;
  const commands = new Map(), calls = [], executed = [], requests = [], contexts = [];
  const settingsManager = sdk.SettingsManager.inMemory({ defaultTools: options.disabled ? ['read'] : ['read', '+codemode'],
    defaultProvider: 'openai-codex', defaultModel: 'gpt-6-astra', compaction: { enabled: false }, retry: { enabled: false } });
  const mocks = pi => {
    api = pi;
    pi.registerTool({ name: 'browser_status', label: 'Inert status', description: 'Inert test status',
      parameters: Type.Object({}),
      async execute(id, args, signal) {
        executed.push({ id, args, signal });
        if (options.execute) return options.execute(signal);
        return { content: [{ type: 'text', text: 'inert-status' }] };
      },
    });
    if (options.promptState) pi.on('before_agent_start', event => {
      event.systemPromptOptions.appendSystemPrompt = options.promptState.addendum;
    });
    pi.on('tool_call', e => {
      calls.push(e);
      if (options.block && e.toolName === 'browser_status') return { block: true, reason: 'Inert permission gate denied' };
    });
  };
  const lazy = pi => {
    const original = pi.registerCommand.bind(pi);
    pi.registerCommand = (name, command) => { commands.set(name, command); original(name, command); };
    registerLazy(pi);
  };
  const loader = new sdk.DefaultResourceLoader({ cwd: dir, agentDir: dir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
    extensionFactories: [sdk.createCodemodeExtension({ mode: 'on' }), mocks, lazy, ...(options.slim ? [registerSlim] : [])] });
  await loader.reload();
  const modelRuntime = await sdk.ModelRuntime.create({ authPath: join(dir, 'auth.json'), modelsPath: null,
    modelsStorePath: join(dir, 'models-store.json'), allowModelNetwork: false, refreshOnCreate: false });
  // Auth is inert too: Codex is OAuth-only and ignores API-key availability.
  // The stream below is replaced; no credential store or network is consulted.
  modelRuntime.hasConfiguredAuth = provider => provider === 'openai-codex';
  const { session } = await sdk.createAgentSession({ cwd: dir, agentDir: dir, settingsManager, resourceLoader: loader, modelRuntime,
    sessionManager: sdk.SessionManager.inMemory(dir), excludeTools: options.excludeTools });
  await session.bindExtensions({ onError: e => { throw new Error(e.error); } });
  let queued = [];
  session.agent.streamFunction = (model, context) => {
    requests.push(session.getActiveToolNames());
    contexts.push(structuredClone(context));
    const content = queued.length ? queued.shift() : [{ type: 'text', text: 'done' }];
    const stopReason = content.some(c => c.type === 'toolCall') ? 'toolUse' : 'stop';
    const message = { role: 'assistant', content, api: model.api, provider: model.provider, model: model.id,
      usage, stopReason, timestamp: Date.now() };
    const stream = new EventStream(e => e.type === 'done', e => e.message);
    queueMicrotask(() => { stream.push({ type: 'done', reason: stopReason, message }); stream.end(message); });
    return stream;
  };
  t.after(async () => { session.dispose(); await rm(dir, { recursive: true, force: true }); });
  return { session, api, calls, executed, requests, contexts,
    async reset() { await commands.get('reset-tools').handler('', { ui: { notify() {} } }); },
    async run(code) {
      const before = session.messages.length;
      queued = [[{ type: 'toolCall', id: `test_${++nextId}`, name: 'codemode', arguments: { code } }]];
      if (options.promptLifecycle) await session.prompt('inert test');
      else await session.agent.prompt('inert test');
      const result = session.messages.slice(before).filter(m => m.role === 'toolResult').at(-1);
      assert(result, JSON.stringify(session.messages.slice(before)));
      return result;
    },
  };
}

test('optional codemode survives startup and reset without hiding direct tools', async t => {
  const f = await fixture(t);
  assert(f.api.getActiveTools().includes('codemode'));
  assert(f.api.getActiveTools().includes('read'));
  await f.reset();
  assert(f.api.getActiveTools().includes('codemode'));
  const result = await f.run('return 42;');
  assert.equal(result.isError, false);
  assert.match(resultText(result), /42/);
  assert(f.requests[0].includes('read'));
});

test('disabled and explicitly excluded codemode are not re-enabled', async t => {
  for (const options of [{ disabled: true }, { excludeTools: ['codemode'] }]) {
    const f = await fixture(t, options);
    assert(!f.api.getActiveTools().includes('codemode'));
    await f.reset();
    assert(!f.api.getActiveTools().includes('codemode'));
  }
});

test('scripts load an optional group then execute an inert tool exactly once', async t => {
  const f = await fixture(t);
  await f.run('return await tools.load_tools({ groups: ["browser"] });');
  const result = await f.run('return await tools.browser_status({});');
  assert.equal(result.isError, false, resultText(result));
  assert.match(resultText(result), /inert-status/);
  assert.equal(f.executed.length, 1);
  assert(f.api.getActiveTools().includes('browser_status'));
  assert(f.api.getActiveTools().includes('codemode'));
});

test('newly loaded tools require a subsequent script, not the current snapshot', async t => {
  const f = await fixture(t);
  const first = await f.run('await tools.load_tools({ groups: ["browser"] }); return await tools.browser_status({});');
  assert.equal(first.isError, true);
  assert.match(resultText(first), /does not exist/);
  assert.equal(f.executed.length, 0);
  const next = await f.run('return await tools.browser_status({});');
  assert.equal(next.isError, false);
  assert.equal(f.executed.length, 1);
});

test('nested script calls still pass permission gates and can recover', async t => {
  const f = await fixture(t, { block: true });
  await f.run('return await tools.load_tools({ groups: ["browser"] });');
  const result = await f.run('try { await tools.browser_status({}); } catch (e) { return { caught: true, error: String(e) }; } throw new Error("gate bypassed");');
  assert.equal(result.isError, false, resultText(result));
  assert.match(resultText(result), /Inert permission gate denied/);
  assert.equal(f.executed.length, 0);
  assert(f.calls.some(c => c.toolName === 'browser_status' && c.parentToolCallId));
});

test('excluded optional tools remain unavailable through scripts', async t => {
  const f = await fixture(t, { excludeTools: ['browser_status'] });
  await f.run('return await tools.load_tools({ groups: ["browser"] });');
  const result = await f.run('return await tools.browser_status({});');
  assert.equal(result.isError, true);
  assert.equal(f.executed.length, 0);
});

test('script deadline aborts a pending nested call', async t => {
  let aborted = false;
  const f = await fixture(t, { execute: signal => new Promise((resolve, reject) => {
    const abort = () => { aborted = true; reject(new Error('aborted')); };
    if (signal.aborted) abort(); else signal.addEventListener('abort', abort, { once: true });
  }) });
  await f.run('return await tools.load_tools({ groups: ["browser"] });');
  const result = await f.run('// @options: {"timeout_ms": 500}\nreturn await tools.browser_status({});');
  assert.equal(result.isError, true);
  assert.equal(f.executed.length, 1);
  assert.equal(aborted, true);
});

test('slimming preserves the initial prefix when a real prompt loads tools and starts another turn', async t => {
  const promptState = { addendum: 'Original owner policy.' };
  const f = await fixture(t, { slim: true, promptLifecycle: true, promptState });
  await f.run('return await tools.load_tools({ groups: ["browser"] });');
  const [before, after] = f.contexts;
  assert(before.messages[0].sections, 'startup must not force/flatten the system prompt');
  assert.deepEqual(after.messages.slice(0, before.messages.length), before.messages);
  const additions = after.messages.slice(before.messages.length).filter(m => m.role === 'system');
  assert(additions.some(m => m.toolsAdded?.some(tool => tool.name === 'browser_status')));
  assert(!after.messages[0].toolsAdded.some(tool => tool.name === 'browser_status'));
  promptState.addendum = 'Updated owner policy; preserve it as a later instruction.';
  await f.run('return await tools.browser_status({});');
  assert.deepEqual(f.contexts[2].messages.slice(0, after.messages.length), after.messages);
  assert(f.contexts[2].messages.some(m => m.sections?.addendum?.includes(promptState.addendum)));
  assert.equal(f.executed.length, 1);

  // Offline A/B: exercise both native addition formats, without a provider call.
  const { convertResponsesMessages } = await import(pathToFileURL(join(runtime,
    'node_modules/@earendil-works/pi-ai/dist/api/openai-responses-shared.js')));
  const { resolveTranscriptTools } = await import(pathToFileURL(join(runtime,
    'node_modules/@earendil-works/pi-ai/dist/utils/transcript.js')));
  for (const supportsAdditionalTools of [true, false]) {
    const opts = { includeSystemPrompt: false, supportsMidConvoSystemMessages: true,
      supportsAdditionalTools, supportsToolSearch: true };
    const convert = context => convertResponsesMessages(f.session.model, context, new Set(['openai-codex']), opts);
    const a = convert(before), b = convert(after);
    assert.deepEqual(b.slice(0, a.length), a);
    assert(b.some(item => item.type === (supportsAdditionalTools ? 'additional_tools' : 'tool_search_output')));
    assert.deepEqual(resolveTranscriptTools(before.messages, true).requestTools,
      resolveTranscriptTools(after.messages, true).requestTools);
  }
});

test('payload slimming preserves codemode call and return-type guidance', async () => {
  let handler;
  registerSlim({ on: (name, fn) => { if (name === 'before_provider_request') handler = fn; } });
  assert(handler);
  const suffix = '\n\nCodemode: `tools.read(args)` resolves to text.';
  const payload = { tools: [
    { type: 'function', name: 'read', description: 'Long original description' + suffix, parameters: { type: 'object' } },
    { type: 'function', function: { name: 'read', description: 'Long original description' + suffix, parameters: { type: 'object' } } },
  ] };
  const result = await handler({ payload });
  const compacted = result || payload;
  assert(compacted.tools[0].description.endsWith(suffix));
  assert(compacted.tools[1].function.description.endsWith(suffix));
  assert(!compacted.tools[0].description.startsWith('Long'));
});
