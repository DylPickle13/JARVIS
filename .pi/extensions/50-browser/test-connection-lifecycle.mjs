import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { extensionAction, ExtensionBrowserBackend } from './extension-browser-backend.mjs';

const url='chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2';
function anchorFixture({ foreign=false, outside=false, pendingGroup=false, wrongId=false }={}) {
  const events=[];
  let retired=false, cleaned=false, ticks=0;
  const current={id:20,windowId:7,groupId:pendingGroup ? -1 : 2,url};
  const old={id:10,windowId:7,groupId:1,url};
  const work={id:11,windowId:7,groupId:1,url:'https://work.test'};
  const tabs=[current,old,work];
  const connections=[
    {id:2,clientName:'JARVIS Browser',connectedTabIds:[20]},
    {id:1,clientName:foreign ? 'Other client' : 'JARVIS Browser',connectedTabIds:outside ? [10,11,99] : [10,11]},
  ];
  const sandbox={
    location:{hash:'#jarvis-automation-anchor-v2'}, document:{},
    Date:foreign || outside ? {now:()=>8000*++ticks} : Date,
    setTimeout:fn=>{
      events.push('wait');
      if(retired) {cleaned=true;old.groupId=work.groupId=-1;}
      fn();
    },
    chrome:{
      runtime:{sendMessage:async message=>{
        if(message.type==='getConnectionStatus') return {connections:retired ? connections.slice(0,1) : connections};
        assert.equal(message.type,'disconnect');
        assert.equal(message.connectionId,1,'must not retire the new connection');
        events.push('retire-old');retired=true;
        return {success:true};
      }},
      tabs:{
        getCurrent:async()=>wrongId ? {...current,id:99} : current,
        query:async({windowId})=>{assert.equal(windowId,7);return tabs;},
        remove:async id=>{
          assert.equal(id,10,'only the obsolete internal anchor may close');
          assert.equal(cleaned,true,'wait for old asynchronous debugger/group cleanup');
          events.push('close-old');
        },
        update:async()=>assert.fail('pin/unpin must never run during connection preparation'),
      },
      debugger:{getTargets:async()=>[
        {tabId:20,attached:true},
        {tabId:10,attached:!cleaned},
        {tabId:11,attached:!cleaned},
      ]},
    },
  };
  const anchor={url:()=>url,isClosed:()=>false,
    evaluate:(fn,body)=>vm.runInNewContext(`(${fn.toString()})(${JSON.stringify(body)})`,sandbox)};
  const context={pages:()=>[anchor]};
  return {events, run:()=>extensionAction({context:()=>context},'/prepare-anchor',{windowId:7,connectionTabId:20})};
}

test('fresh anchor retires only old bridge group, awaits cleanup, preserves work tabs',async()=>{
  const f=anchorFixture();await f.run();
  assert.deepEqual(f.events,['retire-old','wait','close-old']);
});
test('ungrouped fresh anchor does not mistake pending old attachments for its own group',async()=>{
  const f=anchorFixture({pendingGroup:true});await f.run();
  assert.deepEqual(f.events,['retire-old','wait','close-old']);
});
test('different client or bridge group spanning another window is never disconnected',async()=>{
  for(const options of [{foreign:true},{outside:true}]) {
    const f=anchorFixture(options);
    await assert.rejects(f.run(),/refusing competing debugger ownership/);
    assert(!f.events.includes('retire-old'));
    assert(!f.events.includes('close-old'));
  }
});
test('wrong anchor identity fails before any cleanup',async()=>{
  const f=anchorFixture({wrongId:true});
  await assert.rejects(f.run(),/identity mismatch/);
  assert.deepEqual(f.events,[]);
});
test('native connection never invokes AppleScript verification or focus restoration', async()=>{
  const window={windowId:7,connectionTabId:20,connectionMode:'jarvis-background-native-v1',previousFrontWindowId:99,previousFrontApp:'com.example.editor'};
  for (const name of ['assertWindow','restoreConnectionFocus']) {
    const source=ExtensionBrowserBackend.prototype[name].toString().replace(`async ${name}(`,'async function(');
    const run=vm.runInNewContext(`(${source})`,{execFileAsync:()=>assert.fail('Native mode must not send AppleEvents')});
    await run.call({window});
  }
  // Skipping AppleEvents is not skipping identity checks: the relay inventory
  // still verifies the anchor/window on every action (covered by backend tests).
});

test('background-only handshake denial is not retried as a transport failure', async()=>{
  const backend = new ExtensionBrowserBackend({});
  let attempts = 0;
  backend.prepare = async()=>{
    attempts++;
    throw new Error('Background-only policy: fresh Chrome handshake blocked; ask sir before supervised reconnection');
  };
  backend.reset = async()=>assert.fail('Policy refusal must not trigger reconnection');
  await assert.rejects(backend.prepareWithRecovery(), /Background-only policy/);
  assert.equal(attempts, 1);
});

test('prepare detects a silently replaced MCP connection despite connected=true',async t=>{
  const dir=await mkdtemp(join(tmpdir(),'jarvis-browser-epoch-'));
  t.after(()=>rm(dir,{recursive:true,force:true}));
  const windowPath=join(dir,'window.json');
  const backend=new ExtensionBrowserBackend({windowPath});
  backend.init=backend.restoreConnectionFocus=async()=>{};
  let epoch=10;
  const prepared=[];
  backend.callAction=async(path,body)=>{
    if(path==='/connect') await writeFile(windowPath,JSON.stringify({windowId:7,connectionTabId:epoch}));
    else if(path==='/prepare-anchor') prepared.push(body.connectionTabId);
    else assert.equal(path,'/status');
    return {pages:[{tabId:50}]};
  };
  backend.assertWindow=async()=>assert.equal(backend.window.connectionTabId,epoch);
  await backend.prepare();
  assert.equal(backend.connected,true);
  assert.equal(backend.connectionGeneration,1);
  backend.connectedAt='stale-generation-time';
  epoch=11;
  await backend.prepare();
  assert.deepEqual(prepared,[10,11]);
  assert.equal(backend.preparedConnectionTabId,11);
  assert.equal(backend.connectionGeneration,2);
  assert.notEqual(backend.connectedAt,'stale-generation-time');
});
