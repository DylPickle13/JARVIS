import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { jiti } from './helpers/pi-import.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const { default: register, createNotifyTool, notificationEventID, parseNotifyResult, dispatchNotification, createNotificationDispatcher } =
  await jiti.import(join(root, '.pi/extensions/44-notify.ts'));
const ctx = { sessionManager: { getSessionId: () => 'fixture-session' } };
const accepted = { ok: true, outcome: 'accepted', sessionID: 2,
  devices: [{ platform: 'iphone', outcome: 'accepted' }, { platform: 'watch', outcome: 'accepted' }] };

function mobilePane(t) {
  const old = process.env.TMUX_PANE;
  process.env.TMUX_PANE = '%12';
  t.after(() => { if (old === undefined) delete process.env.TMUX_PANE; else process.env.TMUX_PANE = old; });
}

test('notify is model-callable with only title/message and no automatic event hooks', () => {
  let tool;
  register({ registerTool: definition => { tool = definition; }, on: () => assert.fail('No lifecycle push hooks') });
  assert.equal(tool.name, 'notify');
  assert.deepEqual(Object.keys(tool.parameters.properties), ['title', 'message']);
  assert.equal(tool.parameters.additionalProperties, false);
  assert.equal(tool.parameters.properties.title.maxLength, 24);
  assert.equal(tool.parameters.properties.message.maxLength, 60);
  assert.match(tool.parameters.properties.title.description, /at most 24 characters/);
  assert.match(tool.parameters.properties.message.description, /One complete sentence, at most 60 characters/);
  assert.match(tool.parameters.properties.message.description, /Put the result first; details stay in this session/);
  const [usage, privacy, outcomes] = tool.promptGuidelines;
  assert.equal(tool.promptGuidelines.length, 3);
  assert.match(usage, /meaningful completions/);
  assert.match(usage, /blockers needing sir's input/);
  assert.match(usage, /important updates—not every turn/);
  assert.match(usage, /Honour explicit completion-alert requests after verification/);
  assert.match(privacy, /Lock Screen: short, non-sensitive text/);
  for (const excluded of ['credentials', 'private paths', 'raw prompts', 'conversation excerpts']) {
    assert(privacy.includes(excluded), excluded);
  }
  assert.match(privacy, /Sanitization\/truncation may use a generic preview/);
  assert.match(outcomes, /accepted=Apple acceptance, not confirmed delivery\/read/);
  assert.match(outcomes, /disabled\/unavailable=no confirmed send/);
  assert.match(outcomes, /partial\/ambiguous=stop, never auto-resend/);
  assert.match(outcomes, /No watchers, reminders or scheduling/);
  assert(tool.promptGuidelines.join(' ').length <= 500, 'Keep system guidance compact without dropping rules');
  assert.match(tool.description, /approved mobile Pi session; tap opens this session/);
  assert.match(tool.description, /never retry partial\/ambiguous sends/);
});

test('explicit tool dispatch carries text via request and returns Apple acceptance honestly', async t => {
  mobilePane(t);
  const calls = [];
  const tool = createNotifyTool(async (request, signal) => { calls.push({ request, signal }); return accepted; });
  const signal = new AbortController().signal;
  const result = await tool.execute('call-1', { title: 'Build ready', message: 'All checks passed, sir.' }, signal, undefined, ctx);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].request.title, 'Build ready');
  assert.equal(calls[0].request.message, 'All checks passed, sir.');
  assert.equal(calls[0].request.pid, process.pid);
  assert.equal(calls[0].request.pane, '%12');
  assert.equal(calls[0].signal, signal);
  assert.equal(result.isError, false);
  assert.deepEqual(result.details, accepted);
  assert.match(result.content[0].text, /Screen delivery.*unverified/);
});

test('watch-friendly limits accept exact character boundaries without cropping, including emoji', async t => {
  mobilePane(t);
  const calls = [];
  const tool = createNotifyTool(async request => { calls.push(request); return accepted; });
  for (const character of ['x', '🔔']) {
    const params = { title: character.repeat(24), message: character.repeat(60) };
    const result = await tool.execute(`boundary-${character}`, params, undefined, undefined, ctx);
    assert.equal(result.isError, false);
    assert.equal(calls.at(-1).title, params.title);
    assert.equal(calls.at(-1).message, params.message);
  }
  assert.equal(calls.length, 2);
});

test('one logical invocation has one receipt identity; new calls/sessions/processes differ', () => {
  const id = notificationEventID('session', 'call', 123);
  assert.match(id, /^[a-f0-9]{8}-[a-f0-9]{4}-5[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  assert.equal(notificationEventID('session', 'call', 123), id);
  for (const args of [['other', 'call', 123], ['session', 'other', 123], ['session', 'call', 124]]) {
    assert.notEqual(notificationEventID(...args), id);
  }
});

test('every non-acceptance outcome is an error and never an automatic resend', async t => {
  mobilePane(t);
  for (const outcome of ['partial', 'disabled', 'unavailable', 'failed', 'ambiguous', 'invalid', 'retired']) {
    let calls = 0;
    const tool = createNotifyTool(async () => { calls++; return { ok: false, outcome, devices: [] }; });
    const result = await tool.execute('call', { title: 'Ready', message: 'Done' }, undefined, undefined, ctx);
    assert.equal(result.isError, true);
    assert.equal(result.details.outcome, outcome);
    assert.equal(calls, 1);
  }
  const tool = createNotifyTool(async () => { throw new Error('private raw transport diagnostic'); });
  const result = await tool.execute('call', { title: 'Ready', message: 'Done' }, undefined, undefined, ctx);
  assert.equal(result.details.outcome, 'ambiguous');
  assert(!result.content[0].text.includes('private raw'));
});

test('missing pane, pre-cancelled calls, and invalid text never dispatch', async t => {
  mobilePane(t);
  const tool = createNotifyTool(async () => assert.fail('Must not dispatch'));
  const abort = new AbortController(); abort.abort();
  let result = await tool.execute('call', { title: 'Ready', message: 'Done' }, abort.signal, undefined, ctx);
  assert.equal(result.details.outcome, 'unavailable');
  result = await dispatchNotification({}, abort.signal);
  assert.equal(result.outcome, 'unavailable');
  delete process.env.TMUX_PANE;
  result = await tool.execute('call', { title: 'Ready', message: 'Done' }, undefined, undefined, ctx);
  assert.equal(result.details.outcome, 'unavailable');
  process.env.TMUX_PANE = '%12';
  for (const params of [{ title: ' ', message: 'Done' }, { title: 'Ready', message: '' },
    ...['x', '🔔'].flatMap(character => [
      { title: character.repeat(25), message: 'Done' },
      { title: 'Ready', message: character.repeat(61) },
    ])]) {
    result = await tool.execute('call', params, undefined, undefined, ctx);
    assert.equal(result.details.outcome, 'invalid');
  }
});

test('receipt parser strips unknown private fields and rejects malformed or false acceptance', () => {
  assert.deepEqual(parseNotifyResult(JSON.stringify({ ...accepted, deviceToken: 'never-forward',
    devices: accepted.devices.map(device => ({ ...device, token: 'never-forward' })) })), accepted);
  for (const value of [null, {}, { ...accepted, ok: false }, { ...accepted, sessionID: true },
    { ...accepted, devices: [] }, { ...accepted, devices: [{ platform: 'iphone', outcome: 'failed' }] },
    { ...accepted, devices: [accepted.devices[0], accepted.devices[0]] },
    { ...accepted, devices: [{ platform: 'other', outcome: 'accepted' }] }]) {
    assert.throws(() => parseNotifyResult(JSON.stringify(value)));
  }
  assert.throws(() => parseNotifyResult('private raw diagnostic'));
});

function fakeProcess(started = true) {
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  child.kills = [];
  child.kill = signal => { child.kills.push(signal); return true; };
  if (started) queueMicrotask(() => child.emit('spawn'));
  return child;
}

test('dispatcher waits for a validated receipt and uses literal stdin only', async () => {
  const child = fakeProcess(), invocations = [];
  const dispatch = createNotificationDispatcher((...args) => { invocations.push(args); return child; });
  const request = { title: 'Literal "$(not shell)"', message: 'Ready' };
  const resultPromise = dispatch(request);
  assert.equal(invocations.length, 1);
  assert.equal(invocations[0][0], '/opt/homebrew/bin/python3');
  assert.equal(invocations[0][1].at(-1), '--notify');
  assert(!JSON.stringify(invocations[0]).includes(request.title));
  assert.equal(JSON.parse(child.stdin.read().toString()).title, request.title);
  child.stdout.write(JSON.stringify(accepted));
  child.emit('close', 0);
  assert.deepEqual(await resultPromise, accepted);
});

test('dispatcher returns unknown without retry on abort, malformed output, overflow or timeout', async () => {
  for (const mode of ['abort', 'malformed', 'overflow', 'exit', 'timeout']) {
    const child = fakeProcess(), abort = new AbortController();
    let calls = 0;
    const dispatch = createNotificationDispatcher(() => { calls++; return child; }, mode === 'timeout' ? 5 : 1000);
    const resultPromise = dispatch({}, abort.signal);
    await Promise.resolve(); // successful spawn before an unknown transmission
    // Keep the event loop alive while the dispatcher's production timer is unref'd.
    const keepAlive = setTimeout(() => {}, 100);
    if (mode === 'abort') abort.abort();
    if (mode === 'malformed') { child.stdout.write('private diagnostic'); child.emit('close', 0); }
    if (mode === 'overflow') child.stdout.write('x'.repeat(8193));
    if (mode === 'exit') child.emit('close', 1);
    const result = await resultPromise;
    clearTimeout(keepAlive);
    assert.equal(result.outcome, 'ambiguous', mode);
    assert.equal(calls, 1, 'never spawn a retry after unknown transmission');
    assert(!JSON.stringify(result).includes('private'));
  }
  const child = fakeProcess(false);
  const promise = createNotificationDispatcher(() => child)({});
  child.emit('error', new Error('private spawn diagnostic'));
  assert.equal((await promise).outcome, 'unavailable');
});

test('helper invocation uses fixed executable/argv and stdin, not shell or detached fire-and-forget', () => {
  const source = readFileSync(join(root, '.pi/extensions/44-notify.ts'), 'utf8');
  assert.match(source, /child\.stdin\.end\(JSON\.stringify\(request\)\)/);
  assert.match(source, /"--notify"/);
  assert.doesNotMatch(source, /shell:|detached:|ctx\.ui\.notify/);
});
