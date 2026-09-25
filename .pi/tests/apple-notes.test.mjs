import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { jiti } from './helpers/pi-import.mjs';
const { default: register } = await jiti.import(resolve(import.meta.dirname, '../extensions/61-apple-notes.ts'));

const ok = stdout => ({ code: 0, killed: false, stdout, stderr: '' });
const ready = ok('ready\n');
const note = { id: 'test-note-id', title: 'Shopping List', folder: 'Notes', account: 'iCloud' };
function fixture(responses) {
  const tools = {}, calls = [];
  register({
    registerTool(tool) { tools[tool.name] = tool; },
    async exec(command, args, options) {
      calls.push({ command, args, options });
      assert.ok(responses.length, 'unexpected execution/retry');
      return responses.shift();
    },
  });
  return { tools, calls, invoke: (name, params = {}, signal) => tools[`apple_notes_${name}`].execute('test', params, signal) };
}

test('readiness timeout is not success and never attempts a write', async () => {
  const f = fixture([{ ...ok(''), killed: true }]);
  await assert.rejects(f.invoke('write', { title: note.title }), /FAILED:.*readiness.*timed out.*NOT attempted.*Do not claim success.*tmux/s);
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].options.timeout, 10_000);
});

test('permission denial and unexpected readiness output stop execution', async () => {
  for (const response of [{ ...ok(''), code: 1, stderr: 'Not authorized (-1743)' }, ok(''), ok('unexpected')]) {
    const f = fixture([response]);
    await assert.rejects(f.invoke('write', { title: note.title }), /FAILED:.*NOT attempted.*Automation/s);
    assert.equal(f.calls.length, 1);
  }
});

test('mutation timeout with code zero is explicitly unconfirmed and not retried', async () => {
  for (const response of [{ ...ok(''), killed: true }, { ...ok(JSON.stringify(note)), killed: true }]) {
    const f = fixture([ready, response]);
    await assert.rejects(f.invoke('write', { title: note.title }), /FAILED:.*timed out.*UNCONFIRMED.*Do not claim success or repeat/s);
    assert.equal(f.calls.length, 2);
  }
});

test('empty, invalid, incomplete and failed mutation output never succeeds', async () => {
  for (const response of [ok(''), ok('bad json'), ok('{}'), ok('null'), ok('{"id":"x"}'), { ...ok(''), code: 1, stderr: 'failure' }]) {
    const f = fixture([ready, response]);
    await assert.rejects(f.invoke('write', { title: note.title }), /FAILED:.*UNCONFIRMED/s);
  }
});

test('search timeout is not an empty list', async () => {
  const f = fixture([ready, { ...ok(''), killed: true }]);
  await assert.rejects(f.invoke('search'), /Do not interpret this as an empty note list/);
});

test('successful write includes an explicit success status and real note id', async () => {
  const f = fixture([ready, ok(JSON.stringify(note))]);
  const body = "- Small mason jar for cream\n- Daddy's sugar";
  const result = await f.invoke('write', { title: note.title, body });
  assert.equal(result.details.status, 'succeeded');
  assert.equal(result.details.action, 'write');
  assert.equal(result.details.id, note.id);
  assert.match(result.content[0].text, /"status": "succeeded"/);
  assert.equal(f.calls[1].command, '/usr/bin/osascript');
  assert.deepEqual(f.calls[1].args.slice(3, 8), ['write', 'Notes', '', note.title, body]);
});

test('valid search/read/update/delete result shapes pass; malformed shapes fail', async () => {
  for (const [action, params, data] of [
    ['search', {}, { notes: [], count: 0 }],
    ['search', {}, { notes: [note], count: 1 }],
    ['read', { id: note.id }, { ...note, body: 'text' }],
    ['update', { id: note.id, body: 'text', mode: 'append' }, { ...note, body: 'text' }],
  ]) {
    const f = fixture([ready, ok(JSON.stringify(data))]);
    assert.equal((await f.invoke(action, params)).details.status, 'succeeded');
  }
  for (const data of [{ notes: [], count: 1 }, { notes: [{}], count: 1 }, { notes: [] }]) {
    const f = fixture([ready, ok(JSON.stringify(data))]);
    await assert.rejects(f.invoke('search'), /unexpected result shape/);
  }
  const f = fixture([ready, ok(JSON.stringify({ ...note, body: 'text' })), ready, ok(JSON.stringify({ ...note, deleted: true }))]);
  const result = await f.tools.apple_notes_delete.execute('test', { id: note.id, confirm: true }, undefined, undefined, { hasUI: false });
  assert.equal(result.details.status, 'succeeded');
  assert.equal(result.details.deleted, true);
});

test('pre-aborted calls do not reach Notes', async () => {
  const controller = new AbortController();
  controller.abort();
  const f = fixture([]);
  await assert.rejects(f.invoke('write', { title: note.title }, controller.signal), /cancelled before execution/);
  assert.equal(f.calls.length, 0);
});

test('cancellation during readiness stops before mutation', async () => {
  const controller = new AbortController();
  let calls = 0;
  const tools = {};
  register({
    registerTool(tool) { tools[tool.name] = tool; },
    async exec() { calls++; controller.abort(); return ready; },
  });
  await assert.rejects(tools.apple_notes_write.execute('test', { title: note.title }, controller.signal), /readiness check was cancelled.*NOT attempted/s);
  assert.equal(calls, 1);
});
