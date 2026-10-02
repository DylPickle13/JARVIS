import test from 'node:test';
import assert from 'node:assert/strict';
import { BrowserSessions } from './browser-sessions.mjs';
import { ExtensionBrowserBackend, extensionAction } from './extension-browser-backend.mjs';

function fixture() {
  let now = 1000, nextId = 10;
  const sessions = new BrowserSessions({ now: () => now, leaseMs: 100 });
  const pages = [], calls = [];
  const run = async (path, body) => {
    calls.push({ path, ...body });
    if (path === '/status') return { pages: pages.map((p, index) => ({ ...p, index })) };
    if (path === '/new-tab') {
      const page = { tabId: nextId++, url: 'about:blank', title: '' };
      pages.push(page);
      return { ...page, index: pages.length - 1 };
    }
    const page = pages.find(p => p.tabId === body.targetTabId);
    assert.ok(page, `missing explicit target for ${path}`);
    if (path === '/open') page.url = body.url;
    if (path === '/tabs' && body.action === 'close') pages.splice(pages.indexOf(page), 1);
    return { ...page, index: pages.indexOf(page) };
  };
  return { sessions, pages, calls, run, advance: () => now += 101,
    call: (id, path, body = {}) => sessions.handle(path, body, id, run) };
}

test('shared inventory, independent selection and interleaved explicit targets', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'https://a.test' });
  const b = await f.call('B', '/open', { url: 'https://b.test' });
  assert.notEqual(a.tabId, b.tabId);
  const sa = await f.call('A', '/status'), sb = await f.call('B', '/status');
  assert.deepEqual(sa.pages.map(p => p.tabId), sb.pages.map(p => p.tabId));
  assert.equal(sa.selectedTabId, a.tabId); assert.equal(sb.selectedTabId, b.tabId);
  assert.equal(sa.pages[1].controlledBy, 'B');
  await f.call('A', '/screenshot');
  await f.call('B', '/open', { url: 'https://b.test/next' });
  await f.call('A', '/click', { x: 4, y: 5 });
  await f.call('B', '/type', { text: 'B' });
  const inputs = f.calls.filter(c => ['/click', '/type'].includes(c.path));
  assert.deepEqual(inputs.map(c => c.targetTabId), [a.tabId, b.tabId]);
});

test('same-tab lease rejects switch/close, explicit release permits handoff', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'about:blank' });
  for (const action of ['switch', 'close']) {
    await assert.rejects(f.call('B', '/tabs', { action, tabId: a.tabId }), /controlled by another/);
  }
  await f.call('B', '/tabs', { action: 'release', tabId: a.tabId });
  assert.equal(f.sessions.lease(a.tabId).owner, 'A', 'cannot release another session');
  await f.call('A', '/tabs', { action: 'release' });
  await f.call('B', '/tabs', { action: 'switch', tabId: a.tabId });
  await assert.rejects(f.call('A', '/click', { x: 1, y: 1 }), /released or expired/);
  await f.call('B', '/click', { x: 2, y: 2 });
});

test('expired leases recover crashed clients but never silently reacquire control', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'about:blank' });
  f.advance();
  await f.call('A', '/status'); // Listing is not a heartbeat.
  await assert.rejects(f.call('A', '/type', { text: 'stale' }), /released or expired/);
  await f.call('B', '/tabs', { action: 'switch', tabId: a.tabId });
  await assert.rejects(f.call('A', '/tabs', { action: 'switch', tabId: a.tabId }), /controlled by another/);
});

test('closed/moved selection is a tombstone, never fallback to another tab', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'about:blank' });
  const b = await f.call('B', '/open', { url: 'about:blank' });
  f.pages.splice(f.pages.findIndex(p => p.tabId === a.tabId), 1);
  const before = f.calls.length;
  for (const path of ['/click', '/screenshot', '/close', '/open']) {
    await assert.rejects(f.call('A', path, { all: false, url: 'https://no.test' }), /closed or moved/);
  }
  assert.ok(f.calls.slice(before).every(c => c.path === '/status'));
  assert.equal((await f.call('A', '/status')).selectionMissing, true);
  assert.equal((await f.call('B', '/status')).selectedTabId, b.tabId);
});

test('indexes bind to the caller\'s prior inventory, not a shifted global array', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'about:blank' });
  const b = await f.call('B', '/open', { url: 'about:blank' });
  await f.call('C', '/tabs', { action: 'list' });
  await f.call('A', '/close', { all: false });
  await f.call('B', '/tabs', { action: 'release' });
  await assert.rejects(f.call('C', '/tabs', { action: 'switch', index: 0 }), /closed or moved/);
  const status = await f.call('C', '/tabs', { action: 'switch', index: 1 });
  assert.equal(status.selectedTabId, b.tabId);
  await assert.rejects(f.call('D', '/tabs', { action: 'switch', index: 0 }), /list tabs before/);
  assert.notEqual(a.tabId, b.tabId);
});

test('release-all is session-local, preserves tabs, and works without Chrome', async () => {
  const f = fixture();
  await f.call('A', '/open', { url: 'about:blank' });
  await f.call('A', '/open', { url: 'about:blank', newTab: true });
  const b = await f.call('B', '/open', { url: 'about:blank' });
  await f.sessions.handle('/close', { all: true }, 'A', () => { throw Error('must not connect'); });
  assert.equal(f.pages.length, 3);
  assert.equal(f.sessions.leases.size, 1);
  assert.equal(f.sessions.lease(b.tabId).owner, 'B');
});

test('new-tab/close keyboard shortcuts respect session selection and leases', async () => {
  const f = fixture();
  await f.call('B', '/open', { url: 'about:blank' });
  const a = await f.call('A', '/key', { key: 'Meta+T' });
  await f.call('A', '/key', { key: 'Control+W' });
  assert.ok(!f.pages.some(p => p.tabId === a.tabId));
  await assert.rejects(f.call('A', '/key', { key: 'Enter' }), /closed or moved/);
  assert.equal(f.pages.length, 1);
});

test('navigation failure retains the created identity/lease; no unsafe URL creates tabs', async () => {
  const f = fixture();
  await assert.rejects(f.call('A', '/open', { url: 'javascript:alert(1)' }), /Only HTTP/);
  assert.equal(f.pages.length, 0);
  await assert.rejects(f.sessions.handle('/open', { url: 'https://bad.test' }, 'A', async (p, b) => {
    if (p === '/open') throw Error('navigation timeout');
    return f.run(p, b);
  }), /navigation timeout/);
  const status = await f.call('A', '/status');
  assert.equal(status.selectedTabId, f.pages[0].tabId);
  assert.equal(status.pages[0].controlledBy, 'A');
});

test('uncertain transport fences stale actions; explicit selection restores control', async () => {
  const f = fixture();
  const a = await f.call('A', '/open', { url: 'about:blank' });
  f.sessions.invalidate();
  await assert.rejects(f.call('A', '/click', { x: 1, y: 2 }), /uncertain outcome/);
  await f.call('A', '/tabs', { action: 'switch', tabId: a.tabId });
  await f.call('A', '/click', { x: 1, y: 2 });
});

test('malformed inventory fails before creating tabs or discarding existing leases', async () => {
  const f = fixture();
  const opened=await f.call('A','/open',{url:'about:blank'});
  let mutations=0;
  await assert.rejects(f.sessions.handle('/open',{url:'about:blank',newTab:true},'A',async path=>{
    if(path!=='/status') mutations++;
    return {pages:[{index:0,url:'about:blank'}]};
  }),/inventory identity missing/);
  assert.equal(mutations,0);
  assert.equal(f.sessions.lease(opened.tabId).owner,'A');
});

test('fresh daemon state cannot inherit physical selection or stale indexes', async () => {
  const f = fixture();
  await f.call('A', '/open', { url: 'about:blank' });
  const restarted = new BrowserSessions();
  await assert.rejects(restarted.handle('/click', {}, 'A', f.run), /No tab selected/);
  await assert.rejects(restarted.handle('/tabs', { action: 'switch', index: 0 }, 'A', f.run), /list tabs before/);
});

test('backend queue serializes routing and actions; transport reset preserves session IDs', async () => {
  const f = fixture(), backend = new ExtensionBrowserBackend({});
  backend.connected = true;
  backend.init = backend.assertWindow = async () => {};
  let active = 0, peak = 0;
  backend.callAction = async (p, b) => {
    peak = Math.max(peak, ++active);
    await new Promise(resolve => setImmediate(resolve));
    try { return await f.run(p, b); } finally { active--; }
  };
  backend.prepare=()=>backend.callAction('/status',{});
  const [a, b] = await Promise.all([
    backend.handle('/open', { url: 'https://a.test' }, 'A'),
    backend.handle('/open', { url: 'https://b.test' }, 'B'),
  ]);
  assert.equal(peak, 1); assert.notEqual(a.tabId, b.tabId);
  await backend.reset();
  assert.equal(backend.sessions.session('A').tabId, a.tabId);
  assert.equal(backend.sessions.session('B').tabId, b.tabId);
});

test('destroyed anchor execution context resets transport and fences sessions without replay', async () => {
  const backend=new ExtensionBrowserBackend({});
  backend.connected=true;
  backend.sessions.session('A').tabId=10;
  backend.init=backend.assertWindow=async()=>{};
  let calls=0;
  backend.prepare=async()=>{calls++;throw new Error('Anchor inventory: page.evaluate: Execution context was destroyed, most likely because of a navigation.');};
  await assert.rejects(backend.handle('/status',{},'A'),/Execution context was destroyed/);
  assert.equal(calls,3); // bounded read-only recovery; no control action dispatched
  assert.equal(backend.connected,false);
  assert.equal(backend.sessions.session('A').uncertain,true);
});

test('read-only preflight recovers while preserving selected IDs; mutation dispatch occurs exactly once', async () => {
  const f=fixture(),backend=new ExtensionBrowserBackend({});
  backend.sessions=f.sessions;
  const opened=await f.call('A','/open',{url:'about:blank'});
  let attempts=0;
  backend.prepare=async()=>{
    if (++attempts===1) throw new Error('Anchor inventory: Execution context was destroyed');
    backend.connected=true;
    return f.run('/status',{});
  };
  backend.callAction=f.run;
  await backend.handle('/click',{x:1,y:2},'A');
  assert.equal(attempts,2);
  assert.equal(backend.recoveryCount,1);
  assert.equal(backend.sessions.session('A').tabId,opened.tabId);
  assert.equal(f.calls.filter(c=>c.path==='/click').length,1);
});

test('lost mutation response is never replayed and requires explicit reselection', async () => {
  const f=fixture(),backend=new ExtensionBrowserBackend({});
  backend.sessions=f.sessions;
  await f.call('A','/open',{url:'about:blank'});
  backend.prepare=async()=>{backend.connected=true;return f.run('/status',{});};
  let clicks=0;
  backend.callAction=async path=>{assert.equal(path,'/click');clicks++;throw new Error('transport closed after dispatch');};
  await assert.rejects(backend.handle('/click',{x:1,y:2},'A'),/transport closed/);
  assert.equal(clicks,1);
  assert.equal(backend.sessions.session('A').uncertain,true);
  await assert.rejects(backend.handle('/click',{x:1,y:2},'A'),/uncertain outcome/);
  assert.equal(clicks,1);
});

test('missing or moved window is not automatically retried', async () => {
  const backend=new ExtensionBrowserBackend({});
  let calls=0;
  backend.prepare=async()=>{calls++;throw new Error('Automation window or connection moved/closed; refusing to control another window');};
  await assert.rejects(backend.handle('/open',{url:'about:blank'},'A'),/moved\/closed/);
  assert.equal(calls,1);
});

test('real fixed action uses stable target, not the physically/logically active tab', async () => {
  const events = [];
  const page = id => ({ isClosed: () => false, url: () => 'about:blank', title: async () => '',
    evaluate: async () => JSON.stringify({tabId:id}), bringToFront: async () => events.push(['activate',id]),
    mouse: { click: async () => events.push(['click',id]) } });
  const a=page(10), b=page(20);
  const anchor = {isClosed:()=>false,url: () => 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2',
    evaluate: async () => JSON.stringify({tabs:[{tabId:10,active:false},{tabId:20,active:true}]})};
  const context = {pages:()=>[anchor,a,b],__jarvisOwnedTabs:{pages:[a,b],active:b,anchor}};
  const seed = {context:()=>context};
  await extensionAction(seed,'/click',{targetTabId:10,x:1,y:2});
  assert.deepEqual(events,[['activate',10],['click',10]]);
  await assert.rejects(extensionAction(seed,'/click',{targetTabId:99,x:1,y:2}),/refusing to target/);
  assert.equal(events.length,2);
});
