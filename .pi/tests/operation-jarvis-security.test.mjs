import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, mkdir, writeFile, chmod, symlink, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { jiti } from './helpers/pi-import.mjs';
const { registerSecurity } = await jiti.import(resolve(import.meta.dirname, '../extensions/48-jarvis-security.ts'));
const { projectSecurity, runSecurity, commissioned } = await jiti.import(resolve(import.meta.dirname, '../extensions/lib/operation-jarvis-security.ts'));
const rule = { name: 'Example protocol', ref: 'a'.repeat(16), revision: 'b'.repeat(64), kind: 'automation', enabled: false };
const configuration = { triggers: [{ model: 'T110', event: 'open', deviceId: 'SECRET' }], actions: [{ model: 'H200', configured_duration_seconds: 300, configured_alarm_tone: 'Alarm 4', configured_volume_raw: '10', thingName: 'SECRET' }], all_day: true, raw: 'SECRET' };
function fixture(options = {}) {
  const tools = {}, calls = [], confirmations = [];
  let current = { ...rule, ...options.rule };
  const payload = args => {
    if (args[0] === 'devices') return { result: 'configured', devices: { 'example-sensor': { model: 'T110', host: 'SECRET' } } };
    if (args[0] === 'status' || args[0] === 'capabilities') return { result: 'read_succeeded', device: args[1], model: 'T110', name: 'PRIVATE', features: { is_open: { value: true } } };
    if (args[1] === 'list') return { result: 'read_succeeded', rules: options.rules ?? [current] };
    if (args[1] === 'describe') return { result: 'read_succeeded', rule: { ...current, ...options.described }, configuration };
    if (options.writeThrow) throw Error('SECRET');
    current = { ...current, enabled: args[1] === 'enable', revision: 'c'.repeat(64) };
    return options.writePayload ?? { result: 'write_verified', rule: current, private_backup: 'SECRET' };
  };
  registerSecurity({ registerTool(t) { tools[t.name] = t; } }, {
    directory: () => '/unused/mock-only', commissioned: async () => options.accepted ?? false,
    run: async (_dir, args) => { calls.push(args); return { code: args[1] === 'enable' ? options.writeCode ?? 0 : 0, payload: payload(args) }; },
  });
  const ctx = { cwd: '/unused', hasUI: options.hasUI ?? true, ui: { async confirm(title, body) { confirmations.push({ title, body }); return options.confirm ?? true; } } };
  return { tools, calls, confirmations, invoke: (p, kind = 'automations', signal) => tools[`operation_jarvis_${kind}`].execute('test', p, signal, undefined, ctx) };
}
test('only canonical tools and narrow schemas; no prompt injection on load', () => {
  const f = fixture();
  assert.deepEqual(Object.keys(f.tools), ['operation_jarvis_security', 'operation_jarvis_automations']);
  for (const tool of Object.values(f.tools)) {
    assert.equal(tool.parameters.additionalProperties, false);
    assert.equal(tool.executionMode, 'sequential');
    assert.equal(tool.promptSnippet, undefined);
  }
});
test('devices/status/capabilities use only fixed read argv and strip identity', async () => {
  const f = fixture();
  for (const action of ['devices', 'status', 'capabilities']) {
    const r = await f.invoke({ action, ...(action === 'devices' ? {} : { device: 'example-sensor' }) }, 'security');
    assert.equal(r.isError, false); assert.doesNotMatch(JSON.stringify(r), /SECRET|PRIVATE/);
  }
  assert.deepEqual(f.calls, [['devices'], ['status', 'example-sensor'], ['capabilities', 'example-sensor']]);
});
test('security rejects arbitrary commands and path/host overrides before networking', async () => {
  const f = fixture();
  for (const p of [{ action: 'snapshot' }, { action: 'status', device: '--help' }, { action: 'status', device: '192.0.2.1' }, { action: 'devices', device: 'example-sensor' }]) {
    assert.equal((await f.invoke(p, 'security')).isError, true);
  }
  assert.equal(f.calls.length, 0);
});
test('list and describe resolve names fresh, no raw rule export', async () => {
  const f = fixture();
  const r = await f.invoke({ action: 'describe', name: 'EXAMPLE PROTOCOL' });
  assert.equal(r.isError, false); assert.doesNotMatch(JSON.stringify(r), /SECRET|private_file|thingName/);
  assert.deepEqual(f.calls, [['smart-actions', 'list'], ['smart-actions', 'describe', rule.ref]]);
  assert.equal(r.details.configuration.trigger_combination, 'not_interpreted');
});
test('missing/duplicate names never pick a rule or write', async () => {
  for (const rules of [[], [rule, { ...rule, ref: 'd'.repeat(16), name: 'EXAMPLE PROTOCOL' }]]) {
    const f = fixture({ rules, accepted: true });
    assert.equal((await f.invoke({ action: 'enable', name: rule.name })).details.reason, 'rule_name_missing_or_ambiguous');
    assert.equal(f.calls.length, 1);
  }
});
test('revision changes between listing and description fail closed', async () => {
  const f = fixture({ described: { revision: 'd'.repeat(64) }, accepted: true });
  assert.equal((await f.invoke({ action: 'enable', name: rule.name })).details.result, 'rule_changed');
  assert.equal(f.calls.length, 2); assert.equal(f.confirmations.length, 0);
});
test('uncommissioned change returns configuration preview without writing', async () => {
  const f = fixture(); const r = await f.invoke({ action: 'enable', name: rule.name });
  assert.equal(r.details.result, 'commissioning_required'); assert.equal(r.details.writes_attempted, 0);
  assert.equal(f.calls.length, 2); assert.equal(f.confirmations.length, 0);
});
test('already desired state is a read-only no-op', async () => {
  const f = fixture(); const r = await f.invoke({ action: 'disable', name: rule.name });
  assert.equal(r.details.result, 'unchanged'); assert.equal(f.calls.length, 2);
});
test('shortcuts are not enabled or executed', async () => {
  const f = fixture({ rule: { kind: 'shortcut' }, accepted: true });
  assert.equal((await f.invoke({ action: 'enable', name: rule.name })).details.result, 'unsupported_rule_kind');
  assert.equal((await f.invoke({ action: 'execute', name: rule.name })).isError, true);
  assert.equal(f.calls.length, 2);
});
test('headless sessions cannot approve a write', async () => {
  const f = fixture({ accepted: true, hasUI: false });
  assert.equal((await f.invoke({ action: 'enable', name: rule.name })).details.result, 'confirmation_ui_required');
  assert.equal(f.calls.length, 2);
});
test('declining confirmation or aborting before write sends nothing', async () => {
  for (const aborted of [false, true]) {
    const f = fixture({ accepted: true, confirm: aborted });
    const signal = aborted ? AbortSignal.abort() : undefined;
    assert.equal((await f.invoke({ action: 'enable', name: rule.name }, 'automations', signal)).details.result, 'cancelled');
    assert.equal(f.calls.length, 2);
  }
});
test('accepted and confirmed enable uses exact revision once with readback', async () => {
  const f = fixture({ accepted: true });
  const r = await f.invoke({ action: 'enable', name: rule.name });
  assert.deepEqual(f.calls.at(-1), ['smart-actions', 'enable', rule.ref, '--revision', rule.revision, '--confirm']);
  assert.equal(f.calls.length, 3); assert.equal(f.confirmations.length, 1);
  assert.match(f.confirmations[0].body, /300|immediately/);
  assert.equal(r.details.configuration_verified, true); assert.equal(r.details.physical_behavior, 'not_verified');
  assert.doesNotMatch(JSON.stringify(r), /SECRET|private_backup/);
});
test('disable uses the same guarded path', async () => {
  const f = fixture({ accepted: true, rule: { enabled: true } });
  assert.equal((await f.invoke({ action: 'disable', name: rule.name })).details.rule.enabled, false);
  assert.equal(f.calls.at(-1)[1], 'disable');
});
test('stale CLI revision rejection is not replayed', async () => {
  const f = fixture({ accepted: true, writeCode: 2, writePayload: { result: 'error', reason: 'smart_revision_conflict' } });
  const r = await f.invoke({ action: 'enable', name: rule.name });
  assert.equal(r.isError, true); assert.equal(r.details.automatic_retry, false); assert.equal(f.calls.length, 3);
});
test('uncertain/timeout/malformed/incorrect readback never reports success or retries', async () => {
  for (const option of [
    { writeCode: 3, writePayload: { result: 'write_outcome_unknown', private_backup: 'SECRET' } },
    { writeThrow: true }, { writePayload: { result: 'write_verified', rule } },
    { writePayload: { result: 'write_verified', rule: { password: 'SECRET' } } },
  ]) {
    const f = fixture({ accepted: true, ...option }); const r = await f.invoke({ action: 'enable', name: rule.name });
    assert.equal(r.details.result, 'write_outcome_unknown'); assert.equal(r.isError, true);
    assert.equal(r.details.automatic_retry, false); assert.equal(f.calls.length, 3);
    assert.doesNotMatch(JSON.stringify(r), /SECRET/);
  }
});
test('device identity mismatch never becomes a successful observation', async () => {
  const tools = {};
  registerSecurity({ registerTool(t) { tools[t.name] = t; } }, {
    directory: () => '/unused', run: async () => ({ code: 0, payload: { result: 'read_succeeded', device: 'wrong-sensor', model: 'T110' } }),
  });
  const r = await tools.operation_jarvis_security.execute('test', { action: 'status', device: 'example-sensor' }, undefined, undefined, { cwd: '/unused' });
  assert.equal(r.isError, true); assert.doesNotMatch(JSON.stringify(r), /wrong-sensor/);
});
test('busy security calls are rejected, never queued', async () => {
  const tools = {}; let release; let calls = 0;
  registerSecurity({ registerTool(t) { tools[t.name] = t; } }, {
    directory: () => '/unused', run: async () => { calls++; await new Promise(r => release = r); return { code: 0, payload: { result: 'configured', devices: {} } }; },
  });
  const invoke = () => tools.operation_jarvis_security.execute('test', { action: 'devices' }, undefined, undefined, { cwd: '/unused' });
  const first = invoke(); const second = await invoke();
  assert.equal(second.details.result, 'device_busy'); assert.equal(calls, 1);
  release(); assert.equal((await first).isError, false);
});
test('revocation while consent is open prevents the write', async () => {
  const tools = {}; let accepted = true; const calls = [];
  registerSecurity({ registerTool(t) { tools[t.name] = t; } }, {
    directory: () => '/unused', commissioned: async () => accepted,
    run: async (_d, args) => { calls.push(args); return { code: 0, payload: args[1] === 'list' ? { result: 'read_succeeded', rules: [rule] } : { result: 'read_succeeded', rule, configuration } }; },
  });
  const r = await tools.operation_jarvis_automations.execute('test', { action: 'enable', name: rule.name }, undefined, undefined,
    { cwd: '/unused', hasUI: true, ui: { async confirm() { accepted = false; return true; } } });
  assert.equal(r.details.result, 'commissioning_required'); assert.equal(calls.length, 2);
});
test('errored or missing feature values cannot masquerade as observations', () => {
  const r = projectSecurity({ result: 'read_succeeded', features: { is_open: { status: 'unknown', value: false }, battery_low: {} } });
  assert.deepEqual(r.features.is_open, { value: null, status: 'unknown' });
  assert.deepEqual(r.features.battery_low, { value: null, status: 'unknown' });
});
test('projection retains unknown freshness and strips unexpected nested fields', () => {
  const r = projectSecurity({ result: 'read_succeeded', model: 'T100', host: 'SECRET', name: 'SECRET', features: { motion_detected: { value: false, private: 'SECRET' }, password: { value: 'SECRET' } } });
  assert.equal(r.radio_freshness, 'unknown'); assert.equal(r.security_assessment, 'not_assessed');
  assert.equal(r.features.motion_detected.value, false); assert.doesNotMatch(JSON.stringify(r), /SECRET/);
});
test('commissioning marker fails closed on absence, malformed data, permissions and symlink', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'operation-commission-test-')); t.after(() => rm(dir, { recursive: true, force: true }));
  await mkdir(join(dir, 'private-notes')); const path = join(dir, 'private-notes/pi-automation-commissioning.json');
  assert.equal(await commissioned(dir, 'enable'), false);
  await writeFile(path, 'not JSON', { mode: 0o600 }); assert.equal(await commissioned(dir, 'enable'), false);
  await writeFile(path, JSON.stringify({ version: 1, accepted: ['enable'] }));
  assert.equal(await commissioned(dir, 'enable'), true); assert.equal(await commissioned(dir, 'disable'), false);
  await chmod(path, 0o644); assert.equal(await commissioned(dir, 'enable'), false);
  await rm(path); const target = join(dir, 'target'); await writeFile(target, '{"version":1,"accepted":["enable"]}', { mode: 0o600 });
  await symlink(target, path); assert.equal(await commissioned(dir, 'enable'), false);
});
async function launcher(t, source) {
  const dir = await mkdtemp(join(tmpdir(), 'operation-runner-test-')); t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, 'security'), `#!${process.execPath}\n${source}\n`, { mode: 0o700 }); return dir;
}
test('bounded runner parses only stdout, sanitizes startup errors and never passes secrets in env', async t => {
  const dir = await launcher(t, `console.error('SECRET'); console.log(JSON.stringify({result:'read_succeeded', args:process.argv.slice(2), secret:process.env.OPERATION_TEST_SECRET ?? null}));`);
  process.env.OPERATION_TEST_SECRET = 'SECRET'; t.after(() => delete process.env.OPERATION_TEST_SECRET);
  const r = await runSecurity(dir, ['devices']); assert.deepEqual(r.payload.args, ['--json', 'devices']); assert.equal(r.payload.secret, null);
  await assert.rejects(runSecurity(join(dir, 'missing'), []), /security_launcher_unavailable/);
});
test('bounded runner rejects oversized or malformed output', async t => {
  const large = await launcher(t, `process.stdout.write('x'.repeat(300000)); setTimeout(()=>{}, 10000);`);
  await assert.rejects(runSecurity(large, []), /security_output_limit/);
  const invalid = await launcher(t, `console.log('SECRET');`);
  await assert.rejects(runSecurity(invalid, []), /^Error: security_invalid_output$/);
});
test('cancellation kills worker process group and never leaks output', async t => {
  const dir = await launcher(t, `const {spawn}=require('node:child_process'); const fs=require('node:fs'); const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'}); fs.writeFileSync('child.pid',String(c.pid)); setInterval(()=>{},1000);`);
  const controller = new AbortController(); const promise = runSecurity(dir, [], controller.signal);
  let pid;
  for (let i = 0; i < 100; i++) {
    try { pid = Number(await readFile(join(dir, 'child.pid'), 'utf8')); break; } catch { await new Promise(r => setTimeout(r, 10)); }
  }
  assert.ok(pid); controller.abort(); await assert.rejects(promise, /security_cancelled/);
  await new Promise(r => setTimeout(r, 100)); assert.throws(() => process.kill(pid, 0), /ESRCH/);
  await assert.rejects(runSecurity(dir, [], AbortSignal.abort()), /security_cancelled/);
});
