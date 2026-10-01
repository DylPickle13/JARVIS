#!/usr/bin/env node
// Live, read-only codemode compatibility test. Uses configured credentials;
// no persistent sessions/settings, no discovered tools, no production actions.
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { resolve, join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const runtime = process.env.PI_CODEMODE_TEST_RUNTIME || '/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent';
const sdk = await import(pathToFileURL(join(runtime, 'dist/bundle/index.js')));
const config = JSON.parse(await readFile(join(root, '.pi/settings.json'), 'utf8'));
const requested = process.argv.slice(2);
const models = requested.length ? requested : config.enabledModels;
const fixtures = await mkdtemp(join(tmpdir(), 'pi-codemode-smoke-'));
const outputDir = join(root, '.pi/runtime/codemode-smoke', new Date().toISOString().replace(/[:.]/g, '-'));
await mkdir(outputDir, { recursive: true, mode: 0o700 });
await writeFile(join(fixtures, 'a.json'), JSON.stringify([{ id: 'a', value: 4 }, { id: 'b', value: 9 }]));
await writeFile(join(fixtures, 'b.json'), JSON.stringify([{ id: 'c', value: 12 }, { id: 'd', value: 2 }]));
const allowed = new Set(['a.json', 'b.json', 'missing.json'].map(p => join(fixtures, p)));
let calls = [], results = [], messages = [], steps = 0;
const guard = pi => {
  pi.on('tool_call', e => {
    calls.push({ name: e.toolName, args: e.input, parentToolCallId: e.parentToolCallId });
    if (++steps > 16) return { block: true, reason: 'Smoke-test tool budget exceeded' };
    if (e.toolName === 'codemode') return;
    if (e.toolName !== 'read' || !allowed.has(resolve(fixtures, e.input.path || ''))) {
      return { block: true, reason: 'Read-only smoke test: only fixture reads are permitted' };
    }
  });
};
const settingsManager = sdk.SettingsManager.inMemory({
  defaultTools: ['read', 'codemode'], codemode: { mode: 'on' },
  compaction: { enabled: false }, retry: { enabled: false },
});
const loader = new sdk.DefaultResourceLoader({
  cwd: root, agentDir: sdk.getAgentDir(), settingsManager,
  noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
  additionalExtensionPaths: [join(root, '.pi/extensions/01-omlx.ts'), join(root, '.pi/extensions/98-slim-provider-payload.ts')],
  extensionFactories: [sdk.createCodemodeExtension({ mode: 'on' }), guard],
  agentsFilesOverride: () => ({ agentsFiles: [] }),
  systemPromptOverride: () => 'You are testing Pi codemode. Perform only requested read-only fixture operations. Use codemode scripts for all tool work. Never call models APIs. Read returns file text. Keep the final answer brief.',
  appendSystemPromptOverride: () => [],
});
await loader.reload();
const { session } = await sdk.createAgentSession({
  cwd: fixtures, agentDir: sdk.getAgentDir(), settingsManager, resourceLoader: loader,
  tools: ['read', 'codemode'], sessionManager: sdk.SessionManager.inMemory(fixtures),
});
const summary = [];
try {
  await session.bindExtensions({ onError: e => console.error('Extension error:', e.error) });
  session.subscribe(e => {
    if (e.type === 'tool_execution_end') results.push({ name: e.toolName, isError: e.isError, result: e.result });
    if (e.type === 'message_end' && e.message.role === 'assistant') messages.push(e.message);
  });
  console.log('Artifacts:', outputDir, '\nActive tools:', session.getActiveToolNames().join(', '));
  for (const key of models) {
    calls = []; results = []; messages = []; steps = 0;
    const start = Date.now();
    let error;
    let timedOut = false;
    const i = key.indexOf('/');
    console.log('TEST', key);
    try {
      const model = session.modelRuntime.getModel(key.slice(0, i), key.slice(i + 1));
      if (!model) throw new Error('Model unavailable in runtime catalog');
      await session.setModel(model);
      session.setThinkingLevel(config.modelThinkingLevels?.[key] || 'medium');
      const timer = setTimeout(() => { timedOut = true; void session.abort(); }, Number(process.env.PI_CODEMODE_TEST_TIMEOUT_MS || 180000));
      try {
        await session.prompt(`Use codemode (not direct read calls) to test the following in one script:\n1. Read ${join(fixtures, 'a.json')} and ${join(fixtures, 'b.json')} concurrently with Promise.all or Promise.allSettled.\n2. Parse the JSON arrays and return only records whose value is >= 9, plus their sum.\n3. Intentionally read ${join(fixtures, 'missing.json')}; catch its error, then successfully read a.json again to demonstrate recovery.\nReturn a JSON object with ids (sorted), sum, caughtError (boolean), recoveryFirstId. Do not output full file contents. Actually execute the script; do not merely describe it. Do not call any models APIs.`);
      } finally { clearTimeout(timer); }
      if (timedOut) error = 'Timed out';
    } catch (e) { error = String(e); }
    const scripts = calls.filter(c => c.name === 'codemode');
    const readCalls = calls.filter(c => c.name === 'read');
    const outputs = results.filter(r => r.name === 'codemode').flatMap(r =>
      r.result.content.filter(c => c.type === 'text').map(c => c.text));
    const observed = outputs.flatMap(text => text.split('\n').flatMap(line => {
      try { const value = JSON.parse(line); return value && typeof value === 'object' ? [value] : []; }
      catch { return []; }
    })).find(value => JSON.stringify(value.ids) === '["b","c"]' && value.sum === 21 &&
      value.caughtError === true && value.recoveryFirstId === 'a');
    const final = messages.at(-1);
    const text = final?.content?.filter(c => c.type === 'text').map(c => c.text).join('\n') || '';
    const providerError = messages.find(m => m.stopReason === 'error')?.errorMessage;
    const recovered = readCalls.some((c, index) => c.args?.path?.endsWith('/missing.json') && readCalls.slice(index + 1).some(n => n.args?.path?.endsWith('/a.json')));
    const pass = !error && !providerError && scripts.length > 0 && scripts.some(c => /Promise\.all(?:Settled)?/.test(JSON.stringify(c.args))) &&
      readCalls.length >= 4 && readCalls.every(c => c.parentToolCallId) && recovered && Boolean(observed);
    const row = { model: key, pass, seconds: Math.round((Date.now() - start) / 1000), codemodeCalls: scripts.length,
      fixtureReads: readCalls.length, recovered, observed, error: error || providerError, final: text,
      replayedPreviousModelHistory: summary.length > 0 };
    summary.push(row);
    await writeFile(join(outputDir, key.replaceAll('/', '__') + '.json'), JSON.stringify({ ...row, calls, results, messages }, null, 2), { mode: 0o600 });
    await writeFile(join(outputDir, 'summary.json'), JSON.stringify(summary, null, 2), { mode: 0o600 });
    console.log(JSON.stringify(row));
  }
} finally {
  session.dispose();
  await rm(fixtures, { recursive: true, force: true });
}
console.log('SUMMARY', outputDir);
process.exitCode = summary.every(r => r.pass) ? 0 : 1;
