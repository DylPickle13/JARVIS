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

test('compacted request and startup prompts retain the owner-requested CLI route and safety gates', () => {
  const original = 'Guidelines:\n- Original guideline.\n\n';
  const request = compact({ instructions: original }).instructions;
  const startup = handlers.get('before_agent_start')({
    systemPrompt: original, systemPromptOptions: { selectedTools: [] },
  }).systemPrompt;
  for (const guidance of [request, startup]) {
    assert.match(guidance, /Owner-requested standalone CLI diagnosis\/commissioning is allowed/);
    assert.match(guidance, /confirmation, identity, locking, privacy and unknown-write safeguards intact/);
    assert.match(guidance, /Never claim actions without tool results or bypass gates/);
    assert(!/then its tools for actual device operations/.test(guidance));
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
  const deferred = [{ type: 'tool_search_output', tools }];
  assert.deepEqual(compact({ input: deferred }).input, deferred);
});

test('preserves constraints on deferred tool schemas', () => {
  const result = compact({ input: [{ type: 'tool_search_output', tools: [{ name: 'read', parameters: schema }] }] });
  assert.equal(result.input[0].tools[0].parameters.additionalProperties, false);
  assert.equal(result.input[0].tools[0].parameters.properties.options.additionalProperties, false);
});
