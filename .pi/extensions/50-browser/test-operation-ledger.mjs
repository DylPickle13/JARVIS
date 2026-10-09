import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, writeFile, chmod, symlink, mkdir, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OperationLedger } from './operation-ledger.mjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const exec=promisify(execFile);
import { ExtensionBrowserBackend } from './extension-browser-backend.mjs';
const meta={action:'/type',sessionId:'A',tabId:7,windowId:99,generation:1};
const complete=r=>({id:r.id,revision:r.revision+1,requestEntered:true,requestTerminal:true,
  snippetEntered:true,snippetTerminal:true,outcome:'completed',valueVerified:true,resultTabId:7,pending:0,unknown:false});
async function fixture(t) {
  const dir=await mkdtemp(join(tmpdir(),'browser-ledger-'));
  const path=join(dir,'private','operations.json');const ledger=new OperationLedger({path});
  t.after(async()=>{await ledger.close();await rm(dir,{recursive:true,force:true});});
  await ledger.load();return {dir,path,ledger};
}

test('journal precedes dispatch, uses owner-only storage, and survives a new boot',async t=>{
  const {path,ledger}=await fixture(t);const r=await ledger.begin(meta);
  assert.equal((await stat(path)).mode&0o777,0o600);
  const restored=new OperationLedger({path});await restored.load();
  assert.equal(restored.unresolved()[0].id,r.id);assert.notEqual(restored.boot,ledger.boot);
  await assert.rejects(restored.begin(meta),/Unresolved/);
});
test('proof requires the latest receipt revision to be durable',async t=>{
  const {ledger}=await fixture(t);const r=await ledger.begin(meta);
  const write=ledger.receipt(r,complete(r));assert.equal(ledger.proven(r),false);
  await write;assert.equal(ledger.proven(r),true);await ledger.state(r,'resolved');
  assert.equal(ledger.unresolved().length,0);await ledger.begin(meta);
});
test('incomplete snippet, incomplete outer handler, pending command, or unknown transport cannot resolve',async()=>{
  for(const override of [{snippetTerminal:false},{requestTerminal:false},{pending:1},{unknown:true}]) {
    const ledger=new OperationLedger();const r=await ledger.begin(meta);
    await ledger.receipt(r,{...complete(r),...override});assert.equal(ledger.proven(r),false);
    await assert.rejects(ledger.state(r,'resolved'),/proof/);
  }
});
test('old, duplicate and foreign receipts cannot alter current evidence',async()=>{
  const ledger=new OperationLedger();const r=await ledger.begin(meta);
  await ledger.receipt(r,{...complete(r),id:'unrelated'});assert.equal(r.revision,0);
  const s=complete(r);await ledger.receipt(r,s);
  await ledger.receipt(r,{...s,unknown:true,pending:10});assert.equal(ledger.proven(r),true);
});
test('unknown transport evidence is sticky across higher-revision receipts',async()=>{
  const ledger=new OperationLedger();const r=await ledger.begin(meta);
  await ledger.receipt(r,{...complete(r),unknown:true});
  await ledger.receipt(r,complete(r));assert.equal(r.unknown,true);assert.equal(ledger.proven(r),false);
});
test('command telemetry does not fsync the whole journal for every round trip',async()=>{
  const ledger=new OperationLedger();let writes=0;const save=ledger.save.bind(ledger);
  ledger.save=()=>{writes++;return save();};const r=await ledger.begin(meta);
  for(let i=0;i<100;i++) await ledger.receipt(r,{...complete(r),requestTerminal:false,snippetTerminal:false,outcome:'pending',pending:i%2});
  assert.equal(writes,1);assert.equal(ledger.proven(r),false);
  await ledger.receipt(r,complete(r));assert.equal(writes,2);assert.equal(ledger.proven(r),true);
});
test('blocked state remains unresolved through restart even with execution proof',async t=>{
  const {path,ledger}=await fixture(t);const r=await ledger.begin(meta);
  await ledger.receipt(r,complete(r));await ledger.state(r,'blocked');
  const restored=new OperationLedger({path});await restored.load();assert.equal(restored.unresolved()[0].state,'blocked');
});
test('normal completion permits bounded history without expiring unresolved evidence',async()=>{
  const ledger=new OperationLedger({historyLimit:2});
  for(let i=0;i<5;i++){const r=await ledger.begin(meta);await ledger.receipt(r,complete(r));await ledger.state(r,'resolved');}
  assert.equal(ledger.records.size,2);const pending=await ledger.begin(meta);
  assert(ledger.unresolved().some(r=>r.id===pending.id));assert.equal(ledger.records.size,3);
});
test('journal omits bodies, values, paths, selectors, URLs, and raw exceptions',async t=>{
  const {path,ledger}=await fixture(t);await ledger.begin({...meta,text:'secret-text',url:'https://private.invalid',selector:'#private-selector',path:'/private/file',exception:'private-error'});
  const body=await readFile(path,'utf8');
  for(const value of ['secret-text','private.invalid','private-selector','/private/file','private-error']) assert(!body.includes(value));
  assert.equal(ledger.summaries('B').length,0);
});
test('invalid journal, false resolved proof and duplicate IDs fail closed',async t=>{
  const {path,ledger}=await fixture(t);const r=await ledger.begin(meta);
  const original=JSON.parse(await readFile(path,'utf8'));
  for(const data of [{version:2,records:[]},{version:1,records:[{...r,state:'resolved'}]},{...original,records:[...original.records,...original.records]}]) {
    await writeFile(path,JSON.stringify(data),{mode:0o600});
    await assert.rejects(new OperationLedger({path}).load(),/invalid/);
  }
});
test('unsafe journal permissions and symlink destinations fail before dispatch',async t=>{
  const {dir,path,ledger}=await fixture(t);await ledger.begin(meta);await chmod(path,0o644);
  await assert.rejects(new OperationLedger({path}).load(),/invalid/);
  await rm(path);const target=join(dir,'target');await writeFile(target,'{}',{mode:0o600});await symlink(target,path);
  await assert.rejects(new OperationLedger({path}).load(),/invalid/);
});
test('unsafe directory fails before journal creation',async t=>{
  const {dir}=await fixture(t);const unsafe=join(dir,'unsafe');await mkdir(unsafe,{mode:0o755});await chmod(unsafe,0o755);
  await assert.rejects(new OperationLedger({path:join(unsafe,'journal.json')}).load(),/Unsafe/);
});
test('write failure prevents a client call or silent recovery',async t=>{
  const {ledger}=await fixture(t);ledger.save=async()=>{ledger.error=true;throw new Error('Synthetic journal failure');};
  const b=new ExtensionBrowserBackend({recoveryMode:'verified-only',recoveryLedger:ledger});
  b.diagnostic=()=>{};b.prepare=async()=>{b.connected=true;return {pages:[{tabId:7}]};};
  b.client={callTool:()=>assert.fail('journal failure must prevent MCP dispatch')};
  await assert.rejects(b.handle('/tabs',{action:'switch',tabId:7},'A'),/journal failure/);
  assert(b.quarantine);assert.equal(b.recoveryState,'blocked-needs-supervision');
});
test('startup fence and metadata release never initiate a browser connection',async t=>{
  const {path,ledger}=await fixture(t);await ledger.begin(meta);
  const b=new ExtensionBrowserBackend({recoveryMode:'manual-only',recoveryLedger:new OperationLedger({path})});
  b.prepare=b.init=async()=>assert.fail('unresolved boot evidence must not contact Chrome');
  const status=await b.handle('/status',{},'B');
  assert(status.daemon.quarantined);assert(status.daemon.inventoryStale);assert.equal(status.daemon.recovery.operations.length,0);
  await assert.rejects(b.handle('/open',{url:'about:blank'},'B'),/quarantined/);
  await b.handle('/close',{all:true},'B');assert(b.quarantine);
});

test('kernel writer lock excludes competing daemons and releases without deleting evidence',async t=>{
  const {path,ledger}=await fixture(t);const r=await ledger.begin(meta);
  await ledger.receipt(r,complete(r));await ledger.state(r,'resolved');
  const competing=new OperationLedger({path});await competing.load();
  await assert.rejects(competing.begin(meta),/writer unavailable|unsafe/);await competing.close();
  await ledger.close();
  const next=new OperationLedger({path});
  try {const pending=await next.begin({...meta,sessionId:'B'});assert.equal(next.unresolved()[0].id,pending.id);}
  finally {await next.close();}
});

test('writer loss prevents further persistence/dispatch while old pending evidence survives',async t=>{
  const {path,ledger}=await fixture(t);const r=await ledger.begin(meta);
  const child=ledger.lockProcess;
  await new Promise(resolve=>{child.once('exit',resolve);child.kill('SIGKILL');});
  await assert.rejects(ledger.receipt(r,complete(r)),/write failed/);
  assert.equal(ledger.proven(r),false);
  const restored=new OperationLedger({path});await restored.load();assert.equal(restored.unresolved().length,1);
  await assert.rejects(restored.begin(meta),/Unresolved/);
});

for(const phase of ['registered','handler-entered','snippet-terminal','terminal-unresolved','unknown','resolved']) {
  test(`abrupt child exit preserves journal safety at ${phase}`,async t=>{
    const {path}=await fixture(t);
    await assert.rejects(exec(process.execPath,[new URL('./test-execution-gate-fixture.mjs',import.meta.url).pathname,'crash-fixture',phase,path],{timeout:8000}),error=>error.code===23);
    const restored=new OperationLedger({path});await restored.load();
    assert.equal(restored.unresolved().length,phase==='resolved'?0:1);
    if(phase!=='resolved') await assert.rejects(restored.begin(meta),/Unresolved/);
  });
}
