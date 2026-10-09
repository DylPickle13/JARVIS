// Offline child process: real pinned MCP/SDK and fake pages or fake WebSocket.
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OperationLedger } from './operation-ledger.mjs';
import { ExtensionBrowserBackend } from './extension-browser-backend.mjs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { createConnection } from '@playwright/mcp';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { installExecutionObserver, registerExecution, OBSERVER_KEY } from './execution-observer.mjs';
const require = createRequire(import.meta.url);
const deferred = () => {let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const code='async page => { await page.work(); return {tabId:7,valueVerified:true}; }';

async function runner(mode) {
  const started=deferred(), work=deferred(), drained=deferred();
  let executions=0;
  const page=new EventEmitter();
  Object.assign(page,{consoleMessages:async()=>[],pageErrors:async()=>[],requests:async()=>[],
    title:async()=> 'Offline fixture',url:()=> 'https://fixture.invalid',evaluate:async(fn,arg)=>fn(arg),
    work:async()=>{executions++;started.resolve();await work.promise;}});
  const context=new EventEmitter();
  Object.assign(context,{pages:()=>[page],browser:()=>null,debugger:{pausedDetails:()=>null}});
  const server=await createConnection({snapshot:{mode:'none'},codegen:'none',timeouts:{settle:0}},async()=>context);
  const client=new Client({name:'Offline receipt test',version:'1'});
  client.onerror=()=>{};
  const [ct,st]=InMemoryTransport.createLinkedPair();
  await server.connect(st);await client.connect(ct);
  const {tools}=await client.listTools();
  const name=tools.find(t=>t.name==='browser_run_code_unsafe').name;
  const warm=await client.callTool({name,arguments:{code:'async () => null'}});
  assert(!warm.isError, JSON.stringify(warm));
  const observed=registerExecution(code,{id:'test-operation',onChange:s=>{if(s.quiescent)drained.resolve(s);}});
  const request=client.callTool({name,arguments:{code}},undefined,{timeout:mode==='deadline'?25:1500}).catch(e=>e);
  await started.promise;
  if(mode==='early-error') process.emit('unhandledRejection',new Error('Synthetic unrelated code-runner failure'),Promise.resolve());
  const response=await request;
  if(mode==='deadline') assert.equal(response.code,-32001);
  else assert.equal(response.isError,true);
  assert.equal(observed.snapshot().snippetTerminal,false);
  assert.equal(observed.snapshot().quiescent,false,'RPC error is not execution completion');
  work.resolve();
  const terminal=await drained.promise;
  assert.equal(executions,1);assert.equal(terminal.outcome,'completed');
  assert.equal(terminal.valueVerified,true);assert.equal(terminal.resultTabId,7);
  observed.retire();
  await client.close();await server.close();
  return {mode,executions,terminal};
}

async function relay(mode) {
  const source=readFileSync(require.resolve('playwright-core/lib/coreBundle'),'utf8');
  const begin=source.indexOf('ExtensionConnection = class {');
  const end=source.indexOf('\n    };',begin);
  assert(begin>0&&end>begin);
  const Connection=vm.runInNewContext('('+source.slice(begin+'ExtensionConnection = '.length,end+6).replace(/;$/,'')+')',{
    globalThis:{[OBSERVER_KEY]:installExecutionObserver()},ws3:{OPEN:1},debugLogger2:()=>{},
  });
  const socket=new EventEmitter();Object.assign(socket,{readyState:1,send:()=>{},close:()=>{}});
  const connection=new Connection(socket);
  const observed=registerExecution(code,{id:'relay-test'});
  const hooks=installExecutionObserver();let command;
  await hooks.request(code,()=>hooks.snippet(code,async()=>{command=connection.send('Input.dispatchMouseEvent',{});command.catch(()=>{});return {tabId:7};}));
  assert.equal(observed.snapshot().snippetTerminal,true);
  assert.equal(observed.snapshot().pending,1);assert.equal(observed.snapshot().quiescent,false);
  if(mode==='relay-generation') {
    const nextSocket=new EventEmitter();Object.assign(nextSocket,{readyState:1,send:()=>{},close:()=>{}});
    const next=new Connection(nextSocket);const other=next.send('Input.dispatchMouseEvent',{});
    next._handleParsedMessage({id:1,result:{}});await other;
    connection._handleParsedMessage({id:1,result:{}});await command;
    assert.equal(observed.snapshot().pending,0);assert.equal(observed.snapshot().unknown,true);
    assert.equal(observed.snapshot().quiescent,false);assert.throws(()=>observed.retire(),/proof missing/);
  } else if(mode==='relay-pending') {
    connection._handleParsedMessage({id:1,result:{}});await command;
    assert.equal(observed.snapshot().quiescent,true);
    connection._handleParsedMessage({id:1,result:{}});
    assert.equal(observed.snapshot().pending,0);observed.retire();
  } else {
    connection._dispose();await command.catch(()=>{});
    assert.equal(observed.snapshot().pending,0);assert.equal(observed.snapshot().unknown,true);
    assert.equal(observed.snapshot().quiescent,false);
    assert.throws(()=>observed.retire(),/proof missing/);
    connection._handleParsedMessage({id:1,result:{}});
    assert.equal(observed.snapshot().quiescent,false,'late/duplicate reply cannot clear transport-loss evidence');
  }
  return {mode,terminal:observed.snapshot()};
}

async function backend(mode) {
  const dir=await mkdtemp(join(tmpdir(),'browser-recovery-fixture-'));
  const started=deferred(), work=deferred();let executions=0, preparations=0;
  const inventory={pages:[{tabId:7},{tabId:8}]};
  const makePage=id=>{
    const p=new EventEmitter();
    Object.assign(p,{consoleMessages:async()=>[],pageErrors:async()=>[],requests:async()=>[],
      title:async()=> 'Offline fixture',url:()=> 'https://fixture.invalid',isClosed:()=>false,
      evaluate:async(fn,arg)=>typeof fn==='string'?JSON.stringify({tabId:id}):fn(arg),
      bringToFront:async()=>{},context:()=>context,
      mouse:{wheel:async()=>{executions++;started.resolve();await work.promise;}},
      locator:()=>({boundingBox:async()=>null,click:async()=>{executions++;started.resolve();await work.promise;},
        innerText:async()=> 'Synthetic fixture observation'})});
    const element={tagName:'TEXTAREA',value:'',disabled:false,readOnly:false,isConnected:true,selectionStart:0,selectionEnd:0};
    const target={evaluate:async(fn,arg)=>vm.runInNewContext('('+fn.toString()+')(element,arg)',{element,arg,document:{activeElement:element}}),
      fill:async text=>{executions++;started.resolve();await work.promise;element.value=mode==='backend-partial'?text.slice(0,2):text;}};
    p.evaluateHandle=async()=>({asElement:()=>target,dispose:async()=>{}});p.fixtureElement=element;
    return p;
  };
  const context=new EventEmitter();const pages=[makePage(7),makePage(8)],anchor=makePage(20);
  anchor.url=()=> 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2';
  anchor.evaluate=async(fn,arg)=>typeof fn==='string'?JSON.stringify({tabs:inventory.pages.map(t=>({...t,active:t.tabId===7}))}):fn(arg);
  Object.assign(context,{pages:()=>[anchor,...pages],browser:()=>null,debugger:{pausedDetails:()=>null}});
  const server=await createConnection({snapshot:{mode:'none'},codegen:'none',timeouts:{settle:0}},async()=>context);
  const client=new Client({name:'Offline recovery backend test',version:'1'});client.onerror=()=>{};
  const [ct,st]=InMemoryTransport.createLinkedPair();await server.connect(st);await client.connect(ct);
  const {tools}=await client.listTools();const name=tools.find(t=>t.name==='browser_run_code_unsafe').name;
  assert(!(await client.callTool({name,arguments:{code:'async () => null'}})).isError);
  const ledger=new OperationLedger({path:join(dir,'journal','operations.json')});
  const b=new ExtensionBrowserBackend({recoveryLedger:ledger,recoveryMode:mode==='backend-observe'?'observe-only':'verified-only',drainGraceMs:mode==='backend-budget'?10:2000});
  b.diagnostic=()=>{};b.window={windowId:99,connectionTabId:20,connectionMode:'jarvis-background-native-v1'};
  b.connectionGeneration=1;b.connected=true;
  if(mode==='backend-stock') b.window.connectionMode='stock';
  b.client={callTool:(args,unused,options)=>{
    // Only the fake client's clock is shortened. Production policy stays 15 s.
    if(args.arguments.code.includes('"/scroll"')||args.arguments.code.includes('"/click"')||args.arguments.code.includes('"/type"')) {
      assert.equal(options.timeout,args.arguments.code.includes('"/scroll"')?15000:args.arguments.code.includes('"/type"')?30000:150000);
      return client.callTool(args,unused,{...options,timeout:25});
    }
    return client.callTool(args,unused,options);
  }};b.runTool=name;
  b.prepare=async()=>{preparations++;b.connected=true;return inventory;};
  await b.handle('/tabs',{action:'switch',tabId:7},'A');
  await b.handle('/tabs',{action:'switch',tabId:8},'B');
  const action=mode==='backend-click'?'/click':['backend-type','backend-partial'].includes(mode)?'/type':'/scroll';
  const request=b.handle(action,action==='/click'?{selector:'#synthetic'}:action==='/type'?{text:'X'.repeat(5000),clear:true,delayMs:0}:{},'A').catch(e=>e);
  await started.promise;
  const queued=b.handle('/click',{selector:'#synthetic'},'B').catch(e=>e);
  assert.match((await request).message,/pending|supervised/);
  assert.match((await queued).message,/pending|quarantined|Stale/);
  const count=preparations;
  const status=await b.handle('/status',{},'B');
  assert.equal(preparations,count,'cached status must not access preflight');
  assert(status.daemon.inventoryStale);assert.equal(status.daemon.recovery.operations.some(r=>r.action===action),false,'another client cannot see the original outcome');
  if(mode==='backend-release') await b.handle('/close',{all:true},'A');
  if(mode==='backend-expired') b.sessions.leases.get(7).expiresAt=0;
  if(mode==='backend-window') b.window.windowId=100;
  if(mode==='backend-generation') b.connectionGeneration=2;
  if(mode==='backend-tab') inventory.pages=inventory.pages.filter(t=>t.tabId!==7);
  if(mode==='backend-budget') await new Promise(r=>setTimeout(r,25));
  work.resolve();
  const limit=Date.now()+2000;
  while(Date.now()<limit) {
    await new Promise(r=>setTimeout(r,5));await ledger.flush();
    if(b.recoveryState==='healthy'||b.recoveryState==='blocked-needs-supervision') break;
  }
  // Observe-only/budget states may predate the terminal receipt; wait for it too.
  while(b.recoveryOperation&&!b.recoveryOperation.observed.snapshot().snippetTerminal&&Date.now()<limit) await new Promise(r=>setTimeout(r,5));
  await ledger.flush();
  const blocked=['backend-observe','backend-budget','backend-window','backend-tab','backend-generation','backend-stock'].includes(mode);
  assert.equal(!!b.quarantine,blocked);assert.equal(executions,1,'no automatic mutation replay');
  if(blocked) {
    assert.equal(b.recoveryState,'blocked-needs-supervision');
    const restored=new OperationLedger({path:ledger.path});await restored.load();assert(restored.unresolved().length>0);
  } else {
    assert.equal(b.recoveryState,'healthy');assert.equal(b.sessions.session('B').uncertain,false);
    assert.equal(b.sessions.lease(8).owner,'B');
    if(mode==='backend-click'||mode==='backend-partial') {
      assert.equal(b.sessions.session('A').uncertain,true);
      const result=await b.handle('/extract',{},'A');assert.equal(result.text,'Synthetic fixture observation');
      await assert.rejects(b.handle('/click',{selector:'#synthetic'},'A'),/uncertain outcome/);
    } else if(mode==='backend-release') assert.equal(b.sessions.sessions.has('A'),false,'late receipt must not resurrect a closed session');
    else if(mode==='backend-expired') {
      assert.equal(b.sessions.lease(7),undefined);
      await assert.rejects(b.handle('/scroll',{},'A'),/released or expired|uncertain outcome/);
    } else {
      assert.equal(b.sessions.session('A').uncertain,false);
      if(mode==='backend-type') assert.equal(pages[0].fixtureElement.value,'X'.repeat(5000));
    }
  }
  await client.close();await server.close();await ledger.close();await rm(dir,{recursive:true,force:true});
  return {mode,executions,state:b.recoveryState};
}

async function crashLedger(phase,path) {
  const ledger=new OperationLedger({path});
  const r=await ledger.begin({action:'/type',sessionId:'A',tabId:7,windowId:99,generation:1});
  if(phase!=='registered') {
    await ledger.receipt(r,{id:r.id,revision:1,requestEntered:true,requestTerminal:false,snippetEntered:true,snippetTerminal:false,outcome:'pending',valueVerified:false,resultTabId:null,pending:0,unknown:false});
    await ledger.save(); // Explicit fault-injection checkpoint, not per-command production I/O.
    if(phase!=='handler-entered') {
      await ledger.receipt(r,{id:r.id,revision:2,requestEntered:true,requestTerminal:phase!=='snippet-terminal',snippetEntered:true,snippetTerminal:true,outcome:phase==='unknown'?'failed':'completed',valueVerified:phase!=='unknown',resultTabId:7,pending:0,unknown:phase==='unknown'});
      await ledger.save();
      if(phase==='resolved') await ledger.state(r,'resolved');
      if(phase==='unknown') await ledger.state(r,'blocked');
    }
  }
  process.exit(23); // Abrupt exit at a DURABLE journal boundary; no Chrome exists.
}

try {
  const mode=process.argv[2];
  if(mode==='crash-fixture') await crashLedger(process.argv[3],process.argv[4]);
  const result=mode.startsWith('backend-')?await backend(mode):mode.startsWith('relay-')?await relay(mode):await runner(mode);
  console.log(JSON.stringify(result));
  process.exit(0); // Dispose stock runner's irrelevant settle timers in this child.
} catch(error) {console.error(error);process.exit(1);}
