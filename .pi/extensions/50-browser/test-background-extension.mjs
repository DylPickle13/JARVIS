import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const directory = fileURLToPath(new URL('./background-extension/', import.meta.url));
// Exercise the exact pinned transformation used by the build, not a second patch.
const source = execFileSync('python3', ['-c', `from pathlib import Path
from build import patch_background
print(patch_background(Path('upstream-background-0.4.0.mjs').read_text(), Path('native-addon.js').read_text()))`], {cwd: directory, encoding:'utf8'});
const mode = 'jarvis-background-native-v1';
const extensionId = 'mmlmfjhmonkocbjadbfplnigmagldckm';
const url = `chrome-extension://${extensionId}/connect.html?token=fixture-only&mcpRelayUrl=${encodeURIComponent('ws://127.0.0.1:1234/extension')}&protocolVersion=2#jarvis-automation-anchor-v2`;
function fixture() {
  const actions = [], replies = [], timers = [];
  let nativeMessage, disconnected, nextTab = 80;
  const tabWindows = new Map();
  const event = () => ({addListener(){},removeListener(){}});
  const forbidden = name => async(...args) => { actions.push([name,...args]); throw new Error('Foreground operation forbidden'); };
  const port = {
    onMessage:{addListener(fn){nativeMessage=fn;}},
    onDisconnect:{addListener(fn){disconnected=fn;}},
    postMessage(message){replies.push(message);},
  };
  const chrome = {
    runtime:{onMessage:event(),getURL:path=>`chrome-extension://${extensionId}/${path}`,
      connectNative(name){actions.push(['pipe',name]);return port;}},
    windows:{get:async id=>({id,type:'normal',incognito:false}),update:forbidden('window-focus'),create:forbidden('window-create')},
    tabs:{onUpdated:event(),onRemoved:event(),onCreated:event(),query:async()=>[],
      get:async id=>({id,windowId:tabWindows.get(id) ?? 7}),
      group:async properties=>{
        // Chrome defaults NEW groups to the CURRENT window, not the tab's.
        const destination=properties.createProperties?.windowId ?? (properties.groupId ? 7 : 99);
        actions.push(['tab-group',properties]);
        for(const id of properties.tabIds) tabWindows.set(id,destination);
        return 100;
      },
      update:forbidden('tab-activation'),create:async properties=>{actions.push(['tab-create',properties]);return {id:++nextTab,windowId:properties.windowId};},
      remove:async id=>actions.push(['tab-remove',id]),ungroup:async()=>{}},
    tabGroups:{query:async()=>[],update:async()=>{}},
    action:{onClicked:event(),setBadgeText:async()=>{},setTitle:async()=>{},setBadgeBackgroundColor:async()=>{}},
  };
  const sandbox = {chrome,URL,console:{log(){}},setTimeout(fn,ms){timers.push([fn,ms]);},clearTimeout(){}};
  vm.runInNewContext(source.replace('new PlaywrightExtension();','globalThis.extension = new PlaywrightExtension();'), sandbox);
  return {actions,replies,timers,chrome,tabWindows,extension:sandbox.extension,
    send:message=>nativeMessage(message),disconnect:()=>disconnected()};
}
const request = (id='one', extra={}) => ({id,command:'connect',mode,windowId:7,url,...extra});

test('pinned worker removes the focus request without widening debugger commands',()=>{
  assert(!source.includes('chrome.windows.update('));
  assert(!source.includes('focused: true'));
  assert(source.includes('JARVIS_BACKGROUND_HANDSHAKE_V1'));
  assert(!source.includes('chrome.windows.create('));
});
test('twenty fresh handshakes initialize connections without activating tabs or windows', async()=>{
  const f=fixture();
  let initialized=0;
  f.extension._pendingConnections.take=async()=>({attachTab(){},didInitialize(){initialized++;}});
  for(let i=0;i<20;i++) await f.extension._connectTab(20+i,{id:20+i,windowId:7},'JARVIS Browser');
  assert.equal(initialized,20);
  assert.equal(f.extension._connections.size,20);
  assert.deepEqual(f.actions.map(x=>x[0]),['pipe']);
});
test('debugger attachment creates groups in the automation window, not the current window',async()=>{
  const f=fixture();
  const connection={attachedTabs:new Set(),attachTab(){},didInitialize(){}};
  f.extension._pendingConnections.take=async()=>connection;
  await f.extension._connectTab(20,{id:20,windowId:7},'JARVIS Browser');
  // Exercise the real attachment callback missing from the original fixture.
  connection.ontabattached(20);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.tabWindows.get(20),7);
  const group=f.extension._connections.get(1);
  await group._addTabToGroup(21);
  assert.equal(f.tabWindows.get(21),7);
  const operations=f.actions.filter(x=>x[0]==='tab-group');
  assert.equal(operations.length,2);
  assert.equal(operations[0][1].createProperties.windowId,7);
  assert.equal(operations[1][1].groupId,100);
});
test('a moved or personal tab is never regrouped into the automation window',async()=>{
  const f=fixture();
  f.extension._pendingConnections.take=async()=>({attachTab(){},didInitialize(){}});
  await f.extension._connectTab(20,{id:20,windowId:7},'JARVIS Browser');
  f.tabWindows.set(20,99);
  await f.extension._connections.get(1)._addTabToGroup(20);
  assert.equal(f.tabWindows.get(20),99);
  assert(!f.actions.some(x=>x[0]==='tab-group'));
});
test('native creation stays inactive in the exact window, duplicate request never replays',async()=>{
  const f=fixture();
  await f.send(request());
  await f.send(request());
  const creations=f.actions.filter(x=>x[0]==='tab-create');
  assert.equal(creations.length,1);
  assert.equal(creations[0][1].windowId,7);
  assert.equal(creations[0][1].active,false);
  assert.equal(f.replies.at(-1).connectionTabId,81);
  assert.equal(f.replies.at(-1).mode,mode);
  assert(!f.actions.some(x=>['window-focus','window-create','tab-activation'].includes(x[0])));
});
test('invalid URLs, relay hosts, windows and protocol fail before creating a tab',async()=>{
  for(const invalid of [
    {windowId:'7'}, {windowId:0}, {command:'evaluate'}, {mode:'stock'},
    {url:'https://example.com/'}, {url:url.replace(extensionId,'other-extension')},
    {url:url.replace('connect.html','status.html')}, {url:url.replace('#jarvis-automation-anchor-v2','')},
    {url:url.replace('127.0.0.1','example.com')}, {url:url.replace('protocolVersion=2','protocolVersion=1')},
    {url:url.replace('token=fixture-only','token=')},
  ]) {
    const f=fixture();await f.send(request('invalid',invalid));
    assert.equal(f.replies.at(-1).ok,false);
    assert.equal(f.actions.filter(x=>x[0]==='tab-create').length,0);
  }
});
test('missing, incognito or non-normal window never falls back to another window',async()=>{
  for(const get of [async()=>{throw new Error('closed');},async()=>({id:99,type:'normal'}),async()=>({id:7,type:'popup'}),async()=>({id:7,type:'normal',incognito:true})]) {
    const f=fixture();f.chrome.windows.get=get;
    await f.send(request());
    assert.equal(f.replies.at(-1).ok,false);
    assert.deepEqual(f.actions.map(x=>x[0]),['pipe']);
  }
});
test('uncertain creation is not replayed or foregrounded',async()=>{
  const f=fixture();let attempts=0;
  f.chrome.tabs.create=async()=>{attempts++;throw new Error('Outcome unknown');};
  await f.send(request());await f.send(request());
  assert.equal(attempts,1);
  assert.equal(f.replies.at(-1).ok,false);
  assert.deepEqual(f.actions.map(x=>x[0]),['pipe']);
});
test('native host loss reconnects only the pipe, with no Chrome/window launch',()=>{
  const f=fixture();f.disconnect();
  assert.equal(f.timers.length,1);
  assert.equal(f.timers[0][1],3000);
  f.timers[0][0]();
  assert.deepEqual(f.actions.map(x=>x[0]),['pipe','pipe']);
});
