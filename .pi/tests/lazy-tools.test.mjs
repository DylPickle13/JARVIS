import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { jiti } from './helpers/pi-import.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const imported = await jiti.import(join(root, '.pi/extensions/99-lazy-tools.ts'));
const registerLazy = imported.default || imported;
const groups = ['memory', 'operation_jarvis', 'github', 'google', 'cron', 'reaper', 'browser', 'apple_notes'];
const optionalNames = [
  'memory', 'operation_jarvis_presence', 'operation_jarvis_plugs', 'operation_jarvis_purifier',
  'operation_jarvis_media', 'operation_jarvis_security', 'operation_jarvis_automations',
  'github_cli', 'google_workspace', 'jarvis_cron', 'reaper_ping', 'reaper_lua',
  'browser_status', 'browser_open', 'browser_screenshot', 'browser_click', 'browser_type',
  'browser_upload', 'browser_key', 'browser_scroll', 'browser_wait', 'browser_extract',
  'browser_tabs', 'browser_close', 'apple_notes_search', 'apple_notes_read',
  'apple_notes_write', 'apple_notes_update', 'apple_notes_delete',
];

// Registration and activation only: no real optional tool, model or device runs.
function fixture() {
  const tools = new Map([...['read', 'bash', 'edit', 'write', 'grep', 'find', 'ls', 'ssh',
    'web_search', 'fetch_content', 'get_search_content', 'maps', 'codemode'], ...optionalNames]
    .map(name => [name, { name }]));
  const handlers = new Map(), commands = new Map(), messages = [];
  let active = [...tools.keys()];
  const pi = {
    registerTool: tool => tools.set(tool.name, tool),
    registerCommand: (name, command) => commands.set(name, command),
    on: (name, handler) => { handlers.set(name, handler); return () => handlers.delete(name); },
    getAllTools: () => [...tools.values()],
    getActiveTools: () => [...active],
    setActiveTools: names => { active = [...new Set(names)].filter(name => tools.has(name)); },
    sendMessage: message => messages.push(message),
  };
  registerLazy(pi);
  handlers.get('session_start')();
  return { pi, commands, messages, loader: tools.get('load_tools') };
}

const resultText = result => result.content.map(part => part.text || '').join('\n');

test('owner-requested standalone CLI is allowed while safety guidance remains intact', async () => {
  const { loader } = fixture();
  const result = await loader.execute('inert', { groups: ['operation_jarvis'] });
  const prompt = loader.promptGuidelines.join('\n');
  const playbook = resultText(result);
  for (const guidance of [prompt, playbook]) {
    assert.match(guidance, /Owner-requested standalone CLI diagnosis\/commissioning is allowed/);
    assert.match(guidance, /confirmation, identity, locking, privacy and unknown-write safeguards intact/);
    assert(!/operate devices only through its tools|household control, not shell\/SSH/.test(guidance));
  }
  assert.match(prompt, /Never bypass safety gates or claim actions without tool results/);
  assert.match(playbook, /Unknown write outcome means stop, inspect, never replay/);
  assert.match(playbook, /never expose raw rules, credentials or media/);
});

test('loader advertises only the eight supported groups', () => {
  const { loader } = fixture();
  for (const group of groups) assert(loader.description.includes(`${group}=`));
  assert(!/code_docs|code_search/.test(loader.description));
});

test('retired group is rejected without activating tools or returning its playbook', async () => {
  const { pi, loader } = fixture();
  const before = pi.getActiveTools();
  const result = await loader.execute('inert', { groups: ['code_docs'] });
  assert.deepEqual(result.details.invalidGroups, ['code_docs']);
  assert.match(resultText(result), /Invalid tool group/);
  assert(!result.details.validGroups.includes('code_docs'));
  assert(!resultText(result).includes('code_search'));
  assert.deepEqual(pi.getActiveTools(), before);
});

test('all activates supported groups additively and retains their playbooks', async () => {
  const { pi, loader } = fixture();
  const before = pi.getActiveTools();
  const result = await loader.execute('inert', { groups: ['all'] });
  assert.deepEqual(result.details.groups, groups);
  assert.deepEqual(result.details.missingTools, []);
  for (const name of [...before, ...optionalNames]) assert(pi.getActiveTools().includes(name));
  for (const group of groups) assert(result.details.guidance.includes(`### ${group} group`));
  assert(!/code_docs|code_search/.test(result.details.guidance));
});

test('slash-command loading rejects retired group without changing state', async () => {
  const { pi, commands, messages } = fixture();
  const before = pi.getActiveTools(), notifications = [];
  await commands.get('load-tools').handler('code_docs', { ui: { notify: text => notifications.push(text) } });
  assert.deepEqual(pi.getActiveTools(), before);
  assert.equal(messages.length, 0);
  assert.match(notifications[0], /Invalid group\(s\): code_docs/);
});

test('slimming no longer carries metadata for the removed tool', () => {
  const source = readFileSync(join(root, '.pi/extensions/98-slim-provider-payload.ts'), 'utf8');
  assert(!/code_docs|code_search/.test(source));
});

test('settings template disables only unused built-ins through the real resource loader', async t => {
  const runtime = process.env.PI_CODEMODE_TEST_RUNTIME || '/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent';
  const sdk = await import(pathToFileURL(join(runtime, 'dist/bundle/index.js')));
  const template = JSON.parse(readFileSync(join(root, '.pi/settings.example.json'), 'utf8'));
  assert.deepEqual(template.extensions, ['-builtin:llama.cpp', '-builtin:mcp']);
  assert.equal(template.packages[0].source, 'npm:pi-web-access@0.33.0');
  assert.equal(template.packages[0].extensions, undefined);

  const directory = await mkdtemp(join(tmpdir(), 'pi-builtins-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const loaded = [];
  const settingsManager = sdk.SettingsManager.inMemory({ extensions: template.extensions });
  const resourceLoader = new sdk.DefaultResourceLoader({ cwd: directory, agentDir: resolve(directory, 'agent'),
    settingsManager, noSkills: true, noPromptTemplates: true, noThemes: true,
    extensionFactories: ['llama.cpp', 'mcp', 'codemode', 'tool-search'].map(name => ({
      name, builtin: true, factory: () => { loaded.push(name); },
    })),
  });
  await resourceLoader.reload();
  assert.deepEqual(resourceLoader.getExtensions().errors, []);
  assert.deepEqual(loaded.sort(), ['codemode', 'tool-search']);
});
