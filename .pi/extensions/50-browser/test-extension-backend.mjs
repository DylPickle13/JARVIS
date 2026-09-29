import test from 'node:test';
import assert from 'node:assert/strict';
import { extensionAction, parseToolResult, ExtensionBrowserBackend } from './extension-browser-backend.mjs';

test('only parses result; never returns connection URL or code transcript',()=>{
  const result=parseToolResult({content:[{type:'text',text:'### Result\n{"ok":true}\n### Page\nchrome-extension://example/?token=secret'}]});
  assert.deepEqual(result,{ok:true});
});
test('malformed and error responses fail closed',()=>{
  assert.throws(()=>parseToolResult({content:[]}));
  assert.throws(()=>parseToolResult({isError:true,content:[{type:'text',text:'### Error\nfailed'}]}));
});
test('errors redact token and connection URL',()=>{
  const b=new ExtensionBrowserBackend({});b.secret='unit-test-secret';
  const text=b.sanitize('unit-test-secret chrome-extension://id/connect?token=other');
  assert(!text.includes('unit-test-secret'));assert(!text.includes('token=other'));
});
test('seed/personal tabs are never adopted or closed',async()=>{
  let created=0;
  const context={newPage:async()=>{
    created++;
    const p={closed:false,isClosed(){return this.closed;},async close(){this.closed=true;},url:()=> 'about:blank',title:async()=>'',goto:async()=>{}};
    return p;
  }};
  const seed={context:()=>context,close(){throw new Error('seed must not be closed');}};
  assert.deepEqual(await extensionAction(seed,'/connect',{}),{activeIndex:-1,pages:[]});
  await extensionAction(seed,'/close',{all:false});assert.equal(created,0);
  await extensionAction(seed,'/open',{url:'about:blank'});assert.equal(created,1);
  await assert.rejects(extensionAction(seed,'/tabs',{action:'close',index:99}));
  await extensionAction(seed,'/close',{all:false});
  assert.deepEqual(await extensionAction(seed,'/status',{}),{activeIndex:-1,pages:[]});
});
test('window inventory recovers existing duplicate-URL tabs and excludes moved/personal tabs',async()=>{
  let inventory = [{tabId:11,active:true},{tabId:12,active:false}];
  const page = id => ({isClosed:()=>false,url:()=> 'https://example.com/same',title:async()=> 'same',evaluate:async()=>JSON.stringify({tabId:id}),bringToFront:async()=>{},close:async()=>{throw new Error('must not close during discovery');}});
  const a=page(11), b=page(12), personal=page(99);
  const anchor={url:()=> 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2',evaluate:async()=>JSON.stringify({tabs:inventory}),isClosed:()=>false};
  const context={pages:()=>[anchor,a,b,personal],__jarvisOwnedTabs:{pages:[],active:null,anchor}};
  const seed={context:()=>context};
  let result=await extensionAction(seed,'/tabs',{action:'list'});
  assert.deepEqual(result.pages.map(p=>p.tabId),[11,12]);
  assert.equal(result.activeIndex,0);
  // A tab moved out is removed on the next action; duplicate URLs never merge.
  inventory=[{tabId:12,active:true}];
  result=await extensionAction(seed,'/status',{});
  assert.deepEqual(result.pages.map(p=>p.tabId),[12]);
  assert.equal(result.activeIndex,0);
  // Reconnect loses in-memory ownership, but the same Chrome inventory restores it.
  context.__jarvisOwnedTabs={pages:[],active:null,anchor};
  result=await extensionAction(seed,'/tabs',{action:'list'});
  assert.deepEqual(result.pages.map(p=>p.tabId),[12]);
  inventory=[];
  assert.deepEqual(await extensionAction(seed,'/status',{}),{activeIndex:-1,pages:[]});
});
test('failed inventory discovery does not create, navigate, or close tabs',async()=>{
  const anchor={evaluate:async()=>{throw new Error('Connection anchor identity mismatch');}};
  const context={pages:()=>[],__jarvisOwnedTabs:{pages:[],active:null,anchor},newPage:()=>{throw new Error('must not create');}};
  await assert.rejects(extensionAction({context:()=>context},'/open',{url:'about:blank'}),/anchor identity/);
});
test('unsafe navigation is rejected before a tab is created',async()=>{
  const seed={context:()=>({newPage(){throw new Error('unexpected creation');}})};
  await assert.rejects(extensionAction(seed,'/open',{url:'javascript:alert(1)'}),/Only HTTP/);
});
