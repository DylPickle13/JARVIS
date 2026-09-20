#!/usr/bin/env node
// Opt-in local inference only. Schemas are real; NO household tool executes.
// Usage: node .pi/scripts/eval-operation-jarvis.mjs --model MODEL_ID
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { jiti } from '../tests/helpers/pi-import.mjs';
const modelIndex = process.argv.indexOf('--model');
const model = modelIndex >= 0 ? process.argv[modelIndex + 1] : undefined;
if (!model) throw Error('Explicit --model MODEL_ID required; local inference only, no tool execution');
const base = process.env.OPERATION_JARVIS_EVAL_URL || 'http://127.0.0.1:8000/v1';
const host = new URL(base).hostname;
assert(['127.0.0.1', 'localhost', '[::1]'].includes(host), 'Evaluation is loopback-only');
const tools = new Map(), handlers = new Map();
let active = ['load_tools'];
const api = { registerTool(t) { tools.set(t.name, t); }, on(name, fn) { handlers.set(name, fn); }, registerCommand() {},
  getActiveTools() { return active; }, setActiveTools(names) { active = names; }, getAllTools() { return [...tools.values()]; } };
for (const name of ['45-jarvis', '48-jarvis-security', '99-lazy-tools', '98-slim-provider-payload']) {
  const register = await jiti.import(resolve(import.meta.dirname, `../extensions/${name}.ts`), { default: true });
  register(api);
}
const loader = tools.get('load_tools');
const slim = payload => handlers.get('before_provider_request')({ payload });
const schema = t => ({ type: 'function', function: { name: t.name, description: t.description, parameters: t.parameters } });
const coding = [{ type: 'function', function: { name: 'bash', description: 'Execute a local shell command for coding tasks.', parameters: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] } } }];
const baseline = slim({ tools: [...coding, schema(loader)] }).tools;
const focused = slim({ tools: [...coding, schema(loader), ...[...tools.values()].filter(t => t.name.startsWith('operation_jarvis_')).map(schema)] }).tools;
const system = 'You are an assistant operating inside Pi, a coding agent harness. Use available tools for requests.\n' + loader.promptGuidelines.join('\n');
// Only execute the schema loader. Household tool execute functions are never called.
const loaded = await loader.execute('load-eval', { groups: ['operation_jarvis'] });
const loadedText = loaded.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
const protocol = process.env.OPERATION_JARVIS_EVAL_PROTOCOL || 'Front door security protocol';
const cases = [
  ['Turn on the lamp.', 'operation_jarvis_plugs', 'on', { plug: 'lamp' }],
  ['Stop the music on the speakers.', 'operation_jarvis_media', 'stop', { device: 'speakers' }],
  ['Set the air purifier to auto mode.', 'operation_jarvis_purifier', 'set', { setting: 'mode', value: 'auto' }],
  ['Which security devices are configured?', 'operation_jarvis_security', 'devices', {}],
  [`What does ${protocol} do?`, 'operation_jarvis_automations', 'describe', { name: protocol }],
  [`Enable ${protocol}.`, 'operation_jarvis_automations', 'enable', { name: protocol }],
  ['List my Tapo automations.', 'operation_jarvis_automations', 'list', {}],
];
let passed = 0, total = 0;
console.log(JSON.stringify({ model, systemChars: system.length, baselineSchemaChars: JSON.stringify(baseline).length, loadedSchemaChars: JSON.stringify(focused).length }));
async function request(messages, definitions) {
  const response = await fetch(`${base}/chat/completions`, { method: 'POST', signal: AbortSignal.timeout(120000), headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
    model, temperature: 0, max_tokens: 512, chat_template_kwargs: { enable_thinking: false },
    messages: [{ role: 'system', content: system }, ...messages], tools: definitions, tool_choice: 'auto',
  }) });
  if (!response.ok) throw Error(`Local inference HTTP ${response.status}`);
  const body = await response.json(); const calls = body.choices?.[0]?.message?.tool_calls ?? [];
  if (!calls.length) console.log(JSON.stringify({ diagnostic: body.choices?.[0]?.message?.content?.slice(0, 1000), finishReason: body.choices?.[0]?.finish_reason }));
  return calls.map(c => { let args; try { args = JSON.parse(c.function.arguments); } catch { args = {}; } return { name: c.function.name, args }; });
}
for (const [prompt, tool, action, parameters] of cases) {
  for (const stage of ['discover', 'loaded']) {
    const messages = [{ role: 'user', content: prompt }];
    if (stage === 'loaded') messages.push(
      { role: 'assistant', content: null, tool_calls: [{ id: 'load-eval', type: 'function', function: { name: 'load_tools', arguments: JSON.stringify({ groups: ['operation_jarvis'] }) } }] },
      { role: 'tool', tool_call_id: 'load-eval', content: loadedText });
    let calls = await request(messages, stage === 'discover' ? baseline : focused);
    // A discovery read before selecting a device/rule is correct. Return an inert
    // synthetic listing, then require the intended final action (never execute it).
    if (stage === 'loaded' && action !== 'list' && calls.length === 1 && calls[0].name === tool && calls[0].args.action === 'list' && ['operation_jarvis_plugs', 'operation_jarvis_automations'].includes(tool)) {
      console.log(JSON.stringify({ stage: 'safe-preflight', prompt, calls }));
      const listing = tool === 'operation_jarvis_plugs' ? { plugs: [{ alias: 'lamp' }] } : { rules: [{ name: protocol, kind: 'automation', enabled: false }] };
      messages.push({ role: 'assistant', content: null, tool_calls: [{ id: 'list-eval', type: 'function', function: { name: tool, arguments: JSON.stringify(calls[0].args) } }] },
        { role: 'tool', tool_call_id: 'list-eval', content: JSON.stringify(listing) });
      calls = await request(messages, focused);
    }
    const ok = calls.length === 1 && (stage === 'discover'
      ? calls[0].name === 'load_tools' && JSON.stringify(calls[0].args.groups) === JSON.stringify(['operation_jarvis'])
      : calls[0].name === tool && calls[0].args.action === action && Object.entries(parameters).every(([k, v]) => String(calls[0].args[k]).toLowerCase() === String(v).toLowerCase()));
    total++; if (ok) passed++;
    console.log(JSON.stringify({ stage, prompt, ok, calls }));
  }
}
for (const [prompt, group] of [
  ['What scheduled Pi jobs do I have?', 'cron'],
  ['Tell Minecraft jarvis to follow me.', 'minecraft_jarvis'],
]) {
  const calls = await request([{ role: 'user', content: prompt }], baseline);
  const ok = calls.length === 1 && calls[0].name === 'load_tools' && JSON.stringify(calls[0].args.groups) === JSON.stringify([group]);
  total++; if (ok) passed++;
  console.log(JSON.stringify({ stage: 'boundary', prompt, ok, calls }));
}
console.log(JSON.stringify({ passed, total, hardwareCalls: 0 }));
if (passed !== total) process.exitCode = 1;
