#!/usr/bin/env node
// Opt-in live checks. No server settings, model load/unload APIs, real tools or
// private session prompts are used. --generate exercises already-loaded models;
// --allow-on-demand additionally permits ordinary inference to load a model.
import { piRuntimeRoot, piRequire, piDependencyRoot } from './pi-runtime.mjs';
import { mkdtempSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { deflateSync } from 'node:zlib';
import assert from 'node:assert/strict';
const root = piRuntimeRoot();
const ai = piDependencyRoot('@earendil-works/pi-ai', root);
const { createJiti } = piRequire(root)('jiti');
const jiti = createJiti(import.meta.url, { interopDefault: true, alias: {
  '@earendil-works/pi-coding-agent': join(root, 'dist/index.js'),
  '@earendil-works/pi-ai/compat': join(ai, 'dist/compat.js'),
  '@earendil-works/pi-ai': join(ai, 'dist/index.js'),
} });
const { registerOmlx } = await jiti.import(resolve('.pi/extensions/01-omlx.ts'));
const { normalizeContext } = await jiti.import(join(ai, 'dist/compat.js'));
const configs = new Map();
const dir = mkdtempSync(join(tmpdir(), 'omlx-live-'));
const instance = registerOmlx({ on() {}, registerCommand() {}, registerProvider: (id, config) => configs.set(id, config) },
  { cachePath: join(dir, 'catalog.json') });
let failures = 0;
function redPng() {
  const crc = bytes => { let n = 0xffffffff; for (const b of bytes) { n ^= b; for (let j = 0; j < 8; j++) n = (n >>> 1) ^ ((n & 1) ? 0xedb88320 : 0); } return (n ^ 0xffffffff) >>> 0; };
  const chunk = (name, data) => { const type = Buffer.from(name), length = Buffer.alloc(4), checksum = Buffer.alloc(4); length.writeUInt32BE(data.length); checksum.writeUInt32BE(crc(Buffer.concat([type, data]))); return Buffer.concat([length, type, data, checksum]); };
  const header = Buffer.alloc(13); header.writeUInt32BE(32, 0); header.writeUInt32BE(32, 4); header[8] = 8; header[9] = 2;
  const pixels = Buffer.alloc(32 * (1 + 32 * 3)); for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) pixels[y * 97 + 1 + x * 3] = 255;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]).toString('base64');
}
async function request(state, model, context, reasoning) {
  const config = configs.get(state.seed.provider);
  const stream = config.streamSimple({ ...model, api: 'openai-completions', provider: state.seed.provider, baseUrl: state.baseUrl }, normalizeContext(context),
    { apiKey: state.apiKey, maxTokens: 2048, reasoning, signal: AbortSignal.timeout(120000) });
  let terminal;
  for await (const event of stream) if (event.type === 'done' || event.type === 'error') terminal = event;
  if (terminal?.type !== 'done') throw new Error('Generation failed or was cancelled (raw provider error omitted)');
  return terminal.message;
}
const visible = message => message.content.filter(p => p.type === 'text').map(p => p.text).join('').trim();
try {
  await instance.refreshAll();
  for (const state of instance.states) {
    console.log(`${state.seed.provider}: ${state.source}; ${state.records.length} chat models; ${state.lastError ? 'unreachable/discovery failed' : 'discovery OK'}`);
    if (state.source !== 'live' || state.lastError) { console.log('  SKIP generation: host unavailable'); continue; }
    console.log(`  Metadata: ${state.warnings.length} warnings; ${state.records.filter(r => r.loaded).length} loaded; limits from ${[...new Set(state.records.map(r => r.limitSource))].join(', ')}`);
    if (!process.argv.includes('--generate')) continue;
    const record = state.records.find(r => r.loaded === true) ?? (process.argv.includes('--allow-on-demand') ? state.records.find(r => r.id === state.seed.models.at(-1)?.id) ?? state.records[0] : undefined);
    if (!record) { console.log('  SKIP generation: no already-loaded chat model'); continue; }
    const model = configs.get(state.seed.provider).models.find(m => m.id === record.id);
    try {
      const context = { systemPrompt: 'Follow the user request concisely.', messages: [{ role: 'user', content: 'What is 3 + 4? Answer with the number only.', timestamp: Date.now() }], tools: [] };
      const off = await request(state, model, context); assert.ok(visible(off)); console.log(`  PASS text/thinking-off (${off.usage.output} output tokens)`);
      if (model.reasoning) { const on = await request(state, model, context, 'high'); assert.ok(visible(on)); console.log(`  PASS thinking-on (${on.usage.output} output tokens)`); }
      const tools = [{ name: 'echo', description: 'Echo a supplied integer.', parameters: { type: 'object', properties: { value: { type: 'integer' } }, required: ['value'], additionalProperties: false } }];
      const toolContext = { systemPrompt: 'Call tools when requested.', messages: [{ role: 'user', content: 'Call echo with value 7, then report the returned number.', timestamp: Date.now() }], tools };
      const call = await request(state, model, toolContext);
      const tool = call.content.find(p => p.type === 'toolCall'); assert.equal(tool?.name, 'echo'); assert.equal(tool.arguments.value, 7);
      toolContext.messages.push(call, { role: 'toolResult', toolCallId: tool.id, toolName: 'echo', content: [{ type: 'text', text: '7' }], isError: false, timestamp: Date.now() });
      assert.ok(visible(await request(state, model, toolContext))); console.log('  PASS tool arguments and multi-turn tool result (synthetic echo only)');
      if (record.vision) {
        const image = await request(state, model, { systemPrompt: 'Describe images concisely.', tools: [], messages: [{ role: 'user', content: [{ type: 'text', text: 'What is the dominant color in this image? Answer with one word.' }, { type: 'image', mimeType: 'image/png', data: redPng() }], timestamp: Date.now() }] });
        assert.match(visible(image), /\bred\b/i); console.log('  PASS synthetic image input and red-color recognition');
      }
    } catch (error) { failures++; console.log(`  FAIL ${error instanceof assert.AssertionError ? 'response assertion' : 'generation/stream check'} (no raw response logged)`); }
  }
} finally { rmSync(dir, { recursive: true, force: true }); }
process.exitCode = failures ? 1 : 0;
