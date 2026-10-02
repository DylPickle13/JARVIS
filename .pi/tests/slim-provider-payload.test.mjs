import assert from 'node:assert/strict';
import test from 'node:test';
import slimProviderPayload from '../extensions/98-slim-provider-payload.ts';

const handlers = new Map();
slimProviderPayload({ on: (event, handler) => handlers.set(event, handler) });
const compact = payload => handlers.get('before_provider_request')({ payload });
const schema = {
  type: 'object', additionalProperties: false,
  properties: {
    path: { type: 'string', description: 'Path to read' },
    options: { type: 'object', additionalProperties: false, properties: {}, required: [] },
  },
  required: ['path'],
};

test('modern prompt slimming retains every unknown rule and safety gate without forcing the prefix', () => {
  const rules = [
    '- Be concise in your responses',
    '- Owner-requested standalone CLI diagnosis/commissioning is allowed with confirmation, identity, locking, privacy and unknown-write safeguards intact.',
    '- Never claim actions without tool results or bypass gates.',
    '- A future upstream rule must survive verbatim.',
  ].join('\n');
  const original = `<rules>\n${rules}\n</rules>`;
  const options = { sections: {}, selectedTools: [] };
  assert.equal(handlers.get('before_agent_start')({ systemPrompt: original, systemPromptOptions: options }), undefined);
  assert.equal(options.forceSystemPrompt, undefined);
  for (const guidance of [compact({ instructions: original }).instructions, options.sections.rules]) {
    assert.match(guidance, /- Be concise\./);
    for (const rule of rules.split('\n').slice(1)) assert(guidance.includes(rule));
  }
  assert.equal(compact({ instructions: 'Guidelines:\n- Unknown legacy rule.\n\n' }).instructions,
    'Guidelines:\n- Unknown legacy rule.\n\n');
});

test('generated tools and docs shrink deterministically; web snippets and unrelated sections survive', () => {
  const tools = '- edit: Make precise file edits with exact text replacement, including multiple disjoint edits in one call\n- web_search: Preserve this upstream workflow verbatim.';
  const docs = 'Pi documentation (read only when needed):\n- Main documentation: /pi/README.md\n- Additional docs: /pi/docs\n- Examples: /pi/examples\n- When reading docs, follow links.\n';
  const prompt = `<tools>\n${tools}\n</tools>\n<docs>\n${docs}\n</docs>\n<addendum>\nOwner policy\n</addendum>`;
  const options = { sections: { room_audio_voice: 'Voice policy' } };
  const event = { systemPrompt: prompt, systemPromptOptions: options };
  handlers.get('before_agent_start')(event);
  assert.equal(options.sections.tools, '- edit: Exact text replacements; batch disjoint edits.\n- web_search: Preserve this upstream workflow verbatim.');
  assert.match(options.sections.docs, /^Pi docs only when relevant:/);
  assert.equal(options.sections.room_audio_voice, 'Voice policy');
  assert.equal(options.sections.addendum, undefined);
  const once = structuredClone(options);
  handlers.get('before_agent_start')(event);
  assert.deepEqual(options, once);
  const payload = compact({ instructions: prompt });
  assert.deepEqual(compact(payload), payload);
  assert(payload.instructions.includes('<addendum>\nOwner policy\n</addendum>'));
});

test('startup respects custom, forced and extension-owned sections; absent modern options are safe', () => {
  const prompt = '<rules>\n- Be concise in your responses\n</rules>';
  for (const options of [undefined, {}, { sections: {}, customPrompt: 'Custom' },
    { sections: {}, forceSystemPrompt: 'Forced' }, { sections: { rules: 'Custom rules' } }]) {
    const original = structuredClone(options);
    assert.equal(handlers.get('before_agent_start')({ systemPrompt: prompt, systemPromptOptions: options }), undefined);
    assert.deepEqual(options, original);
  }
});

test('preserves strict validation constraints in Responses, Messages, and Chat tools', () => {
  const tools = [
    { type: 'function', name: 'read', strict: true, parameters: schema },
    { name: 'read', input_schema: schema },
    { type: 'function', function: { name: 'read', strict: false, parameters: schema } },
  ];
  const original = structuredClone(tools);
  const result = compact({ tools }).tools;
  for (const parameters of [result[0].parameters, result[1].input_schema, result[2].function.parameters]) {
    assert.equal(parameters.additionalProperties, false);
    assert.equal(parameters.properties.options.additionalProperties, false);
    assert.deepEqual(parameters.required, ['path']);
    assert.equal(parameters.properties.path.description, undefined);
  }
  assert.equal(result[0].strict, true);
  assert.equal(result[2].function.strict, false);
  assert.deepEqual(tools, original);
});

test('keeps focused Operation JARVIS purpose and parameter meanings on all provider shapes', () => {
  const tool = { name: 'operation_jarvis_purifier', description: 'Operation JARVIS household purifier control', parameters: schema };
  const tools = [tool, { name: tool.name, description: tool.description, input_schema: schema }, { type: 'function', function: tool }];
  assert.deepEqual(compact({ tools }).tools, tools);
  for (const type of ['tool_search_output', 'additional_tools']) {
    const deferred = [{ type, tools }];
    assert.deepEqual(compact({ input: deferred }).input, deferred);
  }
});

for (const type of ['tool_search_output', 'additional_tools']) {
  test(`slims ${type} without mutation, constraint loss or metadata changes`, () => {
    const payload = { prompt_cache_key: 'stable-session', input: [
      { type: 'message', role: 'user', content: 'untouched' },
      { type, role: 'developer', call_id: 'stable-id', tools: [{ name: 'read', parameters: schema }] },
    ] };
    const original = structuredClone(payload);
    const result = compact(payload);
    const parameters = result.input[1].tools[0].parameters;
    assert.equal(parameters.additionalProperties, false);
    assert.equal(parameters.properties.options.additionalProperties, false);
    assert.equal(parameters.properties.path.description, undefined);
    assert.equal(result.input[1].call_id, 'stable-id');
    assert.equal(result.input[1].role, 'developer');
    assert.equal(result.prompt_cache_key, 'stable-session');
    assert.deepEqual(result.input[0], payload.input[0]);
    assert.deepEqual(payload, original);
    assert.deepEqual(compact(result), result);
  });
}

test('annotation stripping cannot delete parameter names or change literal validation values', () => {
  const literal = { description: 'literal', title: 'literal', examples: ['literal'] };
  const parameters = { type: 'object', additionalProperties: false,
    properties: Object.fromEntries(['description', 'title', 'examples', '$comment'].map(name =>
      [name, { type: 'object', description: 'annotation', const: literal, default: literal, enum: [literal] }])),
    required: ['description', 'title'],
    $defs: { description: { type: 'string', description: 'annotation', minLength: 1 } },
    anyOf: [{ properties: { title: { description: 'annotation', type: 'string' } } }],
  };
  const result = compact({ tools: [{ name: 'read', parameters }] }).tools[0].parameters;
  assert.deepEqual(Object.keys(result.properties), Object.keys(parameters.properties));
  for (const schema of Object.values(result.properties)) {
    assert.equal(schema.description, undefined);
    assert.deepEqual(schema.const, literal);
    assert.deepEqual(schema.default, literal);
    assert.deepEqual(schema.enum, [literal]);
  }
  assert.deepEqual(result.$defs.description, { type: 'string', minLength: 1 });
  assert.deepEqual(result.anyOf, [{ properties: { title: { type: 'string' } } }]);
  assert.deepEqual(result.required, parameters.required);
});

test('web-access schemas and unknown addition formats stay stock', () => {
  const tools = ['web_search', 'source_check', 'fetch_content', 'get_search_content'].map(name =>
    ({ name, description: 'Stock description', parameters: schema }));
  for (const type of ['additional_tools', 'tool_search_output']) {
    const payload = { tools, input: [{ type, tools }] };
    assert.deepEqual(compact(payload).tools, tools);
    assert.deepEqual(compact(payload).input, payload.input);
  }
  const input = [null, { type: 'future_format', tools: [{ name: 'read', parameters: schema }] },
    { type: 'additional_tools', tools: null }];
  assert.deepEqual(compact({ input }).input, input);
});
