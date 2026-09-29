import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, statSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import { once } from 'node:events';
const globalModules = process.env.PI_TEST_NODE_MODULES || execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
const root = join(globalModules, '@earendil-works/pi-coding-agent');
const aiRoot = join(root, 'node_modules/@earendil-works/pi-ai');
const { createJiti } = await import(pathToFileURL(join(root, 'node_modules/jiti/lib/jiti.mjs')));
const jiti = createJiti(import.meta.url, { interopDefault: true, alias: {
  '@earendil-works/pi-coding-agent': join(root, 'dist/index.js'),
  '@earendil-works/pi-ai/compat': join(aiRoot, 'dist/compat.js'),
  '@earendil-works/pi-ai': join(aiRoot, 'dist/index.js'),
} });
const catalog = await jiti.import(resolve('.pi/extensions/lib/omlx-catalog.ts'));
const seeds = await jiti.import(resolve('.pi/extensions/lib/omlx-seeds.ts'));
const recovery = await jiti.import(resolve('.pi/extensions/lib/omlx-recovery.ts'));
const { createOmlxStream } = await jiti.import(resolve('.pi/extensions/lib/omlx-stream.ts'));
const { registerOmlx } = await jiti.import(resolve('.pi/extensions/01-omlx.ts'));
const { createAssistantMessageEventStream } = await jiti.import(join(aiRoot, 'dist/index.js'));
const { normalizeContext } = await jiti.import(join(aiRoot, 'dist/compat.js'));
const { estimateTokens, buildSessionContext } = await jiti.import(join(root, 'dist/index.js'));
const seed = seeds.OMLX_PROVIDER_SEEDS[1];
const temp = () => mkdtempSync(join(tmpdir(), 'pi-omlx-test-'));
const emptyCache = () => ({ version: 2, providers: {} });
const state = (s = seed) => ({ seed: s, baseUrl: 'http://127.0.0.1:8000/v1', apiKey: 'test-key', records: catalog.seedRecords(s), source: 'fallback', warnings: [] });
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });
function fetchFixture(routes, requests = []) {
  return async (url, options) => { requests.push({ url, options }); return json(routes[new URL(url).pathname] ?? {}, new URL(url).pathname in routes ? 200 : 401); };
}
function hooksFixture() {
  const hooks = {}, notices = [], configs = new Map(), commands = {};
  const pi = { on: (name, fn) => (hooks[name] ??= []).push(fn), registerProvider: (name, config) => configs.set(name, config),
    registerCommand: (name, spec) => commands[name] = spec, getThinkingLevel: () => 'medium' };
  const ctx = { model: { ...seed.models[0], provider: seed.provider }, ui: { notify: (...a) => notices.push(a) } };
  const emit = async (name, event = {}, context = ctx) => {
    let result;
    for (const fn of hooks[name] ?? []) { const r = await fn(event, context); if (r !== undefined) result = r; }
    return result;
  };
  return { pi, ctx, emit, notices, configs, commands };
}
const assistant = (content = [], stopReason = 'stop') => ({ role: 'assistant', content, stopReason, provider: 'omlx-64', model: seed.models[0].id,
  api: 'openai-completions', timestamp: 0, usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });

 test('validates endpoints, positive limits, and offline flags', () => {
  assert.equal(catalog.normalizeBaseUrl('https://example.test:9000/'), 'https://example.test:9000/v1');
  assert.equal(catalog.normalizeBaseUrl('http://localhost/v1/'), 'http://localhost/v1');
  for (const u of ['file:///tmp/a', 'https://user:secret@example.test', 'http://localhost?q=secret']) assert.throws(() => catalog.normalizeBaseUrl(u));
  for (const v of [null, true, false, {}, [], 0, -1, 'bad']) assert.equal(catalog.positiveInt(v), undefined);
 });
 test('authenticates public discovery; admin cookie stays on admin routes; no redirects', async () => {
  const requests = [], s = { apiKey: 'api-secret', adminSession: 'cookie-secret' };
  const fetcher = async (url, options) => { requests.push({ url, options }); return json({}); };
  await catalog.fetchJson('https://example.test/v1/models', s, undefined, 20, fetcher);
  await catalog.fetchJson('https://example.test/admin/api/models', s, undefined, 20, fetcher);
  assert.equal(requests[0].options.headers.authorization, 'Bearer api-secret');
  assert.equal(requests[0].options.headers.cookie, undefined);
  assert.equal(requests[1].options.headers.cookie, 'omlx_admin_session=cookie-secret');
  assert.equal(requests[1].options.redirect, 'error');
  const bad = await catalog.fetchJson('https://example.test/v1/models', s, undefined, 20, async () => { throw new Error('api-secret cookie-secret'); });
  assert.ok(!JSON.stringify(bad).includes('secret'));
 });
 test('discovers complete chat catalog, filters helper models, applies live limits and private cache', async () => {
  const dir = temp();
  try {
    const s = state(), cache = emptyCache(), path = join(dir, 'catalog.json'), requests = [];
    const models = await catalog.discoverCatalog(s, cache, path, undefined, fetchFixture({
      '/v1/models/status': { models: [
        { id: seed.models[0].id, model_type: 'vlm', config_model_type: 'qwen3_5', max_context_window: 262144, max_tokens: 8192, loaded: true },
        { id: 'NewModel', model_type: 'llm', display_name: 'New Model', max_context_window: 64000, max_tokens: 4000, thinking_default: false, preserve_thinking_default: true },
        { id: 'NewModel', model_type: 'llm', max_context_window: 64000, max_tokens: 4000 },
        { id: 'Embed', model_type: 'embedding', max_context_window: 64000, max_tokens: 4000 },
        { id: 'Rank', model_type: 'reranker', max_context_window: 64000, max_tokens: 4000 },
        { id: 'MarkItDown', model_type: 'markitdown' }, { id: 'Missing', model_type: 'llm' },
        { id: 'Hidden', model_type: 'llm', is_hidden: true, max_context_window: 4000, max_tokens: 1000 },
      ] },
      '/v1/models': { data: [{ id: seed.models[0].id, max_model_len: 262144 }, { id: 'NewModel', max_model_len: 32768 }] },
      '/admin/api/models': { models: [{ id: seed.models[0].id, settings: { max_context_window: 65536, max_tokens: 16000, forced_ct_kwargs: ['enable_thinking'] } }] },
      '/admin/api/global-settings': { sampling: {} },
      '/api/status': { model_memory_used_formatted: '20 GB', model_memory_max_formatted: '50 GB' },
    }, requests));
    assert.deepEqual(models.map(m => m.id), [seed.models[0].id, 'NewModel']);
    assert.equal(models[0].contextWindow, 65536); assert.equal(models[0].maxTokens, 16000);
    assert.deepEqual(models[0].input, ['text', 'image']);
    assert.equal(models[0].thinkingLevelMap.high, 'xhigh'); assert.equal(models[0].compat.chatTemplateKwargs.preserve_thinking, true);
    assert.equal(models[1].contextWindow, 32768); assert.equal(models[1].name, 'New Model'); assert.deepEqual(models[1].input, ['text']);
    assert.equal(models[1].reasoning, true); assert.deepEqual(models[1].compat.chatTemplateKwargs.enable_thinking, { $var: 'thinking.enabled' });
    assert.equal(s.source, 'live'); assert.equal(s.memory, '20 GB / 50 GB');
    assert.ok(s.warnings.some(w => w.includes('Missing')));
    assert.equal(statSync(path).mode & 0o777, 0o600);
    assert.ok(!readFileSync(path, 'utf8').includes('test-key'));
    const loaded = catalog.loadCatalogCache(path);
    assert.equal(catalog.restoreRecords(seed, s.baseUrl, loaded).source, 'cache');
    assert.equal(catalog.restoreRecords(seed, 'http://other/v1', loaded).source, 'fallback');
    assert.deepEqual(loaded.providers[seed.provider].models.map(m => m.id), models.map(m => m.id));
    assert.ok(requests.every(r => r.options.headers.authorization === 'Bearer test-key'));
  } finally { rmSync(dir, { recursive: true, force: true }); }
 });
 test('runtime VLM capability is not shadowed by architecture names; explicit modality overrides still work', async () => {
  const dir = temp();
  try {
    const models = await catalog.discoverCatalog(state(), emptyCache(), join(dir, 'cache'), undefined, fetchFixture({
      '/v1/models/status': { models: [
        { id: 'Vision', model_type: 'vlm', engine_type: 'vlm', config_model_type: 'qwen3_5', max_context_window: 32000, max_tokens: 4000 },
        { id: 'Text', model_type: 'llm', engine_type: 'llm', config_model_type: 'qwen3_5', max_context_window: 32000, max_tokens: 4000 },
        { id: 'TextOverride', model_type: 'vlm', config_model_type: 'qwen3_5', max_context_window: 32000, max_tokens: 4000 },
        { id: 'VisionOverride', model_type: 'llm', config_model_type: 'qwen3_5', max_context_window: 32000, max_tokens: 4000 },
      ] },
      '/v1/models': { data: [] },
      '/admin/api/models': { models: [
        { id: 'Vision', settings: { model_type_override: null } },
        { id: 'TextOverride', settings: { model_type_override: 'llm' } },
        { id: 'VisionOverride', settings: { model_type_override: 'vlm' } },
      ] },
      '/admin/api/global-settings': { sampling: {} },
    }));
    assert.deepEqual(models.map(m => [m.id, m.input]), [
      ['Vision', ['text', 'image']], ['Text', ['text']], ['TextOverride', ['text']], ['VisionOverride', ['text', 'image']],
    ]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
 });
 test('fallback model-list discovery uses global settings, warns about admin auth and never invents limits', async () => {
  const dir = temp();
  try {
    const s = state();
    const models = await catalog.discoverCatalog(s, emptyCache(), join(dir, 'cache'), undefined, fetchFixture({
      '/v1/models': { data: [{ id: 'Public', max_model_len: 10000 }, { id: 'NoLimits' }] },
      '/admin/api/global-settings': { sampling: { max_context_window: 5000, max_tokens: 1000 } },
    }));
    assert.equal(models[0].contextWindow, 5000); assert.equal(models[0].maxTokens, 1000);
    assert.ok(s.warnings.some(w => w.includes('HTTP 401')));
  } finally { rmSync(dir, { recursive: true, force: true }); }
 });
 test('effort vocabulary shapes dynamic model menu and known overrides remain stable', () => {
  const r = { ...catalog.seedRecords(seed)[0], id: 'Effort', reasoning: true, thinkingDefault: true, effortOptions: ['low', 'high'] };
  const m = catalog.modelFromRecord(r, seed);
  assert.equal(m.thinkingLevelMap.low, 'low'); assert.equal(m.thinkingLevelMap.medium, null);
  assert.equal(m.compat.thinkingFormat, 'chat-template');
  assert.equal(catalog.modelFromRecord({ ...r, id: seed.models[0].id }, seed).thinkingLevelMap.high, 'xhigh');
 });
 test('retains cache on host failure, honors cancellation and PI_OFFLINE without network', async () => {
  const dir = temp(), old = process.env.PI_OFFLINE;
  try {
    const s = state(), original = structuredClone(s.records), cache = emptyCache();
    await catalog.discoverCatalog(s, cache, join(dir, 'cache'), undefined, async () => { throw new Error('secret payload'); });
    assert.deepEqual(s.records, original); assert.equal(s.source, 'fallback'); assert.ok(s.lastError); assert.deepEqual(cache.providers, {});
    let calls = 0;
    const aborted = new AbortController(); aborted.abort();
    await catalog.discoverCatalog(s, cache, join(dir, 'cache'), aborted.signal, async () => { calls++; return json({}); });
    process.env.PI_OFFLINE = 'true';
    await catalog.discoverCatalog(s, cache, join(dir, 'cache'), undefined, async () => { calls++; return json({}); });
    assert.equal(calls, 0);
  } finally { if (old === undefined) delete process.env.PI_OFFLINE; else process.env.PI_OFFLINE = old; rmSync(dir, { recursive: true, force: true }); }
 });
 test('migrates legacy cache, rejects corrupt catalogs and stale endpoint snapshots', () => {
  const dir = temp();
  try {
    const legacy = join(dir, 'old.json');
    writeFileSync(legacy, JSON.stringify({ version: 1, providers: { [seed.provider]: { baseUrl: 'http://localhost/v1', updatedAt: 'then', models: { [seed.models[0].id]: 42000 } } } }));
    assert.equal(catalog.restoreRecords(seed, 'http://localhost/v1', emptyCache(), legacy).records[0].contextWindow, 42000);
    const path = join(dir, 'new.json'); writeFileSync(path, '{'); assert.deepEqual(catalog.loadCatalogCache(path), emptyCache());
    writeFileSync(path, JSON.stringify({ version: 2, providers: { bad: { baseUrl: 'http://localhost/v1', models: [{ id: 'x', contextWindow: null, maxTokens: 4000 }] } } }));
    assert.equal(catalog.loadCatalogCache(path).providers.bad.models.length, 0);
  } finally { rmSync(dir, { recursive: true, force: true }); }
 });
 test('registers both hosts synchronously with isolated keys, max_tokens, and UI-only diagnostics', async () => {
  const dir = temp(), fixture = hooksFixture();
  try {
    const custom = seeds.OMLX_PROVIDER_SEEDS.map((s, i) => ({ ...s, baseUrlEnvKeys: [`TEST_URL_${i}`], apiKeyEnvKeys: [`TEST_KEY_${i}`], adminSessionEnvKeys: [] }));
    let calls = 0;
    const instance = registerOmlx(fixture.pi, { seeds: custom, dotenv: { TEST_URL_0: 'http://localhost:8001', TEST_URL_1: 'http://localhost:8002', TEST_KEY_0: 'host-one', TEST_KEY_1: 'host-two' },
      cachePath: join(dir, 'cache'), legacyPath: join(dir, 'old'), fetcher: async () => { calls++; return json({}); } });
    assert.equal(calls, 0); assert.equal(fixture.configs.size, 2);
    assert.equal(fixture.configs.get('omlx').apiKey, 'host-one'); assert.equal(fixture.configs.get('omlx-64').apiKey, 'host-two');
    assert.ok(fixture.configs.get('omlx-64').models.every(m => m.compat.maxTokensField === 'max_tokens' && m.compat.supportsDeveloperRole === false));
    await fixture.configs.get('omlx-64').refreshModels({ allowNetwork: false }); assert.equal(calls, 0);
    await fixture.commands['omlx-status'].handler('', fixture.ctx);
    const output = fixture.notices.at(-1)[0]; assert.ok(output.includes('fallback')); assert.ok(output.includes('thinking medium'));
    assert.ok(!output.includes('host-one') && !output.includes('host-two'));
    await fixture.emit('session_start'); await fixture.emit('session_shutdown');
    await new Promise(r => setTimeout(r, 550)); assert.equal(calls, 0);
    assert.equal(instance.states.length, 2);
  } finally { await fixture.emit('session_shutdown'); rmSync(dir, { recursive: true, force: true }); }
 });
 test('normalizes only oMLX overflow and preserves other errors/providers', async () => {
  const f = hooksFixture(), s = { emptyRetries: 0, overflowCompactions: 0, disableThinkingOnce: false };
  recovery.registerOmlxRecovery(f.pi, s);
  for (const errorMessage of [
    'Prompt too long: 50000 tokens exceeds max context window of 32000 tokens',
    'oMLX prefill memory guard rejected',
    'Request aborted: process memory limit exceeded. Please reduce context length',
  ]) {
    const r = await f.emit('message_end', { message: { ...assistant([], 'error'), errorMessage } });
    assert.ok(r.message.errorMessage.startsWith('context_length_exceeded:'));
  }
  assert.equal(await f.emit('message_end', { message: { ...assistant([], 'error'), errorMessage: 'HTTP 429' } }), undefined);
  assert.equal(await f.emit('message_end', { message: { ...assistant([], 'error'), provider: 'other', errorMessage: 'oMLX prefill memory guard rejected' } }), undefined);
 });
 test('empty recovery is bounded, disables thinking once, never retries visible text/tools/abort', async () => {
  const f = hooksFixture(), s = { emptyRetries: 0, overflowCompactions: 0, disableThinkingOnce: false };
  recovery.registerOmlxRecovery(f.pi, s);
  const event = { message: assistant([{ type: 'thinking', thinking: 'private' }]), toolResults: [], context: { canContinue: true }, outcome: 'completed' };
  for (const m of [assistant([{ type: 'text', text: 'Answer' }]), assistant([{ type: 'toolCall', id: 't', name: 'write', arguments: {} }]), assistant([], 'aborted'), assistant([], 'length')]) {
    assert.equal(await f.emit('turn_end', { ...event, message: m }), undefined);
  }
  const r = await f.emit('turn_end', event); assert.equal(r.continue, true); assert.equal(r.entries[0].display, false);
  const payload = await f.emit('before_provider_request', { payload: { model: 'x', chat_template_kwargs: { keep: true } } });
  assert.equal(payload.thinking_budget, 0); assert.equal(payload.chat_template_kwargs.enable_thinking, false); assert.equal(payload.chat_template_kwargs.keep, true);
  assert.equal(await f.emit('before_provider_request', { payload: {} }), undefined);
  assert.equal(await f.emit('turn_end', event), undefined); assert.ok(s.lastAction.includes('manual intervention'));
  await f.emit('before_agent_start'); assert.equal(s.emptyRetries, 0);
  assert.equal(await f.emit('turn_end', { ...event, continue: true }), undefined);
 });
 test('emergency summary preserves recent constraints/files, excludes thinking/images, obeys token cap', async () => {
  const entries = [
    { id: 'u0', type: 'message', message: { role: 'user', content: 'INITIAL REQUEST' } },
    ...Array.from({ length: 12 }, (_, i) => ({ id: `u${i + 1}`, type: 'message', message: { role: 'user', content: `Follow-up ${i}\nMust preserve NEW CONSTRAINT ${i}` } })),
    { id: 'u99', type: 'message', message: { role: 'user', content: 'LATEST REQUEST: only modify oMLX; do not change servers' } },
    { id: 'a', type: 'message', message: assistant([{ type: 'text', text: '- Completed tests\n- Next: run checks\nhttps://example.test/source' }, { type: 'thinking', thinking: 'SECRET THOUGHT' }, { type: 'image', data: 'SECRET IMAGE' }]) },
  ];
  const prep = { messagesToSummarize: entries.map(e => e.message), turnPrefixMessages: [], tokensBefore: 99999, fileOps: { read: new Set(['read.ts', 'edit.ts']), edited: new Set(['edit.ts']), written: new Set(['new.ts']) } };
  const result = recovery.buildEmergencyOverflowCompaction(prep, entries, 12000);
  assert.ok(result.summary.includes('LATEST REQUEST')); assert.ok(result.summary.includes('NEW CONSTRAINT 11'));
  assert.deepEqual(result.details.modifiedFiles, ['edit.ts', 'new.ts']); assert.deepEqual(result.details.readFiles, ['read.ts']);
  assert.ok(!result.summary.includes('SECRET')); assert.ok(estimateTokens({ role: 'user', content: result.summary, timestamp: 0 }) <= result.details.tokenBudget);
  const f = hooksFixture(), s = { emptyRetries: 0, overflowCompactions: 0, disableThinkingOnce: false }; recovery.registerOmlxRecovery(f.pi, s);
  const compact = await f.emit('session_before_compact', { reason: 'overflow', preparation: prep, branchEntries: entries, signal: new AbortController().signal });
  assert.equal(compact.compaction.firstKeptEntryId, recovery.KEEP_NONE_ENTRY_ID);
  assert.equal(await f.emit('session_before_compact', { reason: 'manual', preparation: prep, branchEntries: entries }), undefined);
  const checkpoint = { id: 'c', parentId: 'a', type: 'compaction', ...compact.compaction };
  const projected = buildSessionContext([...entries, checkpoint]);
  assert.ok(projected.messages.length > 0); assert.ok(!JSON.stringify(projected.messages).includes('SECRET IMAGE'));
  assert.ok(!JSON.stringify(projected.messages).includes('SECRET THOUGHT'));
 });
 test('stream wrapper delegates instrumentation and forwards exactly one terminal event', async () => {
  const message = assistant([{ type: 'text', text: 'Hello 🌍' }]), events = [];
  let received;
  const inner = (_m, _c, options) => {
    received = options;
    const s = createAssistantMessageEventStream();
    queueMicrotask(() => { s.push({ type: 'start', partial: message }); s.push({ type: 'text_delta', contentIndex: 0, delta: 'Hello 🌍', partial: message }); s.push({ type: 'done', reason: 'stop', message }); s.end(); });
    return s;
  };
  const options = { onPayload: () => {}, onResponse: () => {}, onProviderStreamEvent: () => {} };
  const stream = createOmlxStream(50, e => { throw new Error(e); }, inner)( { ...seed.models[0], provider: seed.provider, api: 'openai-completions' }, { messages: [] }, options);
  for await (const e of stream) events.push(e);
  assert.deepEqual(events.map(e => e.type), ['start', 'text_delta', 'done']);
  for (const name of ['onPayload', 'onResponse', 'onProviderStreamEvent']) assert.equal(received[name], options[name]);
 });
 test('first-delta timeout ignores keepalives, aborts once without replay; cancellation remains aborted', async () => {
  for (const cancel of [false, true]) {
    let calls = 0; const reported = [], events = [], parent = new AbortController();
    const inner = (_m, _c, options) => {
      calls++;
      const s = createAssistantMessageEventStream();
      queueMicrotask(() => s.push({ type: 'start', partial: assistant() }));
      options.signal.addEventListener('abort', () => { s.push({ type: 'error', reason: 'aborted', error: { ...assistant([], 'aborted'), errorMessage: 'aborted' } }); s.end(); }, { once: true });
      return s;
    };
    const stream = createOmlxStream(25, e => reported.push(e), inner)({ ...seed.models[0], provider: seed.provider, api: 'openai-completions' }, { messages: [] }, { signal: parent.signal });
    if (cancel) setTimeout(() => parent.abort(), 5);
    for await (const e of stream) events.push(e);
    assert.equal(calls, 1); assert.equal(events.filter(e => e.type === 'error' || e.type === 'done').length, 1);
    assert.equal(events.at(-1).reason, cancel ? 'aborted' : 'error');
    if (!cancel) assert.ok(events.at(-1).error.errorMessage.includes('timeout'));
  }
 });
 test('actual Pi request uses max_tokens, valid Qwen effort, preserved thinking and instrumentation', async () => {
  const requests = [];
  const server = createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    requests.push({ headers: req.headers, payload: JSON.parse(Buffer.concat(chunks).toString()) });
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    res.write('data: ' + JSON.stringify({ id: 'test', object: 'chat.completion.chunk', choices: [{ index: 0, delta: { role: 'assistant', content: 'Hello 🌍' }, finish_reason: null }] }) + '\n\n');
    res.write('data: ' + JSON.stringify({ id: 'test', object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 3, total_tokens: 13 } }) + '\n\n');
    res.end('data: [DONE]\n\n');
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  try {
    const model = { ...catalog.modelFromRecord(catalog.seedRecords(seed)[0], seed), provider: seed.provider, api: 'openai-completions', baseUrl: `http://127.0.0.1:${server.address().port}/v1` };
    let responses = 0, payloadHooks = 0, providerEvents = 0;
    for (const level of ['high', undefined]) {
      const transcript = normalizeContext({ systemPrompt: 'Be concise', messages: [{ role: 'user', content: 'Hello', timestamp: 0 }], tools: [] });
      const stream = createOmlxStream(5000, () => {})(model, transcript, { apiKey: 'test-wire-key', reasoning: level,
        onPayload: payload => { payloadHooks++; return { ...payload, metadata: { test: true } }; },
        onResponse: () => { responses++; }, onProviderStreamEvent: () => { providerEvents++; }, });
      const events = []; for await (const event of stream) events.push(event);
      assert.equal(events.at(-1).type, 'done', JSON.stringify(events.at(-1)));
      assert.equal(events.at(-1).message.content.find(p => p.type === 'text').text, 'Hello 🌍');
      assert.equal(events.at(-1).message.usage.output, 3);
    }
    assert.equal(responses, 2); assert.equal(payloadHooks, 2); assert.ok(providerEvents >= 2);
    for (const request of requests) {
      assert.equal(request.headers.authorization, 'Bearer test-wire-key');
      assert.ok(request.payload.max_tokens > 0); assert.equal(request.payload.max_completion_tokens, undefined);
      assert.equal(request.payload.chat_template_kwargs.preserve_thinking, true);
      assert.equal(request.payload.metadata.test, true);
    }
    assert.equal(requests[0].payload.chat_template_kwargs.reasoning_effort, 'xhigh');
    assert.equal(requests[0].payload.chat_template_kwargs.enable_thinking, true);
    assert.equal(requests[1].payload.chat_template_kwargs.enable_thinking, false);
    assert.equal(requests[1].payload.chat_template_kwargs.reasoning_effort, undefined);
    const effort = catalog.modelFromRecord({ ...catalog.seedRecords(seed)[0], id: 'EffortOnly', reasoning: true, effortOptions: ['low', 'high'] }, seed);
    const effortStream = createOmlxStream(5000, () => {})({ ...effort, provider: seed.provider, api: 'openai-completions', baseUrl: model.baseUrl }, normalizeContext({ messages: [{ role: 'user', content: 'Hello', timestamp: 0 }] }), { apiKey: 'test-wire-key' });
    for await (const event of effortStream) if (event.type === 'error') assert.fail('Effort-only serialization failed');
    assert.equal(requests.at(-1).payload.reasoning_effort, 'none');
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
 });
 test('cancelling discovery after requests start never changes or persists the catalog', async () => {
  const dir = temp(), controller = new AbortController(), s = state(), cache = emptyCache();
  const before = structuredClone(s.records); let calls = 0;
  try {
    const work = catalog.discoverCatalog(s, cache, join(dir, 'cache'), controller.signal, async (_url, options) => {
      calls++;
      await new Promise(resolve => options.signal.addEventListener('abort', resolve, { once: true }));
      return json({ models: [{ id: 'New', model_type: 'llm', max_context_window: 4000, max_tokens: 1000 }], data: [] });
    });
    assert.equal(calls, 5); controller.abort(); await work;
    assert.deepEqual(s.records, before); assert.deepEqual(cache.providers, {}); assert.equal(s.source, 'fallback');
  } finally { rmSync(dir, { recursive: true, force: true }); }
 });
 test('fetch timeout cancels the HTTP request and reports only a safe category', async () => {
  let aborted = false;
  const result = await catalog.fetchJson('http://localhost/v1/models', state(), undefined, 10, async (_url, options) => {
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => { aborted = true; reject(new Error('secret response body')); }, { once: true }));
  });
  assert.equal(aborted, true); assert.deepEqual(result, { error: 'timeout' });
 });
 test('bounded summaries handle multilingual/emoji text without split surrogate pairs', () => {
  const text = '最新约束：不要重复已经完成的操作。🌍🛠️ '.repeat(1000);
  const result = recovery.boundSummary(text, 128, 10000);
  assert.ok(estimateTokens({ role: 'user', content: result, timestamp: 0 }) <= 128);
  assert.ok(Buffer.byteLength(result, 'utf8') / 2 <= 128);
  assert.ok(!/[\uD800-\uDBFF]$/.test(result));
 });
