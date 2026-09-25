import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { jiti } from './helpers/pi-import.mjs';
const { transcript, validateTitle, mayRename, registerAutoname, generateTitle, resilientTitle, fallbackTitle, NamingError, isWeakTitle } = await jiti.import(resolve('.pi/extensions/49-session-autoname.ts'));
const user = (id, text) => ({ id, type: 'message', message: { role: 'user', content: text } });
const assistant = (id, text, stopReason = 'stop', extra = []) => ({ id, type: 'message', message: { role: 'assistant', stopReason, content: [{ type: 'text', text }, ...extra] } });
const tick = () => new Promise(r => setImmediate(r));
function fixture(generate) {
  let entries = [user('u1', 'Implement session names'), assistant('a1', 'Added automatic naming')];
  let session = 's1';
  const hooks = {};
  const writes = [];
  const commands = {};
  const pi = {
    on: (event, fn) => { hooks[event] = fn; },
    registerCommand: (name, command) => { commands[name] = command; },
    getSessionName: () => entries.findLast(e => e.type === 'session_info')?.name,
    setSessionName: name => { writes.push(name); entries.push({ id: `i${entries.length}`, type: 'session_info', name }); },
    appendEntry: (customType, data) => entries.push({ id: `c${entries.length}`, type: 'custom', customType, data }),
  };
  const ctx = { sessionManager: {
    getEntries: () => entries,
    getBranch: () => entries,
    getSessionId: () => session,
    getLeafId: () => entries.at(-1)?.id,
  } };
  const reload = () => registerAutoname(pi, generate);
  reload();
  return { pi, writes, ctx, commands, reload, entries: () => entries, emit: event => hooks[event]?.({}, ctx),
    next: () => entries.push(user('u2', 'Add tests'), assistant('a2', 'Tests added')),
    switch: () => { entries = [user('u9', 'Other task'), assistant('a9', 'Done')]; session = 's2'; } };
}

test('selects user and final text only; excludes tools, thinking, images, aborted turns', () => {
  const result = transcript([user('u', 'Task'), assistant('tool', 'Chatter', 'toolUse', [{ type: 'toolCall' }]),
    { id: 't', type: 'message', message: { role: 'toolResult', content: 'SECRET TOOL OUTPUT' } },
    assistant('final', 'Answer', 'stop', [{ type: 'thinking', thinking: 'PRIVATE' }, { type: 'image', data: 'IMAGE' }])]);
  assert.deepEqual(result, { id: 'final', text: 'User: Task\nAssistant: Answer' });
  assert.equal(transcript([user('u', 'Task'), assistant('a', 'Partial', 'aborted')]), undefined);
  assert.equal(transcript([user('u', 'Task')]), undefined);
});

test('bounds input, preserves original task and most recent answer', () => {
  const entries = [user('u0', 'ORIGINAL'), assistant('a0', 'First')];
  for (let i = 1; i < 100; i++) entries.push(user(`u${i}`, 'x'.repeat(9000)), assistant(`a${i}`, `RECENT${i} ` + 'y'.repeat(9000)));
  const result = transcript(entries);
  assert.ok(result.text.length <= 6000);
  assert.match(result.text, /ORIGINAL/);
  assert.match(result.text, /RECENT99/);
});

test('extension reads conversation only from active branch, not global metadata history', async () => {
  let input;
  const f = fixture(async text => { input = text; return 'Active Branch Title'; });
  const branch = [...f.entries()];
  f.entries().push(user('abandoned-u', 'ABANDONED SECRET'), assistant('abandoned-a', 'ABANDONED ANSWER'));
  f.ctx.sessionManager.getBranch = () => branch;
  f.emit('agent_settled'); await tick();
  assert.match(input, /Implement session names/);
  assert.doesNotMatch(input, /ABANDONED/);
  assert.deepEqual(f.writes, ['Active Branch Title']);
});

test('validates titles and rejects terminal controls or multiline output', () => {
  assert.equal(validateTitle('“Pi Session Naming”'), 'Pi Session Naming');
  for (const bad of ['One', 'Title\nExplanation', '\x1b[31mRed Title', '# Markdown Title', 'x'.repeat(73), '/Users/private folder', undefined]) assert.equal(validateTitle(bad), undefined);
});

test('automatic naming is nonblocking, deduplicated, and ownership survives reload', async () => {
  let finish;
  let calls = 0;
  const f = fixture(() => { calls++; return new Promise(r => { finish = r; }); });
  assert.equal(f.emit('agent_settled'), undefined);
  f.emit('agent_settled');
  assert.equal(calls, 1);
  finish('Pi Session Naming'); await tick();
  assert.deepEqual(f.writes, ['Pi Session Naming']);
  assert.equal(mayRename(f.entries(), 'Pi Session Naming', 's1'), true);
  assert.equal(mayRename(f.entries(), 'Pi Session Naming', 'different-session'), false);
  f.reload(); f.next(); f.emit('agent_settled'); finish('Pi Session Naming Tests'); await tick();
  assert.equal(f.writes.length, 2);
});

test('manual names, including same-text renames, remain protected after reload', async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return 'Pi Session Naming'; });
  f.emit('agent_settled'); await tick();
  f.pi.setSessionName('Pi Session Naming');
  f.reload(); f.next(); f.emit('agent_settled'); await tick();
  assert.equal(calls, 1);
  const other = fixture(async () => { throw new Error('must not run'); });
  other.pi.setSessionName('My manual name'); other.emit('agent_settled'); await tick();
  assert.deepEqual(other.writes, ['My manual name']);
});

test('stale inference cannot rename after lifecycle changes or manual rename', async () => {
  for (const event of ['agent_start', 'session_start', 'session_shutdown', 'session_before_switch', 'session_before_fork', 'session_before_tree', 'session_tree', 'session_before_compact', 'manual', 'switch']) {
    let finish, signal;
    const f = fixture((_input, s) => { signal = s; return new Promise(r => { finish = r; }); });
    f.emit('agent_settled');
    if (event === 'manual') f.pi.setSessionName('User choice');
    else if (event === 'switch') f.switch();
    else { f.emit(event); assert.equal(signal.aborted, true); }
    finish('Stale Model Title'); await tick();
    assert.ok(!f.writes.includes('Stale Model Title'), event);
  }
});

test('failure supplies owned fallback; equivalent title leaves session untouched', async () => {
  const f = fixture(async () => { throw new NamingError('missing_binary'); });
  f.emit('agent_settled'); await tick(); assert.deepEqual(f.writes, ['Implement session names']);
  assert.equal(mayRename(f.entries(), f.writes[0], 's1'), true);
  let title = 'Pi Session Naming';
  const g = fixture(async () => title);
  g.emit('agent_settled'); await tick();
  title = 'PI Session-Naming'; g.next(); g.emit('agent_settled'); await tick();
  assert.equal(g.writes.length, 1);
});

test('diagnostics contain categories and counts, not exception content', async () => {
  const f = fixture(async () => { throw new NamingError('missing_binary'); });
  f.emit('agent_settled'); await tick();
  let notification;
  await f.commands['autoname-status'].handler('', { ui: { notify: text => { notification = text; } } });
  assert.deepEqual(JSON.parse(notification), { missing_binary: 1, fallback: 1, renamed: 1 });
});

test('normalizes only unambiguous single-line formatting', () => {
  for (const text of ['Title: Pi Session Naming', '**Pi Session Naming**', '`Pi Session Naming`', 'Title: "Pi Session Naming"'])
    assert.equal(validateTitle(text), 'Pi Session Naming');
  for (const text of ['Title: Good Title\nExplanation', '\u202eHidden Title', '"Mismatched Title', 'Title: /private/file'])
    assert.equal(validateTitle(text), undefined);
});

test('rejects generic naming metadata but keeps specific subjects', () => {
  for (const title of ['Session Picker Selection', 'Session picker conversation', 'Session picker for coding conversation', 'Session title remains unchanged', 'Session title not provided in data', 'No session title provided']) assert.equal(isWeakTitle(title), true, title);
  for (const title of ['Automatic Pi Session Naming', 'Session Picker Performance', 'DroidCam Project Overview', 'Sunday Dinner Deals in Pickering']) assert.equal(isWeakTitle(title), false, title);
  assert.equal(validateTitle('Session Picker: Discord Ping Tool'), 'Discord Ping Tool');
  assert.equal(validateTitle('Session Picker for Light Control'), 'Light Control');
  assert.equal(validateTitle('Session Title: Compare Mac Mini Docks'), 'Compare Mac Mini Docks');
  assert.equal(validateTitle('Automatic Pi Session Naming'), 'Automatic Pi Session Naming');
  assert.equal(fallbackTitle('User: can you manually run the drive backup cron job\nAssistant: Done'), 'Run the drive backup cron job');
});

test('generic titles trigger retries without anchoring on a weak old title', async () => {
  const reports = [], inputs = [];
  const result = await resilientTitle(JSON.stringify({currentTitle:'Session Picker Selection', conversation:'User: Repair the Drive backup schedule'}), new AbortController().signal,
    async input => { inputs.push(JSON.parse(input)); return inputs.length === 1 ? 'Session Picker Conversation' : 'Repair Drive Backup Schedule'; }, code => reports.push(code), 0);
  assert.equal(result, 'Repair Drive Backup Schedule');
  assert.deepEqual(reports, ['generic_title']);
  assert.ok(inputs.every(input => input.currentTitle === ''));
});

test('retries at most twice, shrinks input, and records categories only', async () => {
  const sizes = [], reports = [];
  const result = await resilientTitle(JSON.stringify({ currentTitle: '', conversation: 'x'.repeat(6000) }), new AbortController().signal,
    async input => { sizes.push(JSON.parse(input).conversation.length); if (sizes.length < 3) throw new NamingError('context_limit'); return 'Recovered Local Title'; },
    code => reports.push(code), 0);
  assert.equal(result, 'Recovered Local Title');
  assert.deepEqual(sizes, [6000, 2400, 1200]);
  assert.deepEqual(reports, ['context_limit', 'context_limit']);
});

test('exhausted retries preserve existing name or provide conservative fallback', async () => {
  for (const currentTitle of ['', 'Existing Useful Name']) {
    let calls = 0;
    const reports = [];
    const title = await resilientTitle(JSON.stringify({ currentTitle, conversation: 'User: Implement session names\nAssistant: Done' }), new AbortController().signal,
      async () => { calls++; return 'Invalid\nMultiline'; }, code => reports.push(code), 0);
    assert.equal(calls, 3);
    assert.equal(title, currentTitle || 'Implement session names');
    assert.equal(reports.at(-1), currentTitle ? 'kept_existing' : 'fallback');
  }
  assert.equal(fallbackTitle('User: My password is TOPSECRET\nAssistant: Done'), 'Untitled coding session');
  assert.equal(fallbackTitle('User: Inspect /private/project and https://example.com me@example.com\nAssistant: Done'), 'Untitled coding session');
  assert.equal(fallbackTitle('User: abcdefghijklmnopqrstuvwxyzabcdefghijklmnop'), 'Untitled coding session');
});

test('cancellation during retry wait prevents retries and fallback', async () => {
  const controller = new AbortController();
  let calls = 0;
  const pending = resilientTitle(JSON.stringify({ currentTitle: '', conversation: 'User: A task' }), controller.signal,
    async () => { calls++; throw new NamingError('timeout'); }, () => {}, 1000);
  await tick(); controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(calls, 1);
});

test('CLI adapter uses stdin and validates envelope; handles timeout, overflow, missing binary and abort', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pi-autoname-'));
  const binary = join(dir, 'fake-model');
  const script = async body => writeFile(binary, `#!${process.execPath}\n${body}`, { mode: 0o755 });
  try {
    await script(`let input=''; process.stdin.on('data', b => input += b); process.stdin.on('end', () => {
      if(input !== 'PRIVATE TRANSCRIPT' || process.argv.includes(input)) process.exit(2);
      console.log(JSON.stringify({text:'Local Session Title',localOnly:true}));
    });`);
    assert.equal(await generateTitle('PRIVATE TRANSCRIPT', new AbortController().signal, binary), 'Local Session Title');
    for (const [output, code] of [['not json', 'invalid_json'], [JSON.stringify({ text: 'Cloud Session Title', localOnly: false }), 'not_local'], ['x'.repeat(17000), 'output_limit']]) {
      await script(`process.stdin.resume(); console.log(${JSON.stringify(output)});`);
      await assert.rejects(generateTitle('', new AbortController().signal, binary), { code });
    }
    await script('process.stdin.resume(); setInterval(() => {}, 1000);');
    await assert.rejects(generateTitle('', new AbortController().signal, binary, 50), { code: 'timeout' });
    const controller = new AbortController();
    const pending = generateTitle('', controller.signal, binary); controller.abort();
    await assert.rejects(pending);
    await assert.rejects(generateTitle('', new AbortController().signal, join(dir, 'missing')), { code: 'missing_binary' });
    for (const [error, code] of [['exceeded context token limit', 'context_limit'], ['guardrail refusal', 'refusal'], ['model unavailable', 'model_unavailable'], ['other failure', 'exit_failure']]) {
      await script(`process.stdin.resume(); process.stderr.write(${JSON.stringify(error)}); process.exitCode=1;`);
      await assert.rejects(generateTitle('', new AbortController().signal, binary), { code });
    }
  } finally { await rm(dir, { recursive: true, force: true }); }
});
