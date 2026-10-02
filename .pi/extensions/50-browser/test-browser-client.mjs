import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
// npm --prefix propagates its project prefix to child `npm root -g` calls.
// Resolve the actual Pi install without that test-runner override.
process.env.PI_TEST_NODE_MODULES ||= execFileSync('npm', ['root', '-g'], {
  encoding: 'utf8',
  env: Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^npm_config_.*prefix$/i.test(k))),
}).trim();
const { jiti } = await import('../../tests/helpers/pi-import.mjs');
const { DaemonBrowserManager } = await jiti.import(new URL('./daemon-browser-manager.ts', import.meta.url).pathname);
const { default: registerBrowser } = await jiti.import(new URL('./index.ts', import.meta.url).pathname);

test('client adds unique identities, preflights protocol, and serializes its calls', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'browser-client-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir,'token'), 'test-token');
  const calls = [];
  let version = 2;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: new URL(url).pathname, id: options.headers['x-jarvis-browser-session'] });
    await new Promise(resolve => setImmediate(resolve));
    return { ok: true, json: async () => ({ ok: true, result: { protocolVersion: version, pages: [] } }) };
  });
  const manager = () => new DaemonBrowserManager('http://127.0.0.1:1',join(dir,'token'));
  const a=manager(), b=manager();
  await Promise.all([a.open('about:blank'), a.click({x:1,y:2}), b.status()]);
  assert.notEqual(a.sessionId,b.sessionId);
  assert.deepEqual(calls.filter(c=>c.id===a.sessionId).map(c=>c.path),['/status','/open','/click']);
  assert.ok(calls.every(c=>c.id));
  version=1;
  const old=manager();
  await assert.rejects(old.open('about:blank'), /update\/restart/);
  assert.deepEqual(calls.filter(c=>c.id===old.sessionId).map(c=>c.path),['/status']);
});

test('tool registration scopes managers to Pi sessions and lifecycle releases handles', async t => {
  const tools = {}, hooks = {}, commands = {};
  registerBrowser({registerTool: tool => tools[tool.name]=tool, on:(event,fn)=>hooks[event]=fn, registerCommand:(name,c)=>commands[name]=c});
  const seen = [], released = [];
  t.mock.method(DaemonBrowserManager.prototype,'status',async function() { seen.push(this.sessionId); return {pages:[]}; });
  t.mock.method(DaemonBrowserManager.prototype,'close',async function(all) { released.push([this.sessionId,all]); });
  const ctx = id => ({sessionManager:{getSessionId:()=>id}});
  const call = id => tools.browser_status.execute('call',{},undefined,undefined,ctx(id));
  await call('A'); await call('A'); await call('B');
  assert.equal(seen[0],seen[1]); assert.notEqual(seen[0],seen[2]);
  await hooks.session_start({},ctx('C'));
  assert.equal(released.length,2);
  assert.ok(released.every(([,all])=>all===true));
  await call('A'); assert.notEqual(seen[0],seen[3]);
  await hooks.session_shutdown({},ctx('A'));
  assert.equal(released.length,3);
  assert.ok(tools.browser_tabs.parameters.properties.tabId);
});
