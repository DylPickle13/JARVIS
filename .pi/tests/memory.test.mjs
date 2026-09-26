import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { jiti } from './helpers/pi-import.mjs';
const { default: register } = await jiti.import(resolve('.pi/extensions/35-memory.ts'));

function fixture(result = { ok: true, message: 'ok' }) {
  let tool;
  const calls = [];
  register({
    registerTool: t => { tool = t; },
    registerCommand: () => {},
    exec: async (command, args) => {
      calls.push({ command, args });
      return { code: 0, stdout: JSON.stringify(result), stderr: '' };
    },
  });
  return { tool, calls, run: params => tool.execute('test', params, undefined, undefined, { cwd: process.cwd() }) };
}

test('source update, verification, and project/topic reach the runner', async () => {
  const f = fixture();
  await f.run({ action: 'update', id: 'abc', source: 'docs/current.md', verified_at: '2026-09-19', project: 'app', topic: 'deployment', tags: [] });
  const args = f.calls[0].args;
  for (const [flag, value] of Object.entries({ '--source': 'docs/current.md', '--verified-at': '2026-09-19', '--project': 'app', '--topic': 'deployment', '--tags': '[]' })) {
    assert.equal(args[args.indexOf(flag) + 1], value);
  }
});

test('replacement IDs and historical/tag filters are forwarded', async () => {
  const f = fixture();
  await f.run({ action: 'remember', text: 'Current fact', supersedes: ['abc', 'def'] });
  assert.deepEqual(f.calls[0].args.slice(-4), ['--supersedes', 'abc', '--supersedes', 'def']);
  await f.run({ action: 'search', query: 'fact', tags: ['stable', 'host'], include_superseded: true });
  const args = f.calls[1].args;
  assert.ok(args.includes('--include-superseded'));
  assert.equal(args[args.indexOf('--tags') + 1], '["stable","host"]');
  await assert.rejects(f.run({ action: 'update', id: 'abc', supersedes: ['def'] }), /only supported by remember/);
});

test('assistant-visible results carry provenance, status, and historical warning', async () => {
  const f = fixture({ ok: true, query: 'fact', results: [{
    id: 'abc', kind: 'fact', scope: 'project', status: 'superseded', text: 'Old fact', tags: [],
    source: 'docs/state.md', updated_at: '2026-09-19T00:00:00Z', verified_at: null,
    confidence: 0.9, project: 'app', topic: 'state', superseded_by: 'def',
  }] });
  const result = await f.run({ action: 'search', query: 'fact' });
  const text = result.content[0].text;
  for (const expected of ['not live state or authorization', 'status=superseded', 'project=app', 'topic=state', 'updated=2026-09-19', 'verified=unverified', 'confidence=0.9', 'source="docs/state.md"', 'superseded_by=def']) assert.ok(text.includes(expected), expected);
});

test('numeric tool schemas enforce confidence and integral bounded limits', () => {
  const { tool } = fixture();
  assert.equal(tool.parameters.properties.confidence.minimum, 0);
  assert.equal(tool.parameters.properties.confidence.maximum, 1);
  assert.equal(tool.parameters.properties.limit.type, 'integer');
  assert.equal(tool.parameters.properties.limit.minimum, 1);
  assert.equal(tool.parameters.properties.limit.maximum, 100);
});
