import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { jiti } from './helpers/pi-import.mjs';

const { REAPER_QUERY_GUIDELINES: policy } = await jiti.import(resolve(import.meta.dirname, '../extensions/lib/reaper-query-policy.ts'));
const { default: registerBridge } = await jiti.import(resolve(import.meta.dirname, '../extensions/58-reaper-bridge.ts'));
const { default: registerLazy } = await jiti.import(resolve(import.meta.dirname, '../extensions/99-lazy-tools.ts'));
const { default: registerSlim } = await jiti.import(resolve(import.meta.dirname, '../extensions/98-slim-provider-payload.ts'));

const tools = new Map();
// Registration only. No tool execution, SSH, REAPER, model, or device calls.
registerBridge({ registerTool: tool => tools.set(tool.name, tool) });
const resultText = result => result.content.map(part => part.text || '').join('\n');

function lazyFixture(autoLoad = false) {
  const definitions = new Map([...['read', 'ssh', 'memory'], ...tools.keys()].map(name => [name, tools.get(name) || { name }]));
  const handlers = new Map();
  let active = [...definitions.keys()];
  const pi = {
    registerTool: tool => definitions.set(tool.name, tool),
    registerCommand() {},
    on: (name, handler) => { handlers.set(name, handler); },
    getAllTools: () => [...definitions.values()],
    getActiveTools: () => active,
    setActiveTools: names => { active = [...names]; },
    ...(autoLoad ? { setLazyTools() {} } : {}),
  };
  registerLazy(pi);
  handlers.get('session_start')();
  return { loader: definitions.get('load_tools'), handlers };
}

function assertPolicy(text) {
  for (const line of policy) assert(text.includes(line), `missing REAPER guidance: ${line}`);
}

test('both REAPER tools carry the same source-query policy without changing callable parameters', () => {
  assert.deepEqual([...tools.keys()], ['reaper_ping', 'reaper_lua']);
  for (const tool of tools.values()) assert.deepEqual(tool.promptGuidelines, policy);
  assert.deepEqual(Object.keys(tools.get('reaper_ping').parameters.properties), ['timeoutSeconds', 'host', 'remoteDir']);
  assert.deepEqual(Object.keys(tools.get('reaper_lua').parameters.properties), ['code', 'timeoutSeconds', 'host', 'remoteDir']);
  assert.match(tools.get('reaper_lua').parameters.properties.code.description, /50 rows and 8 KiB/);
  assert.match(tools.get('reaper_ping').description, /never dump REAPER's full accessibility tree/);
  assert.match(tools.get('reaper_lua').description, /small, filtered pages/);
});

test('policy addresses the Actions-window trigger before serialization, not just display truncation', () => {
  const text = policy.join('\n');
  assert.match(text, /filter by track\/item\/FX\/action identity before enumeration/);
  assert.match(text, /page collections with explicit offsets and limits/);
  assert.match(text, /Filter the Actions list by the exact bridge name before inspecting at most 20 matching rows/);
  assert.match(text, /Never request `entire contents` of REAPER windows or the application/);
  assert.match(text, /select scalar names\/values rather than raw UI object lists/);
  assert.match(text, /cap each text field and the total serialized output to 8 KiB/);
  assert.match(text, /save them privately and print only their path and a brief summary, never the full stdout/);
});

test('bridge-unavailable guidance preserves owner authorization and unknown-write safeguards', () => {
  const text = policy.join('\n');
  assert.match(text, /timeout means the bridge is unavailable, not permission to launch REAPER/);
  assert.match(text, /change routing, start transport\/recording, or repeat a possibly completed write/);
  assert.match(text, /owner's existing authorization/);
});

test('explicit and repeated REAPER loading return the policy, including when schemas are already active', async () => {
  const { loader } = lazyFixture();
  const first = await loader.execute('inert', { groups: ['reaper'] });
  assertPolicy(resultText(first));
  assertPolicy(first.details.guidance);
  const repeated = await loader.execute('inert', { groups: ['reaper'] });
  assert.deepEqual(repeated.details.addedToolNames, []);
  assertPolicy(resultText(repeated));
  assert.match(resultText(repeated), /Do not save temporary task scripts for REAPER work/);
  assert.match(resultText(repeated), /Do not guess REAPER\/ReaScript API signatures/);
});

test('automatic REAPER loading also injects the policy before a direct tool result', () => {
  const { handlers } = lazyFixture(true);
  const result = handlers.get('tool_call')({ toolName: 'reaper_ping' });
  assertPolicy(result.toolResultContent.map(part => part.text).join('\n'));
});

test('REAPER query guidance is absent from unrelated group loading and generic loader rules', async () => {
  const { loader } = lazyFixture();
  const result = await loader.execute('inert', { groups: ['memory'] });
  for (const line of policy) {
    assert(!resultText(result).includes(line));
    assert(!loader.promptGuidelines.includes(line));
  }
});

test('loading all groups retains the REAPER policy', async () => {
  const { loader } = lazyFixture();
  assertPolicy(resultText(await loader.execute('inert', { groups: ['all'] })));
});

test('provider slimming preserves the direct REAPER query descriptions and code budget', () => {
  const handlers = new Map();
  registerSlim({ on: (name, handler) => handlers.set(name, handler) });
  const payload = { tools: [...tools.values()].map(tool => ({ name: tool.name, description: tool.description, parameters: tool.parameters })) };
  assert.deepEqual(handlers.get('before_provider_request')({ payload }).tools, payload.tools);
});
