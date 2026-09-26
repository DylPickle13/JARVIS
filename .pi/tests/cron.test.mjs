import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { jiti } from './helpers/pi-import.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const { default: register, parseCronArguments } = await jiti.import(join(root, '.pi/extensions/10-jarvis-cron.ts'));
const runner = join(root, 'projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py');

for (const cwd of [root, join(root, 'projects/operation-jarvis/jarvisd')]) {
  test(`cron adapter resolves backend from ${cwd}`, async () => {
    let tool;
    const calls = [];
    register({
      registerTool(value) { tool = value; },
      registerCommand() {},
      async exec(python, args) {
        calls.push({ python, args });
        return { code: 0, stdout: '{"ok":true,"jobs":7}', stderr: '' };
      },
    });
    const result = await tool.execute('test', { action: 'status' }, undefined, undefined, { cwd });
    assert.deepEqual(calls[0].args, [runner, '--json', 'status']);
    assert.equal(calls[0].python, join(root, '.venv/bin/python'));
    assert.equal(result.details.jobs, 7);
  });
}

function adapterFixture() {
  let tool;
  let command;
  const calls = [];
  register({
    registerTool(value) { tool = value; },
    registerCommand(_name, value) { command = value; },
    async exec(python, args) {
      calls.push({ python, args });
      return { code: 0, stdout: '{"ok":true,"message":"done"}', stderr: '' };
    },
  });
  return { tool, command, calls, ctx: { cwd: root, ui: { notify() {} } } };
}

test('category tool schema and argument forwarding cover add, move, clear and filter', async () => {
  const { tool, calls, ctx } = adapterFixture();
  assert.ok(tool.parameters.properties.category);
  assert.ok(JSON.stringify(tool.parameters.properties.action).includes('set_category'));
  const cases = [
    [{ action: 'add', name: 'keys', schedule: '1m', prompt: 'never run', category: 'Home Automation' },
      ['add', '--name', 'keys', '--schedule', '1m', '--prompt', 'never run', '--category', 'Home Automation']],
    [{ action: 'set_category', jobId: 'Keyboard lights', category: 'Home Automation' },
      ['set-category', 'Keyboard lights', '--category', 'Home Automation']],
    [{ action: 'set_category', jobId: 'job_test', category: '' }, ['set-category', 'job_test', '--category', '']],
    [{ action: 'list', category: 'Shopping' }, ['list', '--category', 'Shopping']],
    [{ action: 'list' }, ['list']],
  ];
  for (const [params, expected] of cases) {
    await tool.execute('test', params, undefined, undefined, ctx);
    assert.deepEqual(calls.at(-1).args, [runner, '--json', ...expected]);
  }
  for (const params of [{ action: 'set_category', jobId: 'job_test' }, { action: 'set_category', category: 'Shopping' }]) {
    await assert.rejects(() => tool.execute('test', params, undefined, undefined, ctx), /requires jobId and category/);
  }
  assert.equal(calls.length, cases.length);
});

test('slash command preserves quoted category/job names and empty category', async () => {
  const { command, calls, ctx } = adapterFixture();
  await command.handler('set-category "Keyboard lights" --category "Home Automation"', ctx);
  assert.deepEqual(calls[0].args, [runner, 'set-category', 'Keyboard lights', '--category', 'Home Automation']);
  await command.handler("set-category 'Keyboard lights' --category ''", ctx);
  assert.deepEqual(calls[1].args, [runner, 'set-category', 'Keyboard lights', '--category', '']);
  await command.handler('', ctx);
  assert.deepEqual(calls[2].args, [runner, 'status']);
  await assert.rejects(() => command.handler('list --category "broken', ctx), /Unclosed quote/);
  assert.equal(calls.length, 3);
});

test('cron argument tokenizer is literal and rejects incomplete input', () => {
  assert.deepEqual(parseCronArguments(String.raw`list --category Home\ Automation`), ['list', '--category', 'Home Automation']);
  assert.deepEqual(parseCronArguments('list --category "$(touch /tmp/nope)"'), ['list', '--category', '$(touch /tmp/nope)']);
  assert.deepEqual(parseCronArguments('list --category ""'), ['list', '--category', '']);
  assert.throws(() => parseCronArguments("list --category 'broken"), /Unclosed quote/);
  assert.throws(() => parseCronArguments('list ' + String.fromCharCode(92)), /trailing escape/);
});

test('Pi permission adapter does not own backend storage', () => {
  const source = readFileSync(join(root, '.pi/extensions/00-private-permissions.ts'), 'utf8');
  assert.ok(!source.includes('scheduler'));
});

test('session notification gate and receipts belong to backend', () => {
  const source = readFileSync(join(root, '.pi/extensions/46-local-pi-session-status.ts'), 'utf8');
  assert.ok(source.includes('"jarvisd_core", "scheduler", "session_completion.py"'));
  assert.ok(!source.includes('"session-notifications", "enabled"'));
});

test('native registration source targets the existing backend directly', () => {
  const source = readFileSync(join(root, 'projects/operation-jarvis/jarvis-app/JARVIS/PushRegistrationSSHTransport.swift'), 'utf8');
  const relative = 'projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/apns_registration.py';
  assert.ok(source.includes(`/Users/dylanrapanan/JARVIS/${relative}`));
  assert.ok(existsSync(join(root, relative)));
  assert.ok(!source.includes('.pi/scheduler'));
});
