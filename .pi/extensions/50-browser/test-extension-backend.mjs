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
test('unsafe navigation is rejected before a tab is created',async()=>{
  const seed={context:()=>({newPage(){throw new Error('unexpected creation');}})};
  await assert.rejects(extensionAction(seed,'/open',{url:'javascript:alert(1)'}),/Only HTTP/);
});
