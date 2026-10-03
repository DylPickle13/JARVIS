import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { verifiedType } from './verified-input.mjs';
import { actionDeadlineMs } from './action-policy.mjs';
import { ExtensionBrowserBackend } from './extension-browser-backend.mjs';

function inputFixture({value='old',tag='TEXTAREA',type='text',start=0,end=0,transform=x=>x,shadow=false}={}) {
  const events=[];
  const e={value,tagName:tag,type,isConnected:true,selectionStart:start,selectionEnd:end};
  const document={activeElement:shadow ? {shadowRoot:{activeElement:e}} : e};
  const evaluate=(fn,arg)=>vm.runInNewContext(`(${fn})(element,arg)`,{element:e,arg,document});
  const target={evaluate,fill:async(text,options)=>{events.push(['fill',text.length,options.timeout]);e.value=transform(text.replace(/\r\n?/g,'\n'));}};
  const handle={asElement:()=>target,dispose:async()=>events.push(['dispose'])};
  const page={
    evaluateHandle:async fn=>{assert.equal(vm.runInNewContext(`(${fn})()`,{document}),e);return handle;},
    locator:()=>({focus:async()=>events.push(['focus'])}),
    keyboard:{type:async(text,{delay})=>{events.push(['keyboard',text.length,delay]);e.value=transform(e.value.slice(0,e.selectionStart)+text+e.value.slice(e.selectionEnd));}},
  };
  return {page,e,document,events};
}

test('long explicit zero-delay replacement is one bounded fill and verifies full value',async()=>{
  const f=inputFixture();
  const result=await verifiedType(f.page,{text:'x'.repeat(9000),clear:true,delayMs:0},10000);
  assert.equal(result.typedCharacters,9000);assert.equal(result.valueVerified,true);assert.equal(result.inputMethod,'fill');
  assert.deepEqual(f.events,[['fill',9000,10000],['dispose']]);
});
test('default short typing delay and selection replacement remain unchanged',async()=>{
  const f=inputFixture({value:'abc',start:1,end:2});
  await verifiedType(f.page,{text:'X'},10000);
  assert.equal(f.e.value,'aXc');assert.deepEqual(f.events,[['keyboard',1,20],['dispose']]);
});
test('explicit slow typing remains available and verified',async()=>{
  const f=inputFixture({value:'',start:0,end:0});
  const result=await verifiedType(f.page,{text:'ab',delayMs:80},10000);
  assert.equal(result.inputMethod,'keyboard');assert.equal(result.valueVerified,true);
  assert.deepEqual(f.events,[['keyboard',2,80],['dispose']]);
});
test('oversized default/slow/unbounded append fails before any focus, clear or input',async()=>{
  for(const body of [{text:'x'.repeat(4539),clear:true},{text:'x'.repeat(4539),delayMs:0},{text:'x'.repeat(40),delayMs:1000,clear:true}]) {
    const f=inputFixture();await assert.rejects(verifiedType(f.page,{selector:'#field',...body},10000),/safe action budget/);
    assert.deepEqual(f.events,[]);assert.equal(f.e.value,'old');
  }
});
test('empty clear, multiline normalization and focused shadow-DOM input are verified',async()=>{
  for(const text of ['', 'one\r\ntwo']) {
    const f=inputFixture({shadow:true});const result=await verifiedType(f.page,{text,clear:true,delayMs:0},10000);
    assert.equal(f.e.value,text.replace(/\r\n/g,'\n'));assert.equal(result.valueVerified,true);
  }
});
test('site truncation/rewriting fails verification without retry or value leakage',async()=>{
  const f=inputFixture({transform:x=>x.slice(0,2)});
  await assert.rejects(verifiedType(f.page,{text:'private-text',clear:true,delayMs:0},10000),e=>/JARVIS_INPUT_UNCERTAIN/.test(e.message)&&!e.message.includes('private-text'));
  assert.equal(f.events.filter(e=>e[0]==='fill').length,1);
});
test('focus loss after input is uncertain, never retried',async()=>{
  const f=inputFixture({transform:x=>{f.document.activeElement={};return x;}});
  await assert.rejects(verifiedType(f.page,{text:'new',clear:true,delayMs:0},10000),/target focus changed/);
  assert.equal(f.events.filter(e=>e[0]==='fill').length,1);
});
test('disabled input and unknowable append range fail without writing',async()=>{
  const f=inputFixture();f.e.disabled=true;
  await assert.rejects(verifiedType(f.page,{text:'new',clear:true,delayMs:0},10000),/editable/);
  const g=inputFixture({tag:'INPUT',type:'email',start:null,end:null});
  await assert.rejects(verifiedType(g.page,{text:'new'},10000),/insertion range/);
  for(const x of [f,g]) assert.equal(x.events.some(e=>['fill','keyboard'].includes(e[0])),false);
});

async function backendFixture() {
  const b=new ExtensionBrowserBackend({});
  const inventory={pages:[{tabId:7},{tabId:8}]};
  b.connected=true;b.connectedAt='old-generation';b.window={windowId:99};
  b.prepare=async()=>{b.connected=true;return inventory;};
  b.callAction=async()=>inventory;
  await b.handle('/tabs',{action:'switch',tabId:7},'A');
  await b.handle('/tabs',{action:'switch',tabId:8},'B');
  return {b,inventory};
}

test('settled local action timeout fences only its owner; queued other session proceeds',async()=>{
  const {b,inventory}=await backendFixture();
  const calls=[];
  b.callAction=async(path,body)=>{calls.push([path,body.targetTabId]);if(path==='/click') throw new Error('TimeoutError: locator.click: Timeout exceeded');return inventory;};
  const results=await Promise.allSettled([b.handle('/click',{},'A'),b.handle('/type',{text:'B'},'B')]);
  assert.equal(results[0].status,'rejected');assert.equal(results[1].status,'fulfilled');
  assert.deepEqual(calls,[['/click',7],['/type',8]]);assert.equal(b.resetCount,0);
  assert.equal(b.sessions.session('A').uncertain,true);assert.equal(b.sessions.session('B').uncertain,false);
  assert.equal(b.lastFailure.kind,'action-timeout');
});
test('unacknowledged deadline blocks queued session, reselection and reset even if old work finishes late',async()=>{
  const {b}=await backendFixture();
  let reject,started,completeLate;
  const lateTargets=[];
  const stillRunning=new Promise(r=>completeLate=r).then(()=>lateTargets.push(7));
  const didStart=new Promise(r=>started=r);
  const calls=[];
  b.callAction=async(path,body)=>{calls.push([path,body.targetTabId]);started();return new Promise((_,r)=>reject=r);};
  const first=b.handle('/scroll',{},'A');
  const observed=first.catch(e=>e);
  await didStart;
  const second=b.handle('/type',{text:'B'},'B');
  const secondObserved=second.catch(e=>e);
  reject(Object.assign(new Error('MCP error -32001: Request timed out'),{code:-32001}));
  assert.match((await observed).message,/Request timed out/);assert.match((await secondObserved).message,/quarantined/);
  completeLate(); // Underlying work is independent of the rejected client request.
  await stillRunning;
  assert.deepEqual(lateTargets,[7]);
  await assert.rejects(b.handle('/tabs',{action:'switch',tabId:8},'B'),/quarantined/);
  await assert.rejects(b.reset(),/quarantined/);
  assert.deepEqual(calls,[['/scroll',7]]);assert.equal(b.resetCount,0);
  assert.equal(b.sessions.session('A').uncertain,true);assert.equal(b.sessions.session('B').uncertain,true);
  const status=await b.handle('/status',{},'B');
  assert.equal(status.connected,false);assert.equal(status.daemon.quarantined,true);assert.equal(status.daemon.inventoryStale,true);
  assert.equal(status.daemon.lastFailure.kind,'unacknowledged-deadline');
  await b.handle('/tabs',{action:'release',tabId:8},'B');
  await b.handle('/close',{all:true},'A');
  assert.deepEqual(calls,[['/scroll',7]]);
});
test('stale quarantine inventory cannot prune leases created after its snapshot',async()=>{
  const {b}=await backendFixture();
  b.quarantine={reason:'execution-not-acknowledged'};b.connected=false;
  b.lastInventory={pages:[]};b.sessions.invalidate();
  const status=await b.handle('/status',{},'A');
  assert.equal(status.selectionMissing,false);assert.equal(status.needsReselect,true);
  assert.equal(b.sessions.lease(7).owner,'A');assert.equal(b.sessions.lease(8).owner,'B');
  await b.handle('/tabs',{action:'release',tabId:7},'A');
  assert.equal(b.sessions.lease(7),undefined);assert.equal(b.sessions.lease(8).owner,'B');
  await assert.rejects(b.sessions.handle('/click',{},'A',()=>assert.fail('no Chrome'),{pages:[]},{reconcile:false}),/Stale inventory/);
});

test('preflight request timeout quarantines without retrying an unresolved operation',async()=>{
  const {b}=await backendFixture();let calls=0;
  b.prepare=async()=>{calls++;throw Object.assign(new Error('Request timed out'),{code:-32001});};
  await assert.rejects(b.handle('/status',{},'A'),/Request timed out/);
  assert.equal(calls,1);assert.equal(b.resetCount,0);assert.ok(b.quarantine);
});
test('all actual resets remain visible after a successful status request',async()=>{
  const {b,inventory}=await backendFixture();
  b.callAction=async()=>{throw new Error('transport closed after dispatch');};
  await assert.rejects(b.handle('/click',{},'A'),/transport closed/);
  assert.equal(b.resetCount,1);assert.equal(b.connectedAt,null);
  const status=await b.handle('/status',{},'B');
  assert.equal(status.daemon.lastError,'');assert.equal(status.daemon.resetCount,1);
  assert.equal(status.daemon.lastReset.reason,'action-transport-error');
  assert.equal(status.daemon.lastFailure.action,'/click');assert.notEqual(status.daemon.connectedAt,'old-generation');
  assert.deepEqual(status.pages.map(p=>p.tabId),inventory.pages.map(p=>p.tabId));
});
test('real fixed actions serialize simultaneous long replacements into independent leased pages',async()=>{
  const inputs=[inputFixture(),inputFixture()];
  const activations=[];
  const pages=inputs.map((f,i)=>Object.assign(f.page,{
    isClosed:()=>false,url:()=> 'https://fixture.test',title:async()=> 'Fixture',
    evaluate:async()=>JSON.stringify({tabId:7+i}),bringToFront:async()=>activations.push(7+i),
  }));
  const anchor={isClosed:()=>false,url:()=> 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2',
    evaluate:async()=>JSON.stringify({tabs:[{tabId:7,active:true},{tabId:8,active:false}]})};
  const context={pages:()=>[anchor,...pages]};
  const seed={context:()=>context};
  const b=new ExtensionBrowserBackend({});
  b.prepare=async()=>{b.connected=true;return {pages:[{tabId:7},{tabId:8}]};};
  b.diagnostic=()=>{};
  b.client={callTool:async(args)=>{
    // Execute the exact serialized MCP wrapper in a separate lexical context.
    const run=vm.runInNewContext(`(${args.arguments.code})`);
    const result=await run(seed);
    return {content:[{type:'text',text:'### Result\n'+JSON.stringify(result)}]};
  }};
  await b.handle('/tabs',{action:'switch',tabId:7},'A');
  await b.handle('/tabs',{action:'switch',tabId:8},'B');
  activations.length=0;
  const values=['A'.repeat(5000),'B'.repeat(6000)];
  const results=await Promise.all(['A','B'].map((id,i)=>b.handle('/type',{text:values[i],clear:true,delayMs:0},id)));
  assert.deepEqual(activations,[7,8]);
  assert.deepEqual(inputs.map(f=>f.e.value),values);
  assert.deepEqual(results.map(r=>r.tabId),[7,8]);
  assert(results.every(r=>r.valueVerified&&r.inputMethod==='fill'));
  await assert.rejects(b.handle('/tabs',{action:'switch',tabId:7},'B'),/controlled by another/);
  assert.deepEqual(inputs.map(f=>f.e.value),values);
});

test('diagnostics omit input, selector, URL and raw exception content',async()=>{
  const b=new ExtensionBrowserBackend({});const events=[];
  b.diagnostic=(event,fields)=>events.push({event,...fields});
  b.client={callTool:async()=>{throw new Error('private-site-value');}};
  await assert.rejects(b.callAction('/type',{targetTabId:8,text:'private-field',selector:'#private-selector',url:'https://private.test'}),/private-site-value/);
  const output=JSON.stringify(events);
  for(const secret of ['private-site-value','private-field','private-selector','private.test']) assert(!output.includes(secret));
  assert.equal(events[0].tabId,8);assert.equal(events[1].outcome,'action-or-preflight-error');
});

test('bulk/scroll request deadlines reach MCP; no schema or focus workaround is introduced',async()=>{
  assert.equal(actionDeadlineMs('/scroll'),15000);assert.equal(actionDeadlineMs('/type',{clear:true,delayMs:0}),30000);
  const b=new ExtensionBrowserBackend({});let received;
  b.client={callTool:async(args,unused,options)=>{received={args,options};return {content:[{type:'text',text:'### Result\n{}'}]};}};
  await b.callAction('/scroll',{});
  assert.equal(received.options.timeout,15000);
  assert.match(received.args.arguments.code,/verifiedType/);
});
