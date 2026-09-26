import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { jiti } from './helpers/pi-import.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const { default: register } = await jiti.import(join(root, '.pi/extensions/10-jarvis-cron.ts'));
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
