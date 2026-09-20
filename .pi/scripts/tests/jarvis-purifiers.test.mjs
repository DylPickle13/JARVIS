import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { jiti } from '../../tests/helpers/pi-import.mjs';
const register = await jiti.import(resolve(import.meta.dirname, '../../extensions/45-jarvis.ts'), { default: true });
const tools = {}; const calls = [];
register({ registerTool(t) { tools[t.name] = t; }, async exec(command, args) { calls.push(args); return { code: 0, stdout: '{"ok":true}', stderr: '' }; } });
const invoke = (params, tool = 'purifier') => tools[`operation_jarvis_${tool}`].execute('offline-test', params, undefined, undefined, { cwd: resolve(import.meta.dirname, '../../..') });
test('only focused canonical tools registered, no mixed legacy names', () => {
  assert.deepEqual(Object.keys(tools).sort(), ['operation_jarvis_media', 'operation_jarvis_plugs', 'operation_jarvis_purifier']);
  for (const t of Object.values(tools)) {
    assert.equal(t.parameters.additionalProperties, false);
    assert.equal(t.executionMode, 'sequential');
    assert.equal(t.promptSnippet, undefined);
    assert.equal(t.promptGuidelines, undefined);
  }
});
test('discovery and batch actions route without spawning a real process', async () => {
  for (const action of ['list', 'status-all']) {
    await invoke({ action }); assert.deepEqual(calls.at(-1).slice(-2), ['--json', `purifier-${action}`]);
  }
});
test('read recovery flag and exact name preserved', async () => {
  await invoke({ action: 'status', purifier: "Example's Air Purifier", retryCooldown: true });
  assert.deepEqual(calls.at(-1).slice(-4), ['purifier-status', '--retry-cooldown', '--purifier', "Example's Air Purifier"]);
});
test('batch recovery routes', async () => {
  await invoke({ action: 'status-all', retryCooldown: true });
  assert.deepEqual(calls.at(-1).slice(-2), ['purifier-status-all', '--retry-cooldown']);
});
test('recovery cannot be applied to writes or discovery', async () => {
  for (const action of ['set', 'list']) {
    const before = calls.length;
    await assert.rejects(invoke({ action, setting: 'mode', value: 'auto', retryCooldown: true }), /only allowed/);
    assert.equal(calls.length, before);
  }
});
test('collection rejects selector; settings require set', async () => {
  await assert.rejects(invoke({ action: 'status-all', purifier: 'example' }), /selector/);
  await assert.rejects(invoke({ action: 'status', setting: 'power', value: 'off' }), /require/);
});
test('single-device write retains selector and no group expansion', async () => {
  await invoke({ action: 'set', purifier: 'example', setting: 'mode', value: 'auto' });
  assert.deepEqual(calls.at(-1).slice(-5), ['purifier-set', '--purifier', 'example', 'mode', 'auto']);
});
test('plug aliases, power and playback are separate', async () => {
  await invoke({ action: 'off', plug: 'tv' }, 'plugs');
  assert.deepEqual(calls.at(-1).slice(-2), ['plug-off', 'tv']);
  await invoke({ action: 'stop', device: 'tv' }, 'media');
  assert.deepEqual(calls.at(-1).slice(-4), ['cast-stop', '--device', 'tv', '--quit-app']);
  await assert.rejects(invoke({ action: 'on', plug: '192.0.2.1' }, 'plugs'), /alias/);
  assert.equal(tools.operation_jarvis_plugs.prepareArguments({ action: 'on', plug: 'Example Light' }).plug, 'example-light');
});
test('media routes speech, Spotify and YouTube to existing adapter', async () => {
  for (const [p, tail] of [
    [{ action: 'speak', text: 'Hello' }, ['speak', '--device', 'speakers', 'Hello']],
    [{ action: 'youtube', query: 'jazz' }, ['cast-youtube', '--device', 'tv', 'jazz']],
    [{ action: 'spotify', resume: true }, ['cast-spotify', '--device', 'speakers', '--resume']],
    [{ action: 'spotify-seek', position: '1:30' }, ['cast-spotify-seek', '--device', 'speakers', '1:30']],
  ]) { await invoke(p, 'media'); assert.deepEqual(calls.at(-1).slice(-tail.length), tail); }
});
test('missing parameters, unsafe positional options and ranges fail before execution', async () => {
  const before = calls.length;
  await assert.rejects(invoke({ action: 'volume' }, 'media'), /required/);
  await assert.rejects(invoke({ action: 'volume', level: 101 }, 'media'), /0..100/);
  await assert.rejects(invoke({ action: 'set', setting: 'speed', level: 5 }), /1..4/);
  await assert.rejects(invoke({ action: 'speak', text: '--help' }, 'media'), /option/);
  await assert.rejects(invoke({ action: 'execute' }, 'media'), /Unsupported/);
  assert.equal(calls.length, before);
});
